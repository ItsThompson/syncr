"""The frozen view the operation repository returns.

``failed_input_snapshot`` is absent on purpose. It exists so a failed solve is reproducible
locally, it is a whole resolved week, and every reader of an operation on the wire or in the
worker wants the status and the attempt rather than the snapshot. Loading it into every read
would carry a week of plan data through paths that never look at it, so the ticket that
builds the failure runbook reads it by identifier instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from syncr_api.core.columns import JsonObject
    from syncr_api.solving.config import OperationKind, OperationStatus
    from syncr_domain.identifiers import OperationId, PlanRevisionId, TenantId
    from syncr_domain.weeks import IsoWeek


@dataclass(frozen=True, slots=True)
class OperationRecord:
    """One tracked operation, as stored."""

    id: OperationId
    tenant_id: TenantId
    kind: OperationKind
    status: OperationStatus
    iso_week: IsoWeek | None
    source_id: UUID | None
    input_version: int | None
    candidate_adjustment: JsonObject | None
    scheduled_for: datetime
    started_at: datetime | None
    finished_at: datetime | None
    result_revision_id: PlanRevisionId | None
    superseded_by: OperationId | None
    attempt: int
    error_code: str | None
    error_message: str | None
