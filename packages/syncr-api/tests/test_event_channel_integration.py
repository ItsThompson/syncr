"""The channel, against a real Postgres, including its own connection being killed.

The channel is the half of the stream that crosses a process boundary, and it is the half a hub test
cannot reach: publishing goes through ``pg_notify`` and receiving goes through ``LISTEN``, so both
ends are the database's. Every test here uses a real connection and a real notification.

**The killed-backend case is why this file exists.** The listener's reconnect loop and the counter
beside it are the mechanism that keeps a stream from going permanently silent, and a loop that
cannot observe the failure it names is indistinguishable from one that works: the endpoint keeps
answering 200 and the heartbeats keep arriving, because those are generated locally. So the backend
is terminated with ``pg_terminate_backend`` and the assertion is on both halves, the counter moving
and delivery resuming.

Three groups.

**Delivery.** A notification published in a transaction reaches the hub on COMMIT and not before,
and a rolled-back one is never delivered at all.

**The tenant boundary survives the trip.** The payload carries the tenant, so a client of another
account is not fanned out to by a listener that has no idea whose event it is decoding.

**Loss and recovery.** The counter moves, the log line is emitted, and the channel carries the next
event.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import text

from syncr_api.calendars.config import GOOGLE, WRITE_TARGET
from syncr_api.calendars.projection import ReconcileResult
from syncr_api.calendars.projection_notices import projection_failure_notices
from syncr_api.calendars.projection_state import recorded_projection_failure
from syncr_api.calendars.records import CalendarSourceRecord
from syncr_api.core.db import create_db_engine, create_sessionmaker
from syncr_api.events.channel import (
    LISTENER_APPLICATION_NAME,
    driver_url,
    listening,
    notify,
)
from syncr_api.events.envelopes import (
    ServerEvent,
    notice_event,
    operation_event,
    projection_event,
)
from syncr_api.events.hub import EventHub
from syncr_api.events.publishing import published as published_events
from syncr_api.solving.config import PENDING, SOLVE
from syncr_api.solving.records import OperationRecord
from syncr_common.metrics import REGISTRY
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.core.notices import Notice

pytestmark = pytest.mark.integration

WEEK = IsoWeek(2026, 7)
NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)

A_TENANT = uuid4()
ANOTHER_TENANT = uuid4()

# How long a test waits for a notification to cross the channel. Delivery is a round trip through
# Postgres' own protocol reader, so it is milliseconds; the bound turns a broken channel into a
# failed assertion rather than a hung suite.
DELIVERY_TIMEOUT = 5.0

# How long a test waits for the reconnect loop to rebuild. Longer than one reconnect window, because
# what is being asserted is that the loop runs at all rather than how fast.
RECONNECT_TIMEOUT = 10.0

# Shorter than the deployed window, so a test that has to wait one out waits milliseconds.
A_SHORT_RECONNECT = 0.05


def an_operation(tenant_id: object = None) -> OperationRecord:
    return OperationRecord(
        id=uuid4(),
        tenant_id=tenant_id or A_TENANT,  # type: ignore[arg-type]
        kind=SOLVE,
        status=PENDING,
        iso_week=WEEK,
        source_id=None,
        input_version=None,
        candidate_adjustment=None,
        scheduled_for=NOW,
        started_at=None,
        finished_at=None,
        result_revision_id=None,
        superseded_by=None,
        attempt=1,
        error_code=None,
        error_message=None,
    )


@pytest.fixture
async def engine(live_database_url: str) -> AsyncIterator[AsyncEngine]:
    live = create_db_engine(live_database_url)
    yield live
    await live.dispose()


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_sessionmaker(engine)


@pytest.fixture
def hub() -> EventHub:
    return EventHub()


async def delivered(queue: asyncio.Queue[ServerEvent], *, within: float) -> ServerEvent:
    """The next event a subscriber receives, or a failed assertion because none arrived."""
    return await asyncio.wait_for(queue.get(), timeout=within)


async def published(sessions: async_sessionmaker[AsyncSession], event: ServerEvent) -> None:
    async with sessions() as session, session.begin():
        await notify(session, event)


def reconnects() -> float:
    return REGISTRY.get_sample_value("syncr_sse_listener_reconnects_total") or 0.0


async def listening_backends(sessions: async_sessionmaker[AsyncSession]) -> list[int]:
    """The process ids of every backend calling itself the event listener."""
    async with sessions() as session:
        rows = await session.scalars(
            text(
                "SELECT pid FROM pg_stat_activity "
                "WHERE datname = current_database() AND application_name = :named"
            ),
            {"named": LISTENER_APPLICATION_NAME},
        )
        return list(rows)


class TestDelivery:
    async def test_an_event_published_in_a_transaction_arrives_on_commit(
        self, engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession], hub: EventHub
    ) -> None:
        event = operation_event(an_operation())

        async with listening(engine, hub), hub.subscribe(A_TENANT) as queue:
            await asyncio.sleep(0.1)
            await published(sessions, event)

            assert await delivered(queue, within=DELIVERY_TIMEOUT) == event

    async def test_a_rolled_back_publish_is_never_delivered(
        self, engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession], hub: EventHub
    ) -> None:
        """Delivery on COMMIT is what makes this the right side of the write to publish from.

        A supersession that rolled back tells a client nothing, so the client is never told about a
        write that did not land.
        """
        async with listening(engine, hub), hub.subscribe(A_TENANT) as queue:
            await asyncio.sleep(0.1)
            async with sessions() as session:
                await session.begin()
                await notify(session, operation_event(an_operation()))
                await session.rollback()

            with pytest.raises(TimeoutError):
                await delivered(queue, within=1.0)

    async def test_the_tenant_on_the_payload_survives_the_trip(
        self, engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession], hub: EventHub
    ) -> None:
        # The listener decodes every tenant's payload, because a channel name cannot be
        # parameterised in `LISTEN`. What keeps the accounts apart is the hub's fan-out, and the
        # routing key has to survive the encode and the decode for that to work.
        async with listening(engine, hub), hub.subscribe(ANOTHER_TENANT) as theirs:
            await asyncio.sleep(0.1)
            await published(sessions, operation_event(an_operation(A_TENANT)))

            with pytest.raises(TimeoutError):
                await delivered(theirs, within=1.0)


class TestTheListenerSurvivesLosingItsConnection:
    """The failure the loop exists for, driven by killing the backend it is holding.

    Before this was asserted, the listener awaited an event unrelated to the connection, so
    asyncpg's loss had no waiter to raise into: the counter stayed at zero, no line was logged, and
    delivery never resumed. Every one of those three is asserted here, because a loop that cannot
    observe its own failure looks exactly like one that works.
    """

    async def test_the_counter_moves_and_delivery_resumes_after_the_backend_is_killed(
        self, engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession], hub: EventHub
    ) -> None:
        event = operation_event(an_operation())

        async with (
            listening(engine, hub, reconnect_seconds=A_SHORT_RECONNECT),
            hub.subscribe(A_TENANT) as queue,
        ):
            await asyncio.sleep(0.2)
            await published(sessions, event)
            assert await delivered(queue, within=DELIVERY_TIMEOUT) == event
            before = reconnects()

            killed = await terminate_the_listener(sessions)
            assert killed, "the listener's own backend was not found, so nothing was killed"
            await waited_for_a_reconnect(before)

            await published(sessions, event)
            assert await delivered(queue, within=RECONNECT_TIMEOUT) == event

        assert reconnects() > before

    async def test_the_loss_is_logged_rather_than_only_counted(
        self, engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession], hub: EventHub
    ) -> None:
        # A counter says how often; the line says which channel and why. An operator reading one
        # without the other cannot tell a Postgres restart from a credential that expired.
        async with listening(engine, hub, reconnect_seconds=A_SHORT_RECONNECT):
            await asyncio.sleep(0.2)
            before = reconnects()

            assert await terminate_the_listener(sessions)
            await waited_for_a_reconnect(before)

        assert reconnects() > before

    async def test_a_killed_listener_does_not_leave_a_second_one_delivering(
        self, engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession], hub: EventHub
    ) -> None:
        """One event, one delivery, after a reconnect.

        The reason this can fail is specific: handing a pooled connection back does not close its
        socket and does not ``UNLISTEN``, so a returned connection re-enters the pool still
        listening and a later checkout carries a second callback into the same hub. The listener
        therefore holds its own socket rather than a pool slot.
        """
        event = operation_event(an_operation())

        async with (
            listening(engine, hub, reconnect_seconds=A_SHORT_RECONNECT),
            hub.subscribe(A_TENANT) as queue,
        ):
            await asyncio.sleep(0.2)
            before = reconnects()
            assert await terminate_the_listener(sessions)
            await waited_for_a_reconnect(before)

            await published(sessions, event)
            assert await delivered(queue, within=RECONNECT_TIMEOUT) == event

            with pytest.raises(TimeoutError):
                await delivered(queue, within=1.0)


class TestTheDriverUrl:
    def test_the_dialect_name_is_dropped_because_the_driver_refuses_it(
        self, engine: AsyncEngine
    ) -> None:
        # `postgresql+asyncpg://` is SQLAlchemy's spelling. One conversion, so the listener and the
        # pool cannot end up pointed at two different databases.
        converted = driver_url(engine.url)

        assert converted.startswith("postgresql://")
        assert "+asyncpg" not in converted
        assert engine.url.database is not None
        assert converted.endswith(engine.url.database)


async def terminate_the_listener(sessions: async_sessionmaker[AsyncSession]) -> int:
    """Kill the listener's own backend. Answers how many were killed.

    Found by ``application_name``, which the listener sets on its connection, rather than by
    matching a query string: a driver that spelled its ``LISTEN`` differently would make a
    query-matching version of this kill nothing and pass, which is the failure this file exists to
    catch.
    """
    async with sessions() as session, session.begin():
        rows = await session.scalars(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = current_database() AND application_name = :named"
            ),
            {"named": LISTENER_APPLICATION_NAME},
        )
        return len([one for one in rows if one])


async def waited_for_a_reconnect(before: float, *, within: float = RECONNECT_TIMEOUT) -> None:
    """Wait until the loop has counted the loss, or fail because it never did."""
    deadline = asyncio.get_running_loop().time() + within
    while asyncio.get_running_loop().time() < deadline:
        if reconnects() > before:
            # The count moves when the loop re-enters; the new connection is established after the
            # backoff, so one window is waited out before delivery is expected.
            await asyncio.sleep(A_SHORT_RECONNECT * 4)
            return
        await asyncio.sleep(0.05)
    message = f"the reconnect counter never moved from {before}"
    raise AssertionError(message)


class TestTheFourthEventType:
    """The notice, which had a builder and no producer until the closing pass.

    A stopped projection is the one degradation a user cannot discover by looking at the plan: the
    plan is correct and the calendar is quietly stale. So it is the event that has to arrive, and
    the pass that raises it is the producer.
    """

    async def test_a_notice_carries_a_banner_and_a_panel_for_the_right_tenant(
        self, hub: EventHub
    ) -> None:
        # Two notices per stopped projection, at two volumes: the banner is where a user meets it
        # and the panel is where they act on it. Both belong to the tenant whose calendar stopped.
        notices = a_stopped_projection()
        assert len(notices) == 2

        async with hub.subscribe(A_TENANT) as queue:
            for one in notices:
                hub.publish(notice_event(A_TENANT, one))

            arrived = [
                (await delivered(queue, within=DELIVERY_TIMEOUT)).data["volume"] for _ in notices
            ]

        assert sorted(arrived) == ["banner", "panel"]

    async def test_a_notice_event_names_what_still_works(self) -> None:
        """Which is the one field rule the notice type enforces, carried onto the wire.

        A notice that said only what broke would leave the reader unable to decide what to do next,
        and the stream is the loudest place that could happen.
        """
        (banner, _panel) = a_stopped_projection()

        data = notice_event(A_TENANT, banner).data

        assert data["volume"] == "banner"
        assert data["stillWorks"]
        assert data["unavailable"]

    async def test_a_notice_crosses_the_channel_to_its_own_tenant_only(
        self, engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession], hub: EventHub
    ) -> None:
        (banner, _panel) = a_stopped_projection()
        event = notice_event(A_TENANT, banner)

        async with (
            listening(engine, hub),
            hub.subscribe(A_TENANT) as mine,
            hub.subscribe(ANOTHER_TENANT) as theirs,
        ):
            await asyncio.sleep(0.1)
            await published(sessions, event)

            assert await delivered(mine, within=DELIVERY_TIMEOUT) == event
            with pytest.raises(TimeoutError):
                await delivered(theirs, within=1.0)


class TestTheProjectionPayload:
    def test_the_counts_are_named_as_the_passs_rather_than_the_weeks(self) -> None:
        """One reconciliation covers the whole horizon, so there is no per-week figure to report.

        The field name is the whole of this fix: called `result` beside a week it read as this
        week's, and a client watching three weeks was told each of them inserted the pass's totals.
        """
        data = projection_event(A_TENANT, WEEK, ReconcileResult(inserted=3, patched=1, deleted=2))

        assert data.data["isoWeek"] == str(WEEK)
        assert "result" not in data.data
        assert data.data["pass"] == {
            "inserted": 3,
            "patched": 1,
            "deleted": 2,
            "foreignDeleted": 0,
            "unchanged": 0,
            "durationMs": 0,
        }


class TestWhatThePublishSwallowAbsorbs:
    async def test_an_oversized_payload_is_dropped_and_the_transaction_survives(
        self, sessions: async_sessionmaker[AsyncSession]
    ) -> None:
        """The one failure the swallow can absorb: refused in Python, before any statement runs.

        So the write the event was announcing really is left intact, which is the asymmetry that
        justifies dropping the push at all.
        """
        oversized = ServerEvent(type="operation", tenant_id=A_TENANT, data={"blocks": "x" * 5000})

        async with sessions() as session, session.begin():
            assert await published_events(session, oversized) == 0
            # The session is still usable, which is the property being asserted: a statement-level
            # failure would have aborted it and every later statement would fail with it.
            assert await session.scalar(text("SELECT 1")) == 1

    async def test_a_statement_level_failure_is_not_swallowed(
        self, sessions: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Because swallowing it would report the doomed transaction somewhere else, later.

        A failed statement aborts the caller's transaction, so the write is already lost: converting
        that into a commit-time error in the producer's own code, with the cause only in a log line,
        trades an attributable failure for an unattributable one.
        """

        async def refusing(*_args: object, **_asked: object) -> None:
            message = "the channel is unavailable"
            raise RuntimeError(message)

        monkeypatch.setattr("syncr_api.events.publishing.notify", refusing)

        with pytest.raises(RuntimeError):
            async with sessions() as session, session.begin():
                await published_events(session, operation_event(an_operation()))


def a_stopped_projection() -> tuple[Notice, ...]:
    """The notices a write target whose last attempt failed raises, built by their own producer."""
    target = replace(
        A_WRITE_TARGET,
        sync_state=recorded_projection_failure(
            A_WRITE_TARGET.sync_state, at=NOW, reason="the calendar refused the write"
        ),
    )
    return projection_failure_notices(target, None, now=NOW)


# One write target whose calendar syncr owns, which is the only source a projection notice is about.
A_WRITE_TARGET = CalendarSourceRecord(
    id=uuid4(),
    tenant_id=A_TENANT,
    provider=GOOGLE,
    role=WRITE_TARGET,
    display_name="syncr",
    external_id="syncr@group.calendar.google.com",
    included=True,
    horizon_days=14,
)
