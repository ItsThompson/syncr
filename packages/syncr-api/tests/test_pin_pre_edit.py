"""Entity-backed facts captured before a pin changes the assembled week."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, cast

from syncr_api.pins.pre_edit import resolve_pre_edit
from syncr_domain.intervals import Interval
from tests.assembly_fakes import WEEK, a_task, a_task_block, an_area, at

if TYPE_CHECKING:
    from syncr_api.areas.records import AreaRecord
    from syncr_api.areas.repository import AreaRepository
    from syncr_api.plans.pins import PinRepository
    from syncr_api.plans.records import PinRecord
    from syncr_api.tasks.records import TaskRecord
    from syncr_api.tasks.repository import TaskRepository
    from syncr_domain.identifiers import AreaId, TaskId


class StoredTasks:
    def __init__(self, task: TaskRecord) -> None:
        self._task = task

    async def find(self, task_id: TaskId) -> TaskRecord | None:
        return self._task if task_id == self._task.id else None


class StoredAreas:
    def __init__(self, area: AreaRecord) -> None:
        self._area = area

    async def find(self, area_id: AreaId) -> AreaRecord | None:
        return self._area if area_id == self._area.id else None


class NoPins:
    async def for_week(self, iso_week: object) -> tuple[PinRecord, ...]:
        return ()


async def test_pre_edit_facts_read_the_entities_before_the_pin_is_held() -> None:
    deadline = at(15, day=4)
    area = an_area(floor_hours=Decimal("2.5"))
    task = a_task(area_id=area.id, deadline=deadline)
    block = a_task_block(
        task_id=task.id,
        area_id=area.id,
        interval=Interval(at(10, day=4), at(11, day=4)),
    )

    facts = await resolve_pre_edit(
        block,
        WEEK,
        tasks=cast("TaskRepository", StoredTasks(task)),
        areas=cast("AreaRepository", StoredAreas(area)),
        pins=cast("PinRepository", NoPins()),
    )

    assert facts.task_deadline == deadline
    assert facts.area_floor_declared == 150
    assert facts.pinned_blocks_before == 0
