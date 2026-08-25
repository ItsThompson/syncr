"""Fakes for the service suites: the settings row, Areas, and Projects.

One declaration each, imported by every ``*_service.py`` suite that needs it, so adding a field
to ``SettingsRecord`` or ``AreaRecord`` is one edit here rather than one per suite. A fake
copied into a second suite is a fake that drifts from the first, and the drift is silent until
a record grows a field the copy was never taught.

Every fake is the REAL repository's interface over a list of records and no database, matching
the convention of ``assembly_fakes`` and ``outcome_fakes``. Doubles that record what they were
ask (a read count, a call log) are not storage fakes: they belong to the suite whose assertion
gives them meaning, and stay there. The one counter carried here is ``locks``, because two
suites assert the service took the settings lock and a subclass in the preferences suite adds
its own count over this Area fake anyway.

The settings fake holds the full read/lock/write interface because the settings service's own
suite drives all three; a suite that only reads loses nothing by sharing it. Its home-zone
default is London because that is the zone every suite but the settings one resolves in; the
settings suite passes the declared default explicitly, since its defaults test asserts that
value.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from syncr_api.areas.records import AreaRecord, ProjectRecord
from syncr_api.areas.repository import AreaRepository, ProjectRepository
from syncr_api.user_settings.config import (
    DAY_END_DEFAULT,
    DAY_START_DEFAULT,
    REVIEW_CADENCE_DEFAULT,
    VISIBLE_HOURS_DEFAULT,
)
from syncr_api.user_settings.records import SettingsRecord
from syncr_api.user_settings.repository import SettingsRepository

if TYPE_CHECKING:
    from datetime import datetime, time
    from decimal import Decimal

    from syncr_api.user_settings.config import ReviewCadence
    from syncr_domain.identifiers import AreaId, ProjectId, TenantId
    from syncr_domain.pigments import PigmentIndex
    from syncr_domain.projects import ProjectStatus

LONDON = "Europe/London"


class FakeSettingsRepository(SettingsRepository):
    """The real repository's interface over one optional record, and no database."""

    def __init__(
        self,
        tenant_id: TenantId,
        stored: SettingsRecord | None = None,
        *,
        home_zone: str = LONDON,
    ) -> None:
        self._tenant_id = tenant_id
        self.stored = stored
        self.locks = 0
        self._home_zone = home_zone

    def defaults(self) -> SettingsRecord:
        """What a tenant who has never saved settings reads, in this fake's home zone."""
        return SettingsRecord(
            tenant_id=self._tenant_id,
            visible_hours=VISIBLE_HOURS_DEFAULT,
            day_start=DAY_START_DEFAULT,
            day_end=DAY_END_DEFAULT,
            review_cadence=REVIEW_CADENCE_DEFAULT,
            home_zone=self._home_zone,
        )

    async def read(self) -> SettingsRecord:
        # A read writes nothing: no row is created to answer it.
        return self.stored if self.stored is not None else self.defaults()

    async def lock(self, *, created_at: datetime) -> SettingsRecord:
        self.locks += 1
        if self.stored is None:
            self.stored = self.defaults()
        return self.stored

    async def write(
        self,
        *,
        visible_hours: int,
        day_start: time,
        day_end: time,
        review_cadence: ReviewCadence,
        home_zone: str,
    ) -> SettingsRecord:
        self.stored = SettingsRecord(
            tenant_id=self._tenant_id,
            visible_hours=visible_hours,
            day_start=day_start,
            day_end=day_end,
            review_cadence=review_cadence,
            home_zone=home_zone,
        )
        return self.stored


class FakeAreaRepository(AreaRepository):
    """The real repository's interface over a list of records, and no database."""

    def __init__(self, tenant_id: TenantId, stored: list[AreaRecord] | None = None) -> None:
        self._tenant_id = tenant_id
        self.rows = list(stored or [])
        self.locks = 0

    async def list_all(self) -> tuple[AreaRecord, ...]:
        return tuple(sorted(self.rows, key=lambda row: (row.created_at, row.id)))

    async def lock_all(self) -> tuple[AreaRecord, ...]:
        self.locks += 1
        return await self.list_all()

    async def find(self, area_id: AreaId) -> AreaRecord | None:
        return next((row for row in self.rows if row.id == area_id), None)

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
        created = AreaRecord(
            id=uuid4(),
            tenant_id=self._tenant_id,
            parent_id=parent_id,
            name=name,
            pigment_index=pigment_index,
            budget_percent=budget_percent,
            floor_hours=floor_hours,
            created_at=created_at,
        )
        self.rows.append(created)
        return created

    async def write(
        self,
        area_id: AreaId,
        *,
        name: str,
        pigment_index: PigmentIndex,
        budget_percent: Decimal | None,
        floor_hours: Decimal | None,
    ) -> None:
        self.rows = [
            AreaRecord(
                id=row.id,
                tenant_id=row.tenant_id,
                parent_id=row.parent_id,
                name=name,
                pigment_index=pigment_index,
                budget_percent=budget_percent,
                floor_hours=floor_hours,
                created_at=row.created_at,
            )
            if row.id == area_id
            else row
            for row in self.rows
        ]


class FakeProjectRepository(ProjectRepository):
    """The real repository's interface over a list of records, and no database."""

    def __init__(self, tenant_id: TenantId, stored: list[ProjectRecord] | None = None) -> None:
        self._tenant_id = tenant_id
        self.rows = list(stored or [])

    async def list_all(self, *, area_id: AreaId | None = None) -> tuple[ProjectRecord, ...]:
        ordered = sorted(self.rows, key=lambda row: (row.created_at, row.id))
        return tuple(row for row in ordered if area_id is None or row.area_id == area_id)

    async def find(self, project_id: ProjectId) -> ProjectRecord | None:
        return next((row for row in self.rows if row.id == project_id), None)

    async def create(
        self,
        *,
        area_id: AreaId,
        name: str,
        deadline: datetime | None,
        status: ProjectStatus,
        created_at: datetime,
    ) -> ProjectRecord:
        created = ProjectRecord(
            id=uuid4(),
            tenant_id=self._tenant_id,
            area_id=area_id,
            name=name,
            deadline=deadline,
            status=status,
            created_at=created_at,
        )
        self.rows.append(created)
        return created

    async def write(
        self,
        project_id: ProjectId,
        *,
        name: str,
        deadline: datetime | None,
        status: ProjectStatus,
    ) -> None:
        self.rows = [
            ProjectRecord(
                id=row.id,
                tenant_id=row.tenant_id,
                area_id=row.area_id,
                name=name,
                deadline=deadline,
                status=status,
                created_at=row.created_at,
            )
            if row.id == project_id
            else row
            for row in self.rows
        ]
