"""Persistence for tasks. Tenant-scoped, and every statement built from the scoped base.

Two reads answer the backlog list, not one, and the split is deliberate. :meth:`list_all` honors
both filters, and :meth:`count_open` honors the Area filter but never the status filter: a header
that reported zero open tasks because the user filtered the table to completed ones would not be
a count of open tasks.

No method writes ``recorded_minutes``. It accumulates from confirmed outcomes, so it is set once
at capture, to zero, and read thereafter. A ``write`` that could change it would let the backlog
contradict the outcome log.

No method commits. One request is one transaction, opened and committed by
:func:`syncr_api.core.db.get_transaction`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import func

from syncr_api.core.repository import TenantScopedRepository
from syncr_api.tasks.models import TaskRow
from syncr_api.tasks.records import TaskRecord
from syncr_domain.tasks import NO_RECORDED_MINUTES, TaskStatus

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy import Select

    from syncr_domain.identifiers import AreaId, ProjectId, TaskId
    from syncr_domain.tasks import Priority, TaskEnding


class TaskRepository(TenantScopedRepository):
    """Lists, counts, reads, captures, and changes this tenant's tasks."""

    async def list_all(
        self, *, area_id: AreaId | None = None, status: TaskStatus | None = None
    ) -> tuple[TaskRecord, ...]:
        """This tenant's tasks, narrowed by either filter, oldest first.

        Oldest first rather than by urgency. The order a backlog is READ in is the screen's
        decision and it needs a deadline, a priority, and the verdict's shortfalls to make it;
        what persistence owes is an order that does not change between two identical reads.
        """
        statement = self._filtered(area_id=area_id, status=status).order_by(
            TaskRow.created_at, TaskRow.id
        )
        found = await self._session.scalars(statement)
        return tuple(_as_record(row) for row in found)

    async def count_open(self, *, area_id: AreaId | None = None) -> int:
        """How many of this tenant's tasks are open, inside one Area or across all of them.

        Counted in the database rather than from the listed rows, because the list may be
        filtered to a status that excludes every open task and the header still has to say how
        many there are.
        """
        counted = await self._session.scalar(
            self._filtered(area_id=area_id, status=TaskStatus.OPEN).with_only_columns(
                func.count(TaskRow.id)
            )
        )
        return counted or 0

    async def find(self, task_id: TaskId) -> TaskRecord | None:
        """One task of this tenant's, or ``None``.

        Scoped, so another tenant's identifier reads as absent rather than as forbidden, which
        is what makes the 404 the service raises truthful.
        """
        found = await self._session.scalar(self.scoped_select(TaskRow).where(TaskRow.id == task_id))
        return _as_record(found) if found is not None else None

    async def create(
        self,
        *,
        area_id: AreaId,
        project_id: ProjectId | None,
        title: str,
        estimate_minutes: int,
        deadline: datetime | None,
        priority: Priority,
        min_chunk_minutes: int,
        splittable: bool,
        created_at: datetime,
    ) -> TaskRecord:
        """Persist one task, open and with nothing recorded against it yet.

        The status and the recorded minutes are not parameters. A captured task is open by
        definition, and recorded time comes from confirmed outcomes, so a caller that could
        supply either could capture a task that was already done.
        """
        row = TaskRow(
            id=uuid4(),
            tenant_id=self.tenant_id,
            area_id=area_id,
            project_id=project_id,
            title=title,
            estimate_minutes=estimate_minutes,
            deadline=deadline,
            priority=priority,
            min_chunk_minutes=min_chunk_minutes,
            splittable=splittable,
            status=TaskStatus.OPEN,
            recorded_minutes=NO_RECORDED_MINUTES,
            completed_at=None,
            created_at=created_at,
        )
        self._session.add(row)
        # Flushed here so a constraint violation surfaces as this call's failure rather than at
        # commit, after the caller has reported success.
        await self._session.flush()
        return _as_record(row)

    async def write(
        self,
        task_id: TaskId,
        *,
        project_id: ProjectId | None,
        title: str,
        estimate_minutes: int,
        deadline: datetime | None,
        priority: Priority,
        min_chunk_minutes: int,
        splittable: bool,
    ) -> None:
        """Replace every editable value on one task. The caller has merged its partial update.

        Whole-record rather than field-by-field, matching the Areas and settings writes: a
        partial update is validated as a set, so the caller holds the merged values anyway.

        ``area_id``, ``status``, ``recorded_minutes``, and ``completed_at`` are absent. The Area
        is declared once, because the hours already recorded against the task were attributed to
        it; the other three are what :meth:`end` and the outcome log own.
        """
        await self._session.execute(
            self.scoped_update(TaskRow)
            .where(TaskRow.id == task_id)
            .values(
                project_id=project_id,
                title=title,
                estimate_minutes=estimate_minutes,
                deadline=deadline,
                priority=priority,
                min_chunk_minutes=min_chunk_minutes,
                splittable=splittable,
            )
        )

    async def end(self, task_id: TaskId, *, ending: TaskEnding, at: datetime | None) -> None:
        """Move one task out of the backlog, recording the instant a completion carries.

        ``at`` is the completion instant and is ``None`` for a drop, which is what the table's
        constraint requires in both directions: a completed row carries an instant and nothing
        else does. Nothing else on the row is touched, so ``recorded_minutes`` and the estimate
        survive for reports.
        """
        await self._session.execute(
            self.scoped_update(TaskRow)
            .where(TaskRow.id == task_id)
            .values(status=ending, completed_at=at)
        )

    def _filtered(
        self, *, area_id: AreaId | None, status: TaskStatus | None
    ) -> Select[tuple[TaskRow]]:
        statement = self.scoped_select(TaskRow)
        if area_id is not None:
            statement = statement.where(TaskRow.area_id == area_id)
        if status is not None:
            statement = statement.where(TaskRow.status == status)
        return statement


def _as_record(row: TaskRow) -> TaskRecord:
    return TaskRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        area_id=row.area_id,
        project_id=row.project_id,
        title=row.title,
        estimate_minutes=row.estimate_minutes,
        deadline=row.deadline,
        priority=row.priority,
        min_chunk_minutes=row.min_chunk_minutes,
        splittable=row.splittable,
        status=row.status,
        recorded_minutes=row.recorded_minutes,
        completed_at=row.completed_at,
        created_at=row.created_at,
    )
