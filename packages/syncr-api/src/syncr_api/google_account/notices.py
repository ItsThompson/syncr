"""The loudest non-blocking notice in the product, and the arithmetic behind its first sentence.

Write-target expiry is the most dangerous silent failure syncr has. Reading keeps working, every
screen looks healthy, and the plan quietly stops reaching the phone, which deletes the one thing
the write target exists for. So it is raised at two volumes at once, banner and a panel on
Settings, and the volume is not negotiable.

**Two volumes are two notices.** A notice carries one volume, because volume is where it renders.
One condition producing a banner and a panel therefore produces two values with a shared
identity root, rather than a notice with a list of places to appear.

**The first sentence is a duration, not an instant.** "Writes have been failing for four days"
is what makes the reader act; "since 2026-02-05T09:14:22Z" makes them do arithmetic. The duration
is computed from when failing STARTED, which is why the credential stores that instant rather
than the last attempt's.

**Every sentence names the surviving capability.** Reading anchors still works, so the plan is
still correct and still solvable: what stopped is the projection. A notice that said only
"Google authorization expired" would leave the reader unsure whether their plan was lost.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from syncr_api.core.notices import BANNER, OXIDE, PANEL, Notice, NoticeAction, NoticeScope

if TYPE_CHECKING:
    from datetime import datetime, timedelta

    from syncr_api.core.notices import NoticeVolume
    from syncr_api.google_account.records import GoogleCredentialRecord

# The identity root both volumes share, so a client can recognise one condition rendered twice.
WRITE_TARGET_EXPIRED: Final = "google.write-target-expired"
BANNER_NOTICE_ID: Final = f"{WRITE_TARGET_EXPIRED}.banner"
PANEL_NOTICE_ID: Final = f"{WRITE_TARGET_EXPIRED}.panel"

SETTINGS_SCREEN: Final = "settings"
RECONNECT_LABEL: Final = "Reconnect Google"
RECONNECT_HREF: Final = "/settings"

TITLE: Final = "The plan is not reaching your calendar"

READING_STILL_WORKS: Final = "Reading your calendars, so the plan is still built around them"
PLAN_STILL_CORRECT: Final = "Every other part of syncr, including solving and the week you see"
WRITING_UNAVAILABLE: Final = "Writing the plan to your Google calendar"

_MINUTE: Final = 60
_HOUR: Final = 60 * _MINUTE
_DAY: Final = 24 * _HOUR


def write_target_expiry_notices(
    credential: GoogleCredentialRecord | None, *, now: datetime
) -> tuple[Notice, ...]:
    """The banner and the Settings panel this condition raises, or nothing at all.

    Nothing is raised when no account is connected: a tenant that never connected Google is not
    a tenant whose writes are failing, and a notice about a capability they never had would be
    noise on first run.
    """
    if credential is None or credential.refresh_failing_since is None:
        return ()
    detail = _detail(now - credential.refresh_failing_since, credential.last_refresh_error)
    since = credential.refresh_failing_since.isoformat()
    return (
        _notice(BANNER_NOTICE_ID, BANNER, detail=detail, since=since, scope=None),
        _notice(
            PANEL_NOTICE_ID,
            PANEL,
            detail=detail,
            since=since,
            scope=NoticeScope(screen=SETTINGS_SCREEN),
        ),
    )


def _notice(
    notice_id: str,
    volume: NoticeVolume,
    *,
    detail: str,
    since: str,
    scope: NoticeScope | None,
) -> Notice:
    return Notice(
        id=notice_id,
        volume=volume,
        pigment=OXIDE,
        title=TITLE,
        detail=detail,
        unavailable=[WRITING_UNAVAILABLE],
        still_works=[READING_STILL_WORKS, PLAN_STILL_CORRECT],
        since=since,
        action=NoticeAction(label=RECONNECT_LABEL, href=RECONNECT_HREF),
        scope=scope,
    )


def _detail(failing_for: timedelta, reason: str | None) -> str:
    """What broke, for how long, what still works, and the one thing to do about it."""
    stated = f" Google's answer: {reason}." if reason else ""
    return (
        "syncr has not been able to write to your Google calendar for "
        f"{stated_duration(failing_for)}, so what your phone shows is that old. Reading your "
        "calendars still works, so the plan itself is current and correct: only the copy on "
        f"Google is stale.{stated} Reconnecting your Google account fixes it, and nothing else "
        "needs redoing."
    )


def stated_duration(elapsed: timedelta) -> str:
    """A duration in the largest unit that still reads as a number a person would say.

    Rounded down, because "for 3 days" understating a 3-day-and-20-hour failure is safer than
    "for 4 days" overstating it: the reader compares it against when they last saw the plan on
    their phone.
    """
    seconds = max(int(elapsed.total_seconds()), 0)
    if seconds >= _DAY:
        return _plural(seconds // _DAY, "day")
    if seconds >= _HOUR:
        return _plural(seconds // _HOUR, "hour")
    if seconds >= _MINUTE:
        return _plural(seconds // _MINUTE, "minute")
    return "less than a minute"


def _plural(count: int, unit: str) -> str:
    return f"{count} {unit}" if count == 1 else f"{count} {unit}s"
