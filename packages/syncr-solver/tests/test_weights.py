"""``WeightSet``: what the objective may read, what it refuses, and what absence means.

The vocabulary crossings are the load-bearing tests here. Three lists have to name one set of
seven terms -- the weights, the breakdown's costs, and the api's own stored column names -- and
each pair is asserted in both directions, so a term cannot exist without a weight, a weight
without a term, or a stored column without either.

The api's ``P0_WEIGHTS`` is read rather than copied. That is deliberate coupling: the numbers
version 1 ships are one statement, and this suite is where a divergence between the solver's
vocabulary and the stored row's is caught. It means this member's suite needs the api member
importable, which the workspace installs.
"""

from __future__ import annotations

from dataclasses import fields

import pytest

from syncr_api.learned.config import OBJECTIVE_TERMS as STORED_TERMS
from syncr_api.learned.config import P0_WEIGHTS
from syncr_solver.weights import (
    HOURS_PER_DAY,
    OBJECTIVE_TERMS,
    TimeBucket,
    WeightError,
    WeightSet,
    bucket_of,
)
from tests.materialized_weeks import CAREER, FITNESS
from tests.objective_weeks import a_breakdown, a_fitness_curve, flat_weights, hand_tuned_weights

# Every float field a weight set carries: the seven weights, and the two parameters that shape two
# of those seven. The inventory the field-kind test is stated against.
EVERY_FLOAT = (*OBJECTIVE_TERMS, "context_switch_cost", "churn_tolerance")


def test_the_seven_weights_and_the_two_shaping_parameters_are_the_whole_float_surface() -> None:
    declared = {member.name for member in fields(WeightSet) if member.type == "float"}

    assert declared == set(EVERY_FLOAT)


def test_a_weight_set_offers_a_weight_for_exactly_the_seven_terms() -> None:
    assert set(hand_tuned_weights().term_weights()) == set(OBJECTIVE_TERMS)


def test_the_breakdowns_costs_name_exactly_the_terms_the_weights_do() -> None:
    """The two mappings are keyed on one vocabulary, in both directions."""
    assert set(a_breakdown().costs()) == set(hand_tuned_weights().term_weights())


def test_the_stored_vocabulary_and_the_objectives_are_one_list_in_the_same_order() -> None:
    """A drift here would let a fitted row carry a name the objective never reads."""
    assert STORED_TERMS == OBJECTIVE_TERMS


def test_the_shipped_weights_cover_the_seven_terms_and_the_two_parameters_and_nothing_else() -> (
    None
):
    assert set(P0_WEIGHTS) == set(EVERY_FLOAT)


def test_version_ones_weights_construct_a_weight_set_the_objective_accepts() -> None:
    """The hand-tuned row is not merely storable: it satisfies every guard below."""
    weights = hand_tuned_weights()

    assert weights.term_weights()["deadline_risk"] == P0_WEIGHTS["deadline_risk"]
    assert weights.churn_tolerance == P0_WEIGHTS["churn_tolerance"]
    assert weights.time_of_day_fitness == {}
    assert weights.skip_probability == {}


def test_deadline_risk_carries_the_highest_weight_of_the_seven() -> None:
    """The shaping the design fixes: a missed deadline is the failure the user notices."""
    weights = hand_tuned_weights().term_weights()

    assert weights["deadline_risk"] == max(weights.values())
    assert weights["deadline_risk"] > weights["budget_deviation"]


def test_no_multiplier_of_a_duration_is_reachable_from_a_weight_set() -> None:
    """``duration_multiplier`` is applied by the assembler, so the objective holds none.

    Absent rather than unread: a number the objective cannot reach is a number it cannot apply,
    and this is the structural half of that rule. The api's own ``DurationMultipliers`` reads the
    same stored row for the field this type does not carry.
    """
    declared = {member.name for member in fields(WeightSet)}

    assert "duration_multiplier" not in declared
    with pytest.raises(TypeError):
        WeightSet(**{**P0_WEIGHTS, "duration_multiplier": {FITNESS: 1.2}})  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------
# What a weight set refuses
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("term", OBJECTIVE_TERMS)
def test_a_negative_weight_is_refused_for_every_term(term: str) -> None:
    with pytest.raises(WeightError, match="at or above zero"):
        hand_tuned_weights(**{term: -0.1})


@pytest.mark.parametrize("term", OBJECTIVE_TERMS)
def test_a_non_finite_weight_is_refused_for_every_term(term: str) -> None:
    with pytest.raises(WeightError, match="at or above zero"):
        hand_tuned_weights(**{term: float("inf")})


def test_a_weight_of_zero_is_accepted_because_silencing_a_term_is_a_choice() -> None:
    assert hand_tuned_weights(churn=0.0).term_weights()["churn"] == 0.0


