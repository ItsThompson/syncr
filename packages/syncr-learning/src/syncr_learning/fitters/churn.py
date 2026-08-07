"""``churn_tolerance``: how many moves away from the approved plan this user absorbs cheaply.

The objective's churn term is a knee: below the tolerance the moves are absorbed cheaply, at it they
cost half the term's unit, and past it the cost climbs toward the whole of it. The tolerance SHAPES
the term and the churn weight SCALES it, which is why they are two numbers.

The measurement is how many moves each rearrangement got past the user without an objection. A user
who absorbs eight moves and pins the ninth back has a tolerance near eight, and a user who pins back
every move a revision made has a tolerance near zero.

**The floor is one move rather than zero.** Zero is not a tolerance: it is a shape with no knee at
all, and the term it shapes would be undefined rather than steep. A user who absorbs no
rearrangement is expressed by a high churn WEIGHT, which is the number that says how much the term
matters. That is the solver's own guard, restated here as the clamp that makes it unreachable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_learning.config import (
    MAX_CHURN_TOLERANCE,
    MIN_CHURN_TOLERANCE,
    PRIOR_CHURN_TOLERANCE,
    PRIOR_WEIGHT,
)
from syncr_learning.shrinkage import clamped, shrunk

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_learning.observations import ChurnObservation
    from syncr_learning.results import FitResult


def fit_churn_tolerance(
    observations: Sequence[ChurnObservation],
    *,
    prior: float = PRIOR_CHURN_TOLERANCE,
    prior_weight: int = PRIOR_WEIGHT,
) -> FitResult:
    """How many moves this user lets stand per rearrangement, shrunk toward the prior.

    A rearrangement that moved nothing is dropped rather than counted as absorbing nothing. It is
    not evidence about tolerance: the user was shown no rearrangement, so they absorbed no
    rearrangement, and counting it would drag every tolerance toward the floor as a week passes
    quietly.
    """
    absorbed = [
        clamped(float(one.absorbed), low=MIN_CHURN_TOLERANCE, high=MAX_CHURN_TOLERANCE)
        for one in observations
        if one.moves > 0
    ]
    return shrunk(absorbed, prior=prior, prior_weight=prior_weight)
