"""The permanent week-scoped records. Six tables, none of them ever pruned.

Each of these is a fact about a week that happened, and a fact does not expire. Nothing
here has a retention path, and adding one would silently break something that reads it: a
review, a retro, a fitter, or a product metric.

| Table | Read by |
|---|---|
| ``pins`` | the solver as a hard constraint, and promotion detection across weeks |
| ``block_outcomes`` | reviews, the retro, the rotation cursor, and the duration fitter |
| ``edit_events`` | the learning layer's pairwise ranking |
| ``conflicts`` | the week view, and the weekly session's repeated-collision item |
| ``week_adjustments`` | the week assembler, as a solve input |
| ``verdict_events`` | the early-catch product metric |

The columns whose semantics arrive later hold JSONB: a ``BindingRef``, an ``EditContext``,
a set of shortfall kinds. Their shape is enforced by the Pydantic model that writes them.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from syncr_api.core.columns import ISO_WEEK_LENGTH, JsonObject, json_key, values_in
from syncr_api.core.orm import Base
from syncr_api.core.tenancy import TENANT_ID_COLUMN, TenantScoped
from syncr_api.plans.config import (
    ADJUSTMENT_KINDS,
    BLOCK_ID_MAX_LENGTH,
    BLOCK_OUTCOMES_TABLE,
    CONFLICT_RESOLUTIONS,
    CONFLICTS_TABLE,
    EDIT_EVENTS_TABLE,
    MOVED_OUTCOME,
    OUTCOME_STATES,
    PARTIAL_OUTCOME,
    PINS_TABLE,
    PLAN_REVISIONS_TABLE,
    VERDICT_EVENTS_TABLE,
    VERDICT_PROVENANCES,
    VERDICT_SURFACES,
    WEEK_ADJUSTMENTS_TABLE,
)
from syncr_api.plans.stored_documents import BINDING, ENTITY_ID, KIND

STATE_LENGTH = 16
KIND_LENGTH = 24

# A nullable column's closed vocabulary needs no `IS NULL` disjunct: `NULL IN (...)`
# evaluates to NULL, and a check constraint rejects only what is false.


class Pin(Base, TenantScoped):
    """Where the user put something, and what the solver had chosen instead.

    A pin binds ONE week and does not carry forward, so the schema stores the week rather
    than a recurrence. The record persists permanently even so: the binding is a live
    constraint on this week's solve, and the record is a fact about a week that has
    already happened.
    """

    __tablename__ = PINS_TABLE

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    iso_week: Mapped[str] = mapped_column(String(ISO_WEEK_LENGTH), nullable=False)
    binding: Mapped[JsonObject] = mapped_column(JSONB, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    superseded_starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    superseded_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Stored, never recomputed later: the weight set that produced it is versioned and
    # will have moved on, so a recomputation would answer a different question.
    objective_delta: Mapped[float | None] = mapped_column(nullable=True)
    weight_set_version: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("starts_at < ends_at", name="interval_is_half_open"),
        CheckConstraint(
            "(superseded_starts_at IS NULL) = (superseded_ends_at IS NULL)",
            name="superseded_placement_is_whole",
        ),
        Index("ix_pins_tenant_id_iso_week", TENANT_ID_COLUMN, "iso_week"),
    )


class BlockOutcome(Base, TenantScoped):
    """What actually happened to one block, in the plan of record it was recorded against.

    ``binding`` is denormalized onto the row so an outcome survives its block's binding
    ceasing to exist, which is also what lets a corrected confirmation re-derive rotation
    cursors and outstanding debt.

    **One row per block, ever**, which is what the unique index below says. A block id is a
    digest of the week and the binding, so one content instance in one week keeps one id
    however many revisions place it, and every consumer of this table is a COUNT over the
    rows it is handed: two rows for one habit occurrence move a rotation cursor a variant
    past the content the user actually did. ``revision_id`` therefore names the plan of
    record the outcome was recorded AGAINST, restated when a correction is recorded.
    """

    __tablename__ = BLOCK_OUTCOMES_TABLE

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    block_id: Mapped[str] = mapped_column(String(BLOCK_ID_MAX_LENGTH), nullable=False)
    binding: Mapped[JsonObject] = mapped_column(JSONB, nullable=False)
    revision_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{PLAN_REVISIONS_TABLE}.id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(STATE_LENGTH), nullable=False)
    actual_minutes: Mapped[int | None] = mapped_column(nullable=True)
    actual_starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    actual_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # None means the day is unconfirmed, which excludes it from reviews and from learning.
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(values_in("state", OUTCOME_STATES), name="state_is_known"),
        # The sole source of the duration-estimate signal, so a `partial` without the
        # minutes is a row that teaches nothing and claims to.
        CheckConstraint(
            f"state <> '{PARTIAL_OUTCOME}' OR actual_minutes IS NOT NULL",
            name="partial_states_its_minutes",
        ),
        # `moved` is a record of when it actually happened, which is the signal the
        # time-of-day fitness curve is fitted from.
        CheckConstraint(
            f"state <> '{MOVED_OUTCOME}' OR "
            "(actual_starts_at IS NOT NULL AND actual_ends_at IS NOT NULL)",
            name="moved_states_when",
        ),
        CheckConstraint(
            "(actual_starts_at IS NULL) = (actual_ends_at IS NULL)",
            name="actual_interval_is_whole",
        ),
        # An outcome is a fact about one block, so the block identifies it. A block id is a
        # digest of the week and the binding, which is what makes one content instance in one
        # week one row rather than one per revision that placed it. Led by the tenant because
        # every read is scoped by one.
        Index(
            "uq_block_outcomes_tenant_id_block_id",
            TENANT_ID_COLUMN,
            "block_id",
            unique=True,
        ),
        # The day ledger and the retro both read a span of days.
        Index("ix_block_outcomes_tenant_id_occurred_at", TENANT_ID_COLUMN, "occurred_at"),
        # The rotation cursor and outstanding debt read every row whose binding names one of a
        # set of habits, which neither index above offers: one leads with the instant and the
        # other with the block. Declared as an expression index over the two keys the match is
        # an equality on, so the tenant is part of the index condition rather than a filter
        # applied after another tenant's rows have been read.
        Index(
            "ix_block_outcomes_tenant_id_binding_entity",
            TENANT_ID_COLUMN,
            json_key(BINDING, KIND),
            json_key(BINDING, ENTITY_ID),
        ),
    )


class EditEvent(Base, TenantScoped):
    """The pairwise comparison learning-to-rank consumes: what was proposed, what was kept.

    Written at the moment of the edit, with its own feature snapshot, because a fact not
    captured when it happened cannot be reconstructed from an append-only record of
    placements.
    """

    __tablename__ = EDIT_EVENTS_TABLE

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    iso_week: Mapped[str] = mapped_column(String(ISO_WEEK_LENGTH), nullable=False)
    binding: Mapped[JsonObject] = mapped_column(JSONB, nullable=False)
    proposed_starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    proposed_ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    objective_delta: Mapped[float] = mapped_column(nullable=False)
    context: Mapped[JsonObject] = mapped_column(JSONB, nullable=False)
    weight_set_version: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("proposed_starts_at < proposed_ends_at", name="proposed_is_half_open"),
        CheckConstraint("accepted_starts_at < accepted_ends_at", name="accepted_is_half_open"),
        # A fitter reads a time window of edits, and the list route pages by the same order.
        Index("ix_edit_events_tenant_id_created_at", TENANT_ID_COLUMN, "created_at"),
    )


class PlanConflict(Base, TenantScoped):
    """An overlap nothing may resolve silently, because both sides are immovable.

    Named ``PlanConflict`` rather than ``Conflict`` because
    :class:`syncr_api.core.errors.Conflict` is the 409 a service raises, and a module
    holding both meanings of the word pays that reading cost on every line.
    """

    __tablename__ = CONFLICTS_TABLE

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    iso_week: Mapped[str] = mapped_column(String(ISO_WEEK_LENGTH), nullable=False)
    # No foreign key: anchors are created by a later migration, and a conflict is retained
    # after a resolution regardless of what happened to the anchor that raised it.
    anchor_id: Mapped[UUID] = mapped_column(nullable=False)
    block_id: Mapped[str] = mapped_column(String(BLOCK_ID_MAX_LENGTH), nullable=False)
    overlap_starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    overlap_ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(STATE_LENGTH), nullable=True)

    __table_args__ = (
        CheckConstraint(values_in("resolution", CONFLICT_RESOLUTIONS), name="resolution_is_known"),
        # A resolved conflict is retained, and the two columns say one thing: either it
        # is open, or it names both when it was resolved and how.
        CheckConstraint(
            "(resolved_at IS NULL) = (resolution IS NULL)", name="resolution_states_when"
        ),
        CheckConstraint("overlap_starts_at < overlap_ends_at", name="overlap_is_half_open"),
        Index("ix_conflicts_tenant_id_iso_week", TENANT_ID_COLUMN, "iso_week"),
    )


class WeekAdjustment(Base, TenantScoped):
    """An approved tradeoff concession, week-scoped so a hard week does not become normal.

    The unique index is what makes a later concession REPLACE an earlier one for the same
    kind and target. Without it, approving "breach the floor by 1h20m" twice would breach
    it by 2h40m, and the rule would rest on the upsert having been written correctly.
    """

    __tablename__ = WEEK_ADJUSTMENTS_TABLE

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    iso_week: Mapped[str] = mapped_column(String(ISO_WEEK_LENGTH), nullable=False)
    kind: Mapped[str] = mapped_column(String(KIND_LENGTH), nullable=False)
    target_id: Mapped[UUID] = mapped_column(nullable=False)
    # Per-date minutes for `reduce_routine`, empty for the other three kinds. The
    # enumerator chose the distribution, so the row stores the result rather than a rule
    # for re-deriving it against inputs that have since changed.
    reductions: Mapped[JsonObject] = mapped_column(JSONB, nullable=False)
    # How much this concession lowers the figure it names, against that figure as it stands:
    # an INCREMENT rather than an absolute target. Set for `breach_floor` and null for the
    # other three kinds. The enumerator computes it over an already-folded assembly, so a
    # second concession on one target lowers what the first left.
    delta_minutes: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # No foreign key: the operation that produced this concession is pruned at 30 days and
    # the concession is permanent.
    created_by_operation_id: Mapped[UUID] = mapped_column(nullable=False)

    __table_args__ = (
        CheckConstraint(values_in("kind", ADJUSTMENT_KINDS), name="kind_is_known"),
        Index(
            "uq_week_adjustments_tenant_id_iso_week_kind_target_id",
            TENANT_ID_COLUMN,
            "iso_week",
            "kind",
            "target_id",
            unique=True,
        ),
    )


class VerdictEvent(Base, TenantScoped):
    """Every time a week's feasibility verdict changed, and where it was computed.

    Append-only and never pruned, because it feeds a product metric and the data is
    unrecoverable after the fact: the probe is a function of inputs that have since
    changed, so a mid-week infeasibility resolved by Thursday leaves no other trace.
    """

    __tablename__ = VERDICT_EVENTS_TABLE

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    iso_week: Mapped[str] = mapped_column(String(ISO_WEEK_LENGTH), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provenance: Mapped[str] = mapped_column(String(STATE_LENGTH), nullable=False)
    feasible: Mapped[bool] = mapped_column(nullable=False)
    shortfall_minutes: Mapped[int] = mapped_column(nullable=False)
    shortfall_kinds: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    surface: Mapped[str] = mapped_column(String(STATE_LENGTH), nullable=False)
    # Supplied by the caller, because only the caller knows whether the weekly session is
    # open. The maintainer and the CLI both report false.
    session_mode_active: Mapped[bool] = mapped_column(nullable=False)
    input_version: Mapped[int] = mapped_column(nullable=False)
    # No foreign key, for the same reason the pending slot carries none: operations are
    # pruned and this row is not.
    caused_by_operation_id: Mapped[UUID | None] = mapped_column(nullable=True)

    __table_args__ = (
        CheckConstraint(values_in("provenance", VERDICT_PROVENANCES), name="provenance_is_known"),
        CheckConstraint(values_in("surface", VERDICT_SURFACES), name="surface_is_known"),
        CheckConstraint("shortfall_minutes >= 0", name="shortfall_is_not_negative"),
        # A feasible week has no shortfall to quantify, so the two columns cannot disagree.
        CheckConstraint("NOT feasible OR shortfall_minutes = 0", name="feasible_has_no_shortfall"),
        Index(
            "ix_verdict_events_tenant_id_iso_week_occurred_at",
            TENANT_ID_COLUMN,
            "iso_week",
            "occurred_at",
        ),
        # The metric job reads a period across every week in it, which the week-led index
        # above cannot serve.
        Index("ix_verdict_events_tenant_id_occurred_at", TENANT_ID_COLUMN, "occurred_at"),
    )
