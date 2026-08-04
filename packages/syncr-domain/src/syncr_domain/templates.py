"""The day-shape vocabulary, and the week pattern that has to map all seven weekdays.

A day shape is declared once and materialized every week, which is what ends repeat
authoring. Three concepts carry it: a **day type** names a kind of day, a **template** is the
shape of one day type, and a **week pattern** says which day type each weekday uses.

**No cadence is expressible on any of them.** Weekly and monthly recurrence is already
``Habit.cadence``, so a template period would have needed composition and override rules for
no added expressiveness. That is why this module has no period, no interval, and no repeat
vocabulary: the three concepts above replace three template periods, and the absence is the
design rather than an omission.

**An entry's kind decides what it may carry**, and the two kinds are not interchangeable. A
concrete entry names a specific routine or habit; a slot names an Area and a duration and
binds its content late, when the solver knows the most. Nothing here checks that pairing,
deliberately: the shapes a declaration is expressed in make an inconsistent entry
unrepresentable, so there is no rule left to state.

**An entry's span owes the fifteen-minute grid.** A concrete entry and a slot both materialize
into a block whose start is the target time on a date and whose end is that start plus the
duration, and both of those have to land on a quarter hour. The entry is fixed by derivation,
so the solver may not move it onto the grid: an off-grid declaration would make the week
infeasible for a reason the user never sees. :class:`EntrySpan` is therefore where the grid is
checked, at the point where a span is first expressible. It is also where a target time carrying
a zone is refused: the zone comes from the date the entry materializes for, and a stored target
time holds no offset, so an offset offered here would be dropped rather than honored.

:class:`WeekPattern` is the one place the seven-weekday rule lives. It is a constructor
precondition rather than a validation step, so a partial mapping is not a pattern that fails a
check: it is not a pattern at all, and no caller can hold one.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from syncr_domain.errors import DomainError
from syncr_domain.snap import SNAP_MINUTES, is_a_snap_multiple, is_wall_time_on_snap_grid
from syncr_domain.weeks import Weekday

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syncr_domain.identifiers import DayTypeId
    from syncr_domain.zones import LocalTime

# One step of the grid. An entry shorter than a step could not both start and end on it.
MIN_DURATION_MINUTES: Final = SNAP_MINUTES
# An entry names a time of day, so a nominal day is the ceiling: past it a span stops describing
# part of a day at all. It is NOT a no-overlap guarantee. Whether one occurrence reaches its own
# next one depends on the local day's real length, which only the week assembler knows: a
# spring-forward day is 23 hours, so a span of a nominal day ends an hour inside the next one.
MAX_DURATION_MINUTES: Final = 24 * 60
# The band shifts the entry either way, so half a day is the point past which the target time
# says nothing about when the entry happens.
MAX_FLEX_BAND_MINUTES: Final = 12 * 60


class TemplateEntryKind(StrEnum):
    """Whether an entry names its content or leaves it to be bound at solve time."""

    CONCRETE = "concrete"
    SLOT = "slot"


class BindingTarget(StrEnum):
    """Which table a concrete entry's binding names.

    A concrete entry points at a routine or at a habit, and the two live in separate tables
    with no shared parent, so the identifier alone does not say which to read. Without this a
    reader would have to probe both, and two rows sharing an identifier would resolve to
    whichever table it looked in first.
    """

    ROUTINE = "routine"
    HABIT = "habit"


class WeekPatternIncomplete(DomainError):
    """A mapping was offered as a week pattern without covering all seven weekdays."""


class EntryField(StrEnum):
    """The field a rejection names, spelled as the span's own field names.

    Carried on the error so the mapping from a refusal to a field is the refusal itself,
    rather than a table elsewhere that a fourth field would have to be added to.
    """

    TARGET_TIME = "target_time"
    DURATION = "duration_minutes"
    FLEX_BAND = "flex_band_minutes"


class TemplateEntryError(DomainError):
    """An entry's span was refused, naming the field that was refused."""

    def __init__(self, field: EntryField, message: str) -> None:
        self.field = field
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class EntrySpan:
    """When an entry targets, how long it runs, and how far the solver may shift it.

    The kind, the binding, and the Area are absent: this is the half both kinds of entry
    carry identically, so a rule about the grid is stated once rather than per kind.

    The band is bounded but not held to the grid, which is deliberate. It bounds a shift
    rather than being one, and the shift itself is a placement, which lands on the grid
    because every placement does. A band below one step therefore permits no shift at all,
    which is a weaker statement than the caller probably meant but not a wrong one.
    """

    target_time: LocalTime
    duration_minutes: int
    flex_band_minutes: int

    def __post_init__(self) -> None:
        if self.target_time.tzinfo is not None:
            raise TemplateEntryError(
                EntryField.TARGET_TIME,
                f"a target time is wall time and names no zone, got {self.target_time!r}. The "
                "zone comes from the date the entry materializes for, and the column that stores "
                "a target time holds no offset, so one sent here would be dropped rather than "
                "honored",
            )
        if not is_wall_time_on_snap_grid(self.target_time):
            raise TemplateEntryError(
                EntryField.TARGET_TIME,
                f"a target time lands on a quarter hour, got {self.target_time.isoformat()}. "
                "An entry is fixed by derivation, so nothing moves it onto the grid later: "
                "the block it materializes would start between two of the grid's lines",
            )
        if not MIN_DURATION_MINUTES <= self.duration_minutes <= MAX_DURATION_MINUTES:
            raise TemplateEntryError(
                EntryField.DURATION,
                f"an entry runs for {MIN_DURATION_MINUTES} to {MAX_DURATION_MINUTES} minutes, "
                f"got {self.duration_minutes}. An entry names a time of day, so a span past a "
                "nominal day stops describing part of one",
            )
        if not is_a_snap_multiple(self.duration_minutes):
            raise TemplateEntryError(
                EntryField.DURATION,
                f"a duration is a whole number of {SNAP_MINUTES}-minute steps, got "
                f"{self.duration_minutes}. A start on the grid plus this duration would end "
                "between two of the grid's lines",
            )
        if not 0 <= self.flex_band_minutes <= MAX_FLEX_BAND_MINUTES:
            raise TemplateEntryError(
                EntryField.FLEX_BAND,
                f"a flex band is 0 to {MAX_FLEX_BAND_MINUTES} minutes, got "
                f"{self.flex_band_minutes}. The band shifts the entry rather than resizing it",
            )


