"""The seven objective terms, one at a time, each isolated from the other six.

Every test here drives ONE term and asserts the other six cost nothing, through
:func:`only_charges`. That is what makes each figure attributable: a week where two terms fire is
a week where a wrong answer in one can be absorbed by the other, and the fixtures start from a
week in which all seven are zero so a test states only what it drives.

**The weights are the shipped ones, not invented numbers.** ``hand_tuned_weights`` is built from
the api's own ``P0_WEIGHTS``, so a test asserting how two terms trade off is asserting it about
version 1's actual weights. ``flat_weights`` puts every weight at one, which is what a test of a
term's own arithmetic uses: with the weight at one the cost IS the raw measurement, so a figure
worked by hand in a docstring is the figure the assertion reads.

No clock, no repository and no database anywhere in this suite, because there is none in the code
it exercises.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

import pytest

from syncr_domain.feasibility import DeadlineDemand
from syncr_domain.identity import BindingRef
from syncr_domain.plan import PlanError
from syncr_domain.preferences import PreferenceOwnerKind, PreferenceStrength
from syncr_solver.constraints import HARD_CONSTRAINTS
from syncr_solver.inputs import ChurnBaseline
from syncr_solver.objective import ObjectiveBreakdown, evaluate
from syncr_solver.preferred import MISFIT_MAX, MISFIT_SOFT, MISFIT_STRONG
from syncr_solver.terms import StalenessInput
from syncr_solver.weights import OBJECTIVE_TERMS, TimeBucket
from tests.materialized_weeks import (
    CAREER,
    FITNESS,
    WEEK,
    a_block,
    a_frame_entry,
    a_live_plan,
    a_pin,
    an_area_budget,
    at,
    between,
    inputs,
    on,
    zones,
)
from tests.objective_weeks import (
    A_HABIT,
    A_MOMENT,
    A_REVISION,
    A_TASK,
    ANOTHER_HABIT,
    ANOTHER_TASK,
    SYDNEY,
    a_budget,
    a_chunk_block,
    a_fitness_curve,
    a_plan_for,
    a_plan_in,
    a_preference,
    a_window,
    an_eligible_task,
    an_occurrence,
    flat_weights,
    hand_tuned_weights,
    skip_probabilities,
)

if TYPE_CHECKING:
    from uuid import UUID

    from syncr_domain.plan import Block
    from syncr_solver.inputs import SolveInputs
    from syncr_solver.weights import WeightSet

# A revision identity for a baseline that names one. Any value: nothing here reads it.


def only_charges(breakdown: ObjectiveBreakdown, term: str) -> float:
    """The named term's cost, having asserted the other six cost nothing.

    The isolation assertion itself. Without it a test could read the figure it expects while a
    second term quietly carried half of it, which is how a term's own arithmetic stops being
    measurable.
    """
    costs = breakdown.costs()
    assert term in costs, f"{term!r} is not one of {OBJECTIVE_TERMS}"
    others = {name: cost for name, cost in costs.items() if name != term and cost != 0}
    assert others == {}, f"the fixture was meant to isolate {term!r} and also charged {others}"
    return costs[term]


def a_task_block(
    *, task_id: UUID = A_TASK, day: int = 0, start: float = 10, end: float = 11
) -> Block:
    """One block placed for a task, in the Fitness Area."""
    return a_block(
        binding=BindingRef.for_task(task_id),
        interval=between(start, end, day=day),
        area_id=FITNESS,
    )


def an_occurrence_block(*, habit_id: UUID = A_HABIT, index: int = 0, start: float = 10) -> Block:
    """One block placed for a habit occurrence, keyed by its position in the expansion."""
    return a_block(
        binding=BindingRef.for_habit(habit_id, index=index),
        interval=between(start, start + 1),
        area_id=FITNESS,
        title="Gym",
    )


# --------------------------------------------------------------------------------------
# An empty week: the boundary every term's guard is written against
# --------------------------------------------------------------------------------------


def test_a_week_with_nothing_in_it_costs_nothing_at_all() -> None:
    breakdown = evaluate(a_live_plan(), inputs=inputs(), weights=hand_tuned_weights())

    assert breakdown.costs() == dict.fromkeys(OBJECTIVE_TERMS, 0.0)
    assert breakdown.total() == 0.0
    assert breakdown.dominant_term() is None


# --------------------------------------------------------------------------------------
# deadline_risk
# --------------------------------------------------------------------------------------


def a_week_with_one_deadline(*, remaining_minutes: int = 120, day: int = 3) -> SolveInputs:
    """A week whose only cost is one task due on Thursday, with nothing else declared."""
    return inputs(
        eligible_tasks=(
            an_eligible_task(remaining_minutes=remaining_minutes, deadline=at(0, day=day)),
        )
    )


def test_deadline_risk_is_the_unplaced_share_of_what_a_deadline_demands() -> None:
    # 120 minutes due Thursday, 60 placed before it: half the demand is unplaced, and the term
    # is the square of that share, so 0.25.
    cost = only_charges(
        evaluate(
            a_live_plan(a_task_block()), inputs=a_week_with_one_deadline(), weights=flat_weights()
        ),
        "deadline_risk",
    )

    assert cost == pytest.approx(0.25)


def test_a_deadline_met_in_full_costs_nothing() -> None:
    plan = a_live_plan(a_task_block(start=10, end=12))

    breakdown = evaluate(plan, inputs=a_week_with_one_deadline(), weights=hand_tuned_weights())

    assert breakdown.deadline_risk == 0.0


def test_work_placed_after_a_deadline_does_not_meet_it() -> None:
    # The same two hours, on Friday. The demand is due Thursday, so none of it lands in time.
    plan = a_live_plan(a_task_block(day=4, start=10, end=12))

    cost = only_charges(
        evaluate(plan, inputs=a_week_with_one_deadline(), weights=flat_weights()), "deadline_risk"
    )

    assert cost == pytest.approx(1.0)


def test_a_block_straddling_a_deadline_counts_the_part_that_lands_in_time() -> None:
    # 60 minutes due at Thursday 11:00, placed 10:30 to 11:30: half of it is in time.
    week = inputs(eligible_tasks=(an_eligible_task(remaining_minutes=60, deadline=at(11, day=3)),))
    plan = a_live_plan(a_task_block(day=3, start=10.5, end=11.5))

    cost = only_charges(evaluate(plan, inputs=week, weights=flat_weights()), "deadline_risk")

    assert cost == pytest.approx(0.25)


def test_a_task_with_no_deadline_carries_no_deadline_risk_however_little_is_placed() -> None:
    week = inputs(eligible_tasks=(an_eligible_task(remaining_minutes=600),))

    breakdown = evaluate(a_live_plan(), inputs=week, weights=hand_tuned_weights())

    assert breakdown.deadline_risk == 0.0


def test_deadline_risk_grows_nonlinearly_as_the_slack_on_a_demand_runs_out() -> None:
    """Half the pressure costs a QUARTER of the cost, not half of it.

    That is what "grows nonlinearly as slack approaches zero" means as arithmetic, and it is what
    lets the term trade off against a budget deviation while slack exists and dominate when it is
    gone.
    """
    week = a_week_with_one_deadline(remaining_minutes=120)
    quarter_short = evaluate(
        a_live_plan(a_task_block(start=10, end=11.5)), inputs=week, weights=flat_weights()
    ).deadline_risk
    half_short = evaluate(
        a_live_plan(a_task_block(start=10, end=11)), inputs=week, weights=flat_weights()
    ).deadline_risk

    assert quarter_short == pytest.approx(0.0625)
    assert half_short == pytest.approx(0.25)
    # Four times the cost for twice the pressure. A linear term would give exactly two.
    assert half_short / quarter_short == pytest.approx(4.0)


def test_deadline_risk_and_budget_deviation_still_trade_off_while_slack_exists() -> None:
    """The two are not lexicographically ordered, which is the whole point of the shaping.

    A deadline ten percent short costs 10 x 0.01 = 0.1 under version 1's weights. A budget
    deviation of the same ten percent costs 3 x 0.1 = 0.3. So the budget wins, and a strict
    ordering that made any deadline risk outrank any budget deviation would be wrong.
    """
    week = inputs(
        eligible_tasks=(an_eligible_task(remaining_minutes=100, deadline=at(0, day=3)),),
        areas=(an_area_budget(target_minutes=100),),
    )
    # 90 of 100 minutes placed: the deadline is ten percent short and so is the allocation.
    plan = a_live_plan(a_task_block(start=10, end=11.5))

    breakdown = evaluate(plan, inputs=week, weights=hand_tuned_weights())

    assert breakdown.deadline_risk == pytest.approx(0.1)
    assert breakdown.budget_deviation == pytest.approx(0.3)
    assert breakdown.dominant_term() == "budget_deviation"


def test_a_deadline_with_no_slack_left_dominates_any_budget_deviation_there_can_be() -> None:
    """And with the slack gone the ordering reverses, without either weight changing.

    A wholly unplaced demand costs the deadline term its whole weight, 10. An Area given none of
    its target is the largest budget deviation one Area can have, and it costs 3.
    """
    week = inputs(
        eligible_tasks=(an_eligible_task(remaining_minutes=100, deadline=at(0, day=3)),),
        areas=(an_area_budget(target_minutes=100),),
    )

    breakdown = evaluate(a_live_plan(), inputs=week, weights=hand_tuned_weights())

    assert breakdown.deadline_risk == pytest.approx(10.0)
    assert breakdown.budget_deviation == pytest.approx(3.0)
    assert breakdown.dominant_term() == "deadline_risk"


def test_deadline_risk_reads_the_tasks_own_deadline_and_not_the_probes_demand() -> None:
    """``EligibleTask.deadline`` is the solver's field; ``deadline_demands`` is the probe's.

    They net different placement sets and the probe's is scoped per deadline, so reading it here
    would schedule a task at half its size and report no shortfall, because both sides would
    agree. The inputs below carry a probe demand and no task deadline, and the term is silent.
    """
    week = inputs(
        eligible_tasks=(an_eligible_task(remaining_minutes=600),),
        deadline_demands=(
            DeadlineDemand(
                deadline=at(0, day=3),
                remaining_minutes=600,
                area_id=FITNESS,
                labels=("Leetcode",),
            ),
        ),
    )

    breakdown = evaluate(a_live_plan(), inputs=week, weights=hand_tuned_weights())

    assert week.deadline_demands != ()
    assert breakdown.deadline_risk == 0.0


def test_a_started_block_is_not_counted_toward_a_demand_that_already_nets_it() -> None:
    """Both sides of the comparison net the same set, or one placement is credited twice.

    ``remaining_minutes`` arrives net of the started blocks and the pins. A week whose live plan
    holds a started block for the task therefore reports the demand that is LEFT, and counting
    the started block's minutes here as well would report the demand as met by work the figure
    had already subtracted.
    """
    started = a_task_block(start=8, end=9)
    week = inputs(
        now=at(12),
        eligible_tasks=(an_eligible_task(remaining_minutes=60, deadline=at(0, day=3)),),
        live_plan=a_live_plan(started),
    )

    cost = only_charges(
        evaluate(a_live_plan(started), inputs=week, weights=flat_weights()), "deadline_risk"
    )

    assert cost == pytest.approx(1.0)


def test_a_pinned_block_is_not_counted_toward_a_demand_that_already_nets_it() -> None:
    placed = a_task_block(start=14, end=15)
    week = inputs(
        eligible_tasks=(an_eligible_task(remaining_minutes=60, deadline=at(0, day=3)),),
        live_plan=a_live_plan(placed),
        pins=(a_pin(binding=placed.binding, interval=placed.interval),),
    )

    cost = only_charges(
        evaluate(a_live_plan(placed), inputs=week, weights=flat_weights()), "deadline_risk"
    )

    assert cost == pytest.approx(1.0)


def test_two_demands_are_weighed_by_how_much_work_each_owes() -> None:
    """A demand-weighted mean, so four hours late outweighs fifteen minutes late.

    Neither a maximum, which would not move when a second deadline went unmet, nor a sum, which
    would leave the term unbounded in the number of tasks rather than in how late the work is.
    """
    week = inputs(
        eligible_tasks=(
            an_eligible_task(remaining_minutes=240, deadline=at(0, day=3)),
            an_eligible_task(
                task_id=ANOTHER_TASK, remaining_minutes=60, deadline=at(0, day=3), area_id=CAREER
            ),
        )
    )
    # The 60-minute demand is met in full; the 240-minute one gets nothing.
    plan = a_live_plan(a_task_block(task_id=ANOTHER_TASK, start=10, end=11))

    cost = only_charges(evaluate(plan, inputs=week, weights=flat_weights()), "deadline_risk")

    assert cost == pytest.approx(240 / 300)


# --------------------------------------------------------------------------------------
# budget_deviation
# --------------------------------------------------------------------------------------


def test_budget_deviation_is_the_absolute_gap_from_each_areas_target() -> None:
    week = inputs(areas=(an_area_budget(target_minutes=120),))

    cost = only_charges(
        evaluate(a_live_plan(a_task_block()), inputs=week, weights=flat_weights()),
        "budget_deviation",
    )

    assert cost == pytest.approx(60 / 120)


def test_over_serving_an_area_is_a_deviation_as_much_as_under_serving_it_is() -> None:
    week = inputs(areas=(an_area_budget(target_minutes=60),))
    under = evaluate(
        a_live_plan(a_task_block(start=10, end=10.5)), inputs=week, weights=flat_weights()
    )
    over = evaluate(
        a_live_plan(a_task_block(start=10, end=11.5)), inputs=week, weights=flat_weights()
    )

    assert under.budget_deviation == pytest.approx(0.5)
    assert over.budget_deviation == pytest.approx(0.5)


def test_an_area_given_exactly_its_target_deviates_by_nothing() -> None:
    week = inputs(areas=(an_area_budget(target_minutes=60),))

    breakdown = evaluate(a_live_plan(a_task_block()), inputs=week, weights=hand_tuned_weights())

    assert breakdown.budget_deviation == 0.0


def test_the_areas_already_placed_minutes_are_not_added_to_the_plans_own() -> None:
    """The fault class this epic has found at five sites, in this term's shape.

    ``AreaBudget.placed_minutes`` counts every placement in that Area, which is what this plan's
    own blocks ARE. A week whose target is met exactly by the plan must report no deviation; a
    reading that added the two would report the Area at twice its allocation and charge a full
    target's worth of deviation on a plan that is exactly right.
    """
    week = inputs(areas=(a_budget(target_minutes=60, placed_minutes=60),))

    breakdown = evaluate(a_live_plan(a_task_block()), inputs=week, weights=hand_tuned_weights())

    assert week.areas[0].placed_minutes == 60
    assert breakdown.budget_deviation == 0.0


def test_two_blocks_of_one_area_over_one_hour_occupy_one_hour_of_it() -> None:
    """Unioned rather than summed, so a user-authored overlap is not worth twice the time."""
    week = inputs(areas=(an_area_budget(target_minutes=60),))
    plan = a_live_plan(
        a_task_block(start=10, end=11),
        an_occurrence_block(start=10),
    )

    breakdown = evaluate(plan, inputs=week, weights=hand_tuned_weights())

    assert breakdown.budget_deviation == 0.0


def test_an_area_the_inputs_declare_no_budget_for_states_no_target_to_deviate_from() -> None:
    week = inputs(areas=())

    breakdown = evaluate(a_live_plan(a_task_block()), inputs=week, weights=hand_tuned_weights())

    assert breakdown.budget_deviation == 0.0


def test_a_floor_is_read_by_no_objective_term() -> None:
    """A floor is H9. Charging a term for it as well would price one requirement twice."""
    week = inputs(areas=(an_area_budget(floor_minutes=300, target_minutes=0),))

    breakdown = evaluate(a_live_plan(), inputs=week, weights=hand_tuned_weights())

    assert week.areas[0].floor_minutes == 300
    assert week.areas[0].floor_reservation_minutes == 300
    assert breakdown.total() == 0.0


def test_a_deviation_larger_than_the_terms_own_unit_is_not_clamped() -> None:
    """The module states the three unclamped terms are deliberate. This is what pins it.

    A clamp reads as safety and removes the gradient where it matters most: an Area given ten times
    its target and one given eleven times would cost the same, so the search would have nothing to
    climb. Measured: 60 minutes of target against 600 placed reads 9.00 and against 660 reads 10.00,
    and clamped both read 1.00.
    """
    week = inputs(areas=(a_budget(target_minutes=60),))
    ten_fold = evaluate(
        a_live_plan(a_task_block(start=8, end=18)), inputs=week, weights=flat_weights()
    ).budget_deviation
    eleven_fold = evaluate(
        a_live_plan(a_task_block(start=8, end=19)), inputs=week, weights=flat_weights()
    ).budget_deviation

    assert ten_fold == pytest.approx(9.0)
    assert eleven_fold == pytest.approx(10.0)


# --------------------------------------------------------------------------------------
# time_of_day_misfit
# --------------------------------------------------------------------------------------


def test_a_block_outside_a_soft_window_is_charged_the_soft_component() -> None:
    week = inputs(
        preferences=(a_preference(windows=(a_window(6, 8),), strength=PreferenceStrength.SOFT),)
    )

    cost = only_charges(
        evaluate(a_live_plan(a_task_block()), inputs=week, weights=flat_weights()),
        "time_of_day_misfit",
    )

    assert cost == pytest.approx(MISFIT_SOFT / MISFIT_MAX)


def test_a_block_inside_its_preferred_window_is_charged_nothing() -> None:
    week = inputs(
        preferences=(a_preference(windows=(a_window(9, 12),), strength=PreferenceStrength.SOFT),)
    )

    breakdown = evaluate(a_live_plan(a_task_block()), inputs=week, weights=hand_tuned_weights())

    assert breakdown.time_of_day_misfit == 0.0


def test_a_strong_window_costs_an_order_of_magnitude_more_than_a_soft_one() -> None:
    """The one ratio between the four components that the design fixes."""
    outside = a_live_plan(a_task_block())
    soft = evaluate(
        outside,
        inputs=inputs(
            preferences=(a_preference(windows=(a_window(6, 8),), strength=PreferenceStrength.SOFT),)
        ),
        weights=flat_weights(),
    ).time_of_day_misfit
    strong = evaluate(
        outside,
        inputs=inputs(
            preferences=(
                a_preference(windows=(a_window(6, 8),), strength=PreferenceStrength.STRONG),
            )
        ),
        weights=flat_weights(),
    ).time_of_day_misfit

    assert strong / soft == pytest.approx(10.0)
    assert pytest.approx(10.0) == MISFIT_STRONG / MISFIT_SOFT


def test_neither_strength_can_leave_a_block_unscheduled() -> None:
    """A window is a cost and never a refusal, which is why H5 was withdrawn.

    The block below is outside the strongest window there is, at the worst fitted hour, and at a
    certain refusal: every component that can apply to one block, charged at once. It is still in
    the plan, the cost is finite and at the term's ceiling rather than beyond it, and no rule of the
    hard-constraint table names a preference for anything to refuse it with.
    """
    week = inputs(
        preferences=(a_preference(windows=(a_window(6, 8),), strength=PreferenceStrength.STRONG),)
    )
    plan = a_live_plan(a_task_block())

    breakdown = evaluate(
        plan,
        inputs=week,
        weights=flat_weights(
            time_of_day_fitness={FITNESS: a_fitness_curve(at_hour=10, value=0.0)},
            skip_probability=skip_probabilities(bucket=TimeBucket.MORNING, value=1.0),
        ),
    )

    assert plan.blocks[0].interval == between(10, 11)
    assert breakdown.time_of_day_misfit == pytest.approx(1.0)
    assert "preference" not in " ".join(rule.forbids for rule in HARD_CONSTRAINTS)


def test_only_one_of_the_two_declared_strengths_can_apply_to_one_block() -> None:
    """The design's formula adds a strong term to a soft term, and the two are exclusive.

    Measured against the producer rather than against the formula: the api keeps one preference per
    owner behind three unique indexes, a preference carries one strength, and an override replaces
    its Area's declaration wholly. So a block has strong windows or soft ones, never both, and the
    week below -- an Area declaring strong and the task itself declaring soft -- is charged the
    task's soft component alone. Ticket 1344 carries the correction.
    """
    week = inputs(
        preferences=(
            a_preference(windows=(a_window(6, 8),), strength=PreferenceStrength.STRONG),
            a_preference(
                owner_id=A_TASK,
                kind=PreferenceOwnerKind.TASK,
                windows=(a_window(6, 8),),
                strength=PreferenceStrength.SOFT,
            ),
        )
    )

    cost = only_charges(
        evaluate(a_live_plan(a_task_block()), inputs=week, weights=flat_weights()),
        "time_of_day_misfit",
    )

    assert cost == pytest.approx(MISFIT_SOFT / MISFIT_MAX)


def test_a_content_preference_replaces_its_areas_rather_than_adding_to_it() -> None:
    """An override replaces its Area's declaration wholly, so the two do not both charge."""
    week = inputs(
        preferences=(
            a_preference(windows=(a_window(6, 8),), strength=PreferenceStrength.STRONG),
            a_preference(
                owner_id=A_TASK,
                kind=PreferenceOwnerKind.TASK,
                windows=(a_window(9, 12),),
                strength=PreferenceStrength.STRONG,
            ),
        )
    )

    breakdown = evaluate(a_live_plan(a_task_block()), inputs=week, weights=hand_tuned_weights())

    assert breakdown.time_of_day_misfit == 0.0


