"""The allocation rules: what an Area's own budget allows a candidate to take.

H8 and H9, and the two are opposite readings of one budget. H8 is a ceiling on one Area for one
day, so it refuses a candidate that would take too much of its own Area. H9 is a floor across every
Area, so it refuses a candidate that would take time some other Area still needs. Both are hard:
a cap comes from an Area preference and no override may relax it, and a floor is breached only
through an approved concession, never by the solver on its own.

## Neither judges a placement the solver cannot move

A rule that judges a CHOICE has nothing to say about a placement nothing can move: refusing a past
block, a pin, or a block fixed by derivation at its own span would drop a block the week already
holds rather than correct anything, and it would do so one rule before H10 and H11 could say the
placement is the one being preserved. Step 1 of the algorithm lists exactly those as the space
rather than as candidates inside it. So both rules pass over a candidate the state holds immovably
at its own span, which is a wider exception than the occupancy rules take, and deliberately: a
derived buffer colliding with another derived buffer IS a refusal a derivation has to make.

## Both measure over what the state holds, and the caller states that

A candidate's own Area minutes are not on the inputs: ``AreaBudget`` carries a whole-week figure,
and charging a whole-week figure against a per-day capacity is the arithmetic these rules exist to
avoid. So each figure here is measured over the placements the state holds, and a caller that seeds
none is asking about a week that holds none.

## A day is the day the user had

A cap is per local day, and a local day is 23 hours across a spring-forward date, 25 across a
fall-back one, and shorter still across a travel boundary. So the minutes are measured against
:func:`~syncr_domain.weeks.local_days` rather than against a 24-hour slice, and a candidate that
crosses local midnight is charged to each date it reaches, in that date's own share.

## The two sets H9 nets, and why they differ

``free`` counts every placement, because occupied time is occupied whether the solver may move it
or not. ``owed`` nets only the placements the Area's floor figure has NOT already netted, which is
every placement except one that has started and a pin: the assembler subtracted exactly those from
``floor_minutes`` before it arrived, so counting them again would let the solver place a floor short
by whatever the previous solve had already done.

``free`` is a union of time and ``owed`` is a sum across Areas, and that asymmetry is deliberate:
one free minute can serve one Area, and two Areas each owing an hour owe two hours between them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from syncr_domain.intervals import IntervalSet
from syncr_solver.constraints import Blocked, ConstraintRule

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from syncr_domain.identifiers import AreaId
    from syncr_solver.constraints import Rule
    from syncr_solver.inputs import AreaBudget
    from syncr_solver.state import PartialPlan, Placement


def area_daily_cap(candidate: Placement, state: PartialPlan) -> Blocked | None:
    """H8. An Area's minutes on one local date never pass the cap that Area declares.

    Only the dates the candidate reaches are measured. A date it does not touch cannot be pushed
    past its cap by placing it, so reporting one would name a rejection this candidate did not
    cause.
    """
    if state.holds_immovably(candidate):
        return None
    area = _budget_of(state.areas, candidate.area_id)
    if area is None or area.max_per_day_minutes is None:
        return None
    claimed = _spans(state.placed, area_id=area.area_id, including=candidate)
    for day in state.days:
        if not day.interval.overlaps(candidate.interval):
            continue
        minutes = claimed.clip(day.interval).total_minutes()
        if minutes > area.max_per_day_minutes:
            return Blocked(
                ConstraintRule.AREA_DAILY_CAP,
                candidate.interval,
                f"{area.name}, {minutes}m against a {area.max_per_day_minutes}m cap on {day.on}",
            )
    return None


def area_floor(candidate: Placement, state: PartialPlan) -> Blocked | None:
    """H9. A candidate never takes the last of the time another Area's floor still needs.

    The comparison is a whole-week one, because a floor is a weekly quantity and the time that can
    satisfy it is anywhere in the week. It over-credits in one direction and does so deliberately:
    free time inside a window that forbids the Area owing the floor is counted as usable here, so
    this rule refuses fewer candidates than the capacity check the verdict is taken from. A hard
    constraint that may not prove feasibility can only safely err that way.
    """
    if candidate.area_id is None or state.holds_immovably(candidate):
        return None
    free = state.discretionary().subtract(_spans(state.placed, including=candidate))
    owing = [(area, owed) for area in state.areas if (owed := _owed(area, state, candidate)) > 0]
    total = sum(owed for _, owed in owing)
    if not owing or total <= free.total_minutes():
        return None
    # The largest shortfall names the rejection, which is the axis the solver's own tie-breaking
    # orders candidates by. `max` keeps the first of equal ones and the Areas are in identity
    # order, so a tie is broken the same way twice.
    area, owed = max(owing, key=lambda pair: pair[1])
    return Blocked(
        ConstraintRule.AREA_FLOOR,
        candidate.interval,
        f"{area.name} still owes {owed}m of its floor, and {free.total_minutes()}m is free",
    )


def _owed(area: AreaBudget, state: PartialPlan, candidate: Placement) -> int:
    """Minutes of this Area's floor that would still be unplaced once ``candidate`` is placed.

    Netted against the placements the floor figure has not already accounted for, which is every
    placement except one that has started and a pin. That is the same set the assembler subtracted
    when it computed ``floor_minutes``, so the two readings cannot count one minute twice. The
    candidate is filtered on the same rule as the rest: a past block offered somewhere ELSE reaches
    this rule, because H10 refuses it one row later, and its minutes are already in the figure.
    """
    placed = _spans(
        [item for item in (*state.placed, candidate) if not _already_netted(item, state)],
        area_id=area.area_id,
    )
    return max(0, area.floor_minutes - placed.total_minutes())


def _already_netted(placement: Placement, state: PartialPlan) -> bool:
    """Whether the Area figures arrived with this placement's minutes already subtracted."""
    return placement.binding in state.started or placement.binding in state.pins


def _budget_of(areas: Sequence[AreaBudget], area_id: AreaId | None) -> AreaBudget | None:
    """This Area's figures for the week, or nothing because there are none to read.

    A candidate carrying no Area is the frame or an imported commitment, and neither competes for
    an Area's budget. An Area the inputs declare no budget for has no cap and no floor to state, so
    there is nothing for either rule to compare against.
    """
    if area_id is None:
        return None
    return next((area for area in areas if area.area_id == area_id), None)


def _spans(
    placements: Iterable[Placement],
    *,
    area_id: AreaId | None = None,
    including: Placement | None = None,
) -> IntervalSet:
    """The time these placements cover, unioned, optionally narrowed to one Area.

    Unioned rather than summed, so a minute claimed twice is claimed once. That is what keeps a
    user-authored overlap inside one Area from reading as twice the time: two blocks over one hour
    occupy one hour of the day, and an Area's floor may not be satisfied by time that does not
    exist. The solver's own placements never overlap, because H4 forbids it, so the two readings
    differ only where the user has already overlapped something by hand.
    """
    offered = () if including is None else (including,)
    return IntervalSet(
        placement.interval
        for placement in (*placements, *offered)
        if placement.area_id is not None and area_id in (None, placement.area_id)
    )


ALLOCATION_RULES: Final[tuple[Rule, ...]] = (area_daily_cap, area_floor)
