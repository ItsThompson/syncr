"""The probe's properties: the five monotonicity rules the product's honesty rests on.

Each of these is a rule about how the verdict may move when one thing about the week changes, and
each exists because the opposite direction was reachable at some point in this design:

- making progress must never manufacture a gap, so pinning work toward a demand leaves that
  demand's gap exactly where it was: both sides of the comparison fall by the same amount;
- pinning anything else cannot reduce that demand's gap, or the whole-week floor gap. It CAN close
  the floor gap of the Area it is pinned in, because work in an Area is progress toward that Area's
  floor, so non-improvement is a rule about one measurement rather than about every gap at once;
- not doing the work must never improve the verdict, so an outcome recorded on a past block
  cannot reduce a gap, and a past span cannot be returned to capacity at all;
- time passing must never improve the verdict, which is what makes a mid-week transition from
  feasible to infeasible computable;
- the verdict panel and the budget report must not disagree about one week, so the probe's
  denominator is the one the report takes;
- and a window scoped to named Areas must never be worth more to an Area than the same window
  scoped to every Area.

**The transformations model the assembler's netting**, because that is what these properties are
about: the probe has to be invariant under the arithmetic its producer performs. A pin lowers the
demand, lowers that Area's reservation, and adds to the committed time, all by the same minutes,
and the probe must not move. Stating the transformation here is what makes the invariance
observable from literals.

The two shared fixtures are consumed here: ``partial_progress`` seeds the net-arithmetic
properties with a real half-done task, and ``recovery_scopes`` supplies the one window declared
both ways for the scope property.
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta
from itertools import combinations
from typing import TYPE_CHECKING

from hypothesis import assume, given
from hypothesis import strategies as st

from syncr_domain.discretionary import discretionary_time
from syncr_domain.feasibility import (
    DeadlineDemand,
    FloorReservation,
    ProbeInputs,
    ScopedWindow,
    ShortfallKind,
    probe,
)
from syncr_domain.fixtures import partial_progress, recovery_scopes
from syncr_domain.intervals import Interval, IntervalSet
from tests.instants import MONDAY
from tests.interval_strategies import interval_sets, intervals

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syncr_domain.feasibility import Shortfall, Verdict
    from syncr_domain.identifiers import AreaId
    from syncr_domain.intervals import Instant

WEEK = Interval(MONDAY, MONDAY + timedelta(days=7))
WEEK_MINUTES = 7 * 24 * 60

FITNESS: AreaId = partial_progress.FITNESS
CAREER: AreaId = partial_progress.CAREER
NAMES = {FITNESS: "Fitness", CAREER: "Career"}

type Gaps = Mapping[tuple[str, str, str], int]


def gaps(verdict: Verdict) -> Gaps:
    """Every gap the verdict holds, keyed by what it is about rather than by its position.

    Keyed so two verdicts can be compared shortfall by shortfall: a rule that says "no gap falls"
    is about the gap for one Area or one deadline, and comparing tuples in order would compare a
    floor gap against a deadline gap as soon as one of them appeared.
    """
    return {_key(shortfall): shortfall.minutes for shortfall in verdict.shortfalls}


def _key(shortfall: Shortfall) -> tuple[str, str, str]:
    return (shortfall.kind.value, str(shortfall.area_id), str(shortfall.deadline))


def no_gap_fell(before: Verdict, after: Verdict) -> bool:
    """Whether every gap the first verdict holds is at least as large in the second.

    A gap that has gone entirely counts as zero, which is the direction that would be an
    improvement, so it fails the comparison rather than passing by absence.
    """
    later = gaps(after)
    return all(later.get(key, 0) >= minutes for key, minutes in gaps(before).items())


@st.composite
def weeks(
    draw: st.DrawFn,
    *,
    with_room_before_the_deadline: bool = False,
    demands: int = 2,
) -> ProbeInputs:
    """A week with occupancy, a floor in each of two Areas, a demand in each, and scoped windows.

    Every shape here is drawn because a property is stated over it, and two of them were added
    after a reviewer proved the generator could not reach the case the arithmetic got wrong:

    *Two demands in two Areas.* The accumulation across deadlines is what makes one demand's
    capacity depend on another's, and a generator with one demand cannot produce a competitor at
    all. The second demand's Area is the OTHER one, so the pair is always cross-Area.

    *Scoped windows naming the week's own Areas.* A window naming an Area nothing in the week holds
    is inert: it changes no figure, so a property injecting one asserts nothing. These name Career
    or Fitness, which are the Areas the floors and the demands carry.

    ``demands=1`` drops the competitor, for the one property that is an exact equality on a single
    demand's gap. With a competitor that property is about something else: capacity moving between
    two demands, which conserves the total rather than leaving one figure alone. The example that
    shows it lands beside the property.

    ``with_room_before_the_deadline`` places the first deadline at least ten hours after ``now``,
    for the properties that have to pin minutes into the capacity before it. Left false, a deadline
    lands anywhere in the week including behind ``now``, which is the overdue case every
    monotonicity rule must also hold over.
    """
    latest_now = WEEK_MINUTES - 1440 if with_room_before_the_deadline else WEEK_MINUTES
    now_minutes = draw(st.integers(min_value=0, max_value=latest_now))
    earliest_deadline = now_minutes + 600 if with_room_before_the_deadline else 1
    deadline_minutes = draw(st.integers(min_value=earliest_deadline, max_value=WEEK_MINUTES))
    now = MONDAY + timedelta(minutes=now_minutes)
    deadline = MONDAY + timedelta(minutes=deadline_minutes)
    measured = draw(st.sampled_from((CAREER, FITNESS)))
    competitor = FITNESS if measured == CAREER else CAREER
    competing = (
        DeadlineDemand(
            deadline=MONDAY
            + timedelta(minutes=draw(st.integers(min_value=1, max_value=WEEK_MINUTES))),
            remaining_minutes=draw(st.integers(min_value=0, max_value=1800)),
            area_id=competitor,
            labels=("Kim's Game Project",),
        ),
    )
    return ProbeInputs(
        span=WEEK,
        now=now,
        computed_at=now,
        input_version=draw(st.integers(min_value=0, max_value=99)),
        frame=draw(interval_sets(max_size=3)),
        anchors=draw(interval_sets(max_size=2)),
        absolute_forbidden=draw(interval_sets(max_size=2)),
        scoped_forbidden=draw(scoped_windows(measured, competitor)),
        off_plan=draw(interval_sets(max_size=1)),
        placed=draw(interval_sets(max_size=3)),
        area_floor_reservations=(
            FloorReservation(
                area_id=measured,
                reserved_minutes=draw(st.integers(min_value=0, max_value=600)),
                label=NAMES[measured],
            ),
            FloorReservation(
                area_id=competitor,
                reserved_minutes=draw(st.integers(min_value=0, max_value=600)),
                label=NAMES[competitor],
            ),
        ),
        deadline_demands=(
            DeadlineDemand(
                deadline=deadline,
                # Up to two and a half days of work, so a week whose capacity before the deadline
                # cannot hold it is an ordinary draw rather than a rare one: a property about how
                # a gap moves is worthless over inputs that mostly have no gap.
                remaining_minutes=draw(st.integers(min_value=1, max_value=3600)),
                area_id=measured,
                labels=("F&F Past Papers",),
            ),
            *(competing if demands > 1 else ()),
        ),
    )


@st.composite
def scoped_windows(draw: st.DrawFn, *areas: AreaId) -> tuple[ScopedWindow, ...]:
    """Up to two recovery windows, each forbidding one of the Areas the week actually holds.

    A window naming an Area no floor and no demand carries cannot change a figure, so a strategy
    that drew one would be generating inert inputs: every property over it would hold whatever the
    arithmetic did with a scope.
    """
    return tuple(
        ScopedWindow(interval=interval, forbidden_area_ids=(draw(st.sampled_from(areas)),))
        for interval in draw(st.lists(intervals(), max_size=2))
    )


def measured_demand(week: ProbeInputs) -> DeadlineDemand:
    """The demand every property here is stated about, which is the first one the week carries."""
    return week.deadline_demands[0]


def free_before(week: ProbeInputs, deadline: Instant) -> IntervalSet:
    """The capacity the measured demand's Area has before ``deadline``, as the probe derives it.

    Derived here to CHOOSE an interval to pin rather than to predict a figure: a property about
    invariance under pinning has to pin minutes the week really had, in capacity that Area may use.
    """
    occupied = week.frame.union(week.anchors).union(week.absolute_forbidden).union(week.off_plan)
    free = IntervalSet([week.span]).subtract(occupied).after(week.now).subtract(week.placed)
    return free.subtract(week.scoped_against(measured_demand(week).area_id)).before(deadline)


def a_window_to_pin_into(free: IntervalSet, minutes: int) -> Interval | None:
    """The earliest ``minutes`` of one member of a free set, or nothing if no member is that long.

    A pin is one block, so pinning half an hour needs half an hour of unbroken capacity rather than
    two quarters of it: free capacity totalling more than the pin is not the same as free capacity
    that can hold it. Returning nothing rather than raising is what lets the property state that
    precondition as an assumption instead of a failure.
    """
    for member in free:
        if member.total_minutes() >= minutes:
            return Interval(member.start, member.start + timedelta(minutes=minutes))
    return None


def pinning_toward(week: ProbeInputs, pinned: Interval) -> ProbeInputs:
    """The week after the user pins ``pinned`` minutes of the measured demand's own work.

    The assembler's three consequences, restated: the committed time gains the span, the demand
    falls by its minutes because they are now placed before the deadline, and that Area's floor
    reservation falls by them too because the block lands in it. All three come from one placement,
    which is why the probe must not move.
    """
    minutes = pinned.total_minutes()
    demand = measured_demand(week)
    return dataclasses.replace(
        week,
        placed=week.placed.union(IntervalSet([pinned])),
        deadline_demands=(
            dataclasses.replace(
                demand, remaining_minutes=max(0, demand.remaining_minutes - minutes)
            ),
            *week.deadline_demands[1:],
        ),
        area_floor_reservations=_lowering(week, demand.area_id, minutes),
    )


def pinning_elsewhere(
    week: ProbeInputs, pinned: Interval, *, toward_their_deadline: bool
) -> ProbeInputs:
    """The week after the user pins work no demand being measured here is waiting on.

    Work in the other Area, so the measured demand is untouched. What happens to the OTHER Area's
    two figures is the whole subject. Its floor reservation always falls, because the block lands
    in it, and its demand falls too when the block is that Area's own deadline-bearing work.
    Modelling only the floor half is what let a fault in the competitor arithmetic survive this
    property: the two figures are one set of minutes, so a transformation that moves one and not
    the other is not a pin the assembler can produce.
    """
    other = _competitor_of(week)
    minutes = pinned.total_minutes()
    demands = week.deadline_demands
    if toward_their_deadline:
        demands = tuple(
            dataclasses.replace(
                demand, remaining_minutes=max(0, demand.remaining_minutes - minutes)
            )
            if demand.area_id == other
            else demand
            for demand in demands
        )
    return dataclasses.replace(
        week,
        placed=week.placed.union(IntervalSet([pinned])),
        deadline_demands=demands,
        area_floor_reservations=_lowering(week, other, minutes),
    )


def _lowering(week: ProbeInputs, area_id: AreaId, minutes: int) -> tuple[FloorReservation, ...]:
    """The reservations with one Area's lowered by the minutes now placed in it, clamped."""
    return tuple(
        dataclasses.replace(
            reservation, reserved_minutes=max(0, reservation.reserved_minutes - minutes)
        )
        if reservation.area_id == area_id
        else reservation
        for reservation in week.area_floor_reservations
    )


