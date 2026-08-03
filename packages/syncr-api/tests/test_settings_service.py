"""The settings service against fakes: the zone reading, the rejections, and the bump.

The repositories are replaced and the clock is injected, so "today" is a literal date and
the week the bump floors at is assertable without waiting for a Monday. Everything else is
real: ``ZoneProfile``, ``active_zone``, and the tz database all run as they do in
production, because those are the parts that would be wrong silently.

The tests worth reading are the ones about what does NOT happen. A read writes nothing. A
visible-hours change bumps nothing, because the grid's zoom is not a solve input. A past
travel override bumps nothing, because a past week keeps the span it was computed with.

Every date here is a real date with a real weekday. ``2026-08-02`` is the Sunday that
closes ``2026-W31``; ``2026-03-29`` is the spring-forward date in ``Europe/London``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syncr_api.core.errors import Conflict, NotFound, ValidationFailed
from syncr_api.core.principal import Principal
from syncr_api.core.scopes import ALL_SCOPES
from syncr_api.user_settings.config import (
    DAY_END_DEFAULT,
    DAY_START_DEFAULT,
    HOME_ZONE_DEFAULT,
    REVIEW_CADENCE_DEFAULT,
    VISIBLE_HOURS_DEFAULT,
    ReviewCadence,
)
from syncr_api.user_settings.records import SettingsRecord, TravelOverrideRecord
from syncr_api.user_settings.repository import SettingsRepository, TravelOverrideRepository
from syncr_api.user_settings.service import SettingsChange, SettingsService
from syncr_api.user_settings.solve_inputs import WeekRange
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from syncr_api.user_settings.records import TravelOverrideId
    from syncr_domain.identifiers import TenantId

LONDON = "Europe/London"
TOKYO = "Asia/Tokyo"

# A Sunday, the last day of 2026-W31, at 09:00 UTC: mid-morning in London and evening in
# Tokyo, so the local date is the same in both and the tests are about zones rather than
# about a date boundary.
NOW = datetime(2026, 8, 2, 9, 0, tzinfo=UTC)
TODAY = date(2026, 8, 2)
WEEK_31 = IsoWeek.parse("2026-W31")
WEEK_32 = IsoWeek.parse("2026-W32")


class FakeSettingsRepository(SettingsRepository):
    """The real repository's interface over one optional record, and no database."""

    def __init__(self, tenant_id: TenantId, stored: SettingsRecord | None = None) -> None:
        self._tenant_id = tenant_id
        self.stored = stored
        self.locks = 0

    async def read(self) -> SettingsRecord:
        return self.stored if self.stored is not None else self.defaults()

    async def lock(self, *, created_at: datetime) -> SettingsRecord:
        self.locks += 1
        if self.stored is None:
            self.stored = self.defaults()
        return self.stored

    async def write(
        self,
        *,
        visible_hours: int,
        day_start: time,
        day_end: time,
        review_cadence: ReviewCadence,
        home_zone: str,
    ) -> SettingsRecord:
        self.stored = SettingsRecord(
            tenant_id=self._tenant_id,
            visible_hours=visible_hours,
            day_start=day_start,
            day_end=day_end,
            review_cadence=review_cadence,
            home_zone=home_zone,
        )
        return self.stored


class FakeTravelOverrideRepository(TravelOverrideRepository):
    """Records what was written, so the service's effects are assertable."""

    def __init__(self, tenant_id: TenantId, stored: list[TravelOverrideRecord]) -> None:
        self._tenant_id = tenant_id
        self.rows = list(stored)

    async def list_all(self) -> tuple[TravelOverrideRecord, ...]:
        return tuple(sorted(self.rows, key=lambda row: (row.start_date, row.end_date)))

    async def find(self, override_id: TravelOverrideId) -> TravelOverrideRecord | None:
        return next((row for row in self.rows if row.id == override_id), None)

    async def create(
        self, *, start_date: date, end_date: date, zone: str, created_at: datetime
    ) -> TravelOverrideRecord:
        created = TravelOverrideRecord(
            id=uuid4(),
            tenant_id=self._tenant_id,
            start_date=start_date,
            end_date=end_date,
            zone=zone,
        )
        self.rows.append(created)
        return created

    async def remove(self, override_id: TravelOverrideId) -> None:
        self.rows = [row for row in self.rows if row.id != override_id]


