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
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syncr_domain.discretionary import discretionary_time
from syncr_domain.feasibility import Provenance, ScopedWindow, Shortfall, ShortfallKind, probe
from syncr_domain.fixtures.dst_weeks import DST_WEEKS, DstWeek
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
    from syncr_domain.feasibility import ProbeInputs
    from syncr_domain.identifiers import AreaId
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
    # A healthy solved week is by definition one whose floors are met by solver-placed blocks, and
    # those are unpinned. The reservation arrives net of EVERY placement, so it is zero here, and
    # free capacity has the same blocks out of it.
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


# --- work another Area must do inside a window this Area cannot use ---------------------------
#
# Both per-Area checks compare a whole-week quantity from OTHER Areas against the capacity THIS
# Area may claim, and the two operands are over different sets the moment a scoped window names
# this Area: its capacity has the window removed and the other Areas' work does not have to avoid
# it. Charging the whole of that work here reports a gap on a week where a valid assignment exists,
# which is the one error direction capacity arithmetic may not take.
#
# Both cases below hold three hours of free capacity, two of which are forbidden to one Area, and
# in both a valid assignment exists.

SCOPED_MORNING = Interval(at(9, day=0), at(11, day=0))
OPEN_HOUR = Interval(at(11, day=0), at(12, day=0))
REST_OF_THE_WEEK = Interval(at(12, day=0), at(0, day=7))


def a_week_of_three_hours(forbidden_to: AreaId, **overrides: object) -> ProbeInputs:
    """Monday 09:00 to 12:00 and nothing else, with the first two hours forbidden to one Area."""
    stated: dict[str, object] = {
        "now": at(9, day=0),
        "off_plan": occupying(REST_OF_THE_WEEK),
        "scoped_forbidden": (
            ScopedWindow(interval=SCOPED_MORNING, forbidden_area_ids=(forbidden_to,)),
        ),
    }
    stated.update(overrides)
    return a_week(**stated)


def test_an_earlier_deadline_that_can_use_a_window_this_area_cannot_does_not_charge_it() -> None:
    # Fitness owes two hours by Wednesday and may use the whole three; Career owes one hour by
    # Thursday and may use only the open hour. Fitness in the window, Career in the hour outside
    # it: the week holds both, so the honest answer is no gap.
    week = a_week_of_three_hours(
        CAREER,
        deadline_demands=(
            a_demand(FITNESS, 2 * 60, at(9, day=2), label="Gym"),
            a_demand(CAREER, 60, at(9, day=3), label="Leetcode"),
        ),
    )

    assert probe(week).shortfalls == ()


def test_another_areas_work_inside_a_window_this_area_cannot_use_does_not_block_its_floor() -> None:
    # The same asymmetry in the per-Area check. Career owes two hours by 11:00, which only the
    # forbidden window can hold; Fitness needs one hour of floor, which the open hour holds.
    week = a_week_of_three_hours(
        FITNESS,
        area_floor_reservations=(a_reservation(FITNESS, 60),),
        deadline_demands=(a_demand(CAREER, 2 * 60, at(11, day=0), label="Leetcode"),),
    )

    assert probe(week).shortfalls == ()


def test_the_discount_is_bounded_by_what_the_other_areas_can_really_place_elsewhere() -> None:
    # The control on the correction, so it cannot become "other Areas never compete". Career owes
    # three hours by Thursday against the same three hours of capacity, of which Fitness may claim
    # only the last one: two of Career's hours fit the window Fitness cannot use and the third
    # takes Fitness's own hour, so the Fitness floor really is unreachable by that hour.
    week = a_week_of_three_hours(
        FITNESS,
        area_floor_reservations=(a_reservation(FITNESS, 60),),
        deadline_demands=(a_demand(CAREER, 3 * 60, at(9, day=3), label="Leetcode"),),
    )

    unreachable = next(
        gap for gap in probe(week).shortfalls if gap.kind is ShortfallKind.AREA_FLOOR_UNREACHABLE
    )
    assert unreachable.minutes == 60


