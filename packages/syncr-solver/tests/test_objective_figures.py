"""The ceilings and units the seven terms are measured against, pinned where each figure sits.

Three rules live here rather than in ``test_objective_terms.py``, which drives one term at a time
and reads every figure as a share of the week:

- the price of an Area change is charged in MINUTES against the gap the schedule already leaves, so
  the price and the term's weight are two numbers rather than one product;
- the churn curve saturates at the term's own unit over the whole tolerance range a weight set
  admits, including the two adjacent tolerances its flat guard sits between;
- the misfit ceiling counts one declared component and the two fitted ones, because a block carries
  one strength, and a block that carries two reads above the unit rather than being clamped to it.

**The absorption is read as minutes rather than as a share, which is what separates it from the
per-term assertion of the same behaviour.** ``test_objective_terms.py`` divides the same charge by
the week, so a change to the denominator reddens there and not here, and a change to the absorption
arithmetic reddens in both.

A plan that costs nothing names no dominant term. That rule is held by
``tests/test_objective.py::test_a_plan_that_costs_nothing_names_no_dominant_term`` and is not
restated here. The module matters: ``tests/test_reasons.py`` carries a case of the same name over
the reason record's clauses, and the one over the breakdown's own reading is the first.

No clock, no repository and no database, because there is none in the code below.
"""

from __future__ import annotations

import ast
import math
import sys
from typing import TYPE_CHECKING

import pytest

from syncr_domain.identity import BindingRef
from syncr_domain.preferences import PreferenceStrength
from syncr_solver.objective import evaluate
from syncr_solver.preferred import (
    MISFIT_FITTED_FITNESS,
    MISFIT_FITTED_SKIP,
    MISFIT_MAX,
    MISFIT_SOFT,
    MISFIT_STRONG,
)
from syncr_solver.reading import PlanReading
from syncr_solver.terms import _CHURN_KNEE_FLAT
from syncr_solver.weights import TimeBucket
from tests.materialized_weeks import CAREER, FITNESS, a_block, a_live_plan, between, inputs
from tests.objective_weeks import (
    ANOTHER_HABIT,
    ANOTHER_TASK,
    a_fitness_curve,
    a_preference,
    a_window,
    flat_weights,
    skip_probabilities,
)
from tests.test_objective_boundary import source_of
from tests.test_objective_terms import a_task_block, churn_of, only_charges

if TYPE_CHECKING:
    from syncr_domain.plan import Block
    from syncr_solver.inputs import ResolvedPreference

# The four-hour week the absorption is measured over. Short, so a charge in minutes is a large
# share of it and a fixture charging one change twice would be visible in either reading.
A_SHORT_WEEK_SPAN = between(9, 13)

# A quarter of an hour of gap, which is half the price the assertions below state. The one gap
# length at which doubling the price and doubling the weight give different answers.
A_GAP_THE_PRICE_OUTLASTS = 0.25


def a_career_block(*, start: float, end: float, index: int = 0) -> Block:
    """One block of a second Area, so the pair either side of it is a change the user made."""
    return a_block(
        binding=BindingRef.for_habit(ANOTHER_HABIT, index=index),
        interval=between(start, end),
        area_id=CAREER,
        title="Dissertation",
    )


def price_charged_in_minutes(*blocks: Block, price: float, weight: float = 1.0) -> float:
    """The minutes of price this plan's Area changes are charged, recovered from the term.

    The term is a share of the week's discretionary time, so the minutes are recovered by
    multiplying by the same denominator the term divided by, read off a reading of the same plan and
    the same week. That keeps the figures below in the unit the price is stated in: a change to the
    denominator moves this function's multiplier and the term alike, and only a change to the
    absorption arithmetic moves the answer.
    """
    week = inputs(span=A_SHORT_WEEK_SPAN)
    plan = a_live_plan(*blocks)
    breakdown = evaluate(
        plan,
        inputs=week,
        weights=flat_weights(context_switch_cost=price, context_switch=weight),
    )
    return only_charges(breakdown, "context_switch") * (
        PlanReading.of(plan, inputs=week).discretionary_minutes()
    )


