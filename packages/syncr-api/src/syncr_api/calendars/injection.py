"""The dependencies the calendar-source routes declare.

The repositories are scoped to the principal's tenant HERE, at the one point where the principal
is available and before the service exists. That is what makes the scope structural: there is no
code path that builds one of these without a tenant, so no statement they compose can reach
another tenant's rows.

This is also where the ICS adapter is composed, and it is the only place that decides two things
the adapter cannot decide for itself.

**The zone profile** comes from the tenant's stored settings and travel overrides, so a floating
time in a feed resolves in the zone the user is actually in on that date. Reading it here rather
than inside the adapter keeps the adapter a pure function of a feed and a profile.

**The horizon** is the write target's ``horizon_days`` when one is set, and the default otherwise.
A tenant that has not designated a write target still reads anchors, so ingest cannot wait on a
projection bound being configured.

**The anchor reconciler's seam is composed here.** ``SourceSyncer`` reconciles anchors between the
fetch and the sync-state write, and it takes the reconciler as a protocol it declares rather than
as an import of the anchor package. This is the request-side composition of that seam; the worker's
is in ``calendars/runner.py``.

The HTTP client is per request rather than shared through application state. A request forces one
source at a time, so pooling would buy one connection's worth of setup while making the client's
lifecycle something the app has to own; the worker, which polls several feeds per tick, keeps one
client for the tick.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Annotated

import httpx
from fastapi import Depends

# FastAPI evaluates a dependency's annotations at runtime, so the request type stays a runtime
# import: the settings this deployment was built with are read off the application.
from starlette.requests import Request  # noqa: TC002

# FastAPI resolves this function's annotations at RUNTIME to build the dependency graph, and
# these names are only reachable from an annotation, so under TYPE_CHECKING they would resolve to
# a NameError while the app is being constructed.
from syncr_api.accounts.injection import PrincipalDep, TransactionDep  # noqa: TC001
from syncr_api.anchors.reconcile import AnchorReconciler
from syncr_api.anchors.repository import AnchorRepository
from syncr_api.anchors.type_repository import AnchorTypeRepository
from syncr_api.calendars.config import GOOGLE, HORIZON_DAYS_DEFAULT, ICS
from syncr_api.calendars.feeds import HttpFeedFetcher, create_feed_client
from syncr_api.calendars.google_adapter import GoogleAdapter
from syncr_api.calendars.google_client import GoogleCalendarClient
from syncr_api.calendars.google_transport import HttpxGoogleTransport, create_google_read_client
from syncr_api.calendars.ics_adapter import IcsAdapter
from syncr_api.calendars.remote_calendars import UnconfiguredCalendarReader
from syncr_api.calendars.repository import CalendarSourceRepository
from syncr_api.calendars.service import CalendarSourceService
from syncr_api.calendars.sync import SourceSyncer
from syncr_api.core.clock import utc_now
from syncr_api.google_account.injection import build_access_tokens
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.lifecycle import OperationLifecycle
from syncr_api.solving.repository import OperationRepository
from syncr_api.user_settings.repository import SettingsRepository, TravelOverrideRepository
from syncr_api.user_settings.solve_inputs import TrackedWeekInputVersions
from syncr_api.user_settings.zone_reading import as_domain, zone_profile
from syncr_domain.intervals import Interval

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_api.calendars.adapters import CalendarAdapter
    from syncr_api.calendars.config import CalendarProvider
    from syncr_api.calendars.remote_calendars import RemoteCalendarReader
    from syncr_api.core.principal import Principal
    from syncr_api.core.settings import ServiceSettings
    from syncr_domain.identifiers import TenantId
    from syncr_domain.zones import ZoneProfile


async def get_feed_client() -> AsyncIterator[httpx.AsyncClient]:
    """One HTTP client for the life of one request, closed when it ends."""
    async with create_feed_client() as client:
        yield client


type FeedClientDep = Annotated[httpx.AsyncClient, Depends(get_feed_client)]


async def get_google_read_client() -> AsyncIterator[httpx.AsyncClient]:
    """One HTTP client for Google's API for the life of one request, closed when it ends.

    Separate from the feed client because the two answer to different bounds: a feed read is capped
    at a size and a whole-read timeout of its own, and a Google page read is capped at another.
    """
    async with create_google_read_client() as client:
        yield client


type GoogleReadClientDep = Annotated[httpx.AsyncClient, Depends(get_google_read_client)]


def build_adapters(
    settings: ServiceSettings,
    session: AsyncSession,
    tenant_id: TenantId,
    *,
    feeds: httpx.AsyncClient,
    google: httpx.AsyncClient,
    profile: ZoneProfile,
    horizon: Interval,
) -> tuple[Mapping[CalendarProvider, CalendarAdapter], RemoteCalendarReader]:
    """The adapters this deployment can read with, and the reader that lists an account.

    **A deployment with no Google client gets no Google adapter**, which is what makes the service's
    rule true rather than nominal: a forced sync on a Google source is refused with a stated reason
    instead of recording a transport failure against a calendar that is fine.

    The ICS adapter is always present. ICS needs no credential from anybody, which is the whole
    reason it is the strategic ingest path.
    """
    ics = IcsAdapter(
        fetcher=HttpFeedFetcher(feeds), profile=profile, horizon=horizon, clock=utc_now
    )
    if not settings.google_oauth_client_id:
        return {ICS: ics}, UnconfiguredCalendarReader()
    client = GoogleCalendarClient(
        transport=HttpxGoogleTransport(google),
        tokens=build_access_tokens(settings, session, tenant_id, google),
    )
    adapter = GoogleAdapter(client=client, profile=profile, horizon=horizon, clock=utc_now)
    return {ICS: ics, GOOGLE: adapter}, adapter


async def read_zone_profile(session: AsyncSession, principal: Principal) -> ZoneProfile:
    """The tenant's home zone and travel overrides, as the domain value zones resolve against."""
    settings = await SettingsRepository(session, principal.tenant_id).read()
    overrides = await TravelOverrideRepository(session, principal.tenant_id).list_all()
    return zone_profile(settings.home_zone, as_domain(overrides))


