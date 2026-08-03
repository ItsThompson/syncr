"""The pending proposal slot: one per week, replaced in place, cleared on approval.

A proposal is not a fact. Nobody agreed to it, it may never have been rendered, and the
solver that produced it will produce another one the moment anything changes. So it is a
slot rather than a log, and the primary key on ``(tenant_id, iso_week)`` is what makes that
a property of the database: replacement can only be an upsert, because a second row for a
week is rejected.

What would be lost by overwriting is the per-week plan of record, and that is a different
table, appended and never replaced.
"""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

from sqlalchemy.dialects.postgresql import insert

from syncr_api.core.repository import TenantScopedRepository
from syncr_api.core.tenancy import TENANT_ID_COLUMN
from syncr_api.plans.derivation import derive_iso_week
from syncr_api.plans.models import PendingProposal
from syncr_api.plans.records import PendingProposalRecord
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_api.core.columns import JsonDocument
    from syncr_domain.identifiers import OperationId


class PendingProposalRepository(TenantScopedRepository):
    """The one proposal awaiting assent per week, for one tenant."""

    async def replace(
        self,
        *,
        document: JsonDocument,
        proposal_diff: JsonDocument,
        objective_breakdown: JsonDocument,
        verdict: JsonDocument,
        input_version: int,
        operation_id: OperationId,
        created_at: datetime,
        candidate_adjustment: JsonDocument | None = None,
    ) -> PendingProposalRecord:
        """Put this proposal in the week's slot, discarding whatever was there.

        The week is derived from the document, so the slot a proposal lands in is the week
        the proposal is for and cannot be pointed elsewhere by a caller.
        """
        iso_week = derive_iso_week(document)
        values = {
            TENANT_ID_COLUMN: self.tenant_id,
            "iso_week": str(iso_week),
            "document": dict(document),
            "proposal_diff": dict(proposal_diff),
            "objective_breakdown": dict(objective_breakdown),
            "verdict": dict(verdict),
            "input_version": input_version,
            "operation_id": operation_id,
            "candidate_adjustment": (
                None if candidate_adjustment is None else dict(candidate_adjustment)
            ),
            "created_at": created_at,
        }
        # One statement, so a replacement cannot be observed as a week with no proposal:
        # a reader either sees the previous one or this one.
        statement = (
            insert(PendingProposal)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[TENANT_ID_COLUMN, "iso_week"],
                set_={key: value for key, value in values.items() if key not in _KEY_COLUMNS},
            )
            .returning(PendingProposal)
        )
        stored = (await self._session.scalars(statement)).one()
        return _as_record(stored)

    async def find(self, iso_week: IsoWeek) -> PendingProposalRecord | None:
        """The week's pending proposal, or ``None`` when the slot is empty."""
        found = await self._session.scalar(
            self.scoped_select(PendingProposal).where(PendingProposal.iso_week == str(iso_week))
        )
        return _as_record(found) if found is not None else None

    async def clear(self, iso_week: IsoWeek) -> bool:
        """Empty the week's slot, reporting whether it held anything.

        Approval clears the slot in the same transaction that appends the approved
        revision, so a proposal cannot be approved twice.
        """
        removed = await self._session.scalar(
            self.scoped_delete(PendingProposal)
            .where(PendingProposal.iso_week == str(iso_week))
            .returning(PendingProposal.iso_week)
        )
        return removed is not None


_KEY_COLUMNS = frozenset({TENANT_ID_COLUMN, "iso_week"})


def _as_record(proposal: PendingProposal) -> PendingProposalRecord:
    return PendingProposalRecord(
        tenant_id=proposal.tenant_id,
        iso_week=IsoWeek.parse(proposal.iso_week),
        document=deepcopy(proposal.document),
        proposal_diff=deepcopy(proposal.proposal_diff),
        objective_breakdown=deepcopy(proposal.objective_breakdown),
        verdict=deepcopy(proposal.verdict),
        input_version=proposal.input_version,
        operation_id=proposal.operation_id,
        candidate_adjustment=deepcopy(proposal.candidate_adjustment),
        created_at=proposal.created_at,
    )
