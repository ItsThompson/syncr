"""``EditContext``: the feature snapshot one edit is a training example inside.

The pair a fitter learns from is the edit event's own two intervals: the solver proposed one, the
user chose the other. This is the surrounding state that makes the pair a labeled EXAMPLE rather
than an unattributed preference, and it is deliberately narrow.

**Narrow, with the figure that decided it.** Embedding the week the edit happened in would cost
roughly 15 KB per edit and 12 MB per user-year, and almost none of it is a feature any fitter reads.
The fields below are the ones a fitter consumes, at roughly 1.5 KB per event.

**Flat, deliberately, and it is a feature vector rather than a document.** The five groups the
comments name are five derivations, but a fitter reads twenty numbers rather than five containers,
and nesting them would put a walk in front of every one. The inventory is asserted against section
11's own list instead, which is what keeps the flatness from hiding a missing field.

**``E3``: every span here is an OFFSET from the accepted placement, in signed minutes.** An event
has to stay meaningful without reconstructing the week it came from, and an absolute instant is only
meaningful beside the frame, the anchors and the zone profile of the day it fell on. That includes
the rejected windows, which section 11 types as intervals: a record whose other spans are relative
would leave that one field needing a zone nobody stored.

**``E4``: an edit inside an off-plan span is recorded and flagged here.** The flag is a field rather
than a column because it is one of this edit's circumstances alongside the rest, and every fitter
reads the context. Recorded rather than refused, because pinning inside an off-plan span is exactly
how "off, except this one thing" is expressed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from syncr_api.plans.errors import EditContextRejected
from syncr_solver.weights import OBJECTIVE_TERMS

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syncr_domain.identifiers import AreaId
    from syncr_domain.zones import ZoneId

# How many of each occupancy kind an event records around its placement. "The nearest few", bounded,
# because the point of an offset list is the immediate neighbourhood: a week's twentieth anchor is
# not context for a placement, and an unbounded list is what makes an event grow with the week.
NEAREST: Final = 3

# How many refused windows one event carries. The solver bounds its own log per binding, and a
# stored block's clauses are bounded again by the clause budget, so this is a third bound rather
# than the only one: what it stops is an event growing with a week's difficulty.
REJECTED_WINDOWS: Final = 5


@dataclass(frozen=True, slots=True, kw_only=True)
class RejectedWindow:
    """One window the solver refused for this content, relative to where the user put it.

    ``offset_minutes`` is signed and measured from the accepted placement's start, so a window the
    solver tried three hours earlier reads as ``-180`` whatever week it was in. ``rule`` is the
    hard-constraint rule that refused it, as the stored clause spells it.
    """

    offset_minutes: int
    duration_minutes: int
    rule: str

    def __post_init__(self) -> None:
        if self.duration_minutes <= 0:
            raise EditContextRejected(
                f"a refused window of {self.duration_minutes} minutes is not a window: the solver "
                "refuses a span it tried to place into, and a span of no length is not one"
            )
        if not self.rule.strip():
            raise EditContextRejected(
                "a refused window names the rule that refused it, because the rule is the feature: "
                "a window with no rule says only that something was in the way"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class EditContext:
    """The state one edit was made in. Twenty-four features, and every one is read by a fitter."""

    # Temporal context. The two minute-of-day figures are local to `zone`, which is the zone active
    # on the accepted placement's own date: a drag across a travel boundary is a drag inside the
    # zone the user was in, and a UTC minute of day would name a different hour of their day.
    weekday: int
    accepted_start_minute_of_day: int
    proposed_start_minute_of_day: int
    duration_minutes: int
    zone: ZoneId

    # Plan context. `objective_breakdown` carries all seven terms, which is what makes any refit of
    # the EXISTING objective fully supported from stored data: the pair alone would let a refit rank
    # two placements and not recover what either cost.
    objective_breakdown: Mapping[str, float]
    discretionary_minutes: int
    unallocated_minutes: int
    blocks_in_day: int
    pinned_blocks_in_week: int

    # Area context. All four are absent or zero for content carrying no Area, which is the frame and
    # a commitment: neither competes for discretionary time, so neither has a floor or a target.
    area_id: AreaId | None
    area_floor_minutes: int | None
    area_placed_minutes: int
    area_target_minutes: int

    # Occupancy near the accepted placement, as signed offsets from its start.
    gap_before_minutes: int
    gap_after_minutes: int
    adjacent_area_before: AreaId | None
    adjacent_area_after: AreaId | None
    anchor_offsets_minutes: tuple[int, ...] = ()
    forbidden_offsets_minutes: tuple[int, ...] = ()

    # Candidate context: what the solver tried for this content and could not use, and whether a
    # deadline was pressing when the user overrode it.
    rejected_windows: tuple[RejectedWindow, ...] = ()
    was_deadline_constrained: bool = False
    days_until_deadline: int | None = None

    # E4. True when the accepted placement falls inside a declared off-plan span, which excludes
    # this event from every fitter.
    inside_off_plan: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "objective_breakdown", dict(self.objective_breakdown))
        object.__setattr__(self, "anchor_offsets_minutes", tuple(self.anchor_offsets_minutes))
        object.__setattr__(self, "forbidden_offsets_minutes", tuple(self.forbidden_offsets_minutes))
        object.__setattr__(self, "rejected_windows", tuple(self.rejected_windows))
        _require_the_seven_terms(self.objective_breakdown)
        _require_a_placement_with_a_length(self.duration_minutes)
        _require_a_weekday(self.weekday)
        _require_bounded(self.anchor_offsets_minutes, "anchor_offsets_minutes", NEAREST)
        _require_bounded(self.forbidden_offsets_minutes, "forbidden_offsets_minutes", NEAREST)
        _require_bounded(self.rejected_windows, "rejected_windows", REJECTED_WINDOWS)
        _require_an_area_for_every_area_figure(self.area_id, self.area_floor_minutes)


def _require_the_seven_terms(breakdown: Mapping[str, float]) -> None:
    """The breakdown names the objective's own seven terms, no more and no fewer.

    The vocabulary is read from :data:`syncr_solver.weights.OBJECTIVE_TERMS` rather than restated,
    so a term added to the objective makes every event written afterwards refuse until it is
    carried. A refit of the existing objective reads all seven, and one silently missing is a
    corpus that cannot support the refit the snapshot exists for.
    """
    if set(breakdown) == set(OBJECTIVE_TERMS):
        return
    raise EditContextRejected(
        f"an edit event carries the objective's seven terms and this names {sorted(breakdown)}: "
        f"the terms are {', '.join(OBJECTIVE_TERMS)}, and a refit reads all of them"
    )


def _require_a_placement_with_a_length(duration_minutes: int) -> None:
    if duration_minutes <= 0:
        raise EditContextRejected(
            f"a placement of {duration_minutes} minutes is not one the user could have dragged: "
            "every interval in this product is half-open, so a block holds at least a minute"
        )


def _require_a_weekday(weekday: int) -> None:
    """An ISO weekday, Monday 1 to Sunday 7, which is what every date in this product reports."""
    if weekday not in range(1, 8):
        raise EditContextRejected(
            f"{weekday} is not an ISO weekday: Monday is 1 and Sunday is 7, and a fitter buckets "
            "by that numbering"
        )


def _require_bounded(held: Sequence[object], named: str, bound: int) -> None:
    """A bounded list stays bounded, so an event's size does not grow with its week's difficulty."""
    if len(held) <= bound:
        return
    raise EditContextRejected(
        f"{named} holds {len(held)} entries and is bounded at {bound}: the snapshot is a trimmed "
        "feature vector, and an unbounded list is what makes one grow into a plan document"
    )


def _require_an_area_for_every_area_figure(
    area_id: AreaId | None, area_floor_minutes: int | None
) -> None:
    """A floor belongs to an Area, so a figure without one names nothing that could hold it."""
    if area_id is None and area_floor_minutes is not None:
        raise EditContextRejected(
            "a floor figure with no Area names nothing: the frame and a commitment carry no Area, "
            "and neither competes for the discretionary time a floor reserves"
        )
