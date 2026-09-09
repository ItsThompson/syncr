"""Per-parameter maturity: what is ready, what is still collecting, and the sentence for each row.

**Maturity is per parameter, never one global flag**, because parameters converge at very different
rates: a duration multiplier is ready in week two and the objective weights in month three.

**A parameter below its threshold is not applied AT ALL**, not applied at a reduced weight. A
half-fitted number is worse than a hand-tuned one, and absence is how the weight set expresses it:
the artefact carries no entry, and the solver applies nothing for a key its map does not name.

**Two of the five parameters have no map to be absent from**, and that is the gap this module
closes. ``context_switch_cost`` and ``churn_tolerance`` are non-nullable columns that version 1
ships hand-tuned, so there is no shape in which "below its gate" can be expressed in storage. For
those two the gate is enforced HERE, by keeping the figure in force rather than writing the fitted
one, and :func:`gated` is the single statement of it: a caller cannot reach a fitted scalar without
passing through the gate that decides whether it may be applied.

## Unlocks count confirmed volume, never adherence

A day where the user skipped everything and said so advances every gate exactly as much as a perfect
day. Tying an unlock to adherence would reward marking things done, and the integrity of the whole
dataset rests on honest confirmation. Backfilled confirmations count identically to same-day ones,
because nothing on a row records how late the answer came, so no gate here can read the difference.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from syncr_learning.config import THRESHOLDS, ConfigError

if TYPE_CHECKING:
    from syncr_learning.results import FitResult

COLLECTING: Literal["collecting"] = "collecting"
READY: Literal["ready"] = "ready"

THRESHOLDS_ARE_ESTIMATES = (
    "These thresholds are estimates rather than measurements. Revising one can move a gate in "
    "either direction without losing any confirmation you have recorded."
)
"""What the Learned screen states about every threshold on it, because they are unvalidated guesses.

Stated here rather than in the screen's own copy so the api serves it beside the figures it
qualifies: asserting a guess as a measurement would violate the product's own standard, and a caveat
that lives only in a template is one a client can render without.
"""


@dataclass(frozen=True, slots=True, kw_only=True)
class ParameterMaturity:
    """One row of the Learned screen: a parameter, its evidence, and what it says in plain words.

    ``value`` is ``None`` while collecting, and that is the whole of the gate as a value: a row with
    no value is a row the solver applies nothing for.
    """

    parameter: str
    samples: int
    threshold: int
    state: Literal["collecting", "ready"]
    value: float | None
    shrinkage_weight: float
    plain_language: str

    def __post_init__(self) -> None:
        if (self.state == READY) != (self.value is not None):
            raise ConfigError(
                f"{self.parameter} is {self.state} and states "
                f"{'a value' if self.value is not None else 'no value'}: a ready parameter is one "
                "with a figure to apply, and a collecting one is a parameter nothing is applied for"
            )
        if self.state == READY and self.samples < self.threshold:
            raise ConfigError(
                f"{self.parameter} is ready on {self.samples} of {self.threshold} observations: a "
                "parameter below its threshold is not applied at all, so a ready row below one "
                "would be a figure the gate did not let through"
            )
        if not self.plain_language.strip():
            raise ConfigError(
                f"{self.parameter} states nothing in plain language, and the sentence is what "
                "builds trust: a row with a number and no words is a diagnostic panel"
            )


def threshold_for(parameter: str) -> int:
    """How many observations this parameter needs before it is applied.

    Read from :data:`~syncr_learning.config.THRESHOLDS` so a revision is a change to configuration
    and nothing else. A parameter with no threshold is a name error rather than a gate of zero,
    because a gate of zero would apply an unfitted figure on the first observation.
    """
    if parameter not in THRESHOLDS:
        raise ConfigError(
            f"{parameter!r} has no maturity threshold, and the parameters that do are "
            f"{', '.join(sorted(THRESHOLDS))}: a parameter with no gate would be applied unfitted"
        )
    return THRESHOLDS[parameter]


def gated(parameter: str, fit: FitResult, *, samples: int | None = None) -> float | None:
    """The fitted figure if the gate lets it through, or nothing at all.

    ``samples`` overrides the count on ``fit`` for the fitters whose gate counts something other
    than the observations they shrank: the context-switch price is gated on cross-Area pairs while
    the figure is shrunk over the extra minutes of each.

    This is the ONE statement of the gate. Every caller that wants a fitted number asks here, so the
    two scalars with no map to be absent from come under the same rule as the three with one.
    """
    counted = fit.samples if samples is None else samples
    if not fit.is_fitted or counted < threshold_for(parameter):
        return None
    return fit.value


def maturity(
    parameter: str,
    fit: FitResult,
    *,
    statement: str,
    samples: int | None = None,
    key: str | None = None,
) -> ParameterMaturity:
    """One maturity row for one parameter, with the gate already applied to its value.

    ``key`` names WHICH instance of a per-key parameter this row is about: an Area for a duration
    multiplier, an Area and a bucket for a skip probability. The threshold is looked up on the
    parameter and the row is named for the key, so one gate serves every key of one parameter and
    the screen can still draw a row per Area.
    """
    counted = fit.samples if samples is None else samples
    value = gated(parameter, fit, samples=counted)
    return ParameterMaturity(
        parameter=parameter if key is None else f"{parameter}[{key}]",
        samples=counted,
        threshold=threshold_for(parameter),
        state=READY if value is not None else COLLECTING,
        value=value,
        shrinkage_weight=fit.shrinkage_weight,
        plain_language=statement,
    )


def parameter_of(row: ParameterMaturity) -> str:
    """The parameter a row is about, with any key stripped off it.

    A metric is labelled by the parameter and a screen row is named for the key, so one of the two
    has to be derived from the other. Deriving the label from the row means a row cannot report
    under a label no gate exists for.
    """
    return row.parameter.split("[", 1)[0]
