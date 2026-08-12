"""Observations to one appendable artefact: every fitter run, every gate applied, every row
explained.

The order is fixed. For each parameter: count the relevant observations, compare the count with the
threshold, and either fit with shrinkage or record a collecting row with no value at all. Nothing
here decides what a fit MEANS; the fitters do that, :mod:`syncr_learning.applied` gates each one,
and this composes them in order.

**This function is pure.** Given one ``Observations`` and one incumbent it returns one artefact,
which makes the job's idempotence a property of the arithmetic rather than of the database: two runs
over the same rows extract the same observations and compose the same row.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from syncr_learning import applied, statements
from syncr_learning.artifact import FittedWeightSet
from syncr_learning.config import OBJECTIVE_WEIGHTS
from syncr_learning.gates import ParameterMaturity, gated, maturity, parameter_of, threshold_for
from syncr_learning.rank import RankFit, fit_objective_weights
from syncr_learning.results import FitResult

if TYPE_CHECKING:
    from collections.abc import Mapping
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
    multipliers = applied.duration_multipliers(observations, area_names, rows)
    curves = applied.fitness_curves(observations, area_names, rows)
    skips = applied.skip_probabilities(observations, area_names, rows)
    switch = applied.switch_cost(observations, switch_cost_in_force, rows)
    churn = applied.churn_tolerance(observations, churn_tolerance_in_force, rows)
    rank = fit_objective_weights(observations.ranking, in_force=in_force)
    weights_evidence = FitResult(
        value=rank.ranked_correctly,
        samples=rank.samples,
        confidence=None if rank.ranked_correctly is None else (0.0, 1.0),
        shrinkage_weight=1.0,
    )
    fitted_weights = (
        rank.weights if gated(OBJECTIVE_WEIGHTS, weights_evidence) is not None else None
    )
    # `rank.ranked_correctly` is non-None whenever the FIT succeeded, which is not the same as the
    # vector SHIPPING: the gate decides that. One name for the one predicate, so the row, the
    # sentence and the artefact below are visibly gated by it rather than each re-deriving it.
    shipped = fitted_weights is not None
    rows.append(
        maturity(
            OBJECTIVE_WEIGHTS,
            replace(weights_evidence, shrinkage_weight=0.0) if shipped else weights_evidence,
            statement=statements.weights_statement(
                samples=rank.samples,
                threshold=threshold_for(OBJECTIVE_WEIGHTS),
                rejection=rank.rejection,
                ranked=rank.ranked_correctly if shipped else None,
            ),
        )
    )
    return FittedParameters(
        artifact=FittedWeightSet(
            term_weights=in_force if fitted_weights is None else fitted_weights,
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
