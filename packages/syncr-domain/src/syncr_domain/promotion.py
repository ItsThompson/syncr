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
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from syncr_domain.budgets import MINUTES_PER_HOUR
from syncr_domain.errors import DomainError
from syncr_domain.weeks import longest_consecutive_run
from syncr_domain.zones import resolve_zone

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from syncr_domain.identity import BindingKind, BindingRef
    from syncr_domain.intervals import Instant
    from syncr_domain.weeks import IsoWeek
    from syncr_domain.zones import ZoneId

CONSECUTIVE_WEEKS_FOR_PROMOTION: Final = 3
"""How many consecutive ISO weeks of one pin make a template promotion candidate."""


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
        hour, minute = divmod(self.minute_of_day, MINUTES_PER_HOUR)
        return f"{hour:02d}:{minute:02d}"


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
        if (run := longest_consecutive_run(weeks)) and len(run) >= consecutive_weeks
    ]
    return sorted(candidates, key=lambda one: (-one.consecutive_weeks, one.local_time))


def _group_of(pin: PinPlacement) -> tuple[BindingKind, UUID, int, int]:
    """The identity a pin is grouped under: the content, the weekday, and the minute of the day.

    The split index is dropped for the reason the occurrence key is: which chunk of a divided task
    got pinned is a fact about one week's division, and the structural claim is about the content.
    """
    local = pin.starts_at.astimezone(resolve_zone(pin.zone))
    return (
        pin.binding.kind,
        pin.binding.entity_id,
        local.isoweekday(),
        local.hour * MINUTES_PER_HOUR + local.minute,
    )
