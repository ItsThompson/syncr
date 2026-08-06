"""The one call a producer makes to push an event, and what its swallow can and cannot absorb.

Publishing is a statement in the producer's own transaction, so it is delivered on commit and a
rolled-back write pushes nothing. What it must not do is turn a successful write into a failure: the
stream is a convenience over a read model the client can always refetch, so an event the channel
refuses is logged and dropped rather than allowed to fail the solve that just landed.

**The swallow is narrowed to the one failure it can absorb**, which is a payload too large for a
notification. That refusal happens in Python, before any statement runs, so the caller's transaction
is untouched and dropping the event really does leave the write intact.

**A failure of the ``pg_notify`` STATEMENT is not absorbable, so it is not caught.** A failed
statement aborts the caller's transaction, and every later statement and the commit fail with it:
swallowing it would convert an immediate, attributable failure into an ``InFailedSqlTransaction`` at
commit time in the producer's own code, with the real cause visible only in a log line. So it
surfaces where it happened. The asymmetry that justifies the narrow swallow does not apply to it,
because the write it would be protecting is already lost.

The newly wired notice is the one event whose payload carries free text, so it is the only one that
can approach the bound at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.events.channel import notify
from syncr_api.events.envelopes import EventTooLarge
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
        except EventTooLarge:
            _log.exception("events.publish.refused", event_type=event.type)
            continue
        accepted += 1
    return accepted
