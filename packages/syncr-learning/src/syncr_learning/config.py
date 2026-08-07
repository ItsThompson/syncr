"""The numbers this job is configured by, and the vocabulary they are keyed on.

Three kinds of number live here and each is a different sort of claim.

**The priors.** What a parameter is worth before this user has produced evidence about it. Every
one equals the hand-tuned figure version 1 ships, because that figure IS the prior belief: a
second, differently chosen prior would mean the first observation moved the value away from what
the solver was already using. ``tests/test_solver_agreement.py`` holds each against the api's own
``P0_WEIGHTS``.

**The prior weights.** How many observations it takes for the evidence to outweigh the prior.
Section 11 states the formula and works three cases at ``k = 10``, so ten is the documented default
and every parameter takes it until one is measured to need otherwise.

**The maturity thresholds. THESE ARE UNVALIDATED ESTIMATES.** They are the PRD author's guesses at
how fast each parameter converges, not measurements of it, and they are stated as such on the
Learned screen. Revising one against real data is a change to this file and nothing else: no
migration, no schema change, and no reprocessing of history, because every run refits from the log.

## Why the vocabulary is restated here rather than imported

``OBJECTIVE_TERMS`` and the three time buckets are owned by ``syncr_solver.weights``, which this
package must not import: the solver ships in the api image and this package pulls scipy. So the
spelling is restated, exactly as ``syncr_api.learned.config`` already restates the seven terms for
the same reason, and ``tests/test_solver_agreement.py`` crosses both against the owner in one
process -- all twenty-four hours of the bucketing, not a sample of it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

# ---------------------------------------------------------------------------
# The vocabulary. Restated from `syncr_solver.weights`, crossed against it by the suite.
# ---------------------------------------------------------------------------

OBJECTIVE_TERMS: Final[tuple[str, ...]] = (
    "deadline_risk",
    "budget_deviation",
    "time_of_day_misfit",
    "fragmentation",
    "churn",
    "context_switch",
    "staleness",
)
"""The seven terms a weight fit outputs, in the order the solver holds them."""

HOURS_PER_DAY: Final = 24


class TimeBucket(StrEnum):
    """The part of the day a skip probability is keyed on."""

    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"


# Where each bucket opens, in local hours, in the order the day runs. The last runs to midnight, so
# the first holds the small hours.
_BUCKET_STARTS: Final[tuple[tuple[int, TimeBucket], ...]] = (
    (0, TimeBucket.MORNING),
    (12, TimeBucket.AFTERNOON),
    (17, TimeBucket.EVENING),
)


class ConfigError(ValueError):
    """A figure reached this configuration's arithmetic that no local day or parameter has."""


def bucket_of(hour: int) -> TimeBucket:
    """Which part of the day a local hour falls in."""
    if not 0 <= hour < HOURS_PER_DAY:
        raise ConfigError(
            f"{hour} is not an hour of a local day: a bucket is keyed on the hour a block starts "
            f"in, which runs from 0 to {HOURS_PER_DAY - 1}"
        )
    found = TimeBucket.MORNING
    for start, bucket in _BUCKET_STARTS:
        if hour >= start:
            found = bucket
    return found


# ---------------------------------------------------------------------------
# The parameters this job fits, named once so a metric label, a maturity row and a stored key
# cannot spell one parameter three ways.
# ---------------------------------------------------------------------------

DURATION_MULTIPLIER: Final = "duration_multiplier"
TIME_OF_DAY_FITNESS: Final = "time_of_day_fitness"
SKIP_PROBABILITY: Final = "skip_probability"
CONTEXT_SWITCH_COST: Final = "context_switch_cost"
CHURN_TOLERANCE: Final = "churn_tolerance"
OBJECTIVE_WEIGHTS: Final = "objective_weights"

FITTED_PARAMETERS: Final[tuple[str, ...]] = (
    DURATION_MULTIPLIER,
    TIME_OF_DAY_FITNESS,
    SKIP_PROBABILITY,
    CONTEXT_SWITCH_COST,
    CHURN_TOLERANCE,
    OBJECTIVE_WEIGHTS,
)
"""Every parameter with a gate. Six rows, which is section 11's maturity table plus the weights."""


# ---------------------------------------------------------------------------
# The priors. Each is the figure version 1 ships hand-tuned.
# ---------------------------------------------------------------------------

PRIOR_DURATION_MULTIPLIER: Final = 1.0
"""The user's own estimate, taken at face value until their outcomes say otherwise."""

