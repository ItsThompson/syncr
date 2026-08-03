"""What a week is already holding, in the five sets the budget arithmetic is stated over.

The denominator subtracts four sets and the numerator reads a fifth, so this is the one shape
that decides what the report divides. Which real span belongs in which of the four is not
decided here: ``syncr_domain.discretionary.SUBTRAHEND_BY_KIND`` is that table, and it is the
only statement of it.

``UnplannedWeek`` answers with empty sets, and it is the correct reading of the schema rather
than a placeholder for one. There is no table of routines, no table of anchors, no table of
forbidden windows, and no table of off-plan periods, so nothing in this deployment can occupy
a week's time yet; and although the plan of record is stored, the interior shape of its
document is not defined, so no Area's blocks can be read out of one. Under those conditions a
week genuinely holds nothing, and the report says so: the whole span is discretionary, every
minute of it is ``unallocated``, and each Area's actual is zero.

The reader is a protocol for the same reason the week input version counter is one: the
concerns that produce these sets each own their own storage, and the report should acquire
their answers rather than reach into five tables itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from syncr_domain.intervals import IntervalSet

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syncr_domain.identifiers import AreaId
    from syncr_domain.intervals import Interval
    from syncr_domain.weeks import IsoWeek


@dataclass(frozen=True, slots=True)
class WeekOccupancy:
    """The spans one week holds, sorted into what the budget arithmetic asks for.

    The first four are the denominator's subtrahends, at the effective durations and real
    times their producers resolved. ``by_area`` is the numerator: the intervals each Area's
    blocks occupy, which is what an Area's actual and the ``unallocated`` residual are measured
    from.

    **The per-Area sets are expected to be mutually disjoint, and nothing enforces it.** A minute
    claimed by two Areas is removed once from the residual and counted once in each Area's actual,
    so the residual stays correct while ``sum(actual) + unallocated`` exceeds the denominator by
    the overlap. Two blocks cannot really occupy one minute, so a producer that emits an overlap
    has a defect upstream of this shape: the pie's wedges stop tiling, which is a milder failure
    than a negative residual but is still one.
    """

    frame: IntervalSet = field(default_factory=IntervalSet)
    anchors: IntervalSet = field(default_factory=IntervalSet)
    absolute_forbidden: IntervalSet = field(default_factory=IntervalSet)
    off_plan: IntervalSet = field(default_factory=IntervalSet)
    by_area: Mapping[AreaId, IntervalSet] = field(default_factory=dict)


class WeekOccupancyReader(Protocol):
    """What the budget report asks for the spans a week already holds."""

    async def read(self, iso_week: IsoWeek, span: Interval) -> WeekOccupancy:
        """The occupancy of ``iso_week``, clipped or not, over ``span``."""
        ...


class UnplannedWeek:
    """The occupancy of a week in a deployment where nothing can occupy one.

    Reads nothing and writes nothing. A budget report over it is honest: the denominator is the
    whole span, and every discretionary minute is unallocated because no block claims any of
    it.
    """

    async def read(self, iso_week: IsoWeek, span: Interval) -> WeekOccupancy:
        return WeekOccupancy()
