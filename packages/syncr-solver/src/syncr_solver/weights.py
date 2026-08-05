"""``WeightSet``: the numbers the objective reads, and the two jobs those numbers do.

The whole model artifact is 30 to 50 floats in a database row. This is the solver's reading of
it: the seven term weights, and the four fitted parameters the objective applies. No scipy, no
artifact store, no serialized binary, which is the rule that keeps the api image small and this
package testable against hand-written fixtures.

## A weight and a parameter are different kinds of number

A **weight** says how much a term matters against the other six. A **parameter** says the
term's internal shape. They are fitted from different signals -- learning to rank over pinned
counterfactuals for the weights, direct observation for the parameters -- which is why they are
separate fields rather than one product.

For a term that is LINEAR in its parameter the two are arithmetically collapsible, and no test
over the term's value can tell ``cost=2, weight=1`` from ``cost=1, weight=2``. ``context_switch``
is therefore not linear in its price: a gap the schedule already leaves absorbs part of the
price, so the two numbers stop being interchangeable at the first pair that is not back to back.
:mod:`syncr_solver.terms` states that arithmetic and the reason for it.

## What is deliberately absent, and the rule the absence expresses

``duration_multiplier`` is NOT here. It sizes work rather than expressing a preference, and the
week assembler applies it, so a plan is always evaluated against already-corrected durations. It
is absent rather than unread: a number the objective cannot reach is a number it cannot apply,
and the same stored row is read by two value types that each carry only what they apply.

No version, no tenant, no ``active`` flag and no maturity list either. Those are the stored
row's columns and the api's business; nothing in the arithmetic below reads one.

## A parameter below its maturity gate is not applied at all

Not applied at a reduced weight: a half-fitted number is worse than a hand-tuned one. **Absence
is how that is expressed.** A fitter that has not cleared an Area's gate writes no entry for it,
so an empty map is what "nothing has been learned yet" looks like, and an Area no map names
contributes nothing to the term.

The distinction the guards below protect is between an ABSENT parameter and a parameter fitted
at zero. An absent time-of-day fitness contributes nothing; a fitness fitted at 0.0 says this
Area's work goes badly at that hour and is charged in full. Read as a default, absence would
become the maximum misfit the term can carry, which is the inverse of the rule.

The two scalars carry no absent state, because the stored row's columns are not nullable and
version 1 ships them hand-tuned. So "below its gate" is a state of a map here, and the fitted
value of a scalar replacing a hand-tuned one is the learner's decision rather than this
module's.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from enum import StrEnum
from math import isfinite
from typing import TYPE_CHECKING, Final

from syncr_domain.errors import DomainError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syncr_domain.identifiers import AreaId

OBJECTIVE_TERMS: Final[tuple[str, ...]] = (
    "deadline_risk",
    "budget_deviation",
    "time_of_day_misfit",
    "fragmentation",
    "churn",
    "context_switch",
    "staleness",
)
"""The seven terms, in the order a breakdown holds them. The objective's whole vocabulary.

Every name here is a weight field below and a cost field on
:class:`~syncr_solver.objective.ObjectiveBreakdown`, and a test crosses this tuple against both
in each direction, so a term cannot exist without a weight or a weight without a term.
"""

# The hours of a local day, which is what a fitted fitness curve carries one value per.
HOURS_PER_DAY: Final = 24


class WeightError(DomainError):
    """A weight set carries a number the objective cannot apply."""


class TimeBucket(StrEnum):
    """The part of the day a skip probability is keyed on.

    Three buckets rather than twenty-four hours, because a refusal is a sparse signal: a user
    produces a handful a week, and a per-hour probability would never leave its prior. Three is
    the same argument that keeps ``staleness`` one term.

    They PARTITION the day. Every hour a block can start in falls in exactly one, because a
    probability keyed on a bucket has to exist for every hour, and an hour belonging to two
    would charge one block twice.
    """

    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"


# Where each bucket starts, in local hours, in the order the day runs. The last bucket runs to
# midnight and the first therefore holds the small hours: a block starting at 02:00 is in the
# morning bucket because the alternative is a fourth bucket, and a fourth bucket is a fourth
# number to fit from the sparsest signal the product has.
_BUCKET_STARTS: Final[tuple[tuple[int, TimeBucket], ...]] = (
    (0, TimeBucket.MORNING),
    (12, TimeBucket.AFTERNOON),
    (17, TimeBucket.EVENING),
)


def bucket_of(hour: int) -> TimeBucket:
    """Which part of the day a local hour falls in."""
    if not 0 <= hour < HOURS_PER_DAY:
        raise WeightError(
            f"{hour} is not an hour of a local day: a bucket is keyed on the hour a block "
            f"starts in, which runs from 0 to {HOURS_PER_DAY - 1}"
        )
    found = TimeBucket.MORNING
    for start, bucket in _BUCKET_STARTS:
        if hour >= start:
            found = bucket
    return found


@dataclass(frozen=True, slots=True, kw_only=True)
class WeightSet:
    """The seven term weights and the four parameters the objective applies.

    Every field is a plain float or a map of them. The maps are copied on construction, so a
    caller mutating what it passed cannot change what a solve was produced under.
    """

    deadline_risk: float
    budget_deviation: float
    time_of_day_misfit: float
    fragmentation: float
    churn: float
    context_switch: float
    staleness: float

    # The price of one Area change, in MINUTES of the week. Charged against the gap the
    # schedule already leaves between the two blocks, which is what gives it a unit rather
    # than only a scale.
    context_switch_cost: float
    # How many moves away from the approved plan this user absorbs before the cost of another
    # one rises steeply. It shapes the churn term; the churn WEIGHT scales it.
    churn_tolerance: float

    # One value per hour of the local day, per Area, each running from 0 (this Area's work
    # goes badly at that hour) to 1 (it goes well). An Area absent from the map has no fitted
    # curve, and no curve is applied for it at all.
    time_of_day_fitness: Mapping[AreaId, tuple[float, ...]] = field(default_factory=dict)
    # How often the user refuses this Area's work in this part of the day, from 0 to 1. A key
    # absent from the map has no fitted probability, and none is applied for it.
    skip_probability: Mapping[tuple[AreaId, TimeBucket], float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "time_of_day_fitness", dict(self.time_of_day_fitness))
        object.__setattr__(self, "skip_probability", dict(self.skip_probability))
        _require_every_term_to_carry_a_weight(self)
        for name in OBJECTIVE_TERMS:
            _require_a_weight(name, self.weight_of(name))
        _require_a_price(self.context_switch_cost)
        _require_a_tolerance(self.churn_tolerance)
        _require_fitted_curves(self.time_of_day_fitness)
        _require_fitted_probabilities(self.skip_probability)

    def weight_of(self, term: str) -> float:
        """How much ``term`` matters against the other six."""
        if term not in OBJECTIVE_TERMS:
            raise WeightError(
                f"{term!r} is not one of the objective's seven terms: they are "
                f"{', '.join(OBJECTIVE_TERMS)}"
            )
        weight = getattr(self, term)
        assert isinstance(weight, float)  # noqa: S101 - held by the field-name guard above
        return weight

    def fitness_at(self, area_id: AreaId, hour: int) -> float | None:
        """How well this Area's work goes at this hour, or ``None`` if nothing is fitted.

        ``None`` rather than a neutral number, so a caller states what an unfitted Area costs
        instead of inheriting a default that reads as a fitted claim.
        """
        curve = self.time_of_day_fitness.get(area_id)
        if curve is None:
            return None
        return curve[hour]

    def skip_at(self, area_id: AreaId, bucket: TimeBucket) -> float | None:
        """How often this Area's work is refused in this part of the day, or ``None``."""
        return self.skip_probability.get((area_id, bucket))