@dataclass(frozen=True, slots=True)
class WeekPattern:
    """Which day type each weekday uses. All seven, or it is not a pattern.

    The completeness rule is enforced on construction, which is what makes a partial mapping
    unrepresentable rather than merely rejected: a caller cannot hold one to write, and a read
    that assembled one from an incomplete set of rows fails where the corruption is instead of
    materializing five days out of seven.
    """

    mapping: Mapping[Weekday, DayTypeId]

    def __post_init__(self) -> None:
        missing = [weekday for weekday in Weekday if weekday not in self.mapping]
        if missing:
            named = ", ".join(missing)
            raise WeekPatternIncomplete(
                f"a week pattern maps all seven weekdays and this one leaves out {named}: "
                "a day with no day type would materialize nothing at all"
            )
        # Copied so the pattern cannot change under a holder after the rule was checked
        # against it. Frozen protects the field, not the mapping the caller passed in.
        object.__setattr__(self, "mapping", dict(self.mapping))

    def day_type(self, weekday: Weekday) -> DayTypeId:
        """The day type this weekday uses. Every weekday has one."""
        return self.mapping[weekday]

    def covers(self, day_type_id: DayTypeId) -> bool:
        """Whether any weekday uses this day type.

        What makes a template edit's reach decidable: a shape whose day type no weekday uses
        changes no week, so nothing downstream of it has to be invalidated.
        """
        return day_type_id in self.mapping.values()
