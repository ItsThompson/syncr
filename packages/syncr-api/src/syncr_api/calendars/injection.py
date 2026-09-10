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
projection bound being configured. The plan horizon maintainer reads the same figure through
``horizons.read_horizon_days``, so the span a calendar is read over and the weeks that get planned
cannot disagree.

**The anchor reconciler's seam is composed here.** ``SourceSyncer`` reconciles anchors between the
fetch and the sync-state write, and it takes the reconciler as a protocol it declares rather than
as an import of the anchor package. This is the request-side composition of that seam; the worker's
is in ``calendars/runner.py``. The reconciler is handed the week input counter and the home zone,
because a pass that moved a commitment invalidates the weeks it moved it in.

**The solve those invalidated weeks need is composed here too**, from the same version rows and this
deployment's debounce window, because a bump nothing acts on leaves the week's plan describing
occupancy the feed has moved.

The HTTP client is per request rather than shared through application state. A request forces one
source at a time, so pooling would buy one connection's worth of setup while making the client's
lifecycle something the app has to own; the worker, which polls several feeds per tick, keeps one
client for the tick.
"""

from __future__ import annotations

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
from syncr_api.calendars.config import GOOGLE, ICS
from syncr_api.calendars.feed_notices import StaleFeedReading
from syncr_api.calendars.feeds import HttpFeedFetcher, create_feed_client
from syncr_api.calendars.google_client import GoogleCalendarClient
from syncr_api.calendars.google_events import GoogleEventWriter, WritesUnavailable
from syncr_api.calendars.google_read_adapter import GoogleReadAdapter
from syncr_api.calendars.google_transport import HttpxGoogleTransport, create_google_read_client
from syncr_api.calendars.google_write_adapter import GoogleWriteTargetAdapter
from syncr_api.calendars.google_writes import HttpxGoogleWriteTransport
from syncr_api.calendars.horizons import read_ingest_horizon
from syncr_api.calendars.ics_adapter import IcsAdapter
from syncr_api.calendars.remote_calendars import UnconfiguredCalendarReader
from syncr_api.calendars.repository import CalendarSourceRepository
from syncr_api.calendars.service import CalendarSourceService
from syncr_api.calendars.solve_requests import TrackedWeekSolves
from syncr_api.calendars.sync import SourceSyncer
from syncr_api.conflicts.ingest import IngestConflicts
from syncr_api.core.clock import utc_now
from syncr_api.core.session_mode import SessionModeDep  # noqa: TC001
from syncr_api.google_account.injection import build_access_tokens
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.injection import build_solve_coordinator, configured_debounce
from syncr_api.solving.lifecycle import OperationLifecycle
from syncr_api.solving.repository import OperationRepository
from syncr_api.user_settings.repository import SettingsRepository, TravelOverrideRepository
from syncr_api.user_settings.solve_inputs import TrackedWeekInputVersions
from syncr_api.user_settings.zone_reading import as_domain, zone_profile

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_api.calendars.adapters import CalendarAdapter
    from syncr_api.calendars.config import CalendarProvider
    from syncr_api.calendars.google_events import EventWriting
    from syncr_api.calendars.remote_calendars import RemoteCalendarReader
    from syncr_api.core.principal import Principal
    from syncr_api.core.settings import ServiceSettings
    from syncr_api.google_account.tokens import AccessTokenSource
    from syncr_domain.identifiers import TenantId
    from syncr_domain.intervals import Interval
    from syncr_domain.zones import ZoneProfile

# Why a deployment with no Google client cannot write. The same condition the connect flow reports,
# stated for the write side: without a client id there is no account, so there is no calendar to
# write to and nothing about the plan is wrong.
NOT_CONFIGURED_REASON = (
    "This deployment has no Google OAuth client, so there is no calendar for syncr to write the "
    "plan to. Every ICS feed still syncs and the plan is still correct in syncr."
)

# Why the adapter a REQUEST composes will not write. Not a failure and not a fault: a request has no
# business writing a calendar at all, because the projection is network-bound, retryable, and
# destructive, so it runs in the worker and never sits on a request. Holding the refusing arm here
# makes that structural rather than a convention every future route has to remember.
READS_ONLY = WritesUnavailable(
    reason=(
        "This is a read of your calendars, and syncr only writes the plan from its background "
        "worker. Nothing was written and nothing is wrong."
    )
)

# Why a deployment that has not been armed will not write. The destructive reconciliation removes
# anything inside its horizon that syncr does not intend, including events the user created by hand.
# It has met the real Google API, from the marked live suite against a development calendar; it has
# never run from an armed deployment over a horizon of real plan blocks. So it is off until an
# operator says otherwise, and the refusal is loud rather than silent.
UNARMED = WritesUnavailable(
    reason=(
        "syncr is not writing the plan to your Google calendar, because writing is switched off in "
        "this deployment. Reading your calendars still works and the plan itself is current: only "
        "the copy on Google is not being updated. An operator turns it on with "
        "GOOGLE_PROJECTION_WRITES=true."
    )
)


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
    """The adapters this deployment can READ with, and the reader that lists an account.

    **A deployment with no Google client gets no Google adapter**, which is what makes the service's
    rule true rather than nominal: a forced sync on a Google source is refused with a stated reason
    instead of recording a transport failure against a calendar that is fine.

    **The Google adapter these compose cannot write**, because it holds the refusing arm of the
    write seam. The projection composes its own, in the worker, with a writer in it.

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
    adapter = GoogleReadAdapter(client=client, profile=profile, horizon=horizon, clock=utc_now)
    return {ICS: ics, GOOGLE: adapter}, adapter


