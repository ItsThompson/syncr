"""When a route answers an operation identifier, and when that identifier becomes readable.

`GET /api/v1/operations/{id}` has answered 404 for identifiers the api had just handed back, twice
under a loaded suite and never in 450 isolated create-then-read pairs. The hypothesis under
investigation was a race: a concurrent maintainer tick colliding with the api on the partial unique
index that makes at most one non-terminal solve per week an invariant.

**These tests measure the ordering the hypothesis assumes, and the ordering is not a race.**
`get_transaction` commits when its `session.begin()` block exits, which is dependency teardown, and
FastAPI runs the teardown of a `yield` dependency AFTER the response has been sent. So at the
instant a client holds the identifier, no other connection can read the row. That is true of an idle
process and of a contended one: adding a maintainer tick to the picture changes nothing about it.

## What the probe is, and why it is inside the response rather than after it

`row_visible_when_the_response_is_sent` wraps the app and reads the row on a connection of its own
at the moment the final body message is handed to the ASGI `send`. The read runs in the request's
own task, so the teardown coroutine cannot have resumed and the commit cannot have been issued,
however long the probe takes. Nothing here depends on timing, and no test in this module sleeps.

That instant is also the earliest a client could possibly read: a real client pays a round trip
first. So a row invisible here is a lower bound on the defect and not an artefact of the instrument.

## The three cases, and what each is for

1. Uncontended, which establishes the ordering and separates a LATE commit from a LOST one: the row
   is unreadable at the response and readable once the request has finished.
2. With a real horizon-maintainer transaction open across the request, which is the race the
   hypothesis names. The answer is the same, which is the finding.
3. With an uncommitted rival solve holding the index key, which is the only interleaving in which
   that index can refuse the api's write. It answers 500 rather than a readable-later identifier, so
   this shape produces a stated fault and not a phantom.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.areas.config import AREAS_PREFIX
from syncr_api.concessions.config import WEEKS_PREFIX
from syncr_api.core.app_factory import create_app
from syncr_api.core.db import create_database
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS
from syncr_api.horizon.maintainer import PlanHorizonMaintainer
from syncr_api.learned.repository import WeightSetRepository
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.week_config import SOLVE_PATH
from syncr_api.routines.config import ROUTINES_PREFIX
from syncr_api.solving.config import SOLVE
from syncr_api.solving.lifecycle import OperationLifecycle
from syncr_api.solving.queue import OperationQueue
from syncr_api.solving.repository import OperationRepository
from syncr_api.templates.config import DAY_TYPES_PREFIX, WEEK_PATTERN_PREFIX
from syncr_domain.weeks import IsoWeek, Weekday
from tests.live_tenants import PASSWORD, delete_tenant, seed_owner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, MutableMapping

    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from starlette.types import ASGIApp, Receive, Scope, Send

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings
    from syncr_domain.identifiers import TenantId

pytestmark = pytest.mark.integration

BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]
BASE_URL = "http://testserver"

# The current week, because the horizon maintainer plans the weeks inside the horizon and this is
# the first of them: the racing transaction below is the real maintainer pass over a real week.
WEEK = IsoWeek.containing(datetime.now(UTC).date())

# How long a racing transaction is given to reach the point it announces before a test gives up.
# Only reached when something has gone wrong: every wait below is on an event another task sets in
# the same loop, and the timeout is so a mistake fails with a name rather than hanging the suite.
WINDOW = 10.0

# How often the wait below asks Postgres whether a backend has reached a lock.
POLL_SECONDS = 0.02


def solve_route(iso_week: IsoWeek, *, immediate: bool) -> str:
    path = WEEKS_PREFIX + SOLVE_PATH.format(iso_week=iso_week)
    return f"{path}?immediate=true" if immediate else path


# ---------------------------------------------------------------------------
# The probe
# ---------------------------------------------------------------------------


class ResponseInstant:
    """What one request's response named, and whether the row was readable when it was sent."""

    def __init__(self) -> None:
        self.identifier: str | None = None
        self.visible_when_sent: bool | None = None


