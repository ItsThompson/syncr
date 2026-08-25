"""``OperationLifecycle``: the one place an operation is created and stepped.

The lifecycle has one home so the state machine has one enforcement. Four callers step an operation
today -- a forced calendar sync that does its own work inline, the plan horizon maintainer, the
reaper, and the retry -- and the solve coordinator makes five. Which steps exist, and why the reaper
needs no step of its own, are :mod:`syncr_api.solving.transitions`, which owns the machine and
states that argument once.

**It takes no principal, and that is why it is not the module's service.** Every caller is either
the worker, which has no credential, or a request-facing service that has already authorized the
request it is serving. ``service.py`` holds the two READS a route answers with, each of which does
take a principal first, so authorization stays in the one place per request the boundary requires.

Three methods, and the shape of the third is why there are only three. ``enqueue`` creates a
pending operation. ``claim`` takes one that exists. ``finish`` performs the terminal step, taking
ONE outcome value rather than a status plus five optional arguments, because each ending carries
different facts and a signature holding all of them at once cannot say which combinations are
legal.

**Selecting which operation to claim is not here.** ``claim`` steps an operation the caller already
holds, which is what an inline caller needs: it created the row, so there is nothing to select. The
worker's claim scans every tenant's due operations to decide WHICH one to take, and that selection
belongs with the debounce and the conditional write it exists to serve, in the solve coordinator.
Splitting it this way keeps one transition in one place while leaving the scan to the component
whose invariant it is.

**The reaper is not here either**, because its sweep enumerates tenants exactly as the calendar poll
does, which makes it a worker duty rather than a method on one tenant's lifecycle. It finishes each
expired claim through :meth:`finish`, so the attempt bound applies to a dying worker exactly as it
applies to a raising solver.

**A failure decides its own retry, in one expression, before it writes.** The snapshot is therefore
kept only on the last attempt and the row that comes back to the queue carries none. The table
forbids a snapshot on any status but ``failed``, so the alternative is a second write to clear one,
and a rule enforced by two writes is a rule that holds until one of them is forgotten.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, assert_never

from syncr_api.solving.config import (
    FAILED,
    MAX_ATTEMPTS,
    PENDING,
    RETRY_BACKOFF,
    RUNNING,
    SOLVE,
    SUCCEEDED,
    SUPERSEDED,
    OperationKind,
)
from syncr_api.solving.errors import OperationMovedOn, OperationNotFound
from syncr_api.solving.metrics import SOLVE_TALLY
from syncr_api.solving.outcomes import Failed, Outcome, Succeeded, Superseded
from syncr_api.solving.transitions import may_retry
from syncr_common.logging import get_logger
from syncr_common.metrics import measured

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from syncr_api.core.clock import Clock
    from syncr_api.core.columns import JsonDocument
    from syncr_api.solving.config import OperationStatus
    from syncr_api.solving.records import OperationRecord
    from syncr_api.solving.repository import OperationRepository
    from syncr_domain.identifiers import OperationId
    from syncr_domain.weeks import IsoWeek

_log = get_logger("syncr.solving")


class OperationLifecycle:
    """Creates and steps one tenant's operations."""

    def __init__(
        self, operations: OperationRepository, clock: Clock, *, max_attempts: int = MAX_ATTEMPTS
    ) -> None:
        self._operations = operations
        self._clock = clock
        self._max_attempts = max_attempts

    @measured("operations")
    async def enqueue(
        self,
        *,
        kind: OperationKind,
        iso_week: IsoWeek | None = None,
        source_id: UUID | None = None,
        due_at: datetime | None = None,
        candidate_adjustment: JsonDocument | None = None,
        session_mode_active: bool = False,
    ) -> OperationRecord:
        """Create one pending operation, due now unless ``due_at`` says later.

        Due now is the default because it is the honest one for every caller that is not
        debouncing: the horizon maintainer, a re-solve control and a tradeoff request each bypass
        the debounce window, and the window itself belongs to the coordinator rather than here.

        ``session_mode_active`` carries what the caller stated about the weekly session. The
        solve coordinator passes its own caller's answer through; every other creator of an
        operation is time-driven or inline and states nothing, which the default spells.
        """
        created = await self._operations.enqueue(
            kind=kind,
            scheduled_for=due_at or self._clock(),
            iso_week=iso_week,
            source_id=source_id,
            candidate_adjustment=candidate_adjustment,
            session_mode_active=session_mode_active,
        )
        _log.info(
            "solving.operation.enqueued",
            operation_id=str(created.id),
            kind=created.kind,
            iso_week=None if created.iso_week is None else str(created.iso_week),
            source_id=None if created.source_id is None else str(created.source_id),
        )
        return created

    @measured("operations")
    async def claim(self, operation_id: OperationId) -> OperationRecord:
        """Step one pending operation to ``running``, stamping when its lease began.

        The lease is read against ``started_at`` and a configured length rather than stored as an
        expiry, because the length is a property of the deployment and not of the row.
        """
        stepped = await self._operations.mark_running(operation_id, at=self._clock())
        return await self._or_refused(operation_id, stepped, to=RUNNING)

    @measured("operations")
    async def finish(self, operation_id: OperationId, outcome: Outcome) -> OperationRecord:
        """Perform the terminal step this outcome names, retrying a failure that has one left.

        A retried failure comes back as ``pending`` with its attempt raised and its next due
        instant pushed out. Both writes are in the caller's transaction, so an operation is never
        observed as failed when it is going to run again.

        **A solve's ending is counted here rather than by the caller**, because this is the one
        place every operation is stepped: the reaper, the retry, the coordinator and the inline
        calendar sync all arrive through it. Counted in the coordinator instead, the counter read
        "solves that reached a terminal status" while omitting every solve the REAPER finished, and
        the supersession ratio an operator tunes the debounce on was a share of a subset.
        """
        stepped = await self._stepped_by(operation_id, outcome)
        if stepped.kind == SOLVE:
            SOLVE_TALLY.finished(stepped.status)
        return stepped

    async def _stepped_by(self, operation_id: OperationId, outcome: Outcome) -> OperationRecord:
        match outcome:
            case Succeeded():
                stepped = await self._operations.mark_succeeded(
                    operation_id,
                    at=self._clock(),
                    result_revision_id=outcome.result_revision_id,
                )
                return await self._or_refused(operation_id, stepped, to=SUCCEEDED)
            case Superseded():
                stepped = await self._operations.mark_superseded(
                    operation_id, at=self._clock(), superseded_by=outcome.superseded_by
                )
                return await self._or_refused(operation_id, stepped, to=SUPERSEDED)
            case Failed():
                return await self._failed(operation_id, outcome)
            case _:  # pragma: no cover - unreachable while the union holds three members
                assert_never(outcome)

    async def _failed(self, operation_id: OperationId, outcome: Failed) -> OperationRecord:
        held = await self._held(operation_id)
        retrying = may_retry(status=FAILED, attempt=held.attempt, max_attempts=self._max_attempts)
        failed = await self._or_refused(
            operation_id,
            await self._operations.mark_failed(
                operation_id,
                at=self._clock(),
                code=outcome.code,
                message=outcome.message,
                snapshot=None if retrying else outcome.snapshot,
            ),
            to=FAILED,
        )
        _log.info(
            "solving.operation.failed",
            operation_id=str(operation_id),
            kind=failed.kind,
            attempt=failed.attempt,
            max_attempts=self._max_attempts,
            error_code=outcome.code,
            retrying=retrying,
        )
        return failed if not retrying else await self._retried(failed)

    async def _retried(self, failed: OperationRecord) -> OperationRecord:
        """The next attempt, queued behind a backoff that doubles with the attempts spent.

        A solver fault is not cleared by retrying at once, and nothing waits on the retry: the
        previous live plan is untouched and still projected while it sits in the queue.
        """
        backoff = RETRY_BACKOFF * 2 ** (failed.attempt - 1)
        attempt = failed.attempt + 1
        rescheduled = await self._operations.reschedule(
            failed.id, attempt=attempt, scheduled_for=self._clock() + backoff
        )
        _log.info(
            "solving.operation.rescheduled",
            operation_id=str(failed.id),
            attempt=attempt,
            seconds_from_now=backoff / timedelta(seconds=1),
        )
        return await self._or_refused(failed.id, rescheduled, to=PENDING)

    async def _held(self, operation_id: OperationId) -> OperationRecord:
        held = await self._operations.find(operation_id)
        if held is None:
            raise OperationNotFound(
                f"operation {operation_id} is not one of this tenant's, so it cannot be stepped",
                operation_id=operation_id,
                held=None,
                attempted=FAILED,
            )
        return held

    async def _or_refused(
        self, operation_id: OperationId, stepped: OperationRecord | None, *, to: OperationStatus
    ) -> OperationRecord:
        """The stepped row, or a stated refusal naming the status the row was actually in.

        The write is what decides legality, so this reads the row only to REPORT a refusal, and the
        two refusals are different types because a caller can usually tell them apart: an absent row
        was never raced into existence, and a row holding another status may have been stepped by
        something else since this caller read it.
        """
        if stepped is not None:
            return stepped
        held = await self._operations.find(operation_id)
        if held is None:
            raise OperationNotFound(
                f"operation {operation_id} cannot become {to!r}: this tenant has no such row",
                operation_id=operation_id,
                held=None,
                attempted=to,
            )
        raise OperationMovedOn(
            f"operation {operation_id} cannot become {to!r} from {held.status!r}: the status set "
            "is a state machine, and a step it does not name would overwrite a state something "
            "else committed",
            operation_id=operation_id,
            held=held.status,
            attempted=to,
        )
