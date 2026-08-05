"""The worker's maintenance duty: return the abandoned claims, prune the terminal rows.

Two sweeps, one duty, because both are periodic housekeeping over one table and neither belongs to
any request.

**The reaper.** A worker killed mid-solve leaves its operation ``running`` and nobody waiting on it:
the row is not scheduled, so nothing brings it back, which makes it the one case the lifecycle
cannot resolve on its own. The reaper finishes such an operation as a failure whose cause is the
lease, and the ordinary retry rule decides whether it comes back. Why that is a failure rather than
a state of its own is :mod:`syncr_api.solving.transitions`, which owns the machine.

**The retention sweep.** Operations are telemetry rather than facts about the plan -- the plan's
history is ``plan_revisions``, which is never pruned -- so pruning one loses nothing about what the
plan was. A failure is kept three times as long because it is diagnostic: its
``failed_input_snapshot`` is what reproduces the failure locally. **Nothing else is pruned by this
duty**, and the sweep names the two status sets it deletes rather than deleting by age alone.

**Containment is per tenant AND per operation, and the runbook is why the second one matters.**
`docs/runbooks/stuck-operation.md` tells an operator to run this sweep inside the live worker during
an incident, which is a second concurrent reaper by construction. Without a boundary per operation,
the row the other sweep finished first would make this one's write match nothing, and the refusal
would roll back every tenant's prune as well: an operator following the runbook would see a
traceback mid-incident caused by their own instruction. Each lost race is counted and skipped
instead.

**Both sweeps are per tenant, and that is deliberate.** Every statement over a table that holds a
plan carries its tenant, with no exception for maintenance, so the runner enumerates tenants and
builds one scoped repository for each rather than issuing one unscoped delete. The cost is a few
queries per tenant per sweep on a deployment whose tenant count is one; what it buys is that "every
scoped statement is scoped" stays a property of the code rather than a property with a footnote.

**It owns its own cadence.** The worker ticks every few seconds and neither sweep is wanted that
often, so the runner keeps the instant it is next due and returns immediately in between. That is
the registry's contract: a runner decides per tick whether it has work."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from prometheus_client import Counter

from syncr_api.accounts.repository import TenantRepository
from syncr_api.solving.config import (
    FAILED,
    FAILED_RETENTION,
    LEASE,
    LEASE_EXPIRED,
    SUCCEEDED,
    SUCCEEDED_RETENTION,
    SUPERSEDED,
)
from syncr_api.solving.errors import OperationMovedOn
from syncr_api.solving.lifecycle import OperationLifecycle
from syncr_api.solving.outcomes import Failed
from syncr_api.solving.repository import OperationRepository
from syncr_api.solving.sweeps import OperationSweeps
from syncr_common.logging import get_logger
from syncr_common.metrics import REGISTRY, measured

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_api.core.clock import Clock
    from syncr_api.worker.main import WorkerContext
    from syncr_domain.identifiers import TenantId

# How often maintenance runs. An expired claim is a stalled week, so the interval is the
# maintainer's own quarter hour rather than a daily sweep: fifteen minutes of a stuck operation is
# the same lag the horizon maintainer already accepts. A pruned row is inert either way.
MAINTENANCE_INTERVAL = timedelta(minutes=15)

# What the user is told when a claim expired. It names what still works, the same rule every error
# detail and every degradation notice follows.
LEASE_EXPIRED_STATEMENT = (
    "The worker holding this work stopped before it finished, so the work was returned to the "
    "queue. The previous plan for the week is untouched and still projected."
)

# A tenant whose sweep raised, and a claim another actor finished first. Both are contained, so
# neither reaches `measured` or the loop's own failure counter: a fault that answers with a tally is
# invisible unless something counts it. A lost race is expected and is counted rather than logged as
# an error, so a sustained rate is readable while a single one is not an incident.
TENANT_SWEEP_FAILURES = Counter(
    "syncr_operation_sweep_tenant_failures_total",
    "Maintenance sweeps that raised for one tenant and were contained.",
    registry=REGISTRY,
)
REAPER_RACES_LOST = Counter(
    "syncr_operation_reaper_races_lost_total",
    "Expired claims another actor finished between this reaper's read and its write.",
    registry=REGISTRY,
)

_log = get_logger("syncr.solving")


@dataclass(frozen=True, slots=True)
class SweptOperations:
    """What one maintenance pass did, so one log line says it.

    ``reaped`` counts claims returned to the queue OR failed terminally, because both are the same
    finding: a worker did not come back. Which of the two happened is the attempt bound's decision
    and it is on the row."""

    reaped: int = 0
    pruned: int = 0
    races_lost: int = 0
    tenants_failed: int = 0

    def plus(self, other: SweptOperations) -> SweptOperations:
        return SweptOperations(
            reaped=self.reaped + other.reaped,
            pruned=self.pruned + other.pruned,
            races_lost=self.races_lost + other.races_lost,
            tenants_failed=self.tenants_failed + other.tenants_failed,
        )

    @property
    def total(self) -> int:
        return self.reaped + self.pruned + self.races_lost + self.tenants_failed

    def as_log_fields(self) -> dict[str, int]:
        return {
            "reaped": self.reaped,
            "pruned": self.pruned,
            "races_lost": self.races_lost,
            "tenants_failed": self.tenants_failed,
        }


class OperationMaintenance:
    """Returns ONE tenant's abandoned claims and removes its aged terminal rows.

    One tenant per instance, because the transaction is one tenant's: a tenant whose sweep raises
    rolls back its own writes and nothing else's. Enumerating tenants belongs to the runner, which
    is where the failure boundary between them is.

    Both collaborators are injected rather than built here, as every other service in this
    neighbourhood composes them. What that buys beyond consistency is that the reaper's lost-race
    branch is drivable: the race is a row changing between the scan and the write, and nothing
    outside a method that owns both of those can interleave them.
    """

    def __init__(
        self,
        sweeps: OperationSweeps,
        lifecycle: OperationLifecycle,
        clock: Clock,
        *,
        lease: timedelta = LEASE,
    ) -> None:
        self._sweeps = sweeps
        self._lifecycle = lifecycle
        self._clock = clock
        self._lease = lease

    @measured("operations")
    async def sweep(self, *, now: datetime | None = None) -> SweptOperations:
        """Reap this tenant's expired claims, then prune its aged terminal rows.

        Reaping first is not an ordering the counts depend on, and it is still the right order: a
        claim the reaper fails terminally becomes prunable, and doing it in this order means such a
        row waits its whole retention window rather than 90 days minus one pass.
        """
        at = now or self._clock()
        reaped, races_lost = await self._reap(at)
        return SweptOperations(reaped=reaped, races_lost=races_lost, pruned=await self._prune(at))

    async def _reap(self, now: datetime) -> tuple[int, int]:
        """Finish every claim taken longer ago than the lease, as a failure naming the lease.

        Through the lifecycle rather than by writing the status here, so an expired claim obeys the
        same attempt bound and the same backoff a raising solver does.

        Each operation is contained. This reaper read the row as ``running`` moments ago, so a row
        that will not take the step was stepped by something else in between, which is a lost race
        rather than a defect: the runbook tells an operator to run a second sweep during an
        incident, so the race is not hypothetical. A lost race is counted and skipped.
        """
        expired = await self._sweeps.running_since_before(now - self._lease)
        reaped = 0
        races_lost = 0
        for operation in expired:
            try:
                await self._lifecycle.finish(
                    operation.id, Failed(code=LEASE_EXPIRED, message=LEASE_EXPIRED_STATEMENT)
                )
            except OperationMovedOn as moved:
                races_lost += 1
                REAPER_RACES_LOST.inc()
                _log.info(
                    "solving.operation.reaper_race_lost",
                    operation_id=str(operation.id),
                    held=moved.held,
                    attempted=moved.attempted,
                )
                continue
            reaped += 1
            _log.warning(
                "solving.operation.lease_expired",
                operation_id=str(operation.id),
                kind=operation.kind,
                attempt=operation.attempt,
                lease_seconds=self._lease / timedelta(seconds=1),
            )
        return reaped, races_lost

    async def _prune(self, now: datetime) -> int:
        """Remove the terminal rows past their window, and nothing else.

        Two windows and two status sets, because a failure is kept three times as long. Why the
        status set is named rather than derived from ``finished_at`` alone is the statement's own.
        """
        aged = await self._sweeps.delete_finished_before(
            now - SUCCEEDED_RETENTION, statuses=(SUCCEEDED, SUPERSEDED)
        )
        return aged + await self._sweeps.delete_finished_before(
            now - FAILED_RETENTION, statuses=(FAILED,)
        )


def maintenance_for(
    session: AsyncSession, tenant_id: TenantId, clock: Clock, *, lease: timedelta = LEASE
) -> OperationMaintenance:
    """One tenant's maintenance over one session. The composition both callers share."""
    return OperationMaintenance(
        OperationSweeps(session, tenant_id),
        OperationLifecycle(OperationRepository(session, tenant_id), clock),
        clock,
        lease=lease,
    )


