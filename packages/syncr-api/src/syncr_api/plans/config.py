"""The closed vocabularies and bounds the plan-side tables are defined against.

Every set here is enumerated in `07-plan-storage.md` or `04-domain-model.md`. Each is
stated once and read twice: the type annotation a repository takes, and the check
constraint the database enforces. The value semantics arrive with the milestone that
computes them; what this module fixes is that a column cannot hold a value no reader
knows.

The document shapes (``PlanDocument``, ``Block``, ``ReasonRecord``, ``BindingRef``,
``Verdict``, ``ProposalDiff``) are deliberately absent. They live in ``syncr_domain`` and
they are written by a Pydantic model, so the storage layer holds their JSONB column and
none of their interior.
"""

from __future__ import annotations

from typing import Final, Literal

PLAN_REVISIONS_TABLE = "plan_revisions"
PENDING_PROPOSALS_TABLE = "pending_proposals"
WEEK_INPUT_VERSIONS_TABLE = "week_input_versions"
PINS_TABLE = "pins"
BLOCK_OUTCOMES_TABLE = "block_outcomes"
EDIT_EVENTS_TABLE = "edit_events"
CONFLICTS_TABLE = "conflicts"
WEEK_ADJUSTMENTS_TABLE = "week_adjustments"
VERDICT_EVENTS_TABLE = "verdict_events"

# A revision is `applied` when the authority rule let it through without asking, and
# `approved` when the user assented. There is no third state: a plan is either the live
# plan or it is the pending slot, which is a different table.
type RevisionStatus = Literal["applied", "approved"]
APPLIED: Final[RevisionStatus] = "applied"
APPROVED: Final[RevisionStatus] = "approved"
REVISION_STATUSES: Final = (APPLIED, APPROVED)

type RevisionReason = Literal[
    "auto_applied_fill",
    "user_approved",
    "tradeoff_approved",
    "anchor_delta",
    "materialized",
    "horizon_advanced",
]
REVISION_REASONS: Final = (
    "auto_applied_fill",
    "user_approved",
    "tradeoff_approved",
    "anchor_delta",
    "materialized",
    "horizon_advanced",
)

# The five reality states. `presumed` is the default and teaches nothing; the other four
# are what the user said happened.
OUTCOME_STATES: Final = ("presumed", "completed", "partial", "skipped", "moved")
PARTIAL_OUTCOME: Final = "partial"
MOVED_OUTCOME: Final = "moved"

# `kept-both` is a legitimate resolution: users multitask.
CONFLICT_RESOLUTIONS: Final = ("moved", "kept-both", "retyped")

# A verdict's provenance. `probe` proves infeasibility only; `solver` is authoritative.
VERDICT_PROVENANCES: Final = ("probe", "solver")

# Where a verdict was computed. A read is absent from this set on purpose: no read path
# appends a verdict event, and `maintainer` is what records a time-driven transition.
VERDICT_SURFACES: Final = ("pin", "mutation", "tradeoff", "solve", "cli", "maintainer")

# The four tradeoff concessions an approval can persist.
type AdjustmentKind = Literal["drop_item", "reduce_routine", "breach_floor", "accept_partial"]
ADJUSTMENT_KINDS: Final = ("drop_item", "reduce_routine", "breach_floor", "accept_partial")

# A block id is a hash of the week and the content identity, derived on construction and
# never minted. This is the width the column reserves for one, not a claim about the
# hash: the derivation lives in the domain package with the value types.
BLOCK_ID_MAX_LENGTH = 64

# The first version of a week's inputs. A missing row means nobody has touched the week
# yet, so the first reference creates it here.
FIRST_INPUT_VERSION = 1
