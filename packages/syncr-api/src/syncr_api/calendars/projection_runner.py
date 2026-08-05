"""The worker duty that drains the projection queue: one reconciliation per tenant that needs one.

The projection runs here and never on a request. It is network-bound, retryable, and destructive, so
it must not sit on a request; and the adapter a request composes holds the refusing arm of the write
seam, so it structurally cannot.

```
tick
  ├── for each tenant:
  │     TRANSACTION  claim every due projection                      committed before any write
  │     SESSION      read the target, the plans, the periods, then reconcile
  │     TRANSACTION  record the attempt on the write target, finish every claimed operation
  └── nothing due → return, having read one row per tenant
```

**Several queued projections are satisfied by ONE reconciliation.** A projection is idempotent over
the whole horizon: it makes the target match the live plan, whatever it held before. So a weekly
session that appended twelve revisions costs one destructive write rather than twelve, which is the
other half of the rule that a projection is enqueued only when the live plan changed. Each claimed
operation is finished with the outcome of that one write, which is the honest answer: what each of
them asked for is what it did.

**The claim is committed before the write, and everything after it is one transaction.** The claim
commits first so a worker that dies mid-reconciliation leaves its operations ``running`` for the
reaper rather than for nobody. The rest of the pass -- the reads, the token refresh the token source
performs, the write, the sync state and the operation transitions -- is one transaction, exactly as
a calendar poll's tenant pass is, so a projection can never be observed as succeeded with its target
looking untried. The cost is a transaction open across the provider, bounded by the reconciliation's
own deadline; the alternative loses the token layer's record of a dead grant, which is the one write
that raises the loudest notice in the product.

**One failure boundary per tenant.** A tenant whose drain raised is counted and the tenants after it
still run. Counted rather than only logged, because a contained fault answers with a tally: without
the counter, a tenant failing every tick would leave every metric at zero while the duty reported
healthy, which is the alert inversion this epic has already shipped twice.

**A tenant with no write target drains its queue and writes nothing.** There is no calendar to
project onto, by the user's own configuration, so each operation succeeds having done what it could:
the same answer a forced sync gives for an excluded source. No notice is raised, because a tenant
that has not designated a write target is not a tenant whose writes are failing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from prometheus_client import Counter

from syncr_api.accounts.repository import TenantRepository
from syncr_api.calendars.config import GOOGLE
from syncr_api.calendars.google_transport import create_google_read_client
from syncr_api.calendars.google_writes import create_google_write_client
from syncr_api.calendars.injection import (
    build_write_target_adapter,
    read_horizon_days,
    read_zone_profile_of,
)
from syncr_api.calendars.projection_errors import ProjectionFailed
from syncr_api.calendars.projection_metrics import (
    FAILED,
    PROJECTION_DURATION,
    PROJECTION_EVENTS,
    SUCCEEDED,
)
from syncr_api.calendars.projection_state import (
    recorded_projection,
    recorded_projection_failure,
)
from syncr_api.calendars.projection_writer import ProjectionWriter
from syncr_api.calendars.repository import CalendarSourceRepository
from syncr_api.horizon.weeks import horizon_span, horizon_weeks
from syncr_api.offplan.repository import OffPlanPeriodRepository
from syncr_api.plans.repository import PlanRepository
from syncr_api.solving.config import PROJECTION
from syncr_api.solving.errors import IllegalTransition
from syncr_api.solving.lifecycle import OperationLifecycle
from syncr_api.solving.outcomes import Failed, Succeeded
from syncr_api.solving.queue import OperationQueue
from syncr_api.solving.repository import OperationRepository
from syncr_api.user_settings.zone_reading import local_date
from syncr_common.logging import get_logger
from syncr_common.metrics import REGISTRY, measured

if TYPE_CHECKING:
    from datetime import datetime

    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_api.calendars.projection import ReconcileResult
    from syncr_api.calendars.records import CalendarSourceRecord, SyncStateRecord
    from syncr_api.core.clock import Clock
    from syncr_api.solving.outcomes import Outcome
    from syncr_api.solving.records import OperationRecord
    from syncr_api.worker.main import WorkerContext
    from syncr_domain.identifiers import TenantId

_log = get_logger("syncr.calendars")

# A tenant whose drain raised outside the reconciliation's own stated failures. Counted rather than
# only logged, because the boundary exists to stop the exception, and a fault that answers with a
# tally is invisible unless something counts it. `18-observability.md` defines no alert on this
# family, which ticket 54 owns.
TENANT_PROJECTION_FAILURES = Counter(
    "syncr_projection_tenant_failures_total",
    "Projection drains that raised for one tenant and were contained.",
    registry=REGISTRY,
)

# Why nothing was written when the tenant has designated no write target. Not an error: the queue is
# drained and the operations succeed, because there is no calendar to project onto by the user's own
# configuration.
NO_WRITE_TARGET = (
    "no calendar is designated as the one syncr writes the plan to, so there was nothing to "
    "project onto"
)

# Why nothing was written when the designated calendar is one syncr cannot write to. Assigning the
# write-target role does not currently require a Google source, so an ICS feed can hold it and
# cannot be written to: a feed is published by somebody else and has no API to write through. Stated
# rather than crashed, and whether the role assignment should refuse it is ticket 1301.
UNWRITABLE_TARGET = (
    "the calendar designated as syncr's write target is a {provider} feed, and the plan can only "
    "be written to a Google calendar: a feed is published by somebody else and has no API to write "
    "through. Designate a Google calendar in Settings."
)


class ProjectionRunner:
    """One duty on the worker loop: project every tenant whose queue holds a projection.

    A callable object rather than a closure, so the loop's name lookup finds a stable name for its
    failure metric and so a test can drive one pass directly.

    Unlike the calendar poll and the horizon maintainer this has no interval of its own and no
    first tick that only schedules: the queue IS the schedule. A tick with an empty queue costs one
    indexed read per tenant, and a projection enqueued by a solve has to reach the phone in seconds
    rather than at the next quarter hour.
    """

    __name__ = "projection"

    def __init__(self, *, clock: Clock) -> None:
        self._clock = clock

    async def __call__(self, context: WorkerContext) -> None:
        # One client per direction for the whole tick, so several tenants share one connection pool
        # each way. The two are separate because a read and a write answer to different timeouts.
        async with create_google_read_client() as reads, create_google_write_client() as writes:
            await self.drain(context, reads, writes, now=self._clock())

    async def drain(
        self,
        context: WorkerContext,
        reads: httpx.AsyncClient,
        writes: httpx.AsyncClient,
        *,
        now: datetime,
    ) -> int:
        """One pass over every tenant. Answers how many reconciliations were performed.

        The clients are arguments rather than created here, exactly as the calendar poll's are: the
        tick owns their lifetime, and a test drives the whole composition -- the token refresh, the
        adapter, the diff -- against a transport it controls.
        """
        async with context.database.sessionmaker() as reader:
            tenants = await TenantRepository(reader).list_ids()

        performed = 0
        for tenant_id in tenants:
            performed += await self._drained(context, tenant_id, reads, writes, now=now)
        return performed

    async def _drained(
        self,
        context: WorkerContext,
        tenant_id: TenantId,
        reads: httpx.AsyncClient,
        writes: httpx.AsyncClient,
        *,
        now: datetime,
    ) -> int:
        """One tenant's queue, with its fault contained so the tenants after it still run."""
        try:
            return await self._projected(context, tenant_id, reads, writes, now=now)
        except Exception:  # noqa: BLE001 - one tenant's fault must not stop the others
            TENANT_PROJECTION_FAILURES.inc()
            _log.exception("calendars.projection.tenant_failed", tenant_id=str(tenant_id))
            return 0

    @measured("projection")
    async def _projected(
        self,
        context: WorkerContext,
        tenant_id: TenantId,
        reads: httpx.AsyncClient,
        writes: httpx.AsyncClient,
        *,
        now: datetime,
    ) -> int:
        claimed = await self._claimed(context, tenant_id, now=now)
        if not claimed:
            return 0
        async with context.database.sessionmaker() as session, session.begin():
            return await self._pass(context, session, tenant_id, claimed, reads, writes, now=now)

    async def _pass(
        self,
        context: WorkerContext,
        session: AsyncSession,
        tenant_id: TenantId,
        claimed: tuple[OperationRecord, ...],
        reads: httpx.AsyncClient,
        writes: httpx.AsyncClient,
        *,
        now: datetime,
    ) -> int:
        """One tenant's whole reconciliation, in one transaction, ending in a recorded attempt."""
        target = await CalendarSourceRepository(session, tenant_id).write_target()
        if target is None:
            await self._close(session, tenant_id, claimed, Succeeded())
            _log.info(
                "calendars.projection.skipped", tenant_id=str(tenant_id), reason=NO_WRITE_TARGET
            )
            return 0
        if target.provider != GOOGLE:
            await self._stopped(
                session,
                tenant_id,
                claimed,
                target,
                ProjectionFailed(UNWRITABLE_TARGET.format(provider=target.provider)),
                now=now,
            )
            return 0
        return await self._reconciled(
            context, session, tenant_id, claimed, target, reads, writes, now=now
        )

    async def _reconciled(
        self,
        context: WorkerContext,
        session: AsyncSession,
        tenant_id: TenantId,
        claimed: tuple[OperationRecord, ...],
        target: CalendarSourceRecord,
        reads: httpx.AsyncClient,
        writes: httpx.AsyncClient,
        *,
        now: datetime,
    ) -> int:
        """Read what the write needs, write it, and record the attempt either way.

        The horizon and the week list are derived from one ``today`` and one ``horizon_days``, so
        the span the calendar is reconciled over and the weeks whose plans are read cannot disagree
        about where the horizon ends.
        """
        sources = CalendarSourceRepository(session, tenant_id)
        profile = await read_zone_profile_of(session, tenant_id)
        horizon_days = await read_horizon_days(sources)
        today = local_date(now, profile.home_zone)
        horizon = horizon_span(today=today, horizon_days=horizon_days, zone=profile.home_zone)
        writer = ProjectionWriter(
            target=target,
            adapter=build_write_target_adapter(
                context.settings,
                session,
                tenant_id,
                reads=reads,
                writes=writes,
                profile=profile,
                horizon=horizon,
            ),
            revisions=PlanRepository(session, tenant_id),
            periods=OffPlanPeriodRepository(session, tenant_id),
            profile=profile,
        )
        try:
            result = await writer.project(
                horizon, horizon_weeks(today=today, horizon_days=horizon_days)
            )
        except ProjectionFailed as failure:
            await self._stopped(session, tenant_id, claimed, target, failure, now=now)
            return 0
        _observed(result, outcome=SUCCEEDED)
        await self._record(
            session, tenant_id, claimed, target, recorded_projection(target.sync_state, at=now)
        )
        _log.info(
            "calendars.projection.completed",
            tenant_id=str(tenant_id),
            source_id=str(target.id),
            operation_count=len(claimed),
            **result.as_log_fields(),
        )
        return 1

    async def _claimed(
        self, context: WorkerContext, tenant_id: TenantId, *, now: datetime
    ) -> tuple[OperationRecord, ...]:
        """Claim every due projection, in one transaction, before anything is written.

        A claim that loses a race is skipped rather than failing the pass: something else took it,
        and whatever took it reconciles the same horizon this pass would have.
        """
        async with context.database.sessionmaker() as session, session.begin():
            due = await OperationQueue(session, tenant_id).due(kind=PROJECTION, at=now)
            if not due:
                return ()
            lifecycle = OperationLifecycle(OperationRepository(session, tenant_id), self._clock)
            claimed: list[OperationRecord] = []
            for operation in due:
                try:
                    claimed.append(await lifecycle.claim(operation.id))
                except IllegalTransition:
                    _log.info(
                        "calendars.projection.claim_lost",
                        tenant_id=str(tenant_id),
                        operation_id=str(operation.id),
                    )
            return tuple(claimed)

    async def _stopped(
        self,
        session: AsyncSession,
        tenant_id: TenantId,
        claimed: tuple[OperationRecord, ...],
        target: CalendarSourceRecord,
        failure: ProjectionFailed,
        *,
        now: datetime,
    ) -> None:
        """Record a reconciliation that did not finish: on the metric, the source, and every claim.

        The partial counts are observed, because those writes happened. The outcome is ``failed``
        whether the write was refused or attempted, because the consequence is the same and the
        alert that watches it must fire for both; the difference is the error code and the sentence.
        """
        _observed(failure.applied, outcome=FAILED)
        await self._record(
            session,
            tenant_id,
            claimed,
            target,
            recorded_projection_failure(target.sync_state, at=now, reason=failure.reason),
            outcome=Failed(code=failure.code, message=str(failure)),
        )
        _log.warning(
            "calendars.projection.failed",
            tenant_id=str(tenant_id),
            source_id=str(target.id),
            operation_count=len(claimed),
            error_code=failure.code,
            **failure.applied.as_log_fields(),
        )

    async def _record(
        self,
        session: AsyncSession,
        tenant_id: TenantId,
        claimed: tuple[OperationRecord, ...],
        target: CalendarSourceRecord,
        state: SyncStateRecord,
        *,
        outcome: Outcome | None = None,
    ) -> None:
        """Write the attempt onto the write target and close every claimed operation, together.

        The caller's transaction, so a projection that succeeded cannot leave an operation looking
        unfinished or a target looking untried. A target row deleted since the claim matches no row
        and writes nothing, which is the right answer: there is no source left to record it on.
        """
        await CalendarSourceRepository(session, tenant_id).save_sync_state(target.id, state)
        await self._close(session, tenant_id, claimed, outcome or Succeeded())

    async def _close(
        self,
        session: AsyncSession,
        tenant_id: TenantId,
        claimed: tuple[OperationRecord, ...],
        outcome: Outcome,
    ) -> None:
        """Close every claimed operation with the outcome the pass produced."""
        lifecycle = OperationLifecycle(OperationRepository(session, tenant_id), self._clock)
        for operation in claimed:
            await lifecycle.finish(operation.id, outcome)


def _observed(result: ReconcileResult, *, outcome: str) -> None:
    """Report one reconciliation to the two metric families, including the zeroes.

    Every action is observed on every reconciliation, so a rate over the histogram is readable: an
    action that appeared only when it was non-zero would make one unreadable.
    """
    PROJECTION_DURATION.labels(outcome=outcome).observe(result.duration_ms / 1000)
    for action, count in result.by_action().items():
        PROJECTION_EVENTS.labels(action=action.value).observe(count)
