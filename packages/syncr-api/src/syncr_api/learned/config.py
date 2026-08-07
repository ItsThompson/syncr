"""The weight set's vocabulary, and the hand-tuned numbers P0 ships.

P0 ships hand-tuned weights through the SAME versioned mechanism fitted weights will use:
a row per version, one active per tenant, `origin = "hand-tuned"`, and the version recorded
on every revision, pin, and edit event that was produced under it. The fitted path is not a
separate code path, so there is nothing to build twice and nothing to switch between.

The magnitudes below are starting values, and the spec fixes their SHAPE rather than their
size: ``deadline_risk`` carries a high weight and grows nonlinearly as slack approaches
zero, which gives it practical dominance over ``budget_deviation`` without a rigid
lexicographic ordering, because a strict ordering would make a budget deviation of any size
invisible next to a deadline risk of any size and that is not how the user reasons.

| Weight | Why this value |
|---|---|
| ``deadline_risk`` | The highest, because a missed deadline is the failure the user notices |
| ``churn`` | Above the remaining terms: a plan that keeps rearranging is one the user stops
  trusting, and the approval gate makes an improved plan safe rather than free |
| ``budget_deviation`` | The steady-state objective, and the one every week has some of |
| ``time_of_day_misfit`` | Below budget: a stated window must yield to an impossible morning |
| ``fragmentation``, ``staleness`` | Shaping terms, felt over weeks rather than within one |
| ``context_switch`` | The lightest term weight; its per-change cost is the parameter beside it |

The fitted parameters start empty, not at a neutral value. A parameter below its maturity
gate is not applied at all rather than applied at a reduced weight, so an empty map is what
"nothing has been learned yet" looks like to the solver.

Retuning any of these ships a NEW version through this same mechanism. That is what the
versioning is for: comparison and rollback are a row and a flag rather than a redeploy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Literal

from syncr_api.core.settings import API_PREFIX

if TYPE_CHECKING:
    from collections.abc import Mapping

WEIGHT_SETS_TABLE = "weight_sets"

type WeightSetOrigin = Literal["hand-tuned", "fitted"]
HAND_TUNED: Final[WeightSetOrigin] = "hand-tuned"
FITTED: Final[WeightSetOrigin] = "fitted"
WEIGHT_SET_ORIGINS: Final = (HAND_TUNED, FITTED)

FIRST_WEIGHT_SET_VERSION = 1

ORIGIN_MAX_LENGTH = 16

# The seven objective term weights, plus the two parameters that shape two of those terms.
# A weight says how much a term matters against the other six; a parameter says the term's
# internal shape. Two numbers, two jobs: one is scale, one is unit.
P0_WEIGHTS: Final[Mapping[str, float]] = {
    "deadline_risk": 10.0,
    "budget_deviation": 3.0,
    "time_of_day_misfit": 2.0,
    "fragmentation": 1.5,
    "churn": 4.0,
    "context_switch": 1.0,
    "staleness": 1.5,
    "context_switch_cost": 1.0,
    "churn_tolerance": 3.0,
}

# The seven term weights, named so a reader of the objective can check the breakdown it
# returns against the weights that produced it.
OBJECTIVE_TERMS: Final = (
    "deadline_risk",
    "budget_deviation",
    "time_of_day_misfit",
    "fragmentation",
    "churn",
    "context_switch",
    "staleness",
)


# ---------------------------------------------------------------------------
# The three routes: the read the Learned screen makes, the version list, and the activation.
#
# Two prefixes rather than one, because the two collections answer different questions. `/learned`
# is the PARAMETERS and their maturity, which is what the screen renders; `/weight-sets` is the
# VERSIONS, which is what a comparison and a revert address. Nesting the second under the first
# would make the screen's own path the address of a row it does not render.
# ---------------------------------------------------------------------------

LEARNED_PREFIX: Final = f"{API_PREFIX}/learned"
WEIGHT_SETS_PREFIX: Final = f"{API_PREFIX}/weight-sets"

# Relative to each router's own prefix.
LEARNED_PATH: Final = ""
WEIGHT_SETS_PATH: Final = ""
ACTIVATE_PATH: Final = "/{version}/activate"

WEIGHT_SET_RESOURCE: Final = "weight set"
