"""The three day-shape services against fakes: the rules, the refusals, and the bump.

The repositories are replaced and the clock is injected, so "today" is a literal date and the week
a bump floors at is assertable without waiting for a Monday. The domain shapes are real
throughout: a stubbed span would let this suite pass while an entry sat off the fifteen-minute
grid, and a stubbed pattern would let it pass while a week had six days.

The tests worth reading are the ones about what does NOT happen. Declaring a day type bumps
nothing, because a day type no weekday maps and no shape describes cannot change what a week
materializes. Editing a shape whose day type the pattern does not use bumps nothing either, and
that pair is what makes "bump when the pattern covers it" a different rule from "bump always".
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime, time
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syncr_api.areas.records import AreaRecord
from syncr_api.areas.repository import AreaRepository
from syncr_api.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from syncr_api.core.patches import ABSENT
from syncr_api.core.principal import Principal
from syncr_api.core.scopes import ALL_SCOPES, Scope
from syncr_api.habits.records import HabitRecord
from syncr_api.habits.repository import HabitRepository
from syncr_api.routines.records import RoutineRecord
from syncr_api.routines.repository import RoutineRepository
from syncr_api.templates.bindings import TemplateBindings
from syncr_api.templates.declarations import (
    ConcreteEntry,
    DayTypeDeclaration,
    EntryChange,
    SlotEntry,
    TemplateChange,
    TemplateDeclaration,
)
from syncr_api.templates.invalidation import FutureWeeks
from syncr_api.templates.records import DayTypeRecord, TemplateEntryRecord, TemplateRecord
from syncr_api.templates.repository import (
    DayTypeRepository,
    TemplateRepository,
    WeekPatternRepository,
)
from syncr_api.templates.service import DayTypeService, TemplateService, WeekPatternService
from syncr_api.user_settings.config import ReviewCadence
from syncr_api.user_settings.records import SettingsRecord
from syncr_api.user_settings.repository import SettingsRepository
from syncr_api.user_settings.solve_inputs import BacklogWideBump, WeekRange
from syncr_domain.habits import BindingSource, CadenceKind, MissPolicy
from syncr_domain.templates import BindingTarget, EntrySpan, TemplateEntryKind, WeekPattern
from syncr_domain.weeks import IsoWeek, Weekday

if TYPE_CHECKING:
    from collections.abc import Callable
    from decimal import Decimal

    from syncr_api.templates.declarations import EntryContent
    from syncr_domain.identifiers import (
        AreaId,
        DayTypeId,
        HabitId,
        RoutineId,
        TemplateEntryId,
        TemplateId,
        TenantId,
    )

LONDON = "Europe/London"

# A Sunday, the last day of 2026-W31, at 09:00 UTC: mid-morning in London, so the local date and
# the UTC date agree and these tests are about shapes rather than about a date boundary.
NOW = datetime(2026, 8, 2, 9, 0, tzinfo=UTC)
WEEK_31 = IsoWeek.parse("2026-W31")

A_SPAN = EntrySpan(target_time=time(7, 0), duration_minutes=45, flex_band_minutes=15)


class FakeDayTypeRepository(DayTypeRepository):
    """The real repository's interface over a list of records, and no database."""

    def __init__(self, tenant_id: TenantId, stored: list[DayTypeRecord] | None = None) -> None:
        self._tenant_id = tenant_id
        self.rows = list(stored or [])

    async def list_all(self) -> tuple[DayTypeRecord, ...]:
        return tuple(sorted(self.rows, key=lambda row: (row.created_at, row.id)))

    async def create(self, *, name: str, created_at: datetime) -> DayTypeRecord:
        created = DayTypeRecord(
            id=uuid4(), tenant_id=self._tenant_id, name=name, created_at=created_at
        )
        self.rows.append(created)
        return created


