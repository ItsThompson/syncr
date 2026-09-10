"""What a week is already holding, in the five sets the budget arithmetic is stated over.

The denominator subtracts four sets and the numerator reads a fifth, so this is the one shape
that decides what the report divides. Which real span belongs in which of the four is not
decided here: ``syncr_domain.discretionary.SUBTRAHEND_BY_KIND`` is that table, and it is the
only statement of it.

``UnplannedWeek`` answers with empty sets. It remains the correct reading for a caller that has
no stored source: the whole span is discretionary, every minute is ``unallocated``, and each
Area's actual is zero. Production uses :class:`WeekOccupancyReader`, which reads plan-document
blocks and composes them with :class:`~syncr_api.offplan.occupancy.OffPlanOccupancy`. A week with
no plan still retains its off-plan occupancy and leaves the other four sets empty.

The reader is a protocol for the same reason the week input version counter is one: the
concerns that produce these sets each own their own storage, and the report should acquire
their answers rather than reach into five tables itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from syncr_api.plans.stored_documents import plan_document
from syncr_domain.discretionary import SUBTRAHEND_BY_KIND, Subtrahend, absolute_forbidden
from syncr_domain.intervals import IntervalSet

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syncr_api.plans.records import PlanRevisionRecord
    from syncr_domain.identifiers import AreaId
    from syncr_domain.intervals import Interval
    from syncr_domain.plan import PlanDocument
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


class WeekOccupancySource(Protocol):
    """What the budget report asks for the spans a week already holds."""

    async def read(self, iso_week: IsoWeek, span: Interval) -> WeekOccupancy:
        """The occupancy of ``iso_week``, clipped or not, over ``span``."""
        ...


class PlanRevisionReader(Protocol):
    """The stored plan revision a budget occupancy reader needs."""

    async def latest(self, iso_week: IsoWeek) -> PlanRevisionRecord | None:
        """The newest stored plan for ``iso_week``, if the tenant has one."""
        ...


class WeekOccupancyReader:
    """The stored plan's occupancy, including its carried Monday occupancy.

    A plan owns a block where it starts. A routine or concrete entry beginning late Sunday therefore
    appears only in the preceding document, even though its Monday minutes occupy this week. The
    document stores that carry separately: routine minutes enter the frame and an Area-carrying
    entry enters that Area's actual.
    """

    def __init__(self, plans: PlanRevisionReader, off_plan: WeekOccupancySource) -> None:
        self._plans = plans
        self._off_plan = off_plan

    async def read(self, iso_week: IsoWeek, span: Interval) -> WeekOccupancy:
        """The stored plan occupancy for ``iso_week``, or only off-plan occupancy without a plan."""
        off_plan = await self._off_plan.read(iso_week, span)
        current = await self._plans.latest(iso_week)
        if current is None:
            return off_plan

        return occupancy_of(plan_document(current.document), off_plan=off_plan.off_plan)


class UnplannedWeek:
    """The occupancy of a week nothing has occupied.

    Reads nothing and writes nothing. A budget report over it is honest: the denominator is the
    whole span, and every discretionary minute is unallocated because no block claims any of
    it.
    """

    async def read(self, iso_week: IsoWeek, span: Interval) -> WeekOccupancy:
        return WeekOccupancy()


def occupancy_of(document: PlanDocument, *, off_plan: IntervalSet) -> WeekOccupancy:
    """The stored plan document's occupancy, composed with its separately stored time off."""
    subtrahends: dict[Subtrahend, list[Interval]] = {subtrahend: [] for subtrahend in Subtrahend}
    by_area: dict[AreaId, list[Interval]] = {}
    for block in document.blocks:
        subtrahend = SUBTRAHEND_BY_KIND.get(block.occupancy_kind)
        if subtrahend is not None:
            subtrahends[subtrahend].append(block.interval)
        if block.area_id is not None:
            by_area.setdefault(block.area_id, []).append(block.interval)
    for overhang in document.frame_overhang:
        if overhang.is_circadian_frame:
            subtrahends[Subtrahend.FRAME].append(overhang.interval)
            continue
        if overhang.area_id is not None:
            by_area.setdefault(overhang.area_id, []).append(overhang.interval)

    return WeekOccupancy(
        frame=IntervalSet(subtrahends[Subtrahend.FRAME]),
        anchors=IntervalSet(subtrahends[Subtrahend.ANCHORS]),
        absolute_forbidden=absolute_forbidden(document.forbidden_windows),
        off_plan=off_plan,
        by_area={area_id: IntervalSet(intervals) for area_id, intervals in by_area.items()},
    )
