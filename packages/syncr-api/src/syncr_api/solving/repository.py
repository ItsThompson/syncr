"""Persistence for ``operations``: enqueue one, read one, step one, and sweep the terminal ones.

Every write here is one statement, and every status change carries its own legality in its
``WHERE`` clause: the statuses a step may leave come from
:func:`~syncr_api.solving.transitions.statuses_that_may_become`, so a row that has already moved
on is not written and the method answers ``None`` rather than overwriting a state somebody else
committed. That is what makes the state machine atomic instead of a check performed before a
write. Naming the invariant belongs to the service, which holds the status the row was in.

``iso_week`` is never derived here and never optional-by-accident: a solve, a materialize and a
projection name a week, a calendar sync names a source, and the table's own check constraint
refuses a row that names both or neither.

**Two things are deliberately elsewhere.** The worker's claim scans every tenant's due operations
to decide WHICH one to take, and that selection is the solve coordinator's, along with the debounce
it exists to serve. The two set-wide statements maintenance runs are
:mod:`syncr_api.solving.sweeps`, so a route cannot reach a statement that deletes.
"""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, cast
from uuid import uuid4

from sqlalchemy import literal, tuple_

from syncr_api.core.repository import TenantScopedRepository
from syncr_api.solving.config import (
    FAILED,
    FIRST_ATTEMPT,
    NON_TERMINAL_STATUSES,
    PENDING,
    RUNNING,
    SUCCEEDED,
    SUPERSEDED,
    OperationKind,
    OperationStatus,
)
from syncr_api.solving.models import Operation
from syncr_api.solving.records import OperationRecord
from syncr_api.solving.transitions import statuses_that_may_become
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy import Select, Update

    from syncr_api.core.columns import JsonDocument
    from syncr_domain.identifiers import OperationId, PlanRevisionId


