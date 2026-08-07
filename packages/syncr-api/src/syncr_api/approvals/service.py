"""Approving the pending proposal, in both its forms, as one transaction.

```
approve(week)
  └── ONE TRANSACTION
        ├── weekVersion.held(week)     THE LOCK. Taken before anything is read
        ├── read the slot. Empty ──▶ 409. There is nothing left to approve
        ├── refuse a document that changes anything the proposal did not show (assent.py)
        ├── pending.clear(week)
        ├── revisions.append(approved, document=the slot's, reason=user|tradeoff_approved)
        ├── adjustments.upsert(the candidate concession)   NOW it is real
        ├── weekVersion.bump()                            REQUIRED. See below
        └── operations.enqueue(projection)
```

## The lock is taken before the read, because the refusal is decided from what was read

The refusal below compares the slot's document against the live plan, and an approval that read the
live plan and then wrote would be deciding against a plan another transaction can replace in
between. The one that does replace it is the solve dispatch's conditional write, which appends an
``applied`` revision when its candidate fills empty space and nothing else. Committing inside this
window, that revision is invisible to the comparison, and the approved document then drops the block
it added with **nothing scheduled to put it back**: approval requests no solve, and the solve that
appended the fill has already reported ``succeeded``.

So the week's version row is taken ``FOR UPDATE`` first. It is the same row the conditional write
locks, which is what makes the two paths serialize without a lock of their own, and it is what the
version row is already called: the single serialization point for anything that changes the live
plan.

**One lock covers every appender, and that is read off the appenders rather than assumed.** Two
places append an ``applied`` revision. The dispatch takes this row first, so it either waits for
this transaction and then finds its own version moved, or it commits first and this comparison sees
its fill. The week producer takes no lock, and it cannot reach a week that holds a pending proposal:
both of its callers refuse a week that already has a live revision, and a week whose first solve
filled the slot has one, because a first plan for a week classifies as fills and is appended rather
than proposed.

A week with no version row is not locked and needs none. Nothing can append to such a week inside
this window: the conditional write treats the absent row as a mismatch and writes nothing.

## What the slot's DELETE decides, and which state each mechanism holds in

Two mechanisms make two concurrent approvals of one slot into one approval, and which of them does
the work depends on whether the week has a version row yet.

**With a row**, this transaction holds it from before the read, so the second approval waits on the
lock and then reads a slot that is already gone: it is refused by the empty-slot branch and never
reaches the DELETE.

**With no row** there is nothing to lock. Nothing needs locking against an ADOPTION in that state,
because the conditional write treats an absent row as a mismatch and writes nothing at all; but two
APPROVALS both read the slot and both proceed, so what makes them one is the DELETE's own row lock
and the check on its answer. A request that finds nothing to delete owns no approval and is refused
before it appends.

**The POSITION of the DELETE is not load-bearing and nothing here claims it is.** The five writes
are one transaction, so a loser's append rolls back with its failed DELETE wherever the statement
sits. What may not be dropped is the answer being checked, and above it the lock.

``PP3`` holds for the same reason: a failure at any step rolls every other write back, so the slot
is intact and the proposal is still approvable.

## Why the bump is here rather than only an invariant elsewhere

Approval changes the live plan, and the live plan is a solve input. A solve that began before the
approval and finishes after it would otherwise match on an unchanged version and adopt a
classification computed against a plan of record that no longer exists, together with a document
solved without the concession this approval just persisted. The bump makes that solve's
conditional write fail, which is what marks it ``superseded`` and enqueues exactly one follow-up.

Nothing here asks for a solve. The bump is what a RUNNING solve has to see; the document the user
approved is the plan of record, so a solve requested from this path would propose changing what
they just accepted.

## The version the approved revision records is the one it was SOLVED against

``PP5``: a proposal may be approved while its ``input_version`` is behind the week's current
version. The user is approving what they can see, and the solve the newer mutation already
enqueued will propose any correction. So the revision records the version the document was
produced from, and the response reports both figures, which is what makes the discrepancy visible
rather than hidden.

## Infeasibility is not consulted, anywhere on this path

``US-FEAS-05``: approval of a knowingly-broken week is permitted, so there is no verdict read
here, no shortfall check, and nothing to make one. Syncr informs; it does not govern.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.concessions.config import ISO_WEEK_FIELD
from syncr_api.core.errors import Conflict
from syncr_api.core.iso_weeks import require_an_iso_week
from syncr_api.core.principal import require_scope
from syncr_api.core.scopes import Scope
from syncr_api.plans.assent import unassented_changes
from syncr_api.plans.candidates import from_document, stored_reductions
from syncr_api.plans.config import APPROVED
from syncr_api.plans.errors import ClassificationRejected
from syncr_api.plans.stored_documents import plan_document
from syncr_api.plans.stored_proposals import read_proposal_diff
from syncr_api.solving.config import PROJECTION
from syncr_common.logging import get_logger
from syncr_common.metrics import measured
from syncr_domain.plan import RevisionReason

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from syncr_api.core.clock import Clock
    from syncr_api.core.principal import Principal
    from syncr_api.plans.adjustments import WeekAdjustmentRepository
    from syncr_api.plans.config import RevisionReason as StoredReason
    from syncr_api.plans.proposals import PendingProposalRepository
    from syncr_api.plans.records import (
        PendingProposalRecord,
        PlanRevisionRecord,
        WeekAdjustmentRecord,
    )
    from syncr_api.plans.repository import PlanRepository
    from syncr_api.plans.versions import WeekInputVersionRepository
    from syncr_api.solving.lifecycle import OperationLifecycle
    from syncr_api.solving.records import OperationRecord
    from syncr_domain.identifiers import PlanRevisionId
    from syncr_domain.plan import PlanDocument
    from syncr_domain.proposals import BlockChange
    from syncr_domain.weeks import IsoWeek

_log = get_logger("syncr.approvals")

# What both refusals over a slot that is no longer approvable say. One statement, because the
# empty slot and the slot another approval took a moment ago are the same fact to a client: what
# it was looking at is gone, and re-reading the week shows what replaced it.
REPLACED_DETAIL = (
    "That proposal has been replaced, so there is nothing left to approve. Nothing was changed: "
    "the week keeps the plan it holds, and reading the week again shows whatever is waiting for "
    "you now."
)

# How many blocks a refusal names before it stops. A week holds hundreds and a message listing
# every one of them is a sentence nobody reads.
TITLES_IN_A_REFUSAL = 3


@dataclass(frozen=True, slots=True, kw_only=True)
class ApprovedWeek:
    """What one approval wrote: the revision, the concession, the version, and the projection.

    Four values because a client redraws on all four: the plan of record it now holds, the
    concession the verdict panel lists from here on, the version it reasons optimistically with,
    and the write to the user's calendar that follows.

    ``approved_at`` is the instant this transaction stamped. Carried beside the revision because the
    revision's own column is nullable -- an ``applied`` revision states no assent -- and a response
    that narrowed it would be narrowing a value this act cannot leave absent.
    """

    revision: PlanRevisionRecord
    adjustment: WeekAdjustmentRecord | None
    approved_at: datetime
    input_version: int
    projection: OperationRecord


class ApprovalService:
    """One tenant's approvals: the pending proposal, and one carrying a tradeoff."""

    def __init__(
        self,
        *,
        revisions: PlanRepository,
        proposals: PendingProposalRepository,
        adjustments: WeekAdjustmentRepository,
        versions: WeekInputVersionRepository,
        operations: OperationLifecycle,
        clock: Clock,
    ) -> None:
        self._revisions = revisions
        self._proposals = proposals
        self._adjustments = adjustments
        self._versions = versions
        self._operations = operations
        self._clock = clock

    @measured("approvals")
    async def approve(self, principal: Principal, iso_week: str) -> ApprovedWeek:
        """Make the pending proposal for ``iso_week`` the plan of record."""
        require_scope(principal, Scope.PLAN_WRITE)
        week = require_an_iso_week(iso_week, field=ISO_WEEK_FIELD)
        now = self._clock()
        # Before the slot and the live plan are read, because what is read decides the refusal and
        # an adoption committing in between would be invisible to it. The module docstring says why
        # this row, and why one lock covers every path that appends.
        await self._versions.held(week)
        pending = await self._proposals.find(week)
        if pending is None:
            raise Conflict(REPLACED_DETAIL)
        document = plan_document(pending.document)
        live = await self._revisions.latest(week)
        self._require_only_the_changes_the_user_was_shown(
            week, pending, document, None if live is None else plan_document(live.document), now=now
        )
        return await self._written(
            week, pending, document, superseding=None if live is None else live.id, now=now
        )

    def _require_only_the_changes_the_user_was_shown(
        self,
        week: IsoWeek,
        pending: PendingProposalRecord,
        document: PlanDocument,
        live: PlanDocument | None,
        *,
        now: datetime,
    ) -> None:
        """Refuse a document that would change the live plan in a way no diff named.

        Two refusals with two causes and one remedy. The document may restate a part of the week
        that elapsed between the solve and this approval, which the classification could not have
        compared because the instant it was decided against had not arrived. Or the live plan may
        have advanced under the slot, which an auto-applied fill does with no defect involved, so
        approving the document would drop the block that fill added without ever asking.

        Both leave the plan of record alone and both are answered by asking for a solve, which
        proposes the same intent against the week as it now stands.
        """
        try:
            unassented = unassented_changes(
                live, document, read_proposal_diff(pending.proposal_diff, week), now=now
            )
        except ClassificationRejected as restated:
            _log.info(
                "approvals.proposal.restates_the_past",
                iso_week=str(week),
                input_version=pending.input_version,
                refusal=str(restated),
            )
            raise Conflict(
                f"Part of {week} has been lived since that proposal was made, and the proposal "
                "places a block the week has already reached somewhere else. Nothing was changed: "
                "the week you lived stays the plan of record. Ask for a solve of the week, and "
                "approve what it proposes for the time that is left."
            ) from restated
        if not unassented:
            return
        _log.info(
            "approvals.proposal.changes_more_than_it_showed",
            iso_week=str(week),
            input_version=pending.input_version,
            blocks=len(unassented),
        )
        raise Conflict(
            f"{_named(unassented)} in {week} since that proposal was made, and the proposal does "
            "not say so, so approving it would move or remove them without asking. Nothing was "
            "changed: the plan of record keeps them. Ask for a solve of the week, and approve what "
            "it proposes."
        )

    async def _written(
        self,
        week: IsoWeek,
        pending: PendingProposalRecord,
        document: PlanDocument,
        *,
        superseding: PlanRevisionId | None,
        now: datetime,
    ) -> ApprovedWeek:
        """The transaction's writes, and the claim deciding which of two approvals performs them."""
        if not await self._proposals.clear(week):
            # Reached only for a week with no version row, where the lock above had nothing to
            # take: two approvals then both read the slot, and this is what makes them one. With a
            # row, the loser waits on the lock and is refused by the empty-slot branch instead.
            raise Conflict(REPLACED_DETAIL)
        reason = _reason_for(pending)
        revision = await self._revisions.append(
            document=pending.document,
            objective_breakdown=pending.objective_breakdown,
            status=APPROVED,
            reason=reason,
            weight_set_version=pending.weight_set_version,
            input_version=pending.input_version,
            created_at=now,
            approved_at=now,
            supersedes_id=superseding,
        )
        adjustment = await self._persisted(week, pending, now=now)
        version = await self._versions.bump(week, at=now)
        projection = await self._operations.enqueue(kind=PROJECTION, iso_week=week)
        _log.info(
            "approvals.proposal.approved",
            iso_week=str(week),
            revision_id=str(revision.id),
            reason=reason,
            solved_against_version=pending.input_version,
            input_version=version,
            blocks=len(document.blocks),
            adjustment_id=None if adjustment is None else str(adjustment.id),
            operation_id=str(pending.operation_id),
            projection_id=str(projection.id),
        )
        return ApprovedWeek(
            revision=revision,
            adjustment=adjustment,
            approved_at=now,
            input_version=version,
            projection=projection,
        )

    async def _persisted(
        self, week: IsoWeek, pending: PendingProposalRecord, *, now: datetime
    ) -> WeekAdjustmentRecord | None:
        """The concession this approval makes real, or ``None`` when the slot carried none.

        Read back through the one reader of a serialized candidate, so the concession stored is
        the one the assembler folded when it produced the document being approved.

        **The row takes the candidate's own identifier**, because the document being appended beside
        it already names that identifier: the solver writes the ids of the concessions it solved
        under into ``PlanDocument.adjustments``, so a row minted with a fresh one would leave the
        approved revision naming a concession nothing holds.

        Approving the same tradeoff twice does not double its effect, and the unique index on
        ``(week, kind, target)`` is what makes that true rather than this upsert having been
        written correctly.
        """
        if pending.candidate_adjustment is None:
            return None
        candidate = from_document(pending.candidate_adjustment, dates=week.dates())
        return await self._adjustments.upsert(
            iso_week=week,
            kind=candidate.kind.value,
            target_id=candidate.target_id,
            created_at=now,
            created_by_operation_id=pending.operation_id,
            adjustment_id=candidate.adjustment_id,
            reductions=stored_reductions(candidate),
            delta_minutes=candidate.delta_minutes,
        )


def _reason_for(pending: PendingProposalRecord) -> StoredReason:
    """Which approval this is, decided by what the slot carries rather than by the caller.

    A client cannot state it, so a tradeoff approval cannot be recorded as an ordinary one and the
    history says which act each revision was.
    """
    if pending.candidate_adjustment is None:
        return RevisionReason.USER_APPROVED.value
    return RevisionReason.TRADEOFF_APPROVED.value


def _named(changes: Sequence[BlockChange]) -> str:
    """The blocks a refusal names, bounded, because a week holds hundreds of them."""
    titles = sorted({change.title for change in changes})
    shown = ", ".join(titles[:TITLES_IN_A_REFUSAL])
    if len(titles) <= TITLES_IN_A_REFUSAL:
        return f"{shown} changed"
    return f"{shown} and {len(titles) - TITLES_IN_A_REFUSAL} more changed"
