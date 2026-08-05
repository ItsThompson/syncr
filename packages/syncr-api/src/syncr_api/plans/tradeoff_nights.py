"""Which nights a routine reduction touches, and how much each of them gives up.

The one tradeoff whose target is not enough to say what the concession is. Dropping a task names a
task and breaching a floor names an Area, but shortening a routine has to name the nights, because
each night is a distinct occurrence with its own identity and its own reduction. So this is where
the distribution is chosen, and the concession stores the result rather than a rule for re-deriving
it: re-derived later against inputs that have moved, a concession could silently shorten different
nights from the ones the user approved.

Two rules decide which nights are eligible, and each removes a night whose reduction would recover
nothing.

*A night that has already begun.* A reduction moves an occurrence's END, so part of what an
occurrence under way would hand back sits behind ``now``, where capacity does not start yet. The
whole occurrence has to be ahead of ``now``.

*A night after the deadline a gap was measured against.* Time handed back on Friday cannot be spent
on work due Thursday morning.

The distribution itself is even, over the fewest nights that can supply the gap. Both halves are
the product's own wording: "reduce sleep by 1h across three nights" states one figure per night, and
a night the concession does not need is a night the user keeps whole.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import TYPE_CHECKING

from syncr_domain.identity import date_occurrence_key

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from uuid import UUID

    from syncr_domain.intervals import Instant
    from syncr_domain.zones import Date
    from syncr_solver.inputs import FrameEntry, SolveInputs


@dataclass(frozen=True, slots=True, kw_only=True)
class Distribution:
    """What one routine would give up, per night, and how much that recovers in total."""

    each: int
    reductions: Mapping[Date, int]

    @property
    def recovers(self) -> int:
        """The sum of the reductions, which is what this concession hands back to the week."""
        return sum(self.reductions.values())


def by_routine(frame: Sequence[FrameEntry]) -> dict[UUID, list[FrameEntry]]:
    """Each routine's occurrences, in the order the assembly resolved them."""
    grouped: dict[UUID, list[FrameEntry]] = {}
    for entry in frame:
        grouped.setdefault(entry.routine_id, []).append(entry)
    return grouped


def reducible(
    occurrences: Sequence[FrameEntry], *, after: Instant, before: Instant | None
) -> tuple[FrameEntry, ...]:
    """The occurrences a reduction could shorten into capacity a gap can use, earliest first."""
    return tuple(
        sorted(
            (
                entry
                for entry in occurrences
                if entry.interval.start >= after
                and (before is None or entry.interval.end <= before)
            ),
            key=lambda entry: entry.interval.start,
        )
    )


def distributed(
    gap: int, *, over: Sequence[FrameEntry], dates: Mapping[str, Date]
) -> Distribution | None:
    """``gap`` spread evenly over the fewest of ``over`` that can supply it, or nothing to offer.

    ``None`` where there is no give: a routine whose minimum equals its target has nothing to
    concede, which by default is every one of them. That is the elastic-sleep rule, and it is why
    the solver may propose spending the floor the user set and may never spend it silently.

    The figure per night is bounded by the SMALLEST give among the nights used, so every night can
    supply the same amount. Where the nights together cannot reach the gap they are all used at
    their full give and the concession recovers less than the gap: the user reads the figure and
    sees that this one does not close it.
    """
    give = min((_give(night) for night in over), default=0)
    if give <= 0:
        return None
    nights = min(len(over), ceil(gap / give))
    each = min(give, ceil(gap / nights))
    return Distribution(
        each=each, reductions={dates[night.occurrence_key]: each for night in over[:nights]}
    )


def dates_of(inputs: SolveInputs) -> dict[str, Date]:
    """This week's dates, by the occurrence key a frame entry carries.

    Built from the week rather than by parsing the key, which is what makes WA7's first half
    structural: every date a reduction names is a date of the week being assembled, because there
    is no other source for one.
    """
    return {date_occurrence_key(on): on for on in inputs.iso_week.dates()}


def _give(entry: FrameEntry) -> int:
    """How much one occurrence could be shortened by, which is what R6's clamp leaves."""
    return entry.interval.total_minutes() - entry.min_duration_minutes
