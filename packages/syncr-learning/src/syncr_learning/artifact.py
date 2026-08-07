"""The whole model artefact: 30 to 50 floats, in the spelling the ``weight_sets`` row holds.

No model registry, no artifact store, no MLflow, no serialized binary. The artefact is a row, and
this module is the one place its shape is stated on this side of the boundary.

## The stored spelling, and who reads each key back

| Key | Stored as | Read back by |
|---|---|---|
| ``duration_multiplier`` | ``{area: factor}`` | the week assembler, through ``plans.multipliers`` |
| ``time_of_day_fitness`` | ``{area: [24 values]}`` | the objective's misfit term |
| ``skip_probability`` | ``{area: {bucket: share}}`` | the objective's misfit term |
| the seven weights | columns | the objective, as its weights |
| the two scalars | columns | the objective's switch and churn terms |
| ``maturity`` | a list of objects | the Learned screen |

``skip_probability`` is nested rather than keyed on a joined string, because the domain key is a
PAIR and a JSONB object cannot hold a tuple: nesting keeps both halves addressable in a ``psql``
session and needs no delimiter that an identifier could contain.

## Absence is the gate

A key is written only for a parameter whose gate passed. An Area the map does not name has no fitted
correction and gets none, which is "a parameter below its threshold is not applied at all" in
storage. A neutral default would be a fitted-looking number nobody fitted, and for the fitness curve
it would be worse than that: read as a default, an absent fitness enters the misfit term as the
largest charge it can carry, which is the inverse of the rule.

## The two scalars have no absent state, so the gate is applied before they get here

Their columns are not nullable and version 1 ships them hand-tuned, so a fitted scalar below its
gate cannot be expressed as absence. :func:`~syncr_learning.gates.gated` is what keeps the figure in
force instead, and this module takes the already-gated values: the fallback it applies is the
INCUMBENT's number rather than a prior, so a refused fit leaves the solver exactly where it was.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from syncr_learning.config import OBJECTIVE_TERMS

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime

    from syncr_learning.gates import ParameterMaturity

DURATION_MULTIPLIER_KEY = "duration_multiplier"
TIME_OF_DAY_FITNESS_KEY = "time_of_day_fitness"
SKIP_PROBABILITY_KEY = "skip_probability"

PARAMETER_KEY = "parameter"
SAMPLES_KEY = "samples"
THRESHOLD_KEY = "threshold"
STATE_KEY = "state"
VALUE_KEY = "value"
SHRINKAGE_WEIGHT_KEY = "shrinkage_weight"
PLAIN_LANGUAGE_KEY = "plain_language"

FITTED_ORIGIN = "fitted"


@dataclass(frozen=True, slots=True, kw_only=True)
class FittedWeightSet:
    """One version's worth of parameters, ready to be appended as a new row.

    Every field is already gated. Nothing downstream re-decides what may be applied, which is what
    makes the gate one statement rather than one per writer.
    """

    term_weights: Mapping[str, float]
    context_switch_cost: float
    churn_tolerance: float
    duration_multiplier: Mapping[str, float] = field(default_factory=dict)
    time_of_day_fitness: Mapping[str, tuple[float, ...]] = field(default_factory=dict)
    skip_probability: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    maturity: Sequence[ParameterMaturity] = ()
    fitted_at: datetime | None = None

    def __post_init__(self) -> None:
        if set(self.term_weights) != set(OBJECTIVE_TERMS):
            raise ValueError(
                f"a weight set carries the objective's seven terms and this names "
                f"{sorted(self.term_weights)}: the solver reads all of them, and a missing one "
                "would be read as a weight of zero rather than as an omission"
            )

    def columns(self) -> dict[str, object]:
        """The row this artefact is, as the columns and JSONB documents a writer inserts.

        One mapping rather than a writer that reads twelve fields, so the stored spelling is stated
        once and the writer is an insert.
        """
        return {
            **dict(self.term_weights),
            "context_switch_cost": self.context_switch_cost,
            "churn_tolerance": self.churn_tolerance,
            DURATION_MULTIPLIER_KEY: dict(self.duration_multiplier),
            TIME_OF_DAY_FITNESS_KEY: {
                area: list(curve) for area, curve in self.time_of_day_fitness.items()
            },
            SKIP_PROBABILITY_KEY: {
                area: dict(buckets) for area, buckets in self.skip_probability.items()
            },
            "maturity": [stored_maturity(one) for one in self.maturity],
            "origin": FITTED_ORIGIN,
            "fitted_at": self.fitted_at,
        }


def stored_maturity(row: ParameterMaturity) -> dict[str, object]:
    """One maturity row as the object the ``maturity`` array holds.

    The keys are the field names, so the stored object and the value it came from read alike in a
    ``psql`` session and on the Learned screen.
    """
    return {
        PARAMETER_KEY: row.parameter,
        SAMPLES_KEY: row.samples,
        THRESHOLD_KEY: row.threshold,
        STATE_KEY: row.state,
        VALUE_KEY: row.value,
        SHRINKAGE_WEIGHT_KEY: row.shrinkage_weight,
        PLAIN_LANGUAGE_KEY: row.plain_language,
    }
