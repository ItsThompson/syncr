"""Persistence for off-plan periods. Tenant-scoped.

Every statement is built from the scoped base, so the tenant predicate is applied by the base
rather than remembered per method, and a repository cannot be constructed without a tenant to
scope to.

:meth:`OffPlanPeriodRepository.for_span` is the read a week's assembly makes, and it answers
with **unclipped** records. A period running from Friday to Monday is one row, and both weeks
that hold part of it read the whole row: clipping it to a week's span is the assembler's, so
storage never has to decide which week a span belongs to.

Its predicate is the half-open overlap test, ``row.start < span.end AND span.start < row.end``,
which is the SQL statement of ``Interval.overlaps``. Two independent statements of one rule,
in two languages, so ``tests/test_off_plan_periods_integration.py`` crosses them: the same
corpus of boundary pairs is answered by Postgres and by the domain, and the two answers have to
agree. A period that ends exactly where the week starts is therefore excluded by both.

No method commits. One request is one transaction, opened and committed by
:func:`syncr_api.core.db.get_transaction`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from syncr_api.core.repository import TenantScopedRepository
from syncr_api.offplan.models import OffPlanPeriodRow
from syncr_api.offplan.records import OffPlanPeriodRecord
from syncr_domain.intervals import Interval

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy import Select

    from syncr_domain.identifiers import OffPlanPeriodId


class OffPlanPeriodRepository(TenantScopedRepository):
    """Lists, reads, creates, updates, and removes this tenant's off-plan periods."""

    async def list_all(self) -> tuple[OffPlanPeriodRecord, ...]:
        """Every period this tenant has declared, earliest first."""
        found = await self._session.scalars(self._ordered())
        return tuple(_as_record(row) for row in found)

    async def for_span(self, span: Interval) -> tuple[OffPlanPeriodRecord, ...]:
        """Every period overlapping ``span``, unclipped, earliest first.

        The read a week's assembly and the budget denominator both make. A period reaching
        past either end of ``span`` is returned whole, so its caller decides what to do with
        the part outside.
        """
        found = await self._session.scalars(
            self._ordered().where(
                OffPlanPeriodRow.start < span.end, span.start < OffPlanPeriodRow.end
            )
        )
        return tuple(_as_record(row) for row in found)

    async def find(self, period_id: OffPlanPeriodId) -> OffPlanPeriodRecord | None:
        """One period of this tenant's, or ``None``.

        Scoped, so another tenant's identifier reads as absent rather than as forbidden,
        which is what makes the 404 the service raises truthful.
        """
        found = await self._session.scalar(
            self.scoped_select(OffPlanPeriodRow).where(OffPlanPeriodRow.id == period_id)
        )
        return _as_record(found) if found is not None else None

    async def create(
        self,
        *,
        interval: Interval,
        keep_frame: bool,
        label: str | None,
        created_at: datetime,
    ) -> OffPlanPeriodRecord:
        """Persist one period. The caller has already rejected an overlap."""
        row = OffPlanPeriodRow(
            id=uuid4(),
            tenant_id=self.tenant_id,
            start=interval.start,
            end=interval.end,
            keep_frame=keep_frame,
            label=label,
            created_at=created_at,
        )
        self._session.add(row)
        # Flushed here so a constraint violation surfaces as this call's failure rather than at
        # commit, after the caller has reported success.
        await self._session.flush()
        return _as_record(row)

    async def write(
        self,
        period_id: OffPlanPeriodId,
        *,
        interval: Interval,
        keep_frame: bool,
        label: str | None,
    ) -> None:
        """Replace every editable value on one period. The caller merged its partial update.

        Whole-record rather than field-by-field, matching the settings and Area writes: a
        partial update is validated as a set, because moving one bound is checked against the
        other and against every other period, so the caller holds the merged values anyway.
        """
        await self._session.execute(
            self.scoped_update(OffPlanPeriodRow)
            .where(OffPlanPeriodRow.id == period_id)
            .values(
                start=interval.start,
                end=interval.end,
                keep_frame=keep_frame,
                label=label,
            )
        )

    async def remove(self, period_id: OffPlanPeriodId) -> None:
        """Delete one period of this tenant's, so its span is on plan again."""
        await self._session.execute(
            self.scoped_delete(OffPlanPeriodRow).where(OffPlanPeriodRow.id == period_id)
        )

    def _ordered(self) -> Select[tuple[OffPlanPeriodRow]]:
        return self.scoped_select(OffPlanPeriodRow).order_by(
            OffPlanPeriodRow.start, OffPlanPeriodRow.id
        )


def _as_record(row: OffPlanPeriodRow) -> OffPlanPeriodRecord:
    return OffPlanPeriodRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        interval=Interval(row.start, row.end),
        keep_frame=row.keep_frame,
        label=row.label,
        created_at=row.created_at,
    )
