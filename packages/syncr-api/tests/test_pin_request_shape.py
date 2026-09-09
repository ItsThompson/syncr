"""Pin request resolution and validation."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syncr_api.core.errors import Conflict, NotFound, ValidationFailed
from syncr_api.pins.request_shape import (
    _block_of,
    _require_a_placement_inside_the_week,
    _require_a_placement_the_week_has_not_reached,
    _starting_at,
)
from syncr_domain.intervals import Interval
from tests.assembly_fakes import a_plan, a_task_block, at

if TYPE_CHECKING:
    from syncr_domain.plan import Block


def _block(*, start: int = 10) -> Block:
    task_id = uuid4()
    area_id = uuid4()
    return a_task_block(
        task_id=task_id,
        area_id=area_id,
        interval=Interval(at(start, day=4), at(start + 1, day=4)),
    )


def test_request_shape_resolves_the_named_block_and_preserves_its_duration() -> None:
    block = _block()
    plan = a_plan(blocks=(block,))
    start = at(12, day=4)

    assert _block_of(plan, block.id) is block
    assert _starting_at(start, block) == Interval(start, start + timedelta(hours=1))


def test_request_shape_refuses_a_block_the_week_has_reached() -> None:
    block = _block(start=8)
    accepted = Interval(at(12, day=4), at(13, day=4))

    with pytest.raises(Conflict, match="began at"):
        _require_a_placement_the_week_has_not_reached(block, accepted, at(9, day=4))


def test_request_shape_refuses_a_start_the_week_has_reached() -> None:
    block = _block()
    accepted = Interval(at(8, day=4), at(9, day=4))

    with pytest.raises(ValidationFailed, match="start has already passed"):
        _require_a_placement_the_week_has_not_reached(block, accepted, at(9, day=4))


def test_request_shape_accepts_a_start_inside_the_assembled_week() -> None:
    span = Interval(at(0), at(0, day=7))
    accepted = Interval(at(12, day=4), at(13, day=4))

    _require_a_placement_inside_the_week(accepted, span)


def test_request_shape_refuses_a_start_outside_the_assembled_week() -> None:
    span = Interval(at(0), at(0, day=7))
    accepted = Interval(at(0, day=7), at(1, day=7))

    with pytest.raises(ValidationFailed, match="puts the block outside the week"):
        _require_a_placement_inside_the_week(accepted, span)


def test_request_shape_refuses_a_missing_block() -> None:
    with pytest.raises(NotFound, match="matches that identifier"):
        _block_of(a_plan(), "no-such-block")
