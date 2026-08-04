"""templates, day types, and the week pattern

Four tables, one concern: the shape of a day, declared once and materialized every week.

``day_types`` names a kind of day, ``templates`` is the shape of one day type,
``template_entries`` holds that shape's parts, and ``week_patterns`` maps each weekday onto a day
type as one row per weekday.

**One template per day type**, which the unique index enforces. Materializing a date resolves its
weekday to a day type and the day type to a shape, so two shapes for one day type would need a
composition rule deciding which parts of which one applied. That rule is what this model does not
have and does not need: weekly and monthly recurrence is already a habit's cadence.

**No table here has a cadence column, a period column, or a repeat column.** An entry is
materialized on every date whose weekday maps to its day type, and how often something happens is
a habit's. Three concepts replace the three template periods an earlier model had.

**No table here has a pinned column either.** A template entry is fixed by DERIVATION: its time
comes from the shape rather than from a user's own edit, so the solver may not move it, it renders
no pin glyph, and it creates no row in ``pins``. Fixed by derivation is not "never moved": an
anchor landing on a materialized entry raises a conflict for the user to resolve.

``template_entries.binding_ref`` carries no foreign key, for the same reason
``areas.default_preference_id`` does not: it names a row in one of two tables, routines or habits,
so no single reference could reach both. ``binding_target`` is the column that says which, and
neither is set unless ``kind`` is ``concrete``, which the check constraint holds.

The grid constraints reject a target time off the quarter hour and a duration that is not whole
steps. Both would materialize a block starting or ending between two of the grid's lines, and
because the entry is fixed by derivation nothing may move it onto them: the week would be
infeasible for a reason the user never sees. ``mod()`` rather than ``%``, because the operator
would have to be escaped in the DDL string and a missed escape is a silent difference between the
statement written here and the one the server runs.

``week_patterns`` has no surrogate identifier and no timestamp. Nothing addresses one of its rows,
because the pattern is read and replaced whole, and nothing orders them by when they were written:
the week input version is what records that the pattern changed.

Every bound and every vocabulary member below is spelled here rather than imported. A revision
describes the schema at its own point in the chain and is replayed forever against databases at
that point, so a value read from the workspace's live code would describe the schema as it is now
instead.

Revision ID: 0016_templates_week_pattern
Revises: 0017_off_plan_periods
Create Date: 2026-08-04

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Kept inside 32 characters, which is what `alembic_version.version_num` holds.
revision: str = "0016_templates_week_pattern"
# The head recorded when this work branched was `0007_calendar_sources`. This wave adds several
# migrations over disjoint tables, and a chain has exactly one head, so each is chained onto
# whichever of them landed before it rather than onto that branch point.
down_revision: str | None = "0017_off_plan_periods"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "day_types",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_day_types_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_day_types")),
    )
    # The week pattern's seven rows name a day type by its name, so two holding one name would
    # leave the user choosing between two identical rows.
    op.create_index("uq_day_types_tenant_id_name", "day_types", ["tenant_id", "name"], unique=True)
    op.create_index(
        "ix_day_types_tenant_id_created_at", "day_types", ["tenant_id", "created_at"], unique=False
    )
    op.create_table(
        "templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("day_type_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["day_type_id"],
            ["day_types.id"],
            name=op.f("fk_templates_day_type_id_day_types"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_templates_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_templates")),
    )
    # One shape per day type. Two would need a composition rule to materialize a date.
    op.create_index(
        "uq_templates_tenant_id_day_type_id",
        "templates",
        ["tenant_id", "day_type_id"],
        unique=True,
    )
    op.create_table(
        "template_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=False),
        # A varchar plus a CHECK rather than a Postgres enum type, so adding a member later is a
        # constraint edit rather than an ALTER TYPE. `create_constraint` is stated because
        # SQLAlchemy defaults it to False, which would leave the column accepting any string of
        # the right length.
        sa.Column(
            "kind",
            sa.Enum(
                "concrete",
                "slot",
                name="template_entry_kind",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        # Wall time, no zone. Resolved against whichever zone is active on the date it
        # materializes for, so 07:00 means 07:00 wherever the user is.
        sa.Column("target_time", sa.Time(), nullable=False),
        sa.Column("duration_minutes", sa.SmallInteger(), nullable=False),
        # How far a placement may SHIFT the entry, never how far it may shrink it.
        sa.Column("flex_band_minutes", sa.SmallInteger(), nullable=False),
        # Required for a slot, which is a duration OF an Area. Optional for a concrete entry,
        # whose own content already names an Area.
        sa.Column("area_id", sa.Uuid(), nullable=True),
        sa.Column(
            "binding_target",
            sa.Enum(
                "routine",
                "habit",
                name="binding_target",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        # No foreign key: it names a row in one of two tables, so no single reference could reach
        # both. `binding_target` says which.
        sa.Column("binding_ref", sa.Uuid(), nullable=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "(kind = 'concrete' AND binding_ref IS NOT NULL AND binding_target IS NOT NULL) "
            "OR (kind = 'slot' AND binding_ref IS NULL AND binding_target IS NULL "
            "AND area_id IS NOT NULL)",
            name=op.f("ck_template_entries_kind_states_its_binding"),
        ),
        sa.CheckConstraint(
            "duration_minutes BETWEEN 15 AND 1440 AND mod(duration_minutes, 15) = 0",
            name=op.f("ck_template_entries_duration_is_whole_steps_of_a_day"),
        ),
        sa.CheckConstraint(
            "flex_band_minutes BETWEEN 0 AND 720",
            name=op.f("ck_template_entries_flex_band_shifts_within_a_day"),
        ),
        sa.CheckConstraint(
            "mod(EXTRACT(MINUTE FROM target_time)::int, 15) = 0 "
            "AND EXTRACT(SECOND FROM target_time) = 0",
            name=op.f("ck_template_entries_target_time_is_on_the_grid"),
        ),
        sa.ForeignKeyConstraint(
            ["area_id"],
            ["areas.id"],
            name=op.f("fk_template_entries_area_id_areas"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["templates.id"],
            name=op.f("fk_template_entries_template_id_templates"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_template_entries_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_template_entries")),
    )
    # Every read is one shape's entries in the order the day runs.
    op.create_index(
        "ix_template_entries_tenant_id_template_id_target_time",
        "template_entries",
        ["tenant_id", "template_id", "target_time"],
        unique=False,
    )
    op.create_table(
        "week_patterns",
        sa.Column(
            "weekday",
            sa.Enum(
                "monday",
                "tuesday",
                "wednesday",
                "thursday",
                "friday",
                "saturday",
                "sunday",
                name="weekday",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("day_type_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["day_type_id"],
            ["day_types.id"],
            name=op.f("fk_week_patterns_day_type_id_day_types"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_week_patterns_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        # The tenant and the weekday, so a weekday cannot be mapped twice and the scope leads the
        # index. No surrogate identifier: nothing addresses one of these rows.
        sa.PrimaryKeyConstraint("tenant_id", "weekday", name=op.f("pk_week_patterns")),
    )


def downgrade() -> None:
    op.drop_table("week_patterns")
    op.drop_index(
        "ix_template_entries_tenant_id_template_id_target_time", table_name="template_entries"
    )
    op.drop_table("template_entries")
    op.drop_index("uq_templates_tenant_id_day_type_id", table_name="templates")
    op.drop_table("templates")
    op.drop_index("ix_day_types_tenant_id_created_at", table_name="day_types")
    op.drop_index("uq_day_types_tenant_id_name", table_name="day_types")
    op.drop_table("day_types")