def _competitor_of(week: ProbeInputs) -> AreaId:
    """The Area the measured demand competes with, which is the other one the week holds."""
    measured = measured_demand(week).area_id
    return FITNESS if measured == CAREER else CAREER


def deadline_gap(week: ProbeInputs) -> int:
    """The minutes the MEASURED demand is short by, or none.

    Keyed by that demand's own deadline and Area rather than summed over every deadline gap: the
    week holds a second demand in another Area, and a pin before one deadline moves the other's
    reading too. A property about one gap has to read one gap.
    """
    demand = measured_demand(week)
    return sum(
        shortfall.minutes
        for shortfall in probe(week).shortfalls
        if shortfall.kind is ShortfallKind.DEADLINE_CAPACITY
        and shortfall.deadline == demand.deadline
        and shortfall.area_id == demand.area_id
    )


def floors_gap(verdict: Verdict) -> int:
    """The minutes every floor together is short by, or none."""
    return sum(
        shortfall.minutes
        for shortfall in verdict.shortfalls
        if shortfall.kind is ShortfallKind.FLOORS_EXCEED_CAPACITY
    )


def available_to(week: ProbeInputs) -> int:
    """A lower bound on what the measured demand could take before its deadline.

    A pin larger than what the demand had takes capacity from something else: from the other
    Areas' floors, or from an earlier deadline. That is a real edit and it is a different
    property, because the minutes it frees for this demand were never this demand's to lose.
    Derived from the gap rather than recomputed: a demand short by ``g`` had ``remaining - g``.
    """
    demand = measured_demand(week)
    return max(0, demand.remaining_minutes - deadline_gap(week))


