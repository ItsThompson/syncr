"""The frozen views the plan repositories return.

A repository hands back one of these rather than a mapped row, for the reason every
repository in this application does: a mapped row carries a session, a load state, and
setters, so returning one would let a caller change a stored value outside the method that
owns the write. These carry values only.

That is why the JSONB payloads are copied out of the row rather than aliased, and why the
copy is DEEP: a plan document holds a list of blocks, so a top-level copy would still hand
back the row's own list, and ``record.document["blocks"].append(...)`` would change the
value the row holds. Nothing is persisted either way, because a plain JSONB column emits no
``UPDATE`` for a mutated value, so what the copy buys is that the record cannot be used to
reach the row it was read from.

``iso_week`` is an :class:`~syncr_domain.weeks.IsoWeek` here and a string in the column.
The conversion happens at this boundary, so no caller parses a week identifier and no
caller formats one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from syncr_api.core.columns import JsonObject
    from syncr_api.plans.config import AdjustmentKind, RevisionReason, RevisionStatus
    from syncr_domain.identifiers import OperationId, PlanRevisionId, TenantId
    from syncr_domain.weeks import IsoWeek


@dataclass(frozen=True, slots=True)
class PlanRevisionRecord:
    """One appended revision, exactly as it was stored."""

    id: PlanRevisionId
    tenant_id: TenantId
    iso_week: IsoWeek
    status: RevisionStatus
    reason: RevisionReason
    document: JsonObject
    objective_breakdown: JsonObject
    weight_set_version: int
    input_version: int
    supersedes_id: PlanRevisionId | None
    created_at: datetime
    approved_at: datetime | None

    def is_approved(self) -> bool:
        """Whether the user assented to this revision."""
        return self.approved_at is not None


@dataclass(frozen=True, slots=True)
class PendingProposalRecord:
    """The one proposal awaiting assent for a week."""

    tenant_id: TenantId
    iso_week: IsoWeek
    document: JsonObject
    proposal_diff: JsonObject
    objective_breakdown: JsonObject
    verdict: JsonObject
    input_version: int
    operation_id: OperationId
    candidate_adjustment: JsonObject | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class WeekAdjustmentRecord:
    """One approved concession for one week, kind, and target."""

    id: UUID
    tenant_id: TenantId
    iso_week: IsoWeek
    kind: AdjustmentKind
    target_id: UUID
    reductions: JsonObject
    delta_minutes: int | None
    created_at: datetime
    created_by_operation_id: OperationId
