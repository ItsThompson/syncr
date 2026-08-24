"""The off-plan service against fakes: the two invariants, the 409, and what gets bumped.

The repositories are replaced and the clock is injected; the domain rules are not. Whether a
span is on the grid, and whether two spans cover a common instant, are answered by
``syncr_domain.off_plan`` here exactly as they are in the running application, and the interval
algebra is real throughout.

The tests worth reading are the boundary ones. A period declared where another ends is accepted,
because adjacency is not overlap. A patch that changes only ``keepFrame`` is not refused for
overlapping its own stored self. And a period moved from one fortnight to another bumps the weeks
it LEFT as well as the weeks it now covers, because both sets of denominators changed.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syncr_api.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from syncr_api.core.patches import ABSENT
from syncr_api.core.principal import Principal
from syncr_api.core.scopes import ALL_SCOPES, Scope
from syncr_api.offplan.declarations import OffPlanChange, OffPlanDeclaration
from syncr_api.offplan.records import OffPlanPeriodRecord
from syncr_api.offplan.repository import OffPlanPeriodRepository
from syncr_api.offplan.service import OffPlanService
from syncr_api.user_settings.config import ReviewCadence
from syncr_api.user_settings.records import SettingsRecord, TravelOverrideRecord
from syncr_api.user_settings.repository import SettingsRepository, TravelOverrideRepository
from syncr_api.user_settings.solve_inputs import WeekRange
from syncr_domain.fixtures.off_plan_week import OFF_PLAN_WEEK
from syncr_domain.intervals import Interval
from syncr_domain.weeks import IsoWeek, week_span

if TYPE_CHECKING:
    from syncr_domain.identifiers import OffPlanPeriodId, TenantId

LONDON = "Europe/London"

# A Wednesday mid-morning in 2026-W10, so "now" is a literal and no test depends on a real clock.
NOW = datetime(2026, 3, 4, 9, 0, tzinfo=UTC)

WEEK_10 = IsoWeek.parse("2026-W10")
WEEK_11 = IsoWeek.parse("2026-W11")

# Friday 14:00 to Monday 09:00 of 2026-W10, in GMT: the shape the product is built around.
FRIDAY = Interval(datetime(2026, 3, 6, 14, 0, tzinfo=UTC), datetime(2026, 3, 9, 9, 0, tzinfo=UTC))
# Starting exactly where it ends, which is the pair that has to be accepted.
ABUTTING = Interval(datetime(2026, 3, 9, 9, 0, tzinfo=UTC), datetime(2026, 3, 9, 17, 0, tzinfo=UTC))


class FakeOffPlanRepository(OffPlanPeriodRepository):
    """The real repository's interface over a list of records, and no database."""

    def __init__(
        self, tenant_id: TenantId, stored: list[OffPlanPeriodRecord] | None = None
    ) -> None:
        self._tenant_id = tenant_id
        self.rows = list(stored or [])

    async def list_all(self) -> tuple[OffPlanPeriodRecord, ...]:
        return tuple(sorted(self.rows, key=lambda row: (row.interval, row.id)))

    async def for_span(self, span: Interval) -> tuple[OffPlanPeriodRecord, ...]:
        found = await self.list_all()
        return tuple(row for row in found if row.interval.overlaps(span))

    async def find(self, period_id: OffPlanPeriodId) -> OffPlanPeriodRecord | None:
        return next((row for row in self.rows if row.id == period_id), None)

    async def create(
        self,
        *,
        interval: Interval,
        keep_frame: bool,
        label: str | None,
        created_at: datetime,
    ) -> OffPlanPeriodRecord:
        created = OffPlanPeriodRecord(
            id=uuid4(),
            tenant_id=self._tenant_id,
            interval=interval,
            keep_frame=keep_frame,
            label=label,
            created_at=created_at,
        )
        self.rows.append(created)
        return created

    async def write(
        self,
        period_id: OffPlanPeriodId,
        *,
        interval: Interval,
        keep_frame: bool,
        label: str | None,
    ) -> None:
        self.rows = [
            OffPlanPeriodRecord(
                id=row.id,
                tenant_id=row.tenant_id,
                interval=interval,
                keep_frame=keep_frame,
                label=label,
                created_at=row.created_at,
            )
            if row.id == period_id
            else row
            for row in self.rows
        ]

    async def remove(self, period_id: OffPlanPeriodId) -> None:
        self.rows = [row for row in self.rows if row.id != period_id]


