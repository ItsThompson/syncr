"""The per-process fan-out: who is connected, and what each of them is given.

One hub per api process, holding one bounded queue per connected stream. A publish puts the event on
every queue belonging to the event's own tenant, and on no other, so two clients on one stream from
two accounts cannot see each other's events.

**A subscriber that has stopped reading is dropped rather than waited for.** Its queue is bounded,
and
a full queue means the socket is gone or the client is not consuming: holding a growing queue for it
would trade one dead connection for unbounded memory, and a client that reconnects refetches the
week
anyway. The drop is counted, because a stream silently losing events is the failure mode a push
transport has.

**Publishing never blocks and never raises into the caller.** A hub with no subscribers is the
ordinary state -- nobody has a tab open -- so a publish is a no-op rather than an error, and one
subscriber's full queue cannot stop another's delivery.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from prometheus_client import Counter, Gauge

from syncr_api.events.config import SUBSCRIBER_BACKLOG
from syncr_common.logging import get_logger
from syncr_common.metrics import REGISTRY

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syncr_api.events.envelopes import ServerEvent
    from syncr_domain.identifiers import TenantId

SSE_CONNECTIONS = Gauge(
    "syncr_sse_connections",
    "Event streams currently open on this process.",
    registry=REGISTRY,
)

# A stream whose backlog filled, which means the client stopped reading. Counted rather than only
# logged: a push transport that quietly drops is indistinguishable from an idle one, and the
# client's own refetch hides it from the user.
EVENTS_DROPPED = Counter(
    "syncr_sse_events_dropped_total",
    "Events discarded because a stream's backlog was full.",
    registry=REGISTRY,
)

_log = get_logger("syncr.events")


class EventHub:
    """The streams open on this process, and the events each of them is owed."""

    def __init__(self, *, backlog: int = SUBSCRIBER_BACKLOG) -> None:
        self._backlog = backlog
        self._subscribers: dict[TenantId, set[asyncio.Queue[ServerEvent]]] = {}

    @property
    def connections(self) -> int:
        """How many streams are open, which is what the gauge reports."""
        return sum(len(queues) for queues in self._subscribers.values())

    @contextlib.asynccontextmanager
    async def subscribe(self, tenant_id: TenantId) -> AsyncIterator[asyncio.Queue[ServerEvent]]:
        """A queue this tenant's events arrive on, registered for as long as the body runs.

        Unregistered on exit whether the body returned or raised, so a client that disappeared
        mid-solve leaves nothing behind: a generator abandoned by a closed connection is cancelled,
        which is a raise through the yield.
        """
        queue: asyncio.Queue[ServerEvent] = asyncio.Queue(maxsize=self._backlog)
        self._subscribers.setdefault(tenant_id, set()).add(queue)
        SSE_CONNECTIONS.set(self.connections)
        _log.info("events.stream.opened", connections=self.connections)
        try:
            yield queue
        finally:
            self._subscribers.get(tenant_id, set()).discard(queue)
            if not self._subscribers.get(tenant_id):
                self._subscribers.pop(tenant_id, None)
            SSE_CONNECTIONS.set(self.connections)
            _log.info("events.stream.closed", connections=self.connections)

    def publish(self, event: ServerEvent) -> int:
        """Put ``event`` on every stream of its own tenant. Answers how many received it."""
        delivered = 0
        for queue in tuple(self._subscribers.get(event.tenant_id, ())):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                EVENTS_DROPPED.inc()
                _log.warning("events.stream.backlog_full", event_type=event.type)
                continue
            delivered += 1
        return delivered