# --- one Area's floor and that Area's own deadline work are the same minutes -----------------
#
# A block placed for a Career task lands in the Career Area, so it satisfies the Career task AND the
# Career floor. The production arithmetic says so in both directions: `reservations.py` nets every
# placement in the Area out of the reservation, and `demand.py` nets the same placement out of the
# demand. So a competitor Area holding an earlier deadline and an unmet floor must place the LARGER
# of the two before this deadline, never their sum.
#
# Neither case below holds a scoped window: this is the reading that needs no scope at all.


def weekday_evenings_and_nights() -> IntervalSet:
    """Everything outside 09:00 to 18:00 on the five weekdays, so each holds nine free hours."""
    return IntervalSet(
        [
            *(Interval(at(0, day=day), at(9, day=day)) for day in range(5)),
            *(Interval(at(18, day=day), at(24, day=day)) for day in range(5)),
        ]
    )


def test_a_competitors_task_is_not_charged_again_inside_that_areas_own_floor() -> None:
    # An ordinary week: nine discretionary hours on each of five weekdays, the weekend off, so 2700
    # free minutes. Career holds a 5h floor and a 2h task due Wednesday, and the task is part of the
    # floor rather than extra to it, so Career's real requirement is 300. Fitness owes 2400 by
    # Friday. 300 + 2400 is exactly 2700: the week holds both, and the honest answer is no gap.
    #
    # Charging Career's task once as an earlier claim and again inside its floor invents 120 minutes
    # of work the week does not owe, which is exactly the gap that reading reports.
    week = a_week(
        now=WEEK.start,
        frame=weekday_evenings_and_nights(),
        off_plan=occupying(Interval(at(0, day=5), at(0, day=7))),
        area_floor_reservations=(a_reservation(CAREER, 300),),
        deadline_demands=(
            a_demand(CAREER, 120, at(18, day=2), label="Leetcode"),
            a_demand(FITNESS, 2400, at(18, day=4), label="Gym"),
        ),
    )

    assert probe(week).discretionary_minutes == 2700
    assert probe(week).shortfalls == ()


def test_the_same_reading_at_sixty_minutes() -> None:
    # The smallest instance of it. One free hour on the Monday: Career owes a minute by 00:01 and
    # holds a 59-minute floor, Fitness owes a minute by 00:02. Career at 00:00, Fitness at 00:01,
    # Career for the remaining 58: 59 Career minutes and one Fitness minute inside 60.
    week = a_week(
        now=WEEK.start,
        off_plan=occupying(Interval(at(1, day=0), at(0, day=7))),
        area_floor_reservations=(a_reservation(CAREER, 59),),
        deadline_demands=(
            a_demand(CAREER, 1, at(0, minute=1, day=0), label="Leetcode"),
            a_demand(FITNESS, 1, at(0, minute=2, day=0), label="Gym"),
        ),
    )

    assert probe(week).shortfalls == ()


def test_a_competitor_that_owes_more_than_its_floor_is_charged_the_larger_figure() -> None:
    # The control on the correction, so it cannot become "an Area's earlier work is free". The same
    # week, with Career owing 400 minutes by Wednesday against a 300-minute floor: the larger figure
    # is the task now, so Career must place 400 before Friday and Fitness's 2400 no longer fits.
    week = a_week(
        now=WEEK.start,
        frame=weekday_evenings_and_nights(),
        off_plan=occupying(Interval(at(0, day=5), at(0, day=7))),
        area_floor_reservations=(a_reservation(CAREER, 300),),
        deadline_demands=(
            a_demand(CAREER, 400, at(18, day=2), label="Leetcode"),
            a_demand(FITNESS, 2400, at(18, day=4), label="Gym"),
        ),
    )

    gap = next(shortfall for shortfall in probe(week).shortfalls if shortfall.area_id == FITNESS)
    assert gap.minutes == 100


