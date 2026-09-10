"""The stored plan and off-plan readings that compose one budget occupancy."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from syncr_api.budgets.occupancy import WeekOccupancy, WeekOccupancyReader
from syncr_api.plans.records import PlanRevisionRecord
from syncr_api.plans.stored_documents import stored_document
from syncr_domain.discretionary import discretionary_intervals
from syncr_domain.gaps import ForbiddenScope
from syncr_domain.identity import Origin
from syncr_domain.intervals import Interval, IntervalSet
from syncr_domain.plan import FrameOverhang
from syncr_domain.weeks import IsoWeek
from tests.plan_documents import CAREER, FITNESS, a_block, a_document, a_window, between

if TYPE_CHECKING:
    from syncr_domain.plan import PlanDocument

WEEK = IsoWeek(2026, 7)
PRECEDING_WEEK = WEEK.preceding()
SPAN = Interval(
    datetime(2026, 2, 9, tzinfo=UTC),
    datetime(2026, 2, 16, tzinfo=UTC),
)


class StoredPlans:
    """The plan revisions a budget occupancy reader asks for."""

    def __init__(self, documents: dict[IsoWeek, PlanDocument]) -> None:
        self._documents = documents
        self.reads: list[IsoWeek] = []

    async def latest(self, iso_week: IsoWeek) -> PlanRevisionRecord | None:
        self.reads.append(iso_week)
        document = self._documents.get(iso_week)
        if document is None:
            return None
        return PlanRevisionRecord(
            id=uuid4(),
            tenant_id=uuid4(),
            iso_week=iso_week,
            status="applied",
            reason="materialized",
            document=stored_document(document),
            objective_breakdown={},
            weight_set_version=1,
            input_version=1,
            supersedes_id=None,
            created_at=datetime(2026, 2, 1, tzinfo=UTC),
            approved_at=None,
        )


class HeldOffPlan:
    """The off-plan occupancy owned outside the stored plan document."""

    def __init__(self, intervals: IntervalSet) -> None:
        self._intervals = intervals

    async def read(self, iso_week: IsoWeek, span: Interval) -> WeekOccupancy:
        return WeekOccupancy(off_plan=self._intervals)


async def test_the_reader_counts_routine_and_area_carries_from_monday() -> None:
    preceding_routine = a_block(
        Origin.FRAME,
        week=PRECEDING_WEEK,
        interval=between(23, 31, day=6, week=PRECEDING_WEEK),
    )
    preceding_entry = a_block(
        Origin.TEMPLATE_ENTRY,
        week=PRECEDING_WEEK,
        interval=between(23, 25, day=6, week=PRECEDING_WEEK),
        area_id=FITNESS,
    )
    frame = tuple(
        a_block(
            Origin.FRAME,
            week=WEEK,
            interval=between(23, 31, day=day, week=WEEK),
        )
        for day in range(7)
    )
    anchor = a_block(Origin.ANCHOR, week=WEEK, interval=between(10, 11, day=2, week=WEEK))
    career = a_block(
        Origin.HABIT, week=WEEK, interval=between(9, 10, day=1, week=WEEK), area_id=CAREER
    )
    fitness = a_block(
        Origin.HABIT, week=WEEK, interval=between(9, 10, day=4, week=WEEK), area_id=FITNESS
    )
    forbidden = a_window(
        interval=between(14, 15, day=3, week=WEEK),
        scope=ForbiddenScope.ALL,
        forbidden_area_ids=(),
    )
    current = a_document(
        week=WEEK,
        blocks=(*frame, anchor, career, fitness),
        frame_overhang=(
            FrameOverhang(interval=preceding_routine.interval),
            FrameOverhang(interval=preceding_entry.interval, label="Shower", area_id=FITNESS),
        ),
        forbidden_windows=(forbidden,),
        discretionary_minutes=6540,
        unallocated_minutes=6360,
    )
    off_plan = IntervalSet([between(12, 13, day=5, week=WEEK)])
    plans = StoredPlans({WEEK: current})
    reader = WeekOccupancyReader(plans, HeldOffPlan(off_plan))

    held = await reader.read(WEEK, SPAN)

    assert held.frame.clip(SPAN).total_minutes() == 56 * 60
    assert held.anchors == IntervalSet([anchor.interval])
    assert held.absolute_forbidden == IntervalSet([forbidden.interval])
    assert held.off_plan == off_plan
    assert held.by_area[CAREER] == IntervalSet([career.interval])
    assert held.by_area[FITNESS] == IntervalSet([preceding_entry.interval, fitness.interval])
    recomputed = discretionary_intervals(
        SPAN, held.frame, held.anchors, held.absolute_forbidden, held.off_plan
    )
    assert recomputed.total_minutes() == current.discretionary_minutes


async def test_a_week_with_no_plan_keeps_the_off_plan_reading() -> None:
    off_plan = IntervalSet([between(12, 13, day=5, week=WEEK)])
    plans = StoredPlans({})
    reader = WeekOccupancyReader(plans, HeldOffPlan(off_plan))

    held = await reader.read(WEEK, SPAN)

    assert held == WeekOccupancy(off_plan=off_plan)
    assert plans.reads == [WEEK]