@given(
    week=weeks(with_room_before_the_deadline=True, demands=1),
    take=st.integers(min_value=1, max_value=120),
)
def test_pinning_work_toward_a_demand_leaves_its_shortfall_exactly_as_it_was(
    week: ProbeInputs, take: int
) -> None:
    # Progress is never punished. The pin removes the span from free capacity AND removes the
    # same minutes from the demand, so the comparison is unchanged: an earlier reading that
    # netted only one side reported a gap that the pin itself had caused.
    #
    # One demand, because with a competitor the pin can take capacity an EARLIER deadline was
    # counting on, and then the gap moves between the two demands rather than staying put. That is
    # conservation rather than invariance, and it has its own example below.
    deadline = measured_demand(week).deadline
    free = free_before(week, deadline)
    assume(available_to(week) >= take)
    pinned = a_window_to_pin_into(free, take)
    assume(pinned is not None)
    assert pinned is not None

    assert deadline_gap(pinning_toward(week, pinned)) == deadline_gap(week)


def test_pinning_into_capacity_an_earlier_deadline_needed_moves_the_gap_not_closes_it() -> None:
    # Why the equality above is stated over a week with one demand. Free capacity runs from 03:07
    # on the Monday; Fitness owes 257 minutes by 07:24, which is exactly what it has, and Career
    # owes 157 by 10:00 against the 156 that are left after Fitness's claim, so Career is a minute
    # short.
    #
    # Pinning one minute of CAREER's work at 03:07 puts it inside the window Fitness needed. Career
    # now fits and Fitness does not: the minute moved between the two demands, and the week is
    # still short by exactly one. That is the arithmetic being right rather than the property being
    # violated, so the property is stated where it is an invariance and this is stated where it is
    # a conservation.
    career_due = MONDAY + timedelta(hours=10)
    fitness_due = MONDAY + timedelta(hours=7, minutes=24)
    week = ProbeInputs(
        span=WEEK,
        now=MONDAY,
        computed_at=MONDAY,
        input_version=1,
        placed=IntervalSet([Interval(MONDAY, MONDAY + timedelta(hours=3, minutes=7))]),
        deadline_demands=(
            DeadlineDemand(
                deadline=career_due,
                remaining_minutes=157,
                area_id=CAREER,
                labels=("F&F Past Papers",),
            ),
            DeadlineDemand(
                deadline=fitness_due,
                remaining_minutes=257,
                area_id=FITNESS,
                labels=("Gym",),
            ),
        ),
    )
    pinned = Interval(
        MONDAY + timedelta(hours=3, minutes=7), MONDAY + timedelta(hours=3, minutes=8)
    )

    before = {(gap.area_id, gap.minutes) for gap in probe(week).shortfalls}
    after = {(gap.area_id, gap.minutes) for gap in probe(pinning_toward(week, pinned)).shortfalls}

    assert before == {(CAREER, 1)}
    assert after == {(FITNESS, 1)}