def misfit_of_one_hour(
    *, preferences: tuple[ResolvedPreference, ...], fitted: bool = False
) -> float:
    """What one hour in the wrong part of the day costs, as a share of the misfit ceiling.

    ``fitted`` puts both fitted parameters at their worst for that Area and that hour, which is the
    only way every component the ceiling counts fires at once.
    """
    weights = (
        flat_weights(
            time_of_day_fitness={FITNESS: a_fitness_curve(at_hour=10, value=0.0)},
            skip_probability=skip_probabilities(bucket=TimeBucket.MORNING, value=1.0),
        )
        if fitted
        else flat_weights()
    )
    breakdown = evaluate(
        a_live_plan(a_task_block()), inputs=inputs(preferences=preferences), weights=weights
    )
    return only_charges(breakdown, "time_of_day_misfit")


def the_components_a_ceiling_adds(source: str) -> tuple[str, ...]:
    """The component names ``MISFIT_MAX``'s own expression adds, sorted, read off the assignment.

    Three of the four components carry the same figure, so a sum of the wrong three has the same
    value as a sum of the right three and no assertion over the figure can tell them apart. This
    reads the names instead. A ceiling spelled some other way than as a sum of names reads as no
    names at all and fails here, which is the price of pinning a composition rather than a value.
    """
    for node in ast.walk(ast.parse(source)):
        target = getattr(node, "target", None)
        if isinstance(node, ast.AnnAssign) and getattr(target, "id", "") == "MISFIT_MAX":
            return tuple(
                sorted(named.id for named in ast.walk(node.value) if isinstance(named, ast.Name))
                if node.value is not None
                else ()
            )
    raise AssertionError("the source states no MISFIT_MAX for its components to be read from")


def test_the_gap_absorbs_the_price_in_minutes_and_the_weight_scales_what_is_left() -> None:
    """The price is minutes of the week and the gap spends them, which is why it is not a scale.

    Thirty minutes of price against fifteen of gap charges the fifteen the gap could not absorb.
    Doubling the price charges forty-five, three times as much rather than twice, because the gap
    absorbs a fixed fifteen either way. Doubling the weight charges thirty, exactly twice, because a
    weight multiplies what the absorption left. Collapsed into one product the second and third
    readings would be equal, and they are asserted to differ.

    A gap the price cannot outlast charges nothing rather than paying the plan, which is the other
    edge of the same subtraction.

    The last figure is the same arithmetic per pair rather than per week: an abutting change and a
    change with fifteen minutes of gap are charged thirty and fifteen, the same forty-five that
    doubling the price charges for one pair. A reading that absorbed one gap for the whole week, or
    spent every gap against every change, would separate the two.
    """
    one_gapped_pair = (
        a_task_block(start=9, end=10),
        a_career_block(start=10 + A_GAP_THE_PRICE_OUTLASTS, end=11 + A_GAP_THE_PRICE_OUTLASTS),
    )
    one_pair_the_gap_outlasts = (
        a_task_block(start=9, end=10),
        a_career_block(start=11, end=12),
    )
    an_abutting_pair_and_a_gapped_one = (
        a_task_block(start=9, end=10),
        a_career_block(start=10, end=11),
        a_block(
            binding=BindingRef.for_task(ANOTHER_TASK),
            interval=between(11 + A_GAP_THE_PRICE_OUTLASTS, 12 + A_GAP_THE_PRICE_OUTLASTS),
            area_id=FITNESS,
            title="Leetcode",
        ),
    )

    stated_price = price_charged_in_minutes(*one_gapped_pair, price=30.0)
    doubled_price = price_charged_in_minutes(*one_gapped_pair, price=60.0)
    doubled_weight = price_charged_in_minutes(*one_gapped_pair, price=30.0, weight=2.0)
    an_hour_of_gap = price_charged_in_minutes(*one_pair_the_gap_outlasts, price=30.0)
    two_pairs = price_charged_in_minutes(*an_abutting_pair_and_a_gapped_one, price=30.0)

    assert stated_price == pytest.approx(15.0)
    assert doubled_price == pytest.approx(45.0)
    assert doubled_weight == pytest.approx(30.0)
    assert doubled_price != doubled_weight
    assert an_hour_of_gap == 0.0
    assert two_pairs == pytest.approx(45.0)


