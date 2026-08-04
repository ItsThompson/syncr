"""Persistence for routines. Tenant-scoped.

Every statement is built from the scoped base, so the tenant predicate is applied by the base
rather than remembered per method, and a repository cannot be constructed without a tenant to
scope to.

Reads are ordered by target time, which is the order the day runs: the frame is read as a whole
by the assembler and rendered as a whole by the grid, so there is no read of one routine except
by identifier.

No method commits. One request is one transaction, opened and committed by
:func:`syncr_api.core.db.get_transaction`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from syncr_api.core.repository import TenantScopedRepository
from syncr_api.routines.models import RoutineRow
from syncr_api.routines.records import RoutineRecord

if TYPE_CHECKING:
    from datetime import datetime, time

    from syncr_api.routines.records import RoutineId


class RoutineRepository(TenantScopedRepository):
    """Lists, reads, creates, updates, and removes this tenant's routines."""

    async def list_all(self) -> tuple[RoutineRecord, ...]:
        """Every routine this tenant has declared, in the order the day runs."""
        found = await self._session.scalars(
            self.scoped_select(RoutineRow).order_by(RoutineRow.target_time, RoutineRow.id)
        )
        return tuple(_as_record(row) for row in found)

    async def find(self, routine_id: RoutineId) -> RoutineRecord | None:
        """One routine of this tenant's, or ``None``.

        Scoped, so another tenant's identifier reads as absent rather than as forbidden, which
        is what makes the 404 the service raises truthful.
        """
        found = await self._session.scalar(
            self.scoped_select(RoutineRow).where(RoutineRow.id == routine_id)
        )
        return _as_record(found) if found is not None else None

    async def create(
        self,
        *,
        title: str,
        target_time: time,
        duration_minutes: int,
        min_duration_minutes: int,
        flex_band_minutes: int,
        created_at: datetime,
    ) -> RoutineRecord:
        """Persist one routine. The caller has already validated its span.

        There is no ``area_id`` parameter, and there is no column to take one: a routine defines
        how much time exists rather than competing for it.
        """
        row = RoutineRow(
            id=uuid4(),
            tenant_id=self.tenant_id,
            title=title,
            target_time=target_time,
            duration_minutes=duration_minutes,
            min_duration_minutes=min_duration_minutes,
            flex_band_minutes=flex_band_minutes,
            created_at=created_at,
        )
        self._session.add(row)
        # Flushed here so a constraint violation surfaces as this call's failure rather than at
        # commit, after the caller has reported success.
        await self._session.flush()
        return _as_record(row)

    async def write(
        self,
        routine_id: RoutineId,
        *,
        title: str,
        target_time: time,
        duration_minutes: int,
        min_duration_minutes: int,
        flex_band_minutes: int,
    ) -> None:
        """Replace every editable value on one routine. The caller has merged its partial update.

        Whole-record rather than field-by-field, for the same reason the settings write is: a
        floor and a target are validated as a pair, so the caller holds the merged values anyway.
        """
        await self._session.execute(
            self.scoped_update(RoutineRow)
            .where(RoutineRow.id == routine_id)
            .values(
                title=title,
                target_time=target_time,
                duration_minutes=duration_minutes,
                min_duration_minutes=min_duration_minutes,
                flex_band_minutes=flex_band_minutes,
            )
        )

    async def remove(self, routine_id: RoutineId) -> None:
        """Delete one routine of this tenant's."""
        await self._session.execute(
            self.scoped_delete(RoutineRow).where(RoutineRow.id == routine_id)
        )


def _as_record(row: RoutineRow) -> RoutineRecord:
    return RoutineRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        title=row.title,
        target_time=row.target_time,
        duration_minutes=row.duration_minutes,
        min_duration_minutes=row.min_duration_minutes,
        flex_band_minutes=row.flex_band_minutes,
        created_at=row.created_at,
    )
