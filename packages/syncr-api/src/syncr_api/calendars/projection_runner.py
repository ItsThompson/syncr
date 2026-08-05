"""The worker duty that drains the projection queue: one reconciliation per tenant that needs one.

The projection runs here and never on a request. It is network-bound, retryable, and destructive, so
it must not sit on a request; and the adapter a request composes holds the refusing arm of the write
seam, so it structurally cannot.

```
tick
  ├── for each tenant:
  │     TRANSACTION  claim every due projection                      committed before any write
  │     TRANSACTION  one TenantPass: read, reconcile, record the attempt, close every claim
  └── nothing due → return, having read one row per tenant
```

**Several queued projections are satisfied by ONE reconciliation.** A projection is idempotent over
the whole horizon: it makes the target match the live plan, whatever it held before. So a weekly
session that appended twelve revisions costs one destructive write rather than twelve, which is the
other half of the rule that a projection is enqueued only when the live plan changed. Each claimed
operation is finished with the outcome of that one write, which is the honest answer: what each of
them asked for is what it did.

**One failure boundary per tenant.** A tenant whose drain raised is counted and the tenants after it
still run. Counted rather than only logged, because a contained fault answers with a tally: without
the counter, a tenant failing every tick would leave every metric at zero while the duty reported
healthy, which is the alert inversion this epic has already shipped twice.

What one pass does with what it claimed, and what it records either way, is
:mod:`syncr_api.calendars.projection_pass`. The split is by question: this module decides which
tenants have work and contains one tenant's fault, and that one performs the write.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from prometheus_client import Counter

from syncr_api.accounts.repository import TenantRepository
from syncr_api.calendars.google_transport import create_google_read_client
from syncr_api.calendars.google_writes import create_google_write_client
from syncr_api.calendars.projection_metrics import PROJECTION_WRITES_ENABLED
from syncr_api.calendars.projection_pass import TenantPass
from syncr_api.solving.config import PROJECTION
from syncr_api.solving.errors import IllegalTransition
from syncr_api.solving.lifecycle import OperationLifecycle
from syncr_api.solving.queue import OperationQueue
from syncr_api.solving.repository import OperationRepository
from syncr_common.logging import get_logger
from syncr_common.metrics import REGISTRY, measured

if TYPE_CHECKING:
    from datetime import datetime

    import httpx

    from syncr_api.core.clock import Clock
    from syncr_api.solving.records import OperationRecord
    from syncr_api.worker.main import WorkerContext
    from syncr_domain.identifiers import TenantId

_log = get_logger("syncr.calendars")

# A tenant whose drain raised outside the reconciliation's own stated failures. Counted rather than
# only logged, because the boundary exists to stop the exception, and a fault that answers with a
# tally is invisible unless something counts it. `18-observability.md` defines no alert on this
# family, and it is the ONLY signal for a fault this path can still produce, so ticket 1302 names it
# as a family needing a rule rather than leaving it to the convention its three siblings follow.
TENANT_PROJECTION_FAILURES = Counter(
    "syncr_projection_tenant_failures_total",
    "Projection drains that raised for one tenant and were contained.",
    registry=REGISTRY,
)


class ProjectionRunner:
    """One duty on the worker loop: project every tenant whose queue holds a projection.

    A callable object rather than a closure, so the loop's name lookup finds a stable name for its
    failure metric and so a test can drive one pass directly.

    Unlike the calendar poll and the horizon maintainer this has no interval of its own and no
    first tick that only schedules: the queue IS the schedule. A tick with an empty queue costs one
    indexed read per tenant, and a projection enqueued by a solve has to reach the phone in seconds
    rather than at the next quarter hour.
    """

    __name__ = "projection"

    def __init__(self, *, clock: Clock) -> None:
        self._clock = clock

    async def __call__(self, context: WorkerContext) -> None:
        # One client per direction for the whole tick, so several tenants share one connection pool
        # each way. The two are separate because a read and a write answer to different timeouts.
        async with create_google_read_client() as reads, create_google_write_client() as writes:
            await self.drain(context, reads, writes, now=self._clock())

    async def drain(
        self,
        context: WorkerContext,
        reads: httpx.AsyncClient,
        writes: httpx.AsyncClient,
        *,
        now: datetime,
    ) -> int:
        """One pass over every tenant. Answers how many reconciliations were performed.

        The clients are arguments rather than created here, exactly as the calendar poll's are: the
        tick owns their lifetime, and a test drives the whole composition -- the token refresh, the
        adapter, the diff -- against a transport it controls.

        The arming gauge is set here, before any tenant is read, so it is present in the exposition
        after the first tick whether or not anything was due. An alert that inhibits on it needs it
        to be there.
        """
        PROJECTION_WRITES_ENABLED.set(context.settings.google_projection_writes)
        async with context.database.sessionmaker() as reader:
            tenants = await TenantRepository(reader).list_ids()

        performed = 0
        for tenant_id in tenants:
            performed += await self._drained(context, tenant_id, reads, writes, now=now)
        return performed

    async def _drained(
        self,
        context: WorkerContext,
        tenant_id: TenantId,
        reads: httpx.AsyncClient,
        writes: httpx.AsyncClient,
        *,
        now: datetime,
    ) -> int:
        """One tenant's queue, with its fault contained so the tenants after it still run."""
        try:
            return await self._projected(context, tenant_id, reads, writes, now=now)
        except Exception:  # noqa: BLE001 - one tenant's fault must not stop the others
            TENANT_PROJECTION_FAILURES.inc()
            _log.exception("calendars.projection.tenant_failed", tenant_id=str(tenant_id))
            return 0

    @measured("projection")
    async def _projected(
        self,
        context: WorkerContext,
        tenant_id: TenantId,
        reads: httpx.AsyncClient,
        writes: httpx.AsyncClient,
        *,
        now: datetime,
    ) -> int:
        claimed = await self._claimed(context, tenant_id, now=now)
        if not claimed:
            return 0
        async with context.database.sessionmaker() as session, session.begin():
            return await TenantPass(
                context=context,
                session=session,
                tenant_id=tenant_id,
                claimed=claimed,
                now=now,
                clock=self._clock,
            ).run(reads, writes)

    async def _claimed(
        self, context: WorkerContext, tenant_id: TenantId, *, now: datetime
    ) -> tuple[OperationRecord, ...]:
        """Claim every due projection, in one transaction, before anything is written.

        Committed before the write, so a worker that dies mid-reconciliation leaves its operations
        ``running`` for the reaper rather than for nobody.

        A claim that loses a race is skipped rather than failing the pass: something else took it,
        and whatever took it reconciles the same horizon this pass would have.
        """
        async with context.database.sessionmaker() as session, session.begin():
            due = await OperationQueue(session, tenant_id).due(kind=PROJECTION, at=now)
            if not due:
                return ()
            lifecycle = OperationLifecycle(OperationRepository(session, tenant_id), self._clock)
            claimed: list[OperationRecord] = []
            for operation in due:
                try:
                    claimed.append(await lifecycle.claim(operation.id))
                except IllegalTransition:
                    _log.info(
                        "calendars.projection.claim_lost",
                        tenant_id=str(tenant_id),
                        operation_id=str(operation.id),
                    )
            return tuple(claimed)