# The two tolerances either side of the flat guard's own threshold, stated as literals rather than
# derived from it: a case whose input follows the constant it is about cannot see that constant
# move. The first is the largest tolerance at which the guard does NOT fire, and the second is one
# representable step further, where squaring the inverse would overflow. The test crosses the first
# against the module's own threshold, so the pair is a measurement of where the guard sits.
_AT_THE_FLAT_GUARD = 1.3407807929942596e154
_PAST_THE_FLAT_GUARD = 1.3407807929942597e154

# Every tolerance here is passed to a real weight set, so each case also states that the value is
# one a weight set admits. The values it refuses are the other side of the same guard, at
# ``test_weights.py::test_a_churn_tolerance_at_or_below_zero_is_refused``.
A_TOLERANCE_SWEEP = (
    # The ratio itself overflows to infinity here, and the curve reads its own unit exactly rather
    # than an infinity or a NaN. The unit ATTAINED, which is not the unit passed.
    pytest.param(4, 5e-324, 1.0, id="the-smallest-admitted"),
    pytest.param(4, 1e-10, 1.0, id="a-ratio-that-overflows"),
    # Four moves at a tolerance of one move: the ratio is 4 and the cost is 1/(1 + 1/16). An
    # unbounded square of the same ratio would charge 16, which is what saturating buys instead of
    # a clamp: the cost stays inside the unit without the curve going flat.
    pytest.param(4, 1.0, 16 / 17, id="four-moves-at-one"),
    # The same four moves against a tolerance of ten: the ratio is 0.4 and the cost is 4/29.
    pytest.param(4, 10.0, 4 / 29, id="four-moves-at-ten"),
    # One move at the flat guard's threshold. The guard has NOT fired: the square of the inverse is
    # the largest finite one there is and the cost is its reciprocal, a positive subnormal.
    pytest.param(1, _AT_THE_FLAT_GUARD, 5.56268464626801e-309, id="at-the-flat-guard"),
    # One representable step further and the guard fires, because squaring the inverse would
    # overflow. Two adjacent tolerances, one on each side of the exclusion.
    pytest.param(1, _PAST_THE_FLAT_GUARD, 0.0, id="past-the-flat-guard"),
    pytest.param(4, sys.float_info.max, 0.0, id="the-largest-admitted"),
)


@pytest.mark.parametrize(("moves", "tolerance", "expected"), A_TOLERANCE_SWEEP)
def test_churn_never_passes_the_terms_own_unit_at_any_tolerance_a_weight_set_admits(
    moves: int, tolerance: float, expected: float
) -> None:
    """Churn is a term in this objective rather than a rival engine, at every shape it can take.

    The weight is one in every case, so the cost IS the measurement and the term's own unit is 1.0.
    Three regimes, all total, none of them past that unit: a ratio that overflows reads the unit
    exactly, the ordinary range reads strictly inside it, and the flat guard reads zero, because
    what would overflow below the guard is the arithmetic rather than the cost being large.

    Each case states its own figure, so a curve that changed shape while staying inside the unit is
    red here rather than absorbed by a range check. **The comparison is relative with no absolute
    floor**, because two of these figures are a subnormal and a zero: under the default absolute
    tolerance of 1e-12 either would satisfy the other, and the two adjacent tolerances the flat
    guard sits between would read alike.
    """
    cost = churn_of(moves, flat_weights(churn_tolerance=tolerance))

    assert cost == pytest.approx(expected, rel=1e-12, abs=0.0)
    assert 0.0 <= cost <= 1.0
    assert math.isfinite(cost)


