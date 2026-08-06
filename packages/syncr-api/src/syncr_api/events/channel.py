"""How an event crosses a process boundary: ``NOTIFY`` to publish, ``LISTEN`` to receive.

The api runs two uvicorn workers and the worker is a third process, so the process that produced an
event is usually not the one holding the client's socket. Postgres is the only thing all three
share.

**Publishing is a statement in the producer's own transaction**, so delivery happens on COMMIT: a
supersession that rolled back publishes nothing, and a client is never told about a write that did
not land. That is the property that makes this preferable to publishing after the commit, which is a
second thing that can fail after the first has succeeded.

**Listening needs a connection of its own, held for the process's life.** A pooled connection cannot
be used: ``LISTEN`` is per session and the pool hands sessions out and takes them back. So the
listener takes one connection outside the pool and holds it, and a dropped connection is reconnected
rather than left silent -- a listener that stopped without saying so would leave every stream on the
process permanently empty while the endpoint kept answering 200.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any, Final

from prometheus_client import Counter
from sqlalchemy import text

from syncr_api.events.config import EVENT_CHANNEL
from syncr_api.events.envelopes import as_payload, event_of_payload
from syncr_common.logging import get_logger
from syncr_common.metrics import REGISTRY

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine
    from sqlalchemy.ext.asyncio.session import AsyncSession

    from syncr_api.events.envelopes import ServerEvent
    from syncr_api.events.hub import EventHub

# How long a listener waits before reconnecting after its connection failed. Long enough that a
# Postgres restart is ridden out rather than hammered, short enough that a stream is empty for
# seconds rather than minutes.
RECONNECT_SECONDS: Final = 2.0

# A listener connection that failed and was rebuilt. Counted because the endpoint keeps answering
# 200 while the listener is down: without this the failure is visible only as streams that never
# say anything, which is indistinguishable from an idle account.
LISTENER_RECONNECTS = Counter(
    "syncr_sse_listener_reconnects_total",
    "Times the event listener's connection failed and was rebuilt.",
    registry=REGISTRY,
)

_log = get_logger("syncr.events")


async def notify(session: AsyncSession, event: ServerEvent) -> None:
    """Publish ``event`` in the caller's transaction, so it is delivered on commit."""
    await session.execute(
        text("SELECT pg_notify(:channel, :payload)"),
        {"channel": EVENT_CHANNEL, "payload": as_payload(event)},
    )


@contextlib.asynccontextmanager
async def listening(engine: AsyncEngine, hub: EventHub) -> AsyncIterator[asyncio.Task[None]]:
    """Feed ``hub`` from the channel for as long as the body runs.

    The task is cancelled on exit, which closes the connection it holds. Started as a task rather
    than awaited, because the body of the lifespan this wraps is the whole life of the process.
    """
    listener = asyncio.create_task(_listen_forever(engine, hub))
    try:
        yield listener
    finally:
        listener.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await listener


async def _listen_forever(engine: AsyncEngine, hub: EventHub) -> None:
    """Hold one listening connection, rebuilding it whenever it fails."""
    while True:
        try:
            await _listen(engine, hub)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a listener that stops is a stream that goes silent
            LISTENER_RECONNECTS.inc()
            _log.exception("events.listener.failed")
            await asyncio.sleep(RECONNECT_SECONDS)


async def _listen(engine: AsyncEngine, hub: EventHub) -> None:
    """One connection's worth of listening, until it fails or the task is cancelled."""
    raw = await engine.raw_connection()
    try:
        driver: Any = raw.driver_connection
        await driver.add_listener(EVENT_CHANNEL, _delivering(hub))
        _log.info("events.listener.started", channel=EVENT_CHANNEL)
        # Nothing to await: the driver calls the listener from its own reader task. Sleeping
        # forever holds the connection open and keeps this task cancellable.
        await asyncio.Event().wait()
    finally:
        raw.close()


def _delivering(hub: EventHub) -> Any:
    """The driver's callback, which hands one notification to the hub.

    Synchronous, because asyncpg calls it from its protocol reader: putting on a bounded queue
    without waiting is the only work done here, which is what the hub's own drop rule allows.
    """

    def deliver(
        _connection: object, _pid: int, _channel: str, payload: str
    ) -> None:  # pragma: no cover - driven through a real notification in the integration suite
        try:
            hub.publish(event_of_payload(payload))
        except Exception:  # noqa: BLE001 - a malformed payload must not kill the listener
            _log.exception("events.listener.undeliverable")

    return deliver
