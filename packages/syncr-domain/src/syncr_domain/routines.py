"""The Routine: the circadian frame, as a span rather than a marker.

``Sleep 23:00 + 8h`` is what bounds a day. Subtracting the frame is what makes
discretionary time computable at all, so a routine without a duration is refused rather
than defaulted: there would be nothing to subtract, and every budget figure downstream
would be a plausible number computed from an incomplete denominator.

A routine carries no Area and therefore no pigment. It defines how much time exists, so
it is not competing for it, and it never appears in Area budget arithmetic.

## The minimum is a floor, and equality is the default

``min_duration_minutes`` is how far a routine may be compressed, and it defaults to the
target duration, which makes the routine inelastic. The sleep floor is this field on the
sleep routine and lives nowhere else. There is no sleep-specific rule: ``Lunch`` gets the
same field and the same default, so nothing offers to compress it unless the user gives it
a minimum below its target.

:attr:`RoutineSpan.is_elastic` is the predicate a tradeoff enumerator reads before
offering to shorten a routine, which is why the rule is here rather than beside the
enumerator: the default makes it false for every routine the user has not opted in.

## The flex band shifts, it does not shrink

``flex_band_minutes`` is how far a placement may MOVE the target time. No operation
resizes a routine: a span arrives at the solver already resolved, and the frame defines
the search space rather than competing inside it. The effective duration of one
occurrence, and its clamp to the minimum, are the week assembler's (ticket 25).

## A target time is wall time, at minute resolution

The target names a time of day and nothing else. A value carrying an offset is refused, and
so is one carrying seconds: an offset would be dropped by any store whose column has no
zone, leaving the frame an hour out with nothing to say so, and every duration here is a
count of minutes, so a span starting mid-minute could not be one of them. The rule is on the
span rather than only at an HTTP boundary, so it holds for every writer.

## A duration is elapsed minutes, so a transition does not change it

:meth:`RoutineSpan.occurrence_on` resolves the target time against the zone active on
that date and then adds the duration as ELAPSED time. Eight hours of sleep is eight hours
on every night of the year, so a transition moves the wall-clock end rather than the
length: on ``Europe/London``, ``Sleep 23:00 + 8h`` ends at 08:00 local on the
spring-forward morning and at 06:00 local on the fall-back morning. Reading the duration
as wall-clock arithmetic would instead make one night seven real hours and the other nine,
which would silently spend a sleep floor the solver is forbidden to spend.

Three wall-time inputs have no single answer, and all three are resolved by
:func:`syncr_domain.zones.to_instant` rather than a second time here:

*A target time inside a spring-forward gap* shifts forward by the gap, so 01:30 on
``Europe/London``, 2026-03-29 starts at 02:30 local.

*A target time that occurs twice* takes the first occurrence, so 01:30 on 2026-10-25
starts at 01:30 BST rather than 01:30 GMT an hour later.

*A date the zone skips entirely* carries its occurrence onto the following date at the
same wall time, which is what ``Pacific/Apia`` did to 2011-12-30. No date this product
plans is one of those, and the behavior is stated because the input is real rather than
because a week needs it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from syncr_domain.errors import DomainError
from syncr_domain.intervals import Interval
from syncr_domain.zones import to_instant

if TYPE_CHECKING:
    from syncr_domain.zones import Date, LocalTime, ZoneId

# A routine is a span, so its shortest legal duration is one minute of it.
MIN_DURATION_MINUTES: Final = 1
# A routine names a time of day, so its span is capped at the day it names. The cap does NOT
# keep an occurrence clear of its own next one: a spring-forward local day is 23 hours, so on
# `Europe/London` 2026-03-28 a 1440-minute span overlaps the next date's occurrence by an hour
# and 1381 minutes already overlaps by a minute. No positive cap can deliver that property
# either, because a date the zone skips entirely gives two dates the same instant: on
# `Pacific/Apia` the 2011-12-30 and 2011-12-31 occurrences of one routine are the same
# interval at any duration. Self-overlap is therefore a layout question, and the week
# assembler owns it.
MAX_DURATION_MINUTES: Final = 24 * 60
# A band moves the target either way, so half a day is the point past which the target time
# says nothing about when the routine happens.
MAX_FLEX_BAND_MINUTES: Final = 12 * 60


class SpanField(StrEnum):
    """The field a rejection names, spelled as the span's own field names.

    A boundary needs to say which field it refused. Carrying the name on the error means
    the mapping from a refusal to a field is the refusal itself, rather than a table
    somewhere else that a fourth field would have to be added to.
    """

    TARGET_TIME = "target_time"
    DURATION = "duration_minutes"
    MINIMUM = "min_duration_minutes"
    FLEX_BAND = "flex_band_minutes"


class RoutineError(DomainError):
    """A routine's span was refused, naming the field that was refused."""

    def __init__(self, field: SpanField, message: str) -> None:
        self.field = field
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class RoutineSpan:
    """One routine's shape: where it targets, how long it runs, and how far it may give.

    The identity and the title are absent. This is the part the arithmetic is stated over,
    and the row that carries an id is persistence's, so a span can be built from literals
    wherever a rule about the frame is asserted.
    """

    target_time: LocalTime
    duration_minutes: int
    min_duration_minutes: int
    flex_band_minutes: int

    def __post_init__(self) -> None:
        if self.target_time.tzinfo is not None:
            raise RoutineError(
                SpanField.TARGET_TIME,
                f"a target time is wall time and names no zone, got {self.target_time!r}. "
                "The zone comes from the day the routine materializes on",
            )
        if self.target_time.second or self.target_time.microsecond:
            raise RoutineError(
                SpanField.TARGET_TIME,
                f"a target time is minute-resolution, got {self.target_time!r}. Every "
                "duration here is a count of minutes, so a span starting mid-minute could "
                "not be one of them",
            )
        if not MIN_DURATION_MINUTES <= self.duration_minutes <= MAX_DURATION_MINUTES:
            raise RoutineError(
                SpanField.DURATION,
                f"a routine runs for {MIN_DURATION_MINUTES} to {MAX_DURATION_MINUTES} "
                f"minutes, got {self.duration_minutes}. A routine is a span, not a marker: "
                "without a duration there is nothing to subtract from the day, so "
                "discretionary time cannot be computed",
            )
        if not 0 < self.min_duration_minutes <= self.duration_minutes:
            raise RoutineError(
                SpanField.MINIMUM,
                f"a routine's minimum is above 0 and at most its target duration of "
                f"{self.duration_minutes} minutes, got {self.min_duration_minutes}",
            )
        if not 0 <= self.flex_band_minutes <= MAX_FLEX_BAND_MINUTES:
            raise RoutineError(
                SpanField.FLEX_BAND,
                f"a flex band is 0 to {MAX_FLEX_BAND_MINUTES} minutes, got "
                f"{self.flex_band_minutes}. The band shifts the routine rather than "
                "shrinking it",
            )

    @property
    def is_elastic(self) -> bool:
        """Whether this routine may be shortened at all.

        False for every routine whose minimum equals its target, which is the default, and
        it is what a tradeoff enumerator asks before offering to reduce one.
        """
        return self.min_duration_minutes < self.duration_minutes

    def occurrence_on(self, on: Date, zone: ZoneId) -> Interval:
        """This routine's span on one local date, at its TARGET duration.

        The effective duration, which a tradeoff reduction lowers and the minimum clamps,
        is the week assembler's and is not computed here.

        The interval starts where the target time resolves in ``zone`` on ``on`` and runs
        for the duration in elapsed minutes, so a daylight-saving transition inside it
        moves the wall-clock end rather than shortening the routine.
        """
        start = to_instant(self.target_time, on, zone)
        return Interval(start, start + timedelta(minutes=self.duration_minutes))