def test_an_owner_that_declares_no_window_is_outside_none() -> None:
    """An empty window list is how one habit opts out of a preference its Area keeps."""
    week = inputs(preferences=(a_preference(windows=()),))

    breakdown = evaluate(a_live_plan(a_task_block()), inputs=week, weights=hand_tuned_weights())

    assert breakdown.time_of_day_misfit == 0.0


def test_a_session_running_past_its_window_happened_partly_outside_it() -> None:
    week = inputs(
        preferences=(a_preference(windows=(a_window(9, 10.5),), strength=PreferenceStrength.SOFT),)
    )

    breakdown = evaluate(a_live_plan(a_task_block()), inputs=week, weights=flat_weights())

    assert breakdown.time_of_day_misfit == pytest.approx(MISFIT_SOFT / MISFIT_MAX)


def test_the_fitted_fitness_of_an_hour_is_the_third_component() -> None:
    weights = flat_weights(time_of_day_fitness={FITNESS: a_fitness_curve(at_hour=10, value=0.25)})

    cost = only_charges(
        evaluate(a_live_plan(a_task_block()), inputs=inputs(), weights=weights),
        "time_of_day_misfit",
    )

    assert cost == pytest.approx(0.1 * 0.75 / MISFIT_MAX)


def test_the_fitted_skip_probability_is_the_fourth_component() -> None:
    weights = flat_weights(
        skip_probability=skip_probabilities(bucket=TimeBucket.MORNING, value=0.5)
    )

    cost = only_charges(
        evaluate(a_live_plan(a_task_block()), inputs=inputs(), weights=weights),
        "time_of_day_misfit",
    )

    assert cost == pytest.approx(0.1 * 0.5 / MISFIT_MAX)


