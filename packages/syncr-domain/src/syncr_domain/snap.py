"""The fifteen-minute snap, and what is exempt from it.

Snap is measured rather than chosen: in one real reference month every timed block
began and ended on a quarter hour, 92% of them on the hour or half hour, and not one
at ``:05``, ``:10``, or ``:20``.

Every start and end lands on a quarter hour for solver output, drags, keyboard
moves, and off-plan bounds. Anchors are exempt, and so are the prep, transit, and
recovery buffers derived from an anchor.

An imported anchor is a fact and keeps its real time, even at ``:07``. Its derived
buffers are computed from that real time, so a 30-minute transit before a 16:07
anchor starts at 15:37. The exemption is what makes the grid's quarter-hour lines a
snap target for the user's own placements rather than a claim about every block.

The interval algebra therefore never snaps on its own: an unsnapped interval is
legal, and a producer that owes the grid applies :func:`snap_to_grid` itself.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Final

from syncr_domain.intervals import as_instant

if TYPE_CHECKING:
    from syncr_domain.intervals import Instant

SNAP_MINUTES: Final = 15
SNAP: Final = timedelta(minutes=SNAP_MINUTES)

_HALF_SNAP = SNAP / 2


def is_on_snap_grid(moment: Instant) -> bool:
    """Whether ``moment`` lands on a quarter hour.

    Read in UTC, which is safe because every offset in force since 1980 is a whole
    number of quarter hours, ``+05:45`` and ``+12:45`` included. A local quarter hour is
    therefore a UTC quarter hour, so the grid needs no zone to be checked against.
    Earlier offsets were not: ``Africa/Monrovia`` was ``-00:44:30`` until 1972 and
    ``Pacific/Kiritimati`` was ``-10:40`` until 1979. No date this product handles is.
    """
    instant = as_instant(moment)
    return instant.minute % SNAP_MINUTES == 0 and instant.second == 0 and instant.microsecond == 0


def snap_to_grid(moment: Instant) -> Instant:
    """``moment`` moved to the nearest quarter hour, an exact half-step rounding up."""
    instant = as_instant(moment)
    hour = instant.replace(minute=0, second=0, microsecond=0)
    steps = (instant - hour + _HALF_SNAP) // SNAP
    return hour + steps * SNAP
