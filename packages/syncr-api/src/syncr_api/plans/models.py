"""The storage split: the append-only revision log, the single slot, and the version row.

Three tables, and the difference between them is the whole design of this section.

``plan_revisions`` is a fact per time the live plan changed. Its ``document`` column is
authoritative and its ``iso_week`` is re-derived from that document on every write, so no
column can describe a document it does not match. Nothing updates a row and nothing
deletes one.

``pending_proposals`` is the latest solver output awaiting assent. ``(tenant_id,
iso_week)`` is its PRIMARY KEY, so "at most one proposal per week" is a property of the
database rather than a rule the upsert has to get right. Nobody agreed to a proposal and
it may never have been rendered, so it is not a fact and it is replaced in place.

``week_input_versions`` is the single serialization point for anything that invalidates a
running solve. One row per week, one monotonic counter, and the conditional write in the
worker's commit path is a comparison against it under a row lock.

The permanent week-scoped records that accumulate around these three, and are never
pruned, live in ``facts.py``.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from syncr_api.core.columns import ISO_WEEK_LENGTH, NULLABLE_JSONB, JsonObject, values_in
from syncr_api.core.orm import Base
from syncr_api.core.tenancy import TENANT_ID_COLUMN, TenantScoped
from syncr_api.plans import facts as _facts  # noqa: F401 - see the note below
from syncr_api.plans.config import (
    APPROVED,
    FIRST_INPUT_VERSION,
    PENDING_PROPOSALS_TABLE,
    PLAN_REVISIONS_TABLE,
    REVISION_REASONS,
    REVISION_STATUSES,
    WEEK_INPUT_VERSIONS_TABLE,
)

# `facts` is imported for the side effect of attaching its tables to `Base.metadata`.
# Importing this module therefore brings every plan-side table under the schema rules and
# into `--autogenerate`, whichever of the two modules a caller reached for.

STATUS_LENGTH = 16
REASON_LENGTH = 32


class PlanRevision(Base, TenantScoped):
    """One row per time the live plan actually changed. Append-only, forever.

    ``document`` holds the full week and is the authority. ``iso_week`` is re-derived from
    it on write, so a scalar cannot drift from the document it describes. The remaining
    columns are facts about the write rather than descriptions of the document: which
    weight set was in force, which input version it was solved against, what caused it,
    and whether the user assented.

    ``weight_set_version`` is the set in force when the row was written rather than a
    statement about what chose the arrangement. A write that evaluated no objective
    records the active version too, and nothing weighed the week it describes.
    ``objective_breakdown`` is what tells those apart: it is empty exactly when the write
    evaluated no objective, and otherwise carries a cost for every objective term.
    """

    __tablename__ = PLAN_REVISIONS_TABLE

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    iso_week: Mapped[str] = mapped_column(String(ISO_WEEK_LENGTH), nullable=False)
    status: Mapped[str] = mapped_column(String(STATUS_LENGTH), nullable=False)
    reason: Mapped[str] = mapped_column(String(REASON_LENGTH), nullable=False)
    document: Mapped[JsonObject] = mapped_column(JSONB, nullable=False)
    objective_breakdown: Mapped[JsonObject] = mapped_column(JSONB, nullable=False)
    weight_set_version: Mapped[int] = mapped_column(nullable=False)
    input_version: Mapped[int] = mapped_column(nullable=False)
    # Self-referencing, and cascading on delete only because deleting a TENANT deletes
    # every one of its revisions in one statement; a restricting constraint would refuse
    # that while a superseding row still pointed at a superseded one.
    supersedes_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{PLAN_REVISIONS_TABLE}.id", ondelete="CASCADE"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(values_in("status", REVISION_STATUSES), name="status_is_known"),
        CheckConstraint(values_in("reason", REVISION_REASONS), name="reason_is_known"),
        # An approved revision without the instant of assent would make "the plan of
        # record as of last Sunday" unanswerable, and the retro reads exactly that.
        CheckConstraint(
            f"status <> '{APPROVED}' OR approved_at IS NOT NULL", name="approved_states_when"
        ),
        # Every read is "this week's revisions, newest first": the live plan, the churn
        # baseline, and the projector's two-week range.
        Index(
            "ix_plan_revisions_tenant_id_iso_week_created_at",
            TENANT_ID_COLUMN,
            "iso_week",
            "created_at",
        ),
    )


class PendingProposal(Base, TenantScoped):
    """The latest solver output awaiting assent. One slot per week, replaced in place.

    The primary key is what enforces the single slot. A second proposal for a week is
    rejected by the database, so replacement has to be an upsert and cannot accidentally
    become an append.
    """

    __tablename__ = PENDING_PROPOSALS_TABLE

    iso_week: Mapped[str] = mapped_column(String(ISO_WEEK_LENGTH), nullable=False)
    document: Mapped[JsonObject] = mapped_column(JSONB, nullable=False)
    proposal_diff: Mapped[JsonObject] = mapped_column(JSONB, nullable=False)
    objective_breakdown: Mapped[JsonObject] = mapped_column(JSONB, nullable=False)
    verdict: Mapped[JsonObject] = mapped_column(JSONB, nullable=False)
    # Recorded because approval appends a revision FROM this row, and a revision states which
    # weights produced its document. The set in force at approval is a different figure: the user
    # may have activated another one since the solve that filled this slot.
    weight_set_version: Mapped[int] = mapped_column(nullable=False)
    input_version: Mapped[int] = mapped_column(nullable=False)
    # No foreign key, deliberately. Terminal operations are pruned at 30 and 90 days and a
    # proposal is not, so a constraint here would either block the prune or null a column
    # that has to name the solve this slot came from.
    operation_id: Mapped[UUID] = mapped_column(nullable=False)
    # A tradeoff concession awaiting approval rides in the slot, so it needs no lifecycle
    # of its own and it is discarded when the slot is replaced.
    candidate_adjustment: Mapped[JsonObject | None] = mapped_column(NULLABLE_JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (PrimaryKeyConstraint(TENANT_ID_COLUMN, "iso_week"),)


class WeekInputVersion(Base, TenantScoped):
    """The monotonic counter every solve's conditional write is guarded on.

    One row per week. A mutation bumps it inside its own transaction; a solve records the
    version it read and commits only if the row still holds it. That comparison carries
    the entire staleness mechanism, which is why there is no dirty flag anywhere.
    """

    __tablename__ = WEEK_INPUT_VERSIONS_TABLE

    iso_week: Mapped[str] = mapped_column(String(ISO_WEEK_LENGTH), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint(TENANT_ID_COLUMN, "iso_week"),
        CheckConstraint(f"version >= {FIRST_INPUT_VERSION}", name="version_starts_at_one"),
    )
