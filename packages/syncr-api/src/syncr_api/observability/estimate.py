"""Estimate accuracy: the median absolute percentage error, by Area.

The one product metric that is not a ratio over acts. It answers whether the user's own duration
estimates are getting better, which is the thing the learning layer exists to improve.

``partial`` outcomes carrying ``actual_minutes`` are the whole substrate, which is why that pairing
is a check constraint on the table rather than a convention. The estimate is the block's own placed
duration in the plan of record the outcome was recorded against, so a block the user re-estimated
later is still measured against what was planned when it happened.

**Two exclusions, and both would otherwise flatter the figure.** An unconfirmed day is a day the
user did not answer for, so an ``actual`` on it was presumed rather than observed. An off-plan span
is time the user told syncr not to plan, so a block inside one was not being followed in the first
place. Neither is evidence about estimating.

**The MEDIAN, not the mean.** One block estimated at 15 minutes and taking two hours is a 700%
error, and a mean over a handful of blocks is that one block. The target is stated as a median for
the same reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from syncr_domain.identifiers import AreaId


@dataclass(frozen=True, slots=True, kw_only=True)
class Measurement:
    """One block's estimate against what it actually took, attributed to an Area."""

    area_id: AreaId
    estimated_minutes: int
    actual_minutes: int

    def __post_init__(self) -> None:
        # The invariant lives on the type that divides by it. A zero estimate is not a divisor, and
        # the reader that filters these out is one layer away: constructing one directly with a zero
        # would raise `ZeroDivisionError` from a property rather than being refused here.
        if self.estimated_minutes <= 0:
            raise ValueError(
                "a measurement's estimate is what its error is a percentage OF, so a zero or "
                f"negative estimate measures nothing: got {self.estimated_minutes}"
            )

    @property
    def absolute_percentage_error(self) -> float:
        """How far the estimate was out, as a percentage of the estimate."""
        return abs(self.actual_minutes - self.estimated_minutes) / self.estimated_minutes * 100


def median_ape_by_area(measured: Iterable[Measurement]) -> Mapping[AreaId, float]:
    """The median absolute percentage error per Area, over the measurements given.

    An Area with no measurement is absent rather than zero: zero error is the perfect score, and
    reporting it for an Area nobody logged an outcome in would read as the best possible result.
    """
    by_area: dict[AreaId, list[float]] = {}
    for one in measured:
        by_area.setdefault(one.area_id, []).append(one.absolute_percentage_error)
    return {area_id: median(errors) for area_id, errors in by_area.items()}