def test_a_fitted_parameter_below_its_gate_is_not_applied_at_all() -> None:
    """Absence contributes nothing. It is not read as a fitness of zero, which would be the worst.

    The control is the second assertion: the same Area with a curve fitted AT zero IS charged in
    full, so the first figure is absence rather than a value that happens to cost nothing.
    """
    plan = a_live_plan(a_task_block())
    absent = evaluate(plan, inputs=inputs(), weights=flat_weights()).time_of_day_misfit
    fitted_at_zero = evaluate(
        plan,
        inputs=inputs(),
        weights=flat_weights(time_of_day_fitness={FITNESS: a_fitness_curve(at_hour=10, value=0.0)}),
    ).time_of_day_misfit

    assert absent == 0.0
    assert fitted_at_zero == pytest.approx(0.1 / MISFIT_MAX)


def test_a_curve_fitted_for_one_area_is_not_applied_to_another() -> None:
    weights = flat_weights(time_of_day_fitness={CAREER: a_fitness_curve(at_hour=10, value=0.0)})

    breakdown = evaluate(a_live_plan(a_task_block()), inputs=inputs(), weights=weights)

    assert breakdown.time_of_day_misfit == 0.0


def test_the_misfit_is_weighted_by_how_long_a_block_sits_in_the_wrong_place() -> None:
    week = inputs(
        preferences=(a_preference(windows=(a_window(6, 8),), strength=PreferenceStrength.SOFT),)
    )
    # One hour inside the window and one outside it: half the placed minutes are charged.
    plan = a_live_plan(a_task_block(start=6, end=7), an_occurrence_block(start=10))

    cost = only_charges(evaluate(plan, inputs=week, weights=flat_weights()), "time_of_day_misfit")

    assert cost == pytest.approx(0.5 * MISFIT_SOFT / MISFIT_MAX)