def test_two_competitors_are_discounted_once_between_them_rather_than_once_each() -> None:
    # The discount is against the capacity this Area cannot use, and there is only one such set, so
    # two competitors share it. Discounting each of them by the whole of it credits this Area twice
    # with the same minutes and hides a gap that is real.
    #
    # Five hours are free from Monday 00:00 and the first is forbidden to Study, so Study may claim
    # four and one hour is capacity only the others can use. Career owes an hour by 02:00, Fitness
    # reserves an hour of floor that has nowhere after 05:00 to go, and Study owes four hours by
    # 05:00. Six hours of work against five of capacity: Study is an hour short, exactly once.
    week = a_week(
        now=WEEK.start,
        off_plan=occupying(Interval(at(5, day=0), at(0, day=7))),
        scoped_forbidden=(
            ScopedWindow(
                interval=Interval(at(0, day=0), at(1, day=0)), forbidden_area_ids=(STUDY,)
            ),
        ),
        area_floor_reservations=(a_reservation(FITNESS, 60),),
        deadline_demands=(
            a_demand(CAREER, 60, at(2, day=0), label="Leetcode"),
            a_demand(STUDY, 4 * 60, at(5, day=0), label="F&F Past Papers"),
        ),
    )

    gap = next(
        shortfall
        for shortfall in probe(week).shortfalls
        if shortfall.area_id == STUDY and shortfall.kind is ShortfallKind.DEADLINE_CAPACITY
    )
    assert gap.minutes == 60


def test_another_areas_floor_that_must_fit_early_is_discounted_the_same_way() -> None:
    # The third reading of the same asymmetry, and the one a property found rather than a reader:
    # the floors of other Areas that cannot wait until after a deadline are a whole-week figure too.
    #
    # The whole week is free from Monday 00:00, and one minute of it is forbidden to Fitness. Career
    # reserves all but one of the week's 10080 minutes, so one minute of its floor has to land in
    # the three before 00:03; Fitness owes one minute by 00:03 and may use two of those three. The
    # week holds both: Career takes the forbidden minute and Fitness takes one of the other two.
    week = a_week(
        now=WEEK.start,
        scoped_forbidden=(
            ScopedWindow(
                interval=Interval(WEEK.start, WEEK.start + timedelta(minutes=1)),
                forbidden_area_ids=(FITNESS,),
            ),
        ),
        area_floor_reservations=(a_reservation(CAREER, WEEK_MINUTES - 1),),
        deadline_demands=(a_demand(FITNESS, 1, WEEK.start + timedelta(minutes=3), label="Gym"),),
    )

    assert probe(week).shortfalls == ()


def test_a_deadline_shortfall_states_what_each_honored_floor_took_from_its_window() -> None:
    # Friday 18:00 splits the empty week's 10080 free minutes into 6840 before it and 3240 after.
    # Fitness reserves 3840, so 600 of its floor cannot wait past Friday; Study reserves 3640, so
    # 400 of its floor cannot either. Career owes 6500 of the 6840, which leaves 5840 once the two
    # competitors take theirs: a gap of 660, carried per floor at what it ACTUALLY took, beside an
    # honoring phrase that still names each floor at its declared size.
    week = a_week(
        now=WEEK.start,
        area_floor_reservations=(a_reservation(FITNESS, 3840), a_reservation(STUDY, 3640)),
        deadline_demands=(a_demand(CAREER, 6500, at(18, day=4), label="Leetcode"),),
    )

    gap, fitness_row, study_row = probe(week).shortfalls

    assert gap.kind is ShortfallKind.DEADLINE_CAPACITY
    assert gap.minutes == 660
    assert gap.honored_floor_minutes == (("Fitness", 600), ("Study", 400))
    assert "the Fitness floor of 64h" in gap.honoring
    assert fitness_row.kind is ShortfallKind.AREA_FLOOR_UNREACHABLE
    assert fitness_row.minutes == 260
    assert fitness_row.honored_floor_minutes == ()
    assert study_row.honored_floor_minutes == ()


def test_a_floor_that_fits_after_the_deadline_took_nothing_and_carries_no_take() -> None:
    # The same window, with a competitor floor small enough to fit entirely after Friday: nothing
    # is honored for it, so there is no take to carry and no phrase naming it either.
    week = a_week(
        now=WEEK.start,
        area_floor_reservations=(a_reservation(FITNESS, 300),),
        deadline_demands=(a_demand(CAREER, 7000, at(18, day=4), label="Leetcode"),),
    )

    (gap,) = probe(week).shortfalls

    assert gap.kind is ShortfallKind.DEADLINE_CAPACITY
    assert gap.minutes == 7000 - 6840
    assert gap.honored_floor_minutes == ()
    assert not any("floor" in entry for entry in gap.honoring)


