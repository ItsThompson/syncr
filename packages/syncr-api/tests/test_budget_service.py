"""The budget report against fakes: the two residuals, the union, and a transition week.

The repositories and the occupancy reader are replaced; the arithmetic is not. Discretionary
time, every target, ``unallocated``, and ``oversubscription`` all come from the domain here
exactly as they do in the running application, and the interval algebra is real throughout: a
faked ``IntervalSet`` would let this suite pass while the denominator was wrong, which is the
one failure this product cannot detect any other way.

The tests worth reading:

``test_shares_summing_to_exactly_one_hundred_leave_time_unallocated`` is the defect an earlier
draft's ``discretionary - sum(area_target)`` formula had. ``test_the_denominator_unions_the
_subtrahends_rather_than_summing_them`` is the arithmetic the whole section rests on. And
``test_a_spring_forward_week_has_one_hour_less_discretionary_time`` is the transition rule, over
a real zone and real dates rather than a mocked offset.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest

from syncr_api.areas.records import AreaRecord
from syncr_api.areas.repository import AreaRepository
from syncr_api.budgets.occupancy import UnplannedWeek, WeekOccupancy
from syncr_api.budgets.service import BudgetService
from syncr_api.core.errors import Forbidden, ValidationFailed
from syncr_api.core.principal import Principal
from syncr_api.core.scopes import ALL_SCOPES
from syncr_api.user_settings.config import ReviewCadence
from syncr_api.user_settings.records import SettingsRecord, TravelOverrideRecord
from syncr_api.user_settings.repository import SettingsRepository, TravelOverrideRepository
from syncr_domain.fixtures.dst_weeks import FALL_BACK, LONDON, SPRING_FORWARD
from syncr_domain.intervals import Interval, IntervalSet
from syncr_domain.weeks import IsoWeek, week_span

if TYPE_CHECKING:
    from syncr_domain.identifiers import AreaId, TenantId

# An ordinary 168-hour week in Europe/London: 2026-W10 holds no transition.
ORDINARY_WEEK = "2026-W10"
ORDINARY_WEEK_MINUTES = 168 * 60

FITNESS = UUID("00000000-0000-4000-8000-000000000001")
CAREER = UUID("00000000-0000-4000-8000-000000000002")
LEARNING = UUID("00000000-0000-4000-8000-000000000003")


class StoredAreas(AreaRepository):
    """The Areas the report divides, with no database behind them."""

    def __init__(self, rows: list[AreaRecord]) -> None:
        self.rows = list(rows)

    async def list_all(self) -> tuple[AreaRecord, ...]:
        return tuple(self.rows)


class StoredSettings(SettingsRepository):
    """One settings row, for the home zone the week's span is resolved in."""

    def __init__(self, tenant_id: TenantId, home_zone: str = LONDON) -> None:
        self._tenant_id = tenant_id
        self._home_zone = home_zone

    async def read(self) -> SettingsRecord:
        return SettingsRecord(
            tenant_id=self._tenant_id,
            visible_hours=12,
            day_start=time(7, 0),
            day_end=time(23, 0),
            review_cadence=ReviewCadence.ON_DEMAND,
            home_zone=self._home_zone,
        )


class NoTravel(TravelOverrideRepository):
    """A tenant who has declared no travel, so the home zone governs every day."""

    def __init__(self) -> None:
        """No session and no tenant: this repository answers without reading anything."""

    async def list_all(self) -> tuple[TravelOverrideRecord, ...]:
        return ()


class HeldWeek:
    """An occupancy reader answering with one prepared set of spans."""

    def __init__(self, occupancy: WeekOccupancy) -> None:
        self.occupancy = occupancy
        self.reads: list[IsoWeek] = []

    async def read(self, iso_week: IsoWeek, span: Interval) -> WeekOccupancy:
        self.reads.append(iso_week)
        return self.occupancy


@pytest.fixture
def principal() -> Principal:
    return Principal(tenant_id=uuid4(), user_id=uuid4(), scopes=ALL_SCOPES)


