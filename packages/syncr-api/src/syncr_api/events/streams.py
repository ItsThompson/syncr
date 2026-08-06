"""The stream itself: one frame per event, and a comment when the window passes with none.

Separate from the route for one reason: this is the only part of an SSE endpoint that can be driven
without a socket. A test subscribes, publishes, and reads the frames the generator yields, which is
where the heartbeat, the framing and the disappearing client actually live.

**The heartbeat is a comment rather than an event**, so a client's own handler never fires for it.
It
is what makes a dead connection detectable: a socket the peer has gone from fails on the next write,
and without a periodic write there may not be one for hours.

**The first thing sent is a heartbeat.** A response whose body has not begun is a response the
client
has not received headers for through some proxies, so the stream announces itself rather than
waiting
for the account's first event.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from syncr_api.events.config import HEARTBEAT_SECONDS
from syncr_api.events.envelopes import HEARTBEAT_FRAME, as_frame

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from syncr_api.events.envelopes import ServerEvent
    from syncr_api.events.hub import EventHub
    from syncr_domain.identifiers import TenantId


async def event_stream(
    hub: EventHub,
    tenant_id: TenantId,
    *,
    heartbeat_seconds: float = HEARTBEAT_SECONDS,
    frames: int | None = None,
) -> AsyncGenerator[str, None]:
    """The frames one connected client receives, forever, or ``frames`` of them.

    ``frames`` bounds the generator for a test and for nothing else: a real stream ends when the
    client goes away, which cancels this generator and unregisters the subscription on the way out.
    """
    async with hub.subscribe(tenant_id) as queue:
        yield HEARTBEAT_FRAME
        sent = 1
        while frames is None or sent < frames:
            yield await _next_frame(queue, heartbeat_seconds)
            sent += 1


async def _next_frame(queue: asyncio.Queue[ServerEvent], heartbeat_seconds: float) -> str:
    """The next event's frame, or a heartbeat because the window passed without one."""
    try:
        event = await asyncio.wait_for(queue.get(), timeout=heartbeat_seconds)
    except TimeoutError:
        return HEARTBEAT_FRAME
    return as_frame(event)
