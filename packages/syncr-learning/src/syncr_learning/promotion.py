"""``detect_repeated_pins``: the structural pattern that goes to the template, not to a weight.

The learner absorbs statistical patterns. **Templates absorb structural ones.** Pinning the same
content to the same local time three weeks running is structural, so it is raised as a template
promotion rather than fitted into a number.

## Grouping drops ``occurrence_key``, and that is what makes it work at all

A pin's binding names the content, which occurrence of it, and which chunk of a split task. The
occurrence key is scoped to its own week -- an index in expansion order, or a date -- so two pins of
the same habit in two weeks never share one. Grouping on the whole binding would therefore find a
group of size one every time, whatever the user did.

So the group is ``(kind, entity, local time)``. It works across weeks because the key that is
week-scoped is dropped, and across occurrences because a second gym session on the same weekday at
the same hour is the same structural claim as the first.

**This is one query over pin rows**, which is why pins are first-class rows rather than fields
inside a revision document: a group spanning three weeks is a scan, and it would otherwise be three
document reads and a walk.

## It is raised, never applied

syncr observes and proposes; the user decides. The candidate names the binding, the time and the
week count, and it goes to the weekly session as a question.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_domain.zones import resolve_zone
from syncr_learning.config import CONSECUTIVE_WEEKS_FOR_PROMOTION, ConfigError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from syncr_domain.identity import BindingKind
    from syncr_domain.weeks import IsoWeek
    from syncr_learning.facts import HeldPin


@dataclass(frozen=True, slots=True, kw_only=True)
class PromotionCandidate:
    """One repeated pin, as the weekly session asks about it.

    ``weeks`` is every ISO week the group spans, in order, so the question can say "three
    consecutive weeks" from the data rather than from the threshold it passed.
    """

    kind: BindingKind
    entity_id: UUID
    weekday: int
    minute_of_day: int
    weeks: tuple[IsoWeek, ...]

    @property
    def consecutive_weeks(self) -> int:
        """How many weeks this group runs for."""
        return len(self.weeks)

    @property
    def local_time(self) -> str:
        """The wall time this content keeps being pinned to, as the template would declare it."""
        return f"{self.minute_of_day // 60:02d}:{self.minute_of_day % 60:02d}"


def detect_repeated_pins(
    pins: Sequence[HeldPin],
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
        raise ConfigError(
            f"a run of {consecutive_weeks} weeks is not a repetition: a candidate says the user "
            "did the same thing in consecutive weeks, which takes at least two of them"
        )
    grouped: dict[tuple[BindingKind, UUID, int, int], set[IsoWeek]] = {}
    for pin in pins:
        grouped.setdefault(_group_of(pin), set()).add(pin.iso_week)
    candidates = [
        PromotionCandidate(
            kind=kind,
            entity_id=entity_id,
            weekday=weekday,
            minute_of_day=minute_of_day,
            weeks=run,
        )
        for (kind, entity_id, weekday, minute_of_day), weeks in grouped.items()
        if (run := _longest_run(weeks)) and len(run) >= consecutive_weeks
    ]
    return sorted(candidates, key=lambda one: (-one.consecutive_weeks, one.local_time))


def _group_of(pin: HeldPin) -> tuple[BindingKind, UUID, int, int]:
    """The identity a pin is grouped under: the content, the weekday, and the minute of the day.

    The split index is dropped for the reason the occurrence key is: which chunk of a divided task
    got pinned is a fact about one week's division, and the structural claim is about the content.
    """
    local = pin.starts_at.astimezone(resolve_zone(pin.zone))
    return (
        pin.binding.kind,
        pin.binding.entity_id,
        local.isoweekday(),
        local.hour * 60 + local.minute,
    )


def _longest_run(weeks: set[IsoWeek]) -> tuple[IsoWeek, ...]:
    """The longest run of consecutive ISO weeks in this group, earliest run winning a tie."""
    longest: tuple[IsoWeek, ...] = ()
    current: list[IsoWeek] = []
    for week in sorted(weeks):
        if current and current[-1].following() != week:
            current = []
        current.append(week)
        if len(current) > len(longest):
            longest = tuple(current)
    return longest
