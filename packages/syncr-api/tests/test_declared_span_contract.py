"""The request contract states the quarter-hour grid for declared spans.

The domain already refuses off-grid declarations. These tests hold the public request schemas and
committed document to the same statement without moving that refusal into request parsing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

from syncr_api.routines.schemas import RoutineCreateRequest, RoutinePatchRequest
from syncr_api.tasks.schemas import TaskCreateRequest, TaskPatchRequest
from syncr_domain.snap import SNAP_MINUTES

if TYPE_CHECKING:
    from pydantic import BaseModel

CONTRACT = Path(__file__).resolve().parents[3] / "frontend" / "openapi.json"

ROUTINE_REQUESTS = (RoutineCreateRequest, RoutinePatchRequest)
TASK_REQUESTS = (TaskCreateRequest, TaskPatchRequest)


def field_schema(model: type[BaseModel], name: str) -> dict[str, Any]:
    schema = model.model_json_schema(by_alias=True)
    return cast("dict[str, Any]", schema["properties"][name])


@pytest.mark.parametrize("model", ROUTINE_REQUESTS, ids=lambda model: model.__name__)
def test_routine_requests_state_the_grid_on_time_and_durations(model: type[BaseModel]) -> None:
    for field in ("targetTime", "durationMinutes", "minDurationMinutes"):
        assert "quarter hour" in field_schema(model, field)["description"]

    for field in ("durationMinutes", "minDurationMinutes"):
        assert field_schema(model, field)["multipleOf"] == SNAP_MINUTES


@pytest.mark.parametrize("model", TASK_REQUESTS, ids=lambda model: model.__name__)
def test_task_requests_state_the_grid_on_the_minimum_chunk(model: type[BaseModel]) -> None:
    minimum = field_schema(model, "minChunkMinutes")

    assert minimum["multipleOf"] == SNAP_MINUTES
    assert "quarter hour" in minimum["description"]


def test_request_metadata_does_not_move_domain_refusals_into_schema_parsing() -> None:
    routine = RoutineCreateRequest.model_validate(
        {"title": "Wake", "targetTime": "05:00", "durationMinutes": 50}
    )
    task = TaskCreateRequest.model_validate(
        {
            "areaId": "00000000-0000-0000-0000-000000000000",
            "title": "Leetcode",
            "estimateMinutes": 90,
            "minChunkMinutes": 25,
        }
    )

    assert routine.duration_minutes == 50
    assert task.min_chunk_minutes == 25


def test_committed_document_publishes_the_same_grid_contract() -> None:
    document = json.loads(CONTRACT.read_text(encoding="utf-8"))
    schemas = document["components"]["schemas"]

    for model_name, fields in {
        "RoutineCreateRequest": ("targetTime", "durationMinutes", "minDurationMinutes"),
        "RoutinePatchRequest": ("targetTime", "durationMinutes", "minDurationMinutes"),
        "TaskCreateRequest": ("minChunkMinutes",),
        "TaskPatchRequest": ("minChunkMinutes",),
    }.items():
        properties = schemas[model_name]["properties"]
        for field in fields:
            assert "quarter hour" in properties[field]["description"]
        for field in set(fields) - {"targetTime"}:
            assert properties[field]["multipleOf"] == SNAP_MINUTES