class RecordingWeekInputVersions:
    """Every range the service asked to have bumped, in order."""

    def __init__(self) -> None:
        self.bumped: list[WeekRange] = []

    async def bump(self, weeks: WeekRange) -> None:
        self.bumped.append(weeks)


@pytest.fixture
def principal() -> Principal:
    # One construction site on purpose. The principal's shape is owned elsewhere, and the
    # OAuth slice is widening it in this same wave: a browser session carries every scope,
    # because the user is acting directly, so that is what a stand-in for one carries.
    return Principal(tenant_id=uuid4(), user_id=uuid4(), scopes=ALL_SCOPES)


@pytest.fixture
def versions() -> RecordingWeekInputVersions:
    return RecordingWeekInputVersions()


def build_service(
    principal: Principal,
    versions: RecordingWeekInputVersions,
    *,
    stored: SettingsRecord | None = None,
    overrides: list[TravelOverrideRecord] | None = None,
) -> tuple[SettingsService, FakeSettingsRepository, FakeTravelOverrideRepository]:
    settings = FakeSettingsRepository(principal.tenant_id, stored)
    travel = FakeTravelOverrideRepository(principal.tenant_id, overrides or [])
    service = SettingsService(
        settings=settings, overrides=travel, versions=versions, clock=lambda: NOW
    )
    return service, settings, travel


def a_record(tenant_id: TenantId, **changes: object) -> SettingsRecord:
    fields: dict[str, object] = {
        "tenant_id": tenant_id,
        "visible_hours": VISIBLE_HOURS_DEFAULT,
        "day_start": DAY_START_DEFAULT,
        "day_end": DAY_END_DEFAULT,
        "review_cadence": REVIEW_CADENCE_DEFAULT,
        "home_zone": LONDON,
    }
    return SettingsRecord(**{**fields, **changes})  # type: ignore[arg-type]


def an_override(
    tenant_id: TenantId, start_date: date, end_date: date, zone: str = TOKYO
) -> TravelOverrideRecord:
    return TravelOverrideRecord(
        id=uuid4(), tenant_id=tenant_id, start_date=start_date, end_date=end_date, zone=zone
    )


# --------------------------------------------------------------------------------
# Reading. The defaults, and the zone active today.
# --------------------------------------------------------------------------------


