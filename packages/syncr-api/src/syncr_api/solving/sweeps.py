"""The two set-wide statements maintenance runs over ``operations``.

Separate from :class:`~syncr_api.solving.repository.OperationRepository`, which answers about one
operation, because these two answer about a SET of them and neither is ever wanted on a request
path: one finds the claims a dead worker abandoned, and one removes the terminal rows past their
window. Keeping them apart is what stops a route reaching a statement that deletes.

Both are scoped like every other statement over a table that holds a plan, with no exception for
maintenance, so the duty that calls them enumerates tenants and builds one of these per tenant.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.core.repository import TenantScopedRepository
from syncr_api.solving.config import RUNNING, OperationStatus
from syncr_api.solving.models import Operation
from syncr_api.solving.repository import as_record

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_api.solving.records import OperationRecord


class OperationSweeps(TenantScopedRepository):
    """The abandoned claims and the aged terminal rows of one tenant."""

    async def running_since_before(self, cutoff: datetime) -> list[OperationRecord]:
        """Every operation still ``running`` whose claim was taken before ``cutoff``.

        Unbounded by a limit, and small by construction rather than by that index: a row is
        ``running`` only while a worker holds it, so the set is bounded by how many operations the
        deployment's workers can hold at once plus whatever the last crash left behind. For SOLVE
        operations the partial unique index bounds it further, at one per week per tenant; the other
        three kinds have no single-flight bound, so the general argument is the concurrency one.
        """
        rows = await self._session.scalars(
            self.scoped_select(Operation).where(
                Operation.status == RUNNING, Operation.started_at < cutoff
            )
        )
        return [as_record(row) for row in rows]

    async def delete_finished_before(
        self, cutoff: datetime, *, statuses: tuple[OperationStatus, ...]
    ) -> int:
        """Remove this tenant's operations of these statuses finished before ``cutoff``.

        The statuses are named by the caller rather than derived from ``finished_at`` alone,
        because a ``failed`` row with an attempt left is finished for NOW and scheduled again: a
        window keyed on the instant alone would delete it out from under its own retry. A retried
        row is ``pending``, so naming the status set is what excludes it.

        Answers how many rows went, because a sweep reports what it did: a count that changes is
        how progress is reported in this product.
        """
        return await self._affected_rows(
            self.scoped_delete(Operation).where(
                Operation.status.in_(statuses), Operation.finished_at < cutoff
            )
        )