class FakeTemplateRepository(TemplateRepository):
    """Shapes and their entries in memory, so the service's effects are assertable."""

    def __init__(self, tenant_id: TenantId, stored: list[TemplateRecord] | None = None) -> None:
        self._tenant_id = tenant_id
        self.rows = list(stored or [])

    async def list_all(self) -> tuple[TemplateRecord, ...]:
        return tuple(sorted(self.rows, key=lambda row: (row.created_at, row.id)))

    async def find(self, template_id: TemplateId) -> TemplateRecord | None:
        return next((row for row in self.rows if row.id == template_id), None)

    async def find_by_day_type(self, day_type_id: DayTypeId) -> TemplateRecord | None:
        return next((row for row in self.rows if row.day_type_id == day_type_id), None)

    async def create(
        self, *, day_type_id: DayTypeId, name: str, created_at: datetime
    ) -> TemplateRecord:
        created = TemplateRecord(
            id=uuid4(),
            tenant_id=self._tenant_id,
            day_type_id=day_type_id,
            name=name,
            created_at=created_at,
            entries=(),
        )
        self.rows.append(created)
        return created

    async def write(self, template_id: TemplateId, *, name: str) -> None:
        self._replace(template_id, lambda row: _renamed(row, name))

    async def remove(self, template_id: TemplateId) -> None:
        self.rows = [row for row in self.rows if row.id != template_id]

    async def create_entry(
        self, *, template_id: TemplateId, span: EntrySpan, content: EntryContent
    ) -> TemplateEntryRecord:
        created = TemplateEntryRecord(
            id=uuid4(),
            tenant_id=self._tenant_id,
            template_id=template_id,
            kind=content.kind,
            span=span,
            area_id=content.area_id,
            binding_target=content.binding_target,
            binding_ref=content.binding_ref,
        )
        self._replace(template_id, lambda row: _with_entries(row, (*row.entries, created)))
        return created

    async def write_entry(self, entry_id: TemplateEntryId, *, span: EntrySpan) -> None:
        for row in list(self.rows):
            if any(entry.id == entry_id for entry in row.entries):
                self._replace(
                    row.id,
                    lambda held: _with_entries(
                        held,
                        tuple(
                            _with_span(entry, span) if entry.id == entry_id else entry
                            for entry in held.entries
                        ),
                    ),
                )

    async def remove_entry(self, entry_id: TemplateEntryId) -> None:
        for row in list(self.rows):
            if any(entry.id == entry_id for entry in row.entries):
                self._replace(
                    row.id,
                    lambda held: _with_entries(
                        held, tuple(entry for entry in held.entries if entry.id != entry_id)
                    ),
                )

    def _replace(
        self, template_id: TemplateId, change: Callable[[TemplateRecord], TemplateRecord]
    ) -> None:
        self.rows = [change(row) if row.id == template_id else row for row in self.rows]


class FakeWeekPatternRepository(WeekPatternRepository):
    """One pattern, or none, and a record of what was written."""

    def __init__(self, tenant_id: TenantId, stored: WeekPattern | None = None) -> None:
        self._tenant_id = tenant_id
        self.stored = stored
        self.writes = 0

    async def read(self) -> WeekPattern | None:
        return self.stored

    async def replace(self, pattern: WeekPattern) -> None:
        self.stored = pattern
        self.writes += 1


class FakeAreaRepository(AreaRepository):
    """Only the one read the entry path makes: does this tenant have that Area?"""

    def __init__(self, tenant_id: TenantId, stored: list[AreaId] | None = None) -> None:
        self._tenant_id = tenant_id
        self.rows = list(stored or [])

    async def find(self, area_id: AreaId) -> AreaRecord | None:
        if area_id not in self.rows:
            return None
        return AreaRecord(
            id=area_id,
            tenant_id=self._tenant_id,
            parent_id=None,
            name="Learning",
            pigment_index=0,
            budget_percent=_no_decimal(),
            floor_hours=_no_decimal(),
            created_at=NOW,
        )


class FakeRoutineRepository(RoutineRepository):
    """The routines one tenant holds in memory, scoped the way the real read is."""

    def __init__(self, tenant_id: TenantId) -> None:
        self._tenant_id = tenant_id
        self.rows: list[RoutineRecord] = []

    async def find(self, routine_id: RoutineId) -> RoutineRecord | None:
        # Scoped on the tenant like the real read, so another tenant's row reads as absent:
        # that scoping is what makes one refusal sentence truthful for both cases.
        return next(
            (row for row in self.rows if row.id == routine_id and row.tenant_id == self._tenant_id),
            None,
        )


