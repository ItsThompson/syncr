"""The Task service: authorization, the physics, the two Area checks, and the version bump.

Five rules live here rather than anywhere else.

**A capture needs a title and an Area.** Every other value has a default, and the one default
that is derived rather than constant, the minimum chunk, is resolved here from the domain's own
derivation. A route cannot resolve it: the derivation exists to keep T1 true, and T1 is stated in
the domain.

**T1 is checked against the MERGED pair, on capture and on every change.** A patch that lowers an
estimate under a stored minimum chunk violates it just as a capture with an oversized minimum
does, and neither request carries both numbers, so the comparison is made after the change is
applied to the stored row and before anything is written.

**A task's Area is checked against two stored rows.** It has to exist, and when a Project is
named its Area has to be the task's Area (X2), which is a comparison a request schema cannot make
because it can see neither row. ``syncr_domain.projects.require_matching_area`` is the one
statement of that rule.

**A task is a solve input, so a mutation bumps the week input version** from the current week
onwards. A task belongs to no week: it is backlog content the assembler may place in any week the
user has not yet lived, which is exactly the range ``BacklogWideBump`` covers. Past weeks are not
touched, because an approved revision is immutable and keeps the inputs it was computed with.

**A mutation a solve cannot see bumps nothing**, which is the same gate ``AreaService.update``
applies for the same reason: invalidating a running solve costs it its work, so it is done only
when a solve would read the change. For an Area the exempt thing is a FIELD, the name; for a task
it is the ROW, because an ineligible task is not collected at all.
:func:`~syncr_api.tasks.records.changes_a_solve_input` is the one statement of it.

**Ending a task twice the same way writes nothing and bumps nothing.** A retried completion is
answered with the stored task, its instant unmoved, because nothing about the inputs changed and a
bump would supersede a running solve for no reason. Crossing between the two endings is a 409:
completed is work that happened and survives in reports, dropped is work that will not.

``authorize_tenant`` is called on the one row a caller addresses by identifier. Every row these
methods touch was fetched through a repository scoped to the principal's own tenant, so its
``tenant_id`` IS the principal's, and the scoped ``SELECT`` is what turns another tenant's
identifier into a 404 rather than an edit.

``require_scope`` denies nothing over HTTP today, and that is a property of the credential rather
than of the check: every route reaching these methods resolves a browser session, and a session
carries every scope because the user is acting directly. Reading the backlog needs ``plan:read``
and changing it needs ``plan:write``, which is `12-auth-and-tenancy.md`'s mapping: capture is a
plan change rather than an administrative one, which is why it is not ``admin`` the way a budget
edit is.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from syncr_api.areas.config import AREA_RESOURCE
from syncr_api.areas.rules import unknown_area
from syncr_api.core.errors import NotFound, ValidationFailed
from syncr_api.core.principal import authorize_tenant, require_scope
from syncr_api.core.scopes import Scope
from syncr_api.tasks.config import TASK_RESOURCE
from syncr_api.tasks.records import changes_a_solve_input
from syncr_api.tasks.rules import PROJECT_FIELD, stated_rejection, unknown_project
from syncr_common.logging import get_logger
from syncr_common.metrics import measured
from syncr_domain.projects import require_matching_area
from syncr_domain.tasks import (
    TaskStatus,
    default_min_chunk_minutes,
    require_a_chunk_that_fits,
    require_a_compatible_ending,
)

if TYPE_CHECKING:
    from syncr_api.areas.repository import AreaRepository, ProjectRepository
    from syncr_api.core.clock import Clock
    from syncr_api.core.principal import Principal
    from syncr_api.tasks.declarations import TaskChange, TaskDeclaration
    from syncr_api.tasks.records import TaskRecord
    from syncr_api.tasks.repository import TaskRepository
    from syncr_api.user_settings.solve_inputs import BacklogWideBump
    from syncr_domain.identifiers import AreaId, ProjectId, TaskId
    from syncr_domain.tasks import TaskEnding

_log = get_logger("syncr.tasks")


@dataclass(frozen=True, slots=True)
class Backlog:
    """The tasks one read selected, and the counts the header states over them."""

    tasks: tuple[TaskRecord, ...]
    open_count: int


class TaskService:
    """Read and change one tenant's backlog."""

    def __init__(
        self,
        tasks: TaskRepository,
        areas: AreaRepository,
        projects: ProjectRepository,
        bump: BacklogWideBump,
        clock: Clock,
    ) -> None:
        self._tasks = tasks
        self._areas = areas
        self._projects = projects
        self._bump = bump
        self._clock = clock

    @measured("tasks")
    async def list_all(
        self,
        principal: Principal,
        *,
        area_id: AreaId | None = None,
        status: TaskStatus | None = None,
    ) -> Backlog:
        """The backlog, narrowed by either filter, with the open count over the same Area.

        The open count deliberately ignores the status filter. Filtering the table to completed
        tasks does not change how many are open, and a header that said it did would be reporting
        the page rather than the backlog.
        """
        require_scope(principal, Scope.PLAN_READ)
        return Backlog(
            tasks=await self._tasks.list_all(area_id=area_id, status=status),
            open_count=await self._tasks.count_open(area_id=area_id),
        )

    @measured("tasks")
    async def read(self, principal: Principal, task_id: TaskId) -> TaskRecord:
        """One task of this tenant's, or a 404 that discloses nothing about another's."""
        require_scope(principal, Scope.PLAN_READ)
        return await self._require_task(principal, task_id)

    @measured("tasks")
    async def capture(self, principal: Principal, declaration: TaskDeclaration) -> TaskRecord:
        """Capture a task, open and immediately eligible for the next solve."""
        require_scope(principal, Scope.PLAN_WRITE)
        now = self._clock()
        await self._require_a_declared_area(declaration.area_id)
        minimum = (
            default_min_chunk_minutes(declaration.estimate_minutes)
            if declaration.min_chunk_minutes is None
            else declaration.min_chunk_minutes
        )
        with stated_rejection():
            require_a_chunk_that_fits(
                estimate_minutes=declaration.estimate_minutes, min_chunk_minutes=minimum
            )
            await self._require_a_matching_project(declaration.project_id, declaration.area_id)

        created = await self._tasks.create(
            area_id=declaration.area_id,
            project_id=declaration.project_id,
            title=declaration.title,
            estimate_minutes=declaration.estimate_minutes,
            deadline=declaration.deadline,
            priority=declaration.priority,
            min_chunk_minutes=minimum,
            splittable=declaration.splittable,
            created_at=now,
        )
        # The task's TITLE is deliberately absent from this line. It is the user's own words, and
        # a task called "Second opinion on the biopsy" discloses as much as a block label does.
        _log.info(
            "tasks.task.captured",
            tenant_id=str(principal.tenant_id),
            task_id=str(created.id),
            area_id=str(created.area_id),
            estimate_minutes=created.estimate_minutes,
            splittable=created.splittable,
        )
        await self._bump.from_the_week_holding(now)
        return created

    @measured("tasks")
    async def update(self, principal: Principal, task_id: TaskId, change: TaskChange) -> TaskRecord:
        """Apply a partial update, checking the physics against the merged pair.

        An ended task is still editable. Correcting the estimate on a task completed yesterday is
        a correction to what a report says, not a reopening, and the status is not a member of
        this change. It bumps nothing, because no solve reads an ended task.
        """
        require_scope(principal, Scope.PLAN_WRITE)
        now = self._clock()
        current = await self._require_task(principal, task_id)
        merged = change.applied_to(current)
        with stated_rejection():
            require_a_chunk_that_fits(
                estimate_minutes=merged.estimate_minutes,
                min_chunk_minutes=merged.min_chunk_minutes,
            )
            await self._require_a_matching_project(merged.project_id, merged.area_id)

        await self._tasks.write(
            task_id,
            project_id=merged.project_id,
            title=merged.title,
            estimate_minutes=merged.estimate_minutes,
            deadline=merged.deadline,
            priority=merged.priority,
            min_chunk_minutes=merged.min_chunk_minutes,
            splittable=merged.splittable,
        )
        _log.info(
            "tasks.task.changed",
            tenant_id=str(principal.tenant_id),
            task_id=str(task_id),
            estimate_minutes=merged.estimate_minutes,
            remaining_minutes=merged.remaining_minutes(),
            solve_input_changed=changes_a_solve_input(current, merged),
        )
        if changes_a_solve_input(current, merged):
            await self._bump.from_the_week_holding(now)
        return merged

    @measured("tasks")
    async def complete(self, principal: Principal, task_id: TaskId) -> TaskRecord:
        """Complete a task: out of eligibility immediately, recorded minutes untouched."""
        require_scope(principal, Scope.PLAN_WRITE)
        return await self._end(principal, task_id, ending=TaskStatus.COMPLETED)

    @measured("tasks")
    async def drop(self, principal: Principal, task_id: TaskId) -> TaskRecord:
        """Drop a task: out of eligibility, and out of the backlog, without completing it.

        A permanent act on the task itself, which is a different thing from the ``drop_item``
        tradeoff that excludes a task from one week's eligibility and leaves its status alone.
        """
        require_scope(principal, Scope.PLAN_WRITE)
        return await self._end(principal, task_id, ending=TaskStatus.DROPPED)

    async def _end(
        self, principal: Principal, task_id: TaskId, *, ending: TaskEnding
    ) -> TaskRecord:
        """Move a task out of the backlog, or answer with it unchanged if it already left.

        The second case is what makes a retried request safe without a key: the caller asked for
        the state the task is already in, so nothing is written and nothing is bumped. The
        instant does not move either, which is what keeps a completion's place in a report
        stable.

        Ending a task a solve could not see bumps nothing, for the same reason a change to one
        does not: an open task whose recorded time has already caught up with its estimate is not
        collected by the assembler, so taking it out of a backlog it was not in invalidates
        nothing.
        """
        now = self._clock()
        current = await self._require_task(principal, task_id)
        with stated_rejection():
            require_a_compatible_ending(current=current.status, ending=ending)
        if current.status is ending:
            _log.info(
                "tasks.task.ended_again",
                tenant_id=str(principal.tenant_id),
                task_id=str(task_id),
                status=current.status.value,
            )
            return current

        at = now if ending is TaskStatus.COMPLETED else None
        await self._tasks.end(task_id, ending=ending, at=at)
        ended = replace(current, status=ending, completed_at=at)
        _log.info(
            "tasks.task.ended",
            tenant_id=str(principal.tenant_id),
            task_id=str(task_id),
            status=ending.value,
            recorded_minutes=current.recorded_minutes,
            solve_input_changed=changes_a_solve_input(current, ended),
        )
        if changes_a_solve_input(current, ended):
            await self._bump.from_the_week_holding(now)
        return ended

    async def _require_task(self, principal: Principal, task_id: TaskId) -> TaskRecord:
        found = await self._tasks.find(task_id)
        if found is None:
            raise NotFound(f"No {TASK_RESOURCE} matches that identifier.")
        authorize_tenant(principal, found.tenant_id, resource=TASK_RESOURCE)
        return found

    async def _require_a_declared_area(self, area_id: AreaId) -> None:
        """Refuse a task in an Area this tenant has not declared.

        Answered the same way whether the identifier is unknown or belongs to another tenant, so
        the response discloses nothing about which.
        """
        if await self._areas.find(area_id) is not None:
            return
        raise ValidationFailed(
            f"No {AREA_RESOURCE} matches that identifier, so a {TASK_RESOURCE} cannot be "
            "captured in it. Nothing was changed. Declare the Area first: every hour a task "
            "takes counts toward exactly one Area, so a task without one could not be reported.",
            errors=unknown_area("areaId"),
        )

    async def _require_a_matching_project(
        self, project_id: ProjectId | None, area_id: AreaId
    ) -> None:
        """X2: a task naming a Project sits in that Project's Area.

        The Project has to exist first, and the two checks answer differently on purpose: an
        unknown identifier is a bad reference, and a known one in another Area is a claim that
        would make one hour attributable to two Areas.
        """
        if project_id is None:
            return
        project = await self._projects.find(project_id)
        if project is None:
            raise ValidationFailed(
                f"No project matches that identifier, so this {TASK_RESOURCE} cannot belong to "
                "it. Nothing was changed. Declare the project first, or leave the field out: a "
                "task belongs to an Area whether or not it belongs to a project.",
                errors=unknown_project(PROJECT_FIELD),
            )
        require_matching_area(
            project_id=project_id, project_area_id=project.area_id, task_area_id=area_id
        )
