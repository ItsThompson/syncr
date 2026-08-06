"""One claimed solve, from the inputs it loads to the status it ends in.

```
op = coordinator.claim_next()               already claimed when this is called
  │
  ├── TRANSACTION 1  load
  │     ├── inputs = assembler.assemble(week, now, extra_adjustment=op.candidate_adjustment)
  │     ├── V = inputs.input_version         STAMPED onto the operation here, not at creation
  │     └── weights = weights.active()
  │
  ├── NO TRANSACTION  solve
  │     └── syncr_solver.solve(inputs, weights, cancelled=the version watch)
  │           off the event loop, so the watch can run and the tick's other duties are not blocked
  │
  ├── classify(inputs.live_plan, result.document, now=inputs.now)
  │
  └── TRANSACTION 2  write, guarded
        ├── SELECT version ... FOR UPDATE
        ├── moved  ──▶ ROLLBACK. finish(op, Superseded), which enqueues ONE follow-up
        └── held   ──▶ adopt, bump if the live plan changed, enqueue the projection if it did,
                       finish(op, Succeeded)
```

## The version is stamped when the inputs are LOADED, not when the operation is created

That distinction is what makes coalescing save a solve rather than waste one. Stamped at creation,
the first mutation of a burst would create an operation guarded on a version the next two mutations
had already moved past, so it would be superseded with no concurrency involved at all and "twelve
rapid edits cost one solve" would mean eleven coalesced into a discard plus a re-run.

## Three transactions, and why the solve is outside all of them

A solve is roughly a second and a half of arithmetic. Holding a transaction open across it would
hold a pooled connection for that whole time and, worse, would make the assembly's own snapshot the
thing the conditional write compares against, which is a comparison of a value to itself. So the
load commits, the solve runs against values, and the write takes its own transaction and its own row
lock.

## The classification is made against the SAME live plan the solver read

``inputs.live_plan`` rather than a second read of the revision table. The producer and the guard
then agree by construction: a candidate is judged against the plan it was built to improve on. Read
again in the write transaction, the pair could differ by anything that landed in between, and every
such difference would report as the solver having dropped or moved a block it never saw.

**What that costs today is disclosed rather than hidden.** The assembler's placement seam answers
with no live plan in this deployment, so every candidate classifies as a first plan for its week and
the authority rule has nothing to hold back. The suite supplies a real reader and drives both sides.
Whoever supplies the production reader changes one line of ``plans/injection.py``, and this path
starts holding moves back with no change here.

## A version mismatch discards BEFORE anything is written

The guard is the first statement of the write transaction and it takes the row ``FOR UPDATE``, so
reading the version, comparing it, and writing the revision cannot interleave with another
mutation's bump. A missing row is a mismatch, not a match, which is what stops two concurrent first
solves from both committing. Nothing is rebased and nothing is applied partially: the transaction
rolls back and the coordinator enqueues exactly one follow-up.

## Failure names what still works, and the last attempt keeps the inputs it read

Every failure answers with a stated cause and leaves the previous live plan untouched and still
projected. The attempt bound and the backoff are the lifecycle's, so a solver that raises is retried
exactly as a worker that died is. When the attempts are spent, a week with no live revision at all
is MATERIALIZED instead, so the horizon is never left with a hole; a week that has one keeps it,
because the plan it already has is better than a derived-only one.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.learned.repository import WeightSetRepository
from syncr_api.learned.weight_reading import as_weight_set
from syncr_api.plans.adoption import Candidate, PlanAdoption
from syncr_api.plans.assembler import AssemblyCaller
from syncr_api.plans.authority import classify
from syncr_api.plans.candidates import from_document
from syncr_api.plans.conflicts import PlanConflictRepository
from syncr_api.plans.errors import ClassificationRejected
from syncr_api.plans.injection import build_week_assembler
from syncr_api.plans.production import NoWeightSetInForce, WeekProducer
from syncr_api.plans.proposals import PendingProposalRepository
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_verdicts import stored_verdict
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.checkpoints import watching_the_version
from syncr_api.solving.config import (
    FAILED,
    INPUTS_UNREADABLE,
    PAST_DISAGREEMENT,
    PROJECTION,
    SOLVER_RAISED,
    WRITE_REFUSED,
)
from syncr_api.solving.failures import statement_for
from syncr_api.solving.injection import build_solve_coordinator
from syncr_api.solving.lifecycle import OperationLifecycle
from syncr_api.solving.outcomes import Failed, Succeeded, Superseded
from syncr_api.solving.repository import OperationRepository
from syncr_api.solving.snapshots import as_snapshot
from syncr_common.logging import get_logger
from syncr_common.metrics import measured
from syncr_domain.plan import RevisionReason
from syncr_solver import solve

if TYPE_CHECKING:
    from datetime import timedelta

    from sqlalchemy.ext.asyncio.session import AsyncSession

    from syncr_api.core.clock import Clock
    from syncr_api.core.db import Database
    from syncr_api.plans.authority import Classification
    from syncr_api.solving.config import SolveFailure
    from syncr_api.solving.coordinator import SolveCoordinator
    from syncr_api.solving.records import OperationRecord
    from syncr_domain.identifiers import TenantId
    from syncr_domain.weeks import IsoWeek
    from syncr_solver.budget import SolveBudget
    from syncr_solver.inputs import SolveInputs, WeekAdjustment
    from syncr_solver.solve import SolveResult
    from syncr_solver.weights import WeightSet

_log = get_logger("syncr.solving")


@dataclass(frozen=True, slots=True, kw_only=True)
class Loaded:
    """What one solve read before it began: the resolved week, and the weights in force."""

    inputs: SolveInputs
    weights: WeightSet
    weight_set_version: int

    @property
    def input_version(self) -> int:
        """The version this solve's write is guarded on. Stamped from the assembly, not a clock."""
        return self.inputs.input_version


