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

The last two predicates take no instant, because a DECLARATION carries none: a wall time and
a duration in minutes, with no date and no zone.
:class:`syncr_domain.templates.EntrySpan` reads both, so a template entry that would
materialize a block starting or ending between two of the grid's lines is refused where the
user can still fix it rather than at solve time, where the entry is already fixed by
derivation. :class:`syncr_domain.routines.RoutineSpan` declares the same pair and reads
neither: whether the frame owes the grid is decided there, not here.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Final

from syncr_domain.intervals import as_instant

if TYPE_CHECKING:
    from datetime import time

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


def is_wall_time_on_snap_grid(at: time) -> bool:
    """Whether a declared time of day lands on a quarter hour.

    A wall time carries no date and no zone, so it names no instant and cannot be read by
    :func:`is_on_snap_grid`. It needs its own reading because a target time is declared as wall
    time: ``Wake 05:00`` means 05:00 wherever the user is.
    """
    return at.minute % SNAP_MINUTES == 0 and at.second == 0 and at.microsecond == 0


def is_a_snap_multiple(minutes: int) -> bool:
    """Whether a duration in minutes moves a start to another point on the grid.

    A start on the grid plus a duration that is a multiple of the step gives an end on the
    grid, which is what a declared duration owes the block it will materialize into.
    """
    return minutes % SNAP_MINUTES == 0
