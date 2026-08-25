"""When a route answers an operation identifier, that identifier is already readable.

`GET /api/v1/operations/{id}` answered 404 for identifiers the api had just handed back, twice under
a loaded suite and never in 450 isolated create-then-read pairs. The measurement this module once
took found the cause, and it was not a race: `get_transaction` commits when its `session.begin()`
block exits, which is dependency teardown, and FastAPI has run the teardown of a `yield` dependency
AFTER the response was sent since 0.106. At the instant a client held the identifier, no other
connection could read the row, idle process or contended one.

**The routes that answer such an identifier therefore commit before they answer.** Each handler
whose response carries an operation issues ``await transaction.commit()`` after its work and before
the response is built: the immediate solve (`plans.api`), the forced calendar-source sync
(`calendars.api`), the tradeoff request (`concessions.api`), and the two pin answers whose response
carries the debounced solve the edit scheduled (`pins.api`). These tests assert the fixed ordering
at all of the sites the defect was reached from, on a second connection, at the instant the response
is handed over. Why the rule stops there is stated where the change lives, in `core.db`.

## What the probe is, and why it is inside the response rather than after it

`row_visible_when_the_response_is_sent` wraps the app and reads the row on a connection of its own
at the moment the final body message is handed to the ASGI `send`. The read runs in the request's
own task, so the teardown coroutine cannot have resumed and the commit cannot have been issued,
however long the probe takes. Nothing here depends on timing, and no test in this module sleeps.

That instant is also the earliest a client could possibly read: a real client pays a round trip
first. So a row unreadable here would be a live defect and not an artefact of the instrument.

## The cases, and what each is for

1. The immediate solve, uncontended: the operation is readable at the response and stays readable.
2. The same solve with a real horizon-maintainer transaction open across the request: contention on
   the week changes nothing about the ordering.
3. An uncommitted rival solve holding the single-flight index key: the api's write is refused and
   the route answers a fault, never an identifier.
4. The forced calendar-source sync: the same readability, on the route whose operation both creates
   and completes itself.
5. The tradeoff request: the operation that carries the candidate, asked for against a short week.
6. A pin: the response carries the debounced solve the edit schedules, so that operation is held to
   the same rule even though the route's own answer is a pin, a verdict, and an operation.
7. A resolved conflict whose answer moved the block: the solve the answer names rides under
   `operation`, and is held to the same rule.
8. A commit that fails mid-handler: a fault status and no identifier, never a 200 naming a row
   nobody can read.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.areas.config import AREAS_PREFIX
from syncr_api.areas.models import AreaRow
from syncr_api.areas.repository import AreaRepository
from syncr_api.calendars.config import CALENDAR_SOURCES_PREFIX
from syncr_api.concessions.config import WEEKS_PREFIX
from syncr_api.conflicts.config import CONFLICTS_PREFIX
from syncr_api.core.app_factory import create_app
from syncr_api.core.db import create_database
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS
from syncr_api.horizon.maintainer import PlanHorizonMaintainer
from syncr_api.learned.repository import WeightSetRepository
from syncr_api.offplan.config import OFF_PLAN_PREFIX
from syncr_api.plans.config import MOVED_RESOLUTION
from syncr_api.plans.conflicts import Commitment, PlanConflictRepository
from syncr_api.plans.overlaps import DetectedConflict
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_documents import stored_document
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.plans.week_config import SOLVE_PATH
from syncr_api.routines.config import ROUTINES_PREFIX
from syncr_api.solving.config import SOLVE
from syncr_api.solving.lifecycle import OperationLifecycle
from syncr_api.solving.queue import OperationQueue
from syncr_api.solving.repository import OperationRepository
from syncr_api.tasks.models import TaskRow
from syncr_api.tasks.repository import TaskRepository
from syncr_api.templates.config import DAY_TYPES_PREFIX, WEEK_PATTERN_PREFIX
from syncr_api.user_settings.config import SETTINGS_PREFIX
from syncr_domain.habits import BindingSource
from syncr_domain.identity import BindingKind, BindingRef, Origin, block_id, is_placed_by_the_solver
from syncr_domain.intervals import Interval
from syncr_domain.plan import AdjustmentKind, Block, PlanDocument
from syncr_domain.reasons import Bound, ReasonRecord
from syncr_domain.weeks import IsoWeek, Weekday
from tests.live_tenants import PASSWORD, delete_tenant, seed_owner
from tests.plan_documents import (
    WEEK as CONFLICTED_WEEK,
)
from tests.plan_documents import (
    a_block,
    a_block_holding,
    a_document,
    between,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, MutableMapping

    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import async_sessionmaker
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
#
# A racer's own wait for its release SUPPRESSES the timeout rather than raising it. The racers are
# awaited in a `finally`, and an exception raised there replaces the one the case was reporting: a
# case failing on "nothing was raced" would otherwise report a bare TimeoutError from the racer.
WINDOW = 10.0

# How often the wait below asks Postgres whether a backend has reached a lock.
POLL_SECONDS = 0.02

# The pin case runs against a far-future week, so no placement on it can ever be in the past under
# the real clock, and the plan it pins against is seeded rather than solved. Its clock instant and
# its zone match the seeded plan's own.
PINNED_WEEK = IsoWeek(2030, 7)
PINNED_NOW = datetime(2030, 2, 11, 9, 0, tzinfo=UTC)
PINNED_ZONE = "Europe/London"
PIN_TASK_ID = uuid4()
PIN_AREA_ID = uuid4()
PIN_BINDING = BindingRef(kind=BindingKind.TASK, entity_id=PIN_TASK_ID, occurrence_key="00")
PIN_BLOCK_ID = block_id(PINNED_WEEK, PIN_BINDING)


def solve_route(iso_week: IsoWeek, *, immediate: bool) -> str:
    path = WEEKS_PREFIX + SOLVE_PATH.format(iso_week=iso_week)
    return f"{path}?immediate=true" if immediate else path


def pin_route() -> str:
    return f"{WEEKS_PREFIX}/{PINNED_WEEK}/pins"


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
    other responses on the way to the route under test also carry an ``id``. One level of nesting
    is followed, because a pin's answer carries its scheduled solve under ``operation``.
    """
    names_an_operation = {"id", "kind", "status", "attempt"} <= payload.keys()
    if names_an_operation:
        return payload["id"]
    carried = payload.get("operation")
    return the_operation_identifier(carried) if isinstance(carried, dict) else None


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
# 1. The immediate solve: readable at the answer
# ---------------------------------------------------------------------------


