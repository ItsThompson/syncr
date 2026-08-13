"""Persistence for preferences. Tenant-scoped, and addressed by owner rather than by identifier.

Every read and write names an OWNER, because that is how a preference is addressed everywhere
else: the routes are sub-resources of an Area, a Habit, or a Task, and no caller holds a
preference identifier. Which reference column an owner's kind uses is one mapping, read by every
method here, so a fourth kind of owner would be one entry rather than a branch per statement.

Every statement is built from the scoped base, so the tenant predicate is applied by the base
rather than remembered per method, and a repository cannot be constructed without a tenant to
scope to.

The write path replaces every editable value rather than taking a field at a time, for the same
reason the habit write does, and here it is also the contract: an override replaces its Area's
preference wholly, so a partial write would be a merge rule this product does not have.

There is ONE write, and it neither knows nor asks whether the owner already declared something. A
caller that read first and then chose between an insert and an update would be choosing from a read
that holds no lock, and either choice can be wrong by the time the write runs: two writers that
both saw nothing insert twice, and a writer that saw a row updates nothing once the row is gone.

No method commits. One request is one transaction, opened and committed by
:func:`syncr_api.core.db.get_transaction`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final
from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert

from syncr_api.core.repository import TenantScopedRepository
from syncr_api.preferences.models import PreferenceRow
from syncr_api.preferences.records import (
    PreferenceRecord,
    owner_columns,
    owner_of,
    windows_as_json,
)
from syncr_domain.preferences import PreferenceOwnerKind, PreferenceStrength

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import InstrumentedAttribute

    from syncr_domain.preferences import Preference, PreferenceOwner

# Which reference column each kind of owner is addressed through. One mapping rather than a
# branch per statement, and `test_preferences_service` asserts it covers every kind, so a fourth
# owner is a missing entry rather than a read that silently matches every row.
OWNER_COLUMN: Final[dict[PreferenceOwnerKind, InstrumentedAttribute[object]]] = {
    PreferenceOwnerKind.AREA: PreferenceRow.area_id,
    PreferenceOwnerKind.HABIT: PreferenceRow.habit_id,
    PreferenceOwnerKind.TASK: PreferenceRow.task_id,
}


class PreferenceRepository(TenantScopedRepository):
    """Reads, creates, replaces, and removes one tenant's preferences, addressed by owner."""

    async def find(self, owner: PreferenceOwner) -> PreferenceRecord | None:
        """This owner's preference, or ``None``.

        Scoped, so another tenant's owner reads as having no preference. That is not a disclosure
        risk here on its own, because the service refuses an owner it cannot read first.
        """
        found = await self._session.scalar(
            self.scoped_select(PreferenceRow).where(OWNER_COLUMN[owner.kind] == owner.id)
        )
        return _as_record(found) if found is not None else None

    async def list_all(self) -> tuple[PreferenceRecord, ...]:
        """Every preference this tenant has declared, in declaration order.

        One read rather than one per owner, because the week assembler resolves the chain of
        every Area, habit, and task in the week: addressed per owner, that is a query per entity
        on the path of every live verdict.
        """
        found = await self._session.scalars(
            self.scoped_select(PreferenceRow).order_by(PreferenceRow.created_at, PreferenceRow.id)
        )
        return tuple(_as_record(row) for row in found)

    async def upsert(self, preference: Preference, *, created_at: datetime) -> None:
        """Store this owner's preference, replacing whatever the owner declared before.

        Taking the entity rather than its five fields is what makes an unvalidated preference
        unstorable: constructing a ``Preference`` applies the cap's owner rule and every bound, so
        there is no argument list here that could bypass them.

        The conflict target is the unique index over the owner's OWN reference column, so which of
        the three indexes decides that this owner already has a row is the same mapping every
        other statement here reads. The tenant leads that index and is among the values, so the
        row a conflict names is this tenant's own.

        The editable values are one dict on both halves, because a replacement stores the
        declaration whole either way. Absent from the replacement half: the identifier, the owner
        columns, and ``created_at``. A preference does not move between owners, because it is
        addressed by the owner and a move would be a removal and a declaration elsewhere; and a
        row keeps the instant it was first declared.
        """
        area_id, habit_id, task_id = owner_columns(preference.owner)
        declared = {
            "windows": windows_as_json(preference.windows),
            "strength": preference.strength.value,
            "preferred_duration_minutes": preference.preferred_duration_minutes,
            "max_per_day_minutes": preference.max_per_day_minutes,
        }
        await self._session.execute(
            insert(PreferenceRow)
            .values(
                id=uuid4(),
                tenant_id=self.tenant_id,
                owner_kind=preference.owner.kind.value,
                area_id=area_id,
                habit_id=habit_id,
                task_id=task_id,
                created_at=created_at,
                **declared,
            )
            .on_conflict_do_update(
                index_elements=[PreferenceRow.tenant_id, OWNER_COLUMN[preference.owner.kind]],
                set_=declared,
            )
        )

    async def remove(self, owner: PreferenceOwner) -> int:
        """Delete this owner's preference, answering how many rows that was.

        The count is what the caller gates its version bump on: removing a preference nothing
        declared invalidates no solve, because no solve was reading one.
        """
        return await self._affected_rows(
            self.scoped_delete(PreferenceRow).where(OWNER_COLUMN[owner.kind] == owner.id)
        )


def _as_record(row: PreferenceRow) -> PreferenceRecord:
    kind = PreferenceOwnerKind(row.owner_kind)
    return PreferenceRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        owner=owner_of(kind, area_id=row.area_id, habit_id=row.habit_id, task_id=row.task_id),
        windows=tuple(row.windows),
        strength=PreferenceStrength(row.strength),
        preferred_duration_minutes=row.preferred_duration_minutes,
        max_per_day_minutes=row.max_per_day_minutes,
        created_at=row.created_at,
    )
