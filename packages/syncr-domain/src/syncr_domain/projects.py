"""The Project vocabulary, and the rule that keeps time attribution unambiguous.

A Project ends; an Area does not. A Project has no budget fields, because it inherits its
parent Area's allocation, and that is what makes a time-boxed push expressible without
carving a new wedge out of the pie. Completing one leaves its historical time attribution
intact: the outcomes already recorded name the Area, so nothing has to be rewritten.

A Project belongs to exactly one Area and never spans two. So when a Task names a Project,
the Task's Area is not free: it has to be the Project's, or the same hour would be
attributable to two Areas and the pie would not add up.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from syncr_domain.errors import DomainError

if TYPE_CHECKING:
    from syncr_domain.identifiers import AreaId, ProjectId


class ProjectStatus(StrEnum):
    """Where a Project is in its life. An Area has no equivalent, because it never ends."""

    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class ProjectAreaMismatch(DomainError):
    """A Task names a Project in one Area and claims another."""


def require_matching_area(
    *, project_id: ProjectId, project_area_id: AreaId, task_area_id: AreaId
) -> None:
    """Reject a Task whose Area is not the Area its Project sits in.

    Stated here rather than restated as a request-schema rule, because it is a comparison
    between two stored rows: the schema cannot see the Project's Area, so a rule written
    there would be a second, weaker statement of this one.
    """
    if project_area_id == task_area_id:
        return
    raise ProjectAreaMismatch(
        f"project {project_id} sits in Area {project_area_id}, so a task in Area "
        f"{task_area_id} cannot belong to it. Time spent on a project counts toward one "
        "Area, and a task claiming a second would make the same hour attributable twice."
    )