def row_visible_when_the_response_is_sent(
    app: ASGIApp,
    *,
    identifier_of: Callable[[dict[str, Any]], str | None],
    is_visible: Callable[[UUID], Awaitable[bool]],
    seen: ResponseInstant,
) -> ASGIApp:
    """Wrap ``app`` so the row its response names is read on another connection at that instant.

    The read happens in the request's own task, before the final body message is forwarded, so the
    dependency teardown has not resumed and the transaction has not committed. What it measures is
    therefore the route's own ordering rather than a race with the probe.
    """

    async def wrapped(scope: Scope, receive: Receive, send: Send) -> None:
        body = bytearray()

        async def watched(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.body":
                body.extend(message.get("body", b""))
                if not message.get("more_body", False):
                    await _measure()
            await send(message)

        async def _measure() -> None:
            try:
                payload = json.loads(bytes(body) or b"{}")
            except json.JSONDecodeError:
                payload = {}
            seen.identifier = identifier_of(payload)
            if seen.identifier is not None:
                seen.visible_when_sent = await is_visible(UUID(seen.identifier))

        await app(scope, receive, watched)

    return wrapped


def the_operation_identifier(payload: dict[str, Any]) -> str | None:
    """The identifier an ``OperationResponse`` names, or ``None`` for any other body.

    Recognised by the fields that shape belongs to rather than by ``id`` alone, because several
    other responses on the way to the route under test also carry an ``id``.
    """
    names_an_operation = {"id", "kind", "status", "attempt"} <= payload.keys()
    return payload["id"] if names_an_operation else None


# ---------------------------------------------------------------------------
# The live database, the app, and one signed-in tenant that can be solved for
# ---------------------------------------------------------------------------


@pytest.fixture
async def sessions(live_database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    database = create_database(live_database_url)
    yield database.sessionmaker
    await database.engine.dispose()


@pytest.fixture
async def onlooker(
    live_database_url: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A second engine, so a read of the row cannot share the request's connection or its pool."""
    database = create_database(live_database_url)
    yield database.sessionmaker
    await database.engine.dispose()


@pytest.fixture
async def owner(sessions: async_sessionmaker[AsyncSession]) -> AsyncIterator[UserRecord]:
    account = await seed_owner(sessions)
    yield account
    await delete_tenant(sessions, account.tenant_id)


@pytest.fixture
async def app(live_database_url: str, settings: ServiceSettings) -> AsyncIterator[FastAPI]:
    """The app the process builds, wired to the live database, with no lifespan.

    The transport below calls the app directly rather than over a socket, so nothing runs a
    lifespan; the engine is disposed here instead.
    """
    database = create_database(live_database_url)
    built = create_app(settings)
    built.state.db = database
    yield built
    await database.engine.dispose()


def visibility_of(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> Callable[[UUID], Awaitable[bool]]:
    """Whether this tenant holds the operation, read in a transaction of its own."""

    async def is_visible(operation_id: UUID) -> bool:
        async with sessions() as session:
            return await OperationRepository(session, tenant_id).find(operation_id) is not None

    return is_visible


async def sign_in(client: httpx.AsyncClient, email: str) -> dict[str, str]:
    answered = await client.post(
        f"{AUTH_PREFIX}/login",
        json={"email": email, "password": PASSWORD},
        headers={"Origin": BROWSER_ORIGIN},
    )
    assert answered.status_code == HTTPStatus.OK, answered.text
    cookie = answered.headers["set-cookie"]
    token = cookie.split(f"{SESSION_COOKIE_NAME}=", 1)[1].split(";", 1)[0]
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}", "Origin": BROWSER_ORIGIN}


async def declare_the_minimum(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
) -> None:
    """An Area, a day shape on all seven weekdays, a frame, and the active weight set.

    Without these ``request_solve`` answers 409 rather than an operation, so this is what makes the
    route under test reachable at all.
    """
    area = await client.post(AREAS_PREFIX, json={"name": "Career"}, headers=headers)
    assert area.status_code == HTTPStatus.CREATED, area.text
    day_type = await client.post(DAY_TYPES_PREFIX, json={"name": "Weekday"}, headers=headers)
    assert day_type.status_code == HTTPStatus.CREATED, day_type.text
    pattern = await client.put(
        WEEK_PATTERN_PREFIX,
        json={weekday.value: day_type.json()["id"] for weekday in Weekday},
        headers=headers,
    )
    assert pattern.status_code == HTTPStatus.OK, pattern.text
    frame = await client.post(
        ROUTINES_PREFIX,
        json={"title": "Sleep", "targetTime": "23:00", "durationMinutes": 480},
        headers=headers,
    )
    assert frame.status_code == HTTPStatus.CREATED, frame.text
    async with sessions() as session, session.begin():
        await WeightSetRepository(session, tenant_id).seed_hand_tuned(at=datetime.now(UTC))


@pytest.fixture
async def watched(
    app: FastAPI,
    owner: UserRecord,
    sessions: async_sessionmaker[AsyncSession],
    onlooker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[tuple[httpx.AsyncClient, dict[str, str], ResponseInstant]]:
    """A signed-in client whose every response is probed for the row it names.

    ``raise_app_exceptions=False`` for the reason ``conftest``'s ``TestClient`` passes
    ``raise_server_exceptions=False``: the catch-all handler renders the 500 and then Starlette
    re-raises so the server can log it, so a test that lets the exception through sees the fault
    rather than the response a real client is sent.
    """
    seen = ResponseInstant()
    probed = row_visible_when_the_response_is_sent(
        app,
        identifier_of=the_operation_identifier,
        is_visible=visibility_of(onlooker, owner.tenant_id),
        seen=seen,
    )
    transport = httpx.ASGITransport(app=probed, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
        headers = await sign_in(client, owner.email)
        await declare_the_minimum(client, headers, sessions, owner.tenant_id)
        yield client, headers, seen


# ---------------------------------------------------------------------------
# 1. The ordering, uncontended: late rather than lost
# ---------------------------------------------------------------------------


async def test_a_solve_request_names_a_row_no_other_connection_can_yet_read(
    watched: tuple[httpx.AsyncClient, dict[str, str], ResponseInstant],
    onlooker: async_sessionmaker[AsyncSession],
    owner: UserRecord,
) -> None:
    """The identifier is unreadable at the response and readable once the request has finished.

    Both halves in one case on purpose: the first alone cannot tell a commit that has not happened
    yet from one that failed, and those two are different defects with different fixes.
    """
    client, headers, seen = watched

    answered = await client.post(solve_route(WEEK, immediate=True), headers=headers)

    assert answered.status_code == HTTPStatus.ACCEPTED, answered.text
    assert seen.identifier == answered.json()["id"]
    assert seen.visible_when_sent is False, (
        "the row the response names was already readable on another connection when the response "
        "was sent, so this route commits before it answers"
    )
    assert await visibility_of(onlooker, owner.tenant_id)(UUID(seen.identifier)) is True, (
        "the row never arrived, so the commit did not merely run late: it did not happen"
    )


# ---------------------------------------------------------------------------
# 2. The race the hypothesis names, driven rather than argued
# ---------------------------------------------------------------------------


async def a_maintainer_pass_held_open(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    *,
    inside: asyncio.Event,
    release: asyncio.Event,
) -> None:
    """One real horizon-maintainer pass, announcing that its transaction is open and then waiting.

    `PlanHorizonMaintainer.plan` is the production call the worker's second duty makes, and it runs
    in one transaction per week: it enqueues a `materialize` operation, claims it, assembles the
    week, appends the revision, bumps the version and enqueues a `projection`. Held open here, every
    one of those writes is uncommitted while the request under test runs, which is the loaded
    database the failures were measured under.
    """
    now = datetime.now(UTC)
    async with sessions() as session, session.begin():
        await PlanHorizonMaintainer(session, tenant_id, lambda: now).plan(WEEK, now=now)
        inside.set()
        await asyncio.wait_for(release.wait(), timeout=WINDOW)


async def a_plan_of_record_exists(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> bool:
    """Whether the week holds a live revision, read in a transaction of its own."""
    async with sessions() as session:
        return await PlanRepository(session, tenant_id).latest(WEEK) is not None


async def test_a_solve_request_racing_a_maintainer_tick_names_a_row_nobody_can_yet_read(
    watched: tuple[httpx.AsyncClient, dict[str, str], ResponseInstant],
    sessions: async_sessionmaker[AsyncSession],
    onlooker: async_sessionmaker[AsyncSession],
    owner: UserRecord,
) -> None:
    """The maintainer's open transaction changes nothing about when the identifier becomes readable.

    Which is the measurement: the window is the route's own ordering, so contention on the week the
    tick is planning neither opens it nor widens it.

    The tick's own invisibility is asserted rather than described. Without it this case would pass
    whether or not a transaction was ever open, because the answer it makes is the answer the
    uncontended case makes: the assertion that the maintainer's revision cannot be read while the
    request runs is what makes this a race rather than a second copy of case 1.
    """
    client, headers, seen = watched
    inside, release = asyncio.Event(), asyncio.Event()
    tick = asyncio.create_task(
        a_maintainer_pass_held_open(sessions, owner.tenant_id, inside=inside, release=release)
    )
    try:
        await asyncio.wait_for(inside.wait(), timeout=WINDOW)
        assert await a_plan_of_record_exists(onlooker, owner.tenant_id) is False, (
            "the maintainer's revision was already readable, so its transaction had committed and "
            "nothing was raced"
        )

        answered = await client.post(solve_route(WEEK, immediate=True), headers=headers)

        assert answered.status_code == HTTPStatus.ACCEPTED, answered.text
        assert seen.visible_when_sent is False
    finally:
        release.set()
        await tick
    assert await a_plan_of_record_exists(onlooker, owner.tenant_id) is True
    assert await visibility_of(onlooker, owner.tenant_id)(UUID(str(seen.identifier))) is True


# ---------------------------------------------------------------------------
# 3. The index itself, which refuses rather than lies
# ---------------------------------------------------------------------------


async def a_rival_solve_held_uncommitted(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    *,
    inside: asyncio.Event,
    release: asyncio.Event,
) -> None:
    """A pending solve for the week, uncommitted, holding the single-flight index key.

    This is the shape the worker's own follow-up enqueue leaves inside the dispatch's write
    transaction, and it is the only state in which the api's insert has an uncommitted rival to
    collide with: a committed one is read by `in_flight` and joined instead.
    """
    now = datetime.now(UTC)
    async with sessions() as session, session.begin():
        await OperationLifecycle(OperationRepository(session, tenant_id), lambda: now).enqueue(
            kind=SOLVE, iso_week=WEEK, due_at=now
        )
        inside.set()
        await asyncio.wait_for(release.wait(), timeout=WINDOW)


async def backends_waiting_on_a_lock(sessions: async_sessionmaker[AsyncSession]) -> int:
    """How many backends on this database the server itself reports as waiting on a lock."""
    async with sessions() as session:
        waiting = await session.scalar(
            text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database() AND wait_event_type = 'Lock'"
            )
        )
    return int(waiting or 0)


async def a_backend_blocked_on_a_lock(sessions: async_sessionmaker[AsyncSession]) -> int:
    """Wait until Postgres itself reports a backend waiting on a lock, and answer how many.

    Read out of the server rather than assumed from a sleep: what this has to know is that the api's
    insert has reached the index's lock wait, and the server is the only thing that knows.
    """
    try:
        async with asyncio.timeout(WINDOW):
            while True:
                waiting = await backends_waiting_on_a_lock(sessions)
                if waiting:
                    return waiting
                await asyncio.sleep(POLL_SECONDS)
    except TimeoutError as ran_out:
        message = f"no backend reached a lock within {WINDOW}s, so nothing was raced"
        raise AssertionError(message) from ran_out


async def non_terminal_solves(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> int:
    """How many of this tenant's solves are pending or running, which the index bounds to one."""
    async with sessions() as session:
        return (await OperationQueue(session, tenant_id).non_terminal_counts())[SOLVE]


async def test_a_solve_request_colliding_on_the_single_flight_index_is_refused(
    watched: tuple[httpx.AsyncClient, dict[str, str], ResponseInstant],
    sessions: async_sessionmaker[AsyncSession],
    onlooker: async_sessionmaker[AsyncSession],
    owner: UserRecord,
) -> None:
    """A write the index refuses answers a fault, not an identifier.

    The rival is uncommitted while the request reads, so ``in_flight`` sees nothing and the insert
    is attempted rather than joined. It then blocks on the rival's index key, which is what the wait
    on ``pg_stat_activity`` observes, and it is refused once the rival commits. The answer names no
    operation, so this shape cannot be mistaken for an identifier that reads back absent: there is
    no identifier at all.
    """
    client, headers, seen = watched
    inside, release = asyncio.Event(), asyncio.Event()
    rival = asyncio.create_task(
        a_rival_solve_held_uncommitted(sessions, owner.tenant_id, inside=inside, release=release)
    )
    try:
        await asyncio.wait_for(inside.wait(), timeout=WINDOW)
        requesting = asyncio.create_task(
            client.post(solve_route(WEEK, immediate=True), headers=headers)
        )
        await a_backend_blocked_on_a_lock(onlooker)
        release.set()
        await rival
        answered = await requesting
    finally:
        release.set()

    assert answered.status_code == HTTPStatus.INTERNAL_SERVER_ERROR, answered.text
    assert "id" not in answered.json(), "a refused write must not answer an operation identifier"
    assert seen.identifier is None
    assert await non_terminal_solves(onlooker, owner.tenant_id) == 1, (
        "the refused write left a second non-terminal solve behind, which is what the index exists "
        "to make impossible"
    )