@given(
    week=weeks(with_room_before_the_deadline=True),
    take=st.integers(min_value=1, max_value=120),
    toward_their_deadline=st.booleans(),
)
def test_pinning_anything_else_can_only_make_the_reading_worse(
    week: ProbeInputs, take: int, toward_their_deadline: bool
) -> None:
    # The honest general property is non-improvement, and it is per measurement rather than per
    # verdict. A pin that is not progress toward this demand takes capacity from it and gives it
    # nothing back, so its gap cannot fall; and the whole-week floor gap cannot fall either,
    # because the reservation it is compared against falls by at most the pinned minutes.
    #
    # **The pinned Area's OWN floor gap may fall, and that is correct.** Work pinned in Fitness is
    # progress toward the Fitness floor, so an unreachable-floor gap that the pin satisfies closes.
    # A property stated over every gap in the verdict fails on exactly that case, which is a
    # property that has read "pinning anything else" as "pinning anything at all".
    #
    # ``toward_their_deadline`` is drawn because the other Area's demand falls as well as its floor
    # when the pinned work is that Area's own deadline-bearing work. One placement does both, so a
    # transformation that moves one and not the other is not a state the assembler can produce.
    free = free_before(week, measured_demand(week).deadline)
    pinned = a_window_to_pin_into(free, take)
    assume(pinned is not None)
    assert pinned is not None

    after = pinning_elsewhere(week, pinned, toward_their_deadline=toward_their_deadline)

    assert deadline_gap(after) >= deadline_gap(week)
    assert floors_gap(probe(after)) >= floors_gap(probe(week))


