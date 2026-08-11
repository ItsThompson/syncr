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

Neither :func:`is_wall_time_on_snap_grid` nor :func:`is_a_snap_multiple` takes an instant, because a
DECLARATION carries none: a wall time and a duration in minutes, with no date and no zone.

**Whether a value is a wall time at all is a different question from whether it is on the grid, and
:func:`not_a_wall_time` is the whole of the first one.** A wall time carries no zone and nothing
below a minute; ``07:05`` breaks neither of those and is off the grid, so the two questions answer
differently and a shape that owes one without the other reads only the one it owes. It is not a
declaration predicate and the crossing below does not include it: it refuses a value that could not
be a time of day at all, before any question about where that time of day falls.

**A declared duration owes the grid, and so does a wall time the user chose.** An anchor and the
buffers derived from it are the only exemption: nothing else is excused, and a shape that declares
a wall time or a duration and reads neither declaration predicate is unenforced rather than exempt.
Every placement lands on the grid, so a declaration off it names a time or a length no block can
hold.

The declaration predicates are read at these sites, and this list is the whole of them:

* ``syncr_domain.habits`` reads both bounds of a habit's duration.
* ``syncr_domain.preferences`` reads a preferred window's bounds, and a preference's ideal
  session length.
* ``syncr_domain.templates`` reads a day-shape entry's target time and its duration, so an entry
  that would materialize a block starting or ending between two of the grid's lines is refused
  where the user can still fix it rather than at solve time, where the entry is already fixed by
  derivation.
* ``syncr_api.promotions.service`` reads the wall time a promoted pattern names, and refuses it
  as a conflict rather than as a field error, because that request carries no body.

Refusing a declaration is not snapping one: nothing here moves a value a person authored. A
duration a computation produced is the other case, and :func:`nearest_snap_multiple` is where
that one moves back onto the grid.
"""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from syncr_domain.intervals import as_instant

if TYPE_CHECKING:
    from datetime import time

    from syncr_domain.intervals import Instant

SNAP_MINUTES: Final = 15
SNAP: Final = timedelta(minutes=SNAP_MINUTES)

_HALF_SNAP = SNAP / 2
# The same half step as a count of minutes, for rounding a duration rather than an instant.
_HALF_SNAP_MINUTES = SNAP_MINUTES // 2


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


class NotAWallTime(StrEnum):
    """The two shapes a time of day cannot take and still be wall time.

    Carried on the answer rather than resolved to a message here, because the message belongs to
    the shape that was refused: a target time, a preferred window bound and a day bound each name
    their own field and their own reason for owing the rule.
    """

    CARRIES_A_ZONE = "carries_a_zone"
    BELOW_MINUTE_RESOLUTION = "below_minute_resolution"


def not_a_wall_time(at: time) -> NotAWallTime | None:
    """Which half of the wall-time rule ``at`` breaks, or ``None`` when it breaks neither.

    A wall time names a time of day and nothing else. An offset would be dropped by any column
    that stores one, leaving the value an hour or more out with nothing to say so, and every
    duration this product declares is a count of minutes, so a value below minute resolution names
    a start no declared span could run from.

    A value carrying both is named by the zone. The precedence is stated once here because it
    decides which refusal a caller reports, and every shape that reads this rule answered the zone
    first before the rule was stated in one place.
    """
    if at.tzinfo is not None:
        return NotAWallTime.CARRIES_A_ZONE
    if at.second or at.microsecond:
        return NotAWallTime.BELOW_MINUTE_RESOLUTION
    return None


def is_a_snap_multiple(minutes: int) -> bool:
    """Whether a duration in minutes moves a start to another point on the grid.

    A start on the grid plus a duration that is a multiple of the step gives an end on the
    grid, which is what a declared duration owes the block it will materialize into.
    """
    return minutes % SNAP_MINUTES == 0


def nearest_snap_multiple(minutes: int) -> int:
    """``minutes`` moved to the nearest whole number of steps.

    For a duration a computation produced rather than a person declared: scaling a declared
    45-minute range by a learned 1.2 gives 54, which no block can hold, so the scaled figure
    is moved back onto the grid where the scaling happens rather than refused there.

    No tie rule is needed and none is stated: half a step is seven and a half minutes, so no
    whole number of minutes sits equidistant between two steps.

    The floor is one step, because a duration below one step could not both start and end on
    the grid, and a scaled duration of zero would name no block at all. A negative input is a
    caller error rather than a short duration, so it is refused instead of clamped.
    """
    if minutes < 0:
        raise ValueError(f"a duration is a count of minutes and this one is {minutes}")
    steps = (minutes + _HALF_SNAP_MINUTES) // SNAP_MINUTES
    return max(SNAP_MINUTES, steps * SNAP_MINUTES)
