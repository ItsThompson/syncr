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

# FastAPI resolves this function's annotations at RUNTIME to build the dependency graph, and
# these names are only reachable from an annotation, so under TYPE_CHECKING they would resolve to
# a NameError while the app is being constructed.
from syncr_api.accounts.injection import PrincipalDep, TransactionDep  # noqa: TC001
from syncr_api.anchors.reconcile import AnchorReconciler
from syncr_api.anchors.repository import AnchorRepository
from syncr_api.anchors.type_repository import AnchorTypeRepository
from syncr_api.calendars.config import HORIZON_DAYS_DEFAULT
from syncr_api.calendars.feeds import HttpFeedFetcher, create_feed_client
from syncr_api.calendars.ics_adapter import IcsAdapter
from syncr_api.calendars.repository import CalendarSourceRepository
from syncr_api.calendars.service import CalendarSourceService
from syncr_api.calendars.sync import SourceSyncer
from syncr_api.core.clock import utc_now
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.repository import OperationRepository
from syncr_api.user_settings.repository import SettingsRepository, TravelOverrideRepository
from syncr_api.user_settings.solve_inputs import TrackedWeekInputVersions
from syncr_api.user_settings.zone_reading import as_domain, zone_profile
from syncr_domain.intervals import Interval

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_api.core.principal import Principal
    from syncr_domain.zones import ZoneProfile


async def get_feed_client() -> AsyncIterator[httpx.AsyncClient]:
    """One HTTP client for the life of one request, closed when it ends."""
    async with create_feed_client() as client:
        yield client


type FeedClientDep = Annotated[httpx.AsyncClient, Depends(get_feed_client)]


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
    principal: PrincipalDep, transaction: TransactionDep, client: FeedClientDep
) -> CalendarSourceService:
    """The calendar-source service, wired for this request and scoped to this tenant."""
    sources = CalendarSourceRepository(transaction, principal.tenant_id)
    now = utc_now()
    adapter = IcsAdapter(
        fetcher=HttpFeedFetcher(client),
        profile=await read_zone_profile(transaction, principal),
        horizon=await read_ingest_horizon(sources, now=now),
        clock=utc_now,
    )
    return CalendarSourceService(
        sources=sources,
        syncer=SourceSyncer(
            sources=sources,
            operations=OperationRepository(transaction, principal.tenant_id),
            adapter=adapter,
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
    )


type CalendarSourceServiceDep = Annotated[
    CalendarSourceService, Depends(get_calendar_source_service)
]