@given(week=weeks(), extra=st.integers(min_value=1, max_value=600))
def test_work_becoming_outstanding_again_never_reduces_a_gap(week: ProbeInputs, extra: int) -> None:
    # What an outcome on a past block can do to the arithmetic: change what is attributed to the
    # task, in the direction of more work outstanding. Capacity cannot move, so no gap may fall.
    demand = measured_demand(week)
    gross = dataclasses.replace(
        week,
        deadline_demands=(
            dataclasses.replace(demand, remaining_minutes=demand.remaining_minutes + extra),
            *week.deadline_demands[1:],
        ),
    )

    assert no_gap_fell(probe(week), probe(gross))


@given(week=weeks())
def test_a_past_placement_is_outside_capacity_however_it_is_recorded(week: ProbeInputs) -> None:
    # The capacity half of the same rule, and it is structural rather than a carve-out: capacity
    # starts at `now`, so a span behind it was never in capacity and cannot be returned to it.
    # This is what closed the hole where pressing "skip" on a Tuesday hour made a Thursday
    # reading of the week improve by an hour.
    without_the_past = dataclasses.replace(week, placed=week.placed.after(week.now))

    assert probe(without_the_past) == probe(week)


@given(week=weeks(), elapsed=st.integers(min_value=1, max_value=WEEK_MINUTES))
def test_advancing_now_with_nothing_else_changed_never_reduces_a_gap(
    week: ProbeInputs, elapsed: int
) -> None:
    # What makes a mid-week transition from feasible to infeasible computable: time passing can
    # only take capacity away, so a gap can appear and none can close.
    later = week.now + timedelta(minutes=elapsed)
    advanced = dataclasses.replace(week, now=later, computed_at=later)

    assert no_gap_fell(probe(week), probe(advanced))


@given(week=weeks(), elapsed=st.integers(min_value=1, max_value=WEEK_MINUTES))
def test_advancing_now_does_not_move_the_denominator(week: ProbeInputs, elapsed: int) -> None:
    # The other half of the two spans: the figure the budget report renders is taken over the
    # whole week, so it does not change as the week elapses.
    later = week.now + timedelta(minutes=elapsed)

    assert (
        probe(dataclasses.replace(week, now=later, computed_at=later)).discretionary_minutes
        == probe(week).discretionary_minutes
    )


@given(week=weeks())
def test_the_probes_denominator_is_the_one_the_budget_report_takes(week: ProbeInputs) -> None:
    # The assertion that closes scope drift between the two surfaces. It is not a tautology: the
    # figure fails here if the probe subtracts the scoped windows, clips the span to `now`, or
    # sums the subtrahends instead of unioning them.
    assert probe(week).discretionary_minutes == discretionary_time(
        week.span,
        frame=week.frame,
        anchors=week.anchors,
        absolute_forbidden=week.absolute_forbidden,
        off_plan=week.off_plan,
    )


