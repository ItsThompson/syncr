"""The shared Area and Task builders for service-level test suites stay in one home."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from syncr_domain.tasks import Priority, TaskStatus
from tests.service_builders import a_task, an_area

TESTS: Final = Path(__file__).resolve().parent
HOME: Final = "service_builders.py"
SERVICE_SUITES: Final = (
    "test_budget_service.py",
    "test_tasks_service.py",
    "test_at_risk_tasks.py",
    "test_weekly_session_rules.py",
)


def builder_sites(builder_name: str) -> list[str]:
    paths = (TESTS / HOME, *(TESTS / suite for suite in SERVICE_SUITES))
    sites: list[str] = []
    for path in paths:
        tree = ast.parse(path.read_text())
        if any(
            isinstance(node, ast.FunctionDef) and node.name == builder_name
            for node in ast.walk(tree)
        ):
            sites.append(path.name)
    return sites


def test_shared_builders_make_valid_records_by_default() -> None:
    area = an_area()
    task = a_task()

    assert area.parent_id is None
    assert area.budget_percent is None
    assert task.area_id is not None
    assert task.status is TaskStatus.OPEN
    assert task.is_eligible_for_solving() is True


def test_shared_builders_allow_any_stored_state_to_be_overridden() -> None:
    recorded_at = datetime(2026, 2, 9, tzinfo=UTC)
    area = an_area(name="Career", pigment_index=4)
    task = a_task(
        area_id=area.id,
        status=TaskStatus.COMPLETED,
        recorded_minutes=60,
        completed_at=recorded_at,
        priority=Priority.HIGH,
        created_at=recorded_at,
    )

    assert area.name == "Career"
    assert area.pigment_index == 4
    assert task.status is TaskStatus.COMPLETED
    assert task.recorded_minutes == 60
    assert task.completed_at == recorded_at
    assert task.priority is Priority.HIGH
    assert task.created_at == recorded_at


def test_service_suites_declare_each_shared_builder_only_in_its_home() -> None:
    assert builder_sites("an_area") == [HOME]
    assert builder_sites("a_task") == [HOME]
