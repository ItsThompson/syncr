"""What each parameter contributes to the artefact, with its gate applied. One function each.

Split from :mod:`syncr_learning.fitting`, which was at 297 lines against a 300-line rule and whose
five per-parameter functions were near-siblings. The split mirrors ``fitters/``: a fitter answers
what the evidence says, and a function here decides what reaches the artefact and what the screen is
told about it.

**Every figure that leaves this module has passed :func:`~syncr_learning.gates.gated`.** That is the
one statement of "a parameter below its threshold is not applied at all". The three maps express it
as an absent key; the two scalars have no absent state, so they express it by answering with the
figure IN FORCE, which leaves the solver exactly where it was rather than moving it to a prior
nobody fitted.

Each function appends its maturity rows to the list it is handed rather than returning them, so the
row ORDER is the order the pipeline runs in. That order is what the Learned screen renders, and two
runs over one corpus have to produce one of it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_learning import statements
from syncr_learning.config import (
    CHURN_TOLERANCE,
    CONTEXT_SWITCH_COST,
    DURATION_MULTIPLIER,
    SKIP_PROBABILITY,
    TIME_OF_DAY_FITNESS,
)
from syncr_learning.fitters import (
    fit_churn_tolerance,
    fit_context_switch_cost,
    fit_duration_multiplier,
    fit_skip_probability,
    fit_time_of_day_fitness,
)
from syncr_learning.fitters.duration import median_actual_minutes, median_planned_minutes
from syncr_learning.gates import gated, maturity, threshold_for
from syncr_learning.results import FitResult

if TYPE_CHECKING:
    from collections.abc import Callable, Hashable, Mapping, Sequence

    from syncr_learning.gates import ParameterMaturity
    from syncr_learning.observations import Observations


def duration_multipliers(
    observations: Observations, area_names: Mapping[str, str], rows: list[ParameterMaturity]
) -> dict[str, float]:
    """One factor per Area whose gate passed, and a row per Area with observations at all."""
    fitted: dict[str, float] = {}
    for area_id, observed in grouped(observations.durations, lambda one: str(one.area_id)):
        result = fit_duration_multiplier(observed)
        value = gated(DURATION_MULTIPLIER, result)
        rows.append(
            maturity(
                DURATION_MULTIPLIER,
                result,
                key=area_id,
                statement=statements.duration_statement(
                    area_names.get(area_id, area_id),
                    multiplier=value,
                    planned_median=median_planned_minutes(observed),
                    actual_median=median_actual_minutes(observed),
                    samples=result.samples,
                    threshold=threshold_for(DURATION_MULTIPLIER),
                ),
            )
        )
        if value is not None:
            fitted[area_id] = value
    return fitted


def fitness_curves(
    observations: Observations, area_names: Mapping[str, str], rows: list[ParameterMaturity]
) -> dict[str, tuple[float, ...]]:
    """One twenty-four value curve per Area whose gate passed AND whose evidence spans the day.

    The second condition is why this cannot use :func:`~syncr_learning.gates.gated` alone: a curve
    over six hours of the day is a curve that says nothing about the other eighteen while claiming
    to be fitted, so the spread is part of what the gate reads.
    """
    fitted: dict[str, tuple[float, ...]] = {}
    for area_id, observed in grouped(observations.time_of_day, lambda one: str(one.area_id)):
        curve = fit_time_of_day_fitness(observed)
        passes = gated(TIME_OF_DAY_FITNESS, curve.result) is not None
        applied = passes and curve.covers_enough_of_the_day
        rows.append(
            maturity(
                TIME_OF_DAY_FITNESS,
                curve.result if applied else FitResult.unfittable(curve.result.samples),
                key=area_id,
                statement=statements.fitness_statement(
                    area_names.get(area_id, area_id),
                    best_hour=curve.best_hour if applied else None,
                    worst_hour=curve.worst_hour if applied else None,
                    samples=curve.result.samples,
                    threshold=threshold_for(TIME_OF_DAY_FITNESS),
                ),
            )
        )
        if applied:
            fitted[area_id] = curve.curve
    return fitted


def skip_probabilities(
    observations: Observations, area_names: Mapping[str, str], rows: list[ParameterMaturity]
) -> dict[str, dict[str, float]]:
    """One share per Area and bucket whose gate passed. Nested, because the domain key is a pair."""
    fitted: dict[str, dict[str, float]] = {}
    for (area_id, bucket), observed in grouped(
        observations.skips, lambda one: (str(one.area_id), one.bucket)
    ):
        result = fit_skip_probability(observed)
        value = gated(SKIP_PROBABILITY, result)
        rows.append(
            maturity(
                SKIP_PROBABILITY,
                result,
                key=f"{area_id},{bucket.value}",
                statement=statements.skip_statement(
                    area_names.get(area_id, area_id),
                    bucket,
                    probability=value,
                    samples=result.samples,
                    threshold=threshold_for(SKIP_PROBABILITY),
                ),
            )
        )
        if value is not None:
            fitted.setdefault(area_id, {})[bucket.value] = value
    return fitted


def switch_cost(
    observations: Observations, in_force: float, rows: list[ParameterMaturity]
) -> float:
    """The fitted price of an Area change, or the price in force because the gate did not pass.

    The gate counts the CROSS-AREA pairs, which is what the fitter reports as its sample count: the
    within-Area pairs are the baseline the price is measured against, and counting them would let a
    corpus of one switch and forty same-Area pairs clear a gate about switches.
    """
    result = fit_context_switch_cost(observations.switches)
    value = gated(CONTEXT_SWITCH_COST, result)
    rows.append(
        maturity(
            CONTEXT_SWITCH_COST,
            result,
            statement=statements.switch_statement(
                minutes=value,
                samples=result.samples,
                threshold=threshold_for(CONTEXT_SWITCH_COST),
            ),
        )
    )
    return in_force if value is None else value


def churn_tolerance(
    observations: Observations, in_force: float, rows: list[ParameterMaturity]
) -> float:
    """The fitted tolerance, or the one in force because the gate did not pass."""
    result = fit_churn_tolerance(observations.churn)
    value = gated(CHURN_TOLERANCE, result)
    rows.append(
        maturity(
            CHURN_TOLERANCE,
            result,
            statement=statements.churn_statement(
                moves=value,
                samples=result.samples,
                threshold=threshold_for(CHURN_TOLERANCE),
            ),
        )
    )
    return in_force if value is None else value


def grouped[ObservationT, KeyT: Hashable](
    observations: Sequence[ObservationT], key: Callable[[ObservationT], KeyT]
) -> list[tuple[KeyT, list[ObservationT]]]:
    """``observations`` grouped by ``key``, in insertion order.

    Insertion order rather than sorted, because the extraction already produces one order for one
    corpus: sorting here would be a second ordering rule, and the maturity list's own order is what
    a screen renders. Two runs over one corpus therefore produce one row order.
    """
    found: dict[KeyT, list[ObservationT]] = {}
    for one in observations:
        found.setdefault(key(one), []).append(one)
    return list(found.items())