def test_the_hour_a_fitted_curve_is_keyed_on_is_the_users_own_hour_and_not_utc() -> None:
    """The one thing the reading states for the first time, and the only zone-sensitive figure here.

    Every other fixture in this package is Europe/London in February, which is GMT, so a local wall
    time and its UTC spelling coincide and no assertion over them can tell the two readings apart.
    Against Australia/Sydney a block at 10:00 UTC is at 21:00 locally, so a curve fitted at hour
    21 is charged and one fitted at hour 10 is not. The last assertion is the control: the same
    block in London reads the other way round, so this fails if the hour is read without a zone.
    """
    block = a_task_block()
    local = flat_weights(time_of_day_fitness={FITNESS: a_fitness_curve(at_hour=21, value=0.0)})
    utc = flat_weights(time_of_day_fitness={FITNESS: a_fitness_curve(at_hour=10, value=0.0)})
    sydney = inputs(zone_by_date=zones(zone=SYDNEY))
    charged = pytest.approx(0.1 / MISFIT_MAX)

    assert evaluate(a_plan_in(SYDNEY, block), inputs=sydney, weights=local).time_of_day_misfit == (
        charged
    )
    assert evaluate(a_plan_in(SYDNEY, block), inputs=sydney, weights=utc).time_of_day_misfit == 0.0
    assert evaluate(a_live_plan(block), inputs=inputs(), weights=utc).time_of_day_misfit == charged


