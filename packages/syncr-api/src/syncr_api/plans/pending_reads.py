"""The proposal a week is holding, as the value its route answers with.

Beside the service rather than inside it, for the reason the readings, the history page, the
emptiness and the currency are: a composed value is built by the module that owns its rules, and the
service's job is to decide which reads to make and in what order.

Two of the slot's columns are JSONB and both are rebuilt through the domain's own constructors here,
so a corrupt row is refused where it is read rather than rendered as a proposal that breaks the
rules a proposal is defined by. Three of its columns are deliberately not read: the objective
breakdown is the learning layer's substrate rather than something a screen renders, and the
candidate document is the whole proposed week, which is a second document in a payload whose reader
already holds the live one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.plans.candidates import awaiting_approval
from syncr_api.plans.stored_proposals import read_proposal_diff
from syncr_api.plans.stored_verdicts import verdict_of
from syncr_api.plans.week_views import PendingProposal

if TYPE_CHECKING:
    from syncr_api.plans.records import PendingProposalRecord


def pending_proposal(held: PendingProposalRecord) -> PendingProposal:
    """One stored slot as the value its route answers with."""
    return PendingProposal(
        iso_week=held.iso_week,
        diff=read_proposal_diff(held.proposal_diff, held.iso_week),
        verdict=verdict_of(held.verdict),
        candidate_adjustment=awaiting_approval(held),
        input_version=held.input_version,
        weight_set_version=held.weight_set_version,
        operation_id=held.operation_id,
        created_at=held.created_at,
    )
