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

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from syncr_api.areas.declarations import (
    AreaChange,
    AreaDeclaration,
    ProjectChange,
    ProjectDeclaration,
)
from syncr_api.areas.records import AreaRecord, ProjectRecord
from syncr_api.areas.rules import FULL_RAMP_REFUSAL
from syncr_api.areas.service import AreaService, ProjectService
from syncr_api.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from syncr_api.core.patches import ABSENT
from syncr_api.core.principal import Principal
from syncr_api.core.scopes import ALL_SCOPES, Scope
from syncr_api.user_settings.solve_inputs import BacklogWideBump, WeekRange
from syncr_domain.pigments import PIGMENT_COUNT, PIGMENT_DEAL_ORDER, next_pigment_index
from syncr_domain.projects import ProjectStatus
from syncr_domain.weeks import IsoWeek
from tests.service_fakes import (
    FakeAreaRepository,
    FakeProjectRepository,
    FakeSettingsRepository,
)

LONDON = "Europe/London"

# A Sunday, the last day of 2026-W31, at 09:00 UTC: mid-morning in London, so the local date
# and the UTC date agree and these tests are about budgets rather than about a date boundary.
NOW = datetime(2026, 8, 2, 9, 0, tzinfo=UTC)
WEEK_31 = IsoWeek.parse("2026-W31")


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
        bump=BacklogWideBump(
            versions=versions, settings=FakeSettingsRepository(principal.tenant_id)
        ),
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


async def test_the_shared_listing_fakes_answer_in_the_repository_s_order(
    principal: Principal,
) -> None:
    """The shared fakes' one behavior beyond storage: the real listings are ordered reads.

    Both real repositories answer ``ORDER BY created_at, id``, so a fake answering insertion
    order would let a service test pass over rows only a sorted page distinguishes. Pinned here
    because no service test happens to store rows out of declaration order.
    """
    # Stored out of declaration order on purpose: an insertion-order answer would read
    # "Later" first, which is not what the real read answers.
    area_rows = [
        replace(a_stored_area(principal, 0), id=UUID(int=3), created_at=NOW + timedelta(days=1)),
        replace(a_stored_area(principal, 1), id=UUID(int=1), created_at=NOW),
        replace(a_stored_area(principal, 2), id=UUID(int=2), created_at=NOW),
    ]
    areas = FakeAreaRepository(principal.tenant_id, area_rows)
    projects = FakeProjectRepository(
        principal.tenant_id,
        [
            ProjectRecord(
                id=UUID(int=9),
                tenant_id=principal.tenant_id,
                area_id=area_rows[2].id,
                name="Later",
                deadline=None,
                status=ProjectStatus.ACTIVE,
                created_at=NOW + timedelta(days=1),
            ),
            ProjectRecord(
                id=UUID(int=8),
                tenant_id=principal.tenant_id,
                area_id=area_rows[0].id,
                name="Earlier",
                deadline=None,
                status=ProjectStatus.ACTIVE,
                created_at=NOW,
            ),
        ],
    )

    listed_areas = await areas.list_all()
    listed_projects = await projects.list_all()
    career_only = await projects.list_all(area_id=area_rows[0].id)

    assert [row.name for row in listed_areas] == ["Area 1", "Area 2", "Area 0"]
    assert [row.name for row in listed_projects] == ["Earlier", "Later"]
    assert [row.name for row in career_only] == ["Earlier"]


async def declare(
    service: AreaService, principal: Principal, name: str, **changes: object
) -> AreaRecord:
    view = await service.create(principal, a_declaration(name, **changes))
    return view.area


def a_stored_area(principal: Principal, index: int) -> AreaRecord:
    """One Area already in the rows, holding the step the deal would have dealt it.

    Past the ramp that step is one another Area holds, which is the state a tenant declared
    before the bound existed is in.
    """
    return AreaRecord(
        id=uuid4(),
        tenant_id=principal.tenant_id,
        parent_id=None,
        name=f"Area {index}",
        pigment_index=next_pigment_index(index),
        budget_percent=None,
        floor_hours=None,
        created_at=NOW,
    )


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


# --------------------------------------------------------------------------------
# The ramp's bound
# --------------------------------------------------------------------------------