@given(week=weeks())
def test_a_scoped_window_is_never_worth_more_to_an_area_than_an_absolute_one(
    week: ProbeInputs,
) -> None:
    # Converting a window from named Areas to every Area may only take capacity away: from the
    # Areas it named, nothing, because they were already forbidden; from every other Area, the
    # whole window. A figure that moved the other way would be subtracting a scoped window from
    # a whole-week total, which manufactures a gap the week does not have.
    #
    # The windows converted are the week's OWN, which name Areas the week holds a floor and a
    # demand in. An injected window naming an Area nothing in the week carries is inert: it changes
    # no figure, so the property would hold whatever the arithmetic did with a scope.
    assume(week.scoped_forbidden)
    absolute = dataclasses.replace(
        week,
        scoped_forbidden=(),
        absolute_forbidden=week.absolute_forbidden.union(
            IntervalSet(window.interval for window in week.scoped_forbidden)
        ),
    )

    assert probe(absolute).discretionary_minutes <= probe(week).discretionary_minutes
    assert no_gap_fell(probe(week), probe(absolute))


@given(
    reserved=st.integers(min_value=1, max_value=600), owed=st.integers(min_value=1, max_value=600)
)
def test_the_recovery_windows_two_declarations_cost_the_area_they_name(
    reserved: int, owed: int
) -> None:
    # The shared fixture's own window, over a week whose Areas are the fixture's, so the scope it
    # declares actually binds. The two declarations differ in scope and in nothing else, which is
    # what the fixture exists for.
    study = recovery_scopes.STUDY
    week = ProbeInputs(
        span=recovery_scopes.SPAN,
        now=recovery_scopes.SPAN.start,
        computed_at=recovery_scopes.SPAN.start,
        input_version=1,
        area_floor_reservations=(
            FloorReservation(area_id=study, reserved_minutes=reserved, label="Study"),
        ),
        deadline_demands=(
            DeadlineDemand(
                deadline=recovery_scopes.SPAN.end,
                remaining_minutes=owed,
                area_id=study,
                labels=("F&F Past Papers",),
            ),
        ),
        scoped_forbidden=(recovery_scopes.SCOPED,),
    )
    absolute = dataclasses.replace(
        week,
        scoped_forbidden=(),
        absolute_forbidden=IntervalSet([recovery_scopes.RECOVERY]),
    )

    # The scoped form stays in the denominator and the absolute form leaves it, by exactly the
    # window's 75 minutes. Neither form is capacity for Study, so no gap of its falls.
    assert probe(week).discretionary_minutes - probe(absolute).discretionary_minutes == (
        recovery_scopes.RECOVERY_MINUTES
    )
    assert no_gap_fell(probe(week), probe(absolute))


@dataclasses.dataclass(frozen=True, slots=True)
class Obligation:
    """Minutes one Area must find, and the capacity it may find them in.

    A demand is one of these before its deadline. A floor is one over the whole week, for the part
    of it **its own Area's demands do not already cover**: a block placed for a Career task lands in
    the Career Area, so an Area owing 2h by Wednesday against a 5h floor owes 5h in total rather
    than 7h. An Area's total requirement is therefore ``max(floor, sum of its demands)``, expressed
    here as each demand under its own deadline plus the floor's remainder anywhere in the week,
    which preserves both the total and the per-deadline sub-constraints.

    **The first version of this oracle counted the two in full**, and that conservatism was not
    generic: it coincided exactly with the probe's own-floor exclusion, which is this module's most
    contested derivation. So the weeks that would have exposed a fault in that rule were the weeks
    the oracle called infeasible, and the property discarded them. An oracle whose blind spot is the
    same shape as the arithmetic's is an oracle that makes a gap look measured.
    """

    minutes: int
    capacity: IntervalSet


