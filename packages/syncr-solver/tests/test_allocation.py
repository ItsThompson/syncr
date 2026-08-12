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

from syncr_domain.feasibility import ShortfallKind, probe
from syncr_domain.identity import BindingRef
from syncr_domain.intervals import Interval
from syncr_domain.weeks import LOCAL_MIDNIGHT, IsoWeek
from syncr_domain.zones import to_instant
from syncr_solver.allocation import area_daily_cap, area_floor
from syncr_solver.constraints import ConstraintCheck, ConstraintRule
from syncr_solver.rules import HARD_RULES
from syncr_solver.state import PartialPlan, Placement
from tests.materialized_weeks import (
    CAREER,
    FITNESS,
    MONDAY_MIDNIGHT,
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

# A third Area, so the largest-unmet-floor tie-break has something to order. Its identity sorts
# after both declared ones, which is what makes the tie test read the order rather than the input.
STUDY = UUID("00000000-0000-4000-8000-000000000003")

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

# Half an hour wider, 210 claimable minutes, which is what lets a week arrive short by an exact
# figure while each of its floors still fits on its own: 200 and 30 against 210.
WIDER_WEEK: dict[str, object] = {
    "off_plan": (an_off_plan_period(interval=Interval(at(3.5), at(0, day=7))),)
}


def a_week_arriving_twenty_minutes_short(*, fitness_floor: int = 200) -> PartialPlan:
    """210 claimable minutes against a 200-minute Fitness floor and a 30-minute Career one.

    Both floors fit on their own and 20 minutes of the two together do not, which is the state the
    aggregate reading left every Area unprotected in. ``fitness_floor`` is the one figure the tests
    below vary, so a control week that arrives satisfiable is the same fixture with one number
    changed.
    """
    return PartialPlan.of(
        inputs(
            **WIDER_WEEK,
            areas=(
                an_area_budget(floor_minutes=fitness_floor),
                an_area_budget(area_id=CAREER, name="Career", floor_minutes=30),
            ),
        )
    )


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
    assert rejection.detail == "Fitness would be left 120m short of its floor, with 60m free"


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
    #
    # The third candidate is what makes the SUM falsifiable rather than the largest floor alone.
    # Thirty minutes of a Study Area that owes nothing leaves 150, which either floor fits inside on
    # its own and the two together do not, so a rule reading one floor at a time would admit it.
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
    assert rejection.detail == "Career would be left 90m short of its floor, with 75m free"

    jointly = area_floor(
        a_candidate(Interval(at(0), at(0.5)), area_id=STUDY, binding=STANDUP), state
    )

    assert jointly is not None
    assert jointly.detail == "Fitness would be left 90m short of its floor, with 150m free"


def test_the_largest_unmet_floor_names_the_rejection() -> None:
    # The axis the solver's own tie-breaking orders candidates by, so the clause names the Area a
    # reader would expect to hear about first. Three Areas, floors of 30, 120 and 30 against 180
    # claimable minutes, so the week ARRIVES satisfiable and it is the ninety-minute candidate that
    # makes it not. A week already short would be refused nothing, which is the rule below.
    week = inputs(
        **NARROW_WEEK,
        areas=(
            an_area_budget(floor_minutes=30),
            an_area_budget(area_id=CAREER, name="Career", floor_minutes=2 * HOUR),
            an_area_budget(area_id=STUDY, name="Study", floor_minutes=30),
        ),
    )

    rejection = area_floor(a_candidate(Interval(at(0), at(1.5)), binding=GYM), PartialPlan.of(week))

    assert rejection is not None
    assert rejection.detail == "Career would be left 120m short of its floor, with 90m free"


def test_two_areas_owing_the_same_amount_are_separated_by_their_identities() -> None:
    # `max` keeps the first of equal ones and the Areas are held in identity order, so a tie is
    # broken the same way twice rather than by whichever the inputs happened to list first.
    areas = (
        an_area_budget(area_id=CAREER, name="Career", floor_minutes=60),
        an_area_budget(area_id=STUDY, name="Study", floor_minutes=60),
    )
    forwards = inputs(**NARROW_WEEK, areas=areas)
    backwards = inputs(**NARROW_WEEK, areas=tuple(reversed(areas)))
    candidate = a_candidate(Interval(at(0), at(1.25)), binding=GYM)

    named = {area_floor(candidate, PartialPlan.of(week)) for week in (forwards, backwards)}

    assert len(named) == 1
    rejection = named.pop()
    assert rejection is not None
    assert rejection.detail == "Career would be left 60m short of its floor, with 105m free"


def test_a_week_that_arrives_short_of_its_floors_refuses_nothing() -> None:
    # Infeasibility is a notice rather than a failure: the product raises, warns and allows, and a
    # week with nothing in it is not something the user can approve. The candidate takes nothing
    # from anyone, the deficit is 60 minutes before it and 60 after, and the absolute reading
    # refused it while naming the shortfall it reduces.
    week = inputs(
        **NARROW_WEEK,
        areas=(
            an_area_budget(floor_minutes=4 * HOUR),
            an_area_budget(area_id=CAREER, name="Career"),
        ),
    )
    state = PartialPlan.of(week)

    assert state.discretionary().total_minutes() == 3 * HOUR
    assert area_floor(a_candidate(Interval(at(0), at(1)), binding=GYM), state) is None
    assert (
        area_floor(a_candidate(Interval(at(0), at(1)), area_id=CAREER, binding=READING), state)
        is None
    )


def test_a_floor_a_placement_nothing_can_move_made_unreachable_refuses_nothing_after_it() -> None:
    # The same rule, reached the other way. A pin the user put inside a narrow week can take the
    # capacity a floor needed, and the pin is honoured. What follows is a week that cannot meet its
    # floor through no choice of the solver's, so H9 has nothing left to protect.
    week = inputs(
        **NARROW_WEEK,
        areas=(
            an_area_budget(floor_minutes=3 * HOUR),
            an_area_budget(area_id=CAREER, name="Career"),
        ),
        pins=(a_pin(binding=READING, interval=Interval(at(0), at(2))),),
    )
    pinned = a_candidate(Interval(at(0), at(2)), area_id=CAREER, binding=READING)
    state = PartialPlan.of(week).with_placed(pinned)

    assert area_floor(a_candidate(Interval(at(2), at(3)), binding=GYM), state) is None


def test_one_areas_arriving_shortfall_leaves_every_other_areas_floor_reserved() -> None:
    # 210 claimable minutes against floors of 200 and 30: each fits on its own, the two together do
    # not, and the 20 minutes the week cannot hold is the arriving shortfall. Each floor is reserved
    # on its own rather than summed into a single gate, so that shortfall opens nothing and a Study
    # candidate taking the whole week is refused.
    #
    # The control is the same week with Fitness's floor lowered until nothing arrives short, and it
    # refuses the identical candidate. So what varies is the arriving deficit and nothing else, and
    # what it varies is the figure in the clause rather than whether there is one.
    whole_week = a_candidate(Interval(at(0), at(3.5)), area_id=STUDY, binding=READING)
    arrives_short = a_week_arriving_twenty_minutes_short()
    arrives_satisfiable = a_week_arriving_twenty_minutes_short(fitness_floor=180)

    assert arrives_short.discretionary().total_minutes() == 210
    refused = area_floor(whole_week, arrives_short)
    assert refused is not None
    assert refused.detail == "Fitness would be left 200m short of its floor, with 0m free"
    control = area_floor(whole_week, arrives_satisfiable)
    assert control is not None
    assert control.detail == "Fitness would be left 180m short of its floor, with 0m free"


def test_the_shortfall_the_rule_leaves_unprotected_is_the_one_the_verdict_reports() -> None:
    # The other half of the same week, and the reason the 20 minutes are safe to leave. The capacity
    # arithmetic the verdict is taken from reads this week and reports exactly those 20 minutes, so
    # the user is told about the part no placement can reach. What the rule tolerates is that figure
    # and nothing beyond it: Fitness may take the 180 minutes the week holds for it, and 15 minutes
    # of Study, which serves no floor at all, is refused.
    #
    # `now` is the week's own start here because the probe clips free capacity to it and the
    # claimable set this rule reads is a whole-week denominator that does not.
    week = inputs(
        **WIDER_WEEK,
        now=MONDAY_MIDNIGHT,
        areas=(
            an_area_budget(floor_minutes=200),
            an_area_budget(area_id=CAREER, name="Career", floor_minutes=30),
        ),
    )
    state = PartialPlan.of(week)

    reported = probe(week.for_probe()).shortfalls

    assert [(one.kind, one.minutes) for one in reported] == [
        (ShortfallKind.FLOORS_EXCEED_CAPACITY, 20)
    ]
    assert area_floor(a_candidate(Interval(at(0), at(3)), binding=GYM), state) is None
    refused = area_floor(
        a_candidate(Interval(at(0), at(0.25)), area_id=STUDY, binding=STANDUP), state
    )
    assert refused is not None
    assert refused.detail == "Fitness would be left 200m short of its floor, with 195m free"


def test_a_candidate_of_one_area_is_refused_over_another_areas_reservation() -> None:
    # A candidate naming Career on the same week, and Career's own floor is not what refuses it:
    # Fitness's 200 minutes are reserved whatever Career is doing with its 30. Under one summed
    # shortfall this candidate took all 210 minutes and no rule had anything to say.
    refused = area_floor(
        a_candidate(Interval(at(0), at(3.5)), area_id=CAREER, binding=READING),
        a_week_arriving_twenty_minutes_short(),
    )

    assert refused is not None
    assert refused.detail == "Fitness would be left 200m short of its floor, with 0m free"


def test_the_area_arriving_short_places_what_the_week_holds_and_not_another_areas_floor() -> None:
    # The other half of the same week: the 20 minutes nobody can place is a shortfall the verdict
    # reports, and no refusal here is taken over it. Fitness may place 180 of its 200 minutes, which
    # is everything the week has once Career's 30 are reserved, and the rule allows all of it. The
    # 181st minute is Career's, so the candidate that takes the whole week is refused and the clause
    # names Career rather than the shortfall Fitness arrived with.
    state = a_week_arriving_twenty_minutes_short()

    assert area_floor(a_candidate(Interval(at(0), at(3)), binding=GYM), state) is None
    refused = area_floor(a_candidate(Interval(at(0), at(3.5)), binding=GYM), state)
    assert refused is not None
    assert refused.detail == "Career would be left 30m short of its floor, with 0m free"


def test_a_floor_the_week_arrived_with_no_room_for_is_the_only_one_left_unprotected() -> None:
    # Fitness declares 300 minutes of a 210-minute week, so no sequence of placements can meet that
    # floor and there is nothing here to protect: 180 minutes of the time Fitness would have used
    # is taken by Study and nothing refuses it. Career's 30 minutes fit, so they are still
    # reserved, and the candidate that would leave Career short is refused by name.
    state = a_week_arriving_twenty_minutes_short(fitness_floor=300)
    unprotected = a_candidate(Interval(at(0), at(3)), area_id=STUDY, binding=READING)
    over_career = a_candidate(Interval(at(0), at(3.5)), area_id=STUDY, binding=READING)

    assert area_floor(unprotected, state) is None
    refused = area_floor(over_career, state)
    assert refused is not None
    assert refused.detail == "Career would be left 30m short of its floor, with 0m free"


def test_a_reservation_outlives_the_candidate_that_takes_the_arriving_deficit_up() -> None:
    # Which floors are reserved is decided by the room the week ARRIVED with rather than by the room
    # in front of the candidate, and this is the difference between the two. Career's 30 minutes are
    # placed, which the rule allows because it leaves the shortfall at the 20 minutes it found.
    # Fitness's 200 now exceed the 180 that remain, so a reservation read off the state in front of
    # it would drop Fitness here and let the rest of the week go anywhere: the same 20-minute
    # deficit, reappearing one candidate later. Read off the arrival it holds, and Fitness ends 20
    # minutes short rather than 200.
    state = a_week_arriving_twenty_minutes_short()
    career_floor = a_candidate(Interval(at(0), at(0.5)), area_id=CAREER, binding=READING)

    assert area_floor(career_floor, state) is None
    refused = area_floor(
        a_candidate(Interval(at(0.5), at(1)), area_id=STUDY, binding=STANDUP),
        state.with_placed(career_floor),
    )
    assert refused is not None
    assert refused.detail == "Fitness would be left 200m short of its floor, with 150m free"


def test_the_room_a_block_fixed_by_derivation_left_is_what_decides_a_reservation() -> None:
    # A derived block is immovable for a reason of the derivation's rather than the user's, and the
    # time it takes is as unavailable to a floor as a pin's is. It is the one immovable the Area
    # figures did NOT arrive netted of, so the two predicates disagree about it, and that is what
    # this case drives: everything is held fixed and only the length derivation took varies. With 60
    # of the 180 minutes on a transit block, Fitness's 120-minute floor exactly fits what is left
    # and is reserved, so the identical Study candidate is refused. With 120 taken, 60 minutes are
    # free, that floor is unreachable however the solver places, and there is nothing here to
    # protect.
    def a_week_derivation_took(minutes: float) -> tuple[PartialPlan, Placement]:
        transit = a_transit_block(
            anchor_id=UUID(int=61),
            interval=Interval(at(0), at(minutes / HOUR)),
            area_id=CAREER,
        )
        week = inputs(
            **NARROW_WEEK,
            areas=(
                an_area_budget(floor_minutes=2 * HOUR),
                an_area_budget(area_id=CAREER, name="Career"),
            ),
            shadow_blocks=(transit,),
        )
        derived = a_candidate(
            transit.interval, area_id=CAREER, binding=transit.binding, title=transit.title
        )
        return PartialPlan.of(week).with_placed(derived), derived

    reserved, _ = a_week_derivation_took(60)
    unreachable, derived = a_week_derivation_took(120)
    study = a_candidate(Interval(at(2), at(2.25)), area_id=STUDY, binding=STANDUP)

    assert unreachable.holds(derived)
    assert not unreachable.already_netted(derived.binding)
    refused = area_floor(study, reserved)
    assert refused is not None
    assert refused.detail == "Fitness would be left 120m short of its floor, with 105m free"
    assert area_floor(study, unreachable) is None


def test_a_derived_blocks_minutes_serve_the_floor_of_the_area_that_claims_them() -> None:
    # The other answer the disagreeing placement gives, and the case above cannot see it because its
    # derived block sits in an Area with no floor. A block fixed by derivation is immovable, so the
    # arrival subtracts its time; and the Area figures did NOT arrive netted of it, so its minutes
    # count toward its own Area's floor exactly as a solver-chosen placement's would. Sixty derived
    # minutes meet Career's sixty-minute floor, which leaves Fitness's sixty owing against ninety
    # free minutes, so a thirty-minute candidate of an Area that owes nothing takes nothing from
    # anybody. Read as content the figures had already netted, Career would owe its sixty again and
    # the same candidate would be refused.
    #
    # The second arm is the control on the fixture: a candidate large enough to leave Fitness short
    # IS refused on this week, so the first arm's silence is the rule's answer rather than an empty
    # week.
    transit = a_transit_block(
        anchor_id=UUID(int=62), interval=Interval(at(0), at(1)), area_id=CAREER
    )
    week = inputs(
        **NARROW_WEEK,
        areas=(
            an_area_budget(floor_minutes=HOUR),
            an_area_budget(area_id=CAREER, name="Career", floor_minutes=HOUR),
        ),
        shadow_blocks=(transit,),
    )
    derived = a_candidate(
        transit.interval, area_id=CAREER, binding=transit.binding, title=transit.title
    )
    state = PartialPlan.of(week).with_placed(derived)

    assert state.holds(derived)
    assert not state.already_netted(derived.binding)
    assert (
        area_floor(a_candidate(Interval(at(1), at(1.5)), area_id=STUDY, binding=STANDUP), state)
        is None
    )
    refused = area_floor(a_candidate(Interval(at(1), at(3)), area_id=STUDY, binding=STANDUP), state)
    assert refused is not None
    assert refused.detail == "Fitness would be left 60m short of its floor, with 0m free"


def test_the_room_a_block_that_has_begun_left_is_what_decides_a_reservation() -> None:
    # The third way content reaches the arrival, and the one neither other case drives: a block that
    # has BEGUN is immovable for a reason of the clock's rather than the user's or the derivation's,
    # and it is held through a different index. Everything below is held fixed and only Fitness's
    # floor varies against the 120 minutes the begun hour leaves: at 120 the floor fits and is
    # reserved, so the identical Study candidate is refused; at 150 it does not fit, no placement
    # can meet it, and there is nothing here to protect.
    def a_week_with_an_hour_begun(fitness_floor: int) -> tuple[PartialPlan, Placement]:
        begun = a_block(binding=STANDUP, interval=Interval(at(0), at(1)), area_id=CAREER)
        week = inputs(
            **NARROW_WEEK,
            areas=(
                an_area_budget(floor_minutes=fitness_floor),
                an_area_budget(area_id=CAREER, name="Career"),
            ),
            live_plan=a_live_plan(begun),
        )
        started = a_candidate(begun.interval, area_id=CAREER, binding=begun.binding)
        return PartialPlan.of(week).with_placed(started), started

    reserved, started = a_week_with_an_hour_begun(2 * HOUR)
    unreachable, _ = a_week_with_an_hour_begun(150)
    study = a_candidate(Interval(at(2), at(2.5)), area_id=STUDY, binding=READING)

    assert started.binding in reserved.started
    assert started.binding not in reserved.immovable
    refused = area_floor(study, reserved)
    assert refused is not None
    assert refused.detail == "Fitness would be left 120m short of its floor, with 90m free"
    assert area_floor(study, unreachable) is None


def test_one_areas_placement_never_nets_against_another_areas_floor() -> None:
    # Each Area's floor nets that Area's own placements and nobody else's. Two floors of 120
    # minutes against 180 claimable, an hour of Career already placed and movable, and a Study
    # candidate that takes 30 more: the reserved floors owe 180 minutes between them either way, so
    # the total cannot tell the two Areas apart and the clause is what does. Fitness owes its whole
    # 120 and Career owes 60, so Fitness is the larger and the rejection names it. Pooled into one
    # figure the sum is identical and the clause names Career.
    week = inputs(
        **NARROW_WEEK,
        areas=(
            an_area_budget(floor_minutes=2 * HOUR),
            an_area_budget(area_id=CAREER, name="Career", floor_minutes=2 * HOUR),
        ),
    )
    career_hour = a_candidate(Interval(at(0), at(1)), area_id=CAREER, binding=READING)

    rejection = area_floor(
        a_candidate(Interval(at(1), at(1.5)), area_id=STUDY, binding=STANDUP),
        PartialPlan.of(week).with_placed(career_hour),
    )

    assert rejection is not None
    assert rejection.detail == "Fitness would be left 120m short of its floor, with 90m free"


def test_the_room_a_pin_left_the_week_with_is_what_decides_a_reservation() -> None:
    # A pin is content the Area figures arrived netted of, so the time it takes is time no floor
    # ever had. Everything below is held fixed and the only thing that varies is how much of the
    # week the pin took: with 60 of the 180 minutes pinned to Career, Fitness's 120-minute floor
    # exactly fits what is left and is reserved, and the identical Study candidate is refused. With
    # 90 pinned it does not fit, and nothing is left to protect.
    def pinned_for(minutes: float) -> PartialPlan:
        week = inputs(
            **NARROW_WEEK,
            areas=(
                an_area_budget(floor_minutes=2 * HOUR),
                an_area_budget(area_id=CAREER, name="Career"),
            ),
            pins=(a_pin(binding=READING, interval=Interval(at(0), at(minutes / HOUR))),),
        )
        pin = a_candidate(
            Interval(at(0), at(minutes / HOUR)), area_id=CAREER, binding=READING, title="Reading"
        )
        return PartialPlan.of(week).with_placed(pin)

    study = a_candidate(Interval(at(2), at(2.5)), area_id=STUDY, binding=STANDUP)

    refused = area_floor(study, pinned_for(60))
    assert refused is not None
    assert refused.detail == "Fitness would be left 120m short of its floor, with 90m free"
    assert area_floor(study, pinned_for(90)) is None


def test_the_clause_never_names_the_area_the_refused_block_would_have_served() -> None:
    # Provable rather than incidental, and universal now that the rule passes over any content the
    # week already holds. A candidate that reaches this rule is held nowhere, so its minutes are not
    # already inside `floor_minutes` and they count toward its own Area: that Area's unmet floor can
    # only FALL. If it is still owing afterwards then the candidate was fully absorbed, so the
    # shortfall did not rise and nothing was refused. Whatever IS refused therefore belongs to an
    # Area owing nothing, and the clause cannot name it.
    #
    # The precondition and the refusal are both asserted, because the earlier form of this test
    # skipped a candidate nothing refused and would have gone green while asserting nothing at all.
    week = inputs(
        **NARROW_WEEK,
        areas=(
            an_area_budget(floor_minutes=2 * HOUR),
            an_area_budget(area_id=CAREER, name="Career", floor_minutes=30),
        ),
    )
    state = PartialPlan.of(week)
    offered = [
        a_candidate(Interval(at(0), at(2.5)), area_id=area_id, binding=READING)
        for area_id in (FITNESS, CAREER)
    ]
    refused = [(candidate, area_floor(candidate, state)) for candidate in offered]

    assert all(not state.holds(candidate) for candidate in offered)
    assert any(rejection is not None for _, rejection in refused)
    for candidate, rejection in refused:
        if rejection is None:
            continue
        assert rejection.detail is not None
        served = next(area.name for area in state.areas if area.area_id == candidate.area_id)
        assert not rejection.detail.startswith(served)


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
    assert refused.detail == "Fitness would be left 120m short of its floor, with 60m free"
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
    assert rejection.detail == "Fitness would be left 120m short of its floor, with 60m free"


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
    assert rejection.detail == "Fitness would be left 120m short of its floor, with 90m free"


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
# What neither rule judges: content the week already holds, wherever it holds it
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

    assert state.holds(candidate)
    assert area_daily_cap(candidate, state) is None
    assert area_floor(candidate, state) is None


def test_a_block_dragged_off_the_moment_it_began_is_refused_for_that_and_not_a_budget() -> None:
    # The pass-over reads the BINDING rather than the span, and this is the reason. Both allocation
    # rules sit above H10 and H11 in the table, so bounded to the span they answered first and the
    # user who dragged a block that has already run was told about a daily cap. Nothing was dropped,
    # because H10 refuses the same candidate one row later, but the clause named the wrong thing.
    #
    # Reachable with no pin at all, which is what makes it the most user-visible of the three.
    started = a_block(binding=GYM, interval=Interval(at(0), at(1)), title="Gym")
    week = inputs(
        **NARROW_WEEK,
        areas=(an_area_budget(floor_minutes=2 * HOUR, max_per_day_minutes=HOUR),),
        live_plan=a_live_plan(started),
    )
    dragged = a_candidate(Interval(at(1), at(3)), binding=GYM, title="Gym")
    state = PartialPlan.of(week)

    assert state.holds(dragged)
    assert area_daily_cap(dragged, state) is None
    assert area_floor(dragged, state) is None

    reported = ConstraintCheck(HARD_RULES).check(dragged, state)
    assert reported is not None
    assert (reported.rule, reported.detail) == (ConstraintRule.PAST_BLOCK, "Gym")


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
        assert state.holds(candidate)
        assert area_daily_cap(candidate, state) is None
        assert area_floor(candidate, state) is None