async def test_an_immediate_solve_names_a_row_readable_the_moment_it_answers(
    watched: tuple[httpx.AsyncClient, dict[str, str], ResponseInstant],
    onlooker: async_sessionmaker[AsyncSession],
    owner: UserRecord,
) -> None:
    """The operation is readable on another connection when the response is sent.

    The route commits before it answers, so the identifier a client holds names a row that is
    already there. Readability after the request has finished is asserted beside it, so a commit
    that never ran cannot hide behind one that merely moved.
    """
    client, headers, seen = watched

    answered = await client.post(solve_route(WEEK, immediate=True), headers=headers)

    assert answered.status_code == HTTPStatus.ACCEPTED, answered.text
    assert seen.identifier == answered.json()["id"]
    assert seen.visible_when_sent is True, (
        "the row the response names was still unreadable when the response was sent, so this "
        "route left its commit to teardown, which FastAPI runs only after the response"
    )
    assert await visibility_of(onlooker, owner.tenant_id)(UUID(seen.identifier)) is True


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
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(release.wait(), timeout=WINDOW)


async def a_plan_of_record_exists(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> bool:
    """Whether the week holds a live revision, read in a transaction of its own."""
    async with sessions() as session:
        return await PlanRepository(session, tenant_id).latest(WEEK) is not None


async def test_a_solve_request_racing_a_maintainer_tick_answers_a_readable_row(
    watched: tuple[httpx.AsyncClient, dict[str, str], ResponseInstant],
    sessions: async_sessionmaker[AsyncSession],
    onlooker: async_sessionmaker[AsyncSession],
    owner: UserRecord,
) -> None:
    """The maintainer's open transaction changes nothing about when the identifier is readable.

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
        assert seen.visible_when_sent is True
    finally:
        release.set()
        await tick
    assert seen.identifier is not None
    assert await a_plan_of_record_exists(onlooker, owner.tenant_id) is True
    assert await visibility_of(onlooker, owner.tenant_id)(UUID(seen.identifier)) is True


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
        with contextlib.suppress(TimeoutError):
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
    requesting: asyncio.Task[httpx.Response] | None = None
    try:
        await asyncio.wait_for(inside.wait(), timeout=WINDOW)
        requesting = asyncio.create_task(
            client.post(solve_route(WEEK, immediate=True), headers=headers)
        )
        await a_backend_blocked_on_a_lock(onlooker)
        # The request is inside the index's lock wait, so releasing the rival is what turns that
        # wait into a refusal rather than a timeout.
        release.set()
        answered = await requesting
    finally:
        # Released and awaited here as well, so a wait that raises leaves neither transaction open
        # while the tenant's rows are deleted around it. Awaiting a finished task is a no-op.
        release.set()
        await rival
        if requesting is not None:
            await requesting

    assert answered.status_code == HTTPStatus.INTERNAL_SERVER_ERROR, answered.text
    assert "id" not in answered.json(), "a refused write must not answer an operation identifier"
    assert seen.identifier is None
    assert await non_terminal_solves(onlooker, owner.tenant_id) == 1, (
        "the refused write left a second non-terminal solve behind, which is what the index exists "
        "to make impossible"
    )


# ---------------------------------------------------------------------------
# 4. The forced calendar-source sync
# ---------------------------------------------------------------------------


async def test_a_forced_source_sync_answers_a_readable_operation(
    watched: tuple[httpx.AsyncClient, dict[str, str], ResponseInstant],
    onlooker: async_sessionmaker[AsyncSession],
    owner: UserRecord,
) -> None:
    """The sync route's operation is readable when its answer is sent.

    The feed behind the source is never read successfully: the address resolves nowhere, the sync
    records an unreachable feed and completes its operation all the same. That is enough here,
    because what this case reads back is the operation row, whatever the sync itself found.
    """
    client, headers, seen = watched

    added = await client.post(
        CALENDAR_SOURCES_PREFIX,
        json={
            "provider": "ics",
            "displayName": "University",
            "externalId": "https://feeds.invalid/timetable.ics",
        },
        headers=headers,
    )
    assert added.status_code == HTTPStatus.CREATED, added.text

    answered = await client.post(
        f"{CALENDAR_SOURCES_PREFIX}/{added.json()['id']}/sync", headers=headers
    )

    assert answered.status_code == HTTPStatus.OK, answered.text
    assert seen.identifier == answered.json()["id"]
    assert seen.visible_when_sent is True
    assert await visibility_of(onlooker, owner.tenant_id)(UUID(seen.identifier)) is True


# ---------------------------------------------------------------------------
# 5. The tradeoff request
# ---------------------------------------------------------------------------


# Six hours of the week left on plan and a seven-hour floor against it: short by exactly the hour
# the breach-floor concession below is offered for, built the way the concession suite builds one.
TRADEOFF_WEEK = IsoWeek.containing(datetime.now(UTC).date() + timedelta(days=60))
ON_PLAN_HOURS = 6
FLOOR_HOURS = 7


def tradeoffs_route() -> str:
    return f"{WEEKS_PREFIX}/{TRADEOFF_WEEK}/tradeoffs"


def week_instant(*, days: int = 0, hours: int = 0) -> datetime:
    monday = TRADEOFF_WEEK.monday()
    return datetime(monday.year, monday.month, monday.day, tzinfo=UTC) + timedelta(
        days=days, hours=hours
    )


async def test_a_tradeoff_request_answers_a_readable_operation(
    watched: tuple[httpx.AsyncClient, dict[str, str], ResponseInstant],
    sessions: async_sessionmaker[AsyncSession],
    onlooker: async_sessionmaker[AsyncSession],
    owner: UserRecord,
) -> None:
    """The operation a concession request answers with reads back the instant its answer lands.

    The week is made short the way a user makes one short: an off-plan declaration and an Area
    floor, so the offer the request names is one the product computed rather than one seeded at
    it. The plan of record carries one block a solve placed, because a week holding none is
    refused before any operation exists to answer with.
    """
    client, headers, seen = watched

    declared = await client.post(
        OFF_PLAN_PREFIX,
        json={
            "start": week_instant(hours=ON_PLAN_HOURS).isoformat().replace("+00:00", "Z"),
            "end": week_instant(days=7).isoformat().replace("+00:00", "Z"),
            "keepFrame": False,
        },
        headers=headers,
    )
    assert declared.status_code == HTTPStatus.CREATED, declared.text
    fitness = await client.post(
        AREAS_PREFIX, json={"name": "Fitness", "floorHours": FLOOR_HOURS}, headers=headers
    )
    assert fitness.status_code == HTTPStatus.CREATED, fitness.text
    area_id = UUID(fitness.json()["area"]["id"])

    # A second Area holds the placed block so it takes no capacity the Fitness floor competes for.
    elsewhere = await client.post(AREAS_PREFIX, json={"name": "Career2"}, headers=headers)
    assert elsewhere.status_code == HTTPStatus.CREATED, elsewhere.text
    placed = a_block(
        Origin.HABIT,
        week=TRADEOFF_WEEK,
        interval=Interval(week_instant(days=3, hours=10), week_instant(days=3, hours=11)),
        area_id=UUID(elsewhere.json()["area"]["id"]),
    )
    assert is_placed_by_the_solver(placed.origin)
    async with sessions() as session, session.begin():
        await PlanRepository(session, owner.tenant_id).append(
            document=stored_document(a_document(week=TRADEOFF_WEEK, blocks=(placed,))),
            objective_breakdown={},
            status="applied",
            reason="auto_applied_fill",
            weight_set_version=1,
            input_version=1,
            created_at=datetime.now(UTC),
        )

    answered = await client.post(
        tradeoffs_route(),
        json={"kind": AdjustmentKind.BREACH_FLOOR.value, "targetId": str(area_id)},
        headers=headers,
    )

    assert answered.status_code == HTTPStatus.ACCEPTED, answered.text
    assert seen.identifier == answered.json()["id"]
    assert seen.visible_when_sent is True
    assert await visibility_of(onlooker, owner.tenant_id)(UUID(seen.identifier)) is True


# ---------------------------------------------------------------------------
# 6. The debounced solve a pin schedules
# ---------------------------------------------------------------------------


async def seed_a_pinnable_week(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    """An Area, a task, and an applied plan holding one block of that task, for ``PINNED_WEEK``.

    The weight set the pin's pricing needs is already in force: ``declare_the_minimum`` seeds it
    for every case in this module. The plan is appended rather than solved, because what the pin
    path reads from it is the document, and the solve pipeline would add nothing to this case.
    """
    block = Block(
        iso_week=PINNED_WEEK,
        interval=Interval(
            datetime(2030, 2, 13, 14, 0, tzinfo=UTC),
            datetime(2030, 2, 13, 15, 0, tzinfo=UTC),
        ),
        binding=PIN_BINDING,
        title="Gym",
        reason=ReasonRecord((Bound(source=BindingSource.QUEUE, selected="picked"),)),
        area_id=PIN_AREA_ID,
    )
    plan = PlanDocument(
        iso_week=PINNED_WEEK,
        zone_by_date=dict.fromkeys(PINNED_WEEK.dates(), PINNED_ZONE),
        discretionary_minutes=5880,
        unallocated_minutes=5820,
        oversubscription_minutes=0,
        blocks=(block,),
    )
    async with sessions() as session, session.begin():
        area = await AreaRepository(session, tenant_id).create(
            parent_id=None,
            name="Fitness",
            pigment_index=1,
            budget_percent=Decimal(50),
            floor_hours=Decimal(1),
            created_at=PINNED_NOW,
        )
        # The plan's document names these rows by fixed identifiers, so each seeded row takes the
        # identifier the document already carries before anything references it.
        await session.execute(update(AreaRow).where(AreaRow.id == area.id).values(id=PIN_AREA_ID))
    async with sessions() as session, session.begin():
        task = await TaskRepository(session, tenant_id).create(
            area_id=PIN_AREA_ID,
            project_id=None,
            title="Gym",
            estimate_minutes=60,
            deadline=None,
            priority="normal",  # type: ignore[arg-type]
            min_chunk_minutes=15,
            splittable=False,
            created_at=PINNED_NOW,
        )
        await session.execute(update(TaskRow).where(TaskRow.id == task.id).values(id=PIN_TASK_ID))
    async with sessions() as session, session.begin():
        await PlanRepository(session, tenant_id).append(
            document=stored_document(plan),
            objective_breakdown={
                "deadline_risk": 0.0,
                "budget_deviation": 0.0,
                "time_of_day_misfit": 0.0,
                "fragmentation": 0.0,
                "context_switch": 0.0,
                "staleness": 0.0,
            },
            status="applied",
            reason="auto_applied_fill",
            weight_set_version=1,
            input_version=1,
            created_at=PINNED_NOW,
        )
        await WeekInputVersionRepository(session, tenant_id).bump(PINNED_WEEK, at=PINNED_NOW)


async def test_a_pin_answers_with_its_scheduled_solve_already_readable(
    watched: tuple[httpx.AsyncClient, dict[str, str], ResponseInstant],
    sessions: async_sessionmaker[AsyncSession],
    onlooker: async_sessionmaker[AsyncSession],
    owner: UserRecord,
) -> None:
    """A pin's answer carries the debounced solve it scheduled, and that operation reads back.

    The pin's own rows are held to the same rule as an operation answer: whatever identifier the
    response carries, the client can read it the instant it holds it. The week is far future, so
    no placement on it can be refused as past under the real clock.
    """
    client, headers, seen = watched

    zoned = await client.patch(SETTINGS_PREFIX, json={"homeZone": PINNED_ZONE}, headers=headers)
    assert zoned.status_code == HTTPStatus.OK, zoned.text
    await seed_a_pinnable_week(sessions, owner.tenant_id)

    answered = await client.post(
        pin_route(),
        json={"blockId": PIN_BLOCK_ID, "start": "2030-02-13T10:00:00Z"},
        headers=headers,
    )

    assert answered.status_code == HTTPStatus.CREATED, answered.text
    assert seen.identifier == answered.json()["operation"]["id"]
    assert seen.visible_when_sent is True
    assert await visibility_of(onlooker, owner.tenant_id)(UUID(seen.identifier)) is True


# ---------------------------------------------------------------------------
# 7. The solve a resolved conflict asks for
# ---------------------------------------------------------------------------


async def seed_an_answerable_conflict(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> str:
    """A live plan holding one block and one open overlap against its binding.

    The overlap is the second half of the block's own span, so the pair is one the detector could
    really have produced. ``moved`` is the answer the case gives, because it is the one that
    answers with a solve; ``kept-both`` asks for none and names no operation.
    """
    held = a_block_holding(BindingRef.for_habit(uuid4(), index=0), between(9, 10))
    detected = DetectedConflict(
        anchor_id=uuid4(),
        iso_week=CONFLICTED_WEEK,
        binding=held.binding,
        overlap=Interval(held.interval.start + held.interval.duration / 2, held.interval.end),
    )
    async with sessions() as session, session.begin():
        await PlanRepository(session, tenant_id).append(
            document=stored_document(a_document(blocks=(held,))),
            objective_breakdown={"budget_deviation": 1.0},
            status="applied",
            reason="auto_applied_fill",
            weight_set_version=1,
            input_version=1,
            created_at=datetime.now(UTC),
        )
        (raised,) = await PlanConflictRepository(session, tenant_id).raise_all(
            (detected,),
            at=datetime.now(UTC),
            commitments={detected.anchor_id: Commitment(series_uid=None, title="Standup")},
        )
    return str(raised.id)


async def test_a_resolved_conflict_answers_with_its_solve_already_readable(
    watched: tuple[httpx.AsyncClient, dict[str, str], ResponseInstant],
    sessions: async_sessionmaker[AsyncSession],
    onlooker: async_sessionmaker[AsyncSession],
    owner: UserRecord,
) -> None:
    """The operation the answer to a conflict carries reads back when the answer does.

    A resolution that moves the block enqueues the solve that will read the freed week, so the
    answer carries that operation under `operation`, exactly as a pin's answer does, and it is
    held to the same rule.
    """
    client, headers, seen = watched

    conflict_id = await seed_an_answerable_conflict(sessions, owner.tenant_id)
    answered = await client.post(
        f"{CONFLICTS_PREFIX}/{conflict_id}/resolve",
        json={"resolution": MOVED_RESOLUTION},
        headers=headers,
    )

    assert answered.status_code == HTTPStatus.OK, answered.text
    assert seen.identifier == answered.json()["operation"]["id"]
    assert seen.visible_when_sent is True
    assert await visibility_of(onlooker, owner.tenant_id)(UUID(seen.identifier)) is True


# ---------------------------------------------------------------------------
# 8. A commit that fails answers a fault, not an identifier
# ---------------------------------------------------------------------------


async def test_a_failing_commit_is_a_fault_rather_than_an_answer(
    watched: tuple[httpx.AsyncClient, dict[str, str], ResponseInstant],
    onlooker: async_sessionmaker[AsyncSession],
    owner: UserRecord,
) -> None:
    """When the route's own commit raises, the client gets a fault status and no identifier.

    The commit runs inside the handler now, so its failure surfaces through the api's catch-all
    before any body is sent. Under teardown ordering this was exactly the shape that could answer
    200 first and fail afterwards, which is why the failure is injected at the commit itself
    rather than arranged through database state.
    """
    client, headers, seen = watched

    async def refusing(self: AsyncSession) -> None:
        raise OperationalError("COMMIT", None, Exception("commit refused"))

    with patch.object(AsyncSession, "commit", refusing):
        answered = await client.post(solve_route(WEEK, immediate=True), headers=headers)

    assert answered.status_code == HTTPStatus.INTERNAL_SERVER_ERROR, answered.text
    assert "id" not in answered.json(), "a failed commit must not answer an operation identifier"
    assert seen.identifier is None
