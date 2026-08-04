"""Persistence for habits. Tenant-scoped, and it holds no cursor and no debt figure.

Every statement is built from the scoped base, so the tenant predicate is applied by the base
rather than remembered per method, and a repository cannot be constructed without a tenant to
scope to.

There is no ``write_cursor`` and no ``write_debt``, and the absence is the design rather than
an omission. Both are projections of the outcome log, so a column to write would be a value
that can disagree with the log that produced it.

The write path replaces every editable value rather than taking a field at a time, for the same
reason the Area write does: a partial update is validated as a set, so the caller already holds
the merged values.

No method commits. One request is one transaction, opened and committed by
:func:`syncr_api.core.db.get_transaction`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.core.repository import TenantScopedRepository
from syncr_api.habits.models import HabitRow
from syncr_api.habits.records import HabitRecord, columns_of
from syncr_domain.habits import CadenceKind

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_domain.habits import Habit
    from syncr_domain.identifiers import AreaId, HabitId


class HabitRepository(TenantScopedRepository):
    """Lists, reads, creates, updates, and removes this tenant's habits."""

    async def list_all(self, *, area_id: AreaId | None = None) -> tuple[HabitRecord, ...]:
        """This tenant's habits, or the ones inside one Area, in declaration order."""
        statement = self.scoped_select(HabitRow).order_by(HabitRow.created_at, HabitRow.id)
        if area_id is not None:
            statement = statement.where(HabitRow.area_id == area_id)
        found = await self._session.scalars(statement)
        return tuple(_as_record(row) for row in found)

    async def find(self, habit_id: HabitId) -> HabitRecord | None:
        """One habit of this tenant's, or ``None``.

        Scoped, so another tenant's identifier reads as absent rather than as forbidden, which
        is what makes the 404 the service raises truthful.
        """
        found = await self._session.scalar(
            self.scoped_select(HabitRow).where(HabitRow.id == habit_id)
        )
        return _as_record(found) if found is not None else None

    async def create(
        self, *, area_id: AreaId, title: str, habit: Habit, created_at: datetime
    ) -> HabitRecord:
        """Persist one habit from the entity the caller already validated.

        Taking the entity rather than its seven fields is what makes an unvalidated habit
        unstorable: constructing a ``Habit`` applies X3, X4, and every bound, so there is no
        argument list here that could bypass them.
        """
        kind, times_per_week, approx_days = columns_of(habit.cadence)
        row = HabitRow(
            id=habit.id,
            tenant_id=self.tenant_id,
            area_id=area_id,
            title=title,
            cadence_kind=kind.value,
            cadence_times_per_week=times_per_week,
            cadence_approx_days=approx_days,
            duration_min_minutes=habit.duration.min_minutes,
            duration_max_minutes=habit.duration.max_minutes,
            miss_policy=habit.miss_policy,
            binding_source=habit.binding_source,
            variants=list(habit.variants),
            debt_cap_periods=habit.debt_cap_periods,
            created_at=created_at,
        )
        self._session.add(row)
        # Flushed here so a constraint violation surfaces as this call's failure rather than at
        # commit, after the caller has reported success.
        await self._session.flush()
        return _as_record(row)

    async def write(self, habit: Habit, *, title: str) -> None:
        """Replace every editable value on one habit, from the merged entity.

        ``area_id`` is absent: a habit never moves between Areas, because the hours already
        spent on its occurrences were attributed to the Area it was declared in and moving it
        would rewrite reported history.
        """
        kind, times_per_week, approx_days = columns_of(habit.cadence)
        await self._session.execute(
            self.scoped_update(HabitRow)
            .where(HabitRow.id == habit.id)
            .values(
                title=title,
                cadence_kind=kind.value,
                cadence_times_per_week=times_per_week,
                cadence_approx_days=approx_days,
                duration_min_minutes=habit.duration.min_minutes,
                duration_max_minutes=habit.duration.max_minutes,
                miss_policy=habit.miss_policy,
                binding_source=habit.binding_source,
                variants=list(habit.variants),
                debt_cap_periods=habit.debt_cap_periods,
            )
        )

    async def remove(self, habit_id: HabitId) -> None:
        """Delete one habit. Its recorded outcomes are retained, because they are facts.

        An outcome carries its binding denormalized for exactly this case, so a week that
        already happened still reads as it did after the habit that produced it is gone.
        """
        await self._session.execute(self.scoped_delete(HabitRow).where(HabitRow.id == habit_id))


def _as_record(row: HabitRow) -> HabitRecord:
    return HabitRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        area_id=row.area_id,
        title=row.title,
        cadence_kind=CadenceKind(row.cadence_kind),
        cadence_times_per_week=row.cadence_times_per_week,
        cadence_approx_days=row.cadence_approx_days,
        duration_min_minutes=row.duration_min_minutes,
        duration_max_minutes=row.duration_max_minutes,
        miss_policy=row.miss_policy,
        binding_source=row.binding_source,
        variants=tuple(row.variants),
        debt_cap_periods=row.debt_cap_periods,
        created_at=row.created_at,
    )
