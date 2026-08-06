"""``SolveCoordinator``: the deep module whose whole job is the single-flight invariant.

At most one non-terminal solve exists per week. A mutation arriving while one is in flight does not
create a second: it bumps the week's input version, and the version comparison at the conditional
write is what notices. Nothing is cancelled for correctness, nothing is queued in order, and
nothing is rebased.

```
request_solve(week, at_version, immediate, candidate)
  │
  ├── candidate is not None                 A TRADEOFF REQUEST
  │     └──▶ supersede any PENDING operation and create a new one carrying the candidate, due now.
  │          It may never join an existing operation: coalescing into one created by a pin made two
  │          seconds earlier would answer with a proposal that does not contain the concession, and
  │          the tradeoff would appear to have been ignored
  ├── no operation exists
  │     └──▶ create one, due at now + (0 if immediate else the debounce window)
  ├── one is PENDING
  │     ├── it carries a candidate ──▶ leave it. An ordinary mutation does not displace a pending
  │     │                              tradeoff; its own version bump supersedes the tradeoff after
  │     │                              it runs, and the candidate carries forward
  │     ├── immediate              ──▶ pull its due instant forward to now
  │     └── otherwise              ──▶ leave it. THE COALESCING STEP
  └── one is RUNNING
        └──▶ do nothing. The mutation already bumped the version, so the running solve's
             conditional write will fail and finish() enqueues the follow-up. No flag is needed:
             the version row is the only serialization point and it already carries the signal
```

## The window is fixed from the first mutation, not slid by later ones

A burst therefore always resolves within one window of its START. A sliding window would mean a
user editing continuously never gets a solve at all, which is the opposite of the intent, so a
non-immediate request against a pending operation leaves the due instant exactly where it is.

## ``at_version`` is not the guard

It exists for the caller's RESPONSE, so a pin can tell the client which input state was
acknowledged. The guard is the conditional write, made against the version the worker stamped when
it loaded the inputs, and there is nothing here that compares ``at_version`` to anything.

## A tradeoff request arriving while a solve is RUNNING is refused

Three answers were available and the refusal is the one that keeps the invariant. Joining is
forbidden for the reason above. Queueing behind the running solve would need a second non-terminal
solve for the week, which the partial unique index refuses and which is the invariant this module
exists to hold. Superseding the running solve would be cancellation for convenience: it buys
nothing the caller cannot get by asking again, and it opens a race where the solve commits its
adoption between the read that found it running and the write that closed it.

So the refusal is what ships, and it is bounded rather than a dead end: a solve is budgeted at
under two seconds, and :class:`~syncr_api.solving.errors.SolveIsRunning` carries that, so the
caller states it and the client asks again.

## Supersession names its successor, in two writes

The follow-up cannot exist until the superseded row is closed, because at most one non-terminal
solve per week is enforced by an index rather than by convention. So ``finish`` closes the row,
creates the follow-up, and then names it. Both writes are in the caller's transaction, so nothing
observes a supersession with no successor.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from prometheus_client import Counter

from syncr_api.solving.config import PENDING, RUNNING, SOLVE
from syncr_api.solving.errors import OperationMovedOn, SolveIsRunning
from syncr_api.solving.metrics import OPERATION_QUEUE_DELAY, SOLVE_TALLY
from syncr_api.solving.outcomes import Superseded
from syncr_common.logging import get_logger
from syncr_common.metrics import REGISTRY, measured

if TYPE_CHECKING:
    from datetime import datetime, timedelta

    from syncr_api.core.clock import Clock
    from syncr_api.core.columns import JsonDocument
    from syncr_api.solving.config import OperationKind
    from syncr_api.solving.lifecycle import OperationLifecycle
    from syncr_api.solving.outcomes import Outcome
    from syncr_api.solving.records import OperationRecord
    from syncr_api.solving.repository import OperationRepository
    from syncr_domain.weeks import IsoWeek

# A due operation something else finished between this scan's read and its claim. Counted rather
# than only logged, because the scan answers by moving on: without this, a claim losing every race
# would leave the runner reporting nothing to do and every counter at zero.
CLAIM_RACES_LOST = Counter(
    "syncr_solve_claim_races_lost_total",
    "Due solves another actor finished between this scan's read and its claim.",
    registry=REGISTRY,
)

_log = get_logger("syncr.solving")


class DueSolves(Protocol):
    """What the claim scan reads: the due pending operations of one kind, oldest first.

    A protocol rather than the queue itself, because the window between reading a row and claiming
    it cannot be opened from outside the coordinator: a second session's commit is visible to the
    scan's own read. A test substitutes a reader answering with a row that has already moved on,
    which is the only way to drive the branch a real lost race reaches.
    """

    async def due(
        self, *, kind: OperationKind, at: datetime, limit: int = ...
    ) -> tuple[OperationRecord, ...]: ...


class SolveCoordinator:
    """Holds one tenant's single-flight invariant over every week it plans."""

    def __init__(
        self,
        *,
        operations: OperationRepository,
        queue: DueSolves,
        lifecycle: OperationLifecycle,
        clock: Clock,
        debounce: timedelta,
    ) -> None:
        self._operations = operations
        self._queue = queue
        self._lifecycle = lifecycle
        self._clock = clock
        self._debounce = debounce

    @measured("solve_coordinator")
    async def request_solve(
        self,
        week: IsoWeek,
        at_version: int,
        *,
        immediate: bool = False,
        candidate: JsonDocument | None = None,
    ) -> OperationRecord:
        """Ask for a solve of ``week``, and answer with the operation the caller should track.

        Idempotent per week EXCEPT for a request carrying a candidate. Either a newly scheduled
        operation, or the one already in flight.

        ``at_version`` is the input version the caller's own mutation produced. It is recorded on
        this call's log line and handed back to the caller for its response, and it is NOT compared
        to anything: the guard is the conditional write the worker makes against the version it
        stamped when it loaded the inputs.

        Raises :class:`~syncr_api.solving.errors.SolveIsRunning` for a candidate arriving while a
        solve of the week is running.
        """
        in_flight = await self._operations.in_flight(week, kind=SOLVE)
        if candidate is not None:
            return await self._for_a_candidate(week, in_flight, candidate, at_version=at_version)
        if in_flight is None:
            return await self._scheduled(week, immediate=immediate, at_version=at_version)
        return await self._joined(week, in_flight, immediate=immediate, at_version=at_version)

    @measured("solve_coordinator")
    async def claim_next(self) -> OperationRecord | None:
        """Atomically step one due pending solve to running, or ``None`` when nothing is due.

        The scan and the claim are separate statements, so a row read as pending can be finished by
        something else before this claims it. That is an expected race rather than a fault -- a
        tradeoff request supersedes a pending solve, and the reaper finishes an abandoned one -- so
        a lost claim is counted, skipped, and the next due operation is tried.

        The claim's queue delay is observed here, because this is where the wait ends: what it
        measures is the worker falling behind the instant an operation became due.
        """
        now = self._clock()
        for due in await self._queue.due(kind=SOLVE, at=now):
            try:
                claimed = await self._lifecycle.claim(due.id)
            except OperationMovedOn as lost:
                CLAIM_RACES_LOST.inc()
                _log.info(
                    "solving.claim.race_lost",
                    operation_id=str(due.id),
                    held=lost.held,
                    attempted=lost.attempted,
                )
                continue
            OPERATION_QUEUE_DELAY.labels(kind=claimed.kind).observe(
                (now - due.scheduled_for).total_seconds()
            )
            return claimed
        return None

    @measured("solve_coordinator")
    async def finish(self, op: OperationRecord, outcome: Outcome) -> OperationRecord:
        """Perform ``op``'s terminal step, enqueueing exactly one follow-up for a supersession.

        A superseded solve's follow-up carries the same candidate adjustment, so a pin landing mid
        solve does not discard the concession the user asked for. It is due now: the mutation that
        superseded this solve has already been made, so there is nothing left to coalesce with it.
        """
        closed = await self._closed(op, outcome)
        if not isinstance(outcome, Superseded) or outcome.superseded_by is not None:
            return closed
        follow_up = await self._enqueued(
            self._week_of(closed),
            due_at=self._clock(),
            candidate=closed.candidate_adjustment,
            at_version=closed.input_version,
        )
        return await self._named(closed, follow_up)

    async def _closed(self, op: OperationRecord, outcome: Outcome) -> OperationRecord:
        """``op``'s terminal step, counted on the two instruments the debounce is read from."""
        finished = await self._lifecycle.finish(op.id, outcome)
        SOLVE_TALLY.finished(finished.status)
        return finished

    async def _named(
        self, superseded: OperationRecord, successor: OperationRecord
    ) -> OperationRecord:
        """The superseded row, naming the operation that displaced it.

        A second write rather than a value on the step that closed it, because the successor cannot
        exist until the row is closed: at most one non-terminal solve per week is a partial unique
        index, so creating the replacement first is refused by the database. Both writes are in the
        caller's transaction, so nothing observes a supersession with no successor.
        """
        named = await self._operations.name_supersessor(superseded.id, superseded_by=successor.id)
        _log.info(
            "solving.solve.superseded",
            iso_week=str(self._week_of(superseded)),
            operation_id=str(superseded.id),
            superseded_by=str(successor.id),
            input_version=superseded.input_version,
            carried_a_candidate=superseded.candidate_adjustment is not None,
        )
        # The row was just stepped to `superseded` with no successor named, in this transaction, so
        # the only statement that could have taken it is this one.
        if named is None:  # pragma: no cover - unreachable inside one transaction
            message = f"operation {superseded.id} lost its supersession between two of its writes"
            raise RuntimeError(message)
        return named

    async def _for_a_candidate(
        self,
        week: IsoWeek,
        in_flight: OperationRecord | None,
        candidate: JsonDocument,
        *,
        at_version: int,
    ) -> OperationRecord:
        """A tradeoff's own solve, which never joins one that already exists.

        A PENDING operation is closed and this request's operation takes its place, so the
        supersession names this one rather than a follow-up: the replacement is the tradeoff, and
        enqueueing a follow-up as well would be a second non-terminal solve the index refuses.
        """
        if in_flight is not None and in_flight.status == RUNNING:
            raise SolveIsRunning(week)
        closed = None if in_flight is None else await self._closed(in_flight, Superseded())
        created = await self._enqueued(
            week, due_at=self._clock(), candidate=candidate, at_version=at_version
        )
        if closed is not None:
            await self._named(closed, created)
        return created

    def _week_of(self, op: OperationRecord) -> IsoWeek:
        """The week this solve names, which its table's check constraint requires it to have."""
        if op.iso_week is None:  # pragma: no cover - unreachable while that constraint holds
            message = f"solve {op.id} names no week, which its table forbids"
            raise RuntimeError(message)
        return op.iso_week

    async def _scheduled(
        self, week: IsoWeek, *, immediate: bool, at_version: int
    ) -> OperationRecord:
        """The first solve for this week: due now, or at the end of the debounce window."""
        now = self._clock()
        return await self._enqueued(
            week,
            due_at=now if immediate else now + self._debounce,
            candidate=None,
            at_version=at_version,
        )

    async def _joined(
        self, week: IsoWeek, in_flight: OperationRecord, *, immediate: bool, at_version: int
    ) -> OperationRecord:
        """The operation already in flight, its due instant pulled forward if this is immediate.

        A pending tradeoff is left alone by an ordinary mutation, candidate and due instant both:
        the version bump this mutation already made will supersede it once it runs, and the
        follow-up carries the concession forward.
        """
        carries_a_candidate = in_flight.candidate_adjustment is not None
        may_move = in_flight.status == PENDING and not carries_a_candidate
        if immediate and may_move:
            in_flight = (
                await self._operations.bring_forward(in_flight.id, to=self._clock()) or in_flight
            )
        _log.info(
            "solving.solve.joined",
            iso_week=str(week),
            operation_id=str(in_flight.id),
            status=in_flight.status,
            at_version=at_version,
            immediate=immediate,
            joined_a_tradeoff=carries_a_candidate,
        )
        return in_flight

    async def _enqueued(
        self,
        week: IsoWeek,
        *,
        due_at: datetime,
        candidate: JsonDocument | None,
        at_version: int | None,
    ) -> OperationRecord:
        """One new pending solve for this week, and the line that says why it was created."""
        created = await self._lifecycle.enqueue(
            kind=SOLVE, iso_week=week, due_at=due_at, candidate_adjustment=candidate
        )
        _log.info(
            "solving.solve.scheduled",
            iso_week=str(week),
            operation_id=str(created.id),
            at_version=at_version,
            due_in_seconds=(due_at - self._clock()).total_seconds(),
            carries_a_candidate=candidate is not None,
        )
        return created
