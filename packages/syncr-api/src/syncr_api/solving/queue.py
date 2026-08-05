"""The due pending operations of one kind, for the worker duty that drains them.

Separate from :class:`~syncr_api.solving.repository.OperationRepository` for the reason
:mod:`syncr_api.solving.sweeps` is: it answers about a SET of operations and it is never wanted on a
request path. A route reports one operation or pages a tenant's history; only a worker asks "what is
waiting to be done".

**This is not the solve coordinator's scan.** That one decides WHICH due operation a worker claims
across every tenant, and it is one component with the debounce and the conditional write it exists
to serve. This is the projection's queue, read per tenant like every other statement over a table
that holds a plan, and it answers with all of them because a projection is idempotent over the whole
horizon: several queued projections for one tenant are satisfied by one reconciliation, so the drain
wants the set rather than the next one.

**Bounded, because a queue is as long as the deployment let it get.** A pending projection per
revision per week is a handful in ordinary use, and it is a rising floor whenever the drain has
been failing or switched off. The bound is what stops one tenant's backlog turning a tick into an
unbounded read; what is left over is drained by the next tick, and the reconciliation that runs is
the whole horizon either way, so nothing is lost by stopping early.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from syncr_api.core.repository import TenantScopedRepository
from syncr_api.solving.config import PENDING, OperationKind
from syncr_api.solving.models import Operation
from syncr_api.solving.repository import as_record

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_api.solving.records import OperationRecord

# How many due operations of one kind one tick reads for one tenant. Above any backlog ordinary use
# produces, and far below the size at which a read stops being cheap.
DRAIN_LIMIT: Final = 200


class OperationQueue(TenantScopedRepository):
    """What is waiting to be done for one tenant, oldest first."""

    async def due(
        self, *, kind: OperationKind, at: datetime, limit: int = DRAIN_LIMIT
    ) -> tuple[OperationRecord, ...]:
        """Every pending operation of ``kind`` scheduled at or before ``at``, oldest first.

        Oldest first, unlike the list route's newest-first page: a queue is drained in the order it
        was filled, and a retry that has been pushed out by a backoff is not due until its own
        instant, which is what ``scheduled_for`` already says.
        """
        rows = await self._session.scalars(
            self.scoped_select(Operation)
            .where(
                Operation.kind == kind,
                Operation.status == PENDING,
                Operation.scheduled_for <= at,
            )
            .order_by(Operation.scheduled_for, Operation.id)
            .limit(limit)
        )
        return tuple(as_record(row) for row in rows)