def test_the_skip_bucket_is_the_users_own_part_of_the_day() -> None:
    """The second consumer of the same lookup, and the one a wrong zone silently mis-buckets.

    A 10:00 UTC block is morning in London and evening in Sydney. A Sydney tenant reading the
    morning bucket would take a probability fitted for a part of the day they were not working in.
    """
    block = a_task_block()
    evening = flat_weights(skip_probability=skip_probabilities(bucket=TimeBucket.EVENING))
    morning = flat_weights(skip_probability=skip_probabilities(bucket=TimeBucket.MORNING))
    sydney = inputs(zone_by_date=zones(zone=SYDNEY))
    charged = pytest.approx(0.1 / MISFIT_MAX)

    assert evaluate(
        a_plan_in(SYDNEY, block), inputs=sydney, weights=evening
    ).time_of_day_misfit == (charged)
    assert (
        evaluate(a_plan_in(SYDNEY, block), inputs=sydney, weights=morning).time_of_day_misfit == 0.0
    )
    assert evaluate(a_live_plan(block), inputs=inputs(), weights=morning).time_of_day_misfit == (
        charged
    )


def test_a_block_carrying_no_area_is_not_measured_against_a_window() -> None:
    """The frame defines how much time exists rather than choosing when to happen."""
    week = inputs(
        frame=(a_frame_entry(interval=between(23, 31)),),
        preferences=(a_preference(windows=(a_window(6, 8),), strength=PreferenceStrength.STRONG),),
    )
    plan = a_live_plan(
        a_block(
            binding=BindingRef.for_routine(A_HABIT, on=on(0)),
            interval=between(23, 31),
            area_id=None,
            title="Sleep",
        )
    )

    breakdown = evaluate(plan, inputs=week, weights=hand_tuned_weights())

    assert breakdown.time_of_day_misfit == 0.0


# --------------------------------------------------------------------------------------
# fragmentation
# --------------------------------------------------------------------------------------


def test_a_piece_below_its_ideal_session_is_charged_the_difference() -> None:
    week = inputs(
        eligible_tasks=(an_eligible_task(remaining_minutes=120),),
        preferences=(a_preference(preferred_duration_minutes=90),),
    )
    plan = a_live_plan(a_task_block(start=10, end=11))

    cost = only_charges(evaluate(plan, inputs=week, weights=flat_weights()), "fragmentation")

    assert cost == pytest.approx(30 / week.span.total_minutes())


def test_a_piece_at_or_above_its_ideal_session_is_charged_nothing() -> None:
    week = inputs(
        eligible_tasks=(an_eligible_task(remaining_minutes=120),),
        preferences=(a_preference(preferred_duration_minutes=60),),
    )

    breakdown = evaluate(
        a_live_plan(a_task_block(start=10, end=11)), inputs=week, weights=hand_tuned_weights()
    )

    assert breakdown.fragmentation == 0.0


def test_splitting_one_session_into_two_costs_more_than_leaving_it_whole() -> None:
    week = inputs(
        eligible_tasks=(an_eligible_task(remaining_minutes=120),),
        preferences=(a_preference(preferred_duration_minutes=120),),
    )
    whole = evaluate(
        a_live_plan(a_task_block(start=10, end=12)), inputs=week, weights=flat_weights()
    ).fragmentation
    split = evaluate(
        a_live_plan(
            a_chunk_block(index=0, of=2, interval=between(10, 11)),
            a_chunk_block(index=1, of=2, interval=between(14, 15)),
        ),
        inputs=week,
        weights=flat_weights(),
    ).fragmentation

    assert whole == 0.0
    assert split > whole


def test_the_ideal_is_capped_by_the_work_a_task_still_owes() -> None:
    """A task with forty minutes left is not charged for a ninety-minute session it cannot fill."""
    week = inputs(
        eligible_tasks=(an_eligible_task(remaining_minutes=45),),
        preferences=(a_preference(preferred_duration_minutes=90),),
    )

    breakdown = evaluate(
        a_live_plan(a_task_block(start=10, end=10.75)), inputs=week, weights=hand_tuned_weights()
    )

    assert breakdown.fragmentation == 0.0


def test_a_started_chunk_is_not_charged_against_a_demand_that_already_nets_it() -> None:
    """The netting rule again, on the term that reads the same demand for its ideal.

    ``remaining_minutes`` arrives net of the started blocks and the pins, and the ideal a piece is
    measured against is capped by it. So the pieces measured are the ones the demand still owes: an
    hour already begun was subtracted from the demand, and charging it as a short session as well
    would charge one placement against a figure that had already accounted for it.

    The control is the second reading: with ``now`` before the same block, nothing has started, the
    piece is measured, and it is charged the thirty minutes it falls short by.
    """
    started = a_task_block(start=8, end=8.5)
    week = inputs(
        now=at(12),
        eligible_tasks=(an_eligible_task(remaining_minutes=120),),
        preferences=(a_preference(preferred_duration_minutes=60),),
        live_plan=a_live_plan(started),
    )
    movable = dataclasses.replace(week, now=at(0))

    assert evaluate(a_live_plan(started), inputs=week, weights=flat_weights()).fragmentation == 0.0
    assert evaluate(
        a_live_plan(started), inputs=movable, weights=flat_weights()
    ).fragmentation == pytest.approx(30 / week.span.total_minutes())


def test_fragmentation_never_charges_for_keeping_a_piece_at_its_minimum_chunk() -> None:
    """An ideal BELOW a minimum chunk charges the minimum nothing, so nothing pushes below H7.

    The minimum chunk stays a hard constraint. This term only ever grows as a piece gets shorter,
    so no arrangement is made cheaper by cutting one smaller and the term cannot pull a placement
    under the length its content declares.
    """
    week = inputs(
        eligible_tasks=(an_eligible_task(remaining_minutes=120, min_chunk_minutes=30),),
        preferences=(a_preference(preferred_duration_minutes=15),),
    )
    at_the_minimum = evaluate(
        a_live_plan(a_task_block(start=10, end=10.5)), inputs=week, weights=flat_weights()
    ).fragmentation
    below_the_minimum = evaluate(
        a_live_plan(a_task_block(start=10, end=10.25)), inputs=week, weights=flat_weights()
    ).fragmentation

    assert at_the_minimum == 0.0
    assert below_the_minimum == 0.0


