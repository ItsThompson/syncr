"""``detect_repeated_pins``: the structural pattern that goes to the template, not to a weight.

The learner absorbs statistical patterns. **Templates absorb structural ones.** Pinning the same
content to the same local time three weeks running is structural, so it is raised as a template
promotion rather than fitted into a number.

**It is a domain rule with two readers**, which is why it lives here rather than in the offline
learning package. The nightly run reports the candidates it finds on its run report; the weekly
session raises them as a question the user answers. The api image cannot depend on the learning
package, because that package carries scipy, so a rule stated there would have had to be stated a
second time to reach a request.

## Grouping drops ``occurrence_key``, and that is what makes it work at all

A pin's binding names the content, which occurrence of it, and which chunk of a split task. The
occurrence key is scoped to its own week -- an index in expansion order, or a date -- so two pins of
the same habit in two weeks never share one. Grouping on the whole binding would therefore find a
group of size one every time, whatever the user did.

So the group is ``(kind, entity, local time)``. It works across weeks because the key that is
week-scoped is dropped, and across occurrences because a second gym session on the same weekday at
the same hour is the same structural claim as the first.

**This is one pass over pin rows**, which is why pins are first-class rows rather than fields inside
a revision document: a group spanning three weeks is a scan, and it would otherwise be three
document reads and a walk.

## It is raised, never applied

syncr observes and proposes; the user decides. The candidate names the binding, the time and the
week count, and it goes to the weekly session as a question.

## It is addressed by the group it was found by

Nothing stores a candidate, so nothing mints an identifier for one. ``PromotionRef`` is the group
key rendered as a value a URL can carry and read back, which is what lets an accept name one
pattern and a decline silence the same one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import TYPE_CHECKING, Final
from uuid import UUID

from syncr_domain.budgets import MINUTES_PER_HOUR
from syncr_domain.errors import DomainError
from syncr_domain.identity import BindingKind
from syncr_domain.weeks import longest_consecutive_run
from syncr_domain.zones import resolve_zone

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_domain.identity import BindingRef
    from syncr_domain.intervals import Instant
    from syncr_domain.weeks import IsoWeek
    from syncr_domain.zones import ZoneId

CONSECUTIVE_WEEKS_FOR_PROMOTION: Final = 3
"""How many consecutive ISO weeks of one pin make a template promotion candidate."""

_REF_SEPARATOR: Final = ":"
_REF_PARTS: Final = 4
_MINUTES_PER_DAY: Final = 24 * MINUTES_PER_HOUR
_MONDAY: Final = 1
_SUNDAY: Final = 7


class PromotionRefError(DomainError):
    """The value names no promotion candidate."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PromotionRef:
    """What a promotion candidate is addressed by, which is the group the rule groups on.

    Nothing stores a candidate. Detection is one pass over pin rows, so there is no row whose
    primary key could name one, and the identity has to be derivable from the pattern itself:
    the content, the weekday, and the minute of the day. That is exactly what ``_group_of``
    already answers, which is why this is a rendering of it rather than a second identity.

    **The week count is deliberately not part of it.** A run that has grown from three weeks to
    four is the same pattern, so a decline of one is a decline of the other; an identity carrying
    the count would let a fourth week ask a question the reader has already answered.
    """

    kind: BindingKind
    entity_id: UUID
    weekday: int
    minute_of_day: int

    def __post_init__(self) -> None:
        if not _MONDAY <= self.weekday <= _SUNDAY:
            raise PromotionRefError(
                f"a weekday runs {_MONDAY} to {_SUNDAY}, Monday first, got {self.weekday}"
            )
        if not 0 <= self.minute_of_day < _MINUTES_PER_DAY:
            raise PromotionRefError(
                f"a minute of the day runs 0 to {_MINUTES_PER_DAY - 1}, got {self.minute_of_day}"
            )

    @property
    def id(self) -> str:
        """The identifier a URL carries, which is the four values a candidate is grouped by."""
        return _REF_SEPARATOR.join(
            (self.kind.value, str(self.entity_id), str(self.weekday), str(self.minute_of_day))
        )

    @property
    def wall_time(self) -> time:
        """The time of day this content keeps being pinned to, as a day-shape entry declares one.

        A wall time, carrying no zone, because the pins were grouped in the tenant's HOME zone and a
        template entry holds a wall time: any other zone would offer a time a template cannot hold.
        """
        hour, minute = divmod(self.minute_of_day, MINUTES_PER_HOUR)
        return time(hour=hour, minute=minute)

    @property
    def local_time(self) -> str:
        """The wall time as the reader and the template both spell it."""
        return f"{self.wall_time.hour:02d}:{self.wall_time.minute:02d}"

    @classmethod
    def parse(cls, value: str) -> PromotionRef:
        """The reference ``value`` names, or a refusal stating the shape.

        Round-trips :attr:`id`, and refuses everything else: an accept edits a template and a
        decline suppresses a question, so a value this class did not produce must not reach
        either.
        """
        parts = value.split(_REF_SEPARATOR)
        if len(parts) != _REF_PARTS:
            raise PromotionRefError(
                f"{value!r} is not a promotion identifier such as "
                f"'habit{_REF_SEPARATOR}<uuid>{_REF_SEPARATOR}2{_REF_SEPARATOR}780'"
            )
        kind, entity, weekday, minute = parts
        try:
            return cls(
                kind=BindingKind(kind),
                entity_id=UUID(entity),
                weekday=int(weekday),
                minute_of_day=int(minute),
            )
        except ValueError as error:
            # `PromotionRefError` is a `DomainError` and so a `ValueError`, so the bounds this
            # class states above arrive here too and are re-raised with the value they refused.
            raise PromotionRefError(f"{value!r} is not a promotion identifier: {error}") from error


