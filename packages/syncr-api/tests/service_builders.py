"""Builders for stored Area and Task records used by service-level test suites."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from syncr_api.areas.records import AreaRecord
from syncr_api.tasks.records import TaskRecord
from syncr_domain.tasks import NO_RECORDED_MINUTES, Priority, TaskStatus

if TYPE_CHECKING:
    from syncr_domain.identifiers import AreaId, TaskId, TenantId

DEFAULT_CREATED_AT = datetime(2026, 2, 9, tzinfo=UTC)


def an_area(
    tenant_id: TenantId | None = None,
    name: str = "Fitness",
    *,
    area_id: AreaId | None = None,
    **overrides: object,
) -> AreaRecord:
    fields: dict[str, object] = {
        "id": area_id or uuid4(),
        "tenant_id": tenant_id or uuid4(),
        "parent_id": None,
        "name": name,
        "pigment_index": 0,
        "budget_percent": None,
        "floor_hours": None,
        "created_at": DEFAULT_CREATED_AT,
    }
    return AreaRecord(**{**fields, **overrides})  # type: ignore[arg-type]


def a_task(
    tenant_id: TenantId | None = None,
    area_id: AreaId | None = None,
    *,
    task_id: TaskId | None = None,
    **overrides: object,
) -> TaskRecord:
    fields: dict[str, object] = {
        "id": task_id or uuid4(),
        "tenant_id": tenant_id or uuid4(),
        "area_id": area_id or uuid4(),
        "project_id": None,
        "title": "Leetcode",
        "estimate_minutes": 60,
        "deadline": None,
        "priority": Priority.NORMAL,
        "min_chunk_minutes": 15,
        "splittable": True,
        "status": TaskStatus.OPEN,
        "recorded_minutes": NO_RECORDED_MINUTES,
        "completed_at": None,
        "created_at": DEFAULT_CREATED_AT,
    }
    return TaskRecord(**{**fields, **overrides})  # type: ignore[arg-type]
