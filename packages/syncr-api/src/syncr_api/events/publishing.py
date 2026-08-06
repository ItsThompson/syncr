"""The one call a producer makes to push an event, and why it never raises into the producer.

Publishing is a statement in the producer's own transaction, so it is delivered on commit and a
rolled-back write pushes nothing. What it must not do is turn a successful write into a failure: the
stream is a convenience over a read model the client can always refetch, so a channel that refuses a
notification is logged and swallowed rather than allowed to fail the solve that just landed.

That is the one place in this package where a swallowed exception is the right answer, and the
reason
is asymmetric cost: a lost push costs a client one refetch it already knows how to make, and a
raised
push costs the user their plan.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.events.channel import notify
from syncr_common.logging import get_logger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio.session import AsyncSession

    from syncr_api.events.envelopes import ServerEvent

_log = get_logger("syncr.events")


async def published(session: AsyncSession, *events: ServerEvent) -> int:
    """Publish each event on the caller's transaction. Answers how many were accepted."""
    accepted = 0
    for event in events:
        try:
            await notify(session, event)
        except Exception:  # noqa: BLE001 - a lost push must not fail the write it announced
            _log.exception("events.publish.failed", event_type=event.type)
            continue
        accepted += 1
    return accepted
