"""preferences

One table: when an Area's, a Habit's, or a Task's work should happen.

The owner is three nullable foreign keys plus a discriminator, not one untyped identifier. An
untyped ``owner_id`` could reference nothing, so removing a habit would leave a preference addressed
to a row that no longer exists and a resolution would read a window the user had deleted. Three real
references cascade, so a preference dies with its owner. The pairing of the discriminator against
which reference is set is ONE constraint stated as a ``CASE``, rather than two that could disagree,
and ``ELSE false`` rather than no else clause: a ``CASE`` with no matching branch is NULL, and a
check constraint passes on NULL.

One preference per owner is three unique indexes, one per reference column, because Postgres treats
NULLs as distinct: the Area index constrains the Area-owned rows and ignores every other row.

``strength`` holds ``strong`` or ``soft`` and there is no third member. Both are objective costs
differing in weight, so neither can leave a block unscheduled. A hard temporal rule with a
conditional escape is not a hard rule and no property test can be written for one, which is why no
``hard`` value exists to store.

``max_per_day_minutes`` is confined to an Area owner by its own constraint. It is a hard constraint,
and it reaches the solver through the Area's budget rather than through the preference resolved down
an override chain, so an override that could carry one would be an override that could relax a hard
cap. The request shape for an override has no field for it either; this is the half that holds for a
writer reaching the table from ``psql`` or from a later migration.

Windows are an ordered JSONB list and their interior is not validated here. JSONB is schemaless at
the database level, so what the column owes its readers is the list's shape and its length; the wall
times inside it are validated by the entity, on the way in and again on the way out. They are stored
as ``HH:MM:SS`` strings rather than in a ``time`` column on purpose: a ``TIME WITHOUT TIME ZONE``
column drops an offset in silence, and nothing downstream could tell the value had moved.

Every bound and every vocabulary member below is spelled here rather than imported. A revision
describes the schema at its own point in the chain and is replayed forever against databases at that
point, so a value read from the workspace's live code would describe the schema as it is now
instead.

Revision ID: 0021_preferences
Revises: 0018_google_calendar
Create Date: 2026-08-04

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Kept inside 32 characters, which is what `alembic_version.version_num` holds. Numbered for the
# ticket that adds it rather than sequentially: sibling tickets add a revision over disjoint tables
# in the same wave, so a shared counter would collide while the ticket number cannot.
revision: str = "0021_preferences"
down_revision: str | None = "0018_google_calendar"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "preferences",
        sa.Column("id", sa.Uuid(), nullable=False),
        # Which of the three references below is the owner. Paired with them by the CASE below.
        sa.Column("owner_kind", sa.String(length=5), nullable=False),
        sa.Column("area_id", sa.Uuid(), nullable=True),
        sa.Column("habit_id", sa.Uuid(), nullable=True),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        # Ordered earliest first, and possibly empty: on an override an empty list replaces its
        # Area's windows with none, which is how one habit opts out of a preference its Area keeps.
        sa.Column("windows", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("strength", sa.String(length=6), nullable=False),
        # The ideal length of one session, in whole grid steps. An ideal only: a task's minimum
        # chunk stays a hard constraint, so a shorter split is placed and charged to the
        # fragmentation cost rather than refused.
        sa.Column("preferred_duration_minutes", sa.SmallInteger(), nullable=True),
        # An Area's hard daily ceiling. Confined to an Area owner by its own constraint below.
        sa.Column("max_per_day_minutes", sa.SmallInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "owner_kind IN ('area', 'habit', 'task')",
            name=op.f("ck_preferences_owner_kind_is_known"),
        ),
        # Exactly one reference, and it is the one the discriminator names. A row two owners could
        # be read out of resolves to whichever column the reader looked at first.
        sa.CheckConstraint(
            "CASE owner_kind"
            " WHEN 'area'"
            " THEN area_id IS NOT NULL AND habit_id IS NULL AND task_id IS NULL"
            " WHEN 'habit'"
            " THEN habit_id IS NOT NULL AND area_id IS NULL AND task_id IS NULL"
            " WHEN 'task'"
            " THEN task_id IS NOT NULL AND area_id IS NULL AND habit_id IS NULL"
            " ELSE false END",
            name=op.f("ck_preferences_exactly_one_owner_and_it_is_the_kind_named"),
        ),
        sa.CheckConstraint(
            "strength IN ('strong', 'soft')",
            name=op.f("ck_preferences_a_strength_is_strong_or_soft_and_never_hard"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(windows) = 'array'",
            name=op.f("ck_preferences_windows_is_an_ordered_list"),
        ),
        sa.CheckConstraint(
            "jsonb_array_length(windows) <= 6",
            name=op.f("ck_preferences_a_preference_names_a_few_times_of_day"),
        ),
        # A start on the grid plus a multiple of the step gives an end on the grid, which is what an
        # ideal session owes the block it would be met by.
        sa.CheckConstraint(
            "preferred_duration_minutes IS NULL OR (preferred_duration_minutes BETWEEN 15 AND 1440"
            " AND preferred_duration_minutes % 15 = 0)",
            name=op.f("ck_preferences_an_ideal_session_lands_on_the_snap_grid"),
        ),
        sa.CheckConstraint(
            "max_per_day_minutes IS NULL OR owner_kind = 'area'",
            name=op.f("ck_preferences_a_daily_cap_belongs_to_an_area"),
        ),
        # A cap below one grid step admits no block at all, which says never rather than at most.
        sa.CheckConstraint(
            "max_per_day_minutes IS NULL OR max_per_day_minutes BETWEEN 15 AND 1440",
            name=op.f("ck_preferences_a_daily_cap_admits_at_least_one_block"),
        ),
        sa.ForeignKeyConstraint(
            ["area_id"],
            ["areas.id"],
            name=op.f("fk_preferences_area_id_areas"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["habit_id"],
            ["habits.id"],
            name=op.f("fk_preferences_habit_id_habits"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_preferences_task_id_tasks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_preferences_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_preferences")),
    )
    # One preference per owner. Three indexes rather than one over a shared column, because there is
    # no shared column: each constrains the rows whose own reference is set and ignores the rest,
    # which is exactly what NULLs being distinct buys.
    op.create_index(
        "uq_preferences_tenant_id_area_id", "preferences", ["tenant_id", "area_id"], unique=True
    )
    op.create_index(
        "uq_preferences_tenant_id_habit_id", "preferences", ["tenant_id", "habit_id"], unique=True
    )
    op.create_index(
        "uq_preferences_tenant_id_task_id", "preferences", ["tenant_id", "task_id"], unique=True
    )


def downgrade() -> None:
    op.drop_index("uq_preferences_tenant_id_task_id", table_name="preferences")
    op.drop_index("uq_preferences_tenant_id_habit_id", table_name="preferences")
    op.drop_index("uq_preferences_tenant_id_area_id", table_name="preferences")
    op.drop_table("preferences")
