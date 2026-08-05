"""H8 and H9: what an Area's own budget allows, and what another Area's floor still needs.

Both are arithmetic over the state, and both sit inside the defect class this whole product is
shaped against: a quantity netting a different set from the one it is compared against. So each
figure here is asserted as a worked number rather than as a direction, and the two sets H9 counts
are driven against each other by holding everything fixed and varying only whether a placement is
one the Area's figures already netted.

The cap is measured on the LOCAL day, and the fixture week is London in February, where a local
midnight and a UTC midnight coincide. So the day-boundary tests drive a Tokyo week, where they do
not: a Monday 15:30 UTC placement is Tuesday 00:30 where the user is, and a cap read against UTC
would charge it to the wrong date.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from syncr_domain.identity import BindingRef
from syncr_domain.intervals import Interval
from syncr_domain.weeks import LOCAL_MIDNIGHT, IsoWeek
from syncr_domain.zones import to_instant
from syncr_solver.allocation import area_daily_cap, area_floor
from syncr_solver.constraints import ConstraintRule
from syncr_solver.state import PartialPlan
from tests.materialized_weeks import (
    CAREER,
    WEEK,
    a_block,
    a_candidate,
    a_live_plan,
    a_pin,
    a_transit_block,
    an_area_budget,
    an_off_plan_period,
    at,
    between,
    inputs,
    on,
)

TOKYO = "Asia/Tokyo"

GYM = BindingRef.for_task(UUID(int=11))
READING = BindingRef.for_task(UUID(int=12))
STANDUP = BindingRef.for_task(UUID(int=13))

HOUR = 60


def a_tokyo_week(**overrides: object) -> PartialPlan:
    """The same week, read where the user is nine hours ahead of UTC.

    A local date opens at 15:00 the previous day in UTC, so every day boundary falls somewhere a
    reading against UTC would put on the wrong date.
    """
    dates = WEEK.dates()
    following = IsoWeek(WEEK.year, WEEK.week).following().monday()
    stated: dict[str, object] = {
        "zone_by_date": dict.fromkeys(dates, TOKYO),
        "span": Interval(
            to_instant(LOCAL_MIDNIGHT, dates[0], TOKYO),
            to_instant(LOCAL_MIDNIGHT, following, TOKYO),
        ),
    }
    stated.update(overrides)
    return PartialPlan.of(inputs(**stated))


# --------------------------------------------------------------------------------
# H8: an Area's minutes on one local date
# --------------------------------------------------------------------------------


def test_a_candidate_that_takes_an_area_past_its_cap_for_the_day_is_refused() -> None:
    week = inputs(areas=(an_area_budget(max_per_day_minutes=HOUR),))
    already = a_candidate(between(8, 9), binding=GYM)

    rejection = area_daily_cap(
        a_candidate(between(10, 11), binding=READING),
        PartialPlan.of(week).with_placed(already),
    )

    assert rejection is not None
    assert (rejection.rule, rejection.window) == (ConstraintRule.AREA_DAILY_CAP, between(10, 11))
    assert rejection.detail == f"Fitness, 120m against a 60m cap on {on(0)}"


def test_the_same_minutes_on_another_date_are_within_the_cap() -> None:
    # The cap is per day, so a week holding seven hours of an Area capped at one an hour a day is
    # legal. Reading it as a weekly figure would refuse the ordinary case.
    week = inputs(areas=(an_area_budget(max_per_day_minutes=HOUR),))
    already = a_candidate(between(8, 9), binding=GYM)

    assert (
        area_daily_cap(
            a_candidate(between(10, 11, day=1), binding=READING),
            PartialPlan.of(week).with_placed(already),
        )
        is None
    )


def test_a_candidate_at_exactly_the_cap_is_accepted() -> None:
    week = inputs(areas=(an_area_budget(max_per_day_minutes=HOUR),))

    assert area_daily_cap(a_candidate(between(10, 11)), PartialPlan.of(week)) is None


def test_an_area_that_declares_no_cap_refuses_nothing() -> None:
    week = inputs(areas=(an_area_budget(),))
    already = a_candidate(between(8, 14), binding=GYM)

    assert (
        area_daily_cap(a_candidate(between(15, 21)), PartialPlan.of(week).with_placed(already))
        is None
    )


def test_a_candidate_whose_area_the_inputs_declare_no_budget_for_is_not_capped() -> None:
    week = inputs(areas=(an_area_budget(area_id=CAREER, name="Career", max_per_day_minutes=15),))

    assert area_daily_cap(a_candidate(between(10, 12)), PartialPlan.of(week)) is None
    assert area_daily_cap(a_candidate(between(10, 12), area_id=None), PartialPlan.of(week)) is None


def test_a_date_already_past_its_cap_refuses_nothing_elsewhere_in_the_week() -> None:
    # A week can arrive already over a cap: the user pins two hours of an Area into a day capped at
    # one, and a pin is honoured. Judging every date would then refuse every candidate of that Area
    # anywhere in the week and name a date the candidate never reaches, which blames this placement
    # for a state it did not make.
    week = inputs(
        areas=(an_area_budget(max_per_day_minutes=HOUR),),
        pins=(a_pin(binding=GYM, interval=between(8, 10)),),
    )
    inherited = a_candidate(between(8, 10), binding=GYM)

    assert (
        area_daily_cap(
            a_candidate(between(10, 11, day=2), binding=READING),
            PartialPlan.of(week, placed=(inherited,)),
        )
        is None
    )


def test_two_overlapping_placements_of_one_area_charge_their_minutes_once() -> None:
    # Unioned rather than summed. A user-authored overlap inside one Area occupies one hour of the
    # day, and summing would make a legal day read as twice the time.
    week = inputs(
        areas=(an_area_budget(max_per_day_minutes=90),),
        pins=(
            a_pin(binding=GYM, interval=between(8, 9)),
            a_pin(binding=READING, interval=between(8, 9)),
        ),
    )
    state = PartialPlan.of(week)
    for binding in (GYM, READING):
        state = state.with_placed(a_candidate(between(8, 9), binding=binding))

    assert area_daily_cap(a_candidate(between(10, 10.5), binding=STANDUP), state) is None


def test_a_candidate_crossing_local_midnight_is_charged_to_each_date_it_reaches() -> None:
    # Half of it falls on each date, so 30 minutes of an hour-long block lands in each. With 30
    # minutes already on the first date, that date reaches the cap and the rejection names it.
    week: dict[str, object] = {"areas": (an_area_budget(max_per_day_minutes=45),)}

    state = a_tokyo_week(**week)
    boundary = state.days[0].interval.end
    earlier = a_candidate(
        Interval(boundary - timedelta(hours=1), boundary - timedelta(minutes=30)), binding=GYM
    )
    crossing = a_candidate(
        Interval(boundary - timedelta(minutes=30), boundary + timedelta(minutes=30)),
        binding=READING,
    )

    rejection = area_daily_cap(crossing, state.with_placed(earlier))

    assert rejection is not None
    assert rejection.detail == f"Fitness, 60m against a 45m cap on {state.days[0].on}"


def test_the_date_a_cap_is_measured_on_is_the_users_own_rather_than_utc() -> None:
    # Tokyo is nine hours ahead, so a Monday 15:30 UTC placement is Tuesday 00:30 where the user is.
    # Read against UTC both placements would land on Monday and the cap would refuse the second.
    state = a_tokyo_week(areas=(an_area_budget(max_per_day_minutes=HOUR),))
    monday_evening = a_candidate(Interval(at(14), at(15)), binding=GYM)
    just_past_local_midnight = a_candidate(Interval(at(15.5), at(16.5)), binding=READING)

    assert state.days[0].interval.end == at(15)
    assert area_daily_cap(just_past_local_midnight, state.with_placed(monday_evening)) is None


# --------------------------------------------------------------------------------
# H9: the time another Area's floor still needs
# --------------------------------------------------------------------------------

# A week with three hours of claimable time, so a floor and a candidate are worked figures rather
# than fractions of ten thousand minutes. Everything from Monday 03:00 onwards is declared off.
NARROW_WEEK: dict[str, object] = {
    "off_plan": (an_off_plan_period(interval=Interval(at(3), at(0, day=7))),)
}


def test_a_candidate_that_leaves_another_areas_floor_unreachable_is_refused() -> None:
    # Three hours claimable, a two-hour Fitness floor unmet, and a two-hour Career candidate: one of
    # the two cannot be satisfied, and the floor is the one that may not give way.
    week = inputs(
        **NARROW_WEEK,
        areas=(
            an_area_budget(floor_minutes=2 * HOUR),
            an_area_budget(area_id=CAREER, name="Career"),
        ),
    )

    rejection = area_floor(
        a_candidate(Interval(at(0), at(2)), area_id=CAREER, binding=READING), PartialPlan.of(week)
    )

    assert rejection is not None
    assert rejection.rule is ConstraintRule.AREA_FLOOR
    assert rejection.detail == "Fitness still owes 120m of its floor, and 60m is free"


def test_a_candidate_of_the_owing_area_itself_is_accepted_because_it_helps() -> None:
    week = inputs(
        **NARROW_WEEK,
        areas=(
            an_area_budget(floor_minutes=2 * HOUR),
            an_area_budget(area_id=CAREER, name="Career"),
        ),
    )

    assert (
        area_floor(a_candidate(Interval(at(0), at(2)), binding=READING), PartialPlan.of(week))
        is None
    )


def test_a_week_with_room_for_both_refuses_neither() -> None:
    week = inputs(
        **NARROW_WEEK,
        areas=(
            an_area_budget(floor_minutes=HOUR),
            an_area_budget(area_id=CAREER, name="Career"),
        ),
    )

    assert (
        area_floor(
            a_candidate(Interval(at(0), at(2)), area_id=CAREER, binding=READING),
            PartialPlan.of(week),
        )
        is None
    )


def test_a_floor_this_pass_has_already_met_owes_nothing() -> None:
    week = inputs(
        **NARROW_WEEK,
        areas=(
            an_area_budget(floor_minutes=2 * HOUR),
            an_area_budget(area_id=CAREER, name="Career"),
        ),
    )
    met = a_candidate(Interval(at(0), at(2)), binding=GYM)

    assert (
        area_floor(
            a_candidate(Interval(at(2), at(2.5)), area_id=CAREER, binding=READING),
            PartialPlan.of(week).with_placed(met),
        )
        is None
    )


def test_two_areas_owing_a_floor_owe_the_sum_of_both() -> None:
    # `free` is a union of time and `owed` is a sum across Areas: one free minute can serve one
    # Area, so two Areas each owing ninety minutes owe three hours between them and three hours of
    # claimable time is exactly enough until something else takes any of it.
    week = inputs(
        **NARROW_WEEK,
        areas=(
            an_area_budget(floor_minutes=90),
            an_area_budget(area_id=CAREER, name="Career", floor_minutes=90),
        ),
    )
    state = PartialPlan.of(week)

    assert area_floor(a_candidate(Interval(at(0), at(1.5)), binding=GYM), state) is None
    rejection = area_floor(
        a_candidate(Interval(at(0), at(1.75)), binding=GYM),
        state,
    )

    assert rejection is not None
    assert rejection.detail == "Career still owes 90m of its floor, and 75m is free"


def test_the_largest_shortfall_names_the_rejection() -> None:
    # The axis the solver's own tie-breaking orders candidates by, so the clause names the Area a
    # reader would expect to hear about first.
    week = inputs(
        **NARROW_WEEK,
        areas=(
            an_area_budget(floor_minutes=90),
            an_area_budget(area_id=CAREER, name="Career", floor_minutes=2 * HOUR),
        ),
    )

    rejection = area_floor(a_candidate(Interval(at(0), at(1)), binding=GYM), PartialPlan.of(week))

    assert rejection is not None
    assert rejection.detail is not None
    assert rejection.detail.startswith("Career still owes 120m")


def test_a_placement_the_floor_figure_already_netted_is_not_netted_a_second_time() -> None:
    # The whole defect class in one comparison. `floor_minutes` arrives with the immovable
    # placements already subtracted, so counting them again would let the solver place a floor
    # short by whatever the previous solve had done. Everything below is held fixed and the only
    # thing that varies is whether the Fitness hour is one the figure already accounted for.
    fitness_hour = a_candidate(Interval(at(0), at(1)), binding=GYM)
    career_hour = a_candidate(Interval(at(1), at(2)), area_id=CAREER, binding=READING)
    areas = (
        an_area_budget(floor_minutes=2 * HOUR),
        an_area_budget(area_id=CAREER, name="Career"),
    )

    already_netted = PartialPlan.of(
        inputs(
            **NARROW_WEEK,
            areas=areas,
            live_plan=a_live_plan(a_block(binding=GYM, interval=Interval(at(0), at(1)))),
        )
    ).with_placed(fitness_hour)
    this_pass = PartialPlan.of(inputs(**NARROW_WEEK, areas=areas)).with_placed(fitness_hour)

    assert GYM in already_netted.started
    assert GYM not in this_pass.started
    refused = area_floor(career_hour, already_netted)
    assert refused is not None
    assert refused.detail == "Fitness still owes 120m of its floor, and 60m is free"
    assert area_floor(career_hour, this_pass) is None


def test_a_pinned_placement_is_the_other_half_of_the_set_the_figure_already_netted() -> None:
    # A pin is immovable for a different reason and is netted by the same rule, so the two halves of
    # that set are driven separately rather than assumed to travel together.
    fitness_hour = a_candidate(Interval(at(0), at(1)), binding=GYM)
    state = PartialPlan.of(
        inputs(
            **NARROW_WEEK,
            areas=(
                an_area_budget(floor_minutes=2 * HOUR),
                an_area_budget(area_id=CAREER, name="Career"),
            ),
            pins=(a_pin(binding=GYM, interval=Interval(at(0), at(1))),),
        )
    ).with_placed(fitness_hour)

    rejection = area_floor(
        a_candidate(Interval(at(1), at(2)), area_id=CAREER, binding=READING), state
    )

    assert rejection is not None
    assert rejection.detail == "Fitness still owes 120m of its floor, and 60m is free"


def test_occupied_time_leaves_free_capacity_whether_the_solver_may_move_it_or_not() -> None:
    # The other side of the same split: `free` counts every placement, because occupied time is
    # occupied whichever set it belongs to. Only `owed` distinguishes them.
    week = inputs(
        **NARROW_WEEK,
        areas=(
            an_area_budget(floor_minutes=2 * HOUR),
            an_area_budget(area_id=CAREER, name="Career"),
        ),
        live_plan=a_live_plan(
            a_block(binding=STANDUP, interval=Interval(at(0), at(1)), area_id=CAREER)
        ),
    )
    started = a_candidate(Interval(at(0), at(1)), area_id=CAREER, binding=STANDUP)

    rejection = area_floor(
        a_candidate(Interval(at(1), at(1.5)), area_id=CAREER, binding=READING),
        PartialPlan.of(week).with_placed(started),
    )

    assert rejection is not None
    assert rejection.detail == "Fitness still owes 120m of its floor, and 90m is free"


def test_a_candidate_carrying_no_area_is_judged_by_neither_allocation_rule() -> None:
    # The frame and an imported commitment carry no Area: one defines how much time exists and the
    # other is time the product does not own, so neither competes for a budget.
    week = inputs(**NARROW_WEEK, areas=(an_area_budget(floor_minutes=3 * HOUR),))
    commitment = a_candidate(Interval(at(0), at(2)), area_id=None, binding=STANDUP)

    assert area_floor(commitment, PartialPlan.of(week)) is None
    assert area_daily_cap(commitment, PartialPlan.of(week)) is None


def test_a_week_declaring_no_floors_refuses_nothing() -> None:
    week = inputs(**NARROW_WEEK, areas=(an_area_budget(), an_area_budget(area_id=CAREER)))

    assert (
        area_floor(a_candidate(Interval(at(0), at(3)), binding=GYM), PartialPlan.of(week)) is None
    )


# --------------------------------------------------------------------------------
# What neither rule judges: a placement nothing can move
# --------------------------------------------------------------------------------


def test_a_block_that_has_begun_is_judged_by_neither_allocation_rule() -> None:
    # Refusing it would drop a block the week already holds, and it would do so one rule before H10
    # could say the placement is the one being preserved. Both figures are deliberately arranged so
    # that a rule reading them would refuse: two hours of a one-hour cap, and a floor that cannot be
    # met from what is left.
    started = a_block(binding=GYM, interval=Interval(at(0), at(2)))
    week = inputs(
        **NARROW_WEEK,
        areas=(an_area_budget(floor_minutes=3 * HOUR, max_per_day_minutes=HOUR),),
        live_plan=a_live_plan(started),
    )
    candidate = a_candidate(Interval(at(0), at(2)), binding=GYM)
    state = PartialPlan.of(week)

    assert state.holds_immovably(candidate)
    assert area_daily_cap(candidate, state) is None
    assert area_floor(candidate, state) is None


def test_the_same_block_offered_somewhere_else_is_judged_and_counted_once() -> None:
    # A past block offered at another span reaches both rules, because H10 refuses it one row later.
    # Its minutes are already inside `floor_minutes`, so the floor owes its whole residual: netting
    # them again would report a smaller gap than the week has.
    started = a_block(binding=GYM, interval=Interval(at(0), at(1)))
    week = inputs(
        **NARROW_WEEK,
        areas=(an_area_budget(floor_minutes=2 * HOUR),),
        live_plan=a_live_plan(started),
    )
    moved = a_candidate(Interval(at(1), at(3)), binding=GYM)
    state = PartialPlan.of(week)

    assert not state.holds_immovably(moved)
    rejection = area_floor(moved, state)

    assert rejection is not None
    assert rejection.detail == "Fitness still owes 120m of its floor, and 60m is free"


def test_a_pin_and_a_block_fixed_by_derivation_are_the_other_two_the_rules_pass_over() -> None:
    # The exception is wider than the occupancy rules take, on purpose: those except the user's own
    # placement alone, because a derived buffer colliding with another IS a refusal a derivation has
    # to make. A budget is not a collision.
    transit = a_transit_block(
        anchor_id=UUID(int=51), interval=Interval(at(0), at(2)), area_id=CAREER
    )
    week = inputs(
        **NARROW_WEEK,
        areas=(
            an_area_budget(floor_minutes=3 * HOUR),
            an_area_budget(area_id=CAREER, name="Career", max_per_day_minutes=HOUR),
        ),
        shadow_blocks=(transit,),
        pins=(a_pin(binding=READING, interval=Interval(at(0), at(2))),),
    )
    state = PartialPlan.of(week)
    derived = a_candidate(
        Interval(at(0), at(2)), binding=transit.binding, area_id=CAREER, title="Leave for Uni"
    )
    pinned = a_candidate(Interval(at(0), at(2)), area_id=CAREER, binding=READING)

    for candidate in (derived, pinned):
        assert state.holds_immovably(candidate)
        assert area_daily_cap(candidate, state) is None
        assert area_floor(candidate, state) is None
