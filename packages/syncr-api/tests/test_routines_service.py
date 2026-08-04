"""The routine service against fakes: the inelastic default, the merged span, and the bump.

The repository is replaced and the clock is injected, so "today" is a literal date and the week
the bump floors at is assertable without waiting for a Monday. The span's invariants are NOT
faked: ``RoutineSpan`` is the real domain type throughout, because a stubbed invariant would let
this suite pass while a routine with no duration reached the frame.

The tests worth reading are the ones about what a request cannot do. A floor above its target is
refused, and so is lowering a target below a stored floor: those are one violation seen from two
sides, which is why the rule is stated over the MERGED row rather than over either request. And
every mutation bumps the week input version, a rename included, because the frame is the
denominator every Area's share is measured against.
"""

from __future__ import annotations

import inspect
from dataclasses import fields
from datetime import UTC, date, datetime, time
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syncr_api.core.errors import Forbidden, NotFound, ValidationFailed
from syncr_api.core.patches import ABSENT
from syncr_api.core.principal import Principal
from syncr_api.core.scopes import ALL_SCOPES, Scope
from syncr_api.routines.declarations import RoutineChange, RoutineDeclaration
from syncr_api.routines.records import RoutineRecord
from syncr_api.routines.repository import RoutineRepository
from syncr_api.routines.schemas import RoutineCreateRequest, RoutinePatchRequest, RoutineResponse
from syncr_api.routines.service import RoutineService
from syncr_api.user_settings.config import ReviewCadence
from syncr_api.user_settings.records import SettingsRecord
from syncr_api.user_settings.repository import SettingsRepository
from syncr_api.user_settings.schemas import SettingsPatchRequest, SettingsResponse
from syncr_api.user_settings.service import SettingsChange
from syncr_api.user_settings.solve_inputs import WeekRange
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from syncr_api.routines.records import RoutineId
    from syncr_domain.identifiers import TenantId

LONDON = "Europe/London"

# A Sunday, the last day of 2026-W31, at 09:00 UTC: mid-morning in London, so the local date and
# the UTC date agree and these tests are about the frame rather than about a date boundary.
NOW = datetime(2026, 8, 2, 9, 0, tzinfo=UTC)
WEEK_31 = IsoWeek.parse("2026-W31")

SLEEP_TARGET = time(23, 0)
SLEEP_MINUTES = 8 * 60


class FakeRoutineRepository(RoutineRepository):
    """The real repository's interface over a list of records, and no database."""

    def __init__(self, tenant_id: TenantId, stored: list[RoutineRecord] | None = None) -> None:
        self._tenant_id = tenant_id
        self.rows = list(stored or [])

    async def list_all(self) -> tuple[RoutineRecord, ...]:
        return tuple(sorted(self.rows, key=lambda row: (row.target_time, row.id)))

    async def find(self, routine_id: RoutineId) -> RoutineRecord | None:
        return next((row for row in self.rows if row.id == routine_id), None)

    async def create(
        self,
        *,
        title: str,
        target_time: time,
        duration_minutes: int,
        min_duration_minutes: int,
        flex_band_minutes: int,
        created_at: datetime,
    ) -> RoutineRecord:
        created = RoutineRecord(
            id=uuid4(),
            tenant_id=self._tenant_id,
            title=title,
            target_time=target_time,
            duration_minutes=duration_minutes,
            min_duration_minutes=min_duration_minutes,
            flex_band_minutes=flex_band_minutes,
            created_at=created_at,
        )
        self.rows.append(created)
        return created

    async def write(
        self,
        routine_id: RoutineId,
        *,
        title: str,
        target_time: time,
        duration_minutes: int,
        min_duration_minutes: int,
        flex_band_minutes: int,
    ) -> None:
        self.rows = [
            RoutineRecord(
                id=row.id,
                tenant_id=row.tenant_id,
                title=title,
                target_time=target_time,
                duration_minutes=duration_minutes,
                min_duration_minutes=min_duration_minutes,
                flex_band_minutes=flex_band_minutes,
                created_at=row.created_at,
            )
            if row.id == routine_id
            else row
            for row in self.rows
        ]

    async def remove(self, routine_id: RoutineId) -> None:
        self.rows = [row for row in self.rows if row.id != routine_id]


class FakeSettingsRepository(SettingsRepository):
    """One settings row, for the home zone the bump's floor is resolved in."""

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


def build(
    principal: Principal, versions: RecordingWeekInputVersions
) -> tuple[RoutineService, FakeRoutineRepository]:
    routines = FakeRoutineRepository(principal.tenant_id)
    service = RoutineService(
        routines=routines,
        settings=FakeSettingsRepository(principal.tenant_id),
        versions=versions,
        clock=lambda: NOW,
    )
    return service, routines