class FakeSettingsRepository(SettingsRepository):
    """One settings row, for the home zone the weeks are resolved in, and the lock."""

    def __init__(self, tenant_id: TenantId, home_zone: str = LONDON) -> None:
        self._tenant_id = tenant_id
        self._home_zone = home_zone
        self.locks = 0

    async def read(self) -> SettingsRecord:
        return SettingsRecord(
            tenant_id=self._tenant_id,
            visible_hours=12,
            day_start=time(7, 0),
            day_end=time(23, 0),
            review_cadence=ReviewCadence.ON_DEMAND,
            home_zone=self._home_zone,
        )

    async def lock(self, *, created_at: datetime) -> SettingsRecord:
        self.locks += 1
        return await self.read()


class StoredTravel(TravelOverrideRepository):
    """The declared overrides over a list, and no database."""

    def __init__(self, tenant_id: TenantId, *overrides: TravelOverrideRecord) -> None:
        self._tenant_id = tenant_id
        self._overrides = overrides

    async def list_all(self) -> tuple[TravelOverrideRecord, ...]:
        return self._overrides


class RecordingWeekInputVersions:
    """Every range the service asked to have bumped, in order."""

    def __init__(self) -> None:
        self.bumped: list[WeekRange] = []

    async def bump(self, weeks: WeekRange) -> None:
        self.bumped.append(weeks)


@pytest.fixture
def principal() -> Principal:
    return Principal(tenant_id=uuid4(), user_id=uuid4(), scopes=ALL_SCOPES)


@pytest.fixture
def versions() -> RecordingWeekInputVersions:
    return RecordingWeekInputVersions()


def a_period(
    tenant_id: TenantId,
    interval: Interval,
    *,
    keep_frame: bool = False,
    label: str | None = None,
) -> OffPlanPeriodRecord:
    return OffPlanPeriodRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        interval=interval,
        keep_frame=keep_frame,
        label=label,
        created_at=NOW,
    )


def build(
    principal: Principal,
    versions: RecordingWeekInputVersions,
    *,
    stored: list[OffPlanPeriodRecord] | None = None,
    home_zone: str = LONDON,
    travel: TravelOverrideRepository | None = None,
) -> tuple[OffPlanService, FakeOffPlanRepository, FakeSettingsRepository]:
    periods = FakeOffPlanRepository(principal.tenant_id, stored)
    settings = FakeSettingsRepository(principal.tenant_id, home_zone)
    service = OffPlanService(
        periods=periods,
        settings=settings,
        overrides=travel if travel is not None else StoredTravel(principal.tenant_id),
        versions=versions,
        clock=lambda: NOW,
    )
    return service, periods, settings


def declaring(
    interval: Interval, *, keep_frame: bool = False, label: str | None = None
) -> OffPlanDeclaration:
    return OffPlanDeclaration(
        start=interval.start, end=interval.end, keep_frame=keep_frame, label=label
    )


def unchanged() -> OffPlanChange:
    return OffPlanChange(start=ABSENT, end=ABSENT, keep_frame=ABSENT, label=ABSENT)


# --------------------------------------------------------------------------------
# Declaring
# --------------------------------------------------------------------------------


