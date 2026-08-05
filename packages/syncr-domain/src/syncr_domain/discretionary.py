"""Discretionary time: the one denominator every budget figure is measured against.

The pie review, the deviation bars, the verdict panel's discretionary reading, the
feasibility probe, and the solver's capacity check all consume this arithmetic, and there
is exactly one implementation of it. A wrong answer here is a plausible-looking budget
report rather than a crash, which is the failure this product cannot detect any other way.

**The four subtrahends are unioned before subtraction, never summed.** Three of them
routinely overlap: a frame ``Sleep`` span sits inside a long off-plan period, a recovery
window abuts the anchor that cast it, one lecture's recovery overlaps the next lecture.
Summing the durations over-subtracts. On the worked reference inputs, summing gives 84h 30m
of discretionary time and unioning gives 93h 45m from the same spans, and the union is the
correct figure. ``IntervalSet``'s normalization is what makes it correct: ``a.union(a) == a``,
so a span counted twice is counted once.

## What is subtracted, and the one question that decides it

**Can any Area ever claim this time?** If yes it stays in the denominator. If no it comes
out. :data:`SUBTRAHEND_BY_KIND` is that table, and it is the whole reason this module holds
a vocabulary of span kinds rather than only the arithmetic: without it, which real span
belongs in which of the four sets would be written down nowhere, and the narrowing recorded
below would be re-litigated by whichever caller built the sets next.

## This narrows PRD 3.1.2, deliberately

PRD 3.1.2 and `docs/DESIGN-LANGUAGE.md`'s budget-denominator section both state
discretionary time as total time minus the circadian frame, minus external anchors, minus
**anchor shadows**. Prep and transit are anchor shadows and they are **not** subtracted,
because they carry an Area: they are discretionary time *allocated* to that Area, exactly
like a task, and subtracting them would remove the time from the denominator **and** charge
it to an Area. A recovery window scoped to named Areas is not subtracted either, because
every other Area may still claim it.

The narrowing preserves the upstream intent, that only time no Area can claim leaves the
denominator, and corrects the enumeration used to express it. It is a marked deviation
rather than an omission.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Final

from syncr_domain.intervals import IntervalSet

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syncr_domain.intervals import Interval


class Subtrahend(StrEnum):
    """One of the four sets the denominator subtracts.

    The members are spelled as :func:`discretionary_intervals`' own parameters, and a test
    compares the two, so a fifth subtrahend cannot be added to the signature without
    appearing in the table below.
    """

    FRAME = "frame"
    ANCHORS = "anchors"
    ABSOLUTE_FORBIDDEN = "absolute_forbidden"
    OFF_PLAN = "off_plan"


class OccupancyKind(StrEnum):
    """Every kind of span a week holds, subtracted from the denominator or not."""

    FRAME = "frame"
    ANCHOR = "anchor"
    RECOVERY_ALL = "recovery_all"
    RECOVERY_AREAS = "recovery_areas"
    UNATTRIBUTED_BUFFER = "unattributed_buffer"
    OFF_PLAN = "off_plan"
    PREP_BLOCK = "prep_block"
    TRANSIT_BLOCK = "transit_block"
    TASK_BLOCK = "task_block"
    HABIT_BLOCK = "habit_block"
    TEMPLATE_ENTRY_BLOCK = "template_entry_block"
    SLOT_BLOCK = "slot_block"
    EMPTY_SLOT = "empty_slot"


# The subtraction table. A kind present here leaves the denominator, and the value names
# which of the four sets carries it; a kind absent here stays in, and the reason it stays
# in is always the same one: some Area can claim that time.
#
#   FRAME                routines are not budgeted as discretionary time. They define how
#                        much time exists, so they are not competing for it. The spans are
#                        the frame at its EFFECTIVE durations, already clamped
#   ANCHOR               time the product does not own
#   RECOVERY_ALL         nothing may be scheduled there, so no Area can claim it
#   UNATTRIBUTED_BUFFER  a prep or transit buffer with no Area to claim it. With an Area it
#                        is a block, and a block is allocation
#   OFF_PLAN             discretionary scheduling suspends
#
# And the six that stay in:
#
#   RECOVERY_AREAS       only the named Areas are excluded. Every other Area may claim it,
#                        and unfilled it becomes `unallocated`
#   PREP_BLOCK           carries an Area, so it consumes that Area's discretionary time in
#   TRANSIT_BLOCK          the same way a task does
#   TASK_BLOCK           allocation is not removal
#   HABIT_BLOCK
#   TEMPLATE_ENTRY_BLOCK a concrete entry of a day's shape: a `Shower` five mornings a week.
#                        It carries an Area, so allocation is not removal, for the same
#                        reason the two buffer blocks above are not
#   SLOT_BLOCK
#   EMPTY_SLOT           discretionary time nothing could be placed in. Subtracting it
#                        would make an unfillable week read as a fully-budgeted one, when
#                        the honest answer is that the time is `unallocated`
SUBTRAHEND_BY_KIND: Final[Mapping[OccupancyKind, Subtrahend]] = {
    OccupancyKind.FRAME: Subtrahend.FRAME,
    OccupancyKind.ANCHOR: Subtrahend.ANCHORS,
    OccupancyKind.RECOVERY_ALL: Subtrahend.ABSOLUTE_FORBIDDEN,
    OccupancyKind.UNATTRIBUTED_BUFFER: Subtrahend.ABSOLUTE_FORBIDDEN,
    OccupancyKind.OFF_PLAN: Subtrahend.OFF_PLAN,
}


def is_subtracted(kind: OccupancyKind) -> bool:
    """Whether spans of this kind leave the discretionary-time denominator."""
    return kind in SUBTRAHEND_BY_KIND


def discretionary_intervals(
    span: Interval,
    frame: IntervalSet,
    anchors: IntervalSet,
    absolute_forbidden: IntervalSet,
    off_plan: IntervalSet,
) -> IntervalSet:
    """The parts of ``span`` an Area may still claim.

    The set rather than the count, because every figure derived from it stays consistent
    with it: an Area's actual is its blocks intersected with this set, and ``unallocated``
    is this set minus every Area's blocks, so neither can exceed the denominator and
    neither needs a clamp to stay non-negative.
    """
    occupied = frame.union(anchors).union(absolute_forbidden).union(off_plan)
    return IntervalSet([span]).subtract(occupied)


def discretionary_time(
    span: Interval,
    frame: IntervalSet,
    anchors: IntervalSet,
    absolute_forbidden: IntervalSet,
    off_plan: IntervalSet,
) -> int:
    """Minutes of discretionary time in ``span``.

    Derived from :func:`discretionary_intervals` rather than from
    ``span.total_minutes() - occupied.total_minutes()``, so the count and the set cannot
    disagree by a truncated remainder.
    """
    free = discretionary_intervals(span, frame, anchors, absolute_forbidden, off_plan)
    return free.total_minutes()
