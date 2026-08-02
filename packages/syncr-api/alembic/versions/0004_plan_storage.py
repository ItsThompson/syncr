"""plan storage: revisions, the pending slot, the version row, and the week's facts

Twelve tables in one migration, deliberately. Alembic is forward-only with a single head, so
splitting plan storage across tickets that run at the same time would guarantee a branched
chain, and the tables reference each other: an outcome names the revision it belongs to, and
an operation names the revision it produced.

Three shapes here are load-bearing, and each is enforced by the database rather than by the
code that writes it.

``pending_proposals`` takes ``(tenant_id, iso_week)`` as its PRIMARY KEY, so at most one
proposal per week exists by construction and replacement can only be an upsert.

Three PARTIAL UNIQUE indexes hold three invariants: one active weight set per tenant, one
non-terminal solve per tenant per week, and one adjustment per tenant, week, kind and target.
The last is what makes approving the same concession twice replace it rather than double it.

``plan_revisions`` carries the check that an approved revision states when it was approved.
The repository guards the same pair, and both exist on purpose: the guard names the invariant
to the caller that broke it, and the constraint holds for every other writer there will ever
be, including a ``psql`` session.

The JSONB columns are created WITHOUT validating their interior. A document's shape is
enforced by the Pydantic model that writes it, and the value types those documents hold are
defined in the domain package by a later slice. This migration is what those slices append to.

``weight_sets`` is seeded with version 1 for every tenant that already exists. On a fresh
database that is none, because migrations run before any account exists, so account
provisioning seeds the same row for a tenant it creates. Both paths read one definition of the
P0 weights.

Revision ID: 0004_plan_storage
Revises: 0003_settings_and_overrides
Create Date: 2026-08-02

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from syncr_api.learned.config import FIRST_WEIGHT_SET_VERSION, HAND_TUNED, P0_WEIGHTS

# Kept inside 32 characters, which is what `alembic_version.version_num` holds.
revision: str = "0004_plan_storage"
down_revision: str | None = "0003_settings_and_overrides"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plan_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("iso_week", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("document", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("objective_breakdown", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("weight_set_version", sa.Integer(), nullable=False),
        sa.Column("input_version", sa.Integer(), nullable=False),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "reason IN ('auto_applied_fill', 'user_approved', 'tradeoff_approved', "
            "'anchor_delta', 'materialized', 'horizon_advanced')",
            name=op.f("ck_plan_revisions_reason_is_known"),
        ),
        sa.CheckConstraint(
            "status <> 'approved' OR approved_at IS NOT NULL",
            name=op.f("ck_plan_revisions_approved_states_when"),
        ),
        sa.CheckConstraint(
            "status IN ('applied', 'approved')", name=op.f("ck_plan_revisions_status_is_known")
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["plan_revisions.id"],
            name=op.f("fk_plan_revisions_supersedes_id_plan_revisions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_plan_revisions_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_revisions")),
    )
    op.create_index(
        "ix_plan_revisions_tenant_id_iso_week_created_at",
        "plan_revisions",
        ["tenant_id", "iso_week", "created_at"],
        unique=False,
    )
    op.create_table(
        "pending_proposals",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("iso_week", sa.String(length=8), nullable=False),
        sa.Column("document", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("proposal_diff", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("objective_breakdown", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("verdict", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_version", sa.Integer(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_adjustment", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_pending_proposals_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "iso_week", name=op.f("pk_pending_proposals")),
    )
    op.create_table(
        "week_input_versions",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("iso_week", sa.String(length=8), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "version >= 1", name=op.f("ck_week_input_versions_version_starts_at_one")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_week_input_versions_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "iso_week", name=op.f("pk_week_input_versions")),
    )
    op.create_table(
        "weight_sets",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("deadline_risk", sa.Float(), nullable=False),
        sa.Column("budget_deviation", sa.Float(), nullable=False),
        sa.Column("time_of_day_misfit", sa.Float(), nullable=False),
        sa.Column("fragmentation", sa.Float(), nullable=False),
        sa.Column("churn", sa.Float(), nullable=False),
        sa.Column("context_switch", sa.Float(), nullable=False),
        sa.Column("staleness", sa.Float(), nullable=False),
        sa.Column(
            "duration_multiplier",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "time_of_day_fitness",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "skip_probability",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("context_switch_cost", sa.Float(), nullable=False),
        sa.Column("churn_tolerance", sa.Float(), nullable=False),
        sa.Column("fitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "maturity",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(origin = 'fitted') = (fitted_at IS NOT NULL)",
            name=op.f("ck_weight_sets_fitted_states_when"),
        ),
        sa.CheckConstraint(
            "origin IN ('hand-tuned', 'fitted')", name=op.f("ck_weight_sets_origin_is_known")
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_weight_sets_version_starts_at_one")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_weight_sets_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "version", name=op.f("pk_weight_sets")),
    )
    op.create_index(
        "uq_weight_sets_tenant_id_active",
        "weight_sets",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("active"),
    )
    op.create_table(
        "pins",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("iso_week", sa.String(length=8), nullable=False),
        sa.Column("binding", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("objective_delta", sa.Float(), nullable=True),
        sa.Column("weight_set_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(superseded_starts_at IS NULL) = (superseded_ends_at IS NULL)",
            name=op.f("ck_pins_superseded_placement_is_whole"),
        ),
        sa.CheckConstraint("starts_at < ends_at", name=op.f("ck_pins_interval_is_half_open")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_pins_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pins")),
    )
    op.create_index("ix_pins_tenant_id_iso_week", "pins", ["tenant_id", "iso_week"], unique=False)
    op.create_table(
        "block_outcomes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("block_id", sa.String(length=64), nullable=False),
        sa.Column("binding", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("actual_minutes", sa.Integer(), nullable=True),
        sa.Column("actual_starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state <> 'moved' OR (actual_starts_at IS NOT NULL AND actual_ends_at IS NOT NULL)",
            name=op.f("ck_block_outcomes_moved_states_when"),
        ),
        sa.CheckConstraint(
            "state <> 'partial' OR actual_minutes IS NOT NULL",
            name=op.f("ck_block_outcomes_partial_states_its_minutes"),
        ),
        sa.CheckConstraint(
            "state IN ('presumed', 'completed', 'partial', 'skipped', 'moved')",
            name=op.f("ck_block_outcomes_state_is_known"),
        ),
        sa.CheckConstraint(
            "(actual_starts_at IS NULL) = (actual_ends_at IS NULL)",
            name=op.f("ck_block_outcomes_actual_interval_is_whole"),
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["plan_revisions.id"],
            name=op.f("fk_block_outcomes_revision_id_plan_revisions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_block_outcomes_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_block_outcomes")),
    )
    op.create_index(
        "ix_block_outcomes_tenant_id_occurred_at",
        "block_outcomes",
        ["tenant_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "uq_block_outcomes_tenant_id_block_id_revision_id",
        "block_outcomes",
        ["tenant_id", "block_id", "revision_id"],
        unique=True,
    )
    op.create_table(
        "edit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("iso_week", sa.String(length=8), nullable=False),
        sa.Column("binding", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("proposed_starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("proposed_ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("objective_delta", sa.Float(), nullable=False),
        sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("weight_set_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "accepted_starts_at < accepted_ends_at",
            name=op.f("ck_edit_events_accepted_is_half_open"),
        ),
        sa.CheckConstraint(
            "proposed_starts_at < proposed_ends_at",
            name=op.f("ck_edit_events_proposed_is_half_open"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_edit_events_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_edit_events")),
    )
    op.create_index(
        "ix_edit_events_tenant_id_created_at",
        "edit_events",
        ["tenant_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "conflicts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("iso_week", sa.String(length=8), nullable=False),
        sa.Column("anchor_id", sa.Uuid(), nullable=False),
        sa.Column("block_id", sa.String(length=64), nullable=False),
        sa.Column("overlap_starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("overlap_ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution", sa.String(length=16), nullable=True),
        sa.CheckConstraint(
            "resolution IN ('moved', 'kept-both', 'retyped')",
            name=op.f("ck_conflicts_resolution_is_known"),
        ),
        sa.CheckConstraint(
            "(resolved_at IS NULL) = (resolution IS NULL)",
            name=op.f("ck_conflicts_resolution_states_when"),
        ),
        sa.CheckConstraint(
            "overlap_starts_at < overlap_ends_at", name=op.f("ck_conflicts_overlap_is_half_open")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_conflicts_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conflicts")),
    )
    op.create_index(
        "ix_conflicts_tenant_id_iso_week", "conflicts", ["tenant_id", "iso_week"], unique=False
    )
    op.create_table(
        "week_adjustments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("iso_week", sa.String(length=8), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("reductions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("delta_minutes", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_operation_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('drop_item', 'reduce_routine', 'breach_floor', 'accept_partial')",
            name=op.f("ck_week_adjustments_kind_is_known"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_week_adjustments_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_week_adjustments")),
    )
    op.create_index(
        "uq_week_adjustments_tenant_id_iso_week_kind_target_id",
        "week_adjustments",
        ["tenant_id", "iso_week", "kind", "target_id"],
        unique=True,
    )
    op.create_table(
        "verdict_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("iso_week", sa.String(length=8), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provenance", sa.String(length=16), nullable=False),
        sa.Column("feasible", sa.Boolean(), nullable=False),
        sa.Column("shortfall_minutes", sa.Integer(), nullable=False),
        sa.Column("shortfall_kinds", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("surface", sa.String(length=16), nullable=False),
        sa.Column("session_mode_active", sa.Boolean(), nullable=False),
        sa.Column("input_version", sa.Integer(), nullable=False),
        sa.Column("caused_by_operation_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "provenance IN ('probe', 'solver')", name=op.f("ck_verdict_events_provenance_is_known")
        ),
        sa.CheckConstraint(
            "surface IN ('pin', 'mutation', 'tradeoff', 'solve', 'cli', 'maintainer')",
            name=op.f("ck_verdict_events_surface_is_known"),
        ),
        sa.CheckConstraint(
            "NOT feasible OR shortfall_minutes = 0",
            name=op.f("ck_verdict_events_feasible_has_no_shortfall"),
        ),
        sa.CheckConstraint(
            "shortfall_minutes >= 0", name=op.f("ck_verdict_events_shortfall_is_not_negative")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_verdict_events_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_verdict_events")),
    )
    op.create_index(
        "ix_verdict_events_tenant_id_iso_week_occurred_at",
        "verdict_events",
        ["tenant_id", "iso_week", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_verdict_events_tenant_id_occurred_at",
        "verdict_events",
        ["tenant_id", "occurred_at"],
        unique=False,
    )
    op.create_table(
        "operations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("iso_week", sa.String(length=8), nullable=True),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("input_version", sa.Integer(), nullable=True),
        sa.Column("candidate_adjustment", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_revision_id", sa.Uuid(), nullable=True),
        sa.Column("superseded_by", sa.Uuid(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("failed_input_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint(
            "failed_input_snapshot IS NULL OR status = 'failed'",
            name=op.f("ck_operations_snapshot_belongs_to_a_failure"),
        ),
        sa.CheckConstraint(
            "kind IN ('solve', 'materialize', 'calendar_sync', 'projection')",
            name=op.f("ck_operations_kind_is_known"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'superseded')",
            name=op.f("ck_operations_status_is_known"),
        ),
        sa.CheckConstraint(
            "(error_code IS NULL) = (error_message IS NULL)",
            name=op.f("ck_operations_error_states_both_halves"),
        ),
        sa.CheckConstraint("attempt >= 1", name=op.f("ck_operations_attempt_starts_at_one")),
        sa.CheckConstraint(
            "num_nonnulls(iso_week, source_id) = 1", name=op.f("ck_operations_target_is_one_thing")
        ),
        sa.ForeignKeyConstraint(
            ["result_revision_id"],
            ["plan_revisions.id"],
            name=op.f("fk_operations_result_revision_id_plan_revisions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_operations_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_operations")),
    )
    op.create_index("ix_operations_finished_at", "operations", ["finished_at"], unique=False)
    op.create_index(
        "ix_operations_pending_scheduled_for",
        "operations",
        ["scheduled_for"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_operations_tenant_id_iso_week", "operations", ["tenant_id", "iso_week"], unique=False
    )
    op.create_index(
        "uq_operations_tenant_id_iso_week_in_flight_solve",
        "operations",
        ["tenant_id", "iso_week"],
        unique=True,
        postgresql_where=sa.text("kind = 'solve' AND status IN ('pending', 'running')"),
    )
    op.create_table(
        "idempotency_keys",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("route", sa.String(length=200), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(state = 'completed') = (response_body IS NOT NULL)",
            name=op.f("ck_idempotency_keys_completed_stores_its_response"),
        ),
        sa.CheckConstraint(
            "state IN ('in_flight', 'completed')", name=op.f("ck_idempotency_keys_state_is_known")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_idempotency_keys_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "route", "idempotency_key", name=op.f("pk_idempotency_keys")
        ),
    )
    op.create_index(
        "ix_idempotency_keys_expires_at", "idempotency_keys", ["expires_at"], unique=False
    )
    _seed_hand_tuned_weight_sets()


def _seed_hand_tuned_weight_sets() -> None:
    """Give every tenant that already exists its version 1, hand-tuned and active.

    Imports the weights rather than restating them, and that is safe here rather than a
    migration reaching into application code: the statement selects EXISTING tenants, so on a
    fresh database it inserts nothing and a replay cannot produce a different row than the
    one an older database already has. Every tenant created afterwards is seeded by account
    provisioning, from this same definition.

    ``ON CONFLICT DO NOTHING`` covers a re-run: a tenant that already has version 1, or
    already has an active set, keeps it.
    """
    weights = {name: float(value) for name, value in P0_WEIGHTS.items()}
    columns = ", ".join(weights)
    placeholders = ", ".join(f":{name}" for name in weights)
    op.execute(
        sa.text(
            f"INSERT INTO weight_sets "  # noqa: S608 - the names are this module's own constants
            f"(tenant_id, version, active, origin, created_at, {columns}) "
            f"SELECT id, :version, true, :origin, now(), {placeholders} FROM tenants "
            f"ON CONFLICT DO NOTHING"
        ).bindparams(version=FIRST_WEIGHT_SET_VERSION, origin=HAND_TUNED, **weights)
    )


def downgrade() -> None:
    op.drop_index("ix_idempotency_keys_expires_at", table_name="idempotency_keys")
    op.drop_table("idempotency_keys")
    op.drop_index(
        "uq_operations_tenant_id_iso_week_in_flight_solve",
        table_name="operations",
        postgresql_where=sa.text("kind = 'solve' AND status IN ('pending', 'running')"),
    )
    op.drop_index("ix_operations_tenant_id_iso_week", table_name="operations")
    op.drop_index(
        "ix_operations_pending_scheduled_for",
        table_name="operations",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_index("ix_operations_finished_at", table_name="operations")
    op.drop_table("operations")
    op.drop_index("ix_verdict_events_tenant_id_occurred_at", table_name="verdict_events")
    op.drop_index("ix_verdict_events_tenant_id_iso_week_occurred_at", table_name="verdict_events")
    op.drop_table("verdict_events")
    op.drop_index(
        "uq_week_adjustments_tenant_id_iso_week_kind_target_id", table_name="week_adjustments"
    )
    op.drop_table("week_adjustments")
    op.drop_index("ix_conflicts_tenant_id_iso_week", table_name="conflicts")
    op.drop_table("conflicts")
    op.drop_index("ix_edit_events_tenant_id_created_at", table_name="edit_events")
    op.drop_table("edit_events")
    op.drop_index("uq_block_outcomes_tenant_id_block_id_revision_id", table_name="block_outcomes")
    op.drop_index("ix_block_outcomes_tenant_id_occurred_at", table_name="block_outcomes")
    op.drop_table("block_outcomes")
    op.drop_index("ix_pins_tenant_id_iso_week", table_name="pins")
    op.drop_table("pins")
    op.drop_index(
        "uq_weight_sets_tenant_id_active",
        table_name="weight_sets",
        postgresql_where=sa.text("active"),
    )
    op.drop_table("weight_sets")
    op.drop_table("week_input_versions")
    op.drop_table("pending_proposals")
    op.drop_index("ix_plan_revisions_tenant_id_iso_week_created_at", table_name="plan_revisions")
    op.drop_table("plan_revisions")