def an_area(
    area_id: AreaId,
    *,
    percent: str | None = None,
    floor_hours: str | None = None,
    parent_id: AreaId | None = None,
) -> AreaRecord:
    return AreaRecord(
        id=area_id,
        tenant_id=uuid4(),
        parent_id=parent_id,
        name=f"Area {area_id}",
        pigment_index=0,
        budget_percent=None if percent is None else Decimal(percent),
        floor_hours=None if floor_hours is None else Decimal(floor_hours),
        default_preference_id=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def build_service(
    principal: Principal,
    *,
    areas: list[AreaRecord] | None = None,
    occupancy: WeekOccupancy | None = None,
    home_zone: str = LONDON,
) -> BudgetService:
    return BudgetService(
        areas=StoredAreas(areas or []),
        settings=StoredSettings(principal.tenant_id, home_zone),
        overrides=NoTravel(),
        occupancy=HeldWeek(occupancy) if occupancy is not None else UnplannedWeek(),
    )


def at(week: str, *, day: int, hour: int, minutes: int = 0) -> datetime:
    """An instant inside ``week``, counted from the start of its span."""
    span = week_span(IsoWeek.parse(week), SPRING_FORWARD.profile)
    return span.start + timedelta(days=day, hours=hour, minutes=minutes)


def blocks(*spans: Interval) -> IntervalSet:
    return IntervalSet(spans)


# --------------------------------------------------------------------------------
# The denominator
# --------------------------------------------------------------------------------


async def test_an_unoccupied_week_is_discretionary_end_to_end(principal: Principal) -> None:
    service = build_service(principal)

    view = await service.read(principal, ORDINARY_WEEK)

    assert view.period == IsoWeek.parse(ORDINARY_WEEK)
    assert view.span.total_minutes() == ORDINARY_WEEK_MINUTES
    assert view.report.discretionary_minutes == ORDINARY_WEEK_MINUTES
    # Nothing is planned, so every minute of it is in no block at all.
    assert view.report.unallocated_minutes == ORDINARY_WEEK_MINUTES
    assert view.report.oversubscription_minutes == 0
    assert view.report.allocations == ()


async def test_the_denominator_unions_the_subtrahends_rather_than_summing_them(
    principal: Principal,
) -> None:
    # A frame span wholly inside an off-plan period, and a forbidden window overlapping the
    # anchor that cast it: the ordinary shape of a real week. Summing the four durations would
    # subtract the overlaps twice and overstate the subtraction.
    off_plan = Interval(at(ORDINARY_WEEK, day=4, hour=0), at(ORDINARY_WEEK, day=7, hour=0))
    frame = Interval(at(ORDINARY_WEEK, day=5, hour=23), at(ORDINARY_WEEK, day=6, hour=7))
    anchor = Interval(at(ORDINARY_WEEK, day=3, hour=16), at(ORDINARY_WEEK, day=3, hour=18))
    forbidden = Interval(at(ORDINARY_WEEK, day=3, hour=17), at(ORDINARY_WEEK, day=3, hour=19))
    service = build_service(
        principal,
        occupancy=WeekOccupancy(
            frame=blocks(frame),
            anchors=blocks(anchor),
            absolute_forbidden=blocks(forbidden),
            off_plan=blocks(off_plan),
        ),
    )

    view = await service.read(principal, ORDINARY_WEEK)

    summed = sum(span.total_minutes() for span in (frame, anchor, forbidden, off_plan))
    unioned = IntervalSet([frame, anchor, forbidden, off_plan]).total_minutes()
    assert view.report.discretionary_minutes == ORDINARY_WEEK_MINUTES - unioned
    # And the wrong arithmetic is stated too, so the assertion above is measured against
    # something rather than being a number with no alternative.
    assert view.report.discretionary_minutes > ORDINARY_WEEK_MINUTES - summed


async def test_a_spring_forward_week_has_one_hour_less_discretionary_time(
    principal: Principal,
) -> None:
    # D2, over a real zone and real dates. Every figure derives from the span's own minutes, so
    # a transition needs no special case anywhere in the arithmetic.
    service = build_service(principal)
    week_before = str(IsoWeek(SPRING_FORWARD.iso_week.year, SPRING_FORWARD.iso_week.week - 1))

    transition = await service.read(principal, str(SPRING_FORWARD.iso_week))
    ordinary = await service.read(principal, week_before)

    assert transition.span.total_minutes() == SPRING_FORWARD.span_minutes == 167 * 60
    assert ordinary.report.discretionary_minutes - transition.report.discretionary_minutes == 60


async def test_a_fall_back_week_has_one_hour_more_discretionary_time(
    principal: Principal,
) -> None:
    service = build_service(principal)
    week_before = str(IsoWeek(FALL_BACK.iso_week.year, FALL_BACK.iso_week.week - 1))

    transition = await service.read(principal, str(FALL_BACK.iso_week))
    ordinary = await service.read(principal, week_before)

    assert transition.span.total_minutes() == FALL_BACK.span_minutes == 169 * 60
    assert transition.report.discretionary_minutes - ordinary.report.discretionary_minutes == 60


async def test_a_frame_only_week_reports_a_zero_target_for_every_area(
    principal: Principal,
) -> None:
    # Routines never appear in Area budget arithmetic. They define how much time exists, so a
    # week that is entirely frame has nothing to divide.
    span = week_span(IsoWeek.parse(ORDINARY_WEEK), SPRING_FORWARD.profile)
    service = build_service(
        principal,
        areas=[an_area(FITNESS, percent="40"), an_area(CAREER, percent="60")],
        occupancy=WeekOccupancy(frame=blocks(span)),
    )

    view = await service.read(principal, ORDINARY_WEEK)

    assert view.report.discretionary_minutes == 0
    assert [allocation.target_minutes for allocation in view.report.allocations] == [0, 0]
    assert view.report.unallocated_minutes == 0


# --------------------------------------------------------------------------------
# The two residuals
# --------------------------------------------------------------------------------


async def test_shares_summing_to_exactly_one_hundred_leave_time_unallocated(
    principal: Principal,
) -> None:
    # The defect the earlier formula had: `discretionary - sum(area_target)` is exactly zero at
    # 100% every week, however many hours sat in no block.
    service = build_service(
        principal,
        areas=[an_area(FITNESS, percent="40"), an_area(CAREER, percent="60")],
        occupancy=WeekOccupancy(
            by_area={
                FITNESS: blocks(
                    Interval(at(ORDINARY_WEEK, day=0, hour=9), at(ORDINARY_WEEK, day=0, hour=11))
                )
            }
        ),
    )

    view = await service.read(principal, ORDINARY_WEEK)

    targets = [allocation.target_minutes for allocation in view.report.allocations]
    assert sum(targets) == ORDINARY_WEEK_MINUTES
    assert view.report.oversubscription_minutes == 0
    assert view.report.unallocated_minutes == ORDINARY_WEEK_MINUTES - 120
    assert view.report.unallocated_minutes != 0


async def test_shares_summing_past_one_hundred_are_reported_as_oversubscription(
    principal: Principal,
) -> None:
    service = build_service(
        principal, areas=[an_area(FITNESS, percent="80"), an_area(CAREER, percent="50")]
    )

    view = await service.read(principal, ORDINARY_WEEK)

    assert view.report.oversubscription_minutes == ORDINARY_WEEK_MINUTES * 30 // 100
    # And the residual is not negative and not the same quantity: nothing was planned, so every
    # discretionary minute is still in no block.
    assert view.report.unallocated_minutes == ORDINARY_WEEK_MINUTES


async def test_a_floor_and_a_share_divide_the_week_the_way_the_formula_states(
    principal: Principal,
) -> None:
    service = build_service(
        principal,
        areas=[
            an_area(FITNESS, floor_hours="4", percent="25"),
            an_area(CAREER, percent="75"),
        ],
    )

    view = await service.read(principal, ORDINARY_WEEK)

    after_floors = ORDINARY_WEEK_MINUTES - 240
    fitness, career = view.report.allocations
    assert fitness.target_minutes == 240 + after_floors // 4
    assert career.target_minutes == after_floors * 3 // 4
    assert view.report.oversubscription_minutes == 0


async def test_a_child_areas_time_rolls_up_into_its_parent(principal: Principal) -> None:
    service = build_service(
        principal,
        areas=[
            an_area(CAREER, percent="50"),
            an_area(LEARNING, percent="10", parent_id=CAREER),
        ],
        occupancy=WeekOccupancy(
            by_area={
                CAREER: blocks(
                    Interval(at(ORDINARY_WEEK, day=0, hour=9), at(ORDINARY_WEEK, day=0, hour=10))
                ),
                LEARNING: blocks(
                    Interval(at(ORDINARY_WEEK, day=1, hour=14), at(ORDINARY_WEEK, day=1, hour=16))
                ),
            }
        ),
    )

    view = await service.read(principal, ORDINARY_WEEK)
    career, learning = view.report.allocations

    assert career.actual_minutes == 60
    assert career.rolled_up_actual_minutes == 180
    assert career.rolled_up_target_minutes == career.target_minutes + learning.target_minutes
    assert view.report.unallocated_minutes == ORDINARY_WEEK_MINUTES - 180


async def test_an_areas_actual_never_counts_time_that_left_the_denominator(
    principal: Principal,
) -> None:
    # A block inside an off-plan period is time no Area may claim, so it cannot show up as that
    # Area's consumption either. That is what keeps the wedges and the residual adding up.
    off_plan = Interval(at(ORDINARY_WEEK, day=4, hour=0), at(ORDINARY_WEEK, day=7, hour=0))
    service = build_service(
        principal,
        areas=[an_area(FITNESS, percent="100")],
        occupancy=WeekOccupancy(
            off_plan=blocks(off_plan),
            by_area={
                FITNESS: blocks(
                    Interval(at(ORDINARY_WEEK, day=3, hour=23), at(ORDINARY_WEEK, day=4, hour=1))
                )
            },
        ),
    )

    view = await service.read(principal, ORDINARY_WEEK)

    assert view.report.discretionary_minutes == 96 * 60
    assert view.report.allocations[0].actual_minutes == 60
    assert view.report.unallocated_minutes == 96 * 60 - 60


# --------------------------------------------------------------------------------
# The period, and authorization
# --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "period",
    ["", "2026", "2026-W", "2026-W99", "last week", "2026-w10", "2026-W7"],
    ids=["empty", "a year", "no week", "week 99", "prose", "a lowercase w", "an unpadded week"],
)
async def test_a_period_that_names_no_iso_week_is_refused(
    principal: Principal, period: str
) -> None:
    service = build_service(principal)

    with pytest.raises(ValidationFailed) as refused:
        await service.read(principal, period)

    assert refused.value.errors is not None
    assert [error.field for error in refused.value.errors] == ["period"]