def _require_every_term_to_carry_a_weight(weights: WeightSet) -> None:
    """Every name in the vocabulary is a field of this class, in both directions.

    Read from the dataclass rather than from a second list, so a renamed weight fails here
    instead of resolving to whatever ``getattr`` finds. The inverse direction is asserted by
    the suite, because the two parameters below are floats too and only a test can say which
    floats are weights.
    """
    declared = {member.name for member in fields(weights)}
    missing = sorted(term for term in OBJECTIVE_TERMS if term not in declared)
    if missing:  # pragma: no cover - unreachable while the class declares the seven
        raise WeightError(
            f"the objective names terms this weight set carries no weight for: {missing}. "
            "A term with no weight would be scored at whatever a lookup happened to find"
        )


def _require_a_weight(name: str, weight: float) -> None:
    """A weight scales a cost, so it is finite and never negative.

    A negative weight would make the solver actively seek the cost the term measures, which is
    never the intent, and the learner rejects a fit that would produce one. A non-finite weight
    would make every total infinite and every share of it undefined.
    """
    if not isfinite(weight) or weight < 0:
        raise WeightError(
            f"the {name!r} weight is {weight}, and a weight is a finite number at or above "
            "zero: a negative one would make the solver seek the cost this term measures"
        )


def _require_a_price(cost: float) -> None:
    """The price of one Area change is a duration, so it is finite minutes at or above zero."""
    if not isfinite(cost) or cost < 0:
        raise WeightError(
            f"context_switch_cost is {cost}, and it is minutes: a negative price would pay "
            "the plan for changing Area, and a non-finite one would price every week alike"
        )


def _require_a_tolerance(tolerance: float) -> None:
    """Churn tolerance divides, so zero is not a tolerance and neither is a negative.

    A tolerance of zero is not "absorbs nothing": it is a shape with no knee at all, and the
    term it shapes would be undefined rather than steep. A user who absorbs no rearrangement is
    expressed by a high churn WEIGHT, which is the number that says how much the term matters.
    """
    if not isfinite(tolerance) or tolerance <= 0:
        raise WeightError(
            f"churn_tolerance is {tolerance}, and it is the number of moves at which cost "
            "begins to rise steeply: it runs above zero, because zero moves is not a tolerance"
        )


def _require_fitted_curves(curves: Mapping[AreaId, tuple[float, ...]]) -> None:
    """A fitted curve names every hour of the day, and every value is a share.

    Refused rather than read short or clipped. A curve missing an hour would be applied to some
    blocks and not others depending on when they start, which is the least explainable failure
    an Area could have, and a value outside zero to one is not a fitness.
    """
    for area_id, curve in curves.items():
        if len(curve) != HOURS_PER_DAY:
            raise WeightError(
                f"the fitted time-of-day curve for Area {area_id} carries {len(curve)} values "
                f"and a local day has {HOURS_PER_DAY} hours: a curve missing an hour would be "
                "applied to some of an Area's blocks and not others"
            )
        for hour, value in enumerate(curve):
            _require_a_share(value, f"time_of_day_fitness[{area_id}][{hour}]")


def _require_fitted_probabilities(probabilities: Mapping[tuple[AreaId, TimeBucket], float]) -> None:
    for (area_id, bucket), value in probabilities.items():
        _require_a_share(value, f"skip_probability[({area_id}, {bucket.value})]")


def _require_a_share(value: float, named: str) -> None:
    if not isfinite(value) or not 0.0 <= value <= 1.0:
        raise WeightError(
            f"{named} is {value}, and a fitted share runs from 0 to 1: a value outside it "
            "would leave the misfit term's four components off the scale they are fixed on"
        )
