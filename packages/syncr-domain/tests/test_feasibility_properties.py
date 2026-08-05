"""The probe's properties: the five monotonicity rules the product's honesty rests on.

Each of these is a rule about how the verdict may move when one thing about the week changes, and
each exists because the opposite direction was reachable at some point in this design:

- making progress must never manufacture a gap, so pinning work toward a demand leaves that
  demand's gap exactly where it was: both sides of the comparison fall by the same amount;
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
from typing import TYPE_CHECKING

from hypothesis import assume, given
from hypothesis import strategies as st

from syncr_domain.discretionary import discretionary_time
from syncr_domain.feasibility import (
    DeadlineDemand,
    FloorReservation,
    ProbeInputs,
    ShortfallKind,
    probe,
)
from syncr_domain.fixtures import partial_progress, recovery_scopes
from syncr_domain.intervals import Interval, IntervalSet
from tests.instants import MONDAY
from tests.interval_strategies import interval_sets

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syncr_domain.feasibility import Shortfall, Verdict
    from syncr_domain.identifiers import AreaId
    from syncr_domain.intervals import Instant

WEEK = Interval(MONDAY, MONDAY + timedelta(days=7))
WEEK_MINUTES = 7 * 24 * 60

FITNESS: AreaId = partial_progress.FITNESS
CAREER: AreaId = partial_progress.CAREER

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
def weeks(draw: st.DrawFn, *, with_room_before_the_deadline: bool = False) -> ProbeInputs:
    """A week with occupancy, one demand, and a floor in each of two Areas.

    One demand rather than several, because the accumulation across demands is a rule of its own
    and these properties are about one gap at a time. The generated occupancy is real: every
    property here has to hold over a week whose capacity is broken into pieces.

    ``with_room_before_the_deadline`` places the deadline at least ten hours after ``now``, for
    the properties that have to pin minutes into the capacity before it. Left false, a deadline
    lands anywhere in the week including behind ``now``, which is the overdue case every
    monotonicity rule must also hold over.
    """
    latest_now = WEEK_MINUTES - 1440 if with_room_before_the_deadline else WEEK_MINUTES
    now_minutes = draw(st.integers(min_value=0, max_value=latest_now))
    earliest_deadline = now_minutes + 600 if with_room_before_the_deadline else 1
    deadline_minutes = draw(st.integers(min_value=earliest_deadline, max_value=WEEK_MINUTES))
    now = MONDAY + timedelta(minutes=now_minutes)
    deadline = MONDAY + timedelta(minutes=deadline_minutes)
    return ProbeInputs(
        span=WEEK,
        now=now,
        computed_at=now,
        input_version=draw(st.integers(min_value=0, max_value=99)),
        frame=draw(interval_sets(max_size=3)),
        anchors=draw(interval_sets(max_size=2)),
        absolute_forbidden=draw(interval_sets(max_size=2)),
        off_plan=draw(interval_sets(max_size=1)),
        placed=draw(interval_sets(max_size=3)),
        area_floor_reservations=(
            FloorReservation(
                area_id=CAREER,
                reserved_minutes=draw(st.integers(min_value=0, max_value=600)),
                label="Career",
            ),
            FloorReservation(
                area_id=FITNESS,
                reserved_minutes=draw(st.integers(min_value=0, max_value=600)),
                label="Fitness",
            ),
        ),
        deadline_demands=(
            DeadlineDemand(
                deadline=deadline,
                # Up to two and a half days of work, so a week whose capacity before the deadline
                # cannot hold it is an ordinary draw rather than a rare one: a property about how
                # a gap moves is worthless over inputs that mostly have no gap.
                remaining_minutes=draw(st.integers(min_value=1, max_value=3600)),
                area_id=CAREER,
                labels=("F&F Past Papers",),
            ),
        ),
    )


def free_before(week: ProbeInputs, deadline: Instant) -> IntervalSet:
    """The capacity a demand in Career has before its deadline, as the probe derives it.

    Derived here to CHOOSE an interval to pin rather than to predict a figure: a property about
    invariance under pinning has to pin minutes the week really had.
    """
    occupied = week.frame.union(week.anchors).union(week.absolute_forbidden).union(week.off_plan)
    free = IntervalSet([week.span]).subtract(occupied).after(week.now).subtract(week.placed)
    return free.subtract(week.scoped_against(CAREER)).before(deadline)


def first_minutes(free: IntervalSet, minutes: int) -> Interval:
    """The earliest ``minutes`` of a free set, as one interval inside one of its members."""
    for member in free:
        if member.total_minutes() >= minutes:
            return Interval(member.start, member.start + timedelta(minutes=minutes))
    raise AssertionError("no member of the free set is long enough to pin into")


def pinning_toward(week: ProbeInputs, pinned: Interval) -> ProbeInputs:
    """The week after the user pins ``pinned`` minutes of the Career demand's own work.

    The assembler's three consequences, restated: the committed time gains the span, the demand
    falls by its minutes because they are now placed before the deadline, and Career's floor
    reservation falls by them too because the block lands in Career. All three come from one
    placement, which is why the probe must not move.
    """
    minutes = pinned.total_minutes()
    demand = week.deadline_demands[0]
    return dataclasses.replace(
        week,
        placed=week.placed.union(IntervalSet([pinned])),
        deadline_demands=(
            dataclasses.replace(
                demand, remaining_minutes=max(0, demand.remaining_minutes - minutes)
            ),
        ),
        area_floor_reservations=tuple(
            dataclasses.replace(
                reservation, reserved_minutes=max(0, reservation.reserved_minutes - minutes)
            )
            if reservation.area_id == CAREER
            else reservation
            for reservation in week.area_floor_reservations
        ),
    )


def pinning_elsewhere(week: ProbeInputs, pinned: Interval) -> ProbeInputs:
    """The week after the user pins work that no demand here is waiting on.

    Fitness work, so the demand is untouched and Fitness's own reservation falls: the shape of
    every pin that is not progress toward the deadline being measured.
    """
    minutes = pinned.total_minutes()
    return dataclasses.replace(
        week,
        placed=week.placed.union(IntervalSet([pinned])),
        area_floor_reservations=tuple(
            dataclasses.replace(
                reservation, reserved_minutes=max(0, reservation.reserved_minutes - minutes)
            )
            if reservation.area_id == FITNESS
            else reservation
            for reservation in week.area_floor_reservations
        ),
    )


def deadline_gap(week: ProbeInputs) -> int:
    """The minutes the Career demand is short by, or none."""
    return sum(
        shortfall.minutes
        for shortfall in probe(week).shortfalls
        if shortfall.kind is ShortfallKind.DEADLINE_CAPACITY
    )


def available_to(week: ProbeInputs) -> int:
    """A lower bound on what the Career demand could take before its deadline.

    A pin larger than what the demand had takes capacity from something else: from the other
    Areas' floors, or from an earlier deadline. That is a real edit and it is a different
    property, because the minutes it frees for this demand were never this demand's to lose.
    Derived from the gap rather than recomputed: a demand short by ``g`` had ``remaining - g``.
    """
    demand = week.deadline_demands[0]
    return max(0, demand.remaining_minutes - deadline_gap(week))


@given(
    week=weeks(with_room_before_the_deadline=True),
    take=st.integers(min_value=1, max_value=120),
)
def test_pinning_work_toward_a_demand_leaves_its_shortfall_exactly_as_it_was(
    week: ProbeInputs, take: int
) -> None:
    # Progress is never punished. The pin removes the span from free capacity AND removes the
    # same minutes from the demand, so the comparison is unchanged: an earlier reading that
    # netted only one side reported a gap that the pin itself had caused.
    deadline = week.deadline_demands[0].deadline
    free = free_before(week, deadline)
    assume(free.total_minutes() >= take)
    assume(available_to(week) >= take)

    pinned = first_minutes(free, take)

    assert deadline_gap(pinning_toward(week, pinned)) == deadline_gap(week)


@given(
    week=weeks(with_room_before_the_deadline=True),
    take=st.integers(min_value=1, max_value=120),
)
def test_pinning_anything_else_can_only_make_the_reading_worse(
    week: ProbeInputs, take: int
) -> None:
    # The honest general property is non-improvement. A pin that is not progress toward this
    # demand takes capacity from it and gives it nothing back.
    free = free_before(week, week.deadline_demands[0].deadline)
    assume(free.total_minutes() >= take)

    pinned = first_minutes(free, take)

    assert no_gap_fell(probe(week), probe(pinning_elsewhere(week, pinned)))


@given(week=weeks(), extra=st.integers(min_value=1, max_value=600))
def test_work_becoming_outstanding_again_never_reduces_a_gap(week: ProbeInputs, extra: int) -> None:
    # What an outcome on a past block can do to the arithmetic: change what is attributed to the
    # task, in the direction of more work outstanding. Capacity cannot move, so no gap may fall.
    demand = week.deadline_demands[0]
    gross = dataclasses.replace(
        week,
        deadline_demands=(
            dataclasses.replace(demand, remaining_minutes=demand.remaining_minutes + extra),
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
    scoped = dataclasses.replace(week, scoped_forbidden=(recovery_scopes.SCOPED,))
    absolute = dataclasses.replace(
        week,
        scoped_forbidden=(),
        absolute_forbidden=week.absolute_forbidden.union(
            IntervalSet([recovery_scopes.SCOPED.interval])
        ),
    )

    assert probe(absolute).discretionary_minutes <= probe(scoped).discretionary_minutes
    assert no_gap_fell(probe(scoped), probe(absolute))


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

    pinned = first_minutes(free, take)

    assert deadline_gap(pinning_toward(week, pinned)) == deadline_gap(week)


def test_the_half_done_task_demands_only_what_is_left_of_it() -> None:
    # The fixture's own arithmetic, asserted against the probe rather than only against itself:
    # 240 minutes of estimate, 60 attributed to the unconfirmed past hour, 120 pinned before the
    # deadline, and the hour on Saturday satisfying nothing.
    week = partial_progress.PARTIAL_PROGRESS

    assert week.deadline_demands[0].remaining_minutes == 60
    assert probe(week).shortfalls == ()
    assert deadline_gap(dataclasses.replace(week, now=partial_progress.DEADLINE)) == 60