class FakeHabitRepository(HabitRepository):
    """The habits one tenant holds in memory, scoped the way the real read is."""

    def __init__(self, tenant_id: TenantId) -> None:
        self._tenant_id = tenant_id
        self.rows: list[HabitRecord] = []

    async def find(self, habit_id: HabitId) -> HabitRecord | None:
        return next(
            (row for row in self.rows if row.id == habit_id and row.tenant_id == self._tenant_id),
            None,
        )


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
    """Every range a service asked to have bumped, in order."""

    def __init__(self) -> None:
        self.bumped: list[WeekRange] = []

    async def bump(self, weeks: WeekRange) -> None:
        self.bumped.append(weeks)


def _no_decimal() -> Decimal | None:
    return None


def _renamed(row: TemplateRecord, name: str) -> TemplateRecord:
    return TemplateRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        day_type_id=row.day_type_id,
        name=name,
        created_at=row.created_at,
        entries=row.entries,
    )


def _with_entries(row: TemplateRecord, entries: tuple[TemplateEntryRecord, ...]) -> TemplateRecord:
    return TemplateRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        day_type_id=row.day_type_id,
        name=row.name,
        created_at=row.created_at,
        entries=entries,
    )


def _with_span(entry: TemplateEntryRecord, span: EntrySpan) -> TemplateEntryRecord:
    return TemplateEntryRecord(
        id=entry.id,
        tenant_id=entry.tenant_id,
        template_id=entry.template_id,
        kind=entry.kind,
        span=span,
        area_id=entry.area_id,
        binding_target=entry.binding_target,
        binding_ref=entry.binding_ref,
    )


@pytest.fixture
def principal() -> Principal:
    return Principal(tenant_id=uuid4(), user_id=uuid4(), scopes=ALL_SCOPES)


@pytest.fixture
def versions() -> RecordingWeekInputVersions:
    return RecordingWeekInputVersions()


class Wiring:
    """One tenant's fakes and the three services built over them."""

    def __init__(self, principal: Principal, versions: RecordingWeekInputVersions) -> None:
        self.day_types = FakeDayTypeRepository(principal.tenant_id)
        self.templates = FakeTemplateRepository(principal.tenant_id)
        self.patterns = FakeWeekPatternRepository(principal.tenant_id)
        self.areas = FakeAreaRepository(principal.tenant_id)
        self.routines = FakeRoutineRepository(principal.tenant_id)
        self.habits = FakeHabitRepository(principal.tenant_id)
        # One routine and one habit this tenant holds, so a valid concrete entry has something
        # to name. The identifiers are stable per wiring, which is what makes a refusal naming
        # one of them assertable.
        routine = _a_routine_record(principal.tenant_id)
        self.routine_id = routine.id
        self.habit_id = uuid4()
        self.routines.rows.append(routine)
        self.habits.rows.append(_a_habit_record(principal.tenant_id, self.habit_id))
        self.bindings = TemplateBindings(routines=self.routines, habits=self.habits)
        self.versions = versions
        weeks = FutureWeeks(
            patterns=self.patterns,
            bump=BacklogWideBump(
                versions=versions, settings=FakeSettingsRepository(principal.tenant_id)
            ),
            clock=lambda: NOW,
        )
        # The real refusal wrapper over an inert savepoint: these fakes never reach a database,
        # so there is no transaction to roll back and no index to lose to. The races the wrapper
        # exists for need two real connections and are driven in the integration tier.
        self.day_type_service = DayTypeService(
            day_types=self.day_types, clock=lambda: NOW, savepoint=nullcontext
        )
        self.template_service = TemplateService(
            templates=self.templates,
            day_types=self.day_types,
            areas=self.areas,
            bindings=self.bindings,
            weeks=weeks,
            clock=lambda: NOW,
            savepoint=nullcontext,
        )
        self.pattern_service = WeekPatternService(
            patterns=self.patterns, day_types=self.day_types, weeks=weeks
        )

    async def a_day_type(self, principal: Principal, name: str = "Weekday") -> DayTypeRecord:
        return await self.day_type_service.create(principal, DayTypeDeclaration(name=name))

    async def a_shape(
        self, principal: Principal, day_type: DayTypeRecord, name: str = "Weekday shape"
    ) -> TemplateRecord:
        return await self.template_service.create(
            principal, TemplateDeclaration(day_type_id=day_type.id, name=name)
        )

    def map_every_weekday_to(self, day_type: DayTypeRecord) -> None:
        self.patterns.stored = WeekPattern(dict.fromkeys(Weekday, day_type.id))


