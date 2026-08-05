"""The worker's maintenance duty: return the abandoned claims, prune the terminal rows.

Two sweeps, one duty, because both are periodic housekeeping over one table and neither belongs to
any request.

**The reaper.** A worker killed mid-solve leaves its operation ``running`` and nobody waiting on
it: the row is not scheduled, so nothing brings it back, which makes it the one case the lifecycle
cannot resolve on its own. The reaper finishes such an operation as a failure whose cause is the
lease, and the ordinary retry rule decides whether it comes back. That is why there is no
``running`` to ``pending`` transition: a dying worker is a failure, and treating it as one gives it
the attempt bound for free, so an operation no worker survives stops retrying instead of looping
forever.

**The retention sweep.** Operations are telemetry rather than facts about the plan -- the plan's
history is ``plan_revisions``, which is never pruned -- so pruning one loses nothing about what the
plan was. A failure is kept three times as long because it is diagnostic: its
``failed_input_snapshot`` is what reproduces the failure locally. **Nothing else is pruned by this
duty**, and the sweep names the two status sets it deletes rather than deleting by age alone.

**Both sweeps are per tenant, and that is deliberate.** Every statement over a table that holds a
plan carries its tenant, with no exception for maintenance, so this enumerates tenants and builds
one scoped repository for each rather than issuing one unscoped delete. The cost is a few queries
per tenant per sweep on a deployment whose tenant count is one; what it buys is that "every scoped
statement is scoped" stays a property of the code rather than a property with a footnote.

**It owns its own cadence.** The worker ticks every few seconds and neither sweep is wanted that
often, so the runner keeps the instant it is next due and returns immediately in between. That is
the registry's contract: a runner decides per tick whether it has work.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

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
from syncr_api.solving.lifecycle import OperationLifecycle
from syncr_api.solving.outcomes import Failed
from syncr_api.solving.repository import OperationRepository
from syncr_api.solving.sweeps import OperationSweeps
from syncr_common.logging import get_logger
from syncr_common.metrics import measured

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

_log = get_logger("syncr.solving")


@dataclass(frozen=True, slots=True)
class SweptOperations:
    """What one maintenance pass did, so one log line says it.

    ``reaped`` counts claims returned to the queue OR failed terminally, because both are the same
    finding: a worker did not come back. Which of the two happened is the attempt bound's decision
    and it is on the row.
    """

    reaped: int = 0
    pruned: int = 0

    def plus(self, other: SweptOperations) -> SweptOperations:
        return SweptOperations(reaped=self.reaped + other.reaped, pruned=self.pruned + other.pruned)

    @property
    def total(self) -> int:
        return self.reaped + self.pruned

    def as_log_fields(self) -> dict[str, int]:
        return {"reaped": self.reaped, "pruned": self.pruned}


class OperationMaintenance:
    """Returns one tenant's abandoned claims and removes its aged terminal rows."""

    def __init__(self, session: AsyncSession, clock: Clock, *, lease: timedelta = LEASE) -> None:
        self._session = session
        self._clock = clock
        self._lease = lease

    @measured("operations")
    async def sweep(self) -> SweptOperations:
        """One pass over every tenant: reap first, then prune.

        Reaping first is not an ordering the counts depend on, and it is still the right order: a
        claim the reaper fails terminally becomes prunable, and doing it in this order means such a
        row waits its whole retention window rather than 90 days minus one pass.
        """
        now = self._clock()
        swept = SweptOperations()
        for tenant_id in await TenantRepository(self._session).list_ids():
            swept = swept.plus(await self._sweep_tenant(tenant_id, now))
        if swept.total:
            _log.info("solving.maintenance.completed", **swept.as_log_fields())
        return swept

    async def _sweep_tenant(self, tenant_id: TenantId, now: datetime) -> SweptOperations:
        sweeps = OperationSweeps(self._session, tenant_id)
        return SweptOperations(
            reaped=await self._reap(sweeps, tenant_id, now),
            pruned=await self._prune(sweeps, now),
        )

    async def _reap(self, sweeps: OperationSweeps, tenant_id: TenantId, now: datetime) -> int:
        """Finish every claim taken longer ago than the lease, as a failure naming the lease.

        Through the lifecycle service rather than by writing the status here, so an expired claim
        obeys the same attempt bound and the same backoff a raising solver does.
        """
        expired = await sweeps.running_since_before(now - self._lease)
        lifecycle = OperationLifecycle(OperationRepository(self._session, tenant_id), self._clock)
        for operation in expired:
            await lifecycle.finish(
                operation.id, Failed(code=LEASE_EXPIRED, message=LEASE_EXPIRED_STATEMENT)
            )
            _log.warning(
                "solving.operation.lease_expired",
                operation_id=str(operation.id),
                kind=operation.kind,
                attempt=operation.attempt,
                lease_seconds=self._lease / timedelta(seconds=1),
            )
        return len(expired)

    async def _prune(self, sweeps: OperationSweeps, now: datetime) -> int:
        """Remove the terminal rows past their window, and nothing else.

        Two windows and two status sets, because a failure is kept three times as long. Why the
        status set is named rather than derived from ``finished_at`` alone is the statement's own.
        """
        aged = await sweeps.delete_finished_before(
            now - SUCCEEDED_RETENTION, statuses=(SUCCEEDED, SUPERSEDED)
        )
        return aged + await sweeps.delete_finished_before(
            now - FAILED_RETENTION, statuses=(FAILED,)
        )


class OperationMaintenanceRunner:
    """One duty on the worker loop: sweep when due, return immediately when not.

    A callable object rather than a closure, so the loop's name lookup finds a stable name for its
    failure metric and so a test can read when the sweep is next due.

    The FIRST tick schedules rather than sweeps. A process that restarts often would otherwise
    delete on every boot, which is a write on a path that is supposed to be idle.
    """

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
        # Its own session and its own transaction, independent of any request, committed by the
        # context manager so a partial sweep is not left half applied.
        async with context.database.sessionmaker() as session, session.begin():
            await OperationMaintenance(session, self._clock).sweep()
