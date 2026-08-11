"""The feature snapshot one edit is recorded with, derived from the assembly and the two documents.

Pure, and it is the only place an ``EditContext`` is built. Every field is derived from something
the week already states, so nothing here reads a clock, performs a lookup, or invents a figure.

## Two rules govern every span on the record, and both come from ``E3``

**Signed offsets from the accepted placement's start.** An event has to stay meaningful without
reconstructing the week it came from, so a neighbouring anchor two hours earlier reads as ``-120``
whatever week and whatever zone it was in.

**The day is the bound, and both gaps are clamped at zero.** The two gap figures are measured
inside the accepted placement's own local day, clamped so a placement overhanging the day's end
writes 0 rather than a negative. Both figures are non-negative by construction. The day the
fragmentation term reasons over is the same one.

## Which day, and why the domain answers it

The local date an instant falls on is not the UTC date and is not a 24-hour slice: a spring-forward
date is 23 hours long and a travel boundary makes one 14 hours long.
``syncr_domain.weeks.local_days`` already answers "which span does each of this week's dates really
occupy", so the day holding the accepted placement is a lookup over that rather than a second
derivation here."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.plans.edit_context import NEAREST, REJECTED_WINDOWS, EditContext, RejectedWindow
from syncr_domain.reasons import Blocked
from syncr_domain.weeks import local_days

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from syncr_domain.identifiers import AreaId
    from syncr_domain.intervals import Instant, Interval
    from syncr_domain.plan import Block, PlanDocument
    from syncr_domain.weeks import LocalDay
    from syncr_solver.inputs import AreaBudget, SolveInputs
    from syncr_solver.objective import ObjectiveBreakdown

# Minutes in one minute, as the divisor a signed offset is taken with. Named because
# `int(delta.total_seconds() // 60)` appears four times and the intent is the unit, not the maths.
_SECONDS_A_MINUTE = 60


class NoSuchLocalDay(Exception):
    """A placement that falls on none of the week's own days, so no context could describe it.

    Raised rather than tolerated. Every field of the temporal group is resolved against the day the
    placement falls on, and a placement outside the week has no such day: the pin route refuses one
    before it reaches here, so this is the second reading of that rule rather than the only one.
    """


def edit_context(
    *,
    inputs: SolveInputs,
    document: PlanDocument,
    block: Block,
    accepted: Interval,
    breakdown: ObjectiveBreakdown,
    measurement_delta: Mapping[str, float],
    task_deadline: Instant | None,
    area_floor_declared: int | None,
    pinned_blocks_before: int,
) -> EditContext:
    """The state this edit was made in, as the row that outlives it will carry it.

    Two sources, deliberately separated, and no field may read from the wrong one.

    **Pre-edit (the state the proposal was made in):** ``document``, ``breakdown``,
    ``measurement_delta``, ``task_deadline``, ``area_floor_declared``, ``pinned_blocks_before``.
    Each describes the moment before the user acted, which is the circumstance the preference was
    expressed inside. Four arrive as parameters the caller resolved from an entity or a document;
    ``breakdown`` and ``measurement_delta`` it measures in the same pre-pin assembly it passes here
    as ``inputs``.

    **Post-edit (the accepted placement and the week around it):** ``inputs``. This supplies the
    local day and its zone, the Area's placed and target minutes, the anchor and forbidden-window
    offsets, and whether the placement falls inside an off-plan period.

    **Both groups, where they read a frame at all, read one the pin has not entered**, because
    ``inputs`` is the PRE-pin assembly: the caller prices the edit in it, writes the pin row after
    it, and computes the verdict in a second assembly this function never sees. So no field here can
    carry a reading taken after the pin, and a "proposal time" field cannot read one either.
    """
    days = local_days(inputs.iso_week, inputs.zone_by_date, inputs.span)
    day = _day_holding(accepted.start, days)
    neighbours = _neighbours(document, block, accepted=accepted, day=day)
    area = _budget_for(block.area_id, inputs.areas)
    return EditContext(
        weekday=day.on.isoweekday(),
        accepted_start_minute_of_day=_minutes_between(day.interval.start, accepted.start),
        proposed_start_minute_of_day=_minute_of_day(block.interval.start, days),
        duration_minutes=accepted.total_minutes(),
        zone=inputs.zone_by_date[day.on],
        objective_breakdown=breakdown.costs(),
        measurement_delta=measurement_delta,
        discretionary_minutes=document.discretionary_minutes,
        unallocated_minutes=document.unallocated_minutes,
        blocks_in_day=sum(1 for one in document.blocks if day.interval.overlaps(one.interval)),
        pinned_blocks_in_week=pinned_blocks_before,
        area_id=block.area_id,
        area_floor_minutes=area_floor_declared,
        area_placed_minutes=0 if area is None else area.placed_minutes,
        area_target_minutes=0 if area is None else area.target_minutes,
        gap_before_minutes=neighbours.gap_before_minutes,
        gap_after_minutes=neighbours.gap_after_minutes,
        adjacent_area_before=neighbours.area_before,
        adjacent_area_after=neighbours.area_after,
        anchor_offsets_minutes=_offsets(
            (one.interval for one in inputs.anchors), from_=accepted.start
        ),
        forbidden_offsets_minutes=_offsets(
            (one.interval for one in inputs.forbidden_windows), from_=accepted.start
        ),
        rejected_windows=_rejected(block, from_=accepted.start),
        was_deadline_constrained=task_deadline is not None,
        days_until_deadline=_days_until(task_deadline, accepted.start),
        inside_off_plan=any(period.interval.overlaps(accepted) for period in inputs.off_plan),
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class _Neighbours:
    """The blocks either side of the accepted placement inside its own day, and the gaps to them."""

    gap_before_minutes: int
    gap_after_minutes: int
    area_before: AreaId | None
    area_after: AreaId | None


def _neighbours(
    document: PlanDocument, block: Block, *, accepted: Interval, day: LocalDay
) -> _Neighbours:
    """What sits either side of the accepted placement, over the day's own blocks.

    The pinned block itself is excluded, because a block cannot be its own neighbour: with the pin
    applied it is where ``accepted`` says, so the plan's own placement of it is not in the week the
    edit produced. The two Areas are what the context-switch term reads, so the gaps are measured
    against the same pair rather than against occupancy of any other kind.
    """
    others = [
        one
        for one in document.blocks
        if one.binding != block.binding and day.interval.overlaps(one.interval)
    ]
    before = max(
        (one for one in others if one.interval.end <= accepted.start),
        key=lambda one: one.interval.end,
        default=None,
    )
    after = min(
        (one for one in others if one.interval.start >= accepted.end),
        key=lambda one: one.interval.start,
        default=None,
    )
    return _Neighbours(
        gap_before_minutes=max(
            0,
            _minutes_between(
                day.interval.start if before is None else before.interval.end, accepted.start
            ),
        ),
        gap_after_minutes=max(
            0,
            _minutes_between(
                accepted.end, day.interval.end if after is None else after.interval.start
            ),
        ),
        area_before=None if before is None else before.area_id,
        area_after=None if after is None else after.area_id,
    )


def _day_holding(moment: Instant, days: Sequence[LocalDay]) -> LocalDay:
    """The week's day this instant falls inside, or a refusal naming what it fell outside of."""
    found = next((day for day in days if day.interval.start <= moment < day.interval.end), None)
    if found is None:
        message = (
            f"{moment.isoformat()} falls on none of the week's own days, so no temporal context "
            "describes it: a pin binds one week and the route refuses one outside it"
        )
        raise NoSuchLocalDay(message)
    return found