def test_a_gap_too_short_for_anything_the_week_holds_is_charged_as_unusable() -> None:
    """A 30-minute gap between two blocks, with nothing placeable shorter than 60 minutes."""
    week = inputs(
        span=between(9, 13),
        eligible_tasks=(an_eligible_task(remaining_minutes=120, min_chunk_minutes=60),),
    )
    plan = a_live_plan(
        a_chunk_block(index=0, of=2, interval=between(9, 10.5)),
        a_chunk_block(index=1, of=2, interval=between(11, 13)),
    )

    cost = only_charges(evaluate(plan, inputs=week, weights=flat_weights()), "fragmentation")

    assert cost == pytest.approx(30 / (4 * 60))


def test_a_gap_something_could_still_use_is_not_unusable() -> None:
    week = inputs(
        span=between(9, 13),
        eligible_tasks=(an_eligible_task(remaining_minutes=120, min_chunk_minutes=15),),
    )
    plan = a_live_plan(
        a_chunk_block(index=0, of=2, interval=between(9, 10.5)),
        a_chunk_block(index=1, of=2, interval=between(11, 13)),
    )

    breakdown = evaluate(plan, inputs=week, weights=hand_tuned_weights())

    assert breakdown.fragmentation == 0.0


def test_a_week_holding_no_placeable_content_leaves_no_unusable_gap() -> None:
    """Nothing could have used any gap, so no gap is a failure to use one."""
    week = inputs(span=between(9, 13))
    plan = a_live_plan(
        a_chunk_block(index=0, of=2, interval=between(9, 10.5)),
        a_chunk_block(index=1, of=2, interval=between(11, 13)),
    )

    breakdown = evaluate(plan, inputs=week, weights=hand_tuned_weights())

    assert breakdown.fragmentation == 0.0


def test_an_occurrences_smallest_length_also_bounds_what_a_gap_could_hold() -> None:
    """The inventory of what may occupy a gap is tasks AND occurrences, not tasks alone."""
    week = inputs(
        span=between(9, 13),
        habit_occurrences=(an_occurrence(minutes=15),),
        eligible_tasks=(an_eligible_task(remaining_minutes=120, min_chunk_minutes=60),),
    )
    plan = a_live_plan(
        a_chunk_block(index=0, of=2, interval=between(9, 10.5)),
        a_chunk_block(index=1, of=2, interval=between(11, 13)),
    )

    breakdown = evaluate(plan, inputs=week, weights=hand_tuned_weights())

    assert breakdown.fragmentation == 0.0


def test_fragmentation_above_the_terms_own_unit_is_not_clamped() -> None:
    """A plan cut into many pieces is worse than the whole of what the term measures.

    A short week, a long ideal session, and four pieces: each piece is charged its whole shortfall,
    so the deficits sum past the discretionary time they are divided by. A clamp would make eight
    pieces cost what four do.
    """
    week = inputs(
        span=between(9, 13),
        eligible_tasks=(an_eligible_task(remaining_minutes=240, min_chunk_minutes=15),),
        preferences=(a_preference(preferred_duration_minutes=240),),
    )
    plan = a_live_plan(
        *(
            a_chunk_block(index=index, of=4, interval=between(9 + index, 9.25 + index))
            for index in range(4)
        )
    )

    cost = only_charges(evaluate(plan, inputs=week, weights=flat_weights()), "fragmentation")

    # Four pieces of 15 minutes against a 240-minute ideal, over the 240 minutes the week holds. The
    # gaps between them are 45 minutes and the task's minimum chunk is 15, so nothing here is an
    # unusable gap: the whole figure is the split component.
    assert cost > 1.0
    assert cost == pytest.approx(4 * 225 / 240)


# --------------------------------------------------------------------------------------
# churn
# --------------------------------------------------------------------------------------


def an_approved_baseline(*blocks: Block) -> ChurnBaseline:
    """A baseline naming an approved revision, and carrying the plan it approved."""
    return ChurnBaseline.approved(A_REVISION, A_MOMENT, a_live_plan(*blocks))


def test_a_week_that_has_never_been_approved_has_zero_churn_and_says_why() -> None:
    week = inputs(churn_baseline=ChurnBaseline.never_approved())

    breakdown = evaluate(
        a_live_plan(a_task_block(start=14, end=15)), inputs=week, weights=hand_tuned_weights()
    )

    assert breakdown.churn == 0.0
    assert breakdown.churn_baseline.reason == ChurnBaseline.NEVER_APPROVED
    assert breakdown.churn_baseline.is_measured is False


def test_a_plan_identical_to_the_one_the_user_approved_has_moved_nothing() -> None:
    block = a_task_block()
    week = inputs(churn_baseline=an_approved_baseline(block))

    breakdown = evaluate(a_live_plan(block), inputs=week, weights=hand_tuned_weights())

    assert breakdown.churn_baseline.is_measured is True
    assert breakdown.churn == 0.0


def test_a_moved_block_is_churn_against_the_plan_the_user_approved() -> None:
    week = inputs(churn_baseline=an_approved_baseline(a_task_block(start=10, end=11)))

    cost = only_charges(
        evaluate(
            a_live_plan(a_task_block(start=14, end=15)),
            inputs=week,
            weights=flat_weights(churn_tolerance=1.0),
        ),
        "churn",
    )

    # One move against a tolerance of one move: exactly at the knee, which is half the unit.
    assert cost == pytest.approx(0.5)


def test_a_dropped_block_is_churn_and_an_added_one_is_not() -> None:
    """Nothing the user approved was rearranged by placing something new beside it."""
    approved = a_task_block(start=10, end=11)
    week = inputs(churn_baseline=an_approved_baseline(approved))
    dropped = evaluate(a_live_plan(), inputs=week, weights=flat_weights(churn_tolerance=1.0)).churn
    added = evaluate(
        a_live_plan(approved, an_occurrence_block(start=14)),
        inputs=week,
        weights=flat_weights(churn_tolerance=1.0),
    ).churn

    assert dropped == pytest.approx(0.5)
    assert added == 0.0


