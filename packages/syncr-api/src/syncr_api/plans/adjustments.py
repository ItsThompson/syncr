"""Approved tradeoff concessions: one row per week, kind, and target.

An approved concession has to survive, or the next solve reverts it. It is week-scoped, so
a decision taken for one hard week does not leak into the next, and several concessions
coexist in one week because each names a distinct target and kind.

The unique index is what makes a later concession REPLACE an earlier one for the same kind
and target. Otherwise approving "breach the floor by 1h20m" twice would breach it by
2h40m, and the collapse rule would rest on this upsert having been written correctly rather
than on the database.

Requesting a tradeoff writes nothing here. Only approval does.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast
from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert

from syncr_api.core.repository import TenantScopedRepository
from syncr_api.core.tenancy import TENANT_ID_COLUMN
from syncr_api.plans.facts import WeekAdjustment
from syncr_api.plans.records import WeekAdjustmentRecord
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from syncr_api.core.columns import JsonDocument
    from syncr_api.plans.config import AdjustmentKind
    from syncr_domain.identifiers import OperationId

# The columns a replacement leaves alone: the row's identity, and the concession it is a
# concession for. Keeping `id` is deliberate, because a plan document already records the
# adjustments it was solved under by identifier.
_RETAINED_COLUMNS = frozenset({"id", TENANT_ID_COLUMN, "iso_week", "kind", "target_id"})


class WeekAdjustmentRepository(TenantScopedRepository):
    """One tenant's approved concessions."""

    async def upsert(
        self,
        *,
        iso_week: IsoWeek,
        kind: AdjustmentKind,
        target_id: UUID,
        created_at: datetime,
        created_by_operation_id: OperationId,
        reductions: JsonDocument | None = None,
        delta_minutes: int | None = None,
    ) -> WeekAdjustmentRecord:
        """Record this concession, replacing any earlier one for the same kind and target."""
        values = {
            "id": uuid4(),
            TENANT_ID_COLUMN: self.tenant_id,
            "iso_week": str(iso_week),
            "kind": kind,
            "target_id": target_id,
            "reductions": {} if reductions is None else dict(reductions),
            "delta_minutes": delta_minutes,
            "created_at": created_at,
            "created_by_operation_id": created_by_operation_id,
        }
        statement = (
            insert(WeekAdjustment)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[TENANT_ID_COLUMN, "iso_week", "kind", "target_id"],
                set_={key: value for key, value in values.items() if key not in _RETAINED_COLUMNS},
            )
            .returning(WeekAdjustment)
        )
        stored = (await self._session.scalars(statement)).one()
        return _as_record(stored)

    async def for_week(self, iso_week: IsoWeek) -> list[WeekAdjustmentRecord]:
        """Every concession this week was granted. Read by the assembler as a solve input."""
        rows = await self._session.scalars(
            self.scoped_select(WeekAdjustment)
            .where(WeekAdjustment.iso_week == str(iso_week))
            .order_by(WeekAdjustment.kind, WeekAdjustment.created_at)
        )
        return [_as_record(row) for row in rows]


def _as_record(adjustment: WeekAdjustment) -> WeekAdjustmentRecord:
    return WeekAdjustmentRecord(
        id=adjustment.id,
        tenant_id=adjustment.tenant_id,
        iso_week=IsoWeek.parse(adjustment.iso_week),
        # The column's value set is enforced by a check constraint, so the narrowing here
        # states what the database already guarantees rather than re-checking it.
        kind=cast("AdjustmentKind", adjustment.kind),
        target_id=adjustment.target_id,
        reductions=adjustment.reductions,
        delta_minutes=adjustment.delta_minutes,
        created_at=adjustment.created_at,
        created_by_operation_id=adjustment.created_by_operation_id,
    )
