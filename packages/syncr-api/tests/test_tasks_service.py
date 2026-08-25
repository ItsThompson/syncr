"""The Task service against fakes: the physics, the two Area checks, the endings, and the bump.

The repositories are replaced and the clock is injected, so "today" is a literal date and the week
the bump floors at is assertable without waiting for a Monday. The bump itself is the REAL
``BacklogWideBump`` over a recording counter, so what these tests assert is the actual
``WeekRange`` a mutation produces rather than the fact that some bump was requested.

The tests worth reading are the ones about what does NOT happen. Completing a task twice writes
nothing, bumps nothing, and does not move the completion's instant. Completing a dropped task is
refused rather than silently accepted. And both header figures deliberately ignore the status
filter, because a header that reported zero open tasks while the table showed completed ones would
not be a count of open tasks.

**The at-risk set is the week verdict's determination**, so the verdict is STATED here rather than
assembled and the tests are about which tasks each gap names. The arithmetic that decides that is
real and is driven over its own cases in ``test_at_risk_tasks.py``; what these assert is that this
service reads it rather than comparing a deadline against a capacity of its own.

The chunk-bound invariant is asserted against the MERGED pair on a patch, not against the fields one
request carried: lowering an estimate under a stored minimum chunk violates the same invariant as
raising the minimum above a stored estimate, and neither request names both numbers.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syncr_api.areas.records import AreaRecord, ProjectRecord
from syncr_api.areas.repository import AreaRepository, ProjectRepository
from syncr_api.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from syncr_api.core.patches import ABSENT
from syncr_api.core.principal import Principal
from syncr_api.core.scopes import ALL_SCOPES, Scope
from syncr_api.tasks.declarations import TaskChange, TaskDeclaration
from syncr_api.tasks.records import TaskRecord
from syncr_api.tasks.repository import TaskRepository
from syncr_api.tasks.service import TaskService
from syncr_api.user_settings.config import ReviewCadence
from syncr_api.user_settings.records import SettingsRecord
from syncr_api.user_settings.repository import SettingsRepository
from syncr_api.user_settings.solve_inputs import BacklogWideBump, WeekRange
from syncr_domain.feasibility import Provenance, Shortfall, ShortfallKind, Verdict
from syncr_domain.projects import ProjectStatus
from syncr_domain.tasks import (
    DEFAULT_ESTIMATE_MINUTES,
    DEFAULT_MIN_CHUNK_MINUTES,
    NO_RECORDED_MINUTES,
    Priority,
    TaskStatus,
)
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from datetime import datetime as DateTime

    from syncr_domain.identifiers import AreaId, ProjectId, TaskId, TenantId
    from syncr_domain.tasks import TaskEnding

LONDON = "Europe/London"

# A Sunday, the last day of 2026-W31, at 09:00 UTC: mid-morning in London, so the local date and
# the UTC date agree and these tests are about the backlog rather than about a date boundary.
NOW = datetime(2026, 8, 2, 9, 0, tzinfo=UTC)
LATER = datetime(2026, 8, 2, 17, 30, tzinfo=UTC)
WEEK_31 = IsoWeek.parse("2026-W31")

# A deadline inside the week ``NOW`` falls in, which is the week the at-risk reader answers about.
A_DEADLINE = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)

AN_HOUR = 60


class FakeTaskRepository(TaskRepository):
    """The real repository's interface over a list of records, and no database."""

    def __init__(self, tenant_id: TenantId, stored: list[TaskRecord] | None = None) -> None:
        self._tenant_id = tenant_id
        self.rows = list(stored or [])
        self.writes = 0

    async def list_all(
        self, *, area_id: AreaId | None = None, status: TaskStatus | None = None
    ) -> tuple[TaskRecord, ...]:
        ordered = sorted(self.rows, key=lambda row: (row.created_at, row.id))
        return tuple(
            row
            for row in ordered
            if (area_id is None or row.area_id == area_id)
            and (status is None or row.status is status)
        )

    async def count_open(self, *, area_id: AreaId | None = None) -> int:
        return len(await self.list_all(area_id=area_id, status=TaskStatus.OPEN))

    async def find(self, task_id: TaskId) -> TaskRecord | None:
        return next((row for row in self.rows if row.id == task_id), None)

    async def create(
        self,
        *,
        area_id: AreaId,
        project_id: ProjectId | None,
        title: str,
        estimate_minutes: int,
        deadline: DateTime | None,
        priority: Priority,
        min_chunk_minutes: int,
        splittable: bool,
        created_at: DateTime,
    ) -> TaskRecord:
        created = TaskRecord(
            id=uuid4(),
            tenant_id=self._tenant_id,
            area_id=area_id,
            project_id=project_id,
            title=title,
            estimate_minutes=estimate_minutes,
            deadline=deadline,
            priority=priority,
            min_chunk_minutes=min_chunk_minutes,
            splittable=splittable,
            status=TaskStatus.OPEN,
            recorded_minutes=NO_RECORDED_MINUTES,
            completed_at=None,
            created_at=created_at,
        )
        self.rows.append(created)
        self.writes += 1
        return created

    async def write(
        self,
        task_id: TaskId,
        *,
        project_id: ProjectId | None,
        title: str,
        estimate_minutes: int,
        deadline: DateTime | None,
        priority: Priority,
        min_chunk_minutes: int,
        splittable: bool,
    ) -> None:
        self.writes += 1
        self.rows = [
            TaskRecord(
                id=row.id,
                tenant_id=row.tenant_id,
                area_id=row.area_id,
                project_id=project_id,
                title=title,
                estimate_minutes=estimate_minutes,
                deadline=deadline,
                priority=priority,
                min_chunk_minutes=min_chunk_minutes,
                splittable=splittable,
                status=row.status,
                recorded_minutes=row.recorded_minutes,
                completed_at=row.completed_at,
                created_at=row.created_at,
            )
            if row.id == task_id
            else row
            for row in self.rows
        ]

    async def end(self, task_id: TaskId, *, ending: TaskEnding, at: DateTime | None) -> None:
        self.writes += 1
        self.rows = [
            TaskRecord(
                id=row.id,
                tenant_id=row.tenant_id,
                area_id=row.area_id,
                project_id=row.project_id,
                title=row.title,
                estimate_minutes=row.estimate_minutes,
                deadline=row.deadline,
                priority=row.priority,
                min_chunk_minutes=row.min_chunk_minutes,
                splittable=row.splittable,
                status=ending,
                recorded_minutes=row.recorded_minutes,
                completed_at=at,
                created_at=row.created_at,
            )
            if row.id == task_id
            else row
            for row in self.rows
        ]


