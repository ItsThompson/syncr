"""The wire shape of an ``Operation``: the resource a long-running job is followed through.

Its canonical home rather than the calling module's, because four kinds of job answer with one:
a solve, a materialize, a calendar sync, and a projection. A shape declared inside the first
module that needed one would have to be moved by the second.

``target`` is one of two things and never both, exactly as the table's check constraint says: a
week for a solve, a materialize, or a projection, and a calendar source for a sync. It is nested
rather than flattened into two nullable fields, so a client reads which kind of target it has
rather than testing two columns for null.

``error`` is nested for the same reason: a code without a message and a message without a code
are both meaningless, and the row's own constraint already says the two arrive together.

``statement`` is what makes ``superseded`` reported distinctly from ``failed``. The status word
differs and so does the sentence, because supersession is the expected outcome of editing quickly:
presenting it as a failure would make normal use look broken. Every sentence names what still
works, which is the rule this api's error details and its degradation notices both follow.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - pydantic resolves annotations at runtime
from typing import TYPE_CHECKING, Self
from uuid import UUID  # noqa: TC003 - as above

from pydantic import Field

from syncr_api.core.schemas import WireModel
from syncr_api.solving.config import (
    PAGE_LIMIT_DEFAULT,
    PAGE_LIMIT_MAX,
    OperationKind,
    OperationStatus,
)
from syncr_api.solving.reporting import statement

if TYPE_CHECKING:
    from syncr_api.solving.records import OperationRecord


class OperationTarget(WireModel):
    """What an operation acts on. Exactly one member is set."""

    iso_week: str | None = Field(
        default=None, description="The week a solve, a materialize, or a projection is for."
    )
    source_id: UUID | None = Field(default=None, description="The calendar source a sync is for.")


class OperationError(WireModel):
    """Why an operation failed. Absent while it has not."""

    code: str
    message: str


class OperationResponse(WireModel):
    """One tracked long-running job, as a client follows it.

    ``attempt`` is exposed because a retrying job must not be silent: a count that changes is how
    progress is reported in this product, and there is no spinner anywhere to imply movement.
    """

    id: UUID
    kind: OperationKind
    status: OperationStatus
    target: OperationTarget
    input_version: int | None = Field(
        default=None,
        description="The input snapshot this solve read. Null until the worker loads inputs.",
    )
    scheduled_for: datetime = Field(description="When this operation became due.")
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result_revision_id: UUID | None = None
    superseded_by: UUID | None = None
    attempt: int = Field(description="One-based, so a retrying job reads as 'try 2 of N'.")
    error: OperationError | None = None
    statement: str = Field(
        description=(
            "One sentence naming what this status means and what still works. A superseded "
            "operation states that a later change of your own displaced it and that a follow-up "
            "is running, which is not a failure."
        )
    )

    @classmethod
    def of(cls, record: OperationRecord) -> Self:
        """The wire shape of a stored operation."""
        return cls(
            id=record.id,
            kind=record.kind,
            status=record.status,
            target=OperationTarget(
                iso_week=None if record.iso_week is None else str(record.iso_week),
                source_id=record.source_id,
            ),
            input_version=record.input_version,
            scheduled_for=record.scheduled_for,
            started_at=record.started_at,
            finished_at=record.finished_at,
            result_revision_id=record.result_revision_id,
            superseded_by=record.superseded_by,
            attempt=record.attempt,
            error=(
                None
                if record.error_code is None or record.error_message is None
                else OperationError(code=record.error_code, message=record.error_message)
            ),
            statement=statement(record.status),
        )


class OperationsResponse(WireModel):
    """One page of tracked operations, most recently scheduled first.

    Cursor-paginated rather than offset-paginated. An operation created while a client is paging
    shifts every offset after it, which would silently skip a row.
    """

    operations: list[OperationResponse]
    next_cursor: str | None = Field(
        default=None,
        description=(
            "Pass back as `cursor` to read the next page. Null when this is the last page. "
            f"A page holds up to `limit` operations, {PAGE_LIMIT_DEFAULT} by default and "
            f"{PAGE_LIMIT_MAX} at most."
        ),
    )
