"""``time_of_day_fitness[area][hour]``: how well this Area's work goes at each hour of the day.

One value per hour of the local day, each from 0 (this Area's work goes badly then) to 1 (it goes
well). Consumed by the objective's misfit term as ``1 - fitness``, so the prior of 1.0 charges
nothing at all: an hour nothing has been observed at is an hour the term must not penalise.

## The curve is twenty-four fits, and the gate is over the Area

Each hour is its own shrinkage, over the confirmed blocks that really happened in it. An hour with
no observations is exactly the prior, which is why the curve is total over the day without a
fallback branch: the formula already answers the empty case.

**The gate has two conditions and the second is not decoration.** Thirty observations all at 07:00
leave twenty-three hours at the prior, so the curve would say nothing about them while claiming to
be fitted. A gate that counted only the total would pass on that corpus, which is a gate passing
because the thing it measures is undefined on the data it read. So a curve is offered only when the
observations also cover :data:`~syncr_learning.config.MIN_DISTINCT_HOURS` different hours.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean
from typing import TYPE_CHECKING

from syncr_learning.config import HOURS_PER_DAY, MIN_DISTINCT_HOURS, PRIOR_FITNESS, PRIOR_WEIGHT
from syncr_learning.results import FitResult
from syncr_learning.shrinkage import shrunk

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_learning.observations import TimeOfDayObservation


@dataclass(frozen=True, slots=True, kw_only=True)
class FittedCurve:
    """One Area's curve, and the summary the Learned screen shows beside it.

    ``result`` carries the SUMMARY figure -- the mean fitness across the day -- because a maturity
    row displays one number and a bounded meter, and the twenty-four are what the solver reads. The
    two are not alternatives: the summary is how the row is drawn and the curve is what is applied.
    """

    curve: tuple[float, ...]
    result: FitResult
    distinct_hours: int

    def __post_init__(self) -> None:
        if len(self.curve) != HOURS_PER_DAY:
            raise ValueError(
                f"a fitted curve carries {len(self.curve)} values and a local day has "
                f"{HOURS_PER_DAY} hours: a curve missing an hour would be applied to some of an "
                "Area's blocks and not others"
            )

    @property
    def covers_enough_of_the_day(self) -> bool:
        """Whether the observations spread far enough across the day for a curve to mean much."""
        return self.distinct_hours >= MIN_DISTINCT_HOURS

    @property
    def worst_hour(self) -> int:
        """The hour this Area's work goes worst at, which the plain-language statement names.

        A tie goes to the earlier hour, so one corpus always names one hour: without that the
        sentence
        the user reads would depend on a mapping's iteration order.
        """
        return min(range(HOURS_PER_DAY), key=lambda hour: (self.curve[hour], hour))

    @property
    def best_hour(self) -> int:
        """The hour it goes best at. A tie goes to the earlier hour, for the same reason."""
        return max(range(HOURS_PER_DAY), key=lambda hour: (self.curve[hour], -hour))


def fit_time_of_day_fitness(
    observations: Sequence[TimeOfDayObservation],
    *,
    prior: float = PRIOR_FITNESS,
    prior_weight: int = PRIOR_WEIGHT,
) -> FittedCurve:
    """One Area's fitness curve: twenty-four shrunk shares, plus the summary and the spread.

    The caller groups by Area; this fits one Area's list, for the reason the duration fitter states.
    """
    by_hour: dict[int, list[float]] = {}
    for one in observations:
        by_hour.setdefault(one.hour, []).append(1.0 if one.went_well else 0.0)
    fits = [
        shrunk(by_hour.get(hour, []), prior=prior, prior_weight=prior_weight)
        for hour in range(HOURS_PER_DAY)
    ]
    # Every hour's fit carries a value: `shrunk` answers the empty case with the prior, and a share
    # is already inside 0 to 1, so the curve needs no clamp and no fallback.
    curve = tuple(fit.value if fit.value is not None else prior for fit in fits)
    return FittedCurve(
        curve=curve,
        result=FitResult(
            value=fmean(curve),
            samples=len(observations),
            confidence=(min(curve), max(curve)),
            shrinkage_weight=prior_weight / (len(observations) + prior_weight),
        ),
        distinct_hours=len(by_hour),
    )
