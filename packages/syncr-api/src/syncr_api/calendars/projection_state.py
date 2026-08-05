"""The write target's own record of what the projection did, in the fields a source already has.

An anchor source records every read attempt in its sync state, and the write target records every
WRITE attempt in exactly the same four fields. That is not an overload: the questions are the same
ones. ``last_success_at`` is when the plan last reached the phone, ``last_attempt_at`` is when syncr
last tried, ``last_error`` is why it stopped, and ``attempts`` is how many provider calls the last
attempt cost. Staleness is the difference between the first two, which is what the banner states.

**Written on every attempt, successful or not.** That is invariant CS4 and it is what makes the
failure visible: a write target whose last attempt is recent and whose last success is not is a
target that is failing, and nothing else can tell that from one nobody has projected to yet.

**The read-side counts are left alone.** ``events_read``, ``anchors_current``, ``cursor`` and the
rejections describe reading a calendar, and the write target is never read as an anchor source --
the repository's own query excludes it by role -- so they stay at whatever they were. Filling them
with write counts would give one column two meanings that no reader could tell apart.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from syncr_api.calendars.projection_errors import PREVIOUS_PROJECTION_STANDS
from syncr_api.calendars.sync_state import stated_failure

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_api.calendars.records import SyncStateRecord


def recorded_projection(
    previous: SyncStateRecord, *, at: datetime, attempts: int = 1
) -> SyncStateRecord:
    """The state after a reconciliation that made the target match the plan.

    The error is cleared, which is what makes the banner go away by itself: the condition it reports
    is "the plan is not reaching the phone", and it has stopped holding.
    """
    return replace(
        previous, last_success_at=at, last_attempt_at=at, last_error=None, attempts=attempts
    )


def recorded_projection_failure(
    previous: SyncStateRecord, *, at: datetime, reason: str, attempts: int = 1
) -> SyncStateRecord:
    """The state after a reconciliation that did not finish, or was refused before it started.

    ``last_success_at`` is kept, because it did not become untrue: it is when the projection the
    phone is still showing was written, and the banner states how old that makes the phone.
    """
    return replace(
        previous,
        last_attempt_at=at,
        last_error=stated_failure(reason, surviving=PREVIOUS_PROJECTION_STANDS),
        attempts=attempts,
    )
