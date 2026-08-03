"""The idempotency branch against a real Postgres, one test per path a retry can take.

The branch cannot be shown against a fake. Three of its four paths are decided by what the
database already holds, and the fourth is decided by what another TRANSACTION holds, which is
not a thing a fake has.

The transaction shape is the load-bearing part. The claim, the work, and the stored response
share the request's own transaction, so a request that fails leaves no key behind and a request
that succeeds cannot commit its write without the response a retry will replay. A concurrent
request is answered 409 rather than left waiting, because an ``INSERT ... ON CONFLICT`` waits on
an uncommitted duplicate and would hold a second connection for the length of the first request.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select
from starlette.requests import Request

from syncr_api.core.db import create_db_engine, create_sessionmaker
from syncr_api.core.errors import MalformedRequest, ValidationFailed
from syncr_api.core.principal import Principal
from syncr_api.core.schemas import WireModel
from syncr_api.idempotency.config import (
    COMPLETED,
    IDEMPOTENCY_KEY_HEADER,
    IN_FLIGHT,
    IN_FLIGHT_RETRY_AFTER_SECONDS,
    KEY_MAX_LENGTH,
    RETENTION,
)
from syncr_api.idempotency.errors import RequestInFlight
from syncr_api.idempotency.fingerprints import request_fingerprint
from syncr_api.idempotency.guard import IdempotencyGuard
from syncr_api.idempotency.injection import (
    MISSING_KEY_DETAIL,
    OVERSIZE_KEY_DETAIL,
    get_idempotency_guard,
    require_idempotency_key,
)
from syncr_api.idempotency.models import IdempotencyKey
from syncr_api.idempotency.repository import IdempotencyKeyRepository
from tests.live_tenants import delete_tenant, seed_owner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_domain.identifiers import TenantId

pytestmark = pytest.mark.integration

ROUTE = "/api/v1/pins"
OTHER_ROUTE = "/api/v1/tasks"
# Client-chosen and opaque to the product. A readable value rather than a realistic ULID: the
# branch depends on the key matching, never on its shape.
KEY = "pin-the-gym-block"
BODY = b'{"blockId": "abc", "startsAt": "2026-02-09T13:00:00Z"}'
OTHER_BODY = b'{"blockId": "abc", "startsAt": "2026-02-09T14:00:00Z"}'
NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)

# Long enough for a real lock wait to resolve, short enough that a hang fails the test.
TIMEOUT_SECONDS = 5

# The status the in-flight refusal keeps, so its own type does not move it off 409.
HTTP_CONFLICT = 409


class Created(WireModel):
    """A response body, standing in for whatever an unsafe route answers."""

    block_id: str
    minutes: int


class CountingWork:
    """The route's own work, which must run exactly once per key."""

    def __init__(self, response: Created) -> None:
        self.response = response
        self.calls = 0

    async def __call__(self) -> Created:
        self.calls += 1
        return self.response


class FailingWork:
    """Work that raises, so the transaction it ran in rolls back."""

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self) -> Created:
        self.calls += 1
        raise RuntimeError("the service refused")


@pytest.fixture
async def engine(live_database_url: str) -> AsyncIterator[AsyncEngine]:
    live = create_db_engine(live_database_url)
    yield live
    await live.dispose()


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_sessionmaker(engine)


@pytest.fixture
async def owner(sessions: async_sessionmaker[AsyncSession]) -> AsyncIterator[UserRecord]:
    account = await seed_owner(sessions)
    yield account
    await delete_tenant(sessions, account.tenant_id)


@pytest.fixture
async def other_owner(sessions: async_sessionmaker[AsyncSession]) -> AsyncIterator[UserRecord]:
    account = await seed_owner(sessions)
    yield account
    await delete_tenant(sessions, account.tenant_id)


def guard_for(
    session: AsyncSession,
    tenant_id: TenantId,
    *,
    key: str | None = KEY,
    body: bytes = BODY,
    at: datetime = NOW,
) -> IdempotencyGuard:
    return IdempotencyGuard(
        IdempotencyKeyRepository(session, tenant_id),
        key=key,
        request_hash=request_fingerprint(body),
        clock=lambda: at,
    )


