"""The source cursor, when the provider is Google: a sync token, prefixed and bounded.

One column holds the cursor for every provider, so the value says which kind it is. The ICS adapter
writes ``etag:`` or ``modified:``; this writes ``sync:``. That is not decoration: the ICS fetcher
sends an unprefixed cursor as no conditional header at all rather than guessing, and a Google token
sent as an ``If-None-Match`` would make a conditional request that silently stops being conditional.

**The bound is the important half.** A sync token is a value Google chooses the length of, and it
reaches a column with a width. Ticket 11 measured what an oversize write costs on this exact column:
it raises at the flush, which rolls back the whole tenant's sync pass, so every sibling source loses
the sync state it had already earned and the failure is attributable to no source at all. Dropping
the token instead costs one full read on the next poll, and the sync state states why.
"""

from __future__ import annotations

from typing import Final

from syncr_api.calendars.config import CURSOR_MAX_LENGTH

# Which kind of cursor the value is. Read by this module and by nothing else: the ICS fetcher's
# rule is "a prefix I do not recognise is not a validator I can send", which is what makes adding a
# provider safe.
CURSOR_PREFIX: Final = "sync:"


def sync_token_of(cursor: str | None) -> str | None:
    """The sync token this cursor holds, or ``None`` when it holds none.

    A cursor written by another provider's adapter reads as no token rather than as a token, so a
    source whose provider changed reads fully once instead of sending Google an ``ETag``.
    """
    if cursor is None or not cursor.startswith(CURSOR_PREFIX):
        return None
    return cursor.removeprefix(CURSOR_PREFIX) or None


def bounded_cursor(sync_token: str | None) -> str | None:
    """The cursor to store for ``sync_token``, or ``None`` when the column cannot hold it.

    Truncating is not an option: a truncated sync token is not an older sync token, it is a value
    Google would refuse with a 410 on every poll, which turns one dropped token into a permanent
    full read plus a wasted call.
    """
    if not sync_token:
        return None
    cursor = f"{CURSOR_PREFIX}{sync_token}"
    return cursor if len(cursor) <= CURSOR_MAX_LENGTH else None
