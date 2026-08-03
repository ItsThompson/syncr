"""The five statements the idempotency branch is made of.

Each method here is one statement and no decision. Which branch a request takes is the
guard's job, so the classification is testable without a database and these are testable
against one.

``hold`` is the one statement that is not over a table. A transaction-scoped advisory lock is
what makes a concurrent request with the same key answer 409 immediately instead of waiting
for the first request to commit: an ``INSERT ... ON CONFLICT DO NOTHING`` waits on an
uncommitted duplicate, which would hold a second connection for the length of the first
request and answer a retry storm by consuming the pool. The lock's number carries the tenant,
so it is scoped exactly as the row is.
"""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, cast

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from syncr_api.core.repository import TenantScopedRepository
from syncr_api.core.tenancy import TENANT_ID_COLUMN
from syncr_api.idempotency.config import COMPLETED, IN_FLIGHT, KeyState
from syncr_api.idempotency.fingerprints import lock_token
from syncr_api.idempotency.models import IdempotencyKey
from syncr_api.idempotency.records import IdempotencyKeyRecord

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_api.core.columns import JsonDocument

_TRY_ADVISORY_LOCK = text("SELECT pg_try_advisory_xact_lock(:token)")


class IdempotencyKeyRepository(TenantScopedRepository):
    """One tenant's idempotency keys."""

    async def hold(self, *, route: str, key: str) -> bool:
        """Take this key for the rest of this transaction, or report that someone else has it.

        Never waits. The lock is released when the transaction ends, whether it committed or
        rolled back, so a failed request leaves nothing behind for the next one to trip over.
        """
        token = lock_token(self.tenant_id, route, key)
        held = await self._session.scalar(_TRY_ADVISORY_LOCK, {"token": token})
        return bool(held)

    async def claim(
        self,
        *,
        route: str,
        key: str,
        request_hash: str,
        at: datetime,
        expires_at: datetime,
    ) -> bool:
        """Record this key as in flight, reporting whether it was unseen."""
        statement = (
            insert(IdempotencyKey)
            .values(
                {
                    TENANT_ID_COLUMN: self.tenant_id,
                    "route": route,
                    "idempotency_key": key,
                    "request_hash": request_hash,
                    "state": IN_FLIGHT,
                    "response_body": None,
                    "created_at": at,
                    "expires_at": expires_at,
                }
            )
            .on_conflict_do_nothing()
            .returning(IdempotencyKey.idempotency_key)
        )
        return (await self._session.scalar(statement)) is not None

    async def reclaim(
        self,
        *,
        route: str,
        key: str,
        request_hash: str,
        at: datetime,
        expires_at: datetime,
    ) -> bool:
        """Take over a row whose retention window has passed, reporting whether one had.

        A key past its window speaks for nothing, so the request carrying it is a new request
        rather than a retry of one nobody remembers.
        """
        reclaimed = await self._session.scalar(
            self.scoped_update(IdempotencyKey)
            .where(
                IdempotencyKey.route == route,
                IdempotencyKey.idempotency_key == key,
                IdempotencyKey.expires_at <= at,
            )
            .values(
                request_hash=request_hash,
                state=IN_FLIGHT,
                response_body=None,
                created_at=at,
                expires_at=expires_at,
            )
            .returning(IdempotencyKey.idempotency_key)
        )
        return reclaimed is not None

    async def complete(self, *, route: str, key: str, response_body: JsonDocument) -> None:
        """Store the response this key's request produced, so a retry replays it."""
        await self._session.execute(
            self.scoped_update(IdempotencyKey)
            .where(
                IdempotencyKey.route == route,
                IdempotencyKey.idempotency_key == key,
            )
            .values(state=COMPLETED, response_body=dict(response_body))
        )

    async def find(self, *, route: str, key: str) -> IdempotencyKeyRecord | None:
        """The row this key already has, or ``None`` when it is unseen."""
        found = await self._session.scalar(
            self.scoped_select(IdempotencyKey).where(
                IdempotencyKey.route == route,
                IdempotencyKey.idempotency_key == key,
            )
        )
        return _as_record(found) if found is not None else None

    async def sweep(self, *, before: datetime) -> int:
        """Delete every key past its retention window, returning how many went.

        The only retention path in plan storage, alongside terminal operations. Everything
        else here is a fact about a week that happened, and facts do not expire.
        """
        swept = await self._session.scalars(
            self.scoped_delete(IdempotencyKey)
            .where(IdempotencyKey.expires_at <= before)
            .returning(IdempotencyKey.idempotency_key)
        )
        return len(swept.all())


def _as_record(key: IdempotencyKey) -> IdempotencyKeyRecord:
    return IdempotencyKeyRecord(
        tenant_id=key.tenant_id,
        route=key.route,
        key=key.idempotency_key,
        request_hash=key.request_hash,
        state=cast("KeyState", key.state),
        response_body=deepcopy(key.response_body),
        created_at=key.created_at,
        expires_at=key.expires_at,
    )