class OperationRepository(TenantScopedRepository):
    """One tenant's tracked operations."""

    async def enqueue(
        self,
        *,
        kind: OperationKind,
        scheduled_for: datetime,
        iso_week: IsoWeek | None = None,
        source_id: UUID | None = None,
        candidate_adjustment: JsonDocument | None = None,
    ) -> OperationRecord:
        """Create one pending operation for a week or for a calendar source.

        The row is rejected when a solve for this week is already in flight, by the partial
        unique index. A caller that wants to coalesce reads :meth:`in_flight` first; the
        index is what makes the read a check rather than the whole guarantee.
        """
        operation = Operation(
            id=uuid4(),
            tenant_id=self.tenant_id,
            kind=kind,
            status=PENDING,
            iso_week=None if iso_week is None else str(iso_week),
            source_id=source_id,
            input_version=None,
            candidate_adjustment=(
                None if candidate_adjustment is None else dict(candidate_adjustment)
            ),
            scheduled_for=scheduled_for,
            attempt=FIRST_ATTEMPT,
        )
        self._session.add(operation)
        # Flushed here so the single-flight rejection surfaces as this call's failure
        # rather than at the transaction's commit.
        await self._session.flush()
        return as_record(operation)

    async def find(self, operation_id: OperationId) -> OperationRecord | None:
        """The operation with this id, or ``None`` when this tenant has no such row."""
        found = await self._session.scalar(
            self.scoped_select(Operation).where(Operation.id == operation_id)
        )
        return as_record(found) if found is not None else None

    async def read_failed_input_snapshot(self, operation_id: OperationId) -> JsonDocument | None:
        """The resolved inputs a failed operation read, by identifier.

        Absent from :class:`~syncr_api.solving.records.OperationRecord` on purpose: it is a whole
        resolved week, and every reader of an operation on the wire or in the worker wants the
        status and the attempt instead. Loading it into every read would carry a week of plan data
        through paths that never look at it, so it is read here and only when something wants it,
        which is a person reproducing a production failure locally.
        """
        return await self._session.scalar(
            self.scoped_select(Operation)
            .where(Operation.id == operation_id)
            .with_only_columns(Operation.failed_input_snapshot)
        )

    async def in_flight(self, iso_week: IsoWeek, *, kind: OperationKind) -> OperationRecord | None:
        """The week's non-terminal operation of this kind, or ``None``."""
        return await self.in_flight_of(iso_week, kinds=(kind,))

    async def in_flight_of(
        self, iso_week: IsoWeek, *, kinds: Sequence[OperationKind]
    ) -> OperationRecord | None:
        """The week's non-terminal operation of any of these kinds, the most recent first.

        One kind is the single-flight case and answers at most one row by the partial unique index.
        Several kinds can answer more than one, so the order is the table's own: what a caller
        asking "is anything still working on this week" wants is the newest of them.
        """
        found = await self._session.scalar(
            self._ordered()
            .where(
                Operation.iso_week == str(iso_week),
                Operation.kind.in_(sorted(kinds)),
                Operation.status.in_(NON_TERMINAL_STATUSES),
            )
            .limit(1)
        )
        return as_record(found) if found is not None else None

    async def latest_of(
        self, iso_week: IsoWeek, *, kinds: Sequence[OperationKind]
    ) -> OperationRecord | None:
        """The week's most recently scheduled operation of any of these kinds, or ``None``.

        Whatever its status, because the caller that wants it is asking what happened LAST: a
        method that filtered to the terminal ones would answer the same question twice with
        :meth:`in_flight_of` and leave the caller to reconcile two readings of one row set.
        """
        found = await self._session.scalar(
            self._ordered()
            .where(Operation.iso_week == str(iso_week), Operation.kind.in_(sorted(kinds)))
            .limit(1)
        )
        return as_record(found) if found is not None else None

    async def page(
        self,
        *,
        limit: int,
        status: OperationStatus | None = None,
        kind: OperationKind | None = None,
        after: tuple[datetime, OperationId] | None = None,
    ) -> list[OperationRecord]:
        """One page of this tenant's operations, most recently scheduled first.

        Keyset rather than offset, on ``(scheduled_for, id)``, which is the order the page is read
        in: an operation created while a client is paging shifts every offset after it, and an
        offset page would then silently skip a row.
        """
        statement = self._ordered()
        if status is not None:
            statement = statement.where(Operation.status == status)
        if kind is not None:
            statement = statement.where(Operation.kind == kind)
        if after is not None:
            scheduled_for, operation_id = after
            # The bound is a row value rather than two comparisons, so the cursor names one
            # position in one order: `scheduled_for < x OR (scheduled_for = x AND id < y)` written
            # out is the same predicate with two places for the order to be restated wrongly.
            statement = statement.where(
                tuple_(Operation.scheduled_for, Operation.id)
                < tuple_(literal(scheduled_for), literal(operation_id))
            )
        return [as_record(row) for row in await self._session.scalars(statement.limit(limit))]

    def _ordered(self) -> Select[tuple[Operation]]:
        """This tenant's operations, newest first. The one statement of that order.

        The id is a tie-break rather than an order anyone reads: two operations scheduled against
        one instant would otherwise come back in whichever order the scan produced, and a keyset
        cursor needs a total order or a page boundary can drop a row.
        """
        return self.scoped_select(Operation).order_by(
            Operation.scheduled_for.desc(), Operation.id.desc()
        )

    async def mark_running(
        self, operation_id: OperationId, *, at: datetime
    ) -> OperationRecord | None:
        """Claim one pending operation, or ``None`` when it is no longer pending."""
        return await self._stepped(
            operation_id, self._to(operation_id, RUNNING).values(started_at=at)
        )

    async def mark_succeeded(
        self,
        operation_id: OperationId,
        *,
        at: datetime,
        result_revision_id: PlanRevisionId | None = None,
    ) -> OperationRecord | None:
        """Complete one running operation, naming the revision it appended if it appended one."""
        return await self._stepped(
            operation_id,
            self._to(operation_id, SUCCEEDED).values(
                finished_at=at, result_revision_id=result_revision_id
            ),
        )

    async def mark_superseded(
        self, operation_id: OperationId, *, at: datetime, superseded_by: OperationId | None = None
    ) -> OperationRecord | None:
        """Close one operation whose result a later input state displaced."""
        return await self._stepped(
            operation_id,
            self._to(operation_id, SUPERSEDED).values(finished_at=at, superseded_by=superseded_by),
        )

    async def mark_failed(
        self,
        operation_id: OperationId,
        *,
        at: datetime,
        code: str,
        message: str,
        snapshot: JsonDocument | None = None,
    ) -> OperationRecord | None:
        """Record one running operation's failure, and the inputs it read if they are kept.

        The snapshot is written only when the caller means the failure to be the last one: the
        table forbids a snapshot on any status but ``failed``, and a retried attempt returns the
        row to ``pending``, so a snapshot written on a retryable failure would have to be cleared
        again by the step that reschedules it.
        """
        return await self._stepped(
            operation_id,
            self._to(operation_id, FAILED).values(
                finished_at=at,
                error_code=code,
                error_message=message,
                failed_input_snapshot=None if snapshot is None else dict(snapshot),
            ),
        )

    async def reschedule(
        self, operation_id: OperationId, *, attempt: int, scheduled_for: datetime
    ) -> OperationRecord | None:
        """Return one failed operation to the queue as its next attempt.

        ``started_at`` and ``finished_at`` are cleared because the row is no longer running and no
        longer finished. The error is kept: a retrying job must not be silent, and the pair of a
        rising attempt and the last cause is what says it is retrying rather than stuck.
        """
        return await self._stepped(
            operation_id,
            self._to(operation_id, PENDING).values(
                attempt=attempt,
                scheduled_for=scheduled_for,
                started_at=None,
                finished_at=None,
            ),
        )

    def _to(self, operation_id: OperationId, status: OperationStatus) -> Update:
        """The write one step performs, refusing a row that cannot take that step.

        The legality is the ``WHERE`` clause rather than a read before the write, so two callers
        racing on one row cannot both find it steppable and both step it.
        """
        return (
            self.scoped_update(Operation)
            .where(
                Operation.id == operation_id,
                Operation.status.in_(sorted(statuses_that_may_become(status))),
            )
            .values(status=status)
        )

    async def _stepped(
        self, operation_id: OperationId, statement: Update
    ) -> OperationRecord | None:
        """Apply one step and answer the row it produced, or ``None`` when it applied to nothing."""
        if not await self._affected_rows(statement):
            return None
        stepped = await self.find(operation_id)
        if stepped is None:  # pragma: no cover - the statement just wrote this row
            message = f"operation {operation_id} vanished between its own write and its read"
            raise RuntimeError(message)
        return stepped


def as_record(operation: Operation) -> OperationRecord:
    return OperationRecord(
        id=operation.id,
        tenant_id=operation.tenant_id,
        kind=cast("OperationKind", operation.kind),
        status=cast("OperationStatus", operation.status),
        iso_week=None if operation.iso_week is None else IsoWeek.parse(operation.iso_week),
        source_id=operation.source_id,
        input_version=operation.input_version,
        candidate_adjustment=deepcopy(operation.candidate_adjustment),
        scheduled_for=operation.scheduled_for,
        started_at=operation.started_at,
        finished_at=operation.finished_at,
        result_revision_id=operation.result_revision_id,
        superseded_by=operation.superseded_by,
        attempt=operation.attempt,
        error_code=operation.error_code,
        error_message=operation.error_message,
    )