def test_the_two_boundary_tolerances_are_the_ones_the_flat_guard_sits_between() -> None:
    """The threshold is a figure the sweep states as an input and the module states as a constant.

    Crossed here rather than taken from there, and in a case of its own rather than in the sweep's
    body: run once per tolerance it would redden every case alike, and the ids would stop naming the
    regime that broke.
    """
    assert _AT_THE_FLAT_GUARD == _CHURN_KNEE_FLAT
    assert math.nextafter(_CHURN_KNEE_FLAT, math.inf) == _PAST_THE_FLAT_GUARD


def test_the_misfit_ceiling_counts_one_declared_component_because_two_cannot_both_fire() -> None:
    """The ceiling is the strong component plus the two fitted ones, and not the sum of four.

    A preference carries one strength, one preference exists per owner, and an override replaces its
    Area's declaration wholly, so exactly one declared component can apply to a block. A sum of
    four is a selection written as a sum, and the ceiling counts the selection once.

    The soft component is left out of the ceiling because it cannot fire beside the strong one, not
    because it is dead. The last two assertions charge it on its own, which is that exclusion's
    other edge.
    """
    at_the_ceiling = misfit_of_one_hour(
        preferences=(a_preference(windows=(a_window(6, 8),), strength=PreferenceStrength.STRONG),),
        fitted=True,
    )
    a_soft_window_alone = misfit_of_one_hour(
        preferences=(a_preference(windows=(a_window(6, 8),), strength=PreferenceStrength.SOFT),)
    )

    assert MISFIT_MAX == MISFIT_STRONG + MISFIT_FITTED_FITNESS + MISFIT_FITTED_SKIP
    assert MISFIT_MAX < MISFIT_STRONG + MISFIT_SOFT + MISFIT_FITTED_FITNESS + MISFIT_FITTED_SKIP
    # By name as well as by figure: three of the four components carry the same number, so the sum
    # of the wrong three has the right value.
    assert the_components_a_ceiling_adds(source_of("preferred.py")) == (
        "MISFIT_FITTED_FITNESS",
        "MISFIT_FITTED_SKIP",
        "MISFIT_STRONG",
    )
    # The ceiling is what the term divides by, so a block charged every component of it reads one.
    assert at_the_ceiling == pytest.approx(1.0)
    assert a_soft_window_alone == pytest.approx(MISFIT_SOFT / MISFIT_MAX)
    assert a_soft_window_alone > 0.0


def test_a_block_with_two_declared_strengths_reads_above_the_unit_and_is_not_clamped() -> None:
    """Both declared components are charged where both are present, rather than one being picked.

    The week below states two preferences for one owner, one strong and one soft. The producer keeps
    one preference per owner behind three unique indexes, so this is a fault in a producer rather
    than a week the product reaches. It is here because the arithmetic's answer to it is the rule
    under assertion, and a fixture that could not present it could not tell a sum from a selection.

    Charged both declared components and both fitted ones, the block passes the ceiling and the term
    reads above 1.0. The control is the same week with one declared strength, which reads exactly
    1.0: the excess is the second declared component and not the fixture.
    """
    two_strengths = (
        a_preference(windows=(a_window(6, 8),), strength=PreferenceStrength.STRONG),
        a_preference(windows=(a_window(6, 8),), strength=PreferenceStrength.SOFT),
    )
    every_component = misfit_of_one_hour(preferences=two_strengths, fitted=True)
    declared_only = misfit_of_one_hour(preferences=two_strengths)
    one_strength = misfit_of_one_hour(preferences=two_strengths[:1], fitted=True)

    assert every_component > 1.0
    assert every_component == pytest.approx(
        (MISFIT_STRONG + MISFIT_SOFT + MISFIT_FITTED_FITNESS + MISFIT_FITTED_SKIP) / MISFIT_MAX
    )
    # Summed rather than selected between: a maximum of the two would charge the strong one alone.
    assert declared_only * MISFIT_MAX == pytest.approx(MISFIT_STRONG + MISFIT_SOFT)
    assert one_strength == pytest.approx(1.0)