def test_a_negative_price_for_an_area_change_is_refused() -> None:
    with pytest.raises(WeightError, match="context_switch_cost"):
        hand_tuned_weights(context_switch_cost=-1.0)


@pytest.mark.parametrize("tolerance", [0.0, -1.0, float("nan")])
def test_a_churn_tolerance_at_or_below_zero_is_refused(tolerance: float) -> None:
    """It divides, so zero is not a tolerance: a user who absorbs nothing carries a high weight."""
    with pytest.raises(WeightError, match="churn_tolerance"):
        hand_tuned_weights(churn_tolerance=tolerance)


def test_a_fitted_curve_missing_an_hour_is_refused_rather_than_read_short() -> None:
    with pytest.raises(WeightError, match=f"{HOURS_PER_DAY} hours"):
        hand_tuned_weights(time_of_day_fitness={FITNESS: (1.0,) * 23})


@pytest.mark.parametrize("value", [-0.1, 1.1, float("inf")])
def test_a_fitted_fitness_outside_zero_to_one_is_refused(value: float) -> None:
    with pytest.raises(WeightError, match="fitted share runs from 0 to 1"):
        hand_tuned_weights(time_of_day_fitness={FITNESS: a_fitness_curve(at_hour=3, value=value)})


@pytest.mark.parametrize("value", [-0.1, 1.1])
def test_a_fitted_skip_probability_outside_zero_to_one_is_refused(value: float) -> None:
    with pytest.raises(WeightError, match="fitted share runs from 0 to 1"):
        hand_tuned_weights(skip_probability={(FITNESS, TimeBucket.MORNING): value})


def test_asking_for_a_weight_by_a_name_the_objective_does_not_have_is_refused() -> None:
    with pytest.raises(WeightError, match="seven terms"):
        hand_tuned_weights().weight_of("duration_multiplier")


def test_the_maps_are_copied_so_a_caller_cannot_change_what_a_solve_ran_under() -> None:
    curves = {FITNESS: a_fitness_curve(at_hour=9, value=0.5)}
    weights = hand_tuned_weights(time_of_day_fitness=curves)

    curves[CAREER] = a_fitness_curve(at_hour=9, value=0.0)

    assert weights.fitness_at(CAREER, 9) is None


# --------------------------------------------------------------------------------------
# Absence, which is how a maturity gate is expressed
# --------------------------------------------------------------------------------------


def test_an_unfitted_area_answers_nothing_rather_than_a_neutral_number() -> None:
    """``None`` rather than a default, so a caller states what an unfitted Area costs."""
    weights = flat_weights()

    assert weights.fitness_at(FITNESS, 9) is None
    assert weights.skip_at(FITNESS, TimeBucket.MORNING) is None


def test_a_parameter_fitted_at_zero_is_a_value_and_not_an_absence() -> None:
    weights = flat_weights(
        time_of_day_fitness={FITNESS: a_fitness_curve(at_hour=9, value=0.0)},
        skip_probability={(FITNESS, TimeBucket.MORNING): 0.0},
    )

    assert weights.fitness_at(FITNESS, 9) == 0.0
    assert weights.skip_at(FITNESS, TimeBucket.MORNING) == 0.0


# --------------------------------------------------------------------------------------
# The time buckets
# --------------------------------------------------------------------------------------


def test_the_three_buckets_partition_every_hour_a_block_can_start_in() -> None:
    """Total and single-valued, because a probability keyed on a bucket needs one bucket."""
    assigned = [bucket_of(hour) for hour in range(HOURS_PER_DAY)]

    assert len(assigned) == HOURS_PER_DAY
    assert set(assigned) == set(TimeBucket)


def test_each_bucket_holds_a_contiguous_stretch_of_the_day() -> None:
    boundaries = [
        hour for hour in range(1, HOURS_PER_DAY) if bucket_of(hour) is not bucket_of(hour - 1)
    ]

    assert boundaries == [12, 17]


@pytest.mark.parametrize(
    ("hour", "expected"),
    [
        (0, TimeBucket.MORNING),
        (2, TimeBucket.MORNING),
        (11, TimeBucket.MORNING),
        (12, TimeBucket.AFTERNOON),
        (16, TimeBucket.AFTERNOON),
        (17, TimeBucket.EVENING),
        (23, TimeBucket.EVENING),
    ],
)
def test_the_bucket_of_an_hour(hour: int, expected: TimeBucket) -> None:
    assert bucket_of(hour) is expected


@pytest.mark.parametrize("hour", [-1, HOURS_PER_DAY, 99])
def test_an_hour_no_local_day_has_is_refused(hour: int) -> None:
    with pytest.raises(WeightError, match="hour of a local day"):
        bucket_of(hour)
