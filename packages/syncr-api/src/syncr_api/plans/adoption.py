"""Writing what a classification decided: the live plan, the pending slot, or nothing at all.

The authority rule says what a candidate plan may do. This is the write that follows from it, and
it is deliberately one place rather than three statements on a commit path, so "what happens to a
classification" has one answer and the conditional write around it has one thing to call.

| The classification | What is written |
|---|---|
| fills only | an ``applied`` revision carrying the candidate. The live plan advances |
| anything that moves or drops a block | the pending slot, replaced in place |
| empty | **nothing**. No revision, no slot, no row |

The empty row is the one worth stating: a solve that changes nothing leaves no trace beyond its own
operation record. Nothing is appended to a permanent table to record that nothing happened.

## A revision is appended only for a candidate that asks for nothing else

A candidate that fills empty space AND moves something is held whole. Applying the fills alone
would mean composing a document here out of the live plan and part of a candidate, which is a live
plan no solver produced, and the proposal stored beside it would then describe a live plan that had
just been replaced. So the fills wait with the moves, and the live plan advances only when the
candidate asks for no assent at all.

## The pending slot is not cleared when the live plan advances

A proposal held from an earlier solve stays in the slot when a later fill-only candidate appends a
revision, even though its diff was computed against the live plan as it then stood. That follows
the rule the approval path is stated over: the user approves what they can see, the approved
revision records the input version it was solved against, so the discrepancy is visible rather
than hidden. Clearing the slot instead would take away a proposal the user may be looking at and
enqueue nothing to replace it.

## What this module does not do

**It takes no lock and reads no version.** The conditional write that makes an adoption safe under
a concurrent mutation is the solve coordinator's, and it wraps this call rather than living inside
it: this module's whole job is that the three writes agree with one classification.

**It checks that the classification describes THIS candidate, as far as one document can say.**
Every change names a block, and every class but one names where the candidate wants it, so the
document either holds that block at that placement or the pair was mismatched. That is what stops a
classification of one candidate being written over another's document, which is the failure a
single-caller function is least likely to notice and most likely to persist.

**It does not check the candidate against the past, and that is a boundary rather than an
oversight.** The document written here carries the whole candidate, including the days the week has
already lived, so the rule that protects them is real and load-bearing; it lives in
:func:`~syncr_api.plans.authority.classify`, which holds both documents and the instant the rule is
decided against, and which refuses the pair outright. Repeating it here would need a second copy of
the live plan and a second reference instant, and a write-time instant later than the
classification's would refuse a candidate over a block that started while the solve ran, which is a
supersession for the version guard to answer rather than a defect.

**So one thing is left trusted, and it is stated rather than implied: nothing binds a classification
to having come from ``classify``.** A hand-built one paired with a matching document passes every
check here, and the past rule is the factory's. What the checks above cover is the mismatch a real
caller can produce by accident; what they cannot cover is a caller that computed the partition
itself, which no caller does and none should.

**It does not serialize a verdict or a concession.** The plan document and the proposal diff have
stored forms in this package and are written from their values here. The verdict and the candidate
adjustment reach the slot as the objects their own owners produced, exactly as the pending
proposal's repository takes them, because a second spelling of either would be a second answer to
what the week view reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from syncr_api.plans.config import APPLIED
from syncr_api.plans.errors import RevisionRejected
from syncr_api.plans.stored_documents import stored_document
from syncr_api.plans.stored_proposals import stored_proposal_diff
from syncr_common.logging import get_logger
from syncr_common.metrics import measured
from syncr_domain.plan import RevisionReason as DocumentReason

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from syncr_api.core.columns import JsonDocument
    from syncr_api.plans.authority import Classification
    from syncr_api.plans.config import RevisionReason
    from syncr_api.plans.conflicts import CommitmentReader, PlanConflictRepository
    from syncr_api.plans.proposals import PendingProposalRepository
    from syncr_api.plans.records import (
        ConflictRecord,
        PendingProposalRecord,
        PlanRevisionRecord,
    )
    from syncr_api.plans.repository import PlanRepository
    from syncr_domain.identifiers import OperationId
    from syncr_domain.plan import PlanDocument

_log = get_logger("syncr.plans")

# The reasons an `applied` revision may be appended for. Both are the authority rule letting a
# change through without asking: one filled empty space, and one is a calendar sync that freed or
# occupied it. The other four reasons name an approval or the maintainer, and neither of those is
# an adoption, so a revision appended here under one of them would say the user assented to a plan
# nobody showed them.
AUTO_APPLIED_REASONS: Final = frozenset(
    {DocumentReason.AUTO_APPLIED_FILL.value, DocumentReason.ANCHOR_DELTA.value}
)


@dataclass(frozen=True, slots=True, kw_only=True)
class Candidate:
    """One solve's answer, and the facts both possible writes need.

    ``verdict`` and ``candidate_adjustment`` are the shapes their own owners produced; every other
    field is a value this package can write. Held together because the two writes need overlapping
    subsets of them, and a signature carrying nine arguments cannot say which combinations are
    legal.
    """

    document: PlanDocument
    objective_breakdown: Mapping[str, float]
    verdict: JsonDocument
    weight_set_version: int
    input_version: int
    operation_id: OperationId
    candidate_adjustment: JsonDocument | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Adopted:
    """What a classification actually wrote. Every field is empty for a candidate that changed
    nothing.

    ``raised`` holds the conflicts this adoption raised and not the ones that were already open,
    because it is what a notification is sent for.
    """

    revision: PlanRevisionRecord | None = None
    proposal: PendingProposalRecord | None = None
    raised: tuple[ConflictRecord, ...] = ()

    def changed_the_live_plan(self) -> bool:
        """Whether the plan of record advanced, which is what a projection is enqueued for.

        A replaced proposal is not a change to the live plan: nobody has agreed to it, so the
        calendar on the user's phone still describes the week they are living.
        """
        return self.revision is not None


class PlanAdoption:
    """Turns one classification into the writes it names, for one tenant."""

    def __init__(
        self,
        *,
        revisions: PlanRepository,
        pending: PendingProposalRepository,
        conflicts: PlanConflictRepository,
        commitments: CommitmentReader,
    ) -> None:
        self._revisions = revisions
        self._pending = pending
        self._conflicts = conflicts
        self._commitments = commitments

    @measured("plan_adoption")
    async def adopt(
        self,
        classification: Classification,
        candidate: Candidate,
        *,
        reason: RevisionReason,
        at: datetime,
    ) -> Adopted:
        """Write what ``classification`` decided about ``candidate``, and answer with what landed.

        ``reason`` says which auto-application this is: a fill, or a calendar sync that freed or
        occupied space. It is refused for anything else, because the four remaining reasons name an
        approval or the plan horizon maintainer and neither of those passes through here.

        Raises :class:`~syncr_api.plans.errors.RevisionRejected` for such a reason, for a
        classification describing a different week than the candidate, and for one describing
        different blocks: in either case the diff would be stored under a document whose blocks its
        changes cannot be paired against.
        """
        _require_an_auto_applied_reason(reason)
        _require_one_week(classification, candidate.document)
        _require_the_classification_to_describe(classification, candidate.document)
        adopted = Adopted(
            revision=await self._appended(classification, candidate, reason=reason, at=at),
            proposal=await self._replaced(classification, candidate, at=at),
            raised=await self._raised(classification, at=at),
        )
        _log.info(
            "plans.classification.adopted",
            iso_week=str(candidate.document.iso_week),
            operation_id=str(candidate.operation_id),
            input_version=candidate.input_version,
            auto_applicable=len(classification.auto_applicable),
            proposed_added=len(classification.proposal_diff.added),
            proposed_removed=len(classification.proposal_diff.removed),
            proposed_moved=len(classification.proposal_diff.moved),
            conflicts_detected=len(classification.conflicts),
            conflicts_raised=len(adopted.raised),
            revision_id=None if adopted.revision is None else str(adopted.revision.id),
            proposal_replaced=adopted.proposal is not None,
        )
        return adopted

    async def _raised(
        self, classification: Classification, *, at: datetime
    ) -> tuple[ConflictRecord, ...]:
        """The conflicts this adoption raises, each carrying the commitment it is about.

        The commitments are read here rather than carried on the classification, because a
        classification is computed from two plan documents and an anchor block's binding names the
        OCCURRENCE: the series a recurring commitment belongs to is not in either document. The read
        is one statement over the anchors the detections name, and it is skipped entirely when there
        are none, which is every solve that found no collision.
        """
        detected = classification.conflicts
        return await self._conflicts.raise_all(
            detected,
            at=at,
            commitments=await self._commitments.commitments(
                [conflict.anchor_id for conflict in detected]
            ),
        )

    async def _appended(
        self,
        classification: Classification,
        candidate: Candidate,
        *,
        reason: RevisionReason,
        at: datetime,
    ) -> PlanRevisionRecord | None:
        """The revision this adoption appends, or ``None`` when the candidate asks for assent."""
        if not classification.applies_immediately():
            return None
        return await self._revisions.append(
            document=stored_document(candidate.document),
            objective_breakdown=dict(candidate.objective_breakdown),
            status=APPLIED,
            reason=reason,
            weight_set_version=candidate.weight_set_version,
            input_version=candidate.input_version,
            created_at=at,
        )

    async def _replaced(
        self, classification: Classification, candidate: Candidate, *, at: datetime
    ) -> PendingProposalRecord | None:
        """The week's slot, replaced with this candidate, or ``None`` when nothing needs assent."""
        if classification.proposal_diff.is_empty():
            return None
        return await self._pending.replace(
            document=stored_document(candidate.document),
            proposal_diff=stored_proposal_diff(classification.proposal_diff),
            objective_breakdown=dict(candidate.objective_breakdown),
            verdict=candidate.verdict,
            weight_set_version=candidate.weight_set_version,
            input_version=candidate.input_version,
            operation_id=candidate.operation_id,
            created_at=at,
            candidate_adjustment=candidate.candidate_adjustment,
        )