@pytest.fixture
def wiring(principal: Principal, versions: RecordingWeekInputVersions) -> Wiring:
    return Wiring(principal, versions)


def a_slot(area_id: AreaId, span: EntrySpan = A_SPAN) -> SlotEntry:
    return SlotEntry(span=span, area_id=area_id)


def a_concrete_entry(wiring: Wiring, span: EntrySpan = A_SPAN) -> ConcreteEntry:
    """A concrete entry naming the routine this wiring's tenant holds."""
    return ConcreteEntry(
        span=span,
        binding_target=BindingTarget.ROUTINE,
        binding_ref=wiring.routine_id,
        area_id=None,
    )


def _a_routine_record(tenant_id: TenantId, routine_id: RoutineId | None = None) -> RoutineRecord:
    return RoutineRecord(
        id=routine_id or uuid4(),
        tenant_id=tenant_id,
        title="Wake",
        target_time=time(6, 0),
        duration_minutes=30,
        min_duration_minutes=30,
        flex_band_minutes=0,
        created_at=NOW,
    )


def _a_habit_record(tenant_id: TenantId, habit_id: HabitId) -> HabitRecord:
    return HabitRecord(
        id=habit_id,
        tenant_id=tenant_id,
        area_id=uuid4(),
        title="Stretch",
        cadence_kind=CadenceKind.DAILY,
        cadence_times_per_week=None,
        cadence_approx_days=None,
        duration_min_minutes=15,
        duration_max_minutes=15,
        miss_policy=MissPolicy.FORGIVE,
        binding_source=BindingSource.FIXED,
        variants=(),
        debt_cap_periods=2,
        created_at=NOW,
    )


# --------------------------------------------------------------------------------
# Day types
# --------------------------------------------------------------------------------


async def test_a_declared_day_type_is_listed(principal: Principal, wiring: Wiring) -> None:
    declared = await wiring.a_day_type(principal, "Uni day")

    assert await wiring.day_type_service.list_all(principal) == (declared,)


async def test_a_name_another_day_type_holds_is_refused(
    principal: Principal, wiring: Wiring
) -> None:
    await wiring.a_day_type(principal, "Weekday")

    with pytest.raises(Conflict) as refused:
        await wiring.a_day_type(principal, "Weekday")

    assert len(wiring.day_types.rows) == 1
    assert "week pattern" in str(refused.value.detail)


async def test_declaring_a_day_type_bumps_no_input_version(
    principal: Principal, wiring: Wiring
) -> None:
    # A day type no weekday maps and no shape describes cannot change what a week materializes,
    # so invalidating a running solve for one would discard work for nothing.
    await wiring.a_day_type(principal, "Weekday")

    assert wiring.versions.bumped == []


# --------------------------------------------------------------------------------
# Shapes, and how far an edit reaches
# --------------------------------------------------------------------------------


async def test_a_shape_is_declared_against_a_day_type_that_exists(
    principal: Principal, wiring: Wiring
) -> None:
    day_type = await wiring.a_day_type(principal)

    shape = await wiring.a_shape(principal, day_type)

    assert shape.day_type_id == day_type.id
    assert shape.entries == ()


async def test_a_shape_for_an_unknown_day_type_is_refused_rather_than_stored(
    principal: Principal, wiring: Wiring
) -> None:
    with pytest.raises(ValidationFailed) as refused:
        await wiring.template_service.create(
            principal, TemplateDeclaration(day_type_id=uuid4(), name="Weekday shape")
        )

    assert wiring.templates.rows == []
    assert refused.value.errors is not None
    assert [error.field for error in refused.value.errors] == ["dayTypeId"]


async def test_a_second_shape_for_one_day_type_is_refused(
    principal: Principal, wiring: Wiring
) -> None:
    day_type = await wiring.a_day_type(principal)
    await wiring.a_shape(principal, day_type, "Weekday shape")

    with pytest.raises(Conflict) as refused:
        await wiring.a_shape(principal, day_type, "Another weekday shape")

    assert len(wiring.templates.rows) == 1
    # The message names the shape that exists, so the caller can go and edit it.
    assert "Weekday shape" in str(refused.value.detail)