class FakeAreaRepository(AreaRepository):
    """Only the read the Task service makes: does this Area exist, and whose is it."""

    def __init__(self, tenant_id: TenantId, stored: list[AreaRecord] | None = None) -> None:
        self._tenant_id = tenant_id
        self.rows = list(stored or [])

    async def find(self, area_id: AreaId) -> AreaRecord | None:
        return next((row for row in self.rows if row.id == area_id), None)


class FakeProjectRepository(ProjectRepository):
    """Only the read the Task service makes: does this Project exist, and in which Area."""

    def __init__(self, tenant_id: TenantId, stored: list[ProjectRecord] | None = None) -> None:
        self._tenant_id = tenant_id
        self.rows = list(stored or [])

    async def find(self, project_id: ProjectId) -> ProjectRecord | None:
        return next((row for row in self.rows if row.id == project_id), None)


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
    """Every range the bump asked to have applied, in order."""

    def __init__(self) -> None:
        self.bumped: list[WeekRange] = []

    async def bump(self, weeks: WeekRange) -> None:
        self.bumped.append(weeks)


class StatedVerdict:
    """The current week's verdict, stated rather than assembled.

    The service depends on the question rather than on plan storage's reader, so a test states what
    the week's verdict says and the at-risk arithmetic is exercised over it. The arithmetic itself
    is the real :func:`~syncr_api.plans.at_risk.tasks_at_risk`, driven end to end in
    ``test_at_risk_tasks.py`` over the cases a service test cannot reach.
    """

    def __init__(self, verdict: Verdict | None = None) -> None:
        self._verdict = verdict
        self.reads = 0

    async def read(self) -> Verdict | None:
        self.reads += 1
        return self._verdict


@pytest.fixture
def principal() -> Principal:
    return Principal(tenant_id=uuid4(), user_id=uuid4(), scopes=ALL_SCOPES)


@pytest.fixture
def versions() -> RecordingWeekInputVersions:
    return RecordingWeekInputVersions()


def an_area(tenant_id: TenantId, name: str = "Career") -> AreaRecord:
    return AreaRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        parent_id=None,
        name=name,
        pigment_index=0,
        budget_percent=None,
        floor_hours=None,
        created_at=NOW,
    )


def a_project(tenant_id: TenantId, area_id: AreaId) -> ProjectRecord:
    return ProjectRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        area_id=area_id,
        name="Job search",
        deadline=None,
        status=ProjectStatus.ACTIVE,
        created_at=NOW,
    )


def a_task(
    tenant_id: TenantId, area_id: AreaId, *, clock: DateTime = NOW, **changes: object
) -> TaskRecord:
    """A stored task, for the states no route in this module can produce.

    Recorded minutes and an ended status are what confirmed outcomes and the ending routes write;
    seeding them directly is how a read path over one is asserted here.
    """
    fields: dict[str, object] = {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "area_id": area_id,
        "project_id": None,
        "title": "Leetcode",
        "estimate_minutes": AN_HOUR,
        "deadline": None,
        "priority": Priority.NORMAL,
        "min_chunk_minutes": 15,
        "splittable": True,
        "status": TaskStatus.OPEN,
        "recorded_minutes": NO_RECORDED_MINUTES,
        "completed_at": None,
        "created_at": clock,
    }
    return TaskRecord(**{**fields, **changes})  # type: ignore[arg-type]


def build(
    principal: Principal,
    versions: RecordingWeekInputVersions,
    *,
    areas: list[AreaRecord] | None = None,
    projects: list[ProjectRecord] | None = None,
    tasks: list[TaskRecord] | None = None,
    verdict: Verdict | None = None,
    now: DateTime = NOW,
) -> tuple[TaskService, FakeTaskRepository]:
    stored = FakeTaskRepository(principal.tenant_id, tasks)
    service = TaskService(
        tasks=stored,
        areas=FakeAreaRepository(principal.tenant_id, areas),
        projects=FakeProjectRepository(principal.tenant_id, projects),
        bump=BacklogWideBump(
            versions=versions, settings=FakeSettingsRepository(principal.tenant_id)
        ),
        verdict=StatedVerdict(verdict),
        clock=lambda: now,
    )
    return service, stored


def a_declaration(area_id: AreaId, **changes: object) -> TaskDeclaration:
    """A capture that states only a title and an Area, unless a test states more."""
    fields: dict[str, object] = {
        "area_id": area_id,
        "title": "Leetcode",
        "project_id": None,
        "estimate_minutes": DEFAULT_ESTIMATE_MINUTES,
        "deadline": None,
        "priority": Priority.NORMAL,
        "min_chunk_minutes": None,
        "splittable": True,
    }
    return TaskDeclaration(**{**fields, **changes})  # type: ignore[arg-type]


def no_change(**changes: object) -> TaskChange:
    fields: dict[str, object] = {
        "title": ABSENT,
        "project_id": ABSENT,
        "estimate_minutes": ABSENT,
        "deadline": ABSENT,
        "priority": ABSENT,
        "min_chunk_minutes": ABSENT,
        "splittable": ABSENT,
    }
    return TaskChange(**{**fields, **changes})  # type: ignore[arg-type]


# --------------------------------------------------------------------------------
# Capture, and the two-value default
# --------------------------------------------------------------------------------


