"""The Area and Project services against fakes: the deal, the rejections, and the bump.

The repositories are replaced and the clock is injected, so "today" is a literal date and the
week the bump floors at is assertable without waiting for a Monday. The pigment deal is real
throughout, because a stubbed deal would let this suite pass while two Areas shared an ink.

The tests worth reading are the ones about what does NOT happen. Renaming an Area bumps no
input version, because the solver does not read a name. A Project mutation bumps nothing at
all, because a Project declares no budget. And percentages summing past 100 are accepted here
without comment: what answers for them is the budget report's ``oversubscription``, so a
service that rejected them would be enforcing a rule the product does not have.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syncr_api.areas.declarations import (
    AreaChange,
    AreaDeclaration,
    ProjectChange,
    ProjectDeclaration,
)
from syncr_api.areas.records import AreaRecord, ProjectRecord
from syncr_api.areas.repository import AreaRepository, ProjectRepository
from syncr_api.areas.service import AreaService, ProjectService
from syncr_api.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from syncr_api.core.patches import ABSENT
from syncr_api.core.principal import Principal
from syncr_api.core.scopes import ALL_SCOPES, Scope
from syncr_api.user_settings.config import ReviewCadence
from syncr_api.user_settings.records import SettingsRecord
from syncr_api.user_settings.repository import SettingsRepository
from syncr_api.user_settings.solve_inputs import WeekRange
from syncr_domain.pigments import PIGMENT_COUNT, PIGMENT_DEAL_ORDER
from syncr_domain.projects import ProjectStatus
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from syncr_domain.identifiers import AreaId, ProjectId, TenantId
    from syncr_domain.pigments import PigmentIndex

LONDON = "Europe/London"

# A Sunday, the last day of 2026-W31, at 09:00 UTC: mid-morning in London, so the local date
# and the UTC date agree and these tests are about budgets rather than about a date boundary.
NOW = datetime(2026, 8, 2, 9, 0, tzinfo=UTC)
WEEK_31 = IsoWeek.parse("2026-W31")


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
            default_preference_id=None,
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
                default_preference_id=row.default_preference_id,
                created_at=row.created_at,
            )
            if row.id == area_id
            else row
            for row in self.rows
        ]


class FakeProjectRepository(ProjectRepository):
    """Records what was written, so the service's effects are assertable."""

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


class FakeSettingsRepository(SettingsRepository):
    """One settings row, for the home zone the bump's floor is resolved in."""

    def __init__(self, tenant_id: TenantId, home_zone: str = LONDON) -> None:
        self._tenant_id = tenant_id
        self._home_zone = home_zone

    async def read(self) -> SettingsRecord:
        return SettingsRecord(
            tenant_id=self._tenant_id,
            visible_hours=12,
            day_start=time(7, 0),
            day_end=time(23, 0),
            review_cadence=ReviewCadence.ON_DEMAND,
            home_zone=self._home_zone,
        )


class RecordingWeekInputVersions:
    """Every range the service asked to have bumped, in order."""

    def __init__(self) -> None:
        self.bumped: list[WeekRange] = []

    async def bump(self, weeks: WeekRange) -> None:
        self.bumped.append(weeks)


@pytest.fixture
def principal() -> Principal:
    return Principal(tenant_id=uuid4(), user_id=uuid4(), scopes=ALL_SCOPES)


@pytest.fixture
def versions() -> RecordingWeekInputVersions:
    return RecordingWeekInputVersions()


def build_areas(
    principal: Principal,
    versions: RecordingWeekInputVersions,
    *,
    stored: list[AreaRecord] | None = None,
) -> tuple[AreaService, FakeAreaRepository]:
    areas = FakeAreaRepository(principal.tenant_id, stored)
    service = AreaService(
        areas=areas,
        settings=FakeSettingsRepository(principal.tenant_id),
        versions=versions,
        clock=lambda: NOW,
    )
    return service, areas


def build_projects(
    principal: Principal, *, areas: FakeAreaRepository | None = None
) -> tuple[ProjectService, FakeProjectRepository, FakeAreaRepository]:
    area_rows = areas if areas is not None else FakeAreaRepository(principal.tenant_id)
    projects = FakeProjectRepository(principal.tenant_id)
    service = ProjectService(projects=projects, areas=area_rows, clock=lambda: NOW)
    return service, projects, area_rows


