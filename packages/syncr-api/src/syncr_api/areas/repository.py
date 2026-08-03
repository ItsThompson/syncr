"""Persistence for Areas and Projects. Tenant-scoped, both.

Every statement is built from the scoped base, so the tenant predicate is applied by the base
rather than remembered per method, and a repository cannot be constructed without a tenant to
scope to.

One method is load-bearing beyond an ordinary read. :meth:`AreaRepository.lock_all` is the
serialization point for the pigment deal: the step a new Area takes is derived from how many
Areas already hold one, so two declarations racing would both read the same count and both
take the same step. Reading the rows ``FOR UPDATE`` makes the count-then-insert atomic per
tenant once the tenant has an Area at all. A tenant with none has no row to lock, so the very
first pair could still collide, which is the same outcome a thirteenth Area produces and is
corrected the same way: re-pick the step from the ramp.

No method commits. One request is one transaction, opened and committed by
:func:`syncr_api.core.db.get_transaction`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from syncr_api.areas.models import AreaRow, ProjectRow
from syncr_api.areas.records import AreaRecord, ProjectRecord
from syncr_api.core.repository import TenantScopedRepository

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal

    from sqlalchemy import Select

    from syncr_domain.identifiers import AreaId, ProjectId
    from syncr_domain.pigments import PigmentIndex
    from syncr_domain.projects import ProjectStatus


class AreaRepository(TenantScopedRepository):
    """Lists, reads, creates, and updates this tenant's Areas."""

    async def list_all(self) -> tuple[AreaRecord, ...]:
        """Every Area this tenant has declared, in the order they were declared.

        Declaration order is also the order the ramp dealt their pigments, which is what the
        setup wizard's assignment table renders.
        """
        found = await self._session.scalars(self._ordered())
        return tuple(_as_area_record(row) for row in found)

    async def lock_all(self) -> tuple[AreaRecord, ...]:
        """:meth:`list_all`, held until the transaction ends.

        The returned records are the rows' committed state, so a caller deriving the next
        pigment from their count is deriving it from a count nobody else can change
        underneath.
        """
        found = await self._session.scalars(self._ordered().with_for_update())
        return tuple(_as_area_record(row) for row in found)

    async def find(self, area_id: AreaId) -> AreaRecord | None:
        """One Area of this tenant's, or ``None``.

        Scoped, so another tenant's identifier reads as absent rather than as forbidden,
        which is what makes the 404 the service raises truthful.
        """
        found = await self._session.scalar(self.scoped_select(AreaRow).where(AreaRow.id == area_id))
        return _as_area_record(found) if found is not None else None

    async def create(
        self,
        *,
        parent_id: AreaId | None,
        name: str,
        pigment_index: PigmentIndex,
        budget_percent: Decimal | None,
        floor_hours: Decimal | None,
        created_at: datetime,
    ) -> AreaRecord:
        """Persist one Area. The caller has already dealt its pigment and checked its name."""
        row = AreaRow(
            id=uuid4(),
            tenant_id=self.tenant_id,
            parent_id=parent_id,
            name=name,
            pigment_index=pigment_index,
            budget_percent=budget_percent,
            floor_hours=floor_hours,
            default_preference_id=None,
            created_at=created_at,
        )
        self._session.add(row)
        # Flushed here so a constraint violation surfaces as this call's failure rather than
        # at commit, after the caller has reported success.
        await self._session.flush()
        return _as_area_record(row)

    async def write(
        self,
        area_id: AreaId,
        *,
        name: str,
        pigment_index: PigmentIndex,
        budget_percent: Decimal | None,
        floor_hours: Decimal | None,
    ) -> None:
        """Replace every editable value on one Area. The caller has merged its partial update.

        Whole-record rather than field-by-field, for the same reason the settings write is: a
        partial update is validated as a set, so the caller holds the merged values anyway.
        The parent is absent because an Area's place in the hierarchy is declared once: moving
        one would re-attribute history that has already been reported.
        """
        await self._session.execute(
            self.scoped_update(AreaRow)
            .where(AreaRow.id == area_id)
            .values(
                name=name,
                pigment_index=pigment_index,
                budget_percent=budget_percent,
                floor_hours=floor_hours,
            )
        )

    def _ordered(self) -> Select[tuple[AreaRow]]:
        return self.scoped_select(AreaRow).order_by(AreaRow.created_at, AreaRow.id)


class ProjectRepository(TenantScopedRepository):
    """Lists, reads, creates, and updates this tenant's Projects."""

    async def list_all(self, *, area_id: AreaId | None = None) -> tuple[ProjectRecord, ...]:
        """This tenant's Projects, or the ones inside one Area, oldest first."""
        statement = self.scoped_select(ProjectRow).order_by(ProjectRow.created_at, ProjectRow.id)
        if area_id is not None:
            statement = statement.where(ProjectRow.area_id == area_id)
        found = await self._session.scalars(statement)
        return tuple(_as_project_record(row) for row in found)

    async def find(self, project_id: ProjectId) -> ProjectRecord | None:
        """One Project of this tenant's, or ``None``."""
        found = await self._session.scalar(
            self.scoped_select(ProjectRow).where(ProjectRow.id == project_id)
        )
        return _as_project_record(found) if found is not None else None

    async def create(
        self,
        *,
        area_id: AreaId,
        name: str,
        deadline: datetime | None,
        status: ProjectStatus,
        created_at: datetime,
    ) -> ProjectRecord:
        """Persist one Project. The caller has already confirmed its Area exists."""
        row = ProjectRow(
            id=uuid4(),
            tenant_id=self.tenant_id,
            area_id=area_id,
            name=name,
            deadline=deadline,
            status=status,
            created_at=created_at,
        )
        self._session.add(row)
        await self._session.flush()
        return _as_project_record(row)

    async def write(
        self,
        project_id: ProjectId,
        *,
        name: str,
        deadline: datetime | None,
        status: ProjectStatus,
    ) -> None:
        """Replace every editable value on one Project.

        ``area_id`` is absent: a Project never moves between Areas, because the hours already
        spent on it were attributed to the Area it was declared in and moving it would rewrite
        that history.
        """
        await self._session.execute(
            self.scoped_update(ProjectRow)
            .where(ProjectRow.id == project_id)
            .values(name=name, deadline=deadline, status=status)
        )


def _as_area_record(row: AreaRow) -> AreaRecord:
    return AreaRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        parent_id=row.parent_id,
        name=row.name,
        pigment_index=row.pigment_index,
        budget_percent=row.budget_percent,
        floor_hours=row.floor_hours,
        default_preference_id=row.default_preference_id,
        created_at=row.created_at,
    )


def _as_project_record(row: ProjectRow) -> ProjectRecord:
    return ProjectRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        area_id=row.area_id,
        name=row.name,
        deadline=row.deadline,
        status=row.status,
        created_at=row.created_at,
    )
