"""The Project rule that keeps an hour attributable to exactly one Area."""

from __future__ import annotations

from uuid import UUID

import pytest

from syncr_domain.projects import ProjectAreaMismatch, ProjectStatus, require_matching_area

PROJECT = UUID("00000000-0000-4000-8000-0000000000a1")
CAREER = UUID("00000000-0000-4000-8000-000000000002")
LEARNING = UUID("00000000-0000-4000-8000-000000000003")


def test_a_project_has_three_states_and_none_of_them_is_a_budget() -> None:
    assert [status.value for status in ProjectStatus] == ["active", "completed", "abandoned"]


def test_a_task_in_its_projects_area_is_accepted() -> None:
    # Nothing is raised, which is the whole contract: the rule refuses or it is silent.
    require_matching_area(project_id=PROJECT, project_area_id=CAREER, task_area_id=CAREER)


def test_a_task_claiming_another_area_than_its_project_is_refused() -> None:
    with pytest.raises(ProjectAreaMismatch) as refused:
        require_matching_area(project_id=PROJECT, project_area_id=CAREER, task_area_id=LEARNING)

    # The message names both Areas and the project, so the caller can state which one has to
    # move rather than reporting that something did not match.
    stated = str(refused.value)
    assert str(CAREER) in stated
    assert str(LEARNING) in stated
    assert str(PROJECT) in stated
