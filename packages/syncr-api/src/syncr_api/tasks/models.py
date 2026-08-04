"""The ``tasks`` table: the backlog, and the physics that keeps a placement satisfiable.

Five properties of this table are the design rather than incidental.

**There is no preferred-time column, and no column that could hold one.** Preferred times are
a ``Preference``, whose owner is an Area, a Habit, or a Task, so a task inherits its Area's
windows unless it overrides them. A column here would be a second place a window could be
authored, and the two would disagree.

**``recorded_minutes`` is written by confirmed outcomes, never by the backlog.** No route in
this module sets it: it accumulates from the outcome log, and the backlog reads it to report
remaining work. Its default is zero so a captured task is complete without it.

**``completed_at`` exists and ``dropped_at`` does not.** A completion survives in reports, so
its instant is read; nothing reports a dropped task, so an instant for one would be a column
with no reader. The check constraint ties the timestamp to the status in both directions, so a
completed row without an instant and an open row carrying one are both refused.

**T1 is checked here as a backstop, not as its statement.** The rule lives in
``syncr_domain.tasks.require_a_chunk_that_fits``, which is what produces the 422 and its
stated reason. This constraint is what makes a write bypassing that path fail rather than store
a task no placement could satisfy, the same way the unique index on an Area's name backs up the
409 the service raises.

**T3 is NOT a constraint.** Remaining work is clamped at zero where it is computed, because
recording more time than was estimated is ordinary: an estimate is a guess and an outcome is a
fact. A ``recorded_minutes <= estimate_minutes`` constraint would refuse the fact.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from syncr_api.areas.config import AREAS_TABLE, PROJECTS_TABLE
from syncr_api.core.orm import Base
from syncr_api.core.tenancy import TENANT_ID_COLUMN, TenantScoped
from syncr_api.tasks.config import (
    ESTIMATE_MINUTES_MAX,
    ESTIMATE_MINUTES_MIN,
    MIN_CHUNK_MINUTES_MAX,
    MIN_CHUNK_MINUTES_MIN,
    RECORDED_MINUTES_MIN,
    TASKS_TABLE,
    TITLE_MAX_LENGTH,
)
from syncr_domain.tasks import Priority, TaskStatus

# A varchar plus a generated CHECK rather than a Postgres enum type, matching the Areas and
# settings modules: adding a member later is a check-constraint edit rather than an ALTER TYPE,
# and the constraint is generated from the enum so the two cannot drift. `values_callable`
# stores the member VALUES, which are what the wire and the generated TypeScript carry.
_TASK_STATUS_COLUMN = Enum(
    TaskStatus,
    native_enum=False,
    create_constraint=True,
    length=max(len(status.value) for status in TaskStatus),
    values_callable=lambda enum: [member.value for member in enum],
    name="task_status",
)

_PRIORITY_COLUMN = Enum(
    Priority,
    native_enum=False,
    create_constraint=True,
    length=max(len(priority.value) for priority in Priority),
    values_callable=lambda enum: [member.value for member in enum],
    name="task_priority",
)


class TaskRow(Base, TenantScoped):
    """One task: its Area, its physics, and what has been recorded against it."""

    __tablename__ = TASKS_TABLE
    __table_args__ = (
        CheckConstraint(
            f"estimate_minutes BETWEEN {ESTIMATE_MINUTES_MIN} AND {ESTIMATE_MINUTES_MAX}",
            name="estimate_minutes_could_be_placed",
        ),
        CheckConstraint(
            f"min_chunk_minutes BETWEEN {MIN_CHUNK_MINUTES_MIN} AND {MIN_CHUNK_MINUTES_MAX}",
            name="min_chunk_minutes_is_a_duration",
        ),
        # T1's backstop. The domain states the rule and the reason; this is what a write
        # bypassing the service hits.
        CheckConstraint(
            "min_chunk_minutes <= estimate_minutes", name="min_chunk_fits_inside_the_estimate"
        ),
        CheckConstraint(
            f"recorded_minutes >= {RECORDED_MINUTES_MIN}", name="recorded_minutes_is_not_negative"
        ),
        # T4's backstop, both ways: a completion carries its instant, and nothing else does.
        CheckConstraint(
            f"(status = '{TaskStatus.COMPLETED.value}') = (completed_at IS NOT NULL)",
            name="a_completion_carries_its_instant",
        ),
        # The backlog list filters by status and its header counts the open ones.
        Index(f"ix_{TASKS_TABLE}_{TENANT_ID_COLUMN}_status", TENANT_ID_COLUMN, "status"),
        # The other filter the list offers, and the read the week assembler makes per Area.
        Index(f"ix_{TASKS_TABLE}_{TENANT_ID_COLUMN}_area_id", TENANT_ID_COLUMN, "area_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    # Not nullable: an hour spent on a task is attributable to exactly one Area, which is what
    # makes the pie add up. A Project does not replace it, it constrains it (X2).
    area_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{AREAS_TABLE}.id", ondelete="CASCADE"), nullable=False
    )
    # Null for a task that belongs to no time-boxed push. When set, its Area has to be this
    # task's Area, which `syncr_domain.projects.require_matching_area` is the one statement of.
    project_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{PROJECTS_TABLE}.id", ondelete="CASCADE"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(TITLE_MAX_LENGTH), nullable=False)
    # Total work, as the user estimated it. Not reduced by recording time against the task:
    # remaining work is the difference, computed where it is read.
    estimate_minutes: Mapped[int] = mapped_column(Integer(), nullable=False)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    priority: Mapped[Priority] = mapped_column(_PRIORITY_COLUMN, nullable=False)
    # A splittable task is never divided below this. The one field that stops fill placement
    # putting fifteen minutes of something that needs an hour to start into whatever gap fits.
    min_chunk_minutes: Mapped[int] = mapped_column(Integer(), nullable=False)
    # False means atomic: this duration in one block, or not placed.
    splittable: Mapped[bool] = mapped_column(Boolean(), nullable=False)
    status: Mapped[TaskStatus] = mapped_column(_TASK_STATUS_COLUMN, nullable=False)
    # Accumulated from confirmed outcomes. Left intact by completing, so the time spent
    # survives in reports.
    recorded_minutes: Mapped[int] = mapped_column(Integer(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
