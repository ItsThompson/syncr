"""The bounds and the endpoints of the Google path, read and write.

Every value here answers something Google chooses the size of. A page is as large as the API
returns, a calendar is as large as the account made it, a sync token is as long as Google mints
it, and a rate limit is as long as Google decides to hold syncr off. None of those is a number
syncr can trust, so each has a bound, and each bound is checked where the value is read or stored.

Two of these exist because of what an oversize write cost. **The read deadline covers the WHOLE
read**, not one request: a per-operation timeout against a host that answers each page slowly bounds
nothing,
which is how an eighty-second read passed a fifteen-second timeout on the ICS path. And **the sync
token is bounded before it is stored**, because an oversize write does not fail one source, it
rolls back the transaction the whole tenant's sync pass is in.
"""

from __future__ import annotations

from typing import Final
from urllib.parse import quote

# The Calendar API's own base. Pinned rather than discovered, like the OAuth endpoints.
CALENDAR_API_BASE: Final = "https://www.googleapis.com/calendar/v3"
CALENDAR_LIST_URL: Final = f"{CALENDAR_API_BASE}/users/me/calendarList"


def events_url(calendar_id: str) -> str:
    """The events collection of one calendar, with the identifier escaped.

    A calendarId is an email-shaped opaque string the provider chose, and it reaches a URL path.
    Quoting it is what stops one with a slash addressing a different collection.
    """
    return f"{CALENDAR_API_BASE}/calendars/{quote(calendar_id, safe='')}/events"


def event_url(calendar_id: str, event_id: str) -> str:
    """One event of one calendar, with both identifiers escaped.

    The event id comes from the provider's own answer and reaches a URL path exactly as the
    calendar id does, so it is quoted for the same reason: neither is a value syncr chose.
    """
    return f"{events_url(calendar_id)}/{quote(event_id, safe='')}"


# How many events one page asks for. Google's own default is 250 and its ceiling is 2,500. The
# larger the page, the fewer round trips a full read costs and the more memory one page holds;
# 250 is the documented default and a term's timetable is a handful of pages at it.
EVENTS_PAGE_SIZE: Final = 250
# How many calendars one page of the calendar list asks for. An account has tens, not thousands.
CALENDAR_LIST_PAGE_SIZE: Final = 250

# How many pages one read may take. A full read of a busy calendar over a fortnight is one or two
# pages, and a detector read is one by construction, since it stops on the first page carrying an
# entry. This bound exists because a paginating loop over a token the server keeps returning is an
# infinite loop, and a provider bug should cost one source a stated failure rather than a worker
# tick that never ends.
MAX_PAGES: Final = 40

# How long ONE read of one calendar may take, including every page and every backoff wait. The
# deadline is around the whole loop rather than per request: the failure mode it exists for is a
# host that answers every page slowly, which no per-request timeout can see.
READ_DEADLINE_SECONDS: Final = 60.0
# How long one HTTP request may take. Inside the deadline above, so a single hung request cannot
# consume the whole budget and leave nothing for the pages after it.
REQUEST_TIMEOUT_SECONDS: Final = 20.0
# How much of one page's body is read. A 250-event page is a few hundred kilobytes; this is the
# bound that stops a page larger than the API documents exhausting the process.
MAX_PAGE_BYTES: Final = 8 * 1024 * 1024

# How many times ONE REQUEST that was rate limited or transiently refused is retried before the read
# gives up. Per request rather than per read: a rate limit on page four is the same condition as one
# on page one, and a budget shared with pagination gave the later page none. Bounded rather than
# persistent, because the worker polls again on its own interval, so a read that backed off forever
# would hold a tick to do work the next tick redoes. The aggregate bound across pages and waits is
# READ_DEADLINE_SECONDS.
MAX_ATTEMPTS: Final = 4
# The first backoff wait, doubling per attempt: 1s, 2s, 4s. Google's own guidance.
BACKOFF_BASE_SECONDS: Final = 1.0
# The ceiling on one wait. Well inside the read deadline, so the retries fit the budget rather
# than being cut off by it.
MAX_BACKOFF_SECONDS: Final = 8.0
# The most jitter added to a wait. Google's guidance is a random value up to a second, which is
# what stops a fleet of clients retrying in synchronised waves.
MAX_JITTER_SECONDS: Final = 1.0
# The longest `Retry-After` syncr will honour. A provider asking for ten minutes is asking for
# longer than a poll interval, so the read ends and the next tick starts fresh instead.
MAX_HONOURED_RETRY_AFTER_SECONDS: Final = 30.0

# Google's error codes for a rate limit, as it names them in the error body. The STATUS is not
# enough: a 403 is also what an insufficient scope answers, and telling a user their calendar is
# rate limited when their grant is too narrow sends them to the wrong repair.
RATE_LIMIT_REASONS: Final = frozenset(
    {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded"}
)

# --- The write path -----------------------------------------------------------------------------
#
# The reconciliation is bounded from outside for the same reason a read is, and the numbers differ
# because the failure modes do. A read is one paginated request; a reconciliation is one request per
# event it changes, made SEQUENTIALLY, so its cost scales with how much the plan moved.

# The budget one reconciliation is held to. A constant rather than a figure spelled into prose,
# because the deadline below is derived from it and the live suite measures against it.
PROJECTION_BUDGET_SECONDS: Final = 30.0
# How long ONE reconciliation may take, including every write and every wait. Three times the
# budget above, so exceeding the budget is visible in the duration histogram while a provider that
# has stopped answering still cannot hold the worker indefinitely: the duties on the loop are
# serial, so an unbounded write would stop the calendar poll and the horizon maintainer as well.
#
# Not a hard reading of the budget. A first projection of a full horizon is a couple of hundred
# writes and may legitimately exceed it; a reconciliation in the steady state writes only what
# moved, which is a handful.
WRITE_DEADLINE_SECONDS: Final = 3 * PROJECTION_BUDGET_SECONDS
# How long one write request may take. Inside the deadline above, so one hung request cannot consume
# the whole budget and leave nothing for the events after it.
WRITE_REQUEST_TIMEOUT_SECONDS: Final = 20.0

# How many times one MUTATING request is retried, and it is deliberately fewer than a read gets.
# A retry is only safe where the provider is known to have rejected the request without applying it:
# a rate limit is exactly that, and a 5xx or a dropped connection is not. So a write retries a rate
# limit and nothing else, and an ambiguous failure ends the reconciliation instead. That is what
# makes a duplicate event impossible by construction rather than by hoping Google deduplicates:
# the next reconciliation recomputes the diff from a fresh read of the target and converges.
MAX_WRITE_ATTEMPTS: Final = 3
