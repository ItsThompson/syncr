"""Observations to one appendable artefact: every fitter run, every gate applied, every row
explained.

The order is fixed and it is the pipeline section 11 draws. For each parameter: count the relevant
observations, compare the count with the threshold, and either fit with shrinkage or record a
collecting row with no value at all. Nothing here decides what a fit MEANS; the fitters do that and
this composes them.

**Every figure that reaches the artefact has passed :func:`~syncr_learning.gates.gated`.** That is
the one statement of "a parameter below its threshold is not applied at all", and it is what closes
the gap for the two scalars, which have no map to be absent from: their fallback is the figure IN
FORCE rather than the prior, so a young corpus leaves the solver exactly where it was rather than
moving it to a number nobody fitted.

**This function is pure.** Given one ``Observations`` and one incumbent it returns one artefact,
which makes the job's idempotence a property of the arithmetic rather than of the database: two runs
over the same rows extract the same observations and compose the same row.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from syncr_learning import statements
from syncr_learning.artifact import FittedWeightSet
from syncr_learning.config import (
    CHURN_TOLERANCE,
    CONTEXT_SWITCH_COST,
    DURATION_MULTIPLIER,
    OBJECTIVE_WEIGHTS,
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
from syncr_learning.gates import ParameterMaturity, gated, maturity, parameter_of, threshold_for
from syncr_learning.rank import RankFit, fit_objective_weights
from syncr_learning.results import FitResult

if TYPE_CHECKING:
    from collections.abc import Callable, Hashable, Mapping, Sequence
    from datetime import datetime

    from syncr_learning.observations import Observations


@dataclass(frozen=True, slots=True, kw_only=True)
class FittedParameters:
    """One tenant's whole fit: the artefact to append, and what the weight fit did or refused."""

    artifact: FittedWeightSet
    rank: RankFit

    @property
    def ready(self) -> int:
        """How many maturity rows carry a figure the solver will apply."""
        return sum(1 for row in self.artifact.maturity if row.value is not None)

    @property
    def collecting(self) -> int:
        """How many are still below their threshold."""
        return len(self.artifact.maturity) - self.ready

    def samples_by_parameter(self) -> dict[str, int]:
        """The largest sample count behind each parameter, which is what the gauge reports.

        The largest rather than the sum, because the gate is per KEY: an Area at fourteen blocks is
        ready while its sibling at three is not, and a summed thirty-one would report the parameter
        as further along than any part of it is.
        """
        found: dict[str, int] = {}
        for row in self.artifact.maturity:
            name = parameter_of(row)
            found[name] = max(found.get(name, 0), row.samples)
        return found


def fit_everything(
    observations: Observations,
    *,
    in_force: Mapping[str, float],
    switch_cost_in_force: float,
    churn_tolerance_in_force: float,
    area_names: Mapping[str, str],
    at: datetime,
) -> FittedParameters:
    """Every parameter this corpus supports, gated, with a maturity row and a sentence for each."""
    rows: list[ParameterMaturity] = []
    multipliers = _duration_multipliers(observations, area_names, rows)
    curves = _fitness_curves(observations, area_names, rows)
    skips = _skip_probabilities(observations, area_names, rows)
    switch = _switch_cost(observations, switch_cost_in_force, rows)
    churn = _churn_tolerance(observations, churn_tolerance_in_force, rows)
    rank = fit_objective_weights(observations.ranking, in_force=in_force)
    weights_evidence = FitResult(
        value=rank.ranked_correctly,
        samples=rank.samples,
        confidence=None if rank.ranked_correctly is None else (0.0, 1.0),
        shrinkage_weight=1.0,
    )
    # The gate is applied to the VECTOR as well as to the row. Section 11 says fitting runs only
    # when the objective-weights gate is met, and a fit does not refuse a small corpus by itself:
    # over forty pairs it produces seven perfectly ordinary-looking numbers, and without this they
    # would ship.
    fitted_weights = (
        rank.weights if gated(OBJECTIVE_WEIGHTS, weights_evidence) is not None else None
    )
    rows.append(
        maturity(
            OBJECTIVE_WEIGHTS,
            weights_evidence
            if fitted_weights is None
            else replace(weights_evidence, shrinkage_weight=0.0),
            statement=statements.weights_statement(
                samples=rank.samples,
                threshold=threshold_for(OBJECTIVE_WEIGHTS),
                rejection=rank.rejection,
                # The SENTENCE is gated with the same predicate as the vector.
                # `rank.ranked_correctly` is non-None whenever the FIT succeeded, and a successful
                # fit is not a shipped vector: below the threshold the vector is correctly withheld,
                # and a sentence keyed on the fit would tell the user it was applied anyway. The
                # Learned screen is the trust surface, so a false claim there costs more than a
                # missing one.
                ranked=rank.ranked_correctly if fitted_weights is not None else None,
            ),
        )
    )
    return FittedParameters(
        artifact=FittedWeightSet(
            term_weights=fitted_weights if fitted_weights is not None else in_force,
            context_switch_cost=switch,
            churn_tolerance=churn,
            duration_multiplier=multipliers,
            time_of_day_fitness=curves,
            skip_probability=skips,
            maturity=tuple(rows),
            fitted_at=at,
        ),
        rank=rank,
    )


def _duration_multipliers(
    observations: Observations, area_names: Mapping[str, str], rows: list[ParameterMaturity]
) -> dict[str, float]:
    """One factor per Area whose gate passed, and a row per Area with observations at all."""
    fitted: dict[str, float] = {}
    for area_id, observed in _grouped(observations.durations, lambda one: str(one.area_id)):
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


def _fitness_curves(
    observations: Observations, area_names: Mapping[str, str], rows: list[ParameterMaturity]
) -> dict[str, tuple[float, ...]]:
    """One twenty-four value curve per Area whose gate passed AND whose evidence spans the day.

    The second condition is why this cannot use :func:`~syncr_learning.gates.gated` alone: a curve
    over six hours of the day is a curve that says nothing about the other eighteen while claiming
    to be fitted, so the spread is part of what the gate reads.
    """
    fitted: dict[str, tuple[float, ...]] = {}
    for area_id, observed in _grouped(observations.time_of_day, lambda one: str(one.area_id)):
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


def _skip_probabilities(
    observations: Observations, area_names: Mapping[str, str], rows: list[ParameterMaturity]
) -> dict[str, dict[str, float]]:
    """One share per Area and bucket whose gate passed. Nested, because the domain key is a pair."""
    fitted: dict[str, dict[str, float]] = {}
    for (area_id, bucket), observed in _grouped(
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


def _switch_cost(
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


def _churn_tolerance(
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


def _grouped[ObservationT, KeyT: Hashable](
    observations: Sequence[ObservationT], key: Callable[[ObservationT], KeyT]
) -> list[tuple[KeyT, list[ObservationT]]]:
    """``observations`` grouped by ``key``, in insertion order.

    Insertion order rather than sorted, because the extraction already produces one order for one
    corpus: sorting here would be a second ordering rule, and the maturity list's own order is what
    a screen renders. Two runs over one corpus therefore produce one row order.
    """
    grouped: dict[KeyT, list[ObservationT]] = {}
    for one in observations:
        grouped.setdefault(key(one), []).append(one)
    return list(grouped.items())
