"""The entity-backed facts a pin reads before it changes the assembled week."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_domain.budgets import floor_minutes
from syncr_domain.identity import BindingKind

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_api.areas.repository import AreaRepository
    from syncr_api.plans.pins import PinRepository
    from syncr_api.tasks.repository import TaskRepository
    from syncr_domain.plan import Block
    from syncr_domain.weeks import IsoWeek


@dataclass(frozen=True, slots=True)
class PreEditFacts:
    """The entity-backed values recorded with one pin's pre-edit frame."""

    task_deadline: datetime | None
    area_floor_declared: int | None
    pinned_blocks_before: int


async def resolve_pre_edit(
    block: Block,
    week: IsoWeek,
    *,
    tasks: TaskRepository,
    areas: AreaRepository,
    pins: PinRepository,
) -> PreEditFacts:
    """Resolve the facts the transaction reads before it adds this pin."""
    return PreEditFacts(
        task_deadline=await _task_deadline(block, tasks=tasks),
        area_floor_declared=await _declared_floor(block, areas=areas),
        pinned_blocks_before=len(await pins.for_week(week)),
    )


async def _task_deadline(block: Block, *, tasks: TaskRepository) -> datetime | None:
    """The deadline on the task this block holds, read from the entity itself.

    Not from ``eligible_tasks`` or ``deadline_demands``, because both net placements and the
    pin makes its block immovable: a fully-placed task would vanish from either list, falsifying
    the feature by the act of recording it. The task record is what the pin does not perturb.

    Returns ``None`` for content that is not a task, which is what ``edit_context`` writes as
    ``was_deadline_constrained=False``.
    """
    if block.binding.kind != BindingKind.TASK:
        return None
    found = await tasks.find(block.binding.entity_id)
    return None if found is None else found.deadline


async def _declared_floor(block: Block, *, areas: AreaRepository) -> int | None:
    """The Area's declared floor in minutes, read from the entity itself.

    Not from ``AreaBudget.floor_minutes``, because that field is the SOLVER's quantity: it nets
    immovable placements, and a pin makes its block immovable, so the recorded figure would be
    short by exactly the dragged block's duration. The Area's own declaration is what the pin
    does not perturb.

    Returns ``None`` for content carrying no Area (frame, commitment).
    """
    if block.area_id is None:
        return None
    found = await areas.find(block.area_id)
    if found is None:
        return None
    return floor_minutes(found.floor_hours)
