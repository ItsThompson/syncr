"""``evaluate`` and the breakdown it returns: the total, the dominant term, and the guards.

This file is about the breakdown as a value and about the composition that builds it. The seven
terms' own arithmetic is in ``test_objective_terms.py``, and what the module may read is in
``test_objective_boundary.py``.

The boundaries a scoring function has are all here: a week with nothing in it, a term at its
maximum, two plans that tie, a total made of one term and a total made of seven, and every figure
that could go negative.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

import pytest

from syncr_domain.identity import BindingRef
from syncr_domain.plan import PlanError
from syncr_solver.inputs import ChurnBaseline
from syncr_solver.objective import ObjectiveBreakdown, evaluate
from syncr_solver.terms import StalenessInput, StalenessSplit
from syncr_solver.weights import OBJECTIVE_TERMS
from tests.materialized_weeks import (
    CAREER,
    FITNESS,
    NOW,
    WEEK,
    a_block,
    a_live_plan,
    at,
    between,
    inputs,
)
from tests.objective_weeks import (
    A_HABIT,
    A_REVISION,
    A_TASK,
    ANOTHER_TASK,
    a_breakdown,
    a_budget,
    a_plan_for,
    a_preference,
    a_window,
    an_eligible_task,
    an_occurrence,
    flat_weights,
    hand_tuned_weights,
    raw_breakdown,
)

if TYPE_CHECKING:
    from uuid import UUID

    from syncr_domain.plan import Block, PlanDocument
    from syncr_solver.inputs import SolveInputs


def a_task_block(
    *, task_id: UUID = A_TASK, start: float = 10, end: float = 11, day: int = 0
) -> Block:
    return a_block(
        binding=BindingRef.for_task(task_id),
        interval=between(start, end, day=day),
        area_id=FITNESS,
    )


def an_occurrence_block(*, start: float = 10) -> Block:
    """One block placed for a habit occurrence, in the Fitness Area."""
    return a_block(
        binding=BindingRef.for_habit(A_HABIT, index=0),
        interval=between(start, start + 0.5),
        area_id=FITNESS,
        title="Gym",
    )


# --------------------------------------------------------------------------------------
# The breakdown's own arithmetic
# --------------------------------------------------------------------------------------


def test_the_breakdown_carries_exactly_the_seven_costs() -> None:
    floats = {
        member.name for member in dataclasses.fields(ObjectiveBreakdown) if member.type == "float"
    }

    assert floats == set(OBJECTIVE_TERMS)
    assert len(OBJECTIVE_TERMS) == 7


def test_the_total_is_the_sum_of_the_seven() -> None:
    breakdown = a_breakdown(deadline_risk=2.0, churn=0.5, staleness=0.25)

    assert breakdown.total() == pytest.approx(2.75)


def test_the_dominant_term_is_the_one_carrying_the_largest_cost() -> None:
    breakdown = a_breakdown(deadline_risk=0.5, budget_deviation=2.0, churn=1.0)

    assert breakdown.dominant_term() == "budget_deviation"
    assert breakdown.share_of("budget_deviation") == pytest.approx(2.0 / 3.5)


def test_a_plan_that_costs_nothing_names_no_dominant_term() -> None:
    """A name at a share of zero would state a dominant cost nothing computed."""
    breakdown = a_breakdown()

    assert breakdown.total() == 0.0
    assert breakdown.dominant_term() is None
    assert breakdown.share_of("churn") == 0.0


def test_a_tie_between_two_terms_is_broken_by_the_vocabularys_own_order() -> None:
    """Deterministic, so the same plan always names the same term.

    Without it the answer would depend on a mapping's iteration order, and the reason panel would
    name a different term on two evaluations of one plan.
    """
    breakdown = a_breakdown(budget_deviation=1.0, staleness=1.0)

    assert breakdown.dominant_term() == "budget_deviation"
    assert OBJECTIVE_TERMS.index("budget_deviation") < OBJECTIVE_TERMS.index("staleness")


def test_a_total_carried_by_one_term_gives_it_the_whole_share() -> None:
    breakdown = a_breakdown(fragmentation=4.0)

    assert breakdown.share_of("fragmentation") == pytest.approx(1.0)
    assert sum(breakdown.share_of(term) for term in OBJECTIVE_TERMS) == pytest.approx(1.0)


def test_the_shares_of_the_seven_sum_to_one_whenever_anything_costs_anything() -> None:
    breakdown = a_breakdown(
        deadline_risk=1.5,
        budget_deviation=0.25,
        time_of_day_misfit=0.125,
        fragmentation=3.0,
        churn=0.5,
        context_switch=0.75,
        staleness=2.0,
    )

    assert sum(breakdown.share_of(term) for term in OBJECTIVE_TERMS) == pytest.approx(1.0)


def test_a_share_of_a_term_the_objective_does_not_have_is_refused() -> None:
    with pytest.raises(PlanError, match="seven terms"):
        a_breakdown().share_of("duration_multiplier")


@pytest.mark.parametrize("term", OBJECTIVE_TERMS)
def test_a_negative_cost_is_refused_for_every_term(term: str) -> None:
    """It would pay the plan for what the term measures, and could hide a cost in a total."""
    with pytest.raises(PlanError, match="at or above zero"):
        a_breakdown(**{term: -0.5})


@pytest.mark.parametrize("term", OBJECTIVE_TERMS)
def test_a_non_finite_cost_is_refused_for_every_term(term: str) -> None:
    with pytest.raises(PlanError, match="at or above zero"):
        a_breakdown(**{term: float("nan")})


def test_a_charged_churn_with_no_baseline_is_refused() -> None:
    """A cost the reason record could not explain, which is what a dropped baseline would be."""
    with pytest.raises(PlanError, match="difference from the plan"):
        raw_breakdown(churn=1.0)


def test_a_charged_staleness_naming_neither_input_is_refused() -> None:
    with pytest.raises(PlanError, match="names neither input"):
        raw_breakdown(staleness=1.0)


def test_a_charged_staleness_with_a_split_that_names_one_is_accepted() -> None:
    breakdown = dataclasses.replace(
        a_breakdown(),
        staleness=1.0,
        staleness_split=StalenessSplit(cadence_minutes=30, due_minutes=30),
    )

    assert breakdown.staleness_split.dominant() is StalenessInput.CADENCE


def test_a_charged_churn_with_a_baseline_that_names_a_plan_is_accepted() -> None:
    breakdown = dataclasses.replace(
        a_breakdown(),
        churn=1.0,
        churn_baseline=ChurnBaseline.approved(A_REVISION, NOW, a_live_plan()),
    )

    assert breakdown.churn_baseline.is_measured is True


# --------------------------------------------------------------------------------------
# The composition: every weight reaches its own term and no other
# --------------------------------------------------------------------------------------


def a_week_where_every_term_fires() -> SolveInputs:
    """One week that charges all seven, so the composition can be checked term by term."""
    return inputs(
        span=between(9, 17),
        eligible_tasks=(
            an_eligible_task(remaining_minutes=240, deadline=at(16), min_chunk_minutes=60),
        ),
        areas=(a_budget(target_minutes=600), a_budget(area_id=CAREER, target_minutes=60)),
        habit_occurrences=(an_occurrence(minutes=60), an_occurrence(index=1, minutes=60)),
        preferences=(a_preference(windows=(a_window(6, 8),), preferred_duration_minutes=180),),
        churn_baseline=ChurnBaseline.approved(A_REVISION, NOW, a_live_plan(a_task_block())),
    )


def a_plan_that_charges_every_term() -> PlanDocument:
    """A plan charging all seven, and **holding a tie**: two Area blocks over one interval.

    The tie is what lets the permutation test below draw the case it exists to catch. Two blocks
    of different Areas over one span is a legitimate week, because a user-authored overlap is
    preserved: that is what H4 binds and what `minutes_in` unions for. It is also the only shape in
    which the identity that makes `in_start_order` total can be observed, since without a tie every
    permutation of the blocks already sorts to one order.
    """
    return a_live_plan(
        a_task_block(start=9, end=10),
        a_block(
            binding=BindingRef.for_task(ANOTHER_TASK),
            interval=between(10.5, 11),
            area_id=CAREER,
            title="Dissertation",
        ),
        an_occurrence_block(start=10.5),
    )


def test_every_term_is_charged_on_a_week_that_drives_all_seven() -> None:
    breakdown = evaluate(
        a_plan_that_charges_every_term(),
        inputs=a_week_where_every_term_fires(),
        weights=flat_weights(context_switch_cost=60.0),
    )

    silent = [term for term, cost in breakdown.costs().items() if cost == 0]

    assert silent == []


@pytest.mark.parametrize("term", OBJECTIVE_TERMS)
def test_a_weight_of_zero_silences_its_own_term_and_no_other(term: str) -> None:
    """The composition pairs each weight with one term, asserted seven times over.

    A transposed pair would silence the wrong term, which no single-term test could see.
    """
    week = a_week_where_every_term_fires()
    plan = a_plan_that_charges_every_term()
    charged = evaluate(plan, inputs=week, weights=flat_weights(context_switch_cost=60.0)).costs()

    silenced = evaluate(
        plan,
        inputs=week,
        weights=flat_weights(context_switch_cost=60.0, **{term: 0.0}),
    ).costs()

    assert silenced[term] == 0.0
    assert charged[term] > 0
    assert {name: cost for name, cost in silenced.items() if name != term} == {
        name: cost for name, cost in charged.items() if name != term
    }


@pytest.mark.parametrize("term", OBJECTIVE_TERMS)
def test_doubling_one_weight_doubles_its_own_cost_and_no_other(term: str) -> None:
    week = a_week_where_every_term_fires()
    plan = a_plan_that_charges_every_term()
    once = evaluate(plan, inputs=week, weights=flat_weights(context_switch_cost=60.0)).costs()

    twice = evaluate(
        plan, inputs=week, weights=flat_weights(context_switch_cost=60.0, **{term: 2.0})
    ).costs()

    assert twice[term] == pytest.approx(2 * once[term])
    for name, cost in once.items():
        if name != term:
            assert twice[name] == pytest.approx(cost)


def test_the_breakdown_carries_the_baseline_the_week_was_evaluated_against() -> None:
    week = a_week_where_every_term_fires()

    breakdown = evaluate(
        a_plan_that_charges_every_term(), inputs=week, weights=hand_tuned_weights()
    )

    assert breakdown.churn_baseline is week.churn_baseline


# --------------------------------------------------------------------------------------
# Purity, determinism, and the one-week guard
# --------------------------------------------------------------------------------------


def test_two_evaluations_of_one_plan_are_equal() -> None:
    """Pure: no clock, no randomness, no accumulated state between calls.

    What lets the local search accept only strict improvements without a tolerance.
    """
    week = a_week_where_every_term_fires()
    plan = a_plan_that_charges_every_term()

    first = evaluate(plan, inputs=week, weights=hand_tuned_weights())
    second = evaluate(plan, inputs=week, weights=hand_tuned_weights())

    assert first == second


def test_permuting_the_order_of_every_input_list_changes_no_cost() -> None:
    """Including the order of the plan's own blocks, over a plan that HOLDS A TIE.

    The tie is the point. Two blocks equal on span are the only case in which an ordering key can
    be ambiguous, so a week without one cannot distinguish a total order from a stable sort of a
    partial one, and this test would pass whatever `in_start_order` keyed on. Measured: with the
    identity dropped from that key, the plan below costs 0.125 forward and 0.250 reversed.
    """
    week = a_week_where_every_term_fires()
    reversed_week = dataclasses.replace(
        week,
        eligible_tasks=tuple(reversed(week.eligible_tasks)),
        areas=tuple(reversed(week.areas)),
        habit_occurrences=tuple(reversed(week.habit_occurrences)),
        preferences=tuple(reversed(week.preferences)),
    )
    plan = a_plan_that_charges_every_term()
    shuffled = dataclasses.replace(plan, blocks=tuple(reversed(plan.blocks)))
    # A price that the gaps in this plan do not absorb whole. At version 1's one minute the only
    # pairs charging anything are the abutting ones, and both orders hold exactly one of those, so
    # the tie below would be invisible: the fixture would hold its case and the weights would hide
    # it. Measured under the mutation with this price: 90/480 forward against 60/480 reversed.
    weights = flat_weights(context_switch_cost=60.0)

    assert _a_tie_exists_in(plan), "the fixture must hold two Area blocks over one interval"
    assert evaluate(plan, inputs=week, weights=weights) == evaluate(
        shuffled, inputs=reversed_week, weights=weights
    )


def _a_tie_exists_in(plan: PlanDocument) -> bool:
    """Whether two of this plan's Area-carrying blocks cover one interval.

    Asserted rather than assumed, because the invariance above is only about ties and a fixture that
    lost its tie would leave the test passing while measuring nothing. That is ticket 29's failure
    mode, and this is the cheapest form of the check that catches it.
    """
    spans = [block.interval for block in plan.blocks if block.area_id is not None]
    return len(spans) != len(set(spans))


def test_two_plans_that_cost_the_same_are_reported_as_costing_the_same() -> None:
    """A tie is a tie. Ordering two equal candidates is the comparator's job, not this module's."""
    week = inputs(span=between(9, 17), areas=(a_budget(target_minutes=120),))
    morning = a_live_plan(a_task_block(start=9, end=10))
    afternoon = a_live_plan(a_task_block(start=15, end=16))

    assert (
        evaluate(morning, inputs=week, weights=hand_tuned_weights()).total()
        == evaluate(afternoon, inputs=week, weights=hand_tuned_weights()).total()
    )


def test_a_plan_cannot_be_scored_against_another_weeks_inputs() -> None:
    with pytest.raises(PlanError, match="resolved for one specific week"):
        evaluate(a_plan_for(WEEK.following()), inputs=inputs(), weights=hand_tuned_weights())


def test_the_costs_mapping_is_the_shape_a_revision_stores() -> None:
    """``dict[str, float]``, which is what the revision column and an edit event carry."""
    costs = evaluate(
        a_plan_that_charges_every_term(),
        inputs=a_week_where_every_term_fires(),
        weights=hand_tuned_weights(),
    ).costs()

    assert list(costs) == list(OBJECTIVE_TERMS)
    assert all(isinstance(cost, float) for cost in costs.values())