async def stored_keys(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> list[IdempotencyKey]:
    async with sessions() as session:
        rows = await session.scalars(
            select(IdempotencyKey).where(IdempotencyKey.tenant_id == tenant_id)
        )
        return list(rows)


# --------------------------------------------------------------------------------
# Unseen, then replayed
# --------------------------------------------------------------------------------


async def test_an_unseen_key_executes_the_work_and_stores_its_response(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    work = CountingWork(Created(block_id="abc", minutes=45))

    async with sessions() as session, session.begin():
        answered = await guard_for(session, owner.tenant_id).once(ROUTE, Created, work)

    assert work.calls == 1
    assert answered == work.response
    keys = await stored_keys(sessions, owner.tenant_id)
    assert [(row.route, row.idempotency_key, row.state) for row in keys] == [
        (ROUTE, KEY, COMPLETED)
    ]
    assert keys[0].expires_at == NOW + RETENTION


async def test_the_same_key_and_the_same_request_replays_without_re_executing(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # The reason the header exists: an agent retrying a POST must not create a second pin.
    first = CountingWork(Created(block_id="abc", minutes=45))
    second = CountingWork(Created(block_id="abc", minutes=999))

    async with sessions() as session, session.begin():
        await guard_for(session, owner.tenant_id).once(ROUTE, Created, first)
    async with sessions() as session, session.begin():
        replayed = await guard_for(session, owner.tenant_id).once(ROUTE, Created, second)

    assert second.calls == 0, "the work ran again, so the retry applied the request twice"
    assert replayed == first.response
    assert len(await stored_keys(sessions, owner.tenant_id)) == 1


async def test_the_same_key_with_a_different_request_is_refused(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # 422: the key was reused for a different operation, so neither replaying the first response
    # nor applying the second request would be the right answer.
    first = CountingWork(Created(block_id="abc", minutes=45))
    second = CountingWork(Created(block_id="abc", minutes=45))

    async with sessions() as session, session.begin():
        await guard_for(session, owner.tenant_id).once(ROUTE, Created, first)

    async with sessions() as session, session.begin():
        guard = guard_for(session, owner.tenant_id, body=OTHER_BODY)
        with pytest.raises(ValidationFailed, match="already used for a different request"):
            await guard.once(ROUTE, Created, second)

    assert second.calls == 0


async def test_a_request_with_no_key_runs_and_stores_nothing(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # The header is ACCEPTED on every unsafe method rather than demanded. A caller that wants the
    # guarantee sends one; the routes where a repeat is unrecoverable demand one separately.
    work = CountingWork(Created(block_id="abc", minutes=45))

    async with sessions() as session, session.begin():
        answered = await guard_for(session, owner.tenant_id, key=None).once(ROUTE, Created, work)

    assert (work.calls, answered) == (1, work.response)
    assert await stored_keys(sessions, owner.tenant_id) == []


# --------------------------------------------------------------------------------
# In flight, in another transaction
# --------------------------------------------------------------------------------


async def test_a_key_another_transaction_holds_is_answered_with_a_retry_after(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # 409 while in flight, and answered immediately rather than after a wait: the first request
    # has not committed, so there is nothing to replay yet and nothing to be gained by holding a
    # second connection until there is.
    held = CountingWork(Created(block_id="abc", minutes=45))
    contending = CountingWork(Created(block_id="abc", minutes=45))

    async with sessions() as first, first.begin():
        await guard_for(first, owner.tenant_id).once(ROUTE, Created, held)

        async with sessions() as second, second.begin():
            guard = guard_for(second, owner.tenant_id)
            with pytest.raises(RequestInFlight) as refused:
                await guard.once(ROUTE, Created, contending)

    assert contending.calls == 0
    assert refused.value.response_headers() == {"Retry-After": str(IN_FLIGHT_RETRY_AFTER_SECONDS)}
    assert refused.value.status == HTTP_CONFLICT
    assert "still being applied" in refused.value.detail


async def test_a_committed_in_flight_row_is_answered_the_same_way(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # The other way an in-flight key becomes visible: a caller that claims in one transaction and
    # completes in another. The row says the work has not answered yet, so there is nothing to
    # replay.
    async with sessions() as session, session.begin():
        claimed = await IdempotencyKeyRepository(session, owner.tenant_id).claim(
            route=ROUTE,
            key=KEY,
            request_hash=request_fingerprint(BODY),
            at=NOW,
            expires_at=NOW + RETENTION,
        )
    assert claimed is True

    work = CountingWork(Created(block_id="abc", minutes=45))
    async with sessions() as session, session.begin():
        with pytest.raises(RequestInFlight):
            await guard_for(session, owner.tenant_id).once(ROUTE, Created, work)

    assert work.calls == 0
    assert [row.state for row in await stored_keys(sessions, owner.tenant_id)] == [IN_FLIGHT]


async def test_a_request_that_failed_leaves_no_key_and_the_retry_runs(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # What makes the single-transaction shape the right one. The claim rolled back with the work,
    # so the retry is a first attempt rather than a 409 until the key expires.
    failing = FailingWork()

    with pytest.raises(RuntimeError, match="refused"):
        async with sessions() as session, session.begin():
            await guard_for(session, owner.tenant_id).once(ROUTE, Created, failing)

    assert await stored_keys(sessions, owner.tenant_id) == []

    retry = CountingWork(Created(block_id="abc", minutes=45))
    async with sessions() as session, session.begin():
        answered = await guard_for(session, owner.tenant_id).once(ROUTE, Created, retry)

    assert (failing.calls, retry.calls) == (1, 1)
    assert answered == retry.response


# --------------------------------------------------------------------------------
# The scope, and the window
# --------------------------------------------------------------------------------


async def test_one_key_on_two_routes_is_two_keys(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    pinned = CountingWork(Created(block_id="abc", minutes=45))
    captured = CountingWork(Created(block_id="def", minutes=30))

    async with sessions() as session, session.begin():
        await guard_for(session, owner.tenant_id).once(ROUTE, Created, pinned)
    async with sessions() as session, session.begin():
        answered = await guard_for(session, owner.tenant_id).once(OTHER_ROUTE, Created, captured)

    assert (pinned.calls, captured.calls) == (1, 1)
    assert answered == captured.response
    assert len(await stored_keys(sessions, owner.tenant_id)) == 2


async def test_two_tenants_cannot_collide_on_one_key(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, other_owner: UserRecord
) -> None:
    mine = CountingWork(Created(block_id="abc", minutes=45))
    theirs = CountingWork(Created(block_id="xyz", minutes=15))

    async with sessions() as session, session.begin():
        await guard_for(session, owner.tenant_id).once(ROUTE, Created, mine)
    async with sessions() as session, session.begin():
        answered = await guard_for(session, other_owner.tenant_id).once(ROUTE, Created, theirs)

    assert (mine.calls, theirs.calls) == (1, 1)
    assert answered == theirs.response
    assert len(await stored_keys(sessions, owner.tenant_id)) == 1
    assert len(await stored_keys(sessions, other_owner.tenant_id)) == 1


async def test_a_key_past_its_window_is_a_new_request(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # Retention is 24 hours, and the row speaks for the key only while it lasts. Handled on the
    # read path as well as by the sweep, so behavior does not depend on when the sweep last ran.
    first = CountingWork(Created(block_id="abc", minutes=45))
    much_later = NOW + RETENTION + timedelta(minutes=1)
    second = CountingWork(Created(block_id="abc", minutes=90))

    async with sessions() as session, session.begin():
        await guard_for(session, owner.tenant_id).once(ROUTE, Created, first)
    async with sessions() as session, session.begin():
        answered = await guard_for(session, owner.tenant_id, at=much_later).once(
            ROUTE, Created, second
        )

    assert second.calls == 1, "an expired key replayed a response nobody remembers asking for"
    assert answered == second.response
    keys = await stored_keys(sessions, owner.tenant_id)
    assert len(keys) == 1
    assert keys[0].expires_at == much_later + RETENTION


async def test_the_sweep_removes_expired_keys_and_leaves_live_ones(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, other_owner: UserRecord
) -> None:
    # The retention path itself. The loop that calls it on a schedule belongs to the worker; what
    # matters here is that it removes exactly what has expired, for one tenant.
    async with sessions() as session, session.begin():
        keys = IdempotencyKeyRepository(session, owner.tenant_id)
        await keys.claim(
            route=ROUTE,
            key="expired",
            request_hash=request_fingerprint(BODY),
            at=NOW - RETENTION,
            expires_at=NOW - timedelta(minutes=1),
        )
        await keys.claim(
            route=ROUTE,
            key="live",
            request_hash=request_fingerprint(BODY),
            at=NOW,
            expires_at=NOW + RETENTION,
        )
        await IdempotencyKeyRepository(session, other_owner.tenant_id).claim(
            route=ROUTE,
            key="expired",
            request_hash=request_fingerprint(BODY),
            at=NOW - RETENTION,
            expires_at=NOW - timedelta(minutes=1),
        )

    async with sessions() as session, session.begin():
        swept = await IdempotencyKeyRepository(session, owner.tenant_id).sweep(before=NOW)

    assert swept == 1
    assert [row.idempotency_key for row in await stored_keys(sessions, owner.tenant_id)] == ["live"]
    assert [row.idempotency_key for row in await stored_keys(sessions, other_owner.tenant_id)] == [
        "expired"
    ]


# --------------------------------------------------------------------------------
# The dependency a route declares
# --------------------------------------------------------------------------------


def post_request(*, headers: dict[str, str], body: bytes) -> Request:
    """A POST as the framework hands one to a dependency."""

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": ROUTE,
        "headers": [(name.lower().encode(), value.encode()) for name, value in headers.items()],
    }
    return Request(scope, receive)


async def test_the_dependency_reads_the_key_and_hashes_the_body(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # The wiring a route inherits: it declares the dependency and never touches the header or the
    # body's bytes. Asserted through behavior, because the hash is what decides the branch.
    principal = Principal(tenant_id=owner.tenant_id, user_id=owner.id, scopes=frozenset())
    stored = CountingWork(Created(block_id="abc", minutes=45))

    async with sessions() as session, session.begin():
        guard = await get_idempotency_guard(
            post_request(headers={IDEMPOTENCY_KEY_HEADER: KEY}, body=BODY), session, principal
        )
        await guard.once(ROUTE, Created, stored)

    async with sessions() as session, session.begin():
        replaying = await get_idempotency_guard(
            post_request(headers={IDEMPOTENCY_KEY_HEADER: KEY}, body=BODY), session, principal
        )
        replayed = await replaying.once(
            ROUTE, Created, CountingWork(Created(block_id="", minutes=0))
        )

        reusing = await get_idempotency_guard(
            post_request(headers={IDEMPOTENCY_KEY_HEADER: KEY}, body=OTHER_BODY), session, principal
        )
        with pytest.raises(ValidationFailed):
            await reusing.once(ROUTE, Created, CountingWork(Created(block_id="", minutes=0)))

    assert replayed == stored.response


async def test_a_route_that_demands_a_key_refuses_a_request_without_one(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # Approving twice would append two revisions and there is no unapprove, so the routes where a
    # repeat is unrecoverable declare the stricter dependency.
    principal = Principal(tenant_id=owner.tenant_id, user_id=owner.id, scopes=frozenset())

    async with sessions() as session, session.begin():
        without = post_request(headers={}, body=BODY)
        guard = await get_idempotency_guard(without, session, principal)
        with pytest.raises(MalformedRequest, match=IDEMPOTENCY_KEY_HEADER):
            await require_idempotency_key(without, guard)

        withheader = post_request(headers={IDEMPOTENCY_KEY_HEADER: KEY}, body=BODY)
        keyed = await get_idempotency_guard(withheader, session, principal)

        assert await require_idempotency_key(withheader, keyed) is keyed
    assert IDEMPOTENCY_KEY_HEADER in MISSING_KEY_DETAIL


async def test_a_key_wider_than_the_column_is_refused_before_it_reaches_one(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # A caller-supplied value out of bounds is a 400 naming the bound, not a driver failure on
    # the way to storing it. The key at the bound is the control, so the check is shown to
    # refuse what is too wide rather than everything long.
    principal = Principal(tenant_id=owner.tenant_id, user_id=owner.id, scopes=frozenset())
    work = CountingWork(Created(block_id="abc", minutes=45))

    async with sessions() as session, session.begin():
        oversize = post_request(
            headers={IDEMPOTENCY_KEY_HEADER: "k" * (KEY_MAX_LENGTH + 1)}, body=BODY
        )
        with pytest.raises(MalformedRequest, match=str(KEY_MAX_LENGTH)):
            await get_idempotency_guard(oversize, session, principal)

        at_the_bound = post_request(
            headers={IDEMPOTENCY_KEY_HEADER: "k" * KEY_MAX_LENGTH}, body=BODY
        )
        guard = await get_idempotency_guard(at_the_bound, session, principal)
        answered = await guard.once(ROUTE, Created, work)

    assert (work.calls, answered) == (1, work.response)
    assert str(KEY_MAX_LENGTH) in OVERSIZE_KEY_DETAIL
