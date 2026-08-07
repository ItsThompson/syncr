"""``duration_multiplier[area]``: what one stated minute of this Area's work really costs.

Fitted from ``partial`` outcomes, which is the one state that reports how long the work really took.
The measurement is the RATIO of actual to planned minutes, not the difference: a multiplier scales
an estimate, so an Area whose sixty-minute blocks run to eighty-two is at 1.37 whatever the block
length.

**Applied by the week assembler**, before a solve begins, so a plan is always solved against
already-corrected durations. The objective cannot reach it and does not hold it.

The clamp is where the credibility rule lives. One three-hour session against a one-hour plan would
enter as 3.0; clamped it enters as :data:`~syncr_learning.config.MAX_DURATION_RATIO`, and the bound
in :mod:`syncr_learning.shrinkage` then says how far that can move a displayed figure. Clamped
rather than dropped, because the block did run long and dropping it would discard the direction of
the evidence along with its size.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_learning.config import (
    MAX_DURATION_RATIO,
    MIN_DURATION_RATIO,
    PRIOR_DURATION_MULTIPLIER,
    PRIOR_WEIGHT,
)
from syncr_learning.shrinkage import clamped, shrunk

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from syncr_learning.observations import DurationObservation
    from syncr_learning.results import FitResult


def fit_duration_multiplier(
    observations: Sequence[DurationObservation],
    *,
    prior: float = PRIOR_DURATION_MULTIPLIER,
    prior_weight: int = PRIOR_WEIGHT,
) -> FitResult:
    """What this Area's estimates are worth, shrunk toward the prior.

    The caller groups by Area; this fits one Area's list. Grouping here would make the function
    answer with a map and the gate a second walk over it, and the gate is per Area.
    """
    ratios = [
        clamped(one.ratio, low=MIN_DURATION_RATIO, high=MAX_DURATION_RATIO) for one in observations
    ]
    return shrunk(ratios, prior=prior, prior_weight=prior_weight)


def median_actual_minutes(observations: Sequence[DurationObservation]) -> int | None:
    """The middle of what this Area's blocks really took, or nothing because none reported.

    The plain-language statement on the Learned screen quotes this rather than the fitted ratio:
    "you estimate 60m for Leetcode; your actual median is 82m" is what builds trust, and a median is
    what a person can check against their own memory. A mean would be moved by the one long session
    the clamp exists to contain.
    """
    return _median(one.actual_minutes for one in observations)


def median_planned_minutes(observations: Sequence[DurationObservation]) -> int | None:
    """The middle of what this Area's blocks were planned for, quoted beside the other median."""
    return _median(one.planned_minutes for one in observations)


def _median(minutes: Iterable[int]) -> int | None:
    """The middle value, or the whole-minute mean of the middle two. ``None`` for nothing at all.

    Whole minutes because both figures are quoted in a sentence a person reads, and "your actual
    median is 82m" is the sentence rather than "81.5m".
    """
    ordered = sorted(minutes)
    if not ordered:
        return None
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) // 2