def _minute_of_day(moment: Instant, days: Sequence[LocalDay]) -> int:
    """The minute of its own local day this instant falls on."""
    day = _day_holding(moment, days)
    return _minutes_between(day.interval.start, moment)


def _minutes_between(first: Instant, second: Instant) -> int:
    """Whole minutes from ``first`` to ``second``. Signed, so an offset reads either way."""
    return int((second - first).total_seconds() // _SECONDS_A_MINUTE)


def _offsets(intervals: Iterable[Interval], *, from_: Instant) -> tuple[int, ...]:
    """The nearest few starts as signed minute offsets, in time order.

    Nearest by absolute distance, so a placement between two anchors carries one from each side
    rather than three from whichever side has more; ordered by the offset afterwards, so two
    assemblies of one week produce one tuple.
    """
    offsets = (_minutes_between(from_, one.start) for one in intervals)
    return tuple(sorted(sorted(offsets, key=abs)[:NEAREST]))


def _rejected(block: Block, *, from_: Instant) -> tuple[RejectedWindow, ...]:
    """The windows the rules refused for this block, from the clauses the plan stored.

    The blocked_log itself belongs to the solve that produced the plan and is not persisted, but the
    clauses ARE: the reason record carries one ``blocked`` clause per refused window, already
    bounded per block by the clause budget. So the candidate context is read from the document
    rather than from a log this request has no access to, and it is bounded a second time here.
    """
    refusals = [one for one in block.reason.clauses if isinstance(one, Blocked)]
    return tuple(
        RejectedWindow(
            offset_minutes=_minutes_between(from_, one.window.start),
            duration_minutes=one.window.total_minutes(),
            rule=one.rule,
        )
        for one in refusals[:REJECTED_WINDOWS]
    )


def _budget_for(area_id: AreaId | None, areas: Sequence[AreaBudget]) -> AreaBudget | None:
    if area_id is None:
        return None
    return next((one for one in areas if one.area_id == area_id), None)


def _days_until(deadline: Instant | None, moment: Instant) -> int | None:
    """Whole days from the accepted placement to the deadline, or nothing when there is none.

    Signed and floored, so a deadline the placement already passed reads negative rather than as
    zero: a pin made after a deadline is a different circumstance from one made on the day.
    """
    if deadline is None:
        return None
    return (deadline - moment).days
