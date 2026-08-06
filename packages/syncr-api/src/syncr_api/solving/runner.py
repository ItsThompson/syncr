"""The worker duty that drains due solves: one tenant at a time, one solve at a time.

**The tenant enumeration is this duty's decision, and it is the calendar poll's.** Every statement
over a table that holds a plan carries its tenant, with no exception for worker code, so the pass
reads the tenant ids in one session and then builds one scoped coordinator per tenant. The
alternative -- one unscoped scan across every tenant's due operations -- would be the only bare
statement in a scoped package, and the boundary test forbids exactly that.

**Every tick does work when there is work.** Unlike the calendar poll and the horizon maintainer,
this duty holds no interval of its own: due-ness lives on the operation's own ``scheduled_for``,
which the debounce window set, so a solve becomes claimable 1500 ms after the mutation that asked
for it and the tick is only the resolution at which the worker looks.

**One transaction for the claim, and the dispatch takes its own.** The claim has to commit before
the solve begins: an operation left ``running`` inside an open transaction would be invisible to
every other reader, including the reaper, and the solve itself takes over a second during which no
transaction should be held.

**Faults are contained per tenant and per solve.** A tenant whose enumeration raises is counted and
the tenants after it still run; a solve that raises has already been turned into a stated failure by
the dispatch, so what reaches the boundary here is a fault in the containment itself.

**A tenant's drain is bounded per tick.** A backlog of due solves is bounded by the single-flight
invariant to one per week, so an ordinary tenant has one or two; the bound is what stops one tenant
with an unusual backlog from spending a whole tick while others wait, and what is left is claimed by
the next tick.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from prometheus_client import Counter

from syncr_api.accounts.repository import TenantRepository
from syncr_api.solving.config import (
    FAILED,
    PENDING,
    SOLVES_PER_TICK,
    SUCCEEDED,
    SUPERSEDED,
)
from syncr_api.solving.dispatch import SolveDispatch
from syncr_api.solving.injection import build_solve_coordinator, debounce_window
from syncr_api.solving.metrics import OPERATIONS_NON_TERMINAL
from syncr_api.solving.queue import OperationQueue
from syncr_common.logging import get_logger
from syncr_common.metrics import REGISTRY, measured

if TYPE_CHECKING:
    from datetime import timedelta

    from sqlalchemy.ext.asyncio.session import AsyncSession

    from syncr_api.core.clock import Clock
    from syncr_api.solving.coordinator import SolveCoordinator
    from syncr_api.solving.records import OperationRecord
    from syncr_api.worker.main import WorkerContext
    from syncr_domain.identifiers import TenantId

# A tenant whose pass raised before or between its solves. Counted rather than only logged, because
# the tick answers with a tally and a contained fault answers with an empty one: without this, a
# tenant failing every tick would leave every counter at zero while the duty reported healthy.
TENANT_PASS_FAILURES = Counter(
    "syncr_solve_tenant_failures_total",
    "Solve passes that raised for one tenant and were contained.",
    registry=REGISTRY,
)

_log = get_logger("syncr.solving")


@dataclass(frozen=True, slots=True)
class SolvePass:
    """What one pass claimed and what became of it, so one log line says it."""

    claimed: int = 0
    succeeded: int = 0
    superseded: int = 0
    failed: int = 0
    tenants_failed: int = 0

    def plus(self, other: SolvePass) -> SolvePass:
        return SolvePass(
            claimed=self.claimed + other.claimed,
            succeeded=self.succeeded + other.succeeded,
            superseded=self.superseded + other.superseded,
            failed=self.failed + other.failed,
            tenants_failed=self.tenants_failed + other.tenants_failed,
        )

    def as_log_fields(self) -> dict[str, int]:
        return {
            "claimed": self.claimed,
            "succeeded": self.succeeded,
            "superseded": self.superseded,
            "failed": self.failed,
            "tenants_failed": self.tenants_failed,
        }


class SolveRunner:
    """One duty on the worker loop: claim every due solve and run it, or return immediately.

    A callable object rather than a closure, so the loop's name lookup finds a stable name for its
    failure metric.
    """

    __name__ = "solve"

    def __init__(self, *, clock: Clock, solves_per_tick: int = SOLVES_PER_TICK) -> None:
        self._clock = clock
        self._solves_per_tick = solves_per_tick

    async def __call__(self, context: WorkerContext) -> None:
        await self.drain(context)

    @measured("solve_runner")
    async def drain(self, context: WorkerContext) -> SolvePass:
        """One pass over every tenant's due solves, each tenant contained on its own."""
        async with context.database.sessionmaker() as reader:
            tenants = await TenantRepository(reader).list_ids()

        total = SolvePass()
        for tenant_id in tenants:
            total = total.plus(await self._tenant(context, tenant_id))
        if total.claimed or total.tenants_failed:
            _log.info("solving.pass.completed", **total.as_log_fields())
        return total

    async def _tenant(self, context: WorkerContext, tenant_id: TenantId) -> SolvePass:
        """One tenant's due solves, bounded, with its faults contained and counted."""
        total = SolvePass()
        try:
            for _ in range(self._solves_per_tick):
                claimed = await self._claimed(context, tenant_id)
                if claimed is None:
                    break
                total = total.plus(await self._ran(context, tenant_id, claimed))
            await self._set_the_non_terminal_gauge(context, tenant_id)
        except Exception:  # noqa: BLE001 - one tenant's fault must not stop the others
            TENANT_PASS_FAILURES.inc()
            _log.exception("solving.pass.tenant_failed", tenant_id=str(tenant_id))
            return total.plus(SolvePass(tenants_failed=1))
        return total

    async def _claimed(self, context: WorkerContext, tenant_id: TenantId) -> OperationRecord | None:
        """One due solve, stepped to running in its own committed transaction."""
        async with context.database.sessionmaker() as session, session.begin():
            return await self._coordinator(context, session, tenant_id).claim_next()

    async def _ran(
        self, context: WorkerContext, tenant_id: TenantId, claimed: OperationRecord
    ) -> SolvePass:
        """One claimed solve, run to a terminal status, tallied by which one it reached.

        A failure with an attempt left comes back to the queue as ``pending`` in the same
        transaction that recorded it, so both readings of "this solve did not produce a plan" are
        one tally rather than two.
        """
        week = claimed.iso_week
        # The table's own check constraint refuses a solve naming no week, so this is a corrupt row
        # rather than a state the runner has to handle.
        if week is None:  # pragma: no cover - unreachable while that constraint holds
            message = f"solve {claimed.id} names no week, which its table forbids"
            raise RuntimeError(message)
        finished = await self._dispatch(context, tenant_id).run(claimed, week)
        return SolvePass(
            claimed=1,
            succeeded=int(finished.status == SUCCEEDED),
            superseded=int(finished.status == SUPERSEDED),
            failed=int(finished.status in {FAILED, PENDING}),
        )

    async def _set_the_non_terminal_gauge(
        self, context: WorkerContext, tenant_id: TenantId
    ) -> None:
        """Report how much is still outstanding, by kind, after this tenant's pass.

        SET from a read rather than nudged per claim, because it measures a state: a gauge
        incremented per claim would drift permanently the first time a pass raised between two
        solves, and would report a backlog that had already been drained.

        A pass that raised before this leaves the gauge at what it last held, which is why the
        contained-fault counter beside it exists: the two are read together.
        """
        async with context.database.sessionmaker() as reader:
            counts = await OperationQueue(reader, tenant_id).non_terminal_counts()
        for kind, total in counts.items():
            OPERATIONS_NON_TERMINAL.labels(kind=kind).set(total)

    def _coordinator(
        self, context: WorkerContext, session: AsyncSession, tenant_id: TenantId
    ) -> SolveCoordinator:
        return build_solve_coordinator(
            session, tenant_id, clock=self._clock, debounce=self._debounce(context)
        )

    def _dispatch(self, context: WorkerContext, tenant_id: TenantId) -> SolveDispatch:
        return SolveDispatch(
            context.database,
            tenant_id,
            clock=self._clock,
            debounce=self._debounce(context),
        )

    def _debounce(self, context: WorkerContext) -> timedelta:
        """This deployment's window, read from the worker's own settings.

        The runner never schedules a debounced solve itself -- a follow-up is due now, because the
        mutation that displaced its predecessor has already happened -- so this exists for the
        coordinator's constructor rather than for a decision here.
        """
        return debounce_window(context.settings.solve_debounce_ms)