async def test_a_shape_whose_day_type_the_pattern_maps_invalidates_every_future_week(
    principal: Principal, wiring: Wiring
) -> None:
    day_type = await wiring.a_day_type(principal)
    wiring.map_every_weekday_to(day_type)
    wiring.versions.bumped.clear()

    await wiring.a_shape(principal, day_type)

    assert wiring.versions.bumped == [WeekRange(first=WEEK_31, last=None)]


async def test_a_shape_whose_day_type_no_weekday_uses_invalidates_nothing(
    principal: Principal, wiring: Wiring
) -> None:
    # The control for the rule above. Without it, "bump when the pattern covers this day type"
    # and "bump on every mutation" would be the same rule.
    mapped = await wiring.a_day_type(principal, "Weekday")
    unmapped = await wiring.a_day_type(principal, "Holiday")
    wiring.map_every_weekday_to(mapped)
    wiring.versions.bumped.clear()

    await wiring.a_shape(principal, unmapped, "Holiday shape")

    assert wiring.versions.bumped == []


async def test_a_tenant_with_no_pattern_yet_invalidates_nothing(
    principal: Principal, wiring: Wiring
) -> None:
    # Nothing is mapped, so nothing is planned. A shape declared during setup must not enqueue
    # a solve for weeks that have no pattern to materialize from.
    day_type = await wiring.a_day_type(principal)

    await wiring.a_shape(principal, day_type)

    assert wiring.patterns.stored is None
    assert wiring.versions.bumped == []


async def test_renaming_a_shape_leaves_its_day_type_and_entries_alone(
    principal: Principal, wiring: Wiring
) -> None:
    day_type = await wiring.a_day_type(principal)
    shape = await wiring.a_shape(principal, day_type)
    await wiring.template_service.add_entry(principal, shape.id, a_concrete_entry(wiring))

    renamed = await wiring.template_service.update(
        principal, shape.id, TemplateChange(name="Weekdays")
    )

    assert renamed.name == "Weekdays"
    assert renamed.day_type_id == day_type.id
    assert len(renamed.entries) == 1


async def test_removing_a_shape_takes_its_entries_with_it(
    principal: Principal, wiring: Wiring
) -> None:
    day_type = await wiring.a_day_type(principal)
    shape = await wiring.a_shape(principal, day_type)
    await wiring.template_service.add_entry(principal, shape.id, a_concrete_entry(wiring))

    await wiring.template_service.remove(principal, shape.id)

    assert wiring.templates.rows == []
    with pytest.raises(NotFound):
        await wiring.template_service.read(principal, shape.id)


# --------------------------------------------------------------------------------
# Entries
# --------------------------------------------------------------------------------


async def test_a_concrete_entry_stores_its_binding_and_no_area(
    principal: Principal, wiring: Wiring
) -> None:
    day_type = await wiring.a_day_type(principal)
    shape = await wiring.a_shape(principal, day_type)
    declaration = a_concrete_entry(wiring)

    added = await wiring.template_service.add_entry(principal, shape.id, declaration)

    assert added.kind == TemplateEntryKind.CONCRETE
    assert added.binding_target == BindingTarget.ROUTINE
    assert added.binding_ref == declaration.binding_ref
    assert added.area_id is None


async def test_a_slot_stores_its_area_and_no_binding(principal: Principal, wiring: Wiring) -> None:
    day_type = await wiring.a_day_type(principal)
    shape = await wiring.a_shape(principal, day_type)
    area_id = uuid4()
    wiring.areas.rows.append(area_id)

    added = await wiring.template_service.add_entry(principal, shape.id, a_slot(area_id))

    assert added.kind == TemplateEntryKind.SLOT
    assert added.area_id == area_id
    assert added.binding_target is None
    assert added.binding_ref is None


@pytest.mark.parametrize("kind", ["concrete", "slot"])
async def test_an_entry_naming_an_area_this_tenant_does_not_have_is_refused(
    principal: Principal, wiring: Wiring, kind: str
) -> None:
    # Both kinds may name an Area: a slot must, and a concrete entry may for reporting. So both
    # are checked, and testing one would leave the other's guard free to be deleted.
    day_type = await wiring.a_day_type(principal)
    shape = await wiring.a_shape(principal, day_type)
    unknown = uuid4()
    declaration = (
        a_slot(unknown) if kind == "slot" else replace(a_concrete_entry(wiring), area_id=unknown)
    )

    with pytest.raises(ValidationFailed) as refused:
        await wiring.template_service.add_entry(principal, shape.id, declaration)

    assert refused.value.errors is not None
    assert [error.field for error in refused.value.errors] == ["areaId"]
    assert wiring.templates.rows[0].entries == ()