def _require_an_auto_applied_reason(reason: RevisionReason) -> None:
    if reason in AUTO_APPLIED_REASONS:
        return
    spelled = ", ".join(sorted(AUTO_APPLIED_REASONS))
    raise RevisionRejected(
        f"a revision the authority rule let through is appended for {spelled}, not for "
        f"{reason!r}: the other reasons name an approval or the horizon maintainer, so one of "
        "them here would say the user assented to a plan nobody showed them"
    )


def _require_one_week(classification: Classification, candidate: PlanDocument) -> None:
    """The classification has to be of this candidate, as far as the pair can say.

    The week is what is checkable and it is the one that matters: a diff is stored under the week
    its document names, so a diff of another week would hold changes naming blocks this week's
    document does not contain, and the grid would render a proposal target against nothing.

    Every class is read, the fills included. Those are not stored as a diff, but a classification
    of another week is a mispaired call whichever collection reveals it, and a guard that read only
    two of the three would report the pairing as sound whenever the third was the only one filled.
    """
    foreign = sorted(
        {
            str(change.iso_week)
            for change in (*classification.auto_applicable, *classification.proposal_diff.changes())
            if change.iso_week != candidate.iso_week
        }
        | {
            str(conflict.iso_week)
            for conflict in classification.conflicts
            if conflict.iso_week != candidate.iso_week
        }
    )
    if not foreign:
        return
    raise RevisionRejected(
        f"a classification of {', '.join(foreign)} was paired with a candidate for "
        f"{candidate.iso_week}: the diff is stored under the document's week, so its changes "
        "would name blocks that week does not hold"
    )


