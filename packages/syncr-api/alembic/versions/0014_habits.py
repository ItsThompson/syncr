"""habits

One table: the recurring intentions that produce roughly 30% of a week's blocks.

Cadence is a discriminator plus two nullable numbers rather than one column called ``value``,
because a row is read by a human in ``psql`` and by a migration years from now, and naming the
number tells the reader what it means. The ``CASE`` constraint refuses a row two kinds could be
read out of, so a row carrying both numbers cannot resolve to whichever one the discriminator
happens to name. ``ELSE false`` rather than no else clause: a ``CASE`` with no matching branch is
NULL, and a check constraint passes on NULL.

A duration is a range whose fixed case is ``min == max``. There is no kind column and no
nullability, so "fixed or elastic" is a comparison rather than a state, and both bounds carry the
grid check because a block's start and end both land on the quarter hour.

Variants are an ordered JSONB list, and the constraint pairs their presence with the binding
source in both directions. A rotation binds content from the list and nothing else may carry one,
which is one rule, so it is one constraint stated as an equality between two predicates rather
than two that could disagree.

Two columns are deliberately absent. There is no preferred time, because when a habit's work
should happen is a preference whose owner may be this habit. And there is no cursor, because the
rotation cursor is a projection of the append-only outcome log: no column exists for it to drift
from, which is what makes desync impossible rather than merely unlikely.

The outcomes a habit's occurrences produce are NOT cascaded from here, and cannot be: they are
rows in ``block_outcomes``, which carries its binding denormalized for exactly this reason. A
removed habit leaves the weeks that already happened reading as they did.

Every bound and every vocabulary member below is spelled here rather than imported. A revision
describes the schema at its own point in the chain and is replayed forever against databases at
that point, so a value read from the workspace's live code would describe the schema as it is now
instead.

Revision ID: 0014_habits
Revises: 0016_templates_week_pattern
Create Date: 2026-08-04

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Kept inside 32 characters, which is what `alembic_version.version_num` holds. Numbered for the
# ticket that adds it rather than sequentially: sibling tickets add a revision over disjoint
# tables in the same wave, so a shared counter would collide while the ticket number cannot.
revision: str = "0014_habits"
down_revision: str | None = "0016_templates_week_pattern"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "habits",
        sa.Column("id", sa.Uuid(), nullable=False),
        # Not nullable and not a list: a habit's occurrences count toward exactly one Area, which
        # is what keeps an hour attributable once.
        sa.Column("area_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=60), nullable=False),
        sa.Column("cadence_kind", sa.String(length=17), nullable=False),
        # Set for `times_per_week` and null otherwise. One an hour over a nominal 168-hour week,
        # which rejects a count no week could hold rather than describing a real week: a
        # transition week is 167, 169, or neither.
        sa.Column("cadence_times_per_week", sa.SmallInteger(), nullable=True),
        # Set for `every_approx_days` and null otherwise. An interval of one day is `daily`, which
        # is the one spelling of it, so the floor is two.
        sa.Column("cadence_approx_days", sa.SmallInteger(), nullable=True),
        # The floor and the ceiling of one occurrence. Equal means fixed: this span or nothing.
        sa.Column("duration_min_minutes", sa.SmallInteger(), nullable=False),
        sa.Column("duration_max_minutes", sa.SmallInteger(), nullable=False),
        # A varchar plus a CHECK rather than a Postgres enum type, so adding a member later is a
        # constraint edit rather than an ALTER TYPE. `create_constraint` is stated because
        # SQLAlchemy defaults it to False, which would leave the column accepting any string of
        # the right length.
        sa.Column(
            "miss_policy",
            sa.Enum(
                "forgive",
                "debt",
                "escalate",
                name="miss_policy",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "binding_source",
            sa.Enum(
                "fixed",
                "rotation",
                "queue",
                name="binding_source",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        # Ordered, and non-empty exactly for `rotation`. The cursor is an index into it.
        sa.Column("variants", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        # The ceiling on outstanding debt, in cadence periods. A cap of zero would forgive every
        # miss and raise the habit on the first, which is what `escalate` already says.
        sa.Column("debt_cap_periods", sa.SmallInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "cadence_approx_days IS NULL OR cadence_approx_days BETWEEN 2 AND 365",
            name=op.f("ck_habits_an_interval_in_days_is_a_cadence"),
        ),
        sa.CheckConstraint(
            "cadence_times_per_week IS NULL OR cadence_times_per_week BETWEEN 1 AND 168",
            name=op.f("ck_habits_a_count_per_week_is_a_cadence"),
        ),
        sa.CheckConstraint(
            "CASE cadence_kind"
            " WHEN 'times_per_week'"
            " THEN cadence_times_per_week IS NOT NULL AND cadence_approx_days IS NULL"
            " WHEN 'daily'"
            " THEN cadence_times_per_week IS NULL AND cadence_approx_days IS NULL"
            " WHEN 'every_approx_days'"
            " THEN cadence_approx_days IS NOT NULL AND cadence_times_per_week IS NULL"
            " ELSE false END",
            name=op.f("ck_habits_cadence_carries_only_its_own_numbers"),
        ),
        sa.CheckConstraint(
            "cadence_kind IN ('times_per_week', 'daily', 'every_approx_days')",
            name=op.f("ck_habits_cadence_kind_is_known"),
        ),
        sa.CheckConstraint(
            "debt_cap_periods BETWEEN 1 AND 52",
            name=op.f("ck_habits_a_debt_cap_is_a_count_of_periods"),
        ),
        sa.CheckConstraint(
            "duration_min_minutes BETWEEN 15 AND 1440"
            " AND duration_max_minutes BETWEEN 15 AND 1440"
            " AND duration_min_minutes <= duration_max_minutes",
            name=op.f("ck_habits_a_duration_is_a_range_that_runs_forward"),
        ),
        # A start on the grid plus a multiple of the step gives an end on the grid, which is what
        # a declared duration owes the block it materializes into.
        sa.CheckConstraint(
            "duration_min_minutes % 15 = 0 AND duration_max_minutes % 15 = 0",
            name=op.f("ck_habits_a_duration_lands_on_the_snap_grid"),
        ),
        sa.CheckConstraint(
            "jsonb_array_length(variants) <= 24", name=op.f("ck_habits_a_rotation_is_not_a_backlog")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(variants) = 'array'", name=op.f("ck_habits_variants_is_an_ordered_list")
        ),
        # One equality between two predicates: a rotation has variants and nothing else may, so
        # neither direction can hold without the other.
        sa.CheckConstraint(
            "(binding_source = 'rotation') = (jsonb_array_length(variants) > 0)",
            name=op.f("ck_habits_variants_match_the_binding_source"),
        ),
        sa.ForeignKeyConstraint(
            ["area_id"], ["areas.id"], name=op.f("fk_habits_area_id_areas"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_habits_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_habits")),
    )
    # Every list read is this tenant's habits in the order they were declared.
    op.create_index(
        "ix_habits_tenant_id_created_at", "habits", ["tenant_id", "created_at"], unique=False
    )
    # The week assembler and the preference chain both read one Area's habits.
    op.create_index("ix_habits_tenant_id_area_id", "habits", ["tenant_id", "area_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_habits_tenant_id_area_id", table_name="habits")
    op.drop_index("ix_habits_tenant_id_created_at", table_name="habits")
    op.drop_table("habits")