def build_event_writing(
    settings: ServiceSettings, *, writes: httpx.AsyncClient, tokens: AccessTokenSource
) -> EventWriting:
    """The write side of the projection: a writer, or the stated reason there is none.

    Two conditions, and each answers with the sentence a user reads rather than a boolean: a
    deployment with no Google client has nothing to write to, and a deployment that has not been
    armed will not write. Both are checked here, once, so the adapter holds one value and the
    reconciliation asks it before it spends a request.
    """
    if not settings.google_oauth_client_id:
        return WritesUnavailable(reason=NOT_CONFIGURED_REASON)
    if not settings.google_projection_writes:
        return UNARMED
    return GoogleEventWriter(transport=HttpxGoogleWriteTransport(writes), tokens=tokens)


def build_write_target_adapter(
    settings: ServiceSettings,
    session: AsyncSession,
    tenant_id: TenantId,
    *,
    reads: httpx.AsyncClient,
    writes: httpx.AsyncClient,
    profile: ZoneProfile,
    horizon: Interval,
) -> GoogleWriteTargetAdapter:
    """The adapter the projection reconciles the write target through.

    A second adapter rather than the read map's, and the difference is the whole point: this one
    holds a writer and that one holds the refusal. Composed only by the worker's projection duty,
    so the ability to delete a calendar is reachable from exactly one place.

    The horizon is a constructor argument because the adapter applies it: the existing events are
    read over it, and it is the bound past which nothing is removed.

    **One token source, shared by the read and the write.** It caches the access token for its own
    lifetime, so a reconciliation of two hundred events costs one refresh; two sources would cost
    two, and a second request to the token endpoint per pass buys nothing.
    """
    tokens = build_access_tokens(settings, session, tenant_id, reads)
    return GoogleAdapter(
        client=GoogleCalendarClient(transport=HttpxGoogleTransport(reads), tokens=tokens),
        profile=profile,
        horizon=horizon,
        clock=utc_now,
        writes=build_event_writing(settings, writes=writes, tokens=tokens),
    )


async def read_zone_profile(session: AsyncSession, principal: Principal) -> ZoneProfile:
    """The tenant's home zone and travel overrides, as the domain value zones resolve against."""
    return await read_zone_profile_of(session, principal.tenant_id)


async def read_zone_profile_of(session: AsyncSession, tenant_id: TenantId) -> ZoneProfile:
    """The same profile, for the worker, which holds a tenant rather than a principal.

    Two entry points over one reading, so the zone a feed's floating time resolves in and the zone a
    projection's day segments break at cannot come to differ.
    """
    settings = await SettingsRepository(session, tenant_id).read()
    overrides = await TravelOverrideRepository(session, tenant_id).list_all()
    return zone_profile(settings.home_zone, as_domain(overrides))


async def get_calendar_source_service(
    request: Request,
    principal: PrincipalDep,
    transaction: TransactionDep,
    client: FeedClientDep,
    google: GoogleReadClientDep,
    session_mode: SessionModeDep,
) -> CalendarSourceService:
    """The calendar-source service, wired for this request and scoped to this tenant."""
    settings: ServiceSettings = request.app.state.settings
    sources = CalendarSourceRepository(transaction, principal.tenant_id)
    now = utc_now()
    profile = await read_zone_profile(transaction, principal)
    horizon = await read_ingest_horizon(sources, now=now)
    adapters, remote_calendars = build_adapters(
        settings,
        transaction,
        principal.tenant_id,
        feeds=client,
        google=google,
        profile=profile,
        horizon=horizon,
    )
    # One counter for the request, shared by the horizon change and the anchor reconciliation.
    # Both invalidate weeks in this transaction and neither holds state, so a second instance
    # would only be a second name for one row.
    version_rows = WeekInputVersionRepository(transaction, principal.tenant_id)
    versions = TrackedWeekInputVersions(version_rows, clock=utc_now)
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
                versions=versions,
                home_zone=profile.home_zone,
            ),
            collisions=IngestConflicts(transaction, principal.tenant_id),
            solves=TrackedWeekSolves(
                version_rows,
                build_solve_coordinator(
                    transaction,
                    principal.tenant_id,
                    clock=utc_now,
                    debounce=configured_debounce(request),
                ),
                # A mutation here can move several weeks' readings, and the solve of each is
                # recorded with what this request stated about the weekly session.
                session_mode_active=session_mode,
            ),
            clock=utc_now,
        ),
        versions=versions,
        clock=utc_now,
        remote_calendars=remote_calendars,
        feeds=StaleFeedReading(
            AnchorRepository(transaction, principal.tenant_id), profile=profile, horizon=horizon
        ),
    )


type CalendarSourceServiceDep = Annotated[
    CalendarSourceService, Depends(get_calendar_source_service)
]
