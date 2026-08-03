"""The two tables: the hierarchy that carries a budget, and the projects hanging off it.

``areas`` is self-referencing and the reference is nullable, which is what makes a top-level
Area and a child Area one table rather than two. It cascades on delete for the same reason
``plan_revisions.supersedes_id`` does: deleting a TENANT deletes every one of its Areas in
one statement, and a restricting constraint would refuse that while a child still pointed at
its parent. Nothing else deletes an Area. They are permanent in P0: not completed, not
archived, and there is no route that removes one.

``projects`` carries no budget column at all, and that absence is the design. A Project
inherits its parent Area's allocation, so a time-boxed push is expressible without carving a
new wedge out of the pie, and completing one leaves its historical time attribution intact
because the attribution was always to the Area.

The unique index on ``(tenant_id, name)`` is load-bearing rather than tidy. Past twelve Areas
the pigment ramp repeats and identity rests on the hatch and the Area's name, so two Areas
holding one name would leave nothing to tell them apart.

``default_preference_id`` carries no foreign key. Preferences are created by a later
revision, and the column has to exist from the first one that creates ``areas`` because the
Area is where a preference's owner is declared.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from syncr_api.areas.config import (
    AREA_NAME_MAX_LENGTH,
    AREAS_TABLE,
    BUDGET_DECIMAL_PRECISION,
    BUDGET_DECIMAL_SCALE,
    BUDGET_PERCENT_MAX,
    BUDGET_PERCENT_MIN,
    FLOOR_HOURS_MAX,
    FLOOR_HOURS_MIN,
    PROJECT_NAME_MAX_LENGTH,
    PROJECTS_TABLE,
)
from syncr_api.core.orm import Base
from syncr_api.core.tenancy import TENANT_ID_COLUMN, TenantScoped
from syncr_domain.pigments import PIGMENT_COUNT
from syncr_domain.projects import ProjectStatus

# A varchar plus a generated CHECK rather than a Postgres enum type, matching the settings
# module: adding a status later is a check-constraint edit rather than an ALTER TYPE, and the
# constraint is generated from the enum so the two cannot drift. `values_callable` stores the
# member VALUES, which are what the wire and the generated TypeScript carry.
_PROJECT_STATUS_COLUMN = Enum(
    ProjectStatus,
    native_enum=False,
    create_constraint=True,
    length=max(len(status.value) for status in ProjectStatus),
    values_callable=lambda enum: [member.value for member in enum],
    name="project_status",
)

_BUDGET_NUMERIC = Numeric(BUDGET_DECIMAL_PRECISION, BUDGET_DECIMAL_SCALE)


class AreaRow(Base, TenantScoped):
    """One hierarchical life category, and the budget it carries.

    Named for the row rather than for the concept, because ``syncr_domain.budgets.AreaShare``
    is the concept the arithmetic is stated over: the row is what persistence knows, and the
    share is the floor and percentage the report divides. Two names for two things beats one
    name meaning whichever is in scope.
    """

    __tablename__ = AREAS_TABLE
    __table_args__ = (
        CheckConstraint(
            f"pigment_index BETWEEN 0 AND {PIGMENT_COUNT - 1}", name="pigment_index_is_on_the_ramp"
        ),
        CheckConstraint(
            f"budget_percent IS NULL OR budget_percent BETWEEN "
            f"{BUDGET_PERCENT_MIN} AND {BUDGET_PERCENT_MAX}",
            name="budget_percent_is_a_share",
        ),
        CheckConstraint(
            f"floor_hours IS NULL OR floor_hours BETWEEN {FLOOR_HOURS_MIN} AND {FLOOR_HOURS_MAX}",
            name="floor_hours_could_be_met",
        ),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="parent_is_another_area"),
        # Identity past twelve Areas rests on the hatch and the name, so the name has to be
        # unique for that to be true.
        Index(f"uq_{AREAS_TABLE}_{TENANT_ID_COLUMN}_name", TENANT_ID_COLUMN, "name", unique=True),
        # Every list read is "this tenant's Areas, in the order they were declared", which is
        # also the order the ramp dealt their pigments.
        Index(f"ix_{AREAS_TABLE}_{TENANT_ID_COLUMN}_created_at", TENANT_ID_COLUMN, "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{AREAS_TABLE}.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(AREA_NAME_MAX_LENGTH), nullable=False)
    # An index into the sealed ramp, assigned from the deal and never picked as a colour.
    pigment_index: Mapped[int] = mapped_column(SmallInteger(), nullable=False)
    # The share of discretionary time REMAINING after every floor is honored. Null means the
    # Area declares no share, which is different from declaring zero.
    budget_percent: Mapped[Decimal | None] = mapped_column(_BUDGET_NUMERIC, nullable=True)
    # The absolute weekly minimum, in hours as the user authors it. A hard solver constraint.
    floor_hours: Mapped[Decimal | None] = mapped_column(_BUDGET_NUMERIC, nullable=True)
    default_preference_id: Mapped[UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProjectRow(Base, TenantScoped):
    """A time-boxed push inside exactly one Area. It ends; the Area does not."""

    __tablename__ = PROJECTS_TABLE
    __table_args__ = (
        # Every read is either this tenant's projects or the ones inside one Area.
        Index(f"ix_{PROJECTS_TABLE}_{TENANT_ID_COLUMN}_area_id", TENANT_ID_COLUMN, "area_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    # Not nullable and not a list: a Project never spans Areas, which is what keeps an hour
    # spent on it attributable to exactly one Area.
    area_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{AREAS_TABLE}.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(PROJECT_NAME_MAX_LENGTH), nullable=False)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[ProjectStatus] = mapped_column(_PROJECT_STATUS_COLUMN, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
