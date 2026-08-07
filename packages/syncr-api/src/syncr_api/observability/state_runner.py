"""The duty that keeps the state-derived gauges readable, whether or not anything else happened.

Three families are set here: the two per-source gauges the Calendar dashboard draws and
``SourceStale`` fires on, and the token age ``WriteTargetTokenExpiring`` fires on.

**The first tick reads rather than schedules**, which is the opposite of every writing duty on the
loop. A sweep that skips its first tick avoids a write on a path meant to be idle; a READING that
skips its first tick leaves three families absent for a whole interval after every restart, and a
restart is when an operator is most likely to be looking. Nothing is written here, so there is
nothing to defer.

**Per tenant, in one transaction per tenant, with each tenant's fault contained.** Every statement
over a table that holds a plan carries its tenant, so this enumerates tenants and builds scoped
repositories rather than issuing one unscoped read. A tenant whose read raises is counted and the
tenants after it are still observed: a duty that dropped the rest would take the alerting for the
whole deployment down with one bad row.

**AND A TENANT THAT STOPS BEING ENUMERATED IS FORGOTTEN.** All three families here are labelled, and
nothing in the client library removes a child, so a per-tenant reconciliation prunes a tenant's
sources only while that tenant is still visited. A tenant that leaves the list is never visited
again and holds every child at its last value for the life of the process: ``SourceStale`` and
``WriteTargetTokenExpiring`` both read a maximum across tenants, so one departed tenant fires either
of them forever with no repair available. The forgetting is done with the tenant list this duty just
ENUMERATED, deliberately not with the tenants it read successfully, because a contained fault means
a tenant went unobserved rather than away.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from prometheus_client import Counter

from syncr_api.accounts.repository import TenantRepository
from syncr_api.calendars.repository import CalendarSourceRepository
from syncr_api.calendars.sync_metrics import forget_tenants as forget_source_tenants
from syncr_api.calendars.sync_metrics import observed_state
from syncr_api.google_account.repository import GoogleCredentialRepository
from syncr_api.google_account.token_metrics import forget_tenants as forget_token_tenants
from syncr_api.google_account.token_metrics import observed_credential
from syncr_common.logging import get_logger
from syncr_common.metrics import REGISTRY, measured

if TYPE_CHECKING:
    from datetime import datetime, timedelta

    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_api.core.clock import Clock
    from syncr_api.worker.main import WorkerContext
    from syncr_domain.identifiers import TenantId

_log = get_logger("syncr.observability")

# A tenant whose reading raised. Counted rather than only logged, for the reason every other
# contained-fault counter on this loop exists: the boundary means the decorated call no longer
# raises, so `measured` sees a healthy duty while a tenant's gauges go stale forever.
TENANT_READING_FAILURES = Counter(
    "syncr_observability_tenant_failures_total",
    "State readings that raised for one tenant and were contained.",
    registry=REGISTRY,
)


class StateGaugeRunner:
    """One duty on the worker loop: re-read the state gauges when due, return when not.

    A callable object rather than a closure, so the loop's name lookup finds a stable name for its
    failure metric and so a test can read when the reading is next due.
    """

    __name__ = "state_gauges"

    def __init__(self, *, interval: timedelta, clock: Clock) -> None:
        self._interval = interval
        self._clock = clock
        self._next_due_at: datetime | None = None

    @property
    def next_due_at(self) -> datetime | None:
        """When this runner will next do work, or ``None`` before its first tick."""
        return self._next_due_at

    async def __call__(self, context: WorkerContext) -> None:
        now = self._clock()
        if self._next_due_at is not None and now < self._next_due_at:
            return
        self._next_due_at = now + self._interval
        await self.observe(context, now=now)

    @measured("state_gauges")
    async def observe(self, context: WorkerContext, *, now: datetime) -> int:
        """Set every state gauge for every tenant. Returns how many tenants were read."""
        async with context.database.sessionmaker() as reader:
            tenants = await TenantRepository(reader).list_ids()
        read = 0
        for tenant_id in tenants:
            read += await self._observed_tenant(context, tenant_id, now=now)
        # Every tenant that was ENUMERATED, not every tenant that was read: a contained fault above
        # means a tenant went unobserved this tick rather than away, and forgetting it would delete
        # a live series and leave the alert reading healthy for the one tenant in doubt.
        forget_source_tenants(tenants)
        forget_token_tenants(tenants)
        return read

    async def _observed_tenant(
        self, context: WorkerContext, tenant_id: TenantId, *, now: datetime
    ) -> int:
        try:
            async with context.database.sessionmaker() as session:
                await _observe_tenant(session, tenant_id, now=now)
        except Exception:  # noqa: BLE001 - one tenant's fault must not stop the others
            TENANT_READING_FAILURES.inc()
            _log.exception("observability.state.tenant_failed", tenant_id=str(tenant_id))
            return 0
        return 1


async def _observe_tenant(session: AsyncSession, tenant_id: TenantId, *, now: datetime) -> None:
    observed_state(
        tenant_id, await CalendarSourceRepository(session, tenant_id).list_all(), now=now
    )
    observed_credential(
        tenant_id, await GoogleCredentialRepository(session, tenant_id).read(), now=now
    )
