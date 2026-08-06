"""How an event crosses a process boundary: ``NOTIFY`` to publish, ``LISTEN`` to receive.

The api runs two uvicorn workers and the worker is a third process, so the process that produced an
event is usually not the one holding the client's socket. Postgres is the only thing all three
share.

**Publishing is a statement in the producer's own transaction**, so delivery happens on COMMIT: a
supersession that rolled back publishes nothing, and a client is never told about a write that did
not land. That is the property that makes this preferable to publishing after the commit, which is a
second thing that can fail after the first has succeeded.

## Listening takes a connection of its own, and it is not a pooled one

``LISTEN`` is per session and the pool hands sessions out and takes them back, so the listener
connects with the driver directly rather than checking a connection out. Two reasons, and each one
is enough on its own:

- A checked-out connection held for the process's life is a pool slot the process permanently loses,
  which is the kind of cost that does not show up until the pool is the thing under pressure.
- Handing a pooled connection back does not close its socket, and SQLAlchemy's reset-on-return is a
  ``ROLLBACK`` rather than ``UNLISTEN *``. So a returned connection re-enters the pool still
  listening and still carrying this callback, and a later checkout delivers every notification a
  second time into the same hub. That gets worse with every reconnect.

## The connection's own death is what ends the wait

This is the part that has to be right rather than merely written. A listener holds no loop of its
own: asyncpg calls the callback from its protocol reader, so there is nothing here to await except
the connection ceasing to work. Awaiting anything ELSE, a bare event or a sleep or a queue, means
the connection can die with no waiter to raise into, and then this function never returns, the loop
around it never re-enters, and the counter for the reconnect can never increment. The api keeps
answering 200 and keeps emitting heartbeats, because those are generated locally, so neither an
operator nor a client can tell that the stream will never carry an event again.

So the wait is on a termination listener the driver itself fires, and losing the connection is an
exception rather than a return: the loop counts it, logs it, and rebuilds. A test terminates the
backend and asserts both the counter and the delivery.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any, Final

import asyncpg
from prometheus_client import Counter
from sqlalchemy import text

from syncr_api.events.config import EVENT_CHANNEL
from syncr_api.events.envelopes import as_payload, event_of_payload
from syncr_common.logging import get_logger
from syncr_common.metrics import REGISTRY

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.engine import URL
    from sqlalchemy.ext.asyncio import AsyncEngine
    from sqlalchemy.ext.asyncio.session import AsyncSession

    from syncr_api.events.envelopes import ServerEvent
    from syncr_api.events.hub import EventHub

# How long a listener waits before reconnecting after its connection failed. Long enough that a
# Postgres restart is ridden out rather than hammered, short enough that a stream is empty for
# seconds rather than minutes.
RECONNECT_SECONDS: Final = 2.0

# How long closing a listening connection may take. A connection whose backend is already gone has
# nothing to say goodbye to, and the driver would otherwise wait out its own timeout while the
# reconnect this close is on the way to sits idle.
CLOSE_TIMEOUT_SECONDS: Final = 2.0

# What the listener's connection calls itself in ``pg_stat_activity``. Set because this is the one
# connection in the deployment that is idle by design: an operator looking at a database with a
# permanently idle session needs to be able to tell the event listener from something stuck, and it
# is also how a test finds the backend it means to kill.
LISTENER_APPLICATION_NAME: Final = "syncr-event-listener"

# A listener connection that failed and was rebuilt. Counted because the endpoint keeps answering
# 200 while the listener is down: without this the failure is visible only as streams that never
# say anything, which is indistinguishable from an idle account.
LISTENER_RECONNECTS = Counter(
    "syncr_sse_listener_reconnects_total",
    "Times the event listener's connection failed and was rebuilt.",
    registry=REGISTRY,
)

_log = get_logger("syncr.events")


class ListenerConnectionLost(Exception):
    """The listening connection stopped working, so the channel has to be re-established."""


async def notify(session: AsyncSession, event: ServerEvent) -> None:
    """Publish ``event`` in the caller's transaction, so it is delivered on commit."""
    await session.execute(
        text("SELECT pg_notify(:channel, :payload)"),
        {"channel": EVENT_CHANNEL, "payload": as_payload(event)},
    )


@contextlib.asynccontextmanager
async def listening(
    engine: AsyncEngine, hub: EventHub, *, reconnect_seconds: float = RECONNECT_SECONDS
) -> AsyncIterator[asyncio.Task[None]]:
    """Feed ``hub`` from the channel for as long as the body runs.

    The engine is read for its URL and for nothing else: the listener does not use its pool. Started
    as a task rather than awaited, because the body of the lifespan this wraps is the whole life of
    the process, and cancelled on exit, which closes the connection it holds.
    """
    listener = asyncio.create_task(
        _listen_forever(engine.url, hub, reconnect_seconds=reconnect_seconds)
    )
    try:
        yield listener
    finally:
        listener.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await listener


async def _listen_forever(url: URL, hub: EventHub, *, reconnect_seconds: float) -> None:
    """Hold one listening connection, rebuilding it whenever it stops working."""
    while True:
        try:
            await _listen(url, hub)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a listener that stops is a stream that goes silent
            LISTENER_RECONNECTS.inc()
            _log.exception("events.listener.failed")
            await asyncio.sleep(reconnect_seconds)


async def _listen(url: URL, hub: EventHub) -> None:
    """One connection's worth of listening, until it stops working or the task is cancelled.

    Raises :class:`ListenerConnectionLost` when the connection dies, which is what makes the loop
    above rebuild rather than sit on a dead socket forever.
    """
    connection = await asyncpg.connect(
        driver_url(url), server_settings={"application_name": LISTENER_APPLICATION_NAME}
    )
    lost = asyncio.Event()
    try:
        connection.add_termination_listener(lambda _connection: lost.set())
        await connection.add_listener(EVENT_CHANNEL, _delivering(hub))
        _log.info("events.listener.started", channel=EVENT_CHANNEL)
        await lost.wait()
        raise ListenerConnectionLost(
            f"the listening connection on {EVENT_CHANNEL!r} was terminated, so every stream on "
            "this process would go silent without a reconnect"
        )
    finally:
        # Its own socket rather than a pool slot, so closing it really closes it. Bounded, because a
        # connection whose backend is already gone would otherwise wait out the driver's timeout.
        with contextlib.suppress(Exception):
            await asyncio.wait_for(connection.close(), timeout=CLOSE_TIMEOUT_SECONDS)


def driver_url(url: URL) -> str:
    """The engine's URL as the driver takes it, with SQLAlchemy's dialect name removed.

    ``postgresql+asyncpg://`` is a SQLAlchemy spelling and asyncpg refuses it. One conversion, here,
    so the listener and the pool cannot end up pointed at two different databases.
    """
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def _delivering(hub: EventHub) -> Any:
    """The driver's callback, which hands one notification to the hub.

    Synchronous, because asyncpg calls it from its protocol reader: putting on a bounded queue
    without waiting is the only work done here, which is what the hub's own drop rule allows.
    """

    def deliver(_connection: object, _pid: int, _channel: str, payload: str) -> None:
        try:
            hub.publish(event_of_payload(payload))
        except Exception:  # noqa: BLE001 - a malformed payload must not kill the listener
            _log.exception("events.listener.undeliverable")

    return deliver