async def test_capturing_with_a_title_and_an_area_fills_every_other_value(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    area = an_area(principal.tenant_id)
    service, _ = build(principal, versions, areas=[area])

    captured = await service.capture(principal, a_declaration(area.id))

    assert captured.title == "Leetcode"
    assert captured.area_id == area.id
    assert captured.project_id is None
    assert captured.estimate_minutes == DEFAULT_ESTIMATE_MINUTES
    assert captured.min_chunk_minutes == DEFAULT_MIN_CHUNK_MINUTES
    assert captured.priority is Priority.NORMAL
    assert captured.splittable is True
    assert captured.deadline is None
    assert captured.status is TaskStatus.OPEN
    assert captured.recorded_minutes == NO_RECORDED_MINUTES
    assert captured.completed_at is None


async def test_a_captured_task_is_immediately_eligible_for_the_next_solve(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # A captured task is eligible at once, asserted through the same predicate the week assembler
    # will apply rather than through a comparison written here.
    area = an_area(principal.tenant_id)
    service, _ = build(principal, versions, areas=[area])

    captured = await service.capture(principal, a_declaration(area.id))

    assert captured.is_eligible_for_solving() is True
    assert captured.remaining_minutes() == DEFAULT_ESTIMATE_MINUTES


async def test_capturing_bumps_the_current_week_and_every_week_after_it(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # A task belongs to no week: it is backlog content the assembler may place in any week the
    # user has not yet lived, so the range has no end. Past weeks are never bumped, because an
    # approved revision keeps the inputs it was computed with.
    area = an_area(principal.tenant_id)
    service, _ = build(principal, versions, areas=[area])

    await service.capture(principal, a_declaration(area.id))

    assert versions.bumped == [WeekRange(first=WEEK_31, last=None)]


async def test_a_stated_minimum_chunk_is_kept_rather_than_defaulted(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    area = an_area(principal.tenant_id)
    service, _ = build(principal, versions, areas=[area])

    captured = await service.capture(
        principal, a_declaration(area.id, estimate_minutes=90, min_chunk_minutes=45)
    )

    assert captured.min_chunk_minutes == 45


async def test_an_estimate_smaller_than_the_grid_step_is_refused_naming_the_chunk(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # The default chunk is clamped down to the estimate, so a 10-minute estimate derives a
    # 10-minute chunk. The clamp keeps T1 quiet, but the derived chunk is still the smallest
    # placement a splittable task may take, and no block can hold one that misses the grid: no
    # legal chunk exists for this estimate, so capture is refused and names the field the rule
    # answers about.
    area = an_area(principal.tenant_id)
    service, tasks = build(principal, versions, areas=[area])

    with pytest.raises(ValidationFailed) as refused:
        await service.capture(principal, a_declaration(area.id, estimate_minutes=10))

    assert [error.field for error in refused.value.errors or []] == ["minChunkMinutes"]
    assert tasks.rows == []
    assert versions.bumped == []


async def test_a_minimum_chunk_off_the_grid_is_refused_and_stores_nothing(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # 25 passes the schema's floor of one grid step but misses the grid itself, so the refusal
    # is the domain's, stated beside T1 rather than inside it.
    area = an_area(principal.tenant_id)
    service, tasks = build(principal, versions, areas=[area])

    with pytest.raises(ValidationFailed) as refused:
        await service.capture(
            principal, a_declaration(area.id, estimate_minutes=90, min_chunk_minutes=25)
        )

    assert "does not land on the 15-minute grid" in refused.value.detail
    assert "Nothing was changed" in refused.value.detail
    assert [error.field for error in refused.value.errors or []] == ["minChunkMinutes"]
    assert tasks.rows == []
    assert versions.bumped == []


async def test_a_minimum_chunk_above_the_estimate_is_refused_and_stores_nothing(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    area = an_area(principal.tenant_id)
    service, tasks = build(principal, versions, areas=[area])

    with pytest.raises(ValidationFailed) as refused:
        await service.capture(
            principal, a_declaration(area.id, estimate_minutes=60, min_chunk_minutes=61)
        )

    # The reason travels, and both numbers are named: either could be the one the caller meant.
    assert "does not fit" in refused.value.detail
    assert "Nothing was changed" in refused.value.detail
    assert [error.field for error in refused.value.errors or []] == [
        "minChunkMinutes",
        "estimateMinutes",
    ]
    assert tasks.rows == []
    assert versions.bumped == []


async def test_an_unknown_area_is_refused_and_stores_nothing(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, tasks = build(principal, versions)

    with pytest.raises(ValidationFailed) as refused:
        await service.capture(principal, a_declaration(uuid4()))

    assert [error.field for error in refused.value.errors or []] == ["areaId"]
    assert tasks.rows == []
    assert versions.bumped == []


async def test_an_unknown_project_is_refused_and_stores_nothing(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    area = an_area(principal.tenant_id)
    service, tasks = build(principal, versions, areas=[area])

    with pytest.raises(ValidationFailed) as refused:
        await service.capture(principal, a_declaration(area.id, project_id=uuid4()))

    assert [error.field for error in refused.value.errors or []] == ["projectId"]
    assert tasks.rows == []


async def test_a_project_in_another_area_is_refused_because_one_hour_counts_once(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # A comparison between two stored rows, which is why it is here and not in a schema.
    career = an_area(principal.tenant_id, "Career")
    fitness = an_area(principal.tenant_id, "Fitness")
    project = a_project(principal.tenant_id, career.id)
    service, tasks = build(principal, versions, areas=[career, fitness], projects=[project])

    with pytest.raises(ValidationFailed) as refused:
        await service.capture(principal, a_declaration(fitness.id, project_id=project.id))

    assert [error.field for error in refused.value.errors or []] == ["projectId"]
    assert "attributable twice" in refused.value.detail
    assert tasks.rows == []


async def test_a_project_in_the_task_s_own_area_is_accepted(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    area = an_area(principal.tenant_id)
    project = a_project(principal.tenant_id, area.id)
    service, _ = build(principal, versions, areas=[area], projects=[project])

    captured = await service.capture(principal, a_declaration(area.id, project_id=project.id))

    assert captured.project_id == project.id


# --------------------------------------------------------------------------------
# Change, and the chunk bound over the merged pair
# --------------------------------------------------------------------------------


async def test_lowering_an_estimate_under_the_stored_minimum_chunk_is_refused(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # The case a request schema could not catch: this body carries no minimum chunk at all, so
    # the violation is only visible against the merged pair.
    area = an_area(principal.tenant_id)
    stored = a_task(principal.tenant_id, area.id, estimate_minutes=90, min_chunk_minutes=45)
    service, tasks = build(principal, versions, areas=[area], tasks=[stored])

    with pytest.raises(ValidationFailed):
        await service.update(principal, stored.id, no_change(estimate_minutes=30))

    assert tasks.writes == 0
    assert tasks.rows == [stored]
    assert versions.bumped == []


async def test_raising_a_minimum_chunk_above_the_stored_estimate_is_refused(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    area = an_area(principal.tenant_id)
    stored = a_task(principal.tenant_id, area.id, estimate_minutes=60, min_chunk_minutes=15)
    service, tasks = build(principal, versions, areas=[area], tasks=[stored])

    with pytest.raises(ValidationFailed):
        await service.update(principal, stored.id, no_change(min_chunk_minutes=61))

    assert tasks.writes == 0


async def test_patching_a_minimum_chunk_off_the_grid_is_refused(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # The merged pair fits T1; the refusal is the new value's shape alone.
    area = an_area(principal.tenant_id)
    stored = a_task(principal.tenant_id, area.id, estimate_minutes=90, min_chunk_minutes=15)
    service, tasks = build(principal, versions, areas=[area], tasks=[stored])

    with pytest.raises(ValidationFailed) as refused:
        await service.update(principal, stored.id, no_change(min_chunk_minutes=25))

    assert [error.field for error in refused.value.errors or []] == ["minChunkMinutes"]
    assert tasks.writes == 0
    assert tasks.rows == [stored]


async def test_changing_both_numbers_together_is_accepted(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    area = an_area(principal.tenant_id)
    stored = a_task(principal.tenant_id, area.id, estimate_minutes=60, min_chunk_minutes=15)
    service, _ = build(principal, versions, areas=[area], tasks=[stored])

    changed = await service.update(
        principal, stored.id, no_change(estimate_minutes=30, min_chunk_minutes=30)
    )

    assert (changed.estimate_minutes, changed.min_chunk_minutes) == (30, 30)


async def test_an_omitted_field_is_left_alone_and_an_explicit_null_clears_a_deadline(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    area = an_area(principal.tenant_id)
    stored = a_task(principal.tenant_id, area.id, deadline=LATER)
    service, _ = build(principal, versions, areas=[area], tasks=[stored])

    untouched = await service.update(principal, stored.id, no_change(title="Leetcode, harder"))
    assert untouched.deadline == LATER
    assert untouched.title == "Leetcode, harder"

    cleared = await service.update(principal, stored.id, no_change(deadline=None))
    assert cleared.deadline is None


async def test_changing_a_task_bumps_the_current_week_onwards(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # Every field on an ELIGIBLE task is a solve-input change: the assembler reads the title, the
    # estimate, the physics, and the deadline, so there is no field on one the solver cannot see.
    area = an_area(principal.tenant_id)
    stored = a_task(principal.tenant_id, area.id)
    service, _ = build(principal, versions, areas=[area], tasks=[stored])

    await service.update(principal, stored.id, no_change(title="Leetcode, harder"))

    assert versions.bumped == [WeekRange(first=WEEK_31, last=None)]


async def test_a_change_that_states_nothing_bumps_nothing(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # An empty PATCH body leaves the record identical, so there is nothing for a solve to re-read
    # and invalidating a running one would cost it its work for nothing.
    area = an_area(principal.tenant_id)
    stored = a_task(principal.tenant_id, area.id)
    service, _ = build(principal, versions, areas=[area], tasks=[stored])

    unchanged = await service.update(principal, stored.id, no_change())

    assert unchanged == stored
    assert versions.bumped == []


async def test_changing_a_task_no_solve_can_see_bumps_nothing(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # An ended task is not collected by the assembler, so correcting what a report says about one
    # invalidates nothing. Asserted with the editability it depends on, because the two are one
    # action: a correction to an ended task is allowed AND is not a solve-input change.
    area = an_area(principal.tenant_id)
    stored = a_task(principal.tenant_id, area.id, status=TaskStatus.COMPLETED, completed_at=NOW)
    service, _ = build(principal, versions, areas=[area], tasks=[stored])

    corrected = await service.update(principal, stored.id, no_change(estimate_minutes=120))

    assert corrected.estimate_minutes == 120
    assert corrected.status is TaskStatus.COMPLETED
    assert corrected.completed_at == NOW
    assert versions.bumped == []


async def test_a_change_that_creates_eligibility_bumps(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # The case that makes the gate ask about BOTH sides. This task is open and ineligible, because
    # its recorded time has caught up with its estimate; raising the estimate puts it back in the
    # backlog, which is a solve-input change even though the side it started on was ineligible.
    area = an_area(principal.tenant_id)
    stored = a_task(principal.tenant_id, area.id, estimate_minutes=60, recorded_minutes=60)
    service, _ = build(principal, versions, areas=[area], tasks=[stored])
    assert stored.is_eligible_for_solving() is False

    revived = await service.update(principal, stored.id, no_change(estimate_minutes=120))

    assert revived.is_eligible_for_solving() is True
    assert versions.bumped == [WeekRange(first=WEEK_31, last=None)]


async def test_a_change_that_ends_eligibility_bumps(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # The other side of the same rule: the task leaves the backlog, which the assembler has to see.
    area = an_area(principal.tenant_id)
    stored = a_task(principal.tenant_id, area.id, estimate_minutes=120, recorded_minutes=60)
    service, _ = build(principal, versions, areas=[area], tasks=[stored])

    spent = await service.update(principal, stored.id, no_change(estimate_minutes=60))

    assert spent.is_eligible_for_solving() is False
    assert versions.bumped == [WeekRange(first=WEEK_31, last=None)]


async def test_ending_a_task_no_solve_could_see_bumps_nothing(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # An open task whose recorded time has already caught up is not in the assembler's backlog, so
    # taking it out of one it was not in invalidates nothing. The write still happens.
    area = an_area(principal.tenant_id)
    stored = a_task(principal.tenant_id, area.id, estimate_minutes=60, recorded_minutes=60)
    service, tasks = build(principal, versions, areas=[area], tasks=[stored])

    completed = await service.complete(principal, stored.id)

    assert completed.status is TaskStatus.COMPLETED
    assert tasks.writes == 1
    assert versions.bumped == []


async def test_a_change_cannot_reach_the_area_the_status_or_the_recorded_time(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # None of the three is a member of `TaskChange`, so `applied_to` carries them through by
    # construction rather than by remembering to. The wire half, where sending one is a stated 422,
    # is asserted over HTTP.
    area = an_area(principal.tenant_id)
    stored = a_task(
        principal.tenant_id,
        area.id,
        status=TaskStatus.COMPLETED,
        completed_at=NOW,
        recorded_minutes=45,
    )
    service, _ = build(principal, versions, areas=[area], tasks=[stored])

    changed = await service.update(principal, stored.id, no_change(title="renamed"))

    assert changed.area_id == stored.area_id
    assert changed.status is TaskStatus.COMPLETED
    assert changed.completed_at == NOW
    assert changed.recorded_minutes == 45


async def test_changing_a_task_that_does_not_exist_is_a_404(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, _ = build(principal, versions)

    with pytest.raises(NotFound):
        await service.update(principal, uuid4(), no_change(title="x"))


async def test_another_tenant_s_task_is_a_404_rather_than_an_edit(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # The scoped SELECT is what produces this in production; the check is defense in depth, and
    # the fake repository is unscoped precisely so the check itself is what answers here.
    stranger = a_task(uuid4(), uuid4())
    service, tasks = build(principal, versions, tasks=[stranger])

    with pytest.raises(NotFound):
        await service.update(principal, stranger.id, no_change(title="theirs"))

    assert tasks.writes == 0


# --------------------------------------------------------------------------------
# The two endings
# --------------------------------------------------------------------------------


async def test_completing_a_task_records_the_instant_and_keeps_the_recorded_time(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # The recorded time is what a report reads, so completing must not touch it.
    area = an_area(principal.tenant_id)
    stored = a_task(principal.tenant_id, area.id, estimate_minutes=90, recorded_minutes=30)
    service, tasks = build(principal, versions, areas=[area], tasks=[stored], now=LATER)

    completed = await service.complete(principal, stored.id)

    assert completed.status is TaskStatus.COMPLETED
    assert completed.completed_at == LATER
    assert completed.recorded_minutes == 30
    assert completed.estimate_minutes == 90
    assert tasks.rows[0].recorded_minutes == 30


async def test_completing_a_task_takes_it_out_of_eligibility_immediately(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    area = an_area(principal.tenant_id)
    stored = a_task(principal.tenant_id, area.id)
    service, _ = build(principal, versions, areas=[area], tasks=[stored])
    assert stored.is_eligible_for_solving() is True

    completed = await service.complete(principal, stored.id)

    # It still declares an hour of work, and it is still ineligible: the status is what ends
    # eligibility, not the arithmetic.
    assert completed.remaining_minutes() == AN_HOUR
    assert completed.is_eligible_for_solving() is False


async def test_a_partially_completed_splittable_task_keeps_its_time_and_reduces_what_is_left(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # A partially completed task keeps its time. The recorded figure comes from confirmed outcomes,
    # which no route here writes, so it is seeded.
    area = an_area(principal.tenant_id)
    stored = a_task(
        principal.tenant_id, area.id, estimate_minutes=90, recorded_minutes=30, splittable=True
    )
    service, _ = build(principal, versions, areas=[area], tasks=[stored])

    read = await service.read(principal, stored.id)

    assert read.recorded_minutes == 30
    assert read.remaining_minutes() == 60
    assert read.is_eligible_for_solving() is True


async def test_recording_more_than_the_estimate_reports_no_remaining_work_rather_than_negative(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # The clamp, composed through the service: an estimate is a guess and an outcome is a
    # fact, so overrunning is ordinary and must not produce a negative quantity of work.
    area = an_area(principal.tenant_id)
    stored = a_task(principal.tenant_id, area.id, estimate_minutes=60, recorded_minutes=180)
    service, _ = build(principal, versions, areas=[area], tasks=[stored])

    read = await service.read(principal, stored.id)

    assert read.remaining_minutes() == 0
    assert read.is_eligible_for_solving() is False


async def test_completing_bumps_the_current_week_onwards(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    area = an_area(principal.tenant_id)
    stored = a_task(principal.tenant_id, area.id)
    service, _ = build(principal, versions, areas=[area], tasks=[stored])

    await service.complete(principal, stored.id)

    assert versions.bumped == [WeekRange(first=WEEK_31, last=None)]


async def test_completing_a_completed_task_writes_nothing_and_does_not_move_the_instant(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # What makes a retried completion safe without a key. A bump would supersede a running solve
    # for a change that did not happen, and a moved instant would move a completion in a report.
    area = an_area(principal.tenant_id)
    stored = a_task(principal.tenant_id, area.id, status=TaskStatus.COMPLETED, completed_at=NOW)
    service, tasks = build(principal, versions, areas=[area], tasks=[stored], now=LATER)

    again = await service.complete(principal, stored.id)

    assert again.completed_at == NOW
    assert tasks.writes == 0
    assert versions.bumped == []


async def test_dropping_a_task_takes_it_out_of_eligibility_without_a_completion_instant(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    area = an_area(principal.tenant_id)
    stored = a_task(principal.tenant_id, area.id)
    service, _ = build(principal, versions, areas=[area], tasks=[stored])

    dropped = await service.drop(principal, stored.id)

    assert dropped.status is TaskStatus.DROPPED
    assert dropped.completed_at is None
    assert dropped.is_eligible_for_solving() is False
    assert versions.bumped == [WeekRange(first=WEEK_31, last=None)]


async def test_dropping_a_dropped_task_writes_nothing_and_bumps_nothing(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    area = an_area(principal.tenant_id)
    stored = a_task(principal.tenant_id, area.id, status=TaskStatus.DROPPED)
    service, tasks = build(principal, versions, areas=[area], tasks=[stored])

    again = await service.drop(principal, stored.id)

    assert again.status is TaskStatus.DROPPED
    assert tasks.writes == 0
    assert versions.bumped == []


async def test_completing_a_dropped_task_is_a_conflict_and_changes_nothing(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    area = an_area(principal.tenant_id)
    stored = a_task(principal.tenant_id, area.id, status=TaskStatus.DROPPED)
    service, tasks = build(principal, versions, areas=[area], tasks=[stored])

    with pytest.raises(Conflict) as refused:
        await service.complete(principal, stored.id)

    assert "already dropped" in refused.value.detail
    assert "still reads as it did" in refused.value.detail
    assert tasks.writes == 0
    assert versions.bumped == []


async def test_dropping_a_completed_task_is_a_conflict_and_changes_nothing(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # The half that protects a report: a completion counted by one must not be erasable by a
    # drop.
    area = an_area(principal.tenant_id)
    stored = a_task(principal.tenant_id, area.id, status=TaskStatus.COMPLETED, completed_at=NOW)
    service, tasks = build(principal, versions, areas=[area], tasks=[stored])

    with pytest.raises(Conflict):
        await service.drop(principal, stored.id)

    assert tasks.writes == 0
    assert tasks.rows[0].completed_at == NOW


async def test_an_ended_task_is_still_editable_because_a_report_can_be_corrected(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # The editability itself, asserted where the endings are, because a reader looking at the two
    # terminal statuses is who asks whether one of them freezes the row. What it costs in inputs is
    # asserted with the bump, above.
    area = an_area(principal.tenant_id)
    stored = a_task(principal.tenant_id, area.id, status=TaskStatus.DROPPED)
    service, tasks = build(principal, versions, areas=[area], tasks=[stored])

    corrected = await service.update(principal, stored.id, no_change(title="a better title"))

    assert corrected.title == "a better title"
    assert corrected.status is TaskStatus.DROPPED
    assert tasks.writes == 1


# --------------------------------------------------------------------------------
# The list, and the count its header states
# --------------------------------------------------------------------------------


async def test_the_list_is_oldest_first_so_two_identical_reads_agree(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    area = an_area(principal.tenant_id)
    first = a_task(principal.tenant_id, area.id, title="first", clock=NOW)
    second = a_task(principal.tenant_id, area.id, title="second", clock=LATER)
    service, _ = build(principal, versions, areas=[area], tasks=[second, first])

    backlog = await service.list_all(principal)

    assert [task.title for task in backlog.tasks] == ["first", "second"]


async def test_the_area_filter_narrows_the_list(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    career = an_area(principal.tenant_id, "Career")
    fitness = an_area(principal.tenant_id, "Fitness")
    service, _ = build(
        principal,
        versions,
        areas=[career, fitness],
        tasks=[
            a_task(principal.tenant_id, career.id, title="Leetcode"),
            a_task(principal.tenant_id, fitness.id, title="Legs"),
        ],
    )

    backlog = await service.list_all(principal, area_id=fitness.id)

    assert [task.title for task in backlog.tasks] == ["Legs"]


async def test_the_status_filter_narrows_the_list(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    area = an_area(principal.tenant_id)
    service, _ = build(
        principal,
        versions,
        areas=[area],
        tasks=[
            a_task(principal.tenant_id, area.id, title="open one"),
            a_task(
                principal.tenant_id,
                area.id,
                title="done one",
                status=TaskStatus.COMPLETED,
                completed_at=NOW,
            ),
        ],
    )

    backlog = await service.list_all(principal, status=TaskStatus.COMPLETED)

    assert [task.title for task in backlog.tasks] == ["done one"]


async def test_the_open_count_ignores_the_status_filter(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # A header that reported zero open tasks because the table was filtered to completed ones
    # would not be a count of open tasks.
    area = an_area(principal.tenant_id)
    service, _ = build(
        principal,
        versions,
        areas=[area],
        tasks=[
            a_task(principal.tenant_id, area.id, title="open one"),
            a_task(principal.tenant_id, area.id, title="open two"),
            a_task(
                principal.tenant_id,
                area.id,
                title="done one",
                status=TaskStatus.COMPLETED,
                completed_at=NOW,
            ),
        ],
    )

    filtered = await service.list_all(principal, status=TaskStatus.COMPLETED)

    assert [task.title for task in filtered.tasks] == ["done one"]
    assert filtered.open_count == 2


async def test_the_open_count_honors_the_area_filter_because_it_narrows_the_screen(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    career = an_area(principal.tenant_id, "Career")
    fitness = an_area(principal.tenant_id, "Fitness")
    service, _ = build(
        principal,
        versions,
        areas=[career, fitness],
        tasks=[
            a_task(principal.tenant_id, career.id),
            a_task(principal.tenant_id, career.id),
            a_task(principal.tenant_id, fitness.id),
        ],
    )

    assert (await service.list_all(principal)).open_count == 3
    assert (await service.list_all(principal, area_id=fitness.id)).open_count == 1


async def test_a_dropped_task_is_not_counted_as_open(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    area = an_area(principal.tenant_id)
    service, _ = build(
        principal,
        versions,
        areas=[area],
        tasks=[a_task(principal.tenant_id, area.id, status=TaskStatus.DROPPED)],
    )

    assert (await service.list_all(principal)).open_count == 0


async def test_reading_a_task_that_does_not_exist_is_a_404(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, _ = build(principal, versions)

    with pytest.raises(NotFound):
        await service.read(principal, uuid4())


async def test_a_read_bumps_nothing(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    area = an_area(principal.tenant_id)
    stored = a_task(principal.tenant_id, area.id)
    service, _ = build(principal, versions, areas=[area], tasks=[stored])

    await service.list_all(principal)
    await service.read(principal, stored.id)

    assert versions.bumped == []


# --------------------------------------------------------------------------------
# The at-risk set: the verdict's determination, over the same population as the open count
# --------------------------------------------------------------------------------


def a_deadline_gap(*names: str, area_id: AreaId) -> Shortfall:
    """The gap the probe raises for work that does not fit before the instant it is due."""
    return Shortfall(
        kind=ShortfallKind.DEADLINE_CAPACITY,
        minutes=80,
        against=names,
        honoring=("the 4h still uncommitted before it",),
        deadline=A_DEADLINE,
        area_id=area_id,
    )


def a_verdict(*shortfalls: Shortfall) -> Verdict:
    return Verdict(
        feasible=False,
        provenance=Provenance.PROBE,
        computed_at=NOW,
        input_version=4,
        discretionary_minutes=6720,
        shortfalls=shortfalls,
    )


async def test_the_at_risk_set_is_the_verdicts_and_no_comparison_of_this_services_own(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    """Two tasks due at the same instant, and the verdict names one of them.

    A service that compared a deadline against a capacity of its own would have no way to tell them
    apart, because both are open, both are due, and both have the same remaining work.
    """
    area = an_area(principal.tenant_id)
    named = a_task(principal.tenant_id, area.id, title="Leetcode", deadline=A_DEADLINE)
    other = a_task(principal.tenant_id, area.id, title="Mock interview", deadline=A_DEADLINE)
    service, _ = build(
        principal,
        versions,
        areas=[area],
        tasks=[named, other],
        verdict=a_verdict(a_deadline_gap("Leetcode", area_id=area.id)),
    )

    backlog = await service.list_all(principal)

    assert backlog.at_risk == {named.id}


async def test_a_week_whose_verdict_found_no_gap_puts_nothing_at_risk(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    area = an_area(principal.tenant_id)
    service, _ = build(
        principal,
        versions,
        areas=[area],
        tasks=[a_task(principal.tenant_id, area.id, deadline=A_DEADLINE)],
        verdict=a_verdict(),
    )

    assert (await service.list_all(principal)).at_risk == frozenset()


async def test_a_week_with_no_plan_puts_nothing_at_risk(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    """``None`` is what the reader answers for a week the maintainer has not reached.

    Not a shape invented for this test: ``CurrentWeekVerdict.read`` returns ``None`` when the
    current week holds no plan of record, which is driven over its own fakes in
    ``test_served_verdict.py`` and over a real request beside the week read in
    ``test_at_risk_integration.py``. This asserts what the service does WITH that answer, which is
    the only part it owns.
    """
    area = an_area(principal.tenant_id)
    service, _ = build(
        principal,
        versions,
        areas=[area],
        tasks=[a_task(principal.tenant_id, area.id, deadline=A_DEADLINE)],
        verdict=None,
    )

    assert (await service.list_all(principal)).at_risk == frozenset()


async def test_the_at_risk_set_ignores_the_status_filter_the_way_the_open_count_does(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    """Filtering the table to completed tasks does not change how many are at risk.

    The set is derived over the Area's OPEN tasks rather than over the page, so the header's figure
    and the marked rows are one answer even when the page holds neither.
    """
    area = an_area(principal.tenant_id)
    named = a_task(principal.tenant_id, area.id, title="Leetcode", deadline=A_DEADLINE)
    service, _ = build(
        principal,
        versions,
        areas=[area],
        tasks=[
            named,
            a_task(
                principal.tenant_id,
                area.id,
                title="done one",
                status=TaskStatus.COMPLETED,
                completed_at=NOW,
            ),
        ],
        verdict=a_verdict(a_deadline_gap("Leetcode", area_id=area.id)),
    )

    filtered = await service.list_all(principal, status=TaskStatus.COMPLETED)

    assert [task.title for task in filtered.tasks] == ["done one"]
    assert filtered.at_risk == {named.id}


async def test_the_at_risk_set_honors_the_area_filter_because_it_narrows_the_screen(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    """The gap belongs to one Area, and so does the screen when the filter is on."""
    career = an_area(principal.tenant_id, "Career")
    fitness = an_area(principal.tenant_id, "Fitness")
    career_task = a_task(principal.tenant_id, career.id, title="Leetcode", deadline=A_DEADLINE)
    service, _ = build(
        principal,
        versions,
        areas=[career, fitness],
        tasks=[career_task, a_task(principal.tenant_id, fitness.id, deadline=A_DEADLINE)],
        verdict=a_verdict(a_deadline_gap("Leetcode", area_id=career.id)),
    )

    assert (await service.list_all(principal)).at_risk == {career_task.id}
    assert (await service.list_all(principal, area_id=fitness.id)).at_risk == frozenset()


async def test_a_completed_task_the_verdict_still_names_is_not_at_risk(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    """The population is the open tasks, so a task that has left the backlog cannot be in the set.

    A verdict is computed from an assembly and the backlog is read after it, so a task completed
    between the two is named by a gap nothing has recomputed yet.
    """
    area = an_area(principal.tenant_id)
    done = a_task(
        principal.tenant_id,
        area.id,
        title="Leetcode",
        deadline=A_DEADLINE,
        status=TaskStatus.COMPLETED,
        completed_at=NOW,
    )
    service, _ = build(
        principal,
        versions,
        areas=[area],
        tasks=[done],
        verdict=a_verdict(a_deadline_gap("Leetcode", area_id=area.id)),
    )

    assert (await service.list_all(principal)).at_risk == frozenset()


async def test_the_at_risk_filter_selects_the_rows_the_verdict_marks(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    """``atRisk=true`` narrows the rows to the marked set, and to nothing else.

    Two tasks due at the same instant with the same remaining work, and the verdict names one: a
    narrowing computed from the rows rather than from the verdict's own names could not tell them
    apart, which is the whole reason the filter is served here rather than applied by a client.
    """
    area = an_area(principal.tenant_id)
    named = a_task(principal.tenant_id, area.id, title="Leetcode", deadline=A_DEADLINE)
    other = a_task(principal.tenant_id, area.id, title="Mock interview", deadline=A_DEADLINE)
    service, _ = build(
        principal,
        versions,
        areas=[area],
        tasks=[named, other],
        verdict=a_verdict(a_deadline_gap("Leetcode", area_id=area.id)),
    )

    filtered = await service.list_all(principal, at_risk=True)

    assert [task.id for task in filtered.tasks] == [named.id]


async def test_the_at_risk_filter_inverted_selects_every_row_the_verdict_does_not_mark(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    """``atRisk=false`` is the complement, so the two answers partition the unfiltered list.

    Asserted as a partition rather than as one membership, because a filter that answered the same
    rows for both values would pass a test that only drove the true case.
    """
    area = an_area(principal.tenant_id)
    named = a_task(principal.tenant_id, area.id, title="Leetcode", deadline=A_DEADLINE)
    other = a_task(principal.tenant_id, area.id, title="Mock interview", deadline=A_DEADLINE)
    service, _ = build(
        principal,
        versions,
        areas=[area],
        tasks=[named, other],
        verdict=a_verdict(a_deadline_gap("Leetcode", area_id=area.id)),
    )

    marked = await service.list_all(principal, at_risk=True)
    rest = await service.list_all(principal, at_risk=False)
    every = await service.list_all(principal)

    assert [task.id for task in rest.tasks] == [other.id]
    assert {task.id for task in marked.tasks} | {task.id for task in rest.tasks} == {
        task.id for task in every.tasks
    }


async def test_the_at_risk_filter_leaves_both_header_figures_alone(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    """Narrowing the table to the marked rows does not change how many of them there are.

    The same rule ``openCount`` already has for the status filter, and for the same reason: a header
    reporting the page rather than the backlog would disagree with itself as a filter moved.
    """
    area = an_area(principal.tenant_id)
    named = a_task(principal.tenant_id, area.id, title="Leetcode", deadline=A_DEADLINE)
    service, _ = build(
        principal,
        versions,
        areas=[area],
        tasks=[named, a_task(principal.tenant_id, area.id, title="Mock interview")],
        verdict=a_verdict(a_deadline_gap("Leetcode", area_id=area.id)),
    )

    for wanted in (None, True, False):
        answered = await service.list_all(principal, at_risk=wanted)
        assert answered.open_count == 2, wanted
        assert answered.at_risk == {named.id}, wanted


async def test_asking_for_the_marked_rows_among_completed_ones_answers_with_none(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    """The two filters intersect rather than one overriding the other.

    The marked set is derived over the Area's OPEN tasks, so no completed row can be in it. The
    empty answer is the intersection of the filters the caller sent, and the header still states the
    figures over the open population, which is what keeps this an intersection rather than a bug.
    """
    area = an_area(principal.tenant_id)
    named = a_task(principal.tenant_id, area.id, title="Leetcode", deadline=A_DEADLINE)
    service, _ = build(
        principal,
        versions,
        areas=[area],
        tasks=[
            named,
            a_task(
                principal.tenant_id,
                area.id,
                title="done one",
                status=TaskStatus.COMPLETED,
                completed_at=NOW,
            ),
        ],
        verdict=a_verdict(a_deadline_gap("Leetcode", area_id=area.id)),
    )

    filtered = await service.list_all(principal, status=TaskStatus.COMPLETED, at_risk=True)

    assert filtered.tasks == ()
    assert filtered.at_risk == {named.id}
    assert filtered.open_count == 1


async def test_reading_the_backlog_reads_the_verdict_once(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    """One read of the week's verdict per backlog read, because it costs a whole assembly."""
    area = an_area(principal.tenant_id)
    stored = FakeTaskRepository(principal.tenant_id, [a_task(principal.tenant_id, area.id)])
    reader = StatedVerdict(a_verdict())
    service = TaskService(
        tasks=stored,
        areas=FakeAreaRepository(principal.tenant_id, [area]),
        projects=FakeProjectRepository(principal.tenant_id, None),
        bump=BacklogWideBump(
            versions=versions, settings=FakeSettingsRepository(principal.tenant_id)
        ),
        verdict=reader,
        clock=lambda: NOW,
    )

    await service.list_all(principal)

    assert reader.reads == 1


# --------------------------------------------------------------------------------
# Scopes
# --------------------------------------------------------------------------------


async def test_a_credential_without_plan_write_cannot_capture_a_task(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # The scope arithmetic, on a hand-built principal. It is one of the four links between an
    # `Authorization` header and a 403, and the other three have no product route to run over
    # yet: every route here resolves a browser session, which carries every scope.
    area = an_area(principal.tenant_id)
    service, tasks = build(principal, versions, areas=[area])
    reader = Principal(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        scopes=frozenset({Scope.PLAN_READ}),
    )

    with pytest.raises(Forbidden):
        await service.capture(reader, a_declaration(area.id))

    # Refused means not stored, and the read the same credential DOES carry still works.
    assert tasks.rows == []
    assert (await service.list_all(reader)).tasks == ()


async def test_a_credential_without_plan_read_cannot_list_the_backlog(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, _ = build(principal, versions)
    stranger = Principal(
        tenant_id=principal.tenant_id, user_id=principal.user_id, scopes=frozenset()
    )

    with pytest.raises(Forbidden):
        await service.list_all(stranger)


@pytest.mark.parametrize("ending", ["complete", "drop"])
async def test_a_credential_without_plan_write_cannot_end_a_task(
    principal: Principal, versions: RecordingWeekInputVersions, ending: str
) -> None:
    area = an_area(principal.tenant_id)
    stored = a_task(principal.tenant_id, area.id)
    service, tasks = build(principal, versions, areas=[area], tasks=[stored])
    reader = Principal(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        scopes=frozenset({Scope.PLAN_READ}),
    )

    with pytest.raises(Forbidden):
        await getattr(service, ending)(reader, stored.id)

    assert tasks.writes == 0