def test_a_move_and_a_drop_are_two_requirements_rather_than_one() -> None:
    """The two sets are disjoint, so they add. A maximum of the two would count the pair as one.

    Two blocks approved, one moved and one dropped: two moves against a tolerance of two, which is
    exactly the knee. Counted as the larger of the two figures instead, it would be one move at half
    the tolerance, and a plan that both moved and dropped work would read as cheap as one that only
    moved it.
    """
    moved = a_task_block(start=10, end=11)
    doomed = an_occurrence_block(start=12)
    week = inputs(churn_baseline=an_approved_baseline(moved, doomed))

    cost = evaluate(
        a_live_plan(a_task_block(start=15, end=16)),
        inputs=week,
        weights=flat_weights(churn_tolerance=2.0),
    ).churn

    assert cost == pytest.approx(0.5)


def churn_of(moves: int, weights: WeightSet) -> float:
    """What a plan costs for moving this many of the approved plan's blocks."""
    approved = tuple(an_occurrence_block(index=index, start=9) for index in range(moves))
    moved = tuple(
        an_occurrence_block(index=index, start=14 + index * 0.25) for index in range(moves)
    )
    return evaluate(
        a_live_plan(*moved),
        inputs=inputs(churn_baseline=an_approved_baseline(*approved)),
        weights=weights,
    ).churn


def test_a_high_tolerance_user_absorbs_several_moves_cheaply_and_then_objects_sharply() -> None:
    """The tolerance SHAPES the term and the weight SCALES it, which is two jobs for two numbers.

    Ten moves tolerated: three moves cost 0.083 of the term's unit, which is cheap, and twenty cost
    0.8, which is most of it. The same three moves against a tolerance of one cost 0.9, so the
    intolerant user objects where the tolerant one has not noticed.
    """
    tolerant = flat_weights(churn_tolerance=10.0)
    intolerant = flat_weights(churn_tolerance=1.0)

    assert churn_of(3, tolerant) == pytest.approx(0.09 / 1.09)
    assert churn_of(20, tolerant) == pytest.approx(4.0 / 5.0)
    assert churn_of(3, intolerant) == pytest.approx(9.0 / 10.0)
    assert churn_of(3, intolerant) > 10 * churn_of(3, tolerant)


def test_churn_rises_faster_than_the_moves_that_cause_it_around_the_tolerance() -> None:
    """Superlinear through the knee, which is what "begins to rise steeply" means."""
    weights = flat_weights(churn_tolerance=8.0)

    assert churn_of(4, weights) == pytest.approx(0.25 / 1.25)
    assert churn_of(8, weights) == pytest.approx(0.5)
    # Twice the moves for two and a half times the cost, through the knee.
    assert churn_of(8, weights) / churn_of(4, weights) == pytest.approx(2.5)


def test_churn_never_passes_the_terms_own_unit_however_much_a_plan_moves() -> None:
    """Churn is a term in this objective rather than a rival engine.

    Unbounded, the term becomes a minimal-diff engine: it would deliver a worse plan to avoid a
    change the approval gate already makes safe. Measured on a 210-block week, an unbounded square
    of the same ratio charged 4900 against a total of 7.8 for the other six terms.
    """
    intolerant = flat_weights(churn_tolerance=1.0)

    assert churn_of(50, intolerant) < 1.0
    assert churn_of(50, intolerant) > churn_of(20, intolerant)
    assert churn_of(50, intolerant) == pytest.approx(2500 / 2501)


@pytest.mark.parametrize("tolerance", [1e-300, 5e-324, 1e300, 1.7e308])
def test_the_curve_is_total_over_every_tolerance_a_weight_set_admits(tolerance: float) -> None:
    """Neither end raises, and neither reads as a cost outside the term's own unit.

    The direct form of the same curve overflows a float at a ratio of about 2e202, which a tolerance
    of a two-hundredth of a move reaches on an ordinary week.
    """
    cost = churn_of(4, flat_weights(churn_tolerance=tolerance))

    assert 0.0 <= cost <= 1.0


def test_churn_refuses_to_compare_two_documents_of_different_weeks() -> None:
    """A block's id is derived from its week, so ids across weeks never pair.

    Compared anyway, every block of the baseline would read as dropped and every block of the plan
    as an addition: a maximal churn on two plans that may be identical.
    """
    week = inputs(
        churn_baseline=ChurnBaseline.approved(A_REVISION, A_MOMENT, a_plan_for(WEEK.following()))
    )

    with pytest.raises(PlanError, match="derived from its week"):
        evaluate(a_live_plan(), inputs=week, weights=hand_tuned_weights())


# --------------------------------------------------------------------------------------
# context_switch
# --------------------------------------------------------------------------------------


def test_two_adjacent_blocks_of_different_areas_cost_the_whole_price_of_one_change() -> None:
    week = inputs(span=between(9, 13))
    plan = a_live_plan(
        a_task_block(start=9, end=10),
        a_block(
            binding=BindingRef.for_task(ANOTHER_TASK),
            interval=between(10, 11),
            area_id=CAREER,
            title="Dissertation",
        ),
    )

    cost = only_charges(
        evaluate(plan, inputs=week, weights=flat_weights(context_switch_cost=30.0)),
        "context_switch",
    )

    assert cost == pytest.approx(30 / (4 * 60))


def test_two_adjacent_blocks_of_one_area_are_no_change_at_all() -> None:
    week = inputs(span=between(9, 13))
    plan = a_live_plan(a_task_block(start=9, end=10), an_occurrence_block(start=10))

    breakdown = evaluate(plan, inputs=week, weights=flat_weights(context_switch_cost=30.0))

    assert breakdown.context_switch == 0.0


def test_the_gap_the_schedule_leaves_absorbs_the_price_of_a_change() -> None:
    week = inputs(span=between(9, 13))

    def cost_with_a_gap(gap_hours: float) -> float:
        plan = a_live_plan(
            a_task_block(start=9, end=10),
            a_block(
                binding=BindingRef.for_task(ANOTHER_TASK),
                interval=between(10 + gap_hours, 11 + gap_hours),
                area_id=CAREER,
                title="Dissertation",
            ),
        )
        return evaluate(
            plan, inputs=week, weights=flat_weights(context_switch_cost=30.0)
        ).context_switch

    assert cost_with_a_gap(0) == pytest.approx(30 / 240)
    assert cost_with_a_gap(0.25) == pytest.approx(15 / 240)
    assert cost_with_a_gap(0.5) == 0.0
    assert cost_with_a_gap(1) == 0.0