async def test_a_well_formed_period_is_accepted(principal: Principal) -> None:
    # The control at the other end: the rejection above must distinguish rather than refuse
    # every string, and an ISO year's 53rd week is a real week.
    service = build_service(principal)

    assert (await service.read(principal, "2026-W01")).period == IsoWeek(2026, 1)
    assert (await service.read(principal, "2026-W53")).period == IsoWeek(2026, 53)


async def test_a_credential_without_plan_read_cannot_read_a_budget(
    principal: Principal,
) -> None:
    service = build_service(principal)
    stranger = Principal(
        tenant_id=principal.tenant_id, user_id=principal.user_id, scopes=frozenset()
    )

    with pytest.raises(Forbidden):
        await service.read(stranger, ORDINARY_WEEK)


async def test_the_report_asks_the_occupancy_reader_for_the_period_it_was_given(
    principal: Principal,
) -> None:
    held = HeldWeek(WeekOccupancy())
    service = BudgetService(
        areas=StoredAreas([]),
        settings=StoredSettings(principal.tenant_id),
        overrides=NoTravel(),
        occupancy=held,
    )

    await service.read(principal, ORDINARY_WEEK)

    assert held.reads == [IsoWeek.parse(ORDINARY_WEEK)]


async def test_an_unreadable_home_zone_is_a_stated_rejection(principal: Principal) -> None:
    # `Europe` is a DIRECTORY in the tz tree. Without the zone layer's own rejection this would
    # reach the wire as a 500 from inside the span derivation.
    service = build_service(principal, home_zone="Europe")

    with pytest.raises(ValidationFailed, match="IANA"):
        await service.read(principal, ORDINARY_WEEK)