def test_no_check_reads_a_demand_s_per_task_pairs() -> None:
    # Reporting only, asserted rather than stated: the pairs exist so a recovery can name its
    # contributors exactly, and a check reading them would be deriving a second demand.
    week = a_week(deadline_demands=(a_demand(CAREER, 240, FRIDAY_MORNING),))
    named = dataclasses.replace(week.deadline_demands[0], contributors=((uuid4(), 240),))

    assert probe(week) == probe(dataclasses.replace(week, deadline_demands=(named,)))


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


# --- a week whose own length is not 168 hours ------------------------------------------------


@pytest.mark.parametrize("week", DST_WEEKS, ids=[one.label for one in DST_WEEKS])
def test_a_transition_week_is_measured_in_the_minutes_it_really_holds(week: DstWeek) -> None:
    # The arithmetic is over instants and every figure it takes is elapsed minutes, so a daylight
    # transition needs no special case. That is a claim, so it is measured: the spring week holds
    # 167 hours and the autumn week 169, and the denominator is each week's own length.
    probed = a_week(span=week.span, now=week.span.start, computed_at=week.span.start)

    assert probe(probed).discretionary_minutes == week.span_minutes
    assert probe(probed).shortfalls == ()


@pytest.mark.parametrize("week", DST_WEEKS, ids=[one.label for one in DST_WEEKS])
def test_a_floor_of_exactly_a_transition_weeks_length_fits_and_one_minute_more_does_not(
    week: DstWeek,
) -> None:
    # The boundary between two kinds, on a week whose length is not the obvious figure: a floor of
    # exactly the week reports nothing, and a minute more reports one minute, twice, because one
    # infeasibility deliberately emits a whole-week row and a per-Area row.
    def reserving(minutes: int) -> ProbeInputs:
        return a_week(
            span=week.span,
            now=week.span.start,
            computed_at=week.span.start,
            area_floor_reservations=(a_reservation(FITNESS, minutes),),
        )

    assert probe(reserving(week.span_minutes)).shortfalls == ()
    assert [gap.minutes for gap in probe(reserving(week.span_minutes + 1)).shortfalls] == [1, 1]


# --- the size the arithmetic is budgeted at ---------------------------------------------------


def test_the_arithmetic_answers_a_week_of_roughly_two_hundred_intervals() -> None:
    # The size the latency budget is stated at, asserted as a size rather than as a duration: a
    # timing assertion in a unit suite measures the machine it runs on. What this holds is that a
    # week of that shape is an input the probe answers, and that the answer is the one the figures
    # imply.
    #
    # Every figure below is asserted rather than described, because a comment is the only statement
    # of a shape a test does not check and the first version of this one got three of its four
    # numbers wrong.
    occupied = IntervalSet(
        Interval(at(hour, minute=quarter * 15, day=day), at(hour, minute=quarter * 15 + 5, day=day))
        for day in range(7)
        for hour in range(7)
        for quarter in range(4)
    )
    week = a_week(
        frame=NIGHTS,
        anchors=occupied,
        absolute_forbidden=occupying(Interval(at(16, day=2), at(17, day=2))),
        off_plan=occupying(Interval(at(0, day=5), at(6, day=5))),
        placed=occupying(Interval(at(10, day=2), at(12, day=2))),
        scoped_forbidden=tuple(
            ScopedWindow(
                interval=Interval(at(18, day=day), at(19, day=day)), forbidden_area_ids=(STUDY,)
            )
            for day in range(7)
        ),
        area_floor_reservations=(
            a_reservation(FITNESS, 300),
            a_reservation(CAREER, 180),
            a_reservation(STUDY, 120),
        ),
        deadline_demands=tuple(
            a_demand(CAREER, 60, at(9, day=day), label=f"Task {day}") for day in range(1, 7)
        ),
    )

    members = sum(
        len(occupancy)
        for occupancy in (
            week.frame,
            week.anchors,
            week.absolute_forbidden,
            week.off_plan,
            week.placed,
        )
    )
    verdict = probe(week)

    assert members == 206
    assert len(week.scoped_forbidden) == 7
    assert len(week.area_floor_reservations) == 3
    assert len(week.deadline_demands) == 6
    assert verdict.discretionary_minutes > 0
    assert all(gap.honoring for gap in verdict.shortfalls)