async def test_a_span_of_any_length_is_declarable(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, periods, _ = build(principal, versions)

    created = await service.declare(principal, declaring(FRIDAY, keep_frame=True, label="Italy"))

    assert created.interval == FRIDAY
    assert created.keep_frame is True
    assert created.label == "Italy"
    assert created.created_at == NOW
    assert [row.interval for row in periods.rows] == [FRIDAY]


async def test_the_frame_is_dropped_unless_the_declaration_keeps_it(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, _, _ = build(principal, versions)

    created = await service.declare(principal, declaring(FRIDAY))

    assert created.keep_frame is False
    assert created.label is None


async def test_a_declaration_is_serialized_before_the_overlap_check(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # Two declarations racing would both pass a check against the same rows and both insert. The
    # settings row is the lock, and it exists for a tenant with no periods at all, which is
    # exactly the case a lock over the periods themselves would leave open.
    service, _, settings = build(principal, versions)

    await service.declare(principal, declaring(FRIDAY))

    assert settings.locks == 1


async def test_a_span_overlapping_one_already_declared_is_refused(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    stored = [a_period(principal.tenant_id, FRIDAY)]
    service, periods, _ = build(principal, versions, stored=stored)
    inside = Interval(
        datetime(2026, 3, 7, 10, 0, tzinfo=UTC), datetime(2026, 3, 7, 11, 0, tzinfo=UTC)
    )

    with pytest.raises(Conflict) as refused:
        await service.declare(principal, declaring(inside))

    assert "overlaps" in str(refused.value.detail)
    assert "adjacency is not overlap" in str(refused.value.detail)
    # Nothing was stored, and nothing was invalidated either.
    assert [row.interval for row in periods.rows] == [FRIDAY]
    assert versions.bumped == []


async def test_a_span_beginning_where_another_ends_is_accepted(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    stored = [a_period(principal.tenant_id, FRIDAY)]
    service, periods, _ = build(principal, versions, stored=stored)

    created = await service.declare(principal, declaring(ABUTTING))

    assert created.interval == ABUTTING
    assert len(periods.rows) == 2


async def test_a_span_ending_where_another_begins_is_accepted(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # The other direction, because the answer must not depend on which was declared first.
    stored = [a_period(principal.tenant_id, ABUTTING)]
    service, periods, _ = build(principal, versions, stored=stored)

    created = await service.declare(principal, declaring(FRIDAY))

    assert created.interval == FRIDAY
    assert len(periods.rows) == 2


@pytest.mark.parametrize(
    "span",
    [
        (datetime(2026, 3, 6, 14, 5, tzinfo=UTC), datetime(2026, 3, 9, 9, 0, tzinfo=UTC)),
        (datetime(2026, 3, 6, 14, 0, tzinfo=UTC), datetime(2026, 3, 9, 9, 7, tzinfo=UTC)),
    ],
    ids=["start_off_the_grid", "end_off_the_grid"],
)
async def test_a_bound_off_the_quarter_hour_is_refused(
    principal: Principal,
    versions: RecordingWeekInputVersions,
    span: tuple[datetime, datetime],
) -> None:
    service, periods, _ = build(principal, versions)
    start, end = span

    with pytest.raises(ValidationFailed, match="quarter hour"):
        await service.declare(
            principal, OffPlanDeclaration(start=start, end=end, keep_frame=False, label=None)
        )

    assert periods.rows == []
    assert versions.bumped == []


@pytest.mark.parametrize(
    "span",
    [
        (datetime(2026, 3, 9, 9, 0, tzinfo=UTC), datetime(2026, 3, 6, 14, 0, tzinfo=UTC)),
        (datetime(2026, 3, 6, 14, 0, tzinfo=UTC), datetime(2026, 3, 6, 14, 0, tzinfo=UTC)),
    ],
    ids=["reversed", "zero_length"],
)
async def test_a_span_that_covers_nothing_is_refused(
    principal: Principal,
    versions: RecordingWeekInputVersions,
    span: tuple[datetime, datetime],
) -> None:
    service, periods, _ = build(principal, versions)
    start, end = span

    with pytest.raises(ValidationFailed, match="runs forward"):
        await service.declare(
            principal, OffPlanDeclaration(start=start, end=end, keep_frame=False, label=None)
        )

    assert periods.rows == []


# --------------------------------------------------------------------------------
# The version bump
# --------------------------------------------------------------------------------


async def test_declaring_bumps_every_week_the_span_touches(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, _, _ = build(principal, versions)

    await service.declare(principal, declaring(FRIDAY))

    assert versions.bumped == [WeekRange(first=WEEK_10, last=WEEK_11)]


async def test_declaring_inside_a_travel_override_bumps_the_active_zone_week(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # The seam the two-zone reading got wrong. Home Europe/London, an override to Pacific/Auckland
    # over 2026-03-01..22: Auckland's Monday of W11 begins at 2026-03-08 11:00Z (UTC+13), so this
    # span is Sunday morning at home but the FIRST quarter hour of the override's Monday. The
    # week whose denominator changes is W11; the home-zone reading named W10.
    travel = StoredTravel(
        principal.tenant_id,
        TravelOverrideRecord(
            id=uuid4(),
            tenant_id=principal.tenant_id,
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 22),
            zone="Pacific/Auckland",
        ),
    )
    service, _, _ = build(principal, versions, travel=travel)
    aucklands_first_quarter_hour = Interval(
        datetime(2026, 3, 8, 11, 0, tzinfo=UTC), datetime(2026, 3, 8, 11, 15, tzinfo=UTC)
    )

    await service.declare(principal, declaring(aucklands_first_quarter_hour))

    assert versions.bumped == [WeekRange(first=WEEK_11, last=WEEK_11)]


async def test_declaring_a_past_span_bumps_it_too(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # Unlike a budget or a zone change, which govern every week from now on and are floored at
    # the current week, an off-plan span names a bounded set of weeks: a week already lived
    # genuinely reports a different denominator once it is declared off. Only weeks something
    # has planned carry a version row, so a past week with no plan is still never touched.
    last_year = Interval(
        datetime(2025, 3, 7, 14, 0, tzinfo=UTC), datetime(2025, 3, 10, 9, 0, tzinfo=UTC)
    )
    service, _, _ = build(principal, versions)

    await service.declare(principal, declaring(last_year))

    assert versions.bumped == [
        WeekRange(first=IsoWeek.parse("2025-W10"), last=IsoWeek.parse("2025-W11"))
    ]


async def test_removing_bumps_the_weeks_the_span_covered(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    stored = [a_period(principal.tenant_id, FRIDAY)]
    service, periods, _ = build(principal, versions, stored=stored)

    await service.remove(principal, stored[0].id)

    assert periods.rows == []
    assert versions.bumped == [WeekRange(first=WEEK_10, last=WEEK_11)]


async def test_moving_a_span_bumps_the_weeks_it_left_and_the_weeks_it_now_covers(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    stored = [a_period(principal.tenant_id, FRIDAY)]
    service, _, _ = build(principal, versions, stored=stored)
    moved = Interval(
        datetime(2026, 3, 20, 14, 0, tzinfo=UTC), datetime(2026, 3, 23, 9, 0, tzinfo=UTC)
    )

    await service.update(
        principal,
        stored[0].id,
        OffPlanChange(start=moved.start, end=moved.end, keep_frame=ABSENT, label=ABSENT),
    )

    assert versions.bumped == [
        WeekRange(first=WEEK_10, last=WEEK_11),
        WeekRange(first=IsoWeek.parse("2026-W12"), last=IsoWeek.parse("2026-W13")),
    ]


async def test_moving_a_span_onto_a_week_it_already_covered_bumps_that_week_twice(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # The two ranges share W11 without being equal, so both reach the counter and W11 is
    # incremented twice. Recorded as the behavior rather than deduplicated per week: the guard
    # compares a version for equality rather than counting increments, so a second increment costs
    # nothing, and the alternative is a set of weeks where a range is the natural unit.
    spanning_two_weeks = Interval(
        datetime(2026, 3, 6, 14, 0, tzinfo=UTC), datetime(2026, 3, 9, 9, 0, tzinfo=UTC)
    )
    stored = [a_period(principal.tenant_id, spanning_two_weeks)]
    service, _, _ = build(principal, versions, stored=stored)
    moved_forward = Interval(
        datetime(2026, 3, 13, 14, 0, tzinfo=UTC), datetime(2026, 3, 16, 9, 0, tzinfo=UTC)
    )

    await service.update(
        principal,
        stored[0].id,
        OffPlanChange(
            start=moved_forward.start, end=moved_forward.end, keep_frame=ABSENT, label=ABSENT
        ),
    )

    assert versions.bumped == [
        WeekRange(first=WEEK_10, last=WEEK_11),
        WeekRange(first=WEEK_11, last=IsoWeek.parse("2026-W12")),
    ]
    # Both ranges cover W11, and nothing collapses them.
    assert [affected.covers(WEEK_11) for affected in versions.bumped] == [True, True]


async def test_a_change_that_moves_nothing_bumps_its_weeks_once(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # A label-only patch bumps, because every mutation does; what it must not do is bump the same
    # range twice for the two spans that are the same span.
    stored = [a_period(principal.tenant_id, FRIDAY, label="Italy")]
    service, _, _ = build(principal, versions, stored=stored)

    changed = await service.update(
        principal,
        stored[0].id,
        OffPlanChange(start=ABSENT, end=ABSENT, keep_frame=ABSENT, label="Sicily"),
    )

    assert changed.label == "Sicily"
    assert versions.bumped == [WeekRange(first=WEEK_10, last=WEEK_11)]


# --------------------------------------------------------------------------------
# Changing
# --------------------------------------------------------------------------------


async def test_a_patch_is_not_refused_for_overlapping_its_own_stored_self(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # The period being edited is left out of the comparison. Without that, every patch would
    # overlap the row it is patching and nothing could ever be edited.
    stored = [a_period(principal.tenant_id, FRIDAY)]
    service, periods, _ = build(principal, versions, stored=stored)

    changed = await service.update(
        principal,
        stored[0].id,
        OffPlanChange(start=ABSENT, end=ABSENT, keep_frame=True, label=ABSENT),
    )

    assert changed.keep_frame is True
    assert changed.interval == FRIDAY
    assert periods.rows[0].keep_frame is True


async def test_one_bound_may_move_on_its_own(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    stored = [a_period(principal.tenant_id, FRIDAY)]
    service, _, _ = build(principal, versions, stored=stored)
    earlier_end = datetime(2026, 3, 8, 12, 0, tzinfo=UTC)

    changed = await service.update(
        principal,
        stored[0].id,
        OffPlanChange(start=ABSENT, end=earlier_end, keep_frame=ABSENT, label=ABSENT),
    )

    assert changed.interval == Interval(FRIDAY.start, earlier_end)


async def test_a_bound_moved_onto_another_period_is_refused(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    stored = [a_period(principal.tenant_id, FRIDAY), a_period(principal.tenant_id, ABUTTING)]
    service, periods, _ = build(principal, versions, stored=stored)
    into_the_next_period = datetime(2026, 3, 9, 12, 0, tzinfo=UTC)

    with pytest.raises(Conflict):
        await service.update(
            principal,
            stored[0].id,
            OffPlanChange(start=ABSENT, end=into_the_next_period, keep_frame=ABSENT, label=ABSENT),
        )

    assert [row.interval for row in periods.rows] == [FRIDAY, ABUTTING]
    assert versions.bumped == []


async def test_a_patch_may_clear_a_label(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    stored = [a_period(principal.tenant_id, FRIDAY, label="Italy")]
    service, periods, _ = build(principal, versions, stored=stored)

    changed = await service.update(
        principal,
        stored[0].id,
        OffPlanChange(start=ABSENT, end=ABSENT, keep_frame=ABSENT, label=None),
    )

    assert changed.label is None
    assert periods.rows[0].label is None


async def test_a_patch_that_states_nothing_leaves_the_period_as_it_was(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    stored = [a_period(principal.tenant_id, FRIDAY, keep_frame=True, label="Italy")]
    service, _, _ = build(principal, versions, stored=stored)

    changed = await service.update(principal, stored[0].id, unchanged())

    assert changed == stored[0]


async def test_a_patch_moving_a_bound_off_the_grid_is_refused(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    stored = [a_period(principal.tenant_id, FRIDAY)]
    service, periods, _ = build(principal, versions, stored=stored)

    with pytest.raises(ValidationFailed, match="quarter hour"):
        await service.update(
            principal,
            stored[0].id,
            OffPlanChange(
                start=ABSENT,
                end=datetime(2026, 3, 8, 12, 3, tzinfo=UTC),
                keep_frame=ABSENT,
                label=ABSENT,
            ),
        )

    assert periods.rows == stored


async def test_a_patch_that_would_invert_the_period_is_refused(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # The merged PAIR is what is checked, not the field the request sent: this start is a legal
    # instant on its own and is only wrong against the stored end.
    stored = [a_period(principal.tenant_id, FRIDAY)]
    service, periods, _ = build(principal, versions, stored=stored)

    with pytest.raises(ValidationFailed, match="runs forward"):
        await service.update(
            principal,
            stored[0].id,
            OffPlanChange(
                start=datetime(2026, 3, 10, 9, 0, tzinfo=UTC),
                end=ABSENT,
                keep_frame=ABSENT,
                label=ABSENT,
            ),
        )

    assert periods.rows == stored


# --------------------------------------------------------------------------------
# Reading, and the identifiers that answer for nothing
# --------------------------------------------------------------------------------


async def test_the_periods_are_listed_earliest_first(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    stored = [
        a_period(principal.tenant_id, ABUTTING),
        a_period(principal.tenant_id, FRIDAY),
    ]
    service, _, _ = build(principal, versions, stored=stored)

    found = await service.list_all(principal)

    assert [period.interval for period in found] == [FRIDAY, ABUTTING]


async def test_one_period_is_read_by_its_identifier(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    stored = [a_period(principal.tenant_id, FRIDAY, label="Italy")]
    service, _, _ = build(principal, versions, stored=stored)

    assert await service.read(principal, stored[0].id) == stored[0]


@pytest.mark.parametrize("method", ["read", "remove"])
async def test_an_unknown_identifier_is_a_404(
    principal: Principal, versions: RecordingWeekInputVersions, method: str
) -> None:
    service, _, _ = build(principal, versions)

    with pytest.raises(NotFound, match="off-plan period"):
        await getattr(service, method)(principal, uuid4())


async def test_an_unknown_identifier_is_a_404_on_a_patch(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, _, _ = build(principal, versions)

    with pytest.raises(NotFound, match="off-plan period"):
        await service.update(principal, uuid4(), unchanged())


@pytest.mark.parametrize("method", ["read", "remove"])
async def test_another_tenants_period_is_a_404_rather_than_an_edit(
    principal: Principal, versions: RecordingWeekInputVersions, method: str
) -> None:
    # The repository is scoped, so this cannot really be reached over HTTP. The check is defense
    # in depth at the one place a caller supplies an identifier.
    theirs = a_period(uuid4(), FRIDAY)
    service, periods, _ = build(principal, versions, stored=[theirs])

    with pytest.raises(NotFound):
        await getattr(service, method)(principal, theirs.id)

    assert periods.rows == [theirs]


# --------------------------------------------------------------------------------
# Authority
# --------------------------------------------------------------------------------


async def test_a_credential_without_admin_cannot_declare_time_off(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    reader = Principal(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        scopes=frozenset({Scope.PLAN_READ}),
    )
    service, periods, _ = build(principal, versions)

    with pytest.raises(Forbidden):
        await service.declare(reader, declaring(FRIDAY))

    assert periods.rows == []
    # And the read the same credential carries still works.
    assert await service.list_all(reader) == ()


async def test_a_credential_without_plan_read_cannot_read_time_off(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    without = Principal(
        tenant_id=principal.tenant_id, user_id=principal.user_id, scopes=frozenset()
    )
    stored = [a_period(principal.tenant_id, FRIDAY)]
    service, _, _ = build(principal, versions, stored=stored)

    with pytest.raises(Forbidden):
        await service.list_all(without)
    with pytest.raises(Forbidden):
        await service.read(without, stored[0].id)


# --------------------------------------------------------------------------------
# The fixture's own span, through the service
# --------------------------------------------------------------------------------


async def test_the_fixtures_friday_to_monday_span_is_one_record_over_two_weeks(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, periods, _ = build(principal, versions)

    created = await service.declare(
        principal,
        declaring(
            OFF_PLAN_WEEK.off_plan,
            keep_frame=OFF_PLAN_WEEK.keeping_frame.keep_frame,
            label=OFF_PLAN_WEEK.keeping_frame.label,
        ),
    )

    assert len(periods.rows) == 1
    assert created.interval.total_minutes() == OFF_PLAN_WEEK.off_plan_minutes
    # 68 elapsed hours, not the 67 its two wall times differ by: the clocks go back inside it.
    assert created.interval.total_minutes() == OFF_PLAN_WEEK.off_plan_wall_minutes + 60
    assert versions.bumped == [
        WeekRange(first=OFF_PLAN_WEEK.iso_week, last=OFF_PLAN_WEEK.following_week)
    ]
    # Both weeks read the whole record; neither reads a clipped copy of it.
    for week in (OFF_PLAN_WEEK.iso_week, OFF_PLAN_WEEK.following_week):
        found = await periods.for_span(week_span(week, OFF_PLAN_WEEK.profile))
        assert [period.interval for period in found] == [OFF_PLAN_WEEK.off_plan]
