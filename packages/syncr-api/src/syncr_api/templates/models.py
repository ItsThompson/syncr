"""The four tables a day shape is stored in, and the invariants the database itself holds.

``day_types`` names a kind of day. ``templates`` is the shape of one day type and
``template_entries`` holds that shape's parts. ``week_patterns`` says which day type each
weekday uses, as one row per weekday.

**One template per day type**, enforced by a unique index rather than by a convention.
Materializing a date resolves its weekday to a day type and the day type to a shape, so two
shapes for one day type would need a composition rule to decide which parts of which one
applied. That is the rule the model does not have: weekly and monthly recurrence is already
``Habit.cadence``, and a second way to compose a day would be the fourth concept these three
exist to avoid.

**A template entry carries no cadence column**, and the absence is the design. There is
nothing here that repeats: an entry is materialized on every date whose weekday maps to its
day type, and how often something recurs is a habit's cadence.

**A template entry is fixed by derivation, so no row anywhere marks it as pinned.** Its time
comes from the shape rather than from a user's own edit, which means the solver may not move
it, it renders no pin glyph, and it creates no ``Pin`` row. Fixed by derivation is not "never
moved": it is never moved SILENTLY. An anchor landing on a materialized entry raises a
conflict for the user to resolve, and the user may still move one by editing this shape or by
pinning that single occurrence. The two senses of the word have to stay apart, because a pin is
a training label and this is not.

``binding_ref`` carries no foreign key: it points at a routine or at a habit, which are separate
tables, so no single reference could name both. ``binding_target`` is what says which table to
read. Without it a reader would have to probe both, and two rows sharing an identifier would
resolve to whichever was probed first.

The grid checks are here as well as in the domain shape, because a value reaching this table
from a later migration or a ``psql`` session is not type-checked at all, and a start or end
between two of the grid's lines is a hard-constraint violation the solver cannot fix: the entry
is fixed by derivation, so nothing may move it.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Time,
)
from sqlalchemy.orm import Mapped, mapped_column

from syncr_api.areas.config import AREAS_TABLE
from syncr_api.core.orm import Base
from syncr_api.core.tenancy import TENANT_ID_COLUMN, TenantScoped
from syncr_api.templates.config import (
    DAY_TYPE_NAME_MAX_LENGTH,
    DAY_TYPES_TABLE,
    ONE_DAY_TYPE_PER_NAME_INDEX,
    ONE_SHAPE_PER_DAY_TYPE_INDEX,
    TEMPLATE_ENTRIES_TABLE,
    TEMPLATE_NAME_MAX_LENGTH,
    TEMPLATES_TABLE,
    WEEK_PATTERNS_TABLE,
)
from syncr_domain.snap import SNAP_MINUTES
from syncr_domain.templates import (
    MAX_DURATION_MINUTES,
    MAX_FLEX_BAND_MINUTES,
    MIN_DURATION_MINUTES,
    BindingTarget,
    TemplateEntryKind,
)
from syncr_domain.weeks import Weekday

if TYPE_CHECKING:
    from enum import StrEnum


def _closed_vocabulary(members: type[StrEnum], name: str) -> Enum:
    """A varchar column plus a generated CHECK over an enum's VALUES.

    A varchar rather than a Postgres enum type, matching the Areas and settings tables: adding
    a member later is a check-constraint edit rather than an ``ALTER TYPE``. ``values_callable``
    stores the member values, which are what the wire and the generated TypeScript carry.
    """
    return Enum(
        members,
        native_enum=False,
        create_constraint=True,
        length=max(len(member.value) for member in members),
        values_callable=lambda enum: [member.value for member in enum],
        name=name,
    )


_ENTRY_KIND_COLUMN = _closed_vocabulary(TemplateEntryKind, "template_entry_kind")
_BINDING_TARGET_COLUMN = _closed_vocabulary(BindingTarget, "binding_target")
_WEEKDAY_COLUMN = _closed_vocabulary(Weekday, "weekday")


class DayTypeRow(Base, TenantScoped):
    """One kind of day: ``Weekday``, ``Uni day``, ``Weekend``.

    Names are unique per tenant. The week pattern's seven rows and the template list both
    identify a day type by its name, so two day types holding one name would leave the user
    choosing between two identical-looking rows.
    """

    __tablename__ = DAY_TYPES_TABLE
    __table_args__ = (
        Index(ONE_DAY_TYPE_PER_NAME_INDEX, TENANT_ID_COLUMN, "name", unique=True),
        Index(
            f"ix_{DAY_TYPES_TABLE}_{TENANT_ID_COLUMN}_created_at", TENANT_ID_COLUMN, "created_at"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(DAY_TYPE_NAME_MAX_LENGTH), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TemplateRow(Base, TenantScoped):
    """The shape of one day type. Exactly one per day type, which the index enforces."""

    __tablename__ = TEMPLATES_TABLE
    __table_args__ = (
        Index(ONE_SHAPE_PER_DAY_TYPE_INDEX, TENANT_ID_COLUMN, "day_type_id", unique=True),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    # Cascades so deleting a TENANT removes its day types and their shapes in one statement.
    # No route deletes a day type, so nothing else reaches this cascade.
    day_type_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{DAY_TYPES_TABLE}.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(TEMPLATE_NAME_MAX_LENGTH), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TemplateEntryRow(Base, TenantScoped):
    """One part of a day shape: a concrete routine or habit, or a slot bound late.

    The check constraint is the pairing rule: a concrete entry names a binding and a slot names
    an Area and no binding. A slot carrying a binding would be a concrete entry that claimed to
    bind late, and a concrete entry without one would name no content at all.
    """

    __tablename__ = TEMPLATE_ENTRIES_TABLE
    __table_args__ = (
        CheckConstraint(
            f"(kind = '{TemplateEntryKind.CONCRETE}' AND binding_ref IS NOT NULL "
            "AND binding_target IS NOT NULL) "
            f"OR (kind = '{TemplateEntryKind.SLOT}' AND binding_ref IS NULL "
            "AND binding_target IS NULL AND area_id IS NOT NULL)",
            name="kind_states_its_binding",
        ),
        CheckConstraint(
            "mod(EXTRACT(MINUTE FROM target_time)::int, "
            f"{SNAP_MINUTES}) = 0 AND EXTRACT(SECOND FROM target_time) = 0",
            name="target_time_is_on_the_grid",
        ),
        CheckConstraint(
            f"duration_minutes BETWEEN {MIN_DURATION_MINUTES} AND {MAX_DURATION_MINUTES} "
            f"AND mod(duration_minutes, {SNAP_MINUTES}) = 0",
            name="duration_is_whole_steps_of_a_day",
        ),
        CheckConstraint(
            f"flex_band_minutes BETWEEN 0 AND {MAX_FLEX_BAND_MINUTES}",
            name="flex_band_shifts_within_a_day",
        ),
        # Every read is one shape's entries in the order the day runs.
        Index(
            f"ix_{TEMPLATE_ENTRIES_TABLE}_{TENANT_ID_COLUMN}_template_id_target_time",
            TENANT_ID_COLUMN,
            "template_id",
            "target_time",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    template_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{TEMPLATES_TABLE}.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[TemplateEntryKind] = mapped_column(_ENTRY_KIND_COLUMN, nullable=False)
    # Wall time, no zone: an entry at 07:00 is 07:00 wherever the user is, resolved against the
    # zone active on the date it materializes for.
    target_time: Mapped[time] = mapped_column(Time(), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(SmallInteger(), nullable=False)
    # How far a placement may SHIFT the entry. Not how far it may shrink it: nothing resizes an
    # entry, because the shape declares its span.
    flex_band_minutes: Mapped[int] = mapped_column(SmallInteger(), nullable=False)
    # Required for a slot, which is a duration of an Area with content bound late. Optional for
    # a concrete entry, whose content already names its own Area.
    area_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{AREAS_TABLE}.id", ondelete="CASCADE"), nullable=True
    )
    binding_target: Mapped[BindingTarget | None] = mapped_column(
        _BINDING_TARGET_COLUMN, nullable=True
    )
    # No foreign key: it names a row in one of two tables, so no single reference could reach
    # both. `binding_target` says which.
    binding_ref: Mapped[UUID | None] = mapped_column(nullable=True)


class WeekPatternRow(Base, TenantScoped):
    """Which day type one weekday uses. Seven rows per tenant, replaced together.

    The primary key is the tenant and the weekday, so a weekday cannot be mapped twice and the
    scope leads the index. There is no surrogate identifier, because nothing addresses one of
    these rows: the pattern is read and replaced whole.

    There is no timestamp either. Nothing orders these rows by when they were written, and the
    week input version is what records that the pattern changed.
    """

    __tablename__ = WEEK_PATTERNS_TABLE
    __table_args__ = (PrimaryKeyConstraint(TENANT_ID_COLUMN, "weekday"),)

    weekday: Mapped[Weekday] = mapped_column(_WEEKDAY_COLUMN, nullable=False)
    day_type_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{DAY_TYPES_TABLE}.id", ondelete="CASCADE"), nullable=False
    )
