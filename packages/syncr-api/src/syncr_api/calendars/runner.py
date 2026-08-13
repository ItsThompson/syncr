"""The calendar poll the worker runs: one tenant at a time, one pass per interval.

Feeds are polled on a schedule rather than on demand, because an ICS publisher's own refresh is
measured in hours and a user who never opens Settings still needs their timetable current.

**The pass is per tenant, and that is deliberate.** Every statement over a table that holds a
plan carries its tenant, with no exception for maintenance, so the runner enumerates tenants and
builds one scoped repository for each rather than issuing one unscoped read. The cost is a query
per tenant per tick on a deployment whose tenant count is one; what it buys is that "every scoped
statement is scoped" stays a property of the code rather than a property with a footnote.

**Due-ness lives on the source, not in the runner.** A restart therefore does not reset every
feed's schedule, and a source added mid-interval is polled on the next tick rather than waiting
out an interval it was not present for. The runner's own interval only decides how often it looks.

**The zone profile and the horizon are read per tenant.** A floating time resolves in the zone
the user is in on that date, and the horizon is the write target's, so both are the tenant's
rather than the deployment's.

**Which providers a tick can read comes from the deployment.** The adapter map is composed from this
process's settings, so a worker with no Google credentials polls feeds and enumerates no Google
source at all, rather than attempting a read nothing could satisfy and recording a failure against a
calendar that is fine.

**One transaction per tenant.** A publisher that hangs must not hold every other tenant's sync
state uncommitted behind it, and a tenant whose feed failed still has its attempt recorded. The
anchor reconciliation a pass performs is inside that same transaction, so a tenant's anchors, its
sync state, the input versions its moved commitments invalidated, and the solves those versions ask
for either all land or none do.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from prometheus_client import Counter

from syncr_api.accounts.repository import TenantRepository
from syncr_api.anchors.reconcile import AnchorReconciler
from syncr_api.anchors.repository import AnchorRepository
from syncr_api.anchors.type_repository import AnchorTypeRepository
from syncr_api.calendars.feeds import create_feed_client
from syncr_api.calendars.google_transport import create_google_read_client
from syncr_api.calendars.horizons import read_ingest_horizon
from syncr_api.calendars.injection import build_adapters
from syncr_api.calendars.repository import CalendarSourceRepository
from syncr_api.calendars.solve_requests import TrackedWeekSolves
from syncr_api.calendars.sync import SourceSyncer, SyncPass
from syncr_api.conflicts.ingest import IngestConflicts
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.injection import build_solve_coordinator, debounce_window
from syncr_api.solving.lifecycle import OperationLifecycle
from syncr_api.solving.repository import OperationRepository
from syncr_api.user_settings.repository import SettingsRepository, TravelOverrideRepository
from syncr_api.user_settings.solve_inputs import TrackedWeekInputVersions
from syncr_api.user_settings.zone_reading import as_domain, zone_profile
from syncr_common.logging import get_logger
from syncr_common.metrics import REGISTRY, measured

if TYPE_CHECKING:
    from datetime import datetime, timedelta

    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_api.core.clock import Clock
    from syncr_api.worker.main import WorkerContext
    from syncr_domain.identifiers import TenantId

_log = get_logger("syncr.calendars")

# A tenant whose pass raised. Counted rather than only logged, because the tick reports a tally and
# a contained fault answers with an empty one: without this, a tenant failing every tick would leave
# every counter at zero while the duty reported healthy. `measured` cannot see it either, since the
# whole point of the boundary is that the decorated call no longer raises.
TENANT_POLL_FAILURES = Counter(
    "syncr_calendar_tenant_poll_failures_total",
    "Calendar sync passes that raised for one tenant and were contained.",
    registry=REGISTRY,
)


class CalendarSyncRunner:
    """One duty on the worker loop: poll every tenant's due feeds, or return immediately.

    A callable object rather than a closure, so the loop's name lookup finds a stable name for its
    failure metric and so a test can read when the poll is next due.

    The FIRST tick schedules rather than polls. A process that restarts often would otherwise
    fetch every feed on every boot, which is a burst of requests at a publisher for no new data.
    """

    __name__ = "calendar_sync"

    def __init__(self, *, interval: timedelta, clock: Clock) -> None:
        self._interval = interval
        self._clock = clock
        self._next_due_at: datetime | None = None

    @property
    def next_due_at(self) -> datetime | None:
        """When this runner will next do work, or ``None`` before its first tick."""
        return self._next_due_at

    async def __call__(self, context: WorkerContext) -> None:
        now = self._clock()
        if self._next_due_at is None or now < self._next_due_at:
            self._next_due_at = self._next_due_at or now + self._interval
            return
        self._next_due_at = now + self._interval
        # One client per transport for the whole tick, so several feeds on one host reuse a
        # connection and every Google read shares one pool.
        async with create_feed_client() as feeds, create_google_read_client() as google:
            await self.poll(context, feeds, google, now=now)

    @measured("calendar_sync")
    async def poll(
        self,
        context: WorkerContext,
        feeds: httpx.AsyncClient,
        google: httpx.AsyncClient,
        *,
        now: datetime,
    ) -> SyncPass:
        """One pass over every tenant, each in its own transaction and its own failure boundary."""
        async with context.database.sessionmaker() as reader:
            tenants = await TenantRepository(reader).list_ids()

        total = SyncPass()
        for tenant_id in tenants:
            tally = await self._polled_tenant(context, feeds, google, tenant_id, now=now)
            total = SyncPass(
                attempted=total.attempted + tally.attempted,
                succeeded=total.succeeded + tally.succeeded,
                events=total.events + tally.events,
                rejected=total.rejected + tally.rejected,
            )
        if total.attempted:
            _log.info("calendars.poll.completed", **total.as_log_fields())
        return total

    async def _polled_tenant(
        self,
        context: WorkerContext,
        feeds: httpx.AsyncClient,
        google: httpx.AsyncClient,
        tenant_id: TenantId,
        *,
        now: datetime,
    ) -> SyncPass:
        """One tenant's pass, in its own transaction, with its own faults contained.

        Answers with an empty tally on a fault rather than re-raising, so the tenants after this
        one are still polled. The failure is counted and named HERE rather than left to the worker
        loop's handler, which isolates one DUTY and would therefore drop every remaining tenant.
        """
        try:
            async with context.database.sessionmaker() as session, session.begin():
                return await self._poll_tenant(context, session, feeds, google, tenant_id, now=now)
        except Exception:  # noqa: BLE001 - one tenant's fault must not stop the others
            TENANT_POLL_FAILURES.inc()
            _log.exception("calendars.poll.tenant_failed", tenant_id=str(tenant_id))
            return SyncPass()

    async def _poll_tenant(
        self,
        context: WorkerContext,
        session: AsyncSession,
        feeds: httpx.AsyncClient,
        google: httpx.AsyncClient,
        tenant_id: TenantId,
        *,
        now: datetime,
    ) -> SyncPass:
        sources = CalendarSourceRepository(session, tenant_id)
        settings = await SettingsRepository(session, tenant_id).read()
        overrides = await TravelOverrideRepository(session, tenant_id).list_all()
        version_rows = WeekInputVersionRepository(session, tenant_id)
        adapters, _remote_calendars = build_adapters(
            context.settings,
            session,
            tenant_id,
            feeds=feeds,
            google=google,
            profile=zone_profile(settings.home_zone, as_domain(overrides)),
            horizon=await read_ingest_horizon(sources, now=now),
        )
        syncer = SourceSyncer(
            sources=sources,
            operations=OperationLifecycle(OperationRepository(session, tenant_id), self._clock),
            adapters=adapters,
            anchors=AnchorReconciler(
                AnchorRepository(session, tenant_id),
                AnchorTypeRepository(session, tenant_id),
                versions=TrackedWeekInputVersions(version_rows, clock=self._clock),
                home_zone=settings.home_zone,
            ),
            collisions=IngestConflicts(session, tenant_id),
            solves=TrackedWeekSolves(
                version_rows,
                build_solve_coordinator(
                    session,
                    tenant_id,
                    clock=self._clock,
                    debounce=debounce_window(context.settings.solve_debounce_ms),
                ),
            ),
            clock=self._clock,
        )
        return await syncer.sync_due(now=now)
