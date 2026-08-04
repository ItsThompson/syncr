"""What a request asked to capture or change, as the service takes it.

These sit between the route that read the request and the service that applies it, so the
service never imports a wire schema and the route never decides anything.

Every field of a change is three-valued: absent leaves the stored value alone, a value replaces
it, and null clears it where the column is nullable. That is `13-http-api.md`'s explicit-null
convention, and it is why a deadline can be removed at all.

Two things are absent from :class:`TaskChange` and each absence is a rule.

**No ``status``.** A task leaves the backlog through ``POST .../complete`` or ``DELETE``, each
of which records what it owes: a completion carries its instant. A status on a patch would be a
second way to complete a task, and it would bypass the instant.

**No ``recorded_minutes``.** It accumulates from confirmed outcomes, so a client that could set
it could make the backlog contradict the outcome log.

**No ``area_id``.** A task's Area is declared once, because the hours already recorded against
it were attributed to that Area and moving the task would rewrite reported history. A task whose
Area was wrong is dropped and re-captured, which leaves the record of what was actually spent
where it was spent.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from syncr_api.core.patches import resolved

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_api.core.patches import Patched
    from syncr_api.tasks.records import TaskRecord
    from syncr_domain.identifiers import AreaId, ProjectId
    from syncr_domain.tasks import Priority


@dataclass(frozen=True, slots=True)
class TaskDeclaration:
    """One task to capture.

    Every field but the first two carries a default resolved before this is built, so capture
    from any screen can submit a title and an Area and nothing else.

    ``min_chunk_minutes`` is the one exception and it is ``None`` when the request did not state
    one. Its default is DERIVED from the estimate rather than constant, one grid step clamped
    down to a smaller estimate, and the derivation exists to keep T1 true, so it is resolved
    where T1 is checked rather than filled in by the route that read the request.
    """

    area_id: AreaId
    title: str
    project_id: ProjectId | None
    estimate_minutes: int
    deadline: datetime | None
    priority: Priority
    min_chunk_minutes: int | None
    splittable: bool


@dataclass(frozen=True, slots=True)
class TaskChange:
    """What one ``PATCH`` asked to change on a task."""

    title: Patched[str]
    project_id: Patched[ProjectId | None]
    estimate_minutes: Patched[int]
    deadline: Patched[datetime | None]
    priority: Patched[Priority]
    min_chunk_minutes: Patched[int]
    splittable: Patched[bool]

    def applied_to(self, current: TaskRecord) -> TaskRecord:
        """``current`` with every field this change stated replaced.

        The status, the recorded minutes, the completion instant, and the Area are carried
        through untouched: none of them is a member of this shape, so a patch cannot reach one.
        """
        return replace(
            current,
            title=resolved(self.title, current.title),
            project_id=resolved(self.project_id, current.project_id),
            estimate_minutes=resolved(self.estimate_minutes, current.estimate_minutes),
            deadline=resolved(self.deadline, current.deadline),
            priority=resolved(self.priority, current.priority),
            min_chunk_minutes=resolved(self.min_chunk_minutes, current.min_chunk_minutes),
            splittable=resolved(self.splittable, current.splittable),
        )
