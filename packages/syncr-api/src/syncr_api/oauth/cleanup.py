"""The expiry sweep the worker runs.

Three kinds of row accumulate and nothing else removes them: authorization codes, which are
minted per sign-in attempt and live a minute; refresh tokens, which are minted per rotation
and so accumulate one per refresh for the life of a grant; and grants, which linger after
revocation. A refreshing CLI produces a row every fifteen minutes, so without this the table
grows forever for no reader.

**The sweep is per tenant, and that is deliberate.** Every statement over a table that holds
a plan carries its tenant, with no exception for maintenance, so the sweep enumerates tenants
and builds one scoped repository for each rather than issuing one unscoped delete. The cost
is three queries per tenant per sweep, on a deployment whose tenant count is one; what it buys
is that "every scoped statement is scoped" stays a property of the code rather than a property
with a footnote, and that a sweep cannot reach a row it was not scoped to.

**It owns its own cadence.** The worker ticks every few seconds and a sweep is not wanted that
often, so the runner keeps the instant it is next due and returns immediately in between. That
is the registry's contract: a runner decides per tick whether it has work.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from syncr_api.accounts.repository import TenantRepository
from syncr_api.oauth.config import DEAD_GRANT_RETENTION
from syncr_api.oauth.repository import OAuthRepository
from syncr_common.logging import get_logger
from syncr_common.metrics import measured

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_api.core.clock import Clock
    from syncr_api.worker.main import WorkerContext
    from syncr_domain.identifiers import TenantId

# How often the sweep runs. Expired rows are inert, so this governs table size rather than
# correctness, and a quarter hour of imprecision costs nothing.
SWEEP_INTERVAL = timedelta(minutes=15)

_log = get_logger("syncr.oauth")


@dataclass(frozen=True, slots=True)
class SweptRows:
    """What a sweep removed, per kind, so one log line says what it did."""

    codes: int = 0
    refresh_tokens: int = 0
    grants: int = 0

    @property
    def total(self) -> int:
        return self.codes + self.refresh_tokens + self.grants

    def plus(self, other: SweptRows) -> SweptRows:
        """This tally and ``other`` combined."""
        return SweptRows(
            codes=self.codes + other.codes,
            refresh_tokens=self.refresh_tokens + other.refresh_tokens,
            grants=self.grants + other.grants,
        )


class ExpirySweep:
    """Removes the Authorization Server's expired rows, one tenant at a time."""

    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self._session = session
        self._clock = clock

    @measured("oauth")
    async def sweep(self) -> SweptRows:
        """Remove every expired code, expired refresh token, and long-dead grant.

        Grants go last. A grant's refresh tokens are removed with it through the foreign
        key's cascade, so taking the grants first would delete rows the token pass then could
        not count, and the number reported would be wrong in a way nobody could see.
        """
        now = self._clock()
        swept = SweptRows()
        for tenant_id in await TenantRepository(self._session).list_ids():
            swept = swept.plus(await self._sweep_tenant(tenant_id, now))
        if swept.total:
            _log.info(
                "oauth.sweep.completed",
                codes=swept.codes,
                refresh_tokens=swept.refresh_tokens,
                grants=swept.grants,
            )
        return swept

    async def _sweep_tenant(self, tenant_id: TenantId, now: datetime) -> SweptRows:
        scoped = OAuthRepository(self._session, tenant_id)
        return SweptRows(
            codes=await scoped.delete_expired_codes(now),
            refresh_tokens=await scoped.delete_expired_refresh_tokens(now),
            grants=await scoped.delete_grants_revoked_before(now - DEAD_GRANT_RETENTION),
        )


class OAuthSweepRunner:
    """One duty on the worker loop: sweep when due, return immediately when not.

    A callable object rather than a closure, so the loop's name lookup finds a stable name for
    its failure metric and so a test can read when the sweep is next due.

    The FIRST tick schedules rather than sweeps. A process that restarts often would otherwise
    delete on every boot, which is a write on a path that is supposed to be idle.
    """

    __name__ = "oauth_expiry_sweep"

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
        if self._next_due_at is None or now < self._next_due_at:
            self._next_due_at = self._next_due_at or now + self._interval
            return
        self._next_due_at = now + self._interval
        # Its own session and its own transaction, independent of any request, committed by
        # the context manager so a partial sweep is not left half applied.
        async with context.database.sessionmaker() as session, session.begin():
            await ExpirySweep(session, self._clock).sweep()
