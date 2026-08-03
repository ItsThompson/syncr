"""Persistence for ``operations``: enqueue one, read the week's in-flight one, complete one.

Deliberately few methods. The coordinator's claim, terminal transitions, the follow-up
enqueue, the reaper, and the retention sweep all belong to the ticket that builds the worker
loop, and writing their bodies before the loop exists would be inventing a protocol for a
caller nobody has read. What exists here is what the schema needs proven: a row can be
enqueued, the single-flight invariant is enforced by the database rather than by the method
that inserts, and an operation whose work a request performed inline can be closed in that
request's own transaction.
"""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, cast
from uuid import uuid4

from syncr_api.core.repository import TenantScopedRepository
from syncr_api.solving.config import (
    FIRST_ATTEMPT,
    NON_TERMINAL_STATUSES,
    PENDING,
    SUCCEEDED,
    OperationKind,
    OperationStatus,
)
from syncr_api.solving.models import Operation
from syncr_api.solving.records import OperationRecord
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from syncr_api.core.columns import JsonDocument
    from syncr_domain.identifiers import OperationId


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
        return _as_record(operation)

    async def find(self, operation_id: OperationId) -> OperationRecord | None:
        """The operation with this id, or ``None`` when this tenant has no such row."""
        found = await self._session.scalar(
            self.scoped_select(Operation).where(Operation.id == operation_id)
        )
        return _as_record(found) if found is not None else None

    async def in_flight(self, iso_week: IsoWeek, *, kind: OperationKind) -> OperationRecord | None:
        """The week's non-terminal operation of this kind, or ``None``."""
        found = await self._session.scalar(
            self.scoped_select(Operation).where(
                Operation.iso_week == str(iso_week),
                Operation.kind == kind,
                Operation.status.in_(NON_TERMINAL_STATUSES),
            )
        )
        return _as_record(found) if found is not None else None

    async def mark_succeeded(self, operation_id: OperationId, *, at: datetime) -> OperationRecord:
        """Complete one operation whose work finished inside the caller's own transaction.

        The narrow case only: an operation a request performed synchronously, so there is no
        claim to release, no attempt to increment, and no failure to record. **The worker-loop
        ticket owns the general transition logic** (the claim, the terminal transitions, the
        reaper, and the retention sweep); this is not a second lifecycle and must not grow into
        one.
        """
        await self._session.execute(
            self.scoped_update(Operation)
            .where(Operation.id == operation_id)
            .values(status=SUCCEEDED, started_at=at, finished_at=at)
        )
        completed = await self.find(operation_id)
        if completed is None:  # pragma: no cover - the caller holds the row it just created
            message = f"operation {operation_id} vanished before it could be completed"
            raise RuntimeError(message)
        return completed


def _as_record(operation: Operation) -> OperationRecord:
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
