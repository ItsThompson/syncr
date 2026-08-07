"""The five backlog routes.

Thin, on purpose. Each handler validates a body, resolves who is asking, calls exactly one
service method, and maps the result onto a response shape. No authorization decision and no
persistence: ``tests/test_authorization_boundary.py`` asserts this file cannot reach either.

Each response is built field by field rather than validated from the record, so a column added to
the table cannot reach the wire by sharing a name with a schema field. The two derived figures,
remaining work and eligibility, are asked of the record rather than computed here. **The third,
whether the task is at risk, is asked of neither**: it is the week verdict's determination, so it
arrives as a set of identifiers the list read resolved once and appears on the list's shape alone.

**``DELETE`` answers with the task rather than with a 204.** Dropping a task is a state
transition rather than a removal: the row survives, so the response says what it now is, and a
retry can be replayed from a stored body the way every other unsafe method's can.

Every unsafe method takes the idempotency guard. A repeat of any of them is recoverable on its
own, so none demands the header: capture is the one that would create a second row, and the
other three converge, so the guard is offered rather than required.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Query

from syncr_api.accounts.injection import ClientPrincipalDep, PrincipalDep
from syncr_api.core.patches import stated, stated_unless_null
from syncr_api.idempotency.injection import IdempotencyGuardDep
from syncr_api.tasks.config import TASK_COMPLETE_PATH, TASK_PATH
from syncr_api.tasks.declarations import TaskChange, TaskDeclaration
from syncr_api.tasks.injection import TaskServiceDep
from syncr_api.tasks.schemas import (
    BacklogHeader,
    BacklogTaskResponse,
    TaskCreateRequest,
    TaskPatchRequest,
    TaskResponse,
    TasksResponse,
)
from syncr_domain.tasks import TaskStatus

if TYPE_CHECKING:
    from syncr_api.tasks.records import TaskRecord
    from syncr_domain.identifiers import TaskId

router = APIRouter()

CAPTURE_ROUTE = "tasks.capture"
UPDATE_ROUTE = "tasks.update"
COMPLETE_ROUTE = "tasks.complete"
DROP_ROUTE = "tasks.drop"


def _as_task(record: TaskRecord) -> TaskResponse:
    return TaskResponse(
        id=record.id,
        area_id=record.area_id,
        project_id=record.project_id,
        title=record.title,
        estimate_minutes=record.estimate_minutes,
        recorded_minutes=record.recorded_minutes,
        remaining_minutes=record.remaining_minutes(),
        deadline=record.deadline,
        priority=record.priority,
        min_chunk_minutes=record.min_chunk_minutes,
        splittable=record.splittable,
        status=record.status,
        completed_at=record.completed_at,
        eligible_for_solving=record.is_eligible_for_solving(),
    )


def _as_backlog_row(record: TaskRecord, at_risk: frozenset[TaskId]) -> BacklogTaskResponse:
    """One task as the backlog lists it: the row above, plus the week verdict's own determination.

    Composed from the response rather than from the record a second time, which is what keeps the
    field-by-field rule above intact: the mapping is stated once and a column added to the table
    still cannot reach the wire, because what is re-read here is a validated response and not a row.
    """
    return BacklogTaskResponse(**_as_task(record).model_dump(), at_risk=record.id in at_risk)


@router.get("", summary="The backlog, with the counts its header states")
async def list_tasks(
    principal: ClientPrincipalDep,
    service: TaskServiceDep,
    area_id: UUID | None = Query(default=None, alias="areaId"),
    status: TaskStatus | None = Query(default=None),
) -> TasksResponse:
    """The tasks either filter selects, oldest first, and the two figures the header states."""
    backlog = await service.list_all(principal, area_id=area_id, status=status)
    return TasksResponse(
        header=BacklogHeader(open_count=backlog.open_count, at_risk_count=len(backlog.at_risk)),
        tasks=[_as_backlog_row(task, backlog.at_risk) for task in backlog.tasks],
    )


@router.post("", status_code=HTTPStatus.CREATED, summary="Capture a task. A title and an Area")
async def capture_task(
    body: TaskCreateRequest,
    principal: ClientPrincipalDep,
    guard: IdempotencyGuardDep,
    service: TaskServiceDep,
) -> TaskResponse:
    """Capture a task. Everything but the title and the Area has a documented default."""
    declaration = TaskDeclaration(
        area_id=body.area_id,
        title=body.title,
        project_id=body.project_id,
        estimate_minutes=body.estimate_minutes,
        deadline=body.deadline,
        priority=body.priority,
        min_chunk_minutes=body.min_chunk_minutes,
        splittable=body.splittable,
    )

    async def capture() -> TaskResponse:
        return _as_task(await service.capture(principal, declaration))

    return await guard.once(CAPTURE_ROUTE, TaskResponse, capture)


@router.get(TASK_PATH, summary="One task, with its remaining work")
async def read_task(
    task_id: UUID, principal: PrincipalDep, service: TaskServiceDep
) -> TaskResponse:
    """One task of this tenant's."""
    return _as_task(await service.read(principal, task_id))


@router.patch(TASK_PATH, summary="Change a title, a deadline, or the physics")
async def update_task(
    task_id: UUID,
    body: TaskPatchRequest,
    principal: PrincipalDep,
    guard: IdempotencyGuardDep,
    service: TaskServiceDep,
) -> TaskResponse:
    """Apply a partial update. An omitted field is left alone; an explicit null clears one."""
    change = TaskChange(
        title=stated_unless_null(body.title),
        project_id=stated(body, "project_id", body.project_id),
        estimate_minutes=stated_unless_null(body.estimate_minutes),
        deadline=stated(body, "deadline", body.deadline),
        priority=stated_unless_null(body.priority),
        min_chunk_minutes=stated_unless_null(body.min_chunk_minutes),
        splittable=stated_unless_null(body.splittable),
    )

    async def update() -> TaskResponse:
        return _as_task(await service.update(principal, task_id, change))

    return await guard.once(UPDATE_ROUTE, TaskResponse, update)


@router.delete(TASK_PATH, summary="Drop a task. The row survives, out of eligibility")
async def drop_task(
    task_id: UUID,
    principal: PrincipalDep,
    guard: IdempotencyGuardDep,
    service: TaskServiceDep,
) -> TaskResponse:
    """Drop a task, answering with what it now is rather than with an empty 204."""

    async def drop() -> TaskResponse:
        return _as_task(await service.drop(principal, task_id))

    return await guard.once(DROP_ROUTE, TaskResponse, drop)


@router.post(TASK_COMPLETE_PATH, summary="Complete a task. Recorded time is left intact")
async def complete_task(
    task_id: UUID,
    principal: ClientPrincipalDep,
    guard: IdempotencyGuardDep,
    service: TaskServiceDep,
) -> TaskResponse:
    """Complete a task. It leaves solver eligibility immediately and keeps its recorded time."""

    async def complete() -> TaskResponse:
        return _as_task(await service.complete(principal, task_id))

    return await guard.once(COMPLETE_ROUTE, TaskResponse, complete)