def a_declaration(**changes: object) -> RoutineDeclaration:
    fields_: dict[str, object] = {
        "title": "Sleep",
        "target_time": SLEEP_TARGET,
        "duration_minutes": SLEEP_MINUTES,
        "min_duration_minutes": None,
        "flex_band_minutes": 0,
    }
    return RoutineDeclaration(**{**fields_, **changes})  # type: ignore[arg-type]


def a_change(**changes: object) -> RoutineChange:
    fields_: dict[str, object] = {
        "title": ABSENT,
        "target_time": ABSENT,
        "duration_minutes": ABSENT,
        "min_duration_minutes": ABSENT,
        "flex_band_minutes": ABSENT,
    }
    return RoutineChange(**{**fields_, **changes})  # type: ignore[arg-type]


async def declare(
    service: RoutineService, principal: Principal, **changes: object
) -> RoutineRecord:
    return await service.create(principal, a_declaration(**changes))


# --------------------------------------------------------------------------------
# A span, and the floor that defaults to it
# --------------------------------------------------------------------------------


async def test_a_new_routine_is_inelastic_unless_the_caller_says_otherwise(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, _ = build(principal, versions)

    created = await declare(service, principal)

    assert created.min_duration_minutes == created.duration_minutes
    assert created.as_span().is_elastic is False


async def test_a_declaration_may_give_a_routine_an_elastic_range(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # The sleep floor: the one field that makes a routine negotiable. Nothing about it is
    # sleep-specific, so the same declaration would make `Lunch` compressible.
    service, _ = build(principal, versions)

    created = await declare(service, principal, min_duration_minutes=6 * 60)

    assert created.min_duration_minutes == 6 * 60
    assert created.as_span().is_elastic is True


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"duration_minutes": 0}, "durationMinutes"),
        ({"min_duration_minutes": SLEEP_MINUTES + 1}, "minDurationMinutes"),
        ({"min_duration_minutes": 0}, "minDurationMinutes"),
        ({"flex_band_minutes": -1}, "flexBandMinutes"),
        ({"target_time": time(5, 0, tzinfo=UTC)}, "targetTime"),
        ({"target_time": time(5, 0, 30)}, "targetTime"),
    ],
    ids=[
        "no duration",
        "a floor above the target",
        "a floor of nothing",
        "a negative band",
        "a target time carrying a zone",
        "a target time carrying a second",
    ],
)
async def test_a_refused_span_is_a_422_naming_its_field_and_is_not_stored(
    principal: Principal,
    versions: RecordingWeekInputVersions,
    changes: dict[str, object],
    field: str,
) -> None:
    service, routines = build(principal, versions)

    with pytest.raises(ValidationFailed) as refused:
        await declare(service, principal, **changes)

    assert refused.value.errors is not None
    assert [error.field for error in refused.value.errors] == [field]
    assert routines.rows == []
    assert versions.bumped == []