def a_declaration(name: str, **changes: object) -> AreaDeclaration:
    fields: dict[str, object] = {
        "name": name,
        "parent_id": None,
        "budget_percent": None,
        "floor_hours": None,
    }
    return AreaDeclaration(**{**fields, **changes})  # type: ignore[arg-type]


def no_change() -> AreaChange:
    return AreaChange(name=ABSENT, pigment_index=ABSENT, budget_percent=ABSENT, floor_hours=ABSENT)


async def declare(
    service: AreaService, principal: Principal, name: str, **changes: object
) -> AreaRecord:
    view = await service.create(principal, a_declaration(name, **changes))
    return view.area


# --------------------------------------------------------------------------------
# The pigment deal
# --------------------------------------------------------------------------------


async def test_creating_an_area_assigns_the_next_step_of_the_ramp(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, _ = build_areas(principal, versions)

    dealt = [
        (await declare(service, principal, f"Area {index}")).pigment_index for index in range(4)
    ]

    assert dealt == list(PIGMENT_DEAL_ORDER[:4])


async def test_the_deal_is_serialized_on_the_areas_it_counts(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # Without the lock, two declarations would count the same set and take the same step.
    service, areas = build_areas(principal, versions)

    await declare(service, principal, "Fitness")

    assert areas.locks == 1


async def test_the_thirteenth_area_reuses_a_pigment_and_the_response_says_so(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, _ = build_areas(principal, versions)
    for index in range(PIGMENT_COUNT):
        await declare(service, principal, f"Area {index}")

    thirteenth = await service.create(principal, a_declaration("Thirteenth"))

    assert thirteenth.area.pigment_index == PIGMENT_DEAL_ORDER[0]
    assert thirteenth.ramp.pigments_in_use == PIGMENT_COUNT
    assert thirteenth.ramp.areas_sharing_a_pigment == 2
    statement = thirteenth.ramp.statement
    assert statement is not None
    # The interface has to be able to say what identity rests on now, so the response says it.
    assert "hatch" in statement
    assert "name" in statement


async def test_a_full_ramp_is_reported_before_it_is_exhausted(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # The control at the other end of the boundary: twelve Areas hold twelve distinct steps, so
    # nothing is shared and no statement is made.
    service, _ = build_areas(principal, versions)
    for index in range(PIGMENT_COUNT):
        await declare(service, principal, f"Area {index}")

    view = await service.list_all(principal)

    assert view.ramp.pigments_in_use == PIGMENT_COUNT
    assert view.ramp.areas_sharing_a_pigment == 0
    assert view.ramp.statement is None


async def test_a_pigment_can_be_re_picked_from_the_ramp(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, _ = build_areas(principal, versions)
    area = await declare(service, principal, "Fitness")
    wanted = (area.pigment_index + 5) % PIGMENT_COUNT

    changed = await service.update(principal, area.id, AreaChange(ABSENT, wanted, ABSENT, ABSENT))

    assert changed.area.pigment_index == wanted


async def test_re_picking_a_pigment_bumps_no_input_version(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # A pigment is read by the interface alone. Invalidating a running solve for it would
    # discard work for a change the solver cannot see.
    service, _ = build_areas(principal, versions)
    area = await declare(service, principal, "Fitness")
    versions.bumped.clear()

    await service.update(principal, area.id, AreaChange(ABSENT, 3, ABSENT, ABSENT))

    assert versions.bumped == []


# --------------------------------------------------------------------------------
# Names, parents, and shares
# --------------------------------------------------------------------------------


async def test_a_name_another_area_holds_is_refused(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, areas = build_areas(principal, versions)
    await declare(service, principal, "Fitness")

    with pytest.raises(Conflict) as refused:
        await declare(service, principal, "Fitness")

    # Refused rather than stored: a duplicate name would leave a wedge with nothing to
    # identify it once the ramp repeats.
    assert len(areas.rows) == 1
    assert "hatch" in str(refused.value.detail)


async def test_renaming_an_area_to_its_own_name_is_not_a_conflict(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # The control for the rule above: it must exclude the row being changed, or no Area could
    # ever be patched without also being renamed.
    service, _ = build_areas(principal, versions)
    area = await declare(service, principal, "Fitness")

    changed = await service.update(
        principal, area.id, AreaChange("Fitness", ABSENT, ABSENT, ABSENT)
    )

    assert changed.area.name == "Fitness"


async def test_an_area_may_nest_under_one_that_exists(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, _ = build_areas(principal, versions)
    parent = await declare(service, principal, "Career")

    child = await declare(service, principal, "Learning", parent_id=parent.id)

    assert child.parent_id == parent.id


async def test_an_unknown_parent_is_refused_rather_than_stored(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, areas = build_areas(principal, versions)

    with pytest.raises(ValidationFailed) as refused:
        await declare(service, principal, "Learning", parent_id=uuid4())

    assert areas.rows == []
    assert refused.value.errors is not None
    assert [error.field for error in refused.value.errors] == ["parentId"]


async def test_shares_summing_past_one_hundred_are_accepted(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, areas = build_areas(principal, versions)

    await declare(service, principal, "Fitness", budget_percent=Decimal(80))
    await declare(service, principal, "Career", budget_percent=Decimal(50))

    # Accepted, never rejected. Oversubscription is reported by the budget report.
    assert [row.budget_percent for row in areas.rows] == [Decimal(80), Decimal(50)]


# --------------------------------------------------------------------------------
# Patching, and what it bumps
# --------------------------------------------------------------------------------


async def test_an_omitted_field_is_left_alone_and_an_explicit_null_clears_one(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, _ = build_areas(principal, versions)
    area = await declare(
        service, principal, "Fitness", budget_percent=Decimal(25), floor_hours=Decimal(4)
    )

    kept = await service.update(principal, area.id, AreaChange(ABSENT, ABSENT, ABSENT, ABSENT))
    assert (kept.area.budget_percent, kept.area.floor_hours) == (Decimal(25), Decimal(4))

    cleared = await service.update(principal, area.id, AreaChange(ABSENT, ABSENT, ABSENT, None))
    assert cleared.area.floor_hours is None
    # And clearing one left the other alone, which is the whole point of the distinction.
    assert cleared.area.budget_percent == Decimal(25)


@pytest.mark.parametrize(
    "change",
    [
        AreaChange(ABSENT, ABSENT, Decimal(30), ABSENT),
        AreaChange(ABSENT, ABSENT, ABSENT, Decimal(6)),
        AreaChange(ABSENT, ABSENT, None, ABSENT),
        AreaChange(ABSENT, ABSENT, ABSENT, None),
    ],
    ids=["a share", "a floor", "a cleared share", "a cleared floor"],
)
async def test_changing_a_budget_bumps_every_week_from_this_one(
    principal: Principal, versions: RecordingWeekInputVersions, change: AreaChange
) -> None:
    service, _ = build_areas(principal, versions)
    area = await declare(service, principal, "Fitness")
    versions.bumped.clear()

    await service.update(principal, area.id, change)

    # From the week holding today's local date, with no end: a budget governs every week the
    # user has not yet lived, and a past week keeps the inputs it was computed with.
    assert versions.bumped == [WeekRange(first=WEEK_31, last=None)]


async def test_renaming_an_area_bumps_nothing(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, _ = build_areas(principal, versions)
    area = await declare(service, principal, "Fitness")
    versions.bumped.clear()

    await service.update(principal, area.id, AreaChange("Fitness training", ABSENT, ABSENT, ABSENT))

    assert versions.bumped == []


async def test_declaring_an_area_bumps_every_week_from_this_one(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, _ = build_areas(principal, versions)

    await declare(service, principal, "Fitness")

    assert versions.bumped == [WeekRange(first=WEEK_31, last=None)]


async def test_reading_areas_writes_nothing_and_bumps_nothing(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, areas = build_areas(principal, versions)

    await service.list_all(principal)

    assert areas.rows == []
    assert areas.locks == 0
    assert versions.bumped == []


# --------------------------------------------------------------------------------
# Authorization
# --------------------------------------------------------------------------------


async def test_reading_an_area_that_does_not_exist_is_a_404(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, _ = build_areas(principal, versions)

    with pytest.raises(NotFound):
        await service.read(principal, uuid4())


async def test_patching_an_area_that_does_not_exist_is_a_404(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, _ = build_areas(principal, versions)

    with pytest.raises(NotFound):
        await service.update(principal, uuid4(), no_change())


async def test_a_credential_without_admin_cannot_change_a_budget(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, areas = build_areas(principal, versions)
    reader = Principal(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        scopes=frozenset({Scope.PLAN_READ}),
    )

    with pytest.raises(Forbidden):
        await service.create(reader, a_declaration("Fitness"))

    # Refused means not stored, and the read the same credential DOES carry still works.
    assert areas.rows == []
    assert (await service.list_all(reader)).areas == ()


async def test_a_credential_without_plan_read_cannot_list_areas(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, _ = build_areas(principal, versions)
    stranger = Principal(
        tenant_id=principal.tenant_id, user_id=principal.user_id, scopes=frozenset()
    )

    with pytest.raises(Forbidden):
        await service.list_all(stranger)


# --------------------------------------------------------------------------------
# Projects
# --------------------------------------------------------------------------------


async def test_a_project_is_declared_inside_an_area_that_exists(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    area_service, areas = build_areas(principal, versions)
    area = await declare(area_service, principal, "Career")
    service, projects, _ = build_projects(principal, areas=areas)

    created = await service.create(
        principal,
        ProjectDeclaration(
            area_id=area.id, name="Interview prep", deadline=None, status=ProjectStatus.ACTIVE
        ),
    )

    assert created.area_id == area.id
    assert created.status is ProjectStatus.ACTIVE
    assert len(projects.rows) == 1


async def test_a_project_in_an_area_that_does_not_exist_is_refused(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, projects, _ = build_projects(principal)

    with pytest.raises(ValidationFailed) as refused:
        await service.create(
            principal,
            ProjectDeclaration(
                area_id=uuid4(), name="Interview prep", deadline=None, status=ProjectStatus.ACTIVE
            ),
        )

    assert projects.rows == []
    assert refused.value.errors is not None
    assert [error.field for error in refused.value.errors] == ["areaId"]


async def test_completing_a_project_leaves_its_area_and_its_dates_intact(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    area_service, areas = build_areas(principal, versions)
    area = await declare(area_service, principal, "Career")
    service, projects, _ = build_projects(principal, areas=areas)
    deadline = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    created = await service.create(
        principal,
        ProjectDeclaration(
            area_id=area.id, name="Interview prep", deadline=deadline, status=ProjectStatus.ACTIVE
        ),
    )

    completed = await service.update(
        principal,
        created.id,
        ProjectChange(name=ABSENT, deadline=ABSENT, status=ProjectStatus.COMPLETED),
    )

    assert completed.status is ProjectStatus.COMPLETED
    # The historical attribution is the Area and the dates. Completing a Project states
    # something about the Project and re-attributes nothing.
    assert completed.area_id == area.id
    assert completed.deadline == deadline
    assert completed.created_at == created.created_at
    assert projects.rows[0].area_id == area.id


async def test_a_project_mutation_bumps_no_input_version(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # A Project declares no budget and no solve input reads one, so a running solve stays
    # valid across a project edit.
    area_service, areas = build_areas(principal, versions)
    area = await declare(area_service, principal, "Career")
    service, _, _ = build_projects(principal, areas=areas)
    versions.bumped.clear()

    created = await service.create(
        principal,
        ProjectDeclaration(
            area_id=area.id, name="Interview prep", deadline=None, status=ProjectStatus.ACTIVE
        ),
    )
    await service.update(
        principal, created.id, ProjectChange(name="Renamed", deadline=ABSENT, status=ABSENT)
    )

    assert versions.bumped == []


async def test_projects_can_be_listed_for_one_area(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    area_service, areas = build_areas(principal, versions)
    career = await declare(area_service, principal, "Career")
    fitness = await declare(area_service, principal, "Fitness")
    service, _, _ = build_projects(principal, areas=areas)
    for area, name in ((career, "Interview prep"), (fitness, "Marathon")):
        await service.create(
            principal,
            ProjectDeclaration(
                area_id=area.id, name=name, deadline=None, status=ProjectStatus.ACTIVE
            ),
        )

    found = await service.list_all(principal, area_id=career.id)

    assert [project.name for project in found] == ["Interview prep"]
    assert len(await service.list_all(principal)) == 2


async def test_a_project_that_does_not_exist_is_a_404(principal: Principal) -> None:
    service, _, _ = build_projects(principal)

    with pytest.raises(NotFound):
        await service.read(principal, uuid4())


async def test_the_week_the_bump_floors_at_is_the_one_holding_today(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # The clock is injected, so this is a literal date rather than whatever day the suite runs
    # on. 2026-08-02 is the Sunday that closes 2026-W31.
    assert IsoWeek.containing(date(2026, 8, 2)) == WEEK_31
    service, _ = build_areas(principal, versions)

    await declare(service, principal, "Fitness")

    assert versions.bumped[0].first == WEEK_31
