"""The closed vocabularies and bounds the plan-side tables are defined against.

Every set here is closed: each is stated once and read twice, as the type annotation a
repository takes and as the check constraint the database enforces. What computes the values
and what they mean to a solve arrive with the code that reads them; what this module fixes is
that a column cannot hold a value no reader knows.

The document shapes (``PlanDocument``, ``Block``, ``ReasonRecord``, ``BindingRef``,
``Verdict``, ``ProposalDiff``) are deliberately absent. They live in ``syncr_domain`` and
they are written by a Pydantic model, so the storage layer holds their JSONB column and
none of their interior.
"""

from __future__ import annotations

from typing import Final, Literal

from sqlalchemy import text

from syncr_domain import plan as plan_document
from syncr_domain.identity import BLOCK_ID_LENGTH

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

# What caused a revision to exist. The vocabulary is the plan document's, in the domain
# package, and the tuple the check constraint reads is derived from it so the column and the
# document cannot disagree. The `Literal` below is the same six members written as a type, so
# a repository signature narrows a caller's string; `tests/test_plan_vocabulary.py` asserts the
# two are one set.
type RevisionReason = Literal[
    "auto_applied_fill",
    "user_approved",
    "tradeoff_approved",
    "anchor_delta",
    "materialized",
    "horizon_advanced",
]
REVISION_REASONS: Final = tuple(reason.value for reason in plan_document.RevisionReason)

# The five reality states. `presumed` is the default and teaches nothing; the other four
# are what the user said happened.
OUTCOME_STATES: Final = ("presumed", "completed", "partial", "skipped", "moved")
PARTIAL_OUTCOME: Final = "partial"
MOVED_OUTCOME: Final = "moved"

# `kept-both` is a legitimate resolution: users multitask.
CONFLICT_RESOLUTIONS: Final = ("moved", "kept-both", "retyped")
MOVED_RESOLUTION: Final = "moved"
KEPT_BOTH_RESOLUTION: Final = "kept-both"
RETYPED_RESOLUTION: Final = "retyped"
type ConflictResolution = Literal["moved", "kept-both", "retyped"]

# One question per commitment and block, and the two states that answer "already asked". An open
# conflict is waiting for an answer, and one the user answered by accepting the overlap is never
# re-raised; a `moved` or a `retyped` asked for a change, so the same collision afterwards is a new
# event rather than the same question. Stated once and read twice, as the partial unique index the
# table declares and as the conflict target the raise infers, so an insert cannot claim to be
# idempotent over a predicate the index does not hold.
UNANSWERED_CONFLICT_INDEX: Final = "uq_conflicts_tenant_id_anchor_id_block_id"
UNANSWERED_CONFLICT: Final = text(f"resolved_at IS NULL OR resolution = '{KEPT_BOTH_RESOLUTION}'")

# A verdict's provenance. `probe` proves infeasibility only; `solver` is authoritative.
VERDICT_PROVENANCES: Final = ("probe", "solver")

# Where a verdict was computed. A read is absent from this set on purpose: no read path
# appends a verdict event, and `maintainer` is what records a time-driven transition.
VERDICT_SURFACES: Final = ("pin", "mutation", "tradeoff", "solve", "cli", "maintainer")

# The four tradeoff concessions an approval can persist. The vocabulary is the assembler's
# and the reason record's, in the domain package, and the tuple the check constraint reads is
# derived from it so the column and the concession cannot disagree. The `Literal` below is the
# same four members written as a type, so a repository signature narrows a caller;
# `tests/test_plan_vocabulary.py` asserts the two are one set.
type AdjustmentKind = Literal["drop_item", "reduce_routine", "breach_floor", "accept_partial"]
ADJUSTMENT_KINDS: Final = tuple(kind.value for kind in plan_document.AdjustmentKind)

# A block id is a hash of the week and the content identity, derived on construction and
# never minted. The column reserves exactly what the derivation produces, taken from the
# derivation itself rather than restated, so a change to the hash cannot outgrow the column.
BLOCK_ID_MAX_LENGTH = BLOCK_ID_LENGTH

# The first version of a week's inputs. A missing row means nobody has touched the week
# yet, so the first reference creates it here.
FIRST_INPUT_VERSION = 1