def _require_the_classification_to_describe(
    classification: Classification, candidate: PlanDocument
) -> None:
    """Every change names a block this document holds where the change says it wants it.

    The pairing check the write can perform on its own. Three of the four classes state where the
    candidate puts a block, so the document either holds that block at that placement or the
    classification is of a different candidate; a removal states the opposite, that the candidate
    drops it, so the document must not hold it at all.

    What this cannot see is the past, which needs the live plan the write does not receive. The
    module docstring says which of the two rules lives where, and why.
    """
    held = candidate.blocks_by_id()
    wanted = (
        *((change, change.after) for change in classification.auto_applicable),
        *((change, change.after) for change in classification.proposal_diff.added),
        *((change, change.after) for change in classification.proposal_diff.moved),
    )
    for change, placement in wanted:
        block = held.get(change.block_id)
        if block is None or block.interval != placement:
            raise RevisionRejected(
                f"the classification wants {change.title!r} at {placement}, and the candidate for "
                f"{candidate.iso_week} does not hold it there: a classification of one candidate "
                "written over another's document would store a diff nothing in the plan matches"
            )
    for change in classification.proposal_diff.removed:
        if change.block_id in held:
            raise RevisionRejected(
                f"the classification drops {change.title!r} and the candidate for "
                f"{candidate.iso_week} still holds it: a removal names a block the candidate does "
                "not place, so this pair describes two different candidates"
            )