async def read_ingest_horizon(sources: CalendarSourceRepository, *, now: datetime) -> Interval:
    """How far ahead recurrence is expanded: the write target's horizon, else the default.

    From ``now`` rather than from the start of the week, because an occurrence that began before
    now and runs into it is still occupancy, and the parser widens the lower bound by each
    event's own length to catch exactly that.
    """
    target = await sources.write_target()
    days = HORIZON_DAYS_DEFAULT if target is None else target.horizon_days or HORIZON_DAYS_DEFAULT
    return Interval(now, now + timedelta(days=days))


async def get_calendar_source_service(
    request: Request,
    principal: PrincipalDep,
    transaction: TransactionDep,
    client: FeedClientDep,
    google: GoogleReadClientDep,
) -> CalendarSourceService:
    """The calendar-source service, wired for this request and scoped to this tenant."""
    settings: ServiceSettings = request.app.state.settings
    sources = CalendarSourceRepository(transaction, principal.tenant_id)
    now = utc_now()
    adapters, remote_calendars = build_adapters(
        settings,
        transaction,
        principal.tenant_id,
        feeds=client,
        google=google,
        profile=await read_zone_profile(transaction, principal),
        horizon=await read_ingest_horizon(sources, now=now),
    )
    return CalendarSourceService(
        sources=sources,
        syncer=SourceSyncer(
            sources=sources,
            operations=OperationLifecycle(
                OperationRepository(transaction, principal.tenant_id), utc_now
            ),
            adapters=adapters,
            anchors=AnchorReconciler(
                AnchorRepository(transaction, principal.tenant_id),
                AnchorTypeRepository(transaction, principal.tenant_id),
            ),
            clock=utc_now,
        ),
        versions=TrackedWeekInputVersions(
            WeekInputVersionRepository(transaction, principal.tenant_id), clock=utc_now
        ),
        clock=utc_now,
        remote_calendars=remote_calendars,
    )


type CalendarSourceServiceDep = Annotated[
    CalendarSourceService, Depends(get_calendar_source_service)
]
