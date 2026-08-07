"""``skip_probability[(area, bucket)]``: how often the user refuses this Area's work in this part of
the day.

Fitted from confirmed blocks, over the bucket each was PLANNED in. A ``skipped`` outcome is a
refusal and so is a ``moved`` one: the user did not do the work where the solver put it, and that is
the
question this parameter answers. Consumed by the objective's misfit term, charged in full, so the
prior of 0.0 charges nothing.

**Three buckets rather than twenty-four hours, because a refusal is a sparse signal.** A user
produces a handful a week, and a per-hour probability would never leave its prior. That is the same
argument that keeps ``staleness`` one term.

The gate is per KEY rather than per Area. A bucket with no evidence gets no entry, and an absent
entry is not applied at all; an entry at the prior would be a fitted claim that the user never
refuses that part of the day, which is a different statement and one nothing measured.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_learning.config import PRIOR_SKIP_PROBABILITY, PRIOR_WEIGHT
from syncr_learning.shrinkage import shrunk

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_learning.observations import SkipObservation
    from syncr_learning.results import FitResult


def fit_skip_probability(
    observations: Sequence[SkipObservation],
    *,
    prior: float = PRIOR_SKIP_PROBABILITY,
    prior_weight: int = PRIOR_WEIGHT,
) -> FitResult:
    """How often this Area's work in this bucket was refused, shrunk toward the prior.

    The caller groups by ``(area, bucket)``; this fits one key's list. A share is already inside 0
    to 1, so nothing here clamps: the observation carries a boolean and the bound is the vocabulary.
    """
    refusals = [1.0 if one.was_refused else 0.0 for one in observations]
    return shrunk(refusals, prior=prior, prior_weight=prior_weight)