async def test_an_area_the_ramp_has_no_step_for_is_refused_and_stored_nowhere(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, areas = build_areas(principal, versions)
    for index in range(PIGMENT_COUNT):
        await declare(service, principal, f"Area {index}")
    versions.bumped.clear()

    with pytest.raises(ValidationFailed) as refused:
        await service.create(principal, a_declaration("Thirteenth"))

    assert refused.value.detail == FULL_RAMP_REFUSAL
    # No field is at fault: the request is refusable whatever it carries.
    assert refused.value.errors is None
    assert len(areas.rows) == PIGMENT_COUNT
    # Nothing was changed, so no solve input was invalidated either.
    assert versions.bumped == []


async def test_the_twelfth_area_is_accepted_and_takes_the_last_unused_step(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # The control at the accepted side of the bound. A bound stated one step early would refuse
    # this declaration, and the ramp would keep a step nothing could ever be dealt.
    service, _ = build_areas(principal, versions)
    for index in range(PIGMENT_COUNT - 1):
        await declare(service, principal, f"Area {index}")

    twelfth = await service.create(principal, a_declaration("Twelfth"))

    assert twelfth.area.pigment_index == PIGMENT_DEAL_ORDER[-1]
    assert twelfth.ramp.pigments_in_use == PIGMENT_COUNT


async def test_a_tenant_holding_more_areas_than_the_ramp_is_refused_as_well(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # Rows that predate the bound are left alone rather than reconciled, and the next
    # declaration is refused rather than dealt a step a third Area would then share.
    stored = [a_stored_area(principal, index) for index in range(PIGMENT_COUNT + 1)]
    service, areas = build_areas(principal, versions, stored=stored)

    with pytest.raises(ValidationFailed) as refused:
        await service.create(principal, a_declaration("Fourteenth"))

    assert refused.value.detail == FULL_RAMP_REFUSAL
    assert len(areas.rows) == PIGMENT_COUNT + 1


async def test_the_bound_counts_every_area_the_deal_deals_a_step_to(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # A nested Area is dealt a step of its own, so it uses one up. The bound is stated over the
    # count the deal reads, which is why nesting cannot get past it.
    service, _ = build_areas(principal, versions)
    parent = await declare(service, principal, "Career")
    nested = [
        await declare(service, principal, f"Area {index}", parent_id=parent.id)
        for index in range(PIGMENT_COUNT - 1)
    ]

    assert nested[-1].pigment_index == PIGMENT_DEAL_ORDER[-1]
    with pytest.raises(ValidationFailed) as refused:
        await service.create(principal, a_declaration("Thirteenth", parent_id=parent.id))

    # The detail, not the class: an unknown parent raises the same class from this method, so the
    # class alone would not say which rule answered.
    assert refused.value.detail == FULL_RAMP_REFUSAL


async def test_a_full_ramp_is_refused_whatever_the_declaration_is_named(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # Both rules answer this declaration. The bound is the one that does, because at the cap no
    # name is available and a refusal naming the name would send the caller to change the one
    # thing that cannot help.
    service, _ = build_areas(principal, versions)
    for index in range(PIGMENT_COUNT):
        await declare(service, principal, f"Area {index}")

    with pytest.raises(ValidationFailed) as refused:
        await service.create(principal, a_declaration("Area 0"))

    assert refused.value.detail == FULL_RAMP_REFUSAL


async def test_at_the_bound_an_area_can_still_be_renamed_and_rebudgeted(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # Two of the three things the refusal says still work, so they are under test rather than
    # asserted in prose: the bound is on declaring an Area, not on changing one.
    service, _ = build_areas(principal, versions)
    declared = [
        await declare(service, principal, f"Area {index}") for index in range(PIGMENT_COUNT)
    ]

    changed = await service.update(
        principal, declared[0].id, AreaChange("Renamed", ABSENT, Decimal(10), Decimal(3))
    )

    assert changed.area.name == "Renamed"
    assert changed.area.budget_percent == Decimal(10)
    assert changed.area.floor_hours == Decimal(3)


async def test_at_the_bound_new_work_still_fits_inside_an_area_as_a_project(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # The third thing the refusal says still works. A Project carries no budget and no pigment,
    # so nothing about the ramp bounds it.
    service, areas = build_areas(principal, versions)
    inside = await declare(service, principal, "Career")
    for index in range(PIGMENT_COUNT - 1):
        await declare(service, principal, f"Area {index}")
    projects, stored, _ = build_projects(principal, areas=areas)

    created = await projects.create(
        principal,
        ProjectDeclaration(
            area_id=inside.id,
            name="Interview prep",
            deadline=None,
            status=ProjectStatus.ACTIVE,
        ),
    )

    assert created.area_id == inside.id
    assert len(stored.rows) == 1


# --------------------------------------------------------------------------------
# The ramp reading, and re-picking a step
# --------------------------------------------------------------------------------


async def test_a_full_ramp_is_reported_before_it_is_exhausted(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # The control at the other end of the boundary: twelve Areas hold twelve distinct steps.
    service, _ = build_areas(principal, versions)
    for index in range(PIGMENT_COUNT):
        await declare(service, principal, f"Area {index}")

    view = await service.list_all(principal)

    assert view.ramp.pigments_in_use == PIGMENT_COUNT


async def test_the_reading_counts_distinct_steps_when_rows_share_one(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # Rows declared before the bound existed can hold one step between them; the reading
    # reports how many distinct steps they hold rather than reconciling them.
    service, areas = build_areas(principal, versions)
    dealt = await declare(service, principal, "Dealt")
    predating = replace(
        a_stored_area(principal, 1), name="Predating", pigment_index=dealt.pigment_index
    )
    areas.rows.append(predating)

    view = await service.list_all(principal)

    assert len(areas.rows) == 2
    assert view.ramp.pigments_in_use == 1


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

    # Refused rather than stored: a duplicate name would leave two Areas that every
    # name-labeled surface renders as one.
    assert len(areas.rows) == 1
    assert "two Areas cannot share one" in str(refused.value.detail)


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
    # The scope arithmetic, on a hand-built principal. It is one of the four links between an
    # `Authorization` header and a 403, and the other three have no product route to run over
    # yet: every route here resolves a browser session, which carries every scope.
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
