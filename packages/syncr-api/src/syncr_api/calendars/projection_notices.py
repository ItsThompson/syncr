"""The banner a stopped projection raises, and the panel beside it.

A projection failure is the second most dangerous silent failure in the product, after the write
target's token expiring: the plan keeps updating, every screen looks healthy, and the copy on the
phone quietly freezes at whatever was last written. So it is raised at two volumes at once, banner
and a panel on Settings, in oxide, exactly as the token expiry is.

**Two volumes are two notices**, because a notice carries one volume: volume is where it renders.
One condition producing a banner and a panel therefore produces two values with a shared identity
root.

**The condition is the write target's own record.** ``last_error`` is set on every failed attempt
and cleared by the next success, so the notice appears and disappears with the condition rather
than with a row that has to be found and cleaned up. That is also why it does not go stale: a later
successful projection clears it, whatever the failed operation still says.

**Three things the message states**, because the failure table requires them: which operation
failed, the retry count, and that the previous projection is still in place. The first two come from
the operation, and the third is already the last sentence of every projection failure's reason.

**The staleness is a duration, not an instant.** "Your phone is showing the plan from four hours
ago" is what makes a reader act; a timestamp makes them do arithmetic. It is computed from the last
SUCCESSFUL projection, which is when the plan the phone shows was written.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from syncr_api.core.notices import BANNER, OXIDE, PANEL, Notice, NoticeAction, NoticeScope
from syncr_api.google_account.notices import stated_duration
from syncr_api.solving.config import MAX_ATTEMPTS

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_api.calendars.records import CalendarSourceRecord
    from syncr_api.core.notices import NoticeVolume
    from syncr_api.solving.records import OperationRecord

# The identity root both volumes share, so a client can recognise one condition rendered twice.
PROJECTION_STOPPED: Final = "calendar.projection-stopped"
BANNER_NOTICE_ID: Final = f"{PROJECTION_STOPPED}.banner"
PANEL_NOTICE_ID: Final = f"{PROJECTION_STOPPED}.panel"

SETTINGS_SCREEN: Final = "settings"
SETTINGS_LABEL: Final = "Open calendar settings"
SETTINGS_HREF: Final = "/settings"

TITLE: Final = "The plan is not reaching your calendar"

# What the operation was doing, in the user's terms rather than in the queue's. Named because the
# failure table requires the message to say which operation failed, and "projection" is a word from
# the code.
OPERATION: Final = "Writing the plan to your calendar"

PLAN_STILL_CORRECT: Final = "The plan itself, which is current and correct in syncr"
READING_STILL_WORKS: Final = "Reading your calendars, so the plan is still built around them"


def projection_failure_notices(
    target: CalendarSourceRecord | None,
    operation: OperationRecord | None,
    *,
    now: datetime,
) -> tuple[Notice, ...]:
    """The banner and the Settings panel a stopped projection raises, or nothing at all.

    Nothing is raised when no calendar is designated as the write target: a tenant who has not
    chosen one is not a tenant whose writes are failing, and a notice about a capability they never
    asked for would be noise on first run.
    """
    if target is None or target.sync_state.last_error is None:
        return ()
    detail = _detail(target, operation, now=now)
    since = target.sync_state.last_success_at
    return (
        _notice(BANNER_NOTICE_ID, BANNER, detail=detail, since=since, scope=None),
        _notice(
            PANEL_NOTICE_ID,
            PANEL,
            detail=detail,
            since=since,
            scope=NoticeScope(screen=SETTINGS_SCREEN, source_id=str(target.id)),
        ),
    )


def _notice(
    notice_id: str,
    volume: NoticeVolume,
    *,
    detail: str,
    since: datetime | None,
    scope: NoticeScope | None,
) -> Notice:
    return Notice(
        id=notice_id,
        volume=volume,
        pigment=OXIDE,
        title=TITLE,
        detail=detail,
        unavailable=[OPERATION],
        still_works=[PLAN_STILL_CORRECT, READING_STILL_WORKS],
        since=since,
        action=NoticeAction(label=SETTINGS_LABEL, href=SETTINGS_HREF),
        scope=scope,
    )


def _detail(
    target: CalendarSourceRecord, operation: OperationRecord | None, *, now: datetime
) -> str:
    """Which operation failed, how many attempts it has had, and how old the phone's copy is.

    The stored reason already ends with the sentence saying the previous projection is untouched, so
    it is not repeated here: one statement of that fact, written where the failure is raised.
    """
    return " ".join(
        part
        for part in (
            f"{OPERATION} {target.display_name!r} failed.",
            target.sync_state.last_error,
            _attempts(operation),
            _staleness(target, now=now),
        )
        if part
    )


def _attempts(operation: OperationRecord | None) -> str:
    """How many attempts the projection has had, so a retrying job is not silent.

    Read from the most recent projection operation. A projection enqueued after the failure would be
    a newer row on its first attempt, so this understates a retry in that window rather than
    overstating it, which is the safer direction for a count a reader compares against a clock.
    """
    if operation is None:
        return ""
    return f"This was attempt {operation.attempt} of {MAX_ATTEMPTS}."


def _staleness(target: CalendarSourceRecord, *, now: datetime) -> str:
    """How old the copy on the phone is, or that nothing has ever reached it."""
    succeeded = target.sync_state.last_success_at
    if succeeded is None:
        return "The plan has never reached this calendar, so nothing is on it yet."
    return f"Your phone is showing the plan from {stated_duration(now - succeeded)} ago."