def obligations(week: ProbeInputs) -> tuple[Obligation, ...]:
    """Everything the week owes, with the capacity each may be satisfied in.

    The per-Area capacity is derived from ``ScopedWindow.forbids`` rather than through
    ``ProbeInputs.scoped_against``, which the probe itself calls: an oracle that shares the scope
    reading with the module it checks cannot see a fault in that reading, because both sides move
    together and the week is filtered out.
    """
    occupied = week.frame.union(week.anchors).union(week.absolute_forbidden).union(week.off_plan)
    free = IntervalSet([week.span]).subtract(occupied).after(week.now).subtract(week.placed)

    def claimable(area_id: AreaId) -> IntervalSet:
        return free.subtract(
            IntervalSet(
                window.interval for window in week.scoped_forbidden if window.forbids(area_id)
            )
        )

    owed = [
        Obligation(demand.remaining_minutes, claimable(demand.area_id).before(demand.deadline))
        for demand in week.deadline_demands
    ]
    owed += [
        Obligation(
            max(
                0,
                reservation.reserved_minutes
                - sum(
                    demand.remaining_minutes
                    for demand in week.deadline_demands
                    if demand.area_id == reservation.area_id
                ),
            ),
            claimable(reservation.area_id),
        )
        for reservation in week.area_floor_reservations
    ]
    return tuple(one for one in owed if one.minutes)


def every_subset_fits(owed: tuple[Obligation, ...]) -> bool:
    """Whether an assignment of minutes exists that satisfies every obligation at once.

    Hall's condition over the obligations: a set of them fits if and only if no subset asks for
    more minutes than the union of the capacity that subset may use. Written here as an independent
    oracle, deliberately: it shares no expression with the probe, so a property comparing the two
    compares two derivations rather than one applied twice.

    Exact for divisible minutes, which is what the probe measures. A minimum chunk is the solver's
    question, and the kind of failure the probe structurally cannot find.
    """
    for size in range(1, len(owed) + 1):
        for combination in combinations(owed, size):
            claimable = IntervalSet()
            for one in combination:
                claimable = claimable.union(one.capacity)
            if sum(one.minutes for one in combination) > claimable.total_minutes():
                return False
    return True