def test_the_price_of_a_change_and_the_weight_of_the_term_are_not_one_product() -> None:
    """Two numbers, two jobs. Doubling the price is not the same as doubling the weight.

    A pair with a fifteen-minute gap between them is where the two come apart: the price is in
    MINUTES and the gap absorbs it, so doubling the price charges more than twice as much while
    doubling the weight charges exactly twice as much. Collapsed into their product the two
    readings below would be equal.
    """
    week = inputs(span=between(9, 13))
    plan = a_live_plan(
        a_task_block(start=9, end=10),
        a_block(
            binding=BindingRef.for_task(ANOTHER_TASK),
            interval=between(10.25, 11.25),
            area_id=CAREER,
            title="Dissertation",
        ),
    )

    def cost(price: float, weight: float) -> float:
        return evaluate(
            plan,
            inputs=week,
            weights=flat_weights(context_switch_cost=price, context_switch=weight),
        ).context_switch

    # 30 minutes of price against 15 minutes of gap: 15 charged, once.
    assert cost(30.0, 1.0) == pytest.approx(15 / 240)
    # Twice the price against the same gap: 45 charged, which is three times as much.
    assert cost(60.0, 1.0) == pytest.approx(45 / 240)
    # Twice the weight over the same price: exactly twice as much.
    assert cost(30.0, 2.0) == pytest.approx(30 / 240)
    assert cost(60.0, 1.0) != cost(30.0, 2.0)


def test_a_night_between_two_areas_needs_no_rule_of_its_own() -> None:
    """Hours of gap absorb any price, so a day boundary is not a context switch by construction."""
    plan = a_live_plan(
        a_task_block(day=0, start=20, end=21),
        a_block(
            binding=BindingRef.for_task(ANOTHER_TASK),
            interval=between(9, 10, day=1),
            area_id=CAREER,
            title="Dissertation",
        ),
    )

    breakdown = evaluate(plan, inputs=inputs(), weights=flat_weights(context_switch_cost=60.0))

    assert breakdown.context_switch == 0.0


def test_a_block_carrying_no_area_is_not_an_area_the_user_changed_to() -> None:
    week = inputs(span=between(9, 13), frame=(a_frame_entry(interval=between(10, 11)),))
    plan = a_live_plan(
        a_task_block(start=9, end=10),
        a_block(
            binding=BindingRef.for_routine(A_HABIT, on=on(0)),
            interval=between(10, 11),
            area_id=None,
            title="Sleep",
        ),
        an_occurrence_block(start=11),
    )

    breakdown = evaluate(plan, inputs=week, weights=flat_weights(context_switch_cost=30.0))

    assert breakdown.context_switch == 0.0


def test_a_context_switch_charge_above_the_terms_own_unit_is_not_clamped() -> None:
    """A day of abutting changes at a high price costs more than the week has minutes.

    The price is in minutes and it is charged per change, so a week of many short abutting blocks in
    alternating Areas charges more than its own discretionary time. A clamp would make a plan that
    changed Area every fifteen minutes cost what one changing twice does.
    """
    week = inputs(span=between(9, 13))
    plan = a_live_plan(
        *(
            a_block(
                binding=BindingRef.for_habit(A_HABIT, index=index),
                interval=between(9 + index * 0.25, 9.25 + index * 0.25),
                area_id=FITNESS if index % 2 else CAREER,
                title="Gym",
            )
            for index in range(16)
        )
    )

    cost = only_charges(
        evaluate(plan, inputs=week, weights=flat_weights(context_switch_cost=60.0)),
        "context_switch",
    )

    # Fifteen abutting changes at 60 minutes each, over 240 minutes of week.
    assert cost > 1.0
    assert cost == pytest.approx(15 * 60 / 240)


# --------------------------------------------------------------------------------------
# staleness
# --------------------------------------------------------------------------------------


def test_an_unplaced_due_occurrence_is_staleness() -> None:
    week = inputs(habit_occurrences=(an_occurrence(minutes=60),))

    cost = only_charges(evaluate(a_live_plan(), inputs=week, weights=flat_weights()), "staleness")

    assert cost == pytest.approx(1.0)


def test_a_due_occurrence_the_plan_places_is_not_falling_behind() -> None:
    week = inputs(habit_occurrences=(an_occurrence(minutes=60),))

    breakdown = evaluate(
        a_live_plan(an_occurrence_block()), inputs=week, weights=hand_tuned_weights()
    )

    assert breakdown.staleness == 0.0
    assert breakdown.staleness_split.dominant() is None


def test_the_two_inputs_of_staleness_partition_the_weeks_occurrences() -> None:
    """A cadence item and a stuck rotation are one term, and the split says which dominated.

    The occurrence whose content came from the rotation cursor carries a variant. Every other one
    is the cadence half, so no occurrence is in both and the share cannot count one twice.
    """
    week = inputs(
        habit_occurrences=(
            an_occurrence(minutes=30),
            an_occurrence(habit_id=ANOTHER_HABIT, index=0, minutes=90, variant="Legs"),
        )
    )

    breakdown = evaluate(a_live_plan(), inputs=week, weights=flat_weights())
    split = breakdown.staleness_split

    assert split.cadence_minutes == 30
    assert split.rotation_minutes == 90
    assert split.due_minutes == 120
    assert split.cadence_minutes + split.rotation_minutes == split.due_minutes
    assert split.dominant() is StalenessInput.ROTATION
    assert breakdown.staleness == pytest.approx(1.0)


def test_the_cadence_half_can_dominate_too() -> None:
    week = inputs(
        habit_occurrences=(
            an_occurrence(minutes=90),
            an_occurrence(habit_id=ANOTHER_HABIT, index=0, minutes=30, variant="Legs"),
        )
    )

    breakdown = evaluate(a_live_plan(), inputs=week, weights=flat_weights())

    assert breakdown.staleness_split.dominant() is StalenessInput.CADENCE


def test_a_made_up_occurrence_is_counted_at_its_own_size_like_any_other() -> None:
    """Debt is applied before these inputs are built, so it needs no reading of its own."""
    week = inputs(habit_occurrences=(an_occurrence(minutes=45, is_debt=True),))

    breakdown = evaluate(a_live_plan(), inputs=week, weights=flat_weights())

    assert breakdown.staleness_split.cadence_minutes == 45
    assert breakdown.staleness == pytest.approx(1.0)


def test_an_elastic_occurrence_owes_its_smallest_legal_length() -> None:
    week = inputs(habit_occurrences=(an_occurrence(minutes=30, max_minutes=90),))

    breakdown = evaluate(a_live_plan(), inputs=week, weights=flat_weights())

    assert breakdown.staleness_split.due_minutes == 30


def test_a_week_with_no_due_occurrence_has_nothing_falling_behind() -> None:
    breakdown = evaluate(a_live_plan(), inputs=inputs(), weights=hand_tuned_weights())

    assert breakdown.staleness == 0.0
    assert breakdown.staleness_split.due_minutes == 0