async def test_the_binding_vocabulary_has_a_reader_for_every_member(wiring: Wiring) -> None:
    # Removing a BindingTarget member shrinks the vocabulary and this stays green. Adding one
    # without a reader reddens here, rather than resolving against whichever table a reader
    # looked in first.
    assert wiring.bindings.targets == frozenset(BindingTarget)


@pytest.mark.parametrize("target", list(BindingTarget), ids=["routine", "habit"])
async def test_a_valid_concrete_entry_naming_held_content_is_stored(
    principal: Principal, wiring: Wiring, target: BindingTarget
) -> None:
    day_type = await wiring.a_day_type(principal)
    shape = await wiring.a_shape(principal, day_type)
    ref = wiring.routine_id if target is BindingTarget.ROUTINE else wiring.habit_id
    declaration = ConcreteEntry(span=A_SPAN, binding_target=target, binding_ref=ref, area_id=None)

    added = await wiring.template_service.add_entry(principal, shape.id, declaration)

    assert added.binding_target is target
    assert added.binding_ref == ref


async def test_a_concrete_entry_naming_content_this_tenant_does_not_have_is_refused(
    principal: Principal, wiring: Wiring
) -> None:
    day_type = await wiring.a_day_type(principal)
    shape = await wiring.a_shape(principal, day_type)
    declaration = ConcreteEntry(
        span=A_SPAN,
        binding_target=BindingTarget.ROUTINE,
        binding_ref=uuid4(),
        area_id=None,
    )

    with pytest.raises(ValidationFailed) as refused:
        await wiring.template_service.add_entry(principal, shape.id, declaration)

    assert refused.value.errors is not None
    assert [error.field for error in refused.value.errors] == ["bindingRef"]
    assert wiring.templates.rows[0].entries == ()


async def test_an_unknown_identifier_and_another_tenants_are_refused_identically(
    principal: Principal, wiring: Wiring
) -> None:
    # One sentence covers both, so the response discloses nothing about which it refused: an
    # identifier nobody holds and one another tenant's routine answers are the same refusal.
    day_type = await wiring.a_day_type(principal)
    shape = await wiring.a_shape(principal, day_type)
    strangers = _a_routine_record(uuid4())
    wiring.routines.rows.append(strangers)

    def a_declaration(ref: RoutineId) -> ConcreteEntry:
        return ConcreteEntry(
            span=A_SPAN, binding_target=BindingTarget.ROUTINE, binding_ref=ref, area_id=None
        )

    with pytest.raises(ValidationFailed) as unknown:
        await wiring.template_service.add_entry(principal, shape.id, a_declaration(uuid4()))
    with pytest.raises(ValidationFailed) as foreign:
        await wiring.template_service.add_entry(principal, shape.id, a_declaration(strangers.id))

    assert str(unknown.value.detail) == str(foreign.value.detail)
    assert unknown.value.errors == foreign.value.errors
    assert wiring.templates.rows[0].entries == ()


@pytest.mark.parametrize(
    ("target", "held_elsewhere"),
    [
        (BindingTarget.ROUTINE, "habit_id"),
        (BindingTarget.HABIT, "routine_id"),
    ],
    ids=["a routine target naming a habit", "a habit target naming a routine"],
)
async def test_a_binding_cannot_name_the_other_tables_identifier(
    principal: Principal,
    wiring: Wiring,
    target: BindingTarget,
    held_elsewhere: str,
) -> None:
    # The identifier exists in THIS tenant, but in the other table: only the mapping keyed by
    # target stands between the two, which is why both directions are tested.
    day_type = await wiring.a_day_type(principal)
    shape = await wiring.a_shape(principal, day_type)
    declaration = ConcreteEntry(
        span=A_SPAN,
        binding_target=target,
        binding_ref=getattr(wiring, held_elsewhere),
        area_id=None,
    )

    with pytest.raises(ValidationFailed) as refused:
        await wiring.template_service.add_entry(principal, shape.id, declaration)

    assert refused.value.errors is not None
    assert [error.field for error in refused.value.errors] == ["bindingRef"]
    assert wiring.templates.rows[0].entries == ()