@dataclass(frozen=True, slots=True, kw_only=True)
class PinPlacement:
    """One live pin, as promotion detection reads it.

    ``zone`` is the tenant's HOME zone rather than the zone active on the pin's own date. A
    promotion candidate proposes a template entry, a template entry is declared as a wall time in
    the home zone, and grouping in any other zone would offer the user a time their template cannot
    hold.
    """

    binding: BindingRef
    iso_week: IsoWeek
    starts_at: Instant
    zone: ZoneId


@dataclass(frozen=True, slots=True, kw_only=True)
class PromotionCandidate:
    """One repeated pin, as the weekly session asks about it.

    ``weeks`` is every ISO week the group spans, in order, so the question can say "three
    consecutive weeks" from the data rather than from the threshold it passed.

    ``ref`` is the group the rule grouped on, which is also how a request addresses this candidate.
    One value rather than four fields beside a way of rendering them: the group key and the
    identifier are the same fact, and two spellings of it are how an accept comes to act on a
    pattern a decline did not silence.
    """

    ref: PromotionRef
    weeks: tuple[IsoWeek, ...]

    @property
    def consecutive_weeks(self) -> int:
        """How many weeks this group runs for."""
        return len(self.weeks)


def detect_repeated_pins(
    pins: Sequence[PinPlacement],
    consecutive_weeks: int = CONSECUTIVE_WEEKS_FOR_PROMOTION,
) -> list[PromotionCandidate]:
    """Every group of pins on one content at one local time that spans consecutive ISO weeks.

    Consecutive is checked against the week's own successor rather than by counting distinct weeks:
    a user who pinned Gym to 13:00 in weeks 1, 5 and 9 has a habit of pinning, not a structural
    pattern, and a count of three would raise a template change from three unrelated weeks.

    The longest run is what a group reports. A group spanning five consecutive weeks is one
    candidate of five weeks rather than three of three, because the question is about the pattern
    and asking it three times is the nag the product's severity discipline forbids.
    """
    if consecutive_weeks < 2:
        raise DomainError(
            f"a run of {consecutive_weeks} weeks is not a repetition: a candidate says the user "
            "did the same thing in consecutive weeks, which takes at least two of them"
        )
    grouped: dict[PromotionRef, set[IsoWeek]] = {}
    for pin in pins:
        grouped.setdefault(_group_of(pin), set()).add(pin.iso_week)
    candidates = [
        PromotionCandidate(ref=ref, weeks=run)
        for ref, weeks in grouped.items()
        if (run := longest_consecutive_run(weeks)) and len(run) >= consecutive_weeks
    ]
    return sorted(candidates, key=lambda one: (-one.consecutive_weeks, one.ref.local_time))


def _group_of(pin: PinPlacement) -> PromotionRef:
    """The identity a pin is grouped under: the content, the weekday, and the minute of the day.

    The split index is dropped for the reason the occurrence key is: which chunk of a divided task
    got pinned is a fact about one week's division, and the structural claim is about the content.
    """
    local = pin.starts_at.astimezone(resolve_zone(pin.zone))
    return PromotionRef(
        kind=pin.binding.kind,
        entity_id=pin.binding.entity_id,
        weekday=local.isoweekday(),
        minute_of_day=local.hour * MINUTES_PER_HOUR + local.minute,
    )
