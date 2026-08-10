"""Whether the window a destructive reconciliation is about to run over is empty.

The reconciliation the live suite performs removes every event inside its horizon that syncr does
not intend, including one a person created by hand. The suite bounds that to a two-hour window on a
calendar that is supposed to hold nothing real, and the counts it asserts afterwards observe a
removal rather than refuse it: by the time ``foreign_deleted`` is non-zero the event is gone.

So the window is read before anything is written, and an occupied one refuses. The refusal names
the calendar, the window and the identifiers, because an operator has to be able to go and look. It
names no title: a live account holds real ones.

**A cancelled event does not occupy the window.** It holds no time, so there is nothing on the
calendar to remove, and the reconciliation skips it for the same reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.calendars.google_events import SYNCR_KEY_PROPERTY

if TYPE_CHECKING:
    from collections.abc import Iterable

    from syncr_api.calendars.google_payloads import GoogleEventPayload
    from syncr_domain.intervals import Interval


@dataclass(frozen=True, slots=True)
class WindowClear:
    """Nothing occupies the window, so a destructive reconciliation may run over it."""


@dataclass(frozen=True, slots=True)
class WindowOccupied:
    """Why a destructive reconciliation must not run over the window, in an operator's terms."""

    reason: str


type WindowReading = WindowClear | WindowOccupied


def read_window(
    events: Iterable[GoogleEventPayload], *, calendar: str, window: Interval
) -> WindowReading:
    """Whether ``events`` leave the window free for a destructive reconciliation.

    ``events`` is what a read of the target over ``window`` answered, so nothing here filters by
    time: an event the provider returned for that window is an event the reconciliation would
    remove, including one that began before the window and runs into it.
    """
    occupying = sorted((one for one in events if not one.is_cancelled), key=_by_identifier)
    if not occupying:
        return WindowClear()
    by_hand = [one.id for one in occupying if one.private_property(SYNCR_KEY_PROPERTY) is None]
    left_over = [
        one.id for one in occupying if one.private_property(SYNCR_KEY_PROPERTY) is not None
    ]
    return WindowOccupied(
        reason=(
            f"{calendar!r} holds {len(occupying)} event(s) between "
            f"{window.start.isoformat()} and {window.end.isoformat()}, and a reconciliation over "
            f"that window removes every event in it that syncr does not intend. Nothing was "
            f"written. Created by hand, so a person's: {by_hand}. Carrying syncr's key, so left "
            f"by an earlier run: {left_over}. Clear the window on that calendar, or wait for the "
            f"hour to pass so the window moves, and run this again."
        )
    )


def _by_identifier(event: GoogleEventPayload) -> str:
    return event.id