async def test_a_tenant_with_no_row_reads_the_declared_defaults(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, settings, _ = build_service(principal, versions)

    view = await service.read(principal)

    assert view.visible_hours == VISIBLE_HOURS_DEFAULT == 12
    assert (view.day_start, view.day_end) == (DAY_START_DEFAULT, DAY_END_DEFAULT)
    assert view.review_cadence == REVIEW_CADENCE_DEFAULT
    assert view.home_zone == HOME_ZONE_DEFAULT
    # The read is a read: no row was created and no lock was taken to create one.
    assert settings.stored is None
    assert settings.locks == 0


async def test_the_read_states_the_home_zone_when_no_override_covers_today(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, _, _ = build_service(
        principal,
        versions,
        stored=a_record(principal.tenant_id),
        overrides=[an_override(principal.tenant_id, date(2026, 9, 1), date(2026, 9, 10))],
    )

    view = await service.read(principal)

    assert view.active_zone == LONDON
    assert view.active_zone_date == TODAY


@pytest.mark.parametrize(
    ("start_date", "end_date", "expected"),
    [
        # Today inside the range.
        (date(2026, 8, 1), date(2026, 8, 5), TOKYO),
        # Inclusive at the start: today IS the first day.
        (TODAY, date(2026, 8, 5), TOKYO),
        # Inclusive at the end: today IS the last day.
        (date(2026, 7, 20), TODAY, TOKYO),
        # Ending yesterday, so the home zone is back.
        (date(2026, 7, 20), date(2026, 8, 1), LONDON),
        # Starting tomorrow.
        (date(2026, 8, 3), date(2026, 8, 5), LONDON),
    ],
)
async def test_the_active_zone_is_resolved_inclusively_at_both_ends(
    principal: Principal,
    versions: RecordingWeekInputVersions,
    start_date: date,
    end_date: date,
    expected: str,
) -> None:
    # Four of these five cases distinguish an inclusive range from an exclusive one, which
    # is what makes this a test of `active_zone` rather than of the plumbing around it.
    service, _, _ = build_service(
        principal,
        versions,
        stored=a_record(principal.tenant_id),
        overrides=[an_override(principal.tenant_id, start_date, end_date)],
    )

    view = await service.read(principal)

    assert view.active_zone == expected


async def test_the_active_date_is_the_local_date_in_the_home_zone(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # 2026-08-02T23:30Z is still Sunday in London and already Monday in Auckland, so the
    # date the zone is resolved for is a real choice rather than an accident of UTC.
    late = datetime(2026, 8, 2, 23, 30, tzinfo=UTC)
    settings = FakeSettingsRepository(
        principal.tenant_id, a_record(principal.tenant_id, home_zone="Pacific/Auckland")
    )
    service = SettingsService(
        settings=settings,
        overrides=FakeTravelOverrideRepository(principal.tenant_id, []),
        versions=versions,
        clock=lambda: late,
    )

    view = await service.read(principal)

    assert view.active_zone_date == date(2026, 8, 3)


# --------------------------------------------------------------------------------
# Updating. What merges, what is rejected, and what bumps.
# --------------------------------------------------------------------------------


async def test_a_patch_changes_only_the_fields_it_names(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    stored = a_record(principal.tenant_id, visible_hours=8, review_cadence=ReviewCadence.QUARTERLY)
    service, settings, _ = build_service(principal, versions, stored=stored)

    view = await service.update(principal, SettingsChange(visible_hours=18))

    assert view.visible_hours == 18
    assert view.review_cadence == ReviewCadence.QUARTERLY
    assert view.home_zone == LONDON
    assert settings.stored == a_record(
        principal.tenant_id, visible_hours=18, review_cadence=ReviewCadence.QUARTERLY
    )


async def test_an_empty_patch_leaves_every_value_as_it_was(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    stored = a_record(principal.tenant_id, visible_hours=8)
    service, settings, _ = build_service(principal, versions, stored=stored)

    await service.update(principal, SettingsChange())

    assert settings.stored == stored
    assert versions.bumped == []


async def test_changing_the_home_zone_bumps_the_current_week_and_every_week_after_it(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, settings, _ = build_service(principal, versions, stored=a_record(principal.tenant_id))

    view = await service.update(principal, SettingsChange(home_zone=TOKYO))

    assert view.home_zone == view.active_zone == TOKYO
    assert settings.stored is not None
    assert settings.stored.home_zone == TOKYO
    assert versions.bumped == [WeekRange(first=WEEK_31, last=None)]


async def test_rewriting_the_home_zone_with_the_same_value_bumps_nothing(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # The control for the bump above: it fires on a CHANGE, not on a write. A screen that
    # PATCHes every field it renders must not enqueue a solve for every save.
    service, _, _ = build_service(principal, versions, stored=a_record(principal.tenant_id))

    await service.update(principal, SettingsChange(home_zone=LONDON))

    assert versions.bumped == []


@pytest.mark.parametrize(
    "change",
    [
        SettingsChange(visible_hours=24),
        SettingsChange(day_start=time(5, 0)),
        SettingsChange(day_end=time(22, 0)),
        SettingsChange(review_cadence=ReviewCadence.QUARTERLY),
    ],
)
async def test_a_geometry_or_cadence_change_is_not_a_solve_input_mutation(
    principal: Principal, versions: RecordingWeekInputVersions, change: SettingsChange
) -> None:
    # Visible hours and the day bounds set the Week grid's axis, and the cadence decides
    # when the pie review is offered. None of the three changes what a solve reads, so
    # bumping would enqueue a solve that could only reproduce the same plan.
    service, _, _ = build_service(principal, versions, stored=a_record(principal.tenant_id))

    await service.update(principal, change)

    assert versions.bumped == []


@pytest.mark.parametrize(
    "change",
    [
        SettingsChange(day_start=time(23, 0)),
        SettingsChange(day_end=time(6, 0)),
        SettingsChange(day_start=time(9, 0), day_end=time(9, 0)),
    ],
)
async def test_day_bounds_that_describe_no_day_are_rejected(
    principal: Principal, versions: RecordingWeekInputVersions, change: SettingsChange
) -> None:
    # Two of these three patch ONE bound, which is why the rule is stated over the merged
    # record: the pair has to make sense, and half of it arrives in the request.
    service, settings, _ = build_service(principal, versions, stored=a_record(principal.tenant_id))

    with pytest.raises(ValidationFailed, match="earlier than day end"):
        await service.update(principal, change)

    assert settings.stored == a_record(principal.tenant_id)


@pytest.mark.parametrize("visible_hours", [5, 25, 0, -1])
async def test_visible_hours_outside_the_zoom_range_is_rejected(
    principal: Principal, versions: RecordingWeekInputVersions, visible_hours: int
) -> None:
    # The request schema bounds this field as well. Restated in the service because the
    # service is a public interface: a caller reaching it without FastAPI would otherwise
    # get an IntegrityError from the CHECK constraint where the day bounds give a 422.
    service, settings, _ = build_service(principal, versions, stored=a_record(principal.tenant_id))

    with pytest.raises(ValidationFailed, match="zoom range"):
        await service.update(principal, SettingsChange(visible_hours=visible_hours))

    assert settings.stored == a_record(principal.tenant_id)
    assert versions.bumped == []


@pytest.mark.parametrize("zone", ["Europe", "Europe/Lundon", "", "x" * 65, "US"])
async def test_a_home_zone_the_tz_database_does_not_name_is_rejected(
    principal: Principal, versions: RecordingWeekInputVersions, zone: str
) -> None:
    # `Europe` and `US` are DIRECTORIES in the tz tree, and an over-length key fails
    # inside `zoneinfo` as a plain OS error. Every shape arrives here as one domain error,
    # which is why one clause covers all five and none of them is a 500.
    service, settings, _ = build_service(principal, versions, stored=a_record(principal.tenant_id))

    with pytest.raises(ValidationFailed, match="home zone was not accepted") as refused:
        await service.update(principal, SettingsChange(home_zone=zone))

    # The remedy names the field's own vocabulary, which is what separates this rejection
    # from the other thing the zone layer refuses through the same error type.
    assert "IANA" in refused.value.detail
    assert settings.stored == a_record(principal.tenant_id)
    assert versions.bumped == []


# --------------------------------------------------------------------------------
# Travel overrides. The 409, the adjacency rule, and the weeks each one invalidates.
# --------------------------------------------------------------------------------


async def test_declaring_an_override_stores_it_and_bumps_the_weeks_it_covers(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, _, travel = build_service(principal, versions, stored=a_record(principal.tenant_id))

    created = await service.declare_travel_override(
        principal, start_date=date(2026, 8, 4), end_date=date(2026, 8, 6), zone=TOKYO
    )

    assert created.zone == TOKYO
    assert [row.id for row in travel.rows] == [created.id]
    assert versions.bumped == [WeekRange(first=WEEK_32, last=WEEK_32)]


async def test_an_overlapping_declaration_is_refused_with_both_ranges_named(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    existing = an_override(principal.tenant_id, date(2026, 8, 4), date(2026, 8, 10))
    service, _, travel = build_service(
        principal, versions, stored=a_record(principal.tenant_id), overrides=[existing]
    )

    with pytest.raises(Conflict) as refused:
        await service.declare_travel_override(
            principal, start_date=date(2026, 8, 8), end_date=date(2026, 8, 12), zone="Asia/Seoul"
        )

    assert "2026-08-04" in refused.value.detail
    assert "2026-08-08" in refused.value.detail
    assert refused.value.status == 409
    # Nothing was stored, and no solve was invalidated by a declaration that did not land.
    assert [row.id for row in travel.rows] == [existing.id]
    assert versions.bumped == []


@pytest.mark.parametrize(
    ("start_date", "end_date"),
    [
        # Abutting after: the existing range ends on the 10th, this one opens on the 11th.
        (date(2026, 8, 11), date(2026, 8, 14)),
        # Abutting before.
        (date(2026, 8, 1), date(2026, 8, 3)),
    ],
)
async def test_two_ranges_that_abut_exactly_are_both_allowed(
    principal: Principal,
    versions: RecordingWeekInputVersions,
    start_date: date,
    end_date: date,
) -> None:
    # Adjacency is not overlap. The domain owns that rule, and this is the boundary
    # honoring it rather than restating it as a comparison of its own.
    existing = an_override(principal.tenant_id, date(2026, 8, 4), date(2026, 8, 10))
    service, _, travel = build_service(
        principal, versions, stored=a_record(principal.tenant_id), overrides=[existing]
    )

    await service.declare_travel_override(
        principal, start_date=start_date, end_date=end_date, zone="Asia/Seoul"
    )

    assert len(travel.rows) == 2


async def test_a_range_that_ends_before_it_starts_is_rejected(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # A reversed range is not a zone problem, so the rejection does not offer a zone
    # identifier as its remedy. The wire rejects the pair at the schema, naming `endDate`;
    # this is the same refusal for a caller who reaches the service directly.
    service, _, travel = build_service(principal, versions, stored=a_record(principal.tenant_id))

    with pytest.raises(ValidationFailed, match="start_date <= end_date") as refused:
        await service.declare_travel_override(
            principal, start_date=date(2026, 8, 10), end_date=date(2026, 8, 4), zone=TOKYO
        )

    assert "IANA" not in refused.value.detail
    assert travel.rows == []


@pytest.mark.parametrize("zone", ["Europe", "Mars/Olympus", "x" * 65])
async def test_an_override_zone_the_tz_database_does_not_name_is_rejected(
    principal: Principal, versions: RecordingWeekInputVersions, zone: str
) -> None:
    service, _, travel = build_service(principal, versions, stored=a_record(principal.tenant_id))

    with pytest.raises(ValidationFailed, match="zone was not accepted"):
        await service.declare_travel_override(
            principal, start_date=date(2026, 8, 4), end_date=date(2026, 8, 6), zone=zone
        )

    assert travel.rows == []
    assert versions.bumped == []


async def test_declaring_an_override_that_begins_on_a_monday_bumps_the_week_before_it(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # 2026-08-03 is a Monday. The preceding week's span ENDS at that Monday's local
    # midnight, so its length changes even though none of its own days are in the range.
    service, _, _ = build_service(principal, versions, stored=a_record(principal.tenant_id))

    await service.declare_travel_override(
        principal, start_date=date(2026, 8, 3), end_date=date(2026, 8, 5), zone=TOKYO
    )

    assert versions.bumped == [WeekRange(first=WEEK_31, last=WEEK_32)]


async def test_declaring_a_past_range_bumps_nothing(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # Backfilling a trip that already happened. Those weeks keep the span they were
    # computed with, because an approved revision is immutable.
    service, _, travel = build_service(principal, versions, stored=a_record(principal.tenant_id))

    await service.declare_travel_override(
        principal, start_date=date(2026, 7, 6), end_date=date(2026, 7, 10), zone=TOKYO
    )

    assert len(travel.rows) == 1
    assert versions.bumped == []


async def test_removing_an_override_bumps_the_weeks_it_had_covered(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    existing = an_override(principal.tenant_id, date(2026, 8, 4), date(2026, 8, 6))
    service, _, travel = build_service(
        principal, versions, stored=a_record(principal.tenant_id), overrides=[existing]
    )

    await service.remove_travel_override(principal, existing.id)

    assert travel.rows == []
    assert versions.bumped == [WeekRange(first=WEEK_32, last=WEEK_32)]


async def test_removing_an_override_that_does_not_exist_is_a_404(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, _, _ = build_service(principal, versions, stored=a_record(principal.tenant_id))

    with pytest.raises(NotFound, match="No travel override matches"):
        await service.remove_travel_override(principal, uuid4())

    assert versions.bumped == []


async def test_a_declaration_is_serialized_on_the_tenants_own_settings_row(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # The lock is what makes the overlap check atomic per tenant: two declarations racing
    # would otherwise both read the same rows, both pass, and both insert. The integration
    # tier proves the lock actually blocks; this proves the service takes it.
    service, settings, _ = build_service(principal, versions)

    await service.declare_travel_override(
        principal, start_date=date(2026, 8, 4), end_date=date(2026, 8, 6), zone=TOKYO
    )

    assert settings.locks == 1


async def test_listing_returns_every_override_in_date_order(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    later = an_override(principal.tenant_id, date(2026, 9, 1), date(2026, 9, 5))
    earlier = an_override(principal.tenant_id, date(2026, 8, 4), date(2026, 8, 6))
    service, _, _ = build_service(
        principal,
        versions,
        stored=a_record(principal.tenant_id),
        overrides=[later, earlier],
    )

    listed = await service.list_travel_overrides(principal)

    assert [row.id for row in listed] == [earlier.id, later.id]