class SolveDispatch:
    """Runs one claimed solve of one tenant's week to a terminal status."""

    def __init__(
        self,
        database: Database,
        tenant_id: TenantId,
        *,
        clock: Clock,
        debounce: timedelta,
        budget: SolveBudget | None = None,
    ) -> None:
        self._database = database
        self._tenant_id = tenant_id
        self._clock = clock
        self._debounce = debounce
        self._budget = budget

    @measured("solve_dispatch")
    async def run(self, op: OperationRecord, week: IsoWeek) -> OperationRecord:
        """Take ``op`` from its claim to a terminal status, and answer with the row it reached.

        Four phases, each with its own cause: a phase that raises fails the operation with the code
        for the place it stopped, so "what went wrong" is answered by the code rather than by
        reading a traceback out of the log. The three that hold resolved inputs keep them on the
        last attempt, which is what makes a production failure reproducible locally.
        """
        try:
            loaded = await self._loaded(op, week)
        except Exception as unreadable:  # noqa: BLE001 - any read fault is one stated cause
            return await self._failed(op, week, INPUTS_UNREADABLE, cause=unreadable)
        try:
            solved = await self._solved(loaded, week)
        except Exception as raised:  # noqa: BLE001 - the retry exists for exactly this
            return await self._failed(op, week, SOLVER_RAISED, cause=raised, inputs=loaded.inputs)
        try:
            classification = classify(
                loaded.inputs.live_plan, solved.document, now=loaded.inputs.now
            )
        except ClassificationRejected as refused:
            # Before any write transaction is opened, because the refusal is a pure comparison of
            # two documents: a candidate that restates the week's own past never reaches the guard.
            return await self._failed(
                op, week, PAST_DISAGREEMENT, cause=refused, inputs=loaded.inputs
            )
        try:
            return await self._written(op, week, loaded, solved, classification)
        except Exception as unwritable:  # noqa: BLE001 - a refused write is one stated cause
            return await self._failed(
                op, week, WRITE_REFUSED, cause=unwritable, inputs=loaded.inputs
            )

    async def _loaded(self, op: OperationRecord, week: IsoWeek) -> Loaded:
        """Assemble the week, read the weights in force, and stamp the version onto ``op``.

        The stamp is in the same transaction as the read that produced it, so an operation reporting
        a version has read that version's inputs.
        """
        now = self._clock()
        async with self._database.sessionmaker() as session, session.begin():
            assembler = build_week_assembler(session, self._tenant_id, caller=AssemblyCaller.WORKER)
            inputs = await assembler.assemble(week, now, self._candidate_of(op, week))
            stored = await WeightSetRepository(session, self._tenant_id).active()
            if stored is None:
                raise NoWeightSetInForce(
                    "this tenant has no active weight set, so there are no weights a plan could "
                    "be produced under. Provisioning seeds version 1 in the transaction that "
                    "creates a tenant, so a tenant without one was not created by this application"
                )
            await OperationRepository(session, self._tenant_id).stamp_input_version(
                op.id, input_version=inputs.input_version
            )
        return Loaded(
            inputs=inputs,
            weights=as_weight_set(stored),
            weight_set_version=stored.version,
        )

    async def _solved(self, loaded: Loaded, week: IsoWeek) -> SolveResult:
        """The plan this week's inputs produce, run off the event loop under a version watch.

        Off the loop for two reasons that point the same way: a synchronous second and a half would
        block every other duty of the tick, and the watch that lets the solve give up early runs on
        the loop the solve would be holding.
        """
        async with watching_the_version(
            self._database.sessionmaker,
            self._tenant_id,
            week,
            held=loaded.input_version,
        ) as cancelled:
            return await asyncio.to_thread(
                solve, loaded.inputs, loaded.weights, budget=self._budget, cancelled=cancelled
            )

    async def _written(
        self,
        op: OperationRecord,
        week: IsoWeek,
        loaded: Loaded,
        solved: SolveResult,
        classification: Classification,
    ) -> OperationRecord:
        """The one transaction the guard and every write this solve performs live in.

        The version row is taken ``FOR UPDATE`` first, so nothing between the comparison and the
        append can bump it. On a mismatch this returns without writing anything and the supersession
        is recorded in a transaction of its own, because the rollback has to take the read with it.
        """
        now = self._clock()
        async with self._database.sessionmaker() as session, session.begin():
            versions = WeekInputVersionRepository(session, self._tenant_id)
            if not await versions.holds_version(week, loaded.input_version, at=now):
                await session.rollback()
                return await self._superseded(op, week, loaded)
            adopted = await self._adoption(session).adopt(
                classification,
                self._candidate(op, loaded, solved),
                reason=RevisionReason.AUTO_APPLIED_FILL.value,
                at=now,
            )
            if adopted.changed_the_live_plan():
                # The live plan IS a solve input, so the version moves with it, and the projection
                # is enqueued for the same reason and under the same condition: a replaced proposal
                # nobody has agreed to changes neither.
                await versions.bump(week, at=now)
                await self._lifecycle(session).enqueue(kind=PROJECTION, iso_week=week)
            revision = None if adopted.revision is None else adopted.revision.id
            finished = await self._coordinator(session).finish(
                op, Succeeded(result_revision_id=revision)
            )
        _log.info(
            "solving.solve.completed",
            iso_week=str(week),
            operation_id=str(op.id),
            input_version=loaded.input_version,
            weight_set_version=loaded.weight_set_version,
            iterations=solved.iterations,
            revision_id=None if revision is None else str(revision),
            proposal_replaced=adopted.proposal is not None,
            conflicts_raised=len(adopted.raised),
            projection_enqueued=adopted.changed_the_live_plan(),
        )
        return finished

    async def _superseded(
        self, op: OperationRecord, week: IsoWeek, loaded: Loaded
    ) -> OperationRecord:
        """Discard this solve's result and let the coordinator enqueue exactly one follow-up.

        Its own transaction, because the write transaction rolled back: the supersession is a fact
        about this operation and must not be lost with the read that discovered it.
        """
        async with self._database.sessionmaker() as session, session.begin():
            return await self._coordinator(session).finish(op, Superseded())

    async def _failed(
        self,
        op: OperationRecord,
        week: IsoWeek,
        code: SolveFailure,
        *,
        cause: BaseException,
        inputs: SolveInputs | None = None,
    ) -> OperationRecord:
        """Record the failure, and materialize the week when this was the last attempt.

        The snapshot is offered on every failure and kept only on the last one, which the lifecycle
        decides: a retried attempt returns the row to the queue, and the table forbids a snapshot on
        any status but ``failed``.
        """
        _log.exception(
            "solving.solve.failed",
            exc_info=cause,
            iso_week=str(week),
            operation_id=str(op.id),
            error_code=code,
        )
        async with self._database.sessionmaker() as session, session.begin():
            finished = await self._coordinator(session).finish(
                op,
                Failed(
                    code=code,
                    message=statement_for(code),
                    snapshot=None if inputs is None else as_snapshot(inputs),
                ),
            )
        if finished.status != FAILED:
            return finished
        await self._materialized_if_the_week_has_no_plan(week)
        return finished

    async def _materialized_if_the_week_has_no_plan(self, week: IsoWeek) -> None:
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
            await self._producer(session, revisions).materialize_week(week, now=now)
        _log.info("solving.solve.materialized_instead", iso_week=str(week))

    def _candidate_of(self, op: OperationRecord, week: IsoWeek) -> WeekAdjustment | None:
        """The unpersisted concession this solve must fold in, or nothing.

        The operation is the only object that crosses from the request to the worker, so a
        tradeoff's candidate rides on it and is read back here into the value the assembler folds.
        Nothing is persisted by a request, which is what keeps requesting a tradeoff free of effect.
        """
        if op.candidate_adjustment is None:
            return None
        return from_document(op.candidate_adjustment, dates=week.dates())

    def _candidate(self, op: OperationRecord, loaded: Loaded, solved: SolveResult) -> Candidate:
        """What both possible writes need, held as one value."""
        return Candidate(
            document=solved.document,
            objective_breakdown=solved.objective_breakdown.costs(),
            verdict=stored_verdict(solved.verdict),
            weight_set_version=loaded.weight_set_version,
            input_version=loaded.input_version,
            operation_id=op.id,
            candidate_adjustment=op.candidate_adjustment,
        )

    def _adoption(self, session: AsyncSession) -> PlanAdoption:
        return PlanAdoption(
            revisions=PlanRepository(session, self._tenant_id),
            pending=PendingProposalRepository(session, self._tenant_id),
            conflicts=PlanConflictRepository(session, self._tenant_id),
        )

    def _coordinator(self, session: AsyncSession) -> SolveCoordinator:
        return build_solve_coordinator(
            session, self._tenant_id, clock=self._clock, debounce=self._debounce
        )

    def _lifecycle(self, session: AsyncSession) -> OperationLifecycle:
        return OperationLifecycle(OperationRepository(session, self._tenant_id), self._clock)

    def _producer(self, session: AsyncSession, revisions: PlanRepository) -> WeekProducer:
        return WeekProducer(
            assembler=build_week_assembler(session, self._tenant_id, caller=AssemblyCaller.WORKER),
            revisions=revisions,
            versions=WeekInputVersionRepository(session, self._tenant_id),
            weights=WeightSetRepository(session, self._tenant_id),
            operations=self._lifecycle(session),
        )