@st.composite
def weeks_that_can_hold_their_work(draw: st.DrawFn) -> ProbeInputs:
    """A week whose obligations are drawn from the capacity it really has, per Area.

    The property this feeds is stated over weeks where an assignment exists, and drawing
    obligations blindly and filtering for that would discard most of them. So the capacity is
    computed inside the strategy and every obligation is drawn from what its own Area may really
    claim. The floor is drawn to land in the band where a per-Area capacity set and a whole-week
    figure disagree, which is the shape a blind draw almost never produces.

    The scoped windows and the second Area are the point: they are what make one Area's capacity
    differ from the week's, which is the shape the arithmetic has to get right.
    """
    now_minutes = draw(st.integers(min_value=0, max_value=WEEK_MINUTES // 2))
    now = MONDAY + timedelta(minutes=now_minutes)
    frame = draw(interval_sets(max_size=2))
    anchors = draw(interval_sets(max_size=1))
    absolute_forbidden = draw(interval_sets(max_size=1))
    off_plan = draw(interval_sets(max_size=1))
    placed = draw(interval_sets(max_size=2))
    measured = draw(st.sampled_from((CAREER, FITNESS)))
    competitor = FITNESS if measured == CAREER else CAREER
    windows = draw(scoped_windows(measured, competitor))

    occupied = frame.union(anchors).union(absolute_forbidden).union(off_plan)
    free = IntervalSet([WEEK]).subtract(occupied).after(now).subtract(placed)

    def claimable(area_id: AreaId) -> IntervalSet:
        return free.subtract(
            IntervalSet(window.interval for window in windows if window.forbids(area_id))
        )

    mine, theirs = claimable(measured), claimable(competitor)
    # The competitor's deadline is the EARLIER one, because the fault this property exists to see
    # needs the competitor to have already claimed capacity by the time the measured demand is
    # checked. The measured deadline is drawn at the week's end as often as anywhere after it, so
    # that the capacity able to absorb a floor LATER is nil in a fair share of weeks: without that,
    # a competitor's floor never has to land before the deadline and its two figures never overlap.
    theirs_due = MONDAY + timedelta(
        minutes=draw(st.integers(min_value=now_minutes, max_value=WEEK_MINUTES))
    )
    mine_due = MONDAY + timedelta(
        minutes=draw(
            st.one_of(
                st.just(WEEK_MINUTES),
                st.integers(min_value=now_minutes, max_value=WEEK_MINUTES),
            )
        )
    )
    # The competitor's demand is drawn up to ALL of the capacity it may use rather than half of it,
    # and its floor is drawn rather than fixed at zero, because an Area holding both is the shape
    # the fourth site of the competitor defect needed: its floor and its own earlier work are one
    # set of minutes.
    owed_by_them = draw(
        st.integers(min_value=0, max_value=theirs.before(theirs_due).total_minutes())
    )
    reserved_by_them = draw(
        st.integers(min_value=0, max_value=max(owed_by_them, theirs.total_minutes()))
    )
    # What the competitor really has to place before the measured deadline: the larger of the two,
    # never their sum. Derived here so the measured demand can be drawn against the boundary the
    # arithmetic should allow, which is where the two readings differ.
    absorbed_later = free.after(mine_due).total_minutes()
    committed_by_them = max(owed_by_them, max(0, reserved_by_them - absorbed_later))
    together = mine.union(theirs).total_minutes()
    at_least = max(0, mine.total_minutes() - committed_by_them)
    reserved_by_me = draw(
        st.integers(min_value=at_least, max_value=max(at_least, together - committed_by_them))
    )
    return ProbeInputs(
        span=WEEK,
        now=now,
        computed_at=now,
        input_version=draw(st.integers(min_value=0, max_value=99)),
        frame=frame,
        anchors=anchors,
        absolute_forbidden=absolute_forbidden,
        scoped_forbidden=windows,
        off_plan=off_plan,
        placed=placed,
        area_floor_reservations=(
            FloorReservation(
                area_id=measured, reserved_minutes=reserved_by_me, label=NAMES[measured]
            ),
            FloorReservation(
                area_id=competitor, reserved_minutes=reserved_by_them, label=NAMES[competitor]
            ),
        ),
        deadline_demands=(
            DeadlineDemand(
                deadline=mine_due,
                remaining_minutes=draw(
                    st.integers(
                        min_value=0,
                        max_value=max(
                            0,
                            mine.before(mine_due).total_minutes() - committed_by_them,
                        ),
                    )
                ),
                area_id=measured,
                labels=("F&F Past Papers",),
            ),
            DeadlineDemand(
                deadline=theirs_due,
                remaining_minutes=owed_by_them,
                area_id=competitor,
                labels=("Kim's Game Project",),
            ),
        ),
    )


@given(week=weeks_that_can_hold_their_work())
def test_a_week_that_can_hold_all_of_its_work_is_reported_with_no_gap_at_all(
    week: ProbeInputs,
) -> None:
    # The invariant the whole module rests on, stated against an independent oracle rather than
    # against the probe's own expressions: capacity arithmetic may under-report and may never
    # over-report, so a week where an assignment exists must report nothing.
    #
    # This is the property that sees a whole-week competitor charged against a per-Area capacity
    # set. Both reproductions in the example suite satisfy Hall's condition and were reported as
    # gaps, and this property finds that shape by itself.
    assume(every_subset_fits(obligations(week)))

    assert probe(week).shortfalls == ()


@given(week=weeks())
def test_no_generated_week_is_ever_reported_as_feasible(week: ProbeInputs) -> None:
    assert not probe(week).feasible
    assert probe(week).provenance.value == "probe"


@given(take=st.integers(min_value=1, max_value=60))
def test_the_half_done_task_stays_exactly_as_short_when_more_of_it_is_pinned(take: int) -> None:
    # The same invariance over the shared fixture rather than a generated week: a task with half
    # its estimate already placed, an unconfirmed past hour, and an hour that falls after the
    # deadline. Pinning more of it moves neither side of the comparison.
    week = partial_progress.PARTIAL_PROGRESS
    free = free_before(week, partial_progress.DEADLINE)
    assume(available_to(week) >= take)
    pinned = a_window_to_pin_into(free, take)
    assert pinned is not None

    assert deadline_gap(pinning_toward(week, pinned)) == deadline_gap(week)


def test_the_half_done_task_demands_only_what_is_left_of_it() -> None:
    # The fixture's own arithmetic, asserted against the probe rather than only against itself:
    # 240 minutes of estimate, 60 attributed to the unconfirmed past hour, 120 pinned before the
    # deadline, and the hour on Saturday satisfying nothing.
    week = partial_progress.PARTIAL_PROGRESS

    assert week.deadline_demands[0].remaining_minutes == 60
    assert probe(week).shortfalls == ()
    assert deadline_gap(dataclasses.replace(week, now=partial_progress.DEADLINE)) == 60
