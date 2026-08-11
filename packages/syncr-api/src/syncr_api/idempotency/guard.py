"""``IdempotencyGuard``: the four-way branch, behind one call.

```
POST with Idempotency-Key
  │
  ├── key seen, same request hash, completed
  │     └──▶ replay the stored response. Do NOT re-execute
  ├── key seen, same request hash, in flight
  │     └──▶ 409 with a Retry-After
  ├── key seen, DIFFERENT request hash
  │     └──▶ 422. The key was reused for a different operation
  └── key unseen
        └──▶ execute, store the response against the key, return it
```

A route calls :meth:`IdempotencyGuard.once` and stays one expression, so no handler carries
the branch and no handler can implement it slightly differently. The work runs inside the
request's own transaction along with the claim and the stored response, which is what makes
the guarantee exact: a request that fails leaves no key behind, and a request that succeeds
cannot commit its write without the response a retry will replay.

This is not a ``service.py`` and its methods take no principal, for the same reason
``accounts/authentication.py`` is not one: it runs at the HTTP edge around a service call
rather than as the operation being authorized. Its scope comes from the repository it is
built with, which is constructed from the principal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.core.errors import ValidationFailed
from syncr_api.idempotency.config import IN_FLIGHT_DETAIL, RETENTION, REUSED_KEY_DETAIL
from syncr_api.idempotency.errors import RequestInFlight
from syncr_common.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from pydantic import BaseModel

    from syncr_api.core.clock import Clock
    from syncr_api.idempotency.records import IdempotencyKeyRecord
    from syncr_api.idempotency.repository import IdempotencyKeyRepository

_log = get_logger("syncr.idempotency")


class IdempotencyGuard:
    """Runs one unsafe request's work at most once per key.

    The key arrives as a declared header parameter and the request hash is taken from the
    request, both when this is built, so a route never touches the header and never hashes
    a body.
    """

    def __init__(
        self,
        keys: IdempotencyKeyRepository,
        *,
        key: str | None,
        request_hash: str,
        clock: Clock,
    ) -> None:
        self._keys = keys
        self._key = key
        self._request_hash = request_hash
        self._clock = clock

    async def once[ResponseT: BaseModel](
        self,
        route: str,
        response_model: type[ResponseT],
        work: Callable[[], Awaitable[ResponseT]],
    ) -> ResponseT:
        """Run ``work`` unless this key already did, in which case replay what it answered.

        Without a key the work simply runs: the header is accepted on every unsafe method
        rather than demanded, and a caller that wants the guarantee sends one.
        """
        if self._key is None:
            return await work()
        if not await self._take(route, self._key):
            return self._replay(await self._keys.find(route=route, key=self._key), response_model)
        result = await work()
        await self._keys.complete(
            route=route, key=self._key, response_body=result.model_dump(mode="json")
        )
        return result

    async def _take(self, route: str, key: str) -> bool:
        """Whether this request owns the key, having claimed it or taken over an expired row."""
        if not await self._keys.hold(route=route, key=key):
            # Another transaction holds the key right now. Its row is not committed, so
            # there is nothing to classify and nothing to replay yet.
            raise RequestInFlight(IN_FLIGHT_DETAIL)
        at = self._clock()
        expires_at = at + RETENTION
        claimed = await self._keys.claim(
            route=route,
            key=key,
            request_hash=self._request_hash,
            at=at,
            expires_at=expires_at,
        )
        if claimed:
            return True
        return await self._keys.reclaim(
            route=route,
            key=key,
            request_hash=self._request_hash,
            at=at,
            expires_at=expires_at,
        )

    def _replay[ResponseT: BaseModel](
        self, stored: IdempotencyKeyRecord | None, response_model: type[ResponseT]
    ) -> ResponseT:
        if stored is None:
            # The row was swept between the failed claim and this read. Nothing was applied
            # twice; the caller retries and claims the key cleanly.
            raise RequestInFlight(IN_FLIGHT_DETAIL)
        if not stored.answers(self._request_hash):
            raise ValidationFailed(REUSED_KEY_DETAIL)
        if not stored.is_completed() or stored.response_body is None:
            raise RequestInFlight(IN_FLIGHT_DETAIL)
        _log.info("idempotency.request.replayed", route=stored.route)
        return response_model.model_validate(stored.response_body)
