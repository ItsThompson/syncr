"""The probe's arithmetic, case by case, with every figure worked in the assertion.

The cases are grouped as the arithmetic is: the two spans, the three checks, what a shortfall
says, and the boundaries where a figure changes meaning. Each figure is written out in the
assertion rather than derived, because a test that computes its own expectation from the same
rule as the code asserts only that the rule was applied twice.

The interval algebra is real here, as everywhere: a faked ``IntervalSet`` would let this suite
pass while the arithmetic underneath it was wrong.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

import pytest

from syncr_domain.discretionary import discretionary_time
from syncr_domain.feasibility import Provenance, ScopedWindow, Shortfall, ShortfallKind, probe
from syncr_domain.intervals import Interval, IntervalSet
from tests.instants import at
from tests.probe_weeks import (
    CAPACITY_MINUTES,
    CAREER,
    FITNESS,
    NOW,
    STUDY,
    WEEK,
    WEEK_MINUTES,
    a_demand,
    a_reservation,
    a_week,
    occupying,
)

if TYPE_CHECKING:
    from syncr_domain.intervals import Instant

FRIDAY_MORNING = at(9, day=4)
THURSDAY_MORNING = at(9, day=3)

# Every night of the week, 23:00 to 07:00, which is the frame's ordinary shape.
NIGHTS = IntervalSet([Interval(at(23, day=day), at(7, day=day + 1)) for day in range(7)])


def kinds(*shortfalls: Shortfall) -> list[ShortfallKind]:
    return [shortfall.kind for shortfall in shortfalls]


# --- the week with nothing in it -------------------------------------------------------------


def test_a_week_with_nothing_in_it_reports_no_gap_and_the_whole_week_as_discretionary() -> None:
    verdict = probe(a_week())

    assert verdict.shortfalls == ()
    assert verdict.discretionary_minutes == WEEK_MINUTES


def test_a_week_where_one_source_occupies_everything_has_no_discretionary_time() -> None:
    # The other end of the same arithmetic: an off-plan span over the whole week leaves nothing,
    # and nothing is zero rather than a negative figure or a refusal.
    verdict = probe(a_week(off_plan=occupying(WEEK)))

    assert verdict.discretionary_minutes == 0
    assert verdict.shortfalls == ()


# --- the two spans ---------------------------------------------------------------------------


def test_the_denominator_is_the_whole_week_and_does_not_shrink_as_the_week_elapses() -> None:
    # The figure the budget report renders. Holding it over the whole span is what stops an
    # Area's target moving every time the user reloads the page on a Thursday.
    monday = probe(a_week(now=WEEK.start)).discretionary_minutes
    sunday = probe(a_week(now=at(23, day=6))).discretionary_minutes

    assert monday == sunday == WEEK_MINUTES


def test_capacity_starts_at_now_so_the_gaps_of_a_monday_already_gone_are_not_capacity() -> None:
    # 111 hours from Wednesday 09:00 to the end of the week. Without the clip the probe credits
    # the user with the 57 hours that have already elapsed, which is how skipping work came to
    # improve the verdict: a Tuesday hour returned to capacity is an hour that no longer exists.
    reserved = CAPACITY_MINUTES + 60
    verdict = probe(a_week(area_floor_reservations=(a_reservation(FITNESS, reserved),)))

    assert kinds(*verdict.shortfalls) == [
        ShortfallKind.FLOORS_EXCEED_CAPACITY,
        ShortfallKind.AREA_FLOOR_UNREACHABLE,
    ]
    assert verdict.shortfalls[0].minutes == 60


def test_a_week_that_has_wholly_elapsed_holds_no_capacity_and_reports_the_whole_demand() -> None:
    # The boundary that has no interval: `now` past the end of the week leaves a capacity span
    # whose start is not before its end, so it is no span at all rather than an inverted one.
    elapsed = a_week(
        now=at(0, day=9),
        deadline_demands=(a_demand(CAREER, 240, FRIDAY_MORNING),),
        area_floor_reservations=(a_reservation(FITNESS, 300),),
    )

    verdict = probe(elapsed)

    assert verdict.discretionary_minutes == WEEK_MINUTES
    assert [shortfall.minutes for shortfall in verdict.shortfalls] == [300, 240, 300]


# --- the floors against the week -------------------------------------------------------------


def test_floors_that_together_exceed_the_capacity_left_report_the_difference() -> None:
    # 111 hours of capacity, and 112 hours of floor to find between two Areas.
    verdict = probe(
        a_week(
            area_floor_reservations=(
                a_reservation(FITNESS, CAPACITY_MINUTES),
                a_reservation(CAREER, 60),
            )
        )
    )

    floors = verdict.shortfalls[0]
    assert floors.kind is ShortfallKind.FLOORS_EXCEED_CAPACITY
    assert floors.minutes == 60
    assert floors.against == ("Fitness", "Career")
    assert floors.deadline is None
    assert floors.area_id is None


def test_a_floor_already_met_by_unpinned_placed_blocks_reserves_nothing() -> None:
    # Blocker 1, the probe half. A healthy solved week is by definition one whose floors are met
    # by solver-placed blocks, and those are unpinned. The reservation arrives net of EVERY
    # placement, so it is zero here, and free capacity has the same blocks out of it.
    #
    # Under the superseded rule the reservation netted immovable placements only, so this week
    # reported an eight-hour floor against two hours of uncommitted capacity: a six-hour gap on
    # the normal state of the product, at amber panel volume, with tradeoffs offered for it.
    solved = a_week(
        placed=occupying(
            Interval(at(9, day=2), at(14, day=2)),
            Interval(at(9, day=3), at(12, day=3)),
        ),
        area_floor_reservations=(a_reservation(FITNESS, 0), a_reservation(CAREER, 0)),
    )

    assert probe(solved).shortfalls == ()


def test_an_over_satisfied_floor_cannot_reserve_less_than_nothing() -> None:
    # The clamp is the producer's, and the probe states its half: a reservation of zero takes no
    # capacity, so an Area that over-served its floor does not lend capacity to another one.
    verdict = probe(
        a_week(
            area_floor_reservations=(
                a_reservation(FITNESS, 0),
                a_reservation(CAREER, CAPACITY_MINUTES + 60),
            )
        )
    )

    assert verdict.shortfalls[0].minutes == 60
    assert verdict.shortfalls[0].against == ("Career",)


# --- a demand against its deadline -----------------------------------------------------------


def test_a_demand_larger_than_the_capacity_before_its_deadline_reports_the_difference() -> None:
    # Wednesday 09:00 to Friday 09:00 is 48 hours, of which the nights take 16, leaving 32.
    verdict = probe(
        a_week(
            frame=NIGHTS,
            deadline_demands=(a_demand(CAREER, 33 * 60, FRIDAY_MORNING),),
        )
    )

    gap = verdict.shortfalls[0]
    assert gap.kind is ShortfallKind.DEADLINE_CAPACITY
    assert gap.minutes == 60
    assert gap.deadline == FRIDAY_MORNING
    assert gap.area_id == CAREER
    assert gap.against == ("F&F Past Papers",)


def test_a_deadline_at_or_before_now_holds_no_capacity_at_all() -> None:
    # Correct rather than degenerate: work due yesterday that is not done cannot be fitted
    # anywhere, so the whole remaining demand is the gap.
    overdue = a_week(deadline_demands=(a_demand(CAREER, 240, NOW),))

    assert probe(overdue).shortfalls[0].minutes == 240


def test_two_tasks_sharing_one_deadline_are_not_each_told_the_capacity_is_theirs() -> None:
    # 32 hours before Friday after the nights. Two demands of 20 hours each: the first takes 20,
    # the second finds 12, so the second is 8 short and the first is fine.
    verdict = probe(
        a_week(
            frame=NIGHTS,
            deadline_demands=(
                a_demand(CAREER, 20 * 60, FRIDAY_MORNING, label="Leetcode"),
                a_demand(CAREER, 20 * 60, FRIDAY_MORNING, label="F&F Past Papers"),
            ),
        )
    )

    assert [(gap.against, gap.minutes) for gap in verdict.shortfalls] == [(("Leetcode",), 8 * 60)]


def test_an_earlier_deadline_consumes_the_capacity_a_later_one_would_have_counted_on() -> None:
    # Thursday 09:00 is 24 hours after `now`, less 8 hours of night, so 16 are available. The
    # Thursday demand takes all 16; the Friday demand then finds 32 - 16 = 16 of its 20.
    verdict = probe(
        a_week(
            frame=NIGHTS,
            deadline_demands=(
                a_demand(CAREER, 20 * 60, FRIDAY_MORNING, label="F&F Past Papers"),
                a_demand(CAREER, 16 * 60, THURSDAY_MORNING, label="Kim's Game Project"),
            ),
        )
    )

    gap = verdict.shortfalls[0]
    assert gap.deadline == FRIDAY_MORNING
    assert gap.minutes == 4 * 60
    assert "Kim's Game Project, due no later than this" in gap.honoring


def test_the_earliest_deadline_is_checked_first_whatever_order_the_demands_arrive_in() -> None:
    # Determinism the producer cannot be relied on for: the accumulation makes the order
    # observable, so the probe orders the demands itself.
    demands = (
        a_demand(CAREER, 16 * 60, THURSDAY_MORNING, label="Kim's Game Project"),
        a_demand(CAREER, 20 * 60, FRIDAY_MORNING, label="F&F Past Papers"),
    )
    forwards = probe(a_week(frame=NIGHTS, deadline_demands=demands))
    backwards = probe(a_week(frame=NIGHTS, deadline_demands=tuple(reversed(demands))))

    assert forwards == backwards


def test_a_floor_in_another_area_that_cannot_fit_later_is_reserved_before_the_deadline() -> None:
    # Sunday 23:00 leaves one hour, so a Fitness floor of five hours has nowhere later to go and
    # takes the whole hour from the Career demand: 60 - 60 = 0 available against 60 demanded.
    verdict = probe(
        a_week(
            now=at(23, day=6),
            area_floor_reservations=(a_reservation(FITNESS, 300),),
            deadline_demands=(a_demand(CAREER, 60, WEEK.end),),
        )
    )

    gap = next(shortfall for shortfall in verdict.shortfalls if shortfall.deadline == WEEK.end)
    assert gap.minutes == 60
    assert "the Fitness floor of 5h" in gap.honoring


def test_a_floor_with_room_after_the_deadline_competes_with_nothing_before_it() -> None:
    # The correction the boundary forced. A five-hour Fitness floor with 103 hours of week left
    # after Friday morning has somewhere to go, so reserving it against a Tuesday demand would
    # report a gap on a fresh week that has room for everything.
    verdict = probe(
        a_week(
            area_floor_reservations=(a_reservation(FITNESS, 300),),
            deadline_demands=(a_demand(CAREER, 300, FRIDAY_MORNING),),
        )
    )

    assert verdict.shortfalls == ()


def test_an_areas_own_floor_is_not_reserved_against_its_own_deadline() -> None:
    # Work placed for a Career task lands in the Career Area and satisfies the Career floor, so
    # counting the floor against the deadline charges one requirement twice. It is also what
    # would make pinning work toward the deadline improve the reading it is measured by.
    own = probe(
        a_week(
            now=at(23, day=6),
            area_floor_reservations=(a_reservation(CAREER, 300),),
            deadline_demands=(a_demand(CAREER, 60, WEEK.end),),
        )
    )

    assert [gap.kind for gap in own.shortfalls] == [
        ShortfallKind.FLOORS_EXCEED_CAPACITY,
        ShortfallKind.AREA_FLOOR_UNREACHABLE,
    ]


# --- a floor against its own Area ------------------------------------------------------------


def test_a_scoped_window_is_capacity_for_every_area_it_does_not_name() -> None:
    # A window forbidding Study takes nothing from Fitness, so a Fitness floor that fits in the
    # week's capacity fits here too. Subtracting it from a whole-week figure would manufacture
    # the gap this asserts is absent.
    week = a_week(
        scoped_forbidden=(
            ScopedWindow(
                interval=Interval(at(9, day=3), at(9, day=6)), forbidden_area_ids=(STUDY,)
            ),
        ),
        area_floor_reservations=(a_reservation(FITNESS, CAPACITY_MINUTES),),
    )

    assert probe(week).shortfalls == ()


def test_a_scoped_window_bites_the_area_it_names_and_reports_what_it_cannot_reach() -> None:
    # The same window against Study's own floor: 72 hours forbidden out of 111, leaving 39, and
    # a 40-hour floor cannot be reached in them.
    week = a_week(
        scoped_forbidden=(
            ScopedWindow(
                interval=Interval(at(9, day=3), at(9, day=6)), forbidden_area_ids=(STUDY,)
            ),
        ),
        area_floor_reservations=(a_reservation(STUDY, 40 * 60),),
    )

    gap = probe(week).shortfalls[0]
    assert gap.kind is ShortfallKind.AREA_FLOOR_UNREACHABLE
    assert gap.minutes == 60
    assert gap.against == ("Study",)
    assert gap.area_id == STUDY


def test_another_areas_deadline_work_is_counted_against_a_floor_it_competes_with() -> None:
    # 111 hours of capacity, 100 hours of Career work due Friday, and a 12-hour Fitness floor:
    # the floor can reach 11 hours of it, so one is unreachable.
    week = a_week(
        area_floor_reservations=(a_reservation(FITNESS, 12 * 60),),
        deadline_demands=(a_demand(CAREER, 100 * 60, FRIDAY_MORNING),),
    )

    unreachable = next(
        gap for gap in probe(week).shortfalls if gap.kind is ShortfallKind.AREA_FLOOR_UNREACHABLE
    )
    assert unreachable.minutes == 60
    assert "F&F Past Papers" in unreachable.honoring


# --- what a shortfall says -------------------------------------------------------------------


def test_every_shortfall_names_the_constraints_that_produced_it() -> None:
    # `honoring` is what makes a refusal actionable: it names which of the user's own decisions
    # took the capacity, which is the information they choose a tradeoff with.
    week = a_week(
        frame=NIGHTS,
        anchors=occupying(Interval(at(16, day=2), at(17, day=2))),
        absolute_forbidden=occupying(Interval(at(17, day=2), at(18, day=2))),
        off_plan=occupying(Interval(at(0, day=5), at(0, day=6))),
        placed=occupying(Interval(at(10, day=2), at(12, day=2))),
        area_floor_reservations=(a_reservation(FITNESS, CAPACITY_MINUTES),),
    )

    floors = probe(week).shortfalls[0]

    # 111 hours of capacity, less 33 of night inside it (four whole nights plus the hour of
    # Sunday's that falls before the week ends), less the anchor's hour, less the hour reserved
    # after it, less the 16 hours of Saturday the off-plan span does not already share with a
    # night, less the two hours already placed. 58 hours.
    assert floors.honoring == (
        "the circadian frame",
        "your external commitments",
        "the time reserved around them",
        "the days you declared off-plan",
        "the time already committed to this week's plan",
        "the 58h still uncommitted this week",
    )


def test_occupancy_wholly_behind_now_is_not_honored_because_it_took_no_capacity() -> None:
    # A Monday anchor took nothing from the capacity this check measured, so naming it would name
    # a constraint that did not produce the gap.
    week = a_week(
        anchors=occupying(Interval(at(9, day=0), at(17, day=0))),
        area_floor_reservations=(a_reservation(FITNESS, CAPACITY_MINUTES + 60),),
    )

    assert probe(week).shortfalls[0].honoring == ("the 111h still uncommitted this week",)


# --- what the verdict carries ----------------------------------------------------------------


def test_the_verdict_is_stamped_from_the_inputs_rather_than_from_a_clock() -> None:
    stamped = probe(a_week(computed_at=at(12, day=3), input_version=91))

    assert stamped.computed_at == at(12, day=3)
    assert stamped.input_version == 91
    assert stamped.provenance is Provenance.PROBE


def test_the_arithmetic_reads_now_and_never_the_instant_the_verdict_claims() -> None:
    # Two fields, two questions. Moving the instant the verdict claims cannot move a figure, and
    # moving `now` can, which is what keeps the pair from being read as one quantity.
    week = a_week(area_floor_reservations=(a_reservation(FITNESS, CAPACITY_MINUTES + 60),))
    later = probe(dataclasses.replace(week, computed_at=at(0, day=6)))

    assert [gap.minutes for gap in later.shortfalls] == [
        gap.minutes for gap in probe(week).shortfalls
    ]
    assert later.computed_at != probe(week).computed_at


def test_no_check_reads_an_areas_target() -> None:
    # Reporting only, asserted rather than stated: a target that reached the arithmetic would be
    # a second reservation, and a gross one.
    week = a_week(area_floor_reservations=(a_reservation(FITNESS, 60),))

    assert probe(week) == probe(dataclasses.replace(week, area_targets={FITNESS: 99999}))


def test_the_probes_denominator_is_the_one_the_budget_report_takes() -> None:
    # The assertion that closes scope drift between the verdict panel and the budget report: one
    # implementation of the subtraction, called by both.
    week = a_week(
        frame=NIGHTS,
        anchors=occupying(Interval(at(16, day=2), at(17, day=2))),
        absolute_forbidden=occupying(Interval(at(17, day=2), at(18, day=2))),
        off_plan=occupying(Interval(at(0, day=5), at(0, day=6))),
    )

    assert probe(week).discretionary_minutes == discretionary_time(
        week.span,
        frame=week.frame,
        anchors=week.anchors,
        absolute_forbidden=week.absolute_forbidden,
        off_plan=week.off_plan,
    )


def test_the_same_inputs_give_the_same_verdict_including_the_order_of_its_gaps() -> None:
    week = a_week(
        now=at(23, day=6),
        area_floor_reservations=(a_reservation(FITNESS, 300), a_reservation(CAREER, 300)),
        deadline_demands=(
            a_demand(CAREER, 600, WEEK.end),
            a_demand(FITNESS, 60, THURSDAY_MORNING, label="Gym"),
        ),
    )

    assert probe(week) == probe(week)
    assert kinds(*probe(week).shortfalls) == [
        ShortfallKind.FLOORS_EXCEED_CAPACITY,
        ShortfallKind.DEADLINE_CAPACITY,
        ShortfallKind.DEADLINE_CAPACITY,
        ShortfallKind.AREA_FLOOR_UNREACHABLE,
        ShortfallKind.AREA_FLOOR_UNREACHABLE,
    ]


@pytest.mark.parametrize("now", [WEEK.start, NOW, at(23, day=6), at(0, day=7)])
def test_no_verdict_this_module_can_produce_reports_a_week_as_feasible(now: Instant) -> None:
    # The one claim the product must never make, asserted over the producer rather than only over
    # the constructor that refuses it.
    week = a_week(
        now=now,
        area_floor_reservations=(a_reservation(FITNESS, 300),),
        deadline_demands=(a_demand(CAREER, 240, FRIDAY_MORNING),),
    )

    assert not probe(week).feasible
