"""``context_switch_cost``: what one Area change really costs this user, in minutes.

The objective charges the price against the gap the schedule already leaves between two blocks, so
the price has a UNIT rather than only a scale: two blocks of different Areas back to back cost the
whole price, and a gap at least as long as the price costs nothing.

## The price is a difference between two populations, and that makes it refusable

The measurement is how much MORE room this user leaves across an Area change than within one. Both
populations are needed: with only cross-Area pairs there is no baseline, and the figure would be the
absolute gap the user leaves between any two blocks, which is a fact about their day rather than a
price for changing subject.

**So a corpus with one population empty is not fittable, and the fitter says so.** Returning the
prior there would ship a hand-tuned number dressed as a measurement, and the gate would pass on a
metric that is undefined on the data it read. That is the failure this refusal exists for, and it is
the one place in this package where a sample count alone does not decide whether a figure exists.
"""

from __future__ import annotations

from statistics import fmean
from typing import TYPE_CHECKING

from syncr_learning.config import (
    MAX_SWITCH_COST_MINUTES,
    MIN_SWITCH_COST_MINUTES,
    PRIOR_CONTEXT_SWITCH_COST,
    PRIOR_WEIGHT,
)
from syncr_learning.results import FitResult
from syncr_learning.shrinkage import clamped, shrunk

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_learning.observations import SwitchObservation


def fit_context_switch_cost(
    observations: Sequence[SwitchObservation],
    *,
    prior: float = PRIOR_CONTEXT_SWITCH_COST,
    prior_weight: int = PRIOR_WEIGHT,
) -> FitResult:
    """The extra minutes this user leaves across an Area change, shrunk toward the prior.

    Both populations have to be present. The sample count reported is the number of CROSS-AREA
    pairs, because those are the observations of the thing being priced; the within-Area pairs are
    the baseline it is measured against, and counting them would let a corpus of one switch and
    forty same-Area pairs clear a gate about switches.
    """
    across = [one.gap_minutes for one in observations if one.changed_area]
    within = [one.gap_minutes for one in observations if not one.changed_area]
    if not across or not within:
        return FitResult.unfittable(len(across))
    baseline = fmean(within)
    extra = [
        clamped(gap - baseline, low=MIN_SWITCH_COST_MINUTES, high=MAX_SWITCH_COST_MINUTES)
        for gap in across
    ]
    return shrunk(extra, prior=prior, prior_weight=prior_weight)
