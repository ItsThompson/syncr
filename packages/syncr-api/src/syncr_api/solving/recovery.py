"""What one failing solve leaves behind: the stated cause, the lost race, and the last resort.

```
solve raises or a step refuses
  │
  ├── record the failure with a stated cause and, on the last attempt, the inputs it read
  └── if this was the last attempt and the week holds no plan, MATERIALIZE one instead
```

## Failure names what still works, and the last attempt keeps the inputs it read

Every failure answers with a stated cause and leaves the previous live plan untouched and still
projected. The attempt bound and the backoff are the lifecycle's, so a solver that raises is retried
exactly as a worker that died is. When the attempts are spent, a week with no live revision at all
is MATERIALIZED instead, so the horizon is never left with a hole; a week that has one keeps it,
because the plan it already has is better than a derived-only one.

## The snapshot is offered on every failure and kept only on the last

A retried attempt returns the row to the queue, and the table forbids a snapshot on any status but
``failed``, so a snapshot arriving is also the assertion that this was the last attempt. The three
phases that hold resolved inputs keep them on that attempt, which is what makes a production failure
reproducible locally.

## A lease that expired mid-solve is a lost race, not a failure

The reaper finishes an abandoned claim through the same lifecycle, so a solve that outlived its
lease finds its row already back in the queue and the step it tries to take applies to nothing.
That is expected under concurrency, and it is why the refusal has two types: nothing of this
solve's was written, the version did not move, and the retry the reaper queued is what runs next.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.events.envelopes import operation_event
from syncr_api.events.publishing import published
from syncr_api.plans.repository import PlanRepository
from syncr_api.solving.config import FAILED
from syncr_api.solving.errors import OperationMovedOn
from syncr_api.solving.failures import statement_for
from syncr_api.solving.metrics import SOLVE_TAKEN_OVER
from syncr_api.solving.outcomes import Failed
from syncr_api.solving.repository import OperationRepository
from syncr_api.solving.snapshots import as_snapshot
from syncr_common.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio.session import AsyncSession

    from syncr_api.core.clock import Clock
    from syncr_api.core.db import Database
    from syncr_api.plans.production import WeekProducer
    from syncr_api.solving.config import SolveFailure
    from syncr_api.solving.coordinator import SolveCoordinator
    from syncr_api.solving.records import OperationRecord
    from syncr_domain.identifiers import TenantId
    from syncr_domain.weeks import IsoWeek
    from syncr_solver.inputs import SolveInputs

_log = get_logger("syncr.solving")


class SolveRecovery:
    """The failure and last-resort path: record the cause, handle a lost race, materialize if spent.

    Shares only the operation row with the guarded write. The dispatch hands in the two collaborator
    builders it owns (the coordinator and the producer), because moving those five three-line
    builders would leave the reader holding the same concepts in two files.
    """

    def __init__(
        self,
        database: Database,
        tenant_id: TenantId,
        *,
        clock: Clock,
        coordinator_for: Callable[[AsyncSession], SolveCoordinator],
        producer_for: Callable[[AsyncSession, PlanRepository], WeekProducer],
    ) -> None:
        self._database = database
        self._tenant_id = tenant_id
        self._clock = clock
        self._coordinator_for = coordinator_for
        self._producer_for = producer_for

    async def failed(
        self,
        op: OperationRecord,
        week: IsoWeek,
        code: SolveFailure,
        *,
        cause: BaseException,
        inputs: SolveInputs | None = None,
    ) -> OperationRecord:
        """Record the failure, and materialize the week when this was the last attempt.

        Left to raise, the refusal reached the runner's per-tenant boundary and read as a tenant
        fault, which is the one reading it is not: a lease that expired mid-solve is a lost race
        here, handled by :meth:`taken_from_under_this_solve` below.
        """
        _log.exception(
            "solving.solve.failed",
            exc_info=cause,
            iso_week=str(week),
            operation_id=str(op.id),
            error_code=code,
        )
        try:
            async with self._database.sessionmaker() as session, session.begin():
                finished = await self._coordinator_for(session).finish(
                    op,
                    Failed(
                        code=code,
                        message=statement_for(code),
                        snapshot=None if inputs is None else as_snapshot(inputs),
                    ),
                )
                await published(session, operation_event(finished))
        except OperationMovedOn as moved:
            return await self.taken_from_under_this_solve(op, week, moved)
        if finished.status != FAILED:
            return finished
        await self.materialized_if_the_week_has_no_plan(week)
        return finished

    async def taken_from_under_this_solve(
        self, op: OperationRecord, week: IsoWeek, moved: OperationMovedOn
    ) -> OperationRecord:
        """The row as something else left it, so ``run()`` answers rather than raising.

        Two actors reach this: the reaper, on a lease this solve outlived, and a tradeoff request
        superseding the solve to ask its own question of the week. Both leave the same fact behind,
        which is what makes one instrument right for it: this solve's write was discarded whole. It
        is NOT the claim scan's counter, because that race is a row skipped before any work, and the
        status the row was found in is on the line below for the actor.
        """
        SOLVE_TAKEN_OVER.inc()
        _log.info(
            "solving.solve.taken_over",
            iso_week=str(week),
            operation_id=str(op.id),
            held=moved.held,
            attempted=moved.attempted,
        )
        async with self._database.sessionmaker() as session:
            left = await OperationRepository(session, self._tenant_id).find(op.id)
        # The refusal named the status the row held, so the row existed a moment ago. A tenant whose
        # row vanished between the two is a defect the retention sweep cannot produce: it prunes
        # terminal rows only.
        if left is None:  # pragma: no cover - unreachable while pruning is terminal-only
            message = f"operation {op.id} vanished after refusing a step from {moved.held!r}"
            raise RuntimeError(message) from moved
        return left

    async def materialized_if_the_week_has_no_plan(self, week: IsoWeek) -> None:
        """The plan of last resort, for a week whose attempts are spent and that holds no plan.

        A week that already has a live revision keeps it: the plan it has is better than a
        derived-only one, and it is still projected. A week with none would otherwise leave the
        horizon with a hole, so the frame, the commitments, the buffers and the day's shape are
        materialized with every Area slot drawn unfilled.
        """
        now = self._clock()
        async with self._database.sessionmaker() as session, session.begin():
            revisions = PlanRepository(session, self._tenant_id)
            if await revisions.latest(week) is not None:
                return
            await self._producer_for(session, revisions).materialize_week(week, now=now)
        _log.info("solving.solve.materialized_instead", iso_week=str(week))
