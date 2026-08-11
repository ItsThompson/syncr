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

## The price is the clamped difference of two means

The fitted figure is one subtraction: the mean gap across an Area change less the mean gap within
one, brought inside :data:`~syncr_learning.config.MIN_SWITCH_COST_MINUTES` and
:data:`~syncr_learning.config.MAX_SWITCH_COST_MINUTES` **once**. A user whose true extra room is
zero but whose gaps are 5 and 55 against a baseline of 30 therefore fits 0.2 minutes, which is the
prior showing through 40 observations of no extra room at all. Clamping each pair's difference
instead keeps the positive half of such a population at full size and truncates the negative half,
and the mean of what survives sits above the mean of the real differences: the same corpus fits 10.2
minutes.

Two quantities the one clamped figure cannot carry are supplied beside it. The **count** is the
number of cross-Area pairs, because that is what the gate is stated over. The **interval** is built
from the spread of the per-pair differences with no clamp on them, because the disagreement between
those pairs is what the interval reports and the clamped figure alone has none.

The cost of clamping once is that the bound in :mod:`syncr_learning.shrinkage` no longer holds on
one observation's contribution: an absurd gap enters the mean at full size and only the mean is
brought inside the range. The figure a solver reads still cannot leave the range.

## One thing about this parameter is not settled, and here is what would settle it

**The definition is the softest of the five.** "The extra room this user leaves across an Area
change" is an inference from a gap rather than an observation of a cost, so a user whose plan
happens to put breaks between subjects fits a price that is really a scheduling habit. The gate at
twenty cross-Area pairs bounds the exposure.

The measurement that settles it needs a real tenant with twenty or more cross-Area pairs: the price
fitted here, against the cost that tenant is observed to pay for a back-to-back Area change.
Agreement makes the gap a price; a fitted figure well above an observed cost of nothing makes it a
habit. No retune is proposed until that comparison exists, because every candidate figure would be a
guess dressed as a measurement.
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
from syncr_learning.shrinkage import clamped, shrunk_figure

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_learning.observations import SwitchObservation


def gaps_across_areas(observations: Sequence[SwitchObservation]) -> Sequence[float]:
    """The gaps of the adjacent pairs that changed Area: the population being priced.

    Public because the gate counts these pairs while the fit shrinks one figure over them, so the
    count the gate reads cannot be taken from what was shrunk.
    """
    return [one.gap_minutes for one in observations if one.changed_area]


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
    across = gaps_across_areas(observations)
    within = [one.gap_minutes for one in observations if not one.changed_area]
    if not across or not within:
        return FitResult.unfittable(len(across))
    baseline = fmean(within)
    differences = [gap - baseline for gap in across]
    price = clamped(fmean(differences), low=MIN_SWITCH_COST_MINUTES, high=MAX_SWITCH_COST_MINUTES)
    return shrunk_figure(price, spread=differences, prior=prior, prior_weight=prior_weight)
