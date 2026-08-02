"""The ``operations`` table: one tracked long-running job.

Two indexes on this table are load-bearing rather than incidental.

The PARTIAL UNIQUE index is the single-flight invariant. At most one solve per tenant per
week may be non-terminal, and it is the database that says so: a mutation arriving while a
solve runs must bump the week's input version and create no second operation, and a bug
that tried to would be rejected here rather than producing two solves racing to write one
week.

The partial index on ``scheduled_for`` is what the worker's claim reads. That query is
deliberately not tenant-led, because the worker serves every tenant, so the index is on the
one column it orders by and is narrowed by a ``WHERE`` clause instead of by a leading
column.

``input_version`` is null until the worker LOADS inputs, and is stamped then rather than at
creation. Stamping at creation would make a coalesced burst waste a solve: the operation
would be guarded on a version two mutations old and would be superseded by its own
coalescing.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from syncr_api.core.columns import ISO_WEEK_LENGTH, JsonObject, values_in
from syncr_api.core.orm import Base
from syncr_api.core.tenancy import TENANT_ID_COLUMN, TenantScoped
from syncr_api.plans.config import PLAN_REVISIONS_TABLE
from syncr_api.solving.config import (
    ERROR_CODE_MAX_LENGTH,
    FAILED,
    FIRST_ATTEMPT,
    NON_TERMINAL_STATUSES,
    OPERATION_KINDS,
    OPERATION_STATUSES,
    OPERATIONS_TABLE,
    PENDING,
    SOLVE,
)

STATUS_LENGTH = 16
KIND_LENGTH = 16


def _in_flight_solve() -> str:
    statuses = ", ".join(f"'{status}'" for status in NON_TERMINAL_STATUSES)
    return f"kind = '{SOLVE}' AND status IN ({statuses})"


class Operation(Base, TenantScoped):
    """One solve, materialize, calendar sync, or projection, tracked to a terminal state."""

    __tablename__ = OPERATIONS_TABLE

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(KIND_LENGTH), nullable=False)
    status: Mapped[str] = mapped_column(String(STATUS_LENGTH), nullable=False)
    # The target is one of two things and never both: a week for a solve, a materialize, or
    # a projection, and a calendar source for a sync.
    iso_week: Mapped[str | None] = mapped_column(String(ISO_WEEK_LENGTH), nullable=True)
    source_id: Mapped[UUID | None] = mapped_column(nullable=True)
    input_version: Mapped[int | None] = mapped_column(nullable=True)
    # An UNPERSISTED tradeoff concession this solve must fold into its inputs. The only
    # channel from the request to the worker, because requesting a tradeoff persists
    # nothing.
    candidate_adjustment: Mapped[JsonObject | None] = mapped_column(JSONB, nullable=True)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{PLAN_REVISIONS_TABLE}.id", ondelete="CASCADE"), nullable=True
    )
    # No foreign key, deliberately: this table is pruned, so a constraint pointing into it
    # would either block the prune or delete the newer operation because the older one aged
    # out.
    superseded_by: Mapped[UUID | None] = mapped_column(nullable=True)
    attempt: Mapped[int] = mapped_column(nullable=False, default=FIRST_ATTEMPT)
    error_code: Mapped[str | None] = mapped_column(String(ERROR_CODE_MAX_LENGTH), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The exact resolved inputs a failed solve read, so a production failure is reproducible
    # locally. Written only on failure, and pruned with the row at 90 days.
    failed_input_snapshot: Mapped[JsonObject | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        CheckConstraint(values_in("kind", OPERATION_KINDS), name="kind_is_known"),
        CheckConstraint(values_in("status", OPERATION_STATUSES), name="status_is_known"),
        CheckConstraint("num_nonnulls(iso_week, source_id) = 1", name="target_is_one_thing"),
        CheckConstraint(f"attempt >= {FIRST_ATTEMPT}", name="attempt_starts_at_one"),
        CheckConstraint(
            "(error_code IS NULL) = (error_message IS NULL)", name="error_states_both_halves"
        ),
        CheckConstraint(
            f"failed_input_snapshot IS NULL OR status = '{FAILED}'",
            name="snapshot_belongs_to_a_failure",
        ),
        # The single-flight invariant, enforced by the schema rather than by convention.
        Index(
            "uq_operations_tenant_id_iso_week_in_flight_solve",
            TENANT_ID_COLUMN,
            "iso_week",
            unique=True,
            postgresql_where=text(_in_flight_solve()),
        ),
        Index("ix_operations_tenant_id_iso_week", TENANT_ID_COLUMN, "iso_week"),
        # What `claim_next` reads: the earliest due pending operation, for any tenant.
        Index(
            "ix_operations_pending_scheduled_for",
            "scheduled_for",
            postgresql_where=text(f"status = '{PENDING}'"),
        ),
        # What the retention sweep reads: terminal rows past their window.
        Index("ix_operations_finished_at", "finished_at"),
    )