PRIOR_FITNESS: Final = 1.0
"""Work goes well at every hour. The misfit term charges ``1 - fitness``, so this charges nought."""

PRIOR_SKIP_PROBABILITY: Final = 0.0
"""The user refuses nothing. Charged as ``skip``, so this charges nothing either."""

PRIOR_CONTEXT_SWITCH_COST: Final = 1.0
"""Minutes. The hand-tuned price of one Area change."""

PRIOR_CHURN_TOLERANCE: Final = 3.0
"""Moves. The hand-tuned point at which churn cost begins to rise steeply."""

PRIOR_WEIGHT: Final = 10
"""``k``: how many observations it takes for the evidence to weigh as much as the prior.

Section 11 works three cases at this value: one observation leaves the value 91% prior, ten make it
half and half, and fifty make it 83% observed. One default for every parameter until a measurement
says one of them converges differently.
"""


# ---------------------------------------------------------------------------
# The observation ranges. What clamps an outlier, and therefore what bounds its influence.
# ---------------------------------------------------------------------------

MIN_DURATION_RATIO: Final = 0.25
MAX_DURATION_RATIO: Final = 4.0
"""A block that ran to a quarter of its plan, and one that ran to four times it.

The bound exists so a single three-hour session against a one-hour plan cannot make the Fitness
multiplier absurd. A ratio outside this is CLAMPED rather than dropped: the block did run long, and
dropping it would discard the direction of the evidence along with its size.
"""

MIN_SWITCH_COST_MINUTES: Final = 0.0
MAX_SWITCH_COST_MINUTES: Final = 120.0
"""The price of one Area change, in minutes. Two hours is the widest gap this reads as a price."""

MIN_CHURN_TOLERANCE: Final = 1.0
MAX_CHURN_TOLERANCE: Final = 40.0
"""Moves. Zero is not a tolerance, which is the solver's own guard, so the floor here is one."""


# ---------------------------------------------------------------------------
# The maturity thresholds. UNVALIDATED ESTIMATES, and the screen says so.
# ---------------------------------------------------------------------------

THRESHOLD_DURATION_MULTIPLIER: Final = 12
"""Confirmed blocks in one Area. Section 11 estimates 10 to 15; this is the middle of it."""

THRESHOLD_TIME_OF_DAY_FITNESS: Final = 30
"""Confirmed blocks in one Area, spread across hours. Section 11 estimates 30 or more."""

MIN_DISTINCT_HOURS: Final = 6
"""How many different hours those blocks have to cover before a curve is fitted at all.

The second half of "spread across hours", and it is not decoration. Thirty blocks all starting at
07:00 leave twenty-three hours of the curve at the prior, so the fitted curve would say nothing
about them while claiming to be fitted. A gate that counted only the total would pass on that
corpus, which is a gate passing because its metric is undefined on the data it read.
"""

THRESHOLD_SKIP_PROBABILITY: Final = 6
"""Confirmed blocks in one Area and one bucket. Sparse by nature: three buckets, a few a week."""

THRESHOLD_CONTEXT_SWITCH_COST: Final = 20
"""Adjacent confirmed pairs. Both populations, because the figure is a difference between them."""

THRESHOLD_CHURN_TOLERANCE: Final = 20
"""Proposals. Section 11's own figure."""

THRESHOLD_OBJECTIVE_WEIGHTS: Final = 50
"""Edit events. Section 11 estimates 50 to 100; this is the lower bound of it."""

THRESHOLDS: Final[dict[str, int]] = {
    DURATION_MULTIPLIER: THRESHOLD_DURATION_MULTIPLIER,
    TIME_OF_DAY_FITNESS: THRESHOLD_TIME_OF_DAY_FITNESS,
    SKIP_PROBABILITY: THRESHOLD_SKIP_PROBABILITY,
    CONTEXT_SWITCH_COST: THRESHOLD_CONTEXT_SWITCH_COST,
    CHURN_TOLERANCE: THRESHOLD_CHURN_TOLERANCE,
    OBJECTIVE_WEIGHTS: THRESHOLD_OBJECTIVE_WEIGHTS,
}
"""Every gate by the parameter it gates, so a caller reads one mapping rather than six constants."""

CONSECUTIVE_WEEKS_FOR_PROMOTION: Final = 3
"""How many consecutive ISO weeks of one pin make a template promotion candidate."""

CONFIDENCE: Final = 0.95
"""The interval every ``FitResult`` reports, as a two-sided coverage probability."""