class OperationMaintenanceRunner:
    """One duty on the worker loop: sweep when due, return immediately when not.

    A callable object rather than a closure, so the loop's name lookup finds a stable name for its
    failure metric and so a test can read when the sweep is next due.

    The FIRST tick schedules rather than sweeps. A process that restarts often would otherwise
    delete on every boot, which is a write on a path that is supposed to be idle."""

    __name__ = "operation_maintenance"

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
        await self.sweep(context, now=now)

    async def sweep(self, context: WorkerContext, *, now: datetime) -> SweptOperations:
        """One pass over every tenant, each in its own transaction and its own failure boundary."""
        async with context.database.sessionmaker() as reader:
            tenants = await TenantRepository(reader).list_ids()

        total = SweptOperations()
        for tenant_id in tenants:
            total = total.plus(await self._tenant(context, tenant_id, now=now))
        if total.total:
            _log.info("solving.maintenance.completed", **total.as_log_fields())
        return total

    async def _tenant(
        self, context: WorkerContext, tenant_id: TenantId, *, now: datetime
    ) -> SweptOperations:
        """One tenant's sweep, in its own transaction, with its own fault contained.

        Answers with a failure tally rather than re-raising, so the tenants after this one are still
        swept and their prunes are not rolled back with this one's. The failure is counted and named
        HERE rather than left to the worker loop's handler, which isolates one DUTY and would
        therefore drop every remaining tenant.
        """
        try:
            async with context.database.sessionmaker() as session, session.begin():
                return await maintenance_for(session, tenant_id, self._clock).sweep(now=now)
        except Exception:  # noqa: BLE001 - one tenant's fault must not stop the others
            TENANT_SWEEP_FAILURES.inc()
            _log.exception("solving.maintenance.tenant_failed", tenant_id=str(tenant_id))
            return SweptOperations(tenants_failed=1)
