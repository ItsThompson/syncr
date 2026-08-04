"""The ``preferences`` table: one row per owner, with the owner's kind and its identity paired.

**The owner is three nullable foreign keys plus a discriminator, not one untyped identifier.**
An untyped ``owner_id`` could reference nothing, so removing a habit would leave a preference
addressed to a row that no longer exists and the resolution would read a window the user
deleted. Three real references cascade, so a preference dies with its owner. The pairing of the
discriminator against which reference is set is ONE constraint stated as a ``CASE``, rather than
two that could disagree, and ``ELSE false`` rather than no else clause: a ``CASE`` with no
matching branch is NULL, and a check constraint passes on NULL.

**One preference per owner is a unique index rather than a rule the service remembers.** Three
of them, one per reference column, because Postgres treats NULLs as distinct: the Area index
constrains Area-owned rows and ignores every other row. Each is tenant-prefixed, which the
reference column alone would not need but every scoped read does.

**The daily cap's own constraint is the structural half of confining it to an Area.** The domain
refuses it on any other owner and the request shape has no field for it; this stops a row
reaching the table from ``psql`` or from a later migration with a cap on a habit.

**Windows are an ordered JSONB list, and their interior is not database-validated.** JSONB is
schemaless there, so what the column owes its readers is the list's shape and length; the wall
times inside it are validated by :class:`syncr_domain.preferences.LocalTimeWindow`, on the way
in and again on the way out. The wall times are stored as ``HH:MM:SS`` strings rather than in a
``time`` column: a ``TIME WITHOUT TIME ZONE`` column drops an offset in silence, and nothing
downstream could tell the value had moved.

Every bound below is imported from ``syncr_domain.preferences``, so the database and the entity
cannot disagree about what a window list or an ideal duration is. A MIGRATION spells them out
instead, because a revision describes the schema at its own point in the chain.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, SmallInteger, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from syncr_api.areas.config import AREAS_TABLE
from syncr_api.core.columns import values_in
from syncr_api.core.orm import Base
from syncr_api.core.tenancy import TENANT_ID_COLUMN, TenantScoped
from syncr_api.habits.config import HABITS_TABLE
from syncr_api.preferences.config import PREFERENCES_TABLE
from syncr_api.tasks.config import TASKS_TABLE
from syncr_domain.preferences import (
    MAX_MAX_PER_DAY_MINUTES,
    MAX_PREFERRED_DURATION_MINUTES,
    MAX_WINDOWS,
    MIN_MAX_PER_DAY_MINUTES,
    MIN_PREFERRED_DURATION_MINUTES,
    PreferenceOwnerKind,
    PreferenceStrength,
)
from syncr_domain.snap import SNAP_MINUTES

_OWNER_KIND_LENGTH = max(len(kind.value) for kind in PreferenceOwnerKind)
_STRENGTH_LENGTH = max(len(strength.value) for strength in PreferenceStrength)

_AREA = PreferenceOwnerKind.AREA.value
_HABIT = PreferenceOwnerKind.HABIT.value
_TASK = PreferenceOwnerKind.TASK.value


class PreferenceRow(Base, TenantScoped):
    """When one Area's, Habit's, or Task's work should happen."""

    __tablename__ = PREFERENCES_TABLE
    __table_args__ = (
        CheckConstraint(
            values_in("owner_kind", [kind.value for kind in PreferenceOwnerKind]),
            name="owner_kind_is_known",
        ),
        # Exactly one reference, and it is the one the discriminator names. A row two owners
        # could be read out of resolves to whichever column the reader looked at first.
        CheckConstraint(
            f"CASE owner_kind"
            f" WHEN '{_AREA}'"
            f" THEN area_id IS NOT NULL AND habit_id IS NULL AND task_id IS NULL"
            f" WHEN '{_HABIT}'"
            f" THEN habit_id IS NOT NULL AND area_id IS NULL AND task_id IS NULL"
            f" WHEN '{_TASK}'"
            f" THEN task_id IS NOT NULL AND area_id IS NULL AND habit_id IS NULL"
            f" ELSE false END",
            name="exactly_one_owner_and_it_is_the_kind_named",
        ),
        CheckConstraint(
            values_in("strength", [strength.value for strength in PreferenceStrength]),
            name="a_strength_is_strong_or_soft_and_never_hard",
        ),
        CheckConstraint("jsonb_typeof(windows) = 'array'", name="windows_is_an_ordered_list"),
        CheckConstraint(
            f"jsonb_array_length(windows) <= {MAX_WINDOWS}",
            name="a_preference_names_a_few_times_of_day",
        ),
        CheckConstraint(
            f"preferred_duration_minutes IS NULL OR (preferred_duration_minutes BETWEEN "
            f"{MIN_PREFERRED_DURATION_MINUTES} AND {MAX_PREFERRED_DURATION_MINUTES}"
            f" AND preferred_duration_minutes % {SNAP_MINUTES} = 0)",
            name="an_ideal_session_lands_on_the_snap_grid",
        ),
        # The structural half of confining the cap to an Area: an override that could carry one
        # would be an override that could relax a hard constraint.
        CheckConstraint(
            f"max_per_day_minutes IS NULL OR owner_kind = '{_AREA}'",
            name="a_daily_cap_belongs_to_an_area",
        ),
        CheckConstraint(
            f"max_per_day_minutes IS NULL OR max_per_day_minutes BETWEEN "
            f"{MIN_MAX_PER_DAY_MINUTES} AND {MAX_MAX_PER_DAY_MINUTES}",
            name="a_daily_cap_admits_at_least_one_block",
        ),
        # One preference per owner. Three indexes rather than one over the discriminator and a
        # shared column, because there is no shared column: each constrains the rows whose own
        # reference is set and ignores the rest, which is exactly what NULLs being distinct buys.
        Index(
            f"uq_{PREFERENCES_TABLE}_{TENANT_ID_COLUMN}_area_id",
            TENANT_ID_COLUMN,
            "area_id",
            unique=True,
        ),
        Index(
            f"uq_{PREFERENCES_TABLE}_{TENANT_ID_COLUMN}_habit_id",
            TENANT_ID_COLUMN,
            "habit_id",
            unique=True,
        ),
        Index(
            f"uq_{PREFERENCES_TABLE}_{TENANT_ID_COLUMN}_task_id",
            TENANT_ID_COLUMN,
            "task_id",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_kind: Mapped[str] = mapped_column(String(_OWNER_KIND_LENGTH), nullable=False)
    # Set for an Area owner and null otherwise. The triple is guarded above.
    area_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{AREAS_TABLE}.id", ondelete="CASCADE"), nullable=True
    )
    habit_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{HABITS_TABLE}.id", ondelete="CASCADE"), nullable=True
    )
    task_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{TASKS_TABLE}.id", ondelete="CASCADE"), nullable=True
    )
    # Ordered earliest first, and possibly empty: on an override an empty list replaces its
    # Area's windows with none, which is how one habit opts out of a preference its Area keeps.
    windows: Mapped[list[dict[str, str]]] = mapped_column(JSONB, nullable=False)
    strength: Mapped[str] = mapped_column(String(_STRENGTH_LENGTH), nullable=False)
    preferred_duration_minutes: Mapped[int | None] = mapped_column(SmallInteger(), nullable=True)
    # An Area's hard daily ceiling. It reaches the solver as the Area budget's own figure rather
    # than through the resolved preference, which is what keeps an override unable to relax it.
    max_per_day_minutes: Mapped[int | None] = mapped_column(SmallInteger(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