async def test_a_patch_applies_the_same_resolution_as_the_post(
    principal: Principal, wiring: Wiring
) -> None:
    # A patch carries no binding, so the resolution runs over the stored one: an entry whose
    # content has since gone missing cannot be edited into a row nothing will materialize.
    day_type = await wiring.a_day_type(principal)
    shape = await wiring.a_shape(principal, day_type)
    entry = await wiring.template_service.add_entry(principal, shape.id, a_concrete_entry(wiring))
    wiring.routines.rows.clear()

    with pytest.raises(ValidationFailed) as refused:
        await wiring.template_service.change_entry(
            principal,
            shape.id,
            entry.id,
            EntryChange(target_time=time(6, 30), duration_minutes=ABSENT, flex_band_minutes=ABSENT),
        )

    assert refused.value.errors is not None
    assert [error.field for error in refused.value.errors] == ["bindingRef"]
    assert wiring.templates.rows[0].entries[0].span == A_SPAN


async def test_an_entry_of_another_shape_is_not_addressable_through_this_one(
    principal: Principal, wiring: Wiring
) -> None:
    weekday = await wiring.a_day_type(principal, "Weekday")
    weekend = await wiring.a_day_type(principal, "Weekend")
    weekday_shape = await wiring.a_shape(principal, weekday, "Weekday shape")
    weekend_shape = await wiring.a_shape(principal, weekend, "Weekend shape")
    entry = await wiring.template_service.add_entry(
        principal, weekday_shape.id, a_concrete_entry(wiring)
    )

    with pytest.raises(NotFound):
        await wiring.template_service.remove_entry(principal, weekend_shape.id, entry.id)

    assert len(wiring.templates.rows[0].entries) == 1


async def test_a_patch_moves_an_entry_and_leaves_its_content_alone(
    principal: Principal, wiring: Wiring
) -> None:
    day_type = await wiring.a_day_type(principal)
    shape = await wiring.a_shape(principal, day_type)
    declaration = a_concrete_entry(wiring)
    entry = await wiring.template_service.add_entry(principal, shape.id, declaration)

    moved = await wiring.template_service.change_entry(
        principal,
        shape.id,
        entry.id,
        EntryChange(target_time=time(6, 30), duration_minutes=ABSENT, flex_band_minutes=ABSENT),
    )

    assert moved.span.target_time == time(6, 30)
    assert moved.span.duration_minutes == A_SPAN.duration_minutes
    assert moved.binding_ref == declaration.binding_ref


async def test_a_patch_that_would_leave_an_entry_off_the_grid_is_refused(
    principal: Principal, wiring: Wiring
) -> None:
    # The merged span is where the grid rule can first be broken by a PATCH, because the patch
    # names one field and the rule is about the pair.
    day_type = await wiring.a_day_type(principal)
    shape = await wiring.a_shape(principal, day_type)
    entry = await wiring.template_service.add_entry(principal, shape.id, a_concrete_entry(wiring))

    with pytest.raises(ValidationFailed) as refused:
        await wiring.template_service.change_entry(
            principal,
            shape.id,
            entry.id,
            EntryChange(target_time=ABSENT, duration_minutes=50, flex_band_minutes=ABSENT),
        )

    assert refused.value.errors is not None
    assert [error.field for error in refused.value.errors] == ["durationMinutes"]
    assert wiring.templates.rows[0].entries[0].span == A_SPAN


@pytest.mark.parametrize(
    "mutate",
    ["add", "change", "remove"],
)
async def test_every_entry_mutation_invalidates_the_mapped_future_weeks(
    principal: Principal, wiring: Wiring, mutate: str
) -> None:
    day_type = await wiring.a_day_type(principal)
    shape = await wiring.a_shape(principal, day_type)
    entry = await wiring.template_service.add_entry(principal, shape.id, a_concrete_entry(wiring))
    wiring.map_every_weekday_to(day_type)
    wiring.versions.bumped.clear()

    if mutate == "add":
        await wiring.template_service.add_entry(principal, shape.id, a_concrete_entry(wiring))
    elif mutate == "change":
        await wiring.template_service.change_entry(
            principal,
            shape.id,
            entry.id,
            EntryChange(target_time=time(8, 0), duration_minutes=ABSENT, flex_band_minutes=ABSENT),
        )
    else:
        await wiring.template_service.remove_entry(principal, shape.id, entry.id)

    assert wiring.versions.bumped == [WeekRange(first=WEEK_31, last=None)]


