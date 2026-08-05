"""The sync state one attempt produces, from the state before it and what the attempt did.

Every rule about sync state is here, and each one exists because the alternative loses
something the user needs:

**Every attempt is recorded, successful or not.** ``last_attempt_at`` moves on every call and
``last_success_at`` only on a success, so staleness is the difference between them. Writing
only on success would make a feed that has failed for a week indistinguishable from one
nobody has polled.

**A failure retains the anchor count and the cursor.** The anchors read on the last success
are still the best occupancy syncr has, so they are retained and marked possibly stale rather
than cleared. Dropping the cursor would also make the next poll
unconditional, so one outage would cost a full reparse.

**A parse that rejected events is still a success.** A feed that half-works must read as
neither fully working nor fully broken, so the rejections are recorded next to a moved
``last_success_at`` rather than as an error.

**An unchanged feed is a success that changed nothing.** ``304`` means the last parse still
stands, so the counts and the rejections carry forward untouched and only the attempt moves. A
provider that answers "nothing changed since your cursor" is the same case by a different
mechanism, and it takes the same constructor: what the source holds is what the last read found.

**A failure's message names the surviving capability.** A notice that says only what broke
leaves the user unable to decide what to do next, so the retained anchors are stated in the
message the panel renders rather than left for the reader to infer.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from syncr_api.calendars.config import LAST_ERROR_MAX_LENGTH
from syncr_api.calendars.records import SyncStateRecord

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_api.calendars.events import FetchOutcome

RETAINED_NOTICE = (
    "The anchors already read from this feed are retained and marked possibly stale, so "
    "the plan still respects them."
)


def recorded_success(
    outcome: FetchOutcome,
    *,
    at: datetime,
    cursor: str | None,
    attempts: int = 1,
    resync_reason: str | None = None,
) -> SyncStateRecord:
    """The state after an attempt that read the feed, whatever it rejected.

    Nothing carries forward from the previous state, because this parse replaced it wholesale:
    the counts and the rejections describe the feed as it is now.

    ``anchors_current`` is the count of events this parse produced. The anchor reconciler
    replaces it with its own delta once anchors exist; until then the event count is the
    honest answer to "how much occupancy did this feed contribute", and it is the number the
    panel reports progress with.
    """
    return SyncStateRecord(
        last_success_at=at,
        last_attempt_at=at,
        last_error=None,
        cursor=cursor,
        events_read=outcome.events_read,
        anchors_current=len(outcome.events),
        rejections=outcome.rejected,
        attempts=attempts,
        resync_reason=resync_reason,
    )


def recorded_unchanged(
    previous: SyncStateRecord, *, at: datetime, cursor: str | None, attempts: int = 1
) -> SyncStateRecord:
    """The state after a ``304``: a successful attempt that reparsed nothing.

    Every count and every rejection carries forward, because they describe the parse that is
    still current. Zeroing them would report a source that answered correctly as one holding
    no occupancy at all.
    """
    return replace(
        previous,
        last_success_at=at,
        last_attempt_at=at,
        last_error=None,
        cursor=cursor,
        attempts=attempts,
    )


def recorded_failure(
    previous: SyncStateRecord, *, at: datetime, reason: str, attempts: int = 1
) -> SyncStateRecord:
    """The state after an attempt that could not read the feed.

    ``last_success_at``, the counts, the rejections, and the cursor are all kept: none of them
    became untrue because a poll failed, and the panel states when the feed last succeeded.
    """
    return replace(
        previous, last_attempt_at=at, last_error=stated_failure(reason), attempts=attempts
    )


def stated_failure(reason: str, *, surviving: str = RETAINED_NOTICE) -> str:
    """The failure as the panel renders it: what broke, then what still works.

    Bounded to the column's width from the end of the reason rather than the end of the notice, so
    a publisher's long message cannot push out the sentence that says what survived.

    ``surviving`` is an argument because the write target's own attempts are recorded in a sync
    state too, and what survives a failed projection is not what survives a failed read: the
    anchors are irrelevant there and the previous projection is the thing that still stands.
    One implementation of the bound, two sentences.
    """
    room = LAST_ERROR_MAX_LENGTH - len(surviving) - 1
    return f"{reason[:room].rstrip()} {surviving}"
