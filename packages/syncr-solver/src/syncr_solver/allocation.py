"""The allocation rules: what an Area's own budget allows a candidate to take.

H8 and H9, and the two are opposite readings of one budget. H8 is a ceiling on one Area for one
day, so it refuses a candidate that would take too much of its own Area. H9 is a floor across every
Area, so it refuses a candidate that would take time some other Area still needs. Both are hard:
a cap comes from an Area preference and no override may relax it, and a floor is breached only
through an approved concession, never by the solver on its own.

## Neither judges content the solver cannot place freely

A rule that judges a CHOICE has nothing to say about content the week already holds. At the span
that holds it, refusing would drop a block the week has rather than correct anything. At any OTHER
span the refusal belongs to H10 or H11: both sit BELOW these two in the table, so a budget clause
here is what the user reads about a block that cannot move at all. Neither is a placement defect,
and the second is a clause defect on a path reachable today. Step 1 of the algorithm lists exactly
this content as the space rather than as candidates inside it.

So both rules pass over a candidate whose binding the state holds, wherever it holds it. That is a
wider exception than the occupancy rules take, and deliberately: a derived buffer colliding with
another derived buffer IS a refusal a derivation has to make.

**So the invariant a finished plan holds is narrower than either rule's name.** No date is over an
Area's cap and no satisfiable floor is left unsatisfied *among the placements the solver chose*: a
pin can put a date over its cap and the plan keeps it, because refusing it would drop the user's own
placement.

## Neither refuses a candidate for a state the week arrived in

H9 protects a floor that can still be met. A floor the week cannot meet is a shortfall the verdict
reports and an approved concession excuses, and refusing content over it would leave an infeasible
week with nothing in it: infeasibility is a notice rather than a failure, so the product raises,
warns, and allows. Measured the other way round, the absolute reading refused even the candidate of
the Area that owes the floor, and named that Area's own shortfall as the reason.

So the comparison is against the state BEFORE the candidate, and what H9 forbids is the placement
that makes a reachable floor unreachable. The objective's budget term is what still pulls work into
an under-filled Area; a hard rule that emptied the week would not.

**The gate is one aggregate figure, so a week that arrives short is not protected at all, for any
Area.** The floors are summed and the time is unioned into a single shortfall, so a twenty-minute
deficit in one Area opens the gate for every other Area's individually satisfiable floor as well:
measured, a week arriving twenty minutes short can end two hundred and thirty short. That is the
over-crediting direction rather than the unsafe one, and it is a consequence of the aggregate
reading rather than of the gate. The answer is a per-Area reservation, where each Area's own claim
is held rather than one summed deficit, and that is a construction decision rather than a rule:
ticket 1334 carries it against ticket 37.

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

## What H9 over-credits, which is the safe direction

Two things. Free time inside a window that forbids the Area owing the floor is counted as usable
here, so this rule refuses fewer candidates than the capacity check the verdict is taken from. And
a placement carrying NO Area occupies claimable time that ``free`` still counts as available,
because ``_spans`` reads only the placements an Area claims. The oracle in the suite shares that
second blind spot by design, since it nets the same way, so no property can see it: it is recorded
here because a blind spot an instrument shares is the one thing this file's reasoning cannot catch.

A hard constraint that may not prove feasibility can only safely err in that direction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_domain.intervals import IntervalSet
from syncr_solver.constraints import Blocked, ConstraintRule

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from syncr_domain.identifiers import AreaId
    from syncr_domain.intervals import Interval
    from syncr_solver.inputs import AreaBudget
    from syncr_solver.state import PartialPlan, Placement

# One Area's unmet floor: the budget it belongs to, and the minutes still to place in it.
type Unmet = tuple[AreaBudget, int]


def area_daily_cap(candidate: Placement, state: PartialPlan) -> Blocked | None:
    """H8. An Area's minutes on one local date never pass the cap that Area declares.

    Only the dates the candidate reaches are measured. A date it does not touch cannot be pushed
    past its cap by placing it, so reporting one would name a rejection this candidate did not
    cause.
    """
    if state.holds(candidate):
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
    """H9. A candidate never makes a floor the week could still meet unmeetable.

    A whole-week comparison, because a floor is a weekly quantity and the time that can satisfy it
    is anywhere in the week. Twice over: once for the state as it stands, and once with the
    candidate placed. A week already short of its floors stays short whatever is placed, so the
    candidate is not what did it and refusing it would empty the week.

    The claimable set is read once and passed to both readings. It is a fact about the space rather
    than about the placements, so it does not change between them.

    **The two readings are taken over the same set of placements, read once.** The netting filter
    and the per-Area union are what cost, and neither depends on which reading is being taken: the
    second differs only by holding one more placement, and that is expressed as the placement
    joining a set rather than as a figure adjusted by a delta. The distinction is the one every
    netting defect in this module has turned on, and it is preserved: nothing here subtracts a
    minute count from a minute count.

    Measured, because ticket 33 handed the cost to this ticket's budget: on a 152-block week the
    rule cost 2.06 ms per candidate and 2.2 s of a 2.5 s solve, reading the placements six times a
    call.
    """
    if candidate.area_id is None or state.holds(candidate):
        return None
    reading = _Reading.of(state)
    if _shortfall(reading, offered=None) > 0:
        return None
    owing = _unmet(reading, offered=candidate)
    free = _free(reading, offered=candidate)
    shortfall = sum(owed for _, owed in owing) - free
    if shortfall <= 0:
        return None
    # The largest unmet floor names the rejection, which is the axis the solver's own tie-breaking
    # orders candidates by. `max` keeps the first of equal ones and the Areas are in identity
    # order, so a tie is broken the same way twice.
    area, owed = max(owing, key=lambda pair: pair[1])
    return Blocked(
        ConstraintRule.AREA_FLOOR,
        candidate.interval,
        f"{area.name} would be left {owed}m short of its floor, with {free}m free",
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class _Reading:
    """One reading of the placements both of H9's comparisons are taken over.

    Three sets, each read once per candidate rather than once per Area per comparison: the claimable
    space, the time every placement covers, and the time the placements the Area figures have NOT
    already netted cover, per Area.

    The netting is applied here and nowhere else in this rule, so the set the assembler subtracted
    before ``floor_minutes`` arrived has one statement, read through the checker's own answer to
    which placements those are.

    **The per-Area split is a bucketing rather than a re-read.** Each placement is examined once and
    dropped into the bucket of the Area that claims it, so the cost of the reading does not grow
    with the number of Areas the week declares.
    """

    claimable: IntervalSet
    claimed: IntervalSet
    owed_spans: Mapping[AreaId, IntervalSet]
    areas: tuple[AreaBudget, ...]

    @classmethod
    def of(cls, state: PartialPlan) -> _Reading:
        owed: dict[AreaId, list[Interval]] = {area.area_id: [] for area in state.areas}
        for held in state.placed:
            if held.area_id is None or state.already_netted(held.binding):
                continue
            if (spans := owed.get(held.area_id)) is not None:
                spans.append(held.interval)
        return cls(
            claimable=state.discretionary(),
            claimed=_spans(state.placed),
            owed_spans={area_id: IntervalSet(spans) for area_id, spans in owed.items()},
            areas=state.areas,
        )

    def owed_in(self, area_id: AreaId, offered: Placement | None) -> IntervalSet:
        """This Area's netted placements, with ``offered`` among them where it belongs to the Area.

        A set joining a set rather than a figure adjusted by a delta. The offered candidate is never
        one the figures already netted: a candidate whose binding has started or is pinned never
        reaches this rule, because :meth:`PartialPlan.holds` covers both.
        """
        held = self.owed_spans[area_id]
        if offered is None or offered.area_id != area_id:
            return held
        return held.union(IntervalSet([offered.interval]))


def _shortfall(reading: _Reading, *, offered: Placement | None) -> int:
    """How far the Areas' unmet floors exceed the claimable time left for them. Negative is slack.

    One figure over two sets that count different things, which is the asymmetry the module
    docstring states: the floors are summed across Areas because each needs its own minutes, and
    the time is unioned because one free minute serves one Area.
    """
    owing = _unmet(reading, offered=offered)
    return sum(owed for _, owed in owing) - _free(reading, offered=offered)


def _free(reading: _Reading, *, offered: Placement | None) -> int:
    """Minutes of claimable time no Area's placement covers, counting ``offered`` as placed."""
    claimed = reading.claimed
    if offered is not None and offered.area_id is not None:
        claimed = claimed.union(IntervalSet([offered.interval]))
    return reading.claimable.subtract(claimed).total_minutes()


def _unmet(reading: _Reading, *, offered: Placement | None) -> tuple[Unmet, ...]:
    """Each Area that would still owe minutes of its floor, and how many, in identity order."""
    return tuple(
        (area, owed)
        for area in reading.areas
        if (owed := _owed(area, reading, offered=offered)) > 0
    )


def _owed(area: AreaBudget, reading: _Reading, *, offered: Placement | None) -> int:
    """Minutes of this Area's floor that would still be unplaced once ``offered`` is placed.

    Netted through :meth:`~syncr_solver.state.PartialPlan.already_netted`, which the reading applied
    once: it is the one statement of the set the assembler subtracted before ``floor_minutes``
    arrived.
    """
    return max(0, area.floor_minutes - reading.owed_in(area.area_id, offered).total_minutes())


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
