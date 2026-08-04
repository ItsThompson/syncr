"""The immutable view of a task row.

A repository hands one of these back rather than a mapped instance, so a service cannot trigger
a load it did not ask for, a fake repository in a service test is a function returning a frozen
dataclass, and nothing downstream can change a row by assigning to it.

This is not the wire shape: ``schemas.py`` owns that, so a column added to the table does not
appear in a response by sharing a name with a field.

The two derived figures are METHODS on the record rather than columns, and both delegate to
``syncr_domain.tasks``. Remaining work is a difference and eligibility is a predicate over it,
so storing either would be storing a value that can disagree with the row it was derived from.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_domain.tasks import is_eligible_for_solving, remaining_minutes

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_domain.identifiers import AreaId, ProjectId, TaskId, TenantId
    from syncr_domain.tasks import Priority, TaskStatus


@dataclass(frozen=True, slots=True)
class TaskRecord:
    """One task, as persistence knows it."""

    id: TaskId
    tenant_id: TenantId
    area_id: AreaId
    project_id: ProjectId | None
    title: str
    estimate_minutes: int
    deadline: datetime | None
    priority: Priority
    min_chunk_minutes: int
    splittable: bool
    status: TaskStatus
    recorded_minutes: int
    completed_at: datetime | None
    created_at: datetime

    def remaining_minutes(self) -> int:
        """T3: the work left, never negative.

        The backlog's figure, which nets recorded time and nothing else. The week assembler
        computes a narrower one for the solver by netting immovable placements out of this, and
        the probe a third by netting every placement before a deadline.
        """
        return remaining_minutes(
            estimate_minutes=self.estimate_minutes, recorded_minutes=self.recorded_minutes
        )

    def is_eligible_for_solving(self) -> bool:
        """Whether the solver may place this task, asked of the backlog's own remaining figure.

        The same predicate the week assembler applies, so a captured task cannot be eligible
        here and invisible there.
        """
        return is_eligible_for_solving(
            status=self.status, remaining_minutes=self.remaining_minutes()
        )