# --------------------------------------------------------------------------------
# The week pattern
# --------------------------------------------------------------------------------


async def test_reading_a_pattern_nobody_declared_is_a_404_that_says_what_to_do(
    principal: Principal, wiring: Wiring
) -> None:
    with pytest.raises(NotFound) as absent:
        await wiring.pattern_service.read(principal)

    assert "seven weekdays" in str(absent.value.detail)


async def test_replacing_the_pattern_stores_all_seven_and_invalidates_every_future_week(
    principal: Principal, wiring: Wiring
) -> None:
    weekday = await wiring.a_day_type(principal, "Weekday")
    weekend = await wiring.a_day_type(principal, "Weekend")
    declared = WeekPattern(
        {
            weekday_name: weekend.id
            if weekday_name in {Weekday.SATURDAY, Weekday.SUNDAY}
            else weekday.id
            for weekday_name in Weekday
        }
    )

    replaced = await wiring.pattern_service.replace(principal, declared)

    assert replaced.day_type(Weekday.MONDAY) == weekday.id
    assert replaced.day_type(Weekday.SATURDAY) == weekend.id
    assert wiring.patterns.writes == 1
    assert wiring.versions.bumped == [WeekRange(first=WEEK_31, last=None)]


async def test_a_pattern_naming_a_day_type_this_tenant_does_not_have_is_refused(
    principal: Principal, wiring: Wiring
) -> None:
    declared = WeekPattern({weekday: uuid4() for weekday in Weekday})

    with pytest.raises(ValidationFailed) as refused:
        await wiring.pattern_service.replace(principal, declared)

    assert wiring.patterns.stored is None
    assert wiring.versions.bumped == []
    assert refused.value.errors is not None
    assert [error.field for error in refused.value.errors] == ["dayTypeId"]


async def test_replacing_the_pattern_bumps_even_when_the_mapping_is_unchanged(
    principal: Principal, wiring: Wiring
) -> None:
    # A pattern maps all seven weekdays, so there is no future week it does not describe. The
    # bump is unconditional rather than diffed, because a diff would be a second rule about
    # which weeks a pattern reaches.
    day_type = await wiring.a_day_type(principal)
    declared = WeekPattern(dict.fromkeys(Weekday, day_type.id))
    await wiring.pattern_service.replace(principal, declared)
    wiring.versions.bumped.clear()

    await wiring.pattern_service.replace(principal, declared)

    assert wiring.versions.bumped == [WeekRange(first=WEEK_31, last=None)]


# --------------------------------------------------------------------------------
# Authorization
# --------------------------------------------------------------------------------


async def test_a_read_needs_the_read_scope(wiring: Wiring) -> None:
    without = Principal(tenant_id=uuid4(), user_id=uuid4(), scopes=frozenset())

    for read in (
        wiring.day_type_service.list_all,
        wiring.template_service.list_all,
        wiring.pattern_service.read,
    ):
        with pytest.raises(Forbidden):
            await read(without)


async def test_a_mutation_needs_the_admin_scope(principal: Principal, wiring: Wiring) -> None:
    day_type = await wiring.a_day_type(principal)
    reader = Principal(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        scopes=frozenset({Scope.PLAN_READ}),
    )

    with pytest.raises(Forbidden):
        await wiring.a_day_type(reader, "Weekend")
    with pytest.raises(Forbidden):
        await wiring.a_shape(reader, day_type)
    with pytest.raises(Forbidden):
        await wiring.pattern_service.replace(
            reader, WeekPattern(dict.fromkeys(Weekday, day_type.id))
        )


async def test_another_tenants_shape_is_not_readable(principal: Principal, wiring: Wiring) -> None:
    # The repository is scoped, so this is defense in depth: it is the one place an unscoped
    # read could be introduced, and it must answer 404 rather than 403.
    day_type = await wiring.a_day_type(principal)
    shape = await wiring.a_shape(principal, day_type)
    stranger = Principal(tenant_id=uuid4(), user_id=uuid4(), scopes=ALL_SCOPES)

    with pytest.raises(NotFound):
        await wiring.template_service.read(stranger, shape.id)