async def test_the_reason_a_routine_was_refused_reaches_the_caller(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # 422 with a stated reason, not a bare status: a routine without a duration is refused
    # because there would be nothing to subtract from the day.
    service, _ = build(principal, versions)

    with pytest.raises(ValidationFailed) as refused:
        await declare(service, principal, duration_minutes=0)

    assert "nothing to subtract" in refused.value.detail
    assert "Nothing was changed" in refused.value.detail


# --------------------------------------------------------------------------------
# A target and a floor are legal only with respect to each other
# --------------------------------------------------------------------------------


async def test_lowering_a_target_below_a_stored_floor_is_refused(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # The violation from the other side. A request naming only the duration cannot be judged on
    # its own, which is why the span is built from the merged row.
    service, routines = build(principal, versions)
    created = await declare(service, principal, min_duration_minutes=6 * 60)
    versions.bumped.clear()

    with pytest.raises(ValidationFailed) as refused:
        await service.update(principal, created.id, a_change(duration_minutes=5 * 60))

    assert refused.value.errors is not None
    assert [error.field for error in refused.value.errors] == ["minDurationMinutes"]
    # Refused means not written, and not bumped either: an invalidated week for a rejected
    # request would discard a running solve for nothing.
    assert routines.rows[0].duration_minutes == SLEEP_MINUTES
    assert versions.bumped == []


async def test_shortening_an_inelastic_routine_has_to_state_the_floor_too(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # The sharp edge of the equality default, pinned rather than discovered. A routine whose
    # floor IS its target cannot be shortened by a request naming only the duration, because the
    # merged row would put the floor above the target. The refusal names the remedy, and
    # lengthening one is unaffected.
    service, routines = build(principal, versions)
    created = await declare(service, principal)

    with pytest.raises(ValidationFailed) as refused:
        await service.update(principal, created.id, a_change(duration_minutes=7 * 60))

    assert "send both in one request" in refused.value.detail
    assert routines.rows[0].duration_minutes == SLEEP_MINUTES

    both = await service.update(
        principal, created.id, a_change(duration_minutes=7 * 60, min_duration_minutes=7 * 60)
    )
    assert (both.duration_minutes, both.min_duration_minutes) == (7 * 60, 7 * 60)
    assert both.as_span().is_elastic is False


async def test_a_target_and_a_floor_may_move_together_in_one_request(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # The control for the refusal above: the pair is legal, so it must not be the ordering that
    # decides. Both stated in one request is the remedy the refusal names.
    service, _ = build(principal, versions)
    created = await declare(service, principal, min_duration_minutes=6 * 60)

    changed = await service.update(
        principal,
        created.id,
        a_change(duration_minutes=5 * 60, min_duration_minutes=4 * 60),
    )

    assert (changed.duration_minutes, changed.min_duration_minutes) == (5 * 60, 4 * 60)


async def test_a_patch_changes_only_what_it_names(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, _ = build(principal, versions)
    created = await declare(service, principal, flex_band_minutes=30)

    changed = await service.update(principal, created.id, a_change(title="Sleep, properly"))

    assert changed.title == "Sleep, properly"
    assert changed.target_time == SLEEP_TARGET
    assert changed.duration_minutes == SLEEP_MINUTES
    assert changed.flex_band_minutes == 30


async def test_the_floor_is_set_through_a_patch(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # The sleep floor's one home, at this layer: a routine created inelastic becomes negotiable
    # through its own PATCH and through nothing else.
    service, routines = build(principal, versions)
    created = await declare(service, principal)

    changed = await service.update(principal, created.id, a_change(min_duration_minutes=6 * 60))

    assert changed.as_span().is_elastic is True
    assert routines.rows[0].min_duration_minutes == 6 * 60


# --------------------------------------------------------------------------------
# The frame is the denominator, so every mutation bumps
# --------------------------------------------------------------------------------


async def test_declaring_a_routine_bumps_every_week_from_this_one(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, _ = build(principal, versions)

    await declare(service, principal)

    # From the week holding today's local date, with no end: the frame governs every week the
    # user has not yet lived, and a past week keeps the inputs it was computed with.
    assert versions.bumped == [WeekRange(first=WEEK_31, last=None)]


@pytest.mark.parametrize(
    "change",
    [
        {"target_time": time(22, 30)},
        {"duration_minutes": 9 * 60},
        {"min_duration_minutes": 6 * 60},
        {"flex_band_minutes": 45},
        {"title": "Sleep, properly"},
    ],
    ids=["a target time", "a duration", "the floor", "the band", "a title"],
)
async def test_every_change_to_the_frame_bumps_every_week_from_this_one(
    principal: Principal, versions: RecordingWeekInputVersions, change: dict[str, object]
) -> None:
    # Wider than the Area service's rule, which leaves a rename alone. A routine's title reaches
    # the plan document as a block label, so a stale one would survive in an approved week.
    service, _ = build(principal, versions)
    created = await declare(service, principal)
    versions.bumped.clear()

    await service.update(principal, created.id, a_change(**change))

    assert versions.bumped == [WeekRange(first=WEEK_31, last=None)]


async def test_removing_a_routine_bumps_every_week_from_this_one(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # Removing a frame entry GROWS discretionary time, so the denominator changes as surely as
    # declaring one shrinks it.
    service, routines = build(principal, versions)
    created = await declare(service, principal)
    versions.bumped.clear()

    await service.remove(principal, created.id)

    assert routines.rows == []
    assert versions.bumped == [WeekRange(first=WEEK_31, last=None)]


async def test_the_week_the_bump_floors_at_is_the_one_holding_today(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # The clock is injected, so this is a literal date rather than whatever day the suite runs
    # on. 2026-08-02 is the Sunday that closes 2026-W31.
    assert IsoWeek.containing(date(2026, 8, 2)) == WEEK_31
    service, _ = build(principal, versions)

    await declare(service, principal)

    assert versions.bumped[0].first == WEEK_31


async def test_reading_routines_writes_nothing_and_bumps_nothing(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, routines = build(principal, versions)

    await service.list_all(principal)

    assert routines.rows == []
    assert versions.bumped == []


async def test_routines_are_listed_in_the_order_the_day_runs(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, _ = build(principal, versions)
    await declare(service, principal, title="Sleep", target_time=time(23, 0))
    await declare(service, principal, title="Wake", target_time=time(5, 0), duration_minutes=30)
    await declare(service, principal, title="Lunch", target_time=time(12, 30), duration_minutes=45)

    assert [row.title for row in await service.list_all(principal)] == ["Wake", "Lunch", "Sleep"]


# --------------------------------------------------------------------------------
# A routine carries no Area
# --------------------------------------------------------------------------------


def test_no_shape_in_this_module_carries_an_area() -> None:
    # The entity-level half of "routines are excluded from Area budget arithmetic". Ticket 9's
    # frame-only-week test asserts the arithmetic; this asserts that no path exists to give a
    # routine an Area in the first place, so the two cannot disagree.
    named = [
        *(field.name for field in fields(RoutineRecord)),
        *(field.name for field in fields(RoutineDeclaration)),
        *(field.name for field in fields(RoutineChange)),
        *RoutineResponse.model_fields,
        *RoutineCreateRequest.model_fields,
        *RoutinePatchRequest.model_fields,
        *inspect.signature(RoutineRepository.create).parameters,
        *inspect.signature(RoutineRepository.write).parameters,
    ]

    assert named, "the walk found no fields, so this rule would pass on an empty reading"
    assert [name for name in named if "area" in name.lower() or "pigment" in name.lower()] == []


@pytest.mark.parametrize("shape", [RoutineCreateRequest, RoutinePatchRequest])
async def test_a_request_naming_an_area_is_refused_rather_than_ignored(shape: type) -> None:
    # Forbidding the unknown field is what makes the absence a stated 422 instead of a value
    # quietly dropped, which is how an earlier draft of the sleep floor went unread.
    with pytest.raises(ValueError, match=r"area_id|areaId|Extra inputs"):
        shape(title="Sleep", targetTime="23:00", durationMinutes=480, areaId=str(uuid4()))


# --------------------------------------------------------------------------------
# The sleep floor has exactly one home
# --------------------------------------------------------------------------------


def test_the_floor_is_a_routine_field_and_settings_has_no_field_for_it() -> None:
    # An earlier draft put the floor on the Settings endpoint, where nothing read it. Both halves
    # are asserted: the routine shapes carry it, and no settings shape mentions it at all.
    assert "min_duration_minutes" in RoutinePatchRequest.model_fields
    assert "min_duration_minutes" in RoutineResponse.model_fields

    settings_fields = [
        *SettingsResponse.model_fields,
        *SettingsPatchRequest.model_fields,
        *(field.name for field in fields(SettingsChange)),
    ]
    assert settings_fields
    assert [name for name in settings_fields if "floor" in name or "sleep" in name] == []


# --------------------------------------------------------------------------------
# Authorization
# --------------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["read", "update", "remove"])
async def test_addressing_a_routine_that_does_not_exist_is_a_404(
    principal: Principal, versions: RecordingWeekInputVersions, method: str
) -> None:
    service, _ = build(principal, versions)
    arguments: dict[str, list[object]] = {
        "read": [uuid4()],
        "update": [uuid4(), a_change()],
        "remove": [uuid4()],
    }

    with pytest.raises(NotFound):
        await getattr(service, method)(principal, *arguments[method])


async def test_a_credential_without_admin_cannot_change_the_frame(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # The frame is part of the plan's definition, alongside budgets and templates, so changing it
    # needs `admin` rather than `plan:write`.
    service, routines = build(principal, versions)
    reader = Principal(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        scopes=frozenset({Scope.PLAN_READ, Scope.PLAN_WRITE}),
    )

    with pytest.raises(Forbidden):
        await service.create(reader, a_declaration())

    # Refused means not stored, and the read the same credential DOES carry still works.
    assert routines.rows == []
    assert await service.list_all(reader) == ()


async def test_a_credential_without_plan_read_cannot_list_routines(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    service, _ = build(principal, versions)
    stranger = Principal(
        tenant_id=principal.tenant_id, user_id=principal.user_id, scopes=frozenset()
    )

    with pytest.raises(Forbidden):
        await service.list_all(stranger)


async def test_another_tenants_routine_is_a_404_rather_than_a_removal(
    principal: Principal, versions: RecordingWeekInputVersions
) -> None:
    # The defense-in-depth call. A scoped repository would not return the row at all; this is
    # what makes a repository that ever stopped scoping a 404 rather than a deletion.
    service, routines = build(principal, versions)
    theirs = RoutineRecord(
        id=uuid4(),
        tenant_id=uuid4(),
        title="Their sleep",
        target_time=SLEEP_TARGET,
        duration_minutes=SLEEP_MINUTES,
        min_duration_minutes=SLEEP_MINUTES,
        flex_band_minutes=0,
        created_at=NOW,
    )
    routines.rows.append(theirs)

    with pytest.raises(NotFound):
        await service.remove(principal, theirs.id)

    assert routines.rows == [theirs]
