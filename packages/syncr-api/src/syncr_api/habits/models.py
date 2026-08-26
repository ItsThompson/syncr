"""The ``habits`` table: cadence, duration, the miss policy, and what an occurrence binds to.

Three shapes of the entity reach the columns, and each is stored the way it is for a reason.

**Cadence is a discriminator plus two nullable numbers**, not one column called ``value``,
because a row is read by a human in ``psql`` and by a migration years from now: naming the
number tells the reader what it means. The check constraint refuses a row two kinds could be
read out of, so a row carrying both numbers cannot resolve to whichever one the discriminator
happens to name.

**A duration is a range whose fixed case is ``min == max``.** There is no kind column and no
nullability, so "fixed or elastic" is a comparison rather than a state, and both bounds carry
the grid check because a block's start and end both land on the quarter hour.

**Variants are an ordered JSONB list**, and the constraint pairs their presence with the
binding source in both directions. X3 and X4 are one rule, and stating it as an equality
between two predicates is what makes it one constraint rather than two that could disagree.

Two columns are deliberately absent.

``preferred_time``: when a habit's work should happen is a ``Preference``, whose owner is
polymorphic and may be this habit. A column here would be a second home for the value.

``cursor``: the rotation cursor is a projection of the outcome log, derived by
``syncr_domain.cursor``. There is no column for it to drift from, which is what makes desync
impossible rather than merely unlikely.

One projection IS stored, and the asymmetry with ``cursor`` is the point.

``charged_misses``: the walked count of confirmed misses less the make-ups completed against
them, restated on the habit row by the outcome write every time a row of the log changes. A
cursor survives no window: dropping one completion moves every later week onto the wrong
variant, so it stays derived over the whole log. The charge is different: what makes it exact
is the walk, not the rows, and the walk runs where the rows are written. Storing its answer is
what keeps the figure from falling when history ages out of any read a request can afford.

Every bound below is imported from ``syncr_domain.habits``, so the database and the entity
cannot disagree about what a cadence or a duration is. A MIGRATION spells them out instead,
because a revision describes the schema at its own point in the chain.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from syncr_api.areas.config import AREAS_TABLE
from syncr_api.core.columns import values_in
from syncr_api.core.orm import Base
from syncr_api.core.tenancy import TENANT_ID_COLUMN, TenantScoped
from syncr_api.habits.config import HABIT_TITLE_MAX_LENGTH, HABITS_TABLE
from syncr_domain.habits import (
    MAX_APPROX_DAYS,
    MAX_DEBT_CAP_PERIODS,
    MAX_DURATION_MINUTES,
    MAX_TIMES_PER_WEEK,
    MAX_VARIANTS,
    MIN_APPROX_DAYS,
    MIN_DEBT_CAP_PERIODS,
    MIN_DURATION_MINUTES,
    BindingSource,
    CadenceKind,
    MissPolicy,
)
from syncr_domain.snap import SNAP_MINUTES

# A varchar plus a generated CHECK rather than a Postgres enum type, matching the areas and
# settings modules: adding a member later is a check-constraint edit rather than an ALTER TYPE,
# and the constraint is generated from the enum so the two cannot drift. `values_callable`
# stores the member VALUES, which are what the wire and the generated TypeScript carry.
_MISS_POLICY_COLUMN = Enum(
    MissPolicy,
    native_enum=False,
    create_constraint=True,
    length=max(len(policy.value) for policy in MissPolicy),
    values_callable=lambda enum: [member.value for member in enum],
    name="miss_policy",
)

_BINDING_SOURCE_COLUMN = Enum(
    BindingSource,
    native_enum=False,
    create_constraint=True,
    length=max(len(source.value) for source in BindingSource),
    values_callable=lambda enum: [member.value for member in enum],
    name="binding_source",
)

_CADENCE_KIND_LENGTH = max(len(kind.value) for kind in CadenceKind)

_ROTATION = BindingSource.ROTATION.value


class HabitRow(Base, TenantScoped):
    """One recurring intention, and everything about it that is stored rather than derived."""

    __tablename__ = HABITS_TABLE
    __table_args__ = (
        CheckConstraint(
            values_in("cadence_kind", [kind.value for kind in CadenceKind]),
            name="cadence_kind_is_known",
        ),
        # A row two kinds could be read out of resolves to neither, so each kind names exactly
        # the numbers it uses and forbids the other. `ELSE false` rather than no else: a CASE
        # with no matching branch is NULL, and a check constraint passes on NULL.
        CheckConstraint(
            f"CASE cadence_kind"
            f" WHEN '{CadenceKind.TIMES_PER_WEEK.value}'"
            f" THEN cadence_times_per_week IS NOT NULL AND cadence_approx_days IS NULL"
            f" WHEN '{CadenceKind.DAILY.value}'"
            f" THEN cadence_times_per_week IS NULL AND cadence_approx_days IS NULL"
            f" WHEN '{CadenceKind.EVERY_APPROX_DAYS.value}'"
            f" THEN cadence_approx_days IS NOT NULL AND cadence_times_per_week IS NULL"
            f" ELSE false END",
            name="cadence_carries_only_its_own_numbers",
        ),
        CheckConstraint(
            f"cadence_times_per_week IS NULL OR cadence_times_per_week BETWEEN "
            f"1 AND {MAX_TIMES_PER_WEEK}",
            name="a_count_per_week_is_a_cadence",
        ),
        CheckConstraint(
            f"cadence_approx_days IS NULL OR cadence_approx_days BETWEEN "
            f"{MIN_APPROX_DAYS} AND {MAX_APPROX_DAYS}",
            name="an_interval_in_days_is_a_cadence",
        ),
        CheckConstraint(
            f"duration_min_minutes BETWEEN {MIN_DURATION_MINUTES} AND {MAX_DURATION_MINUTES}"
            f" AND duration_max_minutes BETWEEN {MIN_DURATION_MINUTES} AND {MAX_DURATION_MINUTES}"
            f" AND duration_min_minutes <= duration_max_minutes",
            name="a_duration_is_a_range_that_runs_forward",
        ),
        # A start on the grid plus a multiple of the step gives an end on the grid, which is what
        # a declared duration owes the block it materializes into.
        CheckConstraint(
            f"duration_min_minutes % {SNAP_MINUTES} = 0"
            f" AND duration_max_minutes % {SNAP_MINUTES} = 0",
            name="a_duration_lands_on_the_snap_grid",
        ),
        CheckConstraint("jsonb_typeof(variants) = 'array'", name="variants_is_an_ordered_list"),
        # X3 and X4 as one equality between two predicates: a rotation has variants and nothing
        # else may, so neither direction can hold without the other.
        CheckConstraint(
            f"(binding_source = '{_ROTATION}') = (jsonb_array_length(variants) > 0)",
            name="variants_match_the_binding_source",
        ),
        CheckConstraint(
            f"jsonb_array_length(variants) <= {MAX_VARIANTS}",
            name="a_rotation_is_not_a_backlog",
        ),
        CheckConstraint(
            f"debt_cap_periods BETWEEN {MIN_DEBT_CAP_PERIODS} AND {MAX_DEBT_CAP_PERIODS}",
            name="a_debt_cap_is_a_count_of_periods",
        ),
        CheckConstraint("charged_misses >= 0", name="charged_misses_is_a_count"),
        # Every list read is "this tenant's habits, in the order they were declared".
        Index(f"ix_{HABITS_TABLE}_{TENANT_ID_COLUMN}_created_at", TENANT_ID_COLUMN, "created_at"),
        # The week assembler and the preference chain both read one Area's habits.
        Index(f"ix_{HABITS_TABLE}_{TENANT_ID_COLUMN}_area_id", TENANT_ID_COLUMN, "area_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    # Not nullable: a habit's time is attributable to exactly one Area, which is what keeps the
    # pie adding up.
    area_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{AREAS_TABLE}.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(HABIT_TITLE_MAX_LENGTH), nullable=False)
    cadence_kind: Mapped[str] = mapped_column(String(_CADENCE_KIND_LENGTH), nullable=False)
    # Set for `times_per_week` and null otherwise. The pair is guarded above.
    cadence_times_per_week: Mapped[int | None] = mapped_column(SmallInteger(), nullable=True)
    # Set for `every_approx_days` and null otherwise.
    cadence_approx_days: Mapped[int | None] = mapped_column(SmallInteger(), nullable=True)
    # The floor and the ceiling of one occurrence. Equal means fixed: this span or nothing.
    duration_min_minutes: Mapped[int] = mapped_column(SmallInteger(), nullable=False)
    duration_max_minutes: Mapped[int] = mapped_column(SmallInteger(), nullable=False)
    miss_policy: Mapped[MissPolicy] = mapped_column(_MISS_POLICY_COLUMN, nullable=False)
    binding_source: Mapped[BindingSource] = mapped_column(_BINDING_SOURCE_COLUMN, nullable=False)
    # Ordered, and non-empty exactly for `rotation`. The cursor is an index into it.
    variants: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    debt_cap_periods: Mapped[int] = mapped_column(SmallInteger(), nullable=False)
    # The walked charge the outcome write restates: confirmed skips, less the make-ups completed
    # against them, floored per credit. Derived nowhere at read time, so no window a reader takes
    # can lower it; see the module docstring's paragraph on the two projections.
    charged_misses: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
