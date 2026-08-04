"""tasks

One table: the backlog, and the physics that keeps a placement satisfiable.

Five properties of it are the design rather than incidental.

There is no preferred-time column and no column that could hold one. Preferred times are a
``Preference``, whose owner is an Area, a Habit, or a Task, so a task inherits its Area's
windows unless it overrides them. A column here would be a second place a window could be
authored, and the two would disagree.

``recorded_minutes`` is written by confirmed outcomes, never by the backlog. It accumulates from
the outcome log and the backlog reads it to report remaining work.

``completed_at`` exists and there is no ``dropped_at``. A completion survives in reports, so its
instant is read; nothing reports a dropped task, so an instant for one would be a column with no
reader. The constraint ties the timestamp to the status in both directions.

``min_chunk_minutes <= estimate_minutes`` is invariant T1's backstop rather than its statement.
The rule lives in the domain, which is what produces the 422 and its stated reason; this
constraint is what a write bypassing that path hits.

Invariant T3, that remaining work is never negative, is deliberately NOT a constraint. Remaining
work is clamped at zero where it is computed, because recording more time than was estimated is
ordinary: an estimate is a guess and an outcome is a fact.

Every bound and every vocabulary member below is spelled here rather than imported. A revision
describes the schema at its own point in the chain and is replayed forever against databases at
that point, so a value read from the workspace's live code would describe the schema as it is
now instead.

Revision ID: 0013_tasks
Revises: 0007_calendar_sources
Create Date: 2026-08-04

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Kept inside 32 characters, which is what `alembic_version.version_num` holds. Numbered for the
# ticket that adds it rather than sequentially: five sibling tickets add a revision over disjoint
# tables in the same wave, and a sequential number would collide between them.
revision: str = "0013_tasks"
down_revision: str | None = "0007_calendar_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        # Not nullable: an hour spent on a task is attributable to exactly one Area, which is
        # what makes the composition pie add up.
        sa.Column("area_id", sa.Uuid(), nullable=False),
        # Null for a task belonging to no time-boxed push. When set, the Project's Area has to
        # be this task's Area (X2), which the domain states and the service enforces.
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=120), nullable=False),
        # Total work as the user estimated it, never reduced by recording time against the
        # task: remaining work is the difference, computed where it is read.
        sa.Column("estimate_minutes", sa.Integer(), nullable=False),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        # A varchar plus a CHECK rather than a Postgres enum type, so adding a member later is a
        # constraint edit rather than an ALTER TYPE. `create_constraint` is stated because
        # SQLAlchemy defaults it to False, which would leave the column accepting any string of
        # the right length.
        sa.Column(
            "priority",
            sa.Enum(
                "low",
                "normal",
                "high",
                "urgent",
                name="task_priority",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        # A splittable task is never divided below this. The one field that stops fill placement
        # putting fifteen minutes of something that needs an hour to start into whatever fits.
        sa.Column("min_chunk_minutes", sa.Integer(), nullable=False),
        # False means atomic: this duration in one block, or not placed.
        sa.Column("splittable", sa.Boolean(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "completed",
                "dropped",
                name="task_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        # Accumulated from confirmed outcomes, and left intact by completing, so the time spent
        # survives in reports.
        sa.Column("recorded_minutes", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "(status = 'completed') = (completed_at IS NOT NULL)",
            name=op.f("ck_tasks_a_completion_carries_its_instant"),
        ),
        # 10080 is 168 hours in minutes: it rejects an estimate no week could ever hold, which is
        # what an atomic task needs, rather than describing a real week. A real week is 167 or
        # 169 hours whenever a zone transitions.
        sa.CheckConstraint(
            "estimate_minutes BETWEEN 1 AND 10080",
            name=op.f("ck_tasks_estimate_minutes_could_be_placed"),
        ),
        sa.CheckConstraint(
            "min_chunk_minutes <= estimate_minutes",
            name=op.f("ck_tasks_min_chunk_fits_inside_the_estimate"),
        ),
        sa.CheckConstraint(
            "min_chunk_minutes BETWEEN 1 AND 10080",
            name=op.f("ck_tasks_min_chunk_minutes_is_a_duration"),
        ),
        sa.CheckConstraint(
            "recorded_minutes >= 0", name=op.f("ck_tasks_recorded_minutes_is_not_negative")
        ),
        sa.ForeignKeyConstraint(
            ["area_id"], ["areas.id"], name=op.f("fk_tasks_area_id_areas"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_tasks_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_tasks_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
    )
    # The backlog list filters by status and its header counts the open ones.
    op.create_index("ix_tasks_tenant_id_status", "tasks", ["tenant_id", "status"], unique=False)
    # The other filter the list offers, and the read the week assembler makes per Area.
    op.create_index("ix_tasks_tenant_id_area_id", "tasks", ["tenant_id", "area_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_tasks_tenant_id_area_id", table_name="tasks")
    op.drop_index("ix_tasks_tenant_id_status", table_name="tasks")
    op.drop_table("tasks")
