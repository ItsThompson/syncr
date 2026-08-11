"""The preference service against fakes: the chain, the cap's owner, and the bump's gate.

The repositories are replaced and the clock is injected, so "today" is a literal date and the week
the bump floors at is assertable without waiting for a Monday. The domain is real throughout: the
entity and the resolution are the shipped functions, because a stubbed resolution would let this
suite pass while an override was silently ignored.

Three tests are the ones to read.

``test_removing_an_overrides_preference_restores_its_areas`` is the criterion stated as behavior: a
habit that overrode its Area reads its Area's preference again the moment the override is gone.

``test_an_override_that_states_no_ideal_duration_does_not_inherit_its_areas`` is what separates
replacing wholly from merging field by field. It is the only assertion here that would still pass if
the resolution merged.

``test_a_replacement_that_stores_what_was_already_stored_bumps_nothing`` is the bump's gate. Both
halves matter: a change bumps, and a no-op does not, because the cost of a needless bump is a
running solve superseded for nothing.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, time
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syncr_api.areas.records import AreaRecord
from syncr_api.areas.repository import AreaRepository
from syncr_api.core.errors import Forbidden, NotFound, ValidationFailed
from syncr_api.core.principal import Principal
from syncr_api.core.scopes import ALL_SCOPES, Scope
from syncr_api.habits.records import HabitRecord
from syncr_api.habits.repository import HabitRepository
from syncr_api.preferences.declarations import DeclaredWindow, PreferenceDeclaration
from syncr_api.preferences.owners import PreferenceOwners
from syncr_api.preferences.records import (
    PreferenceRecord,
    UnattributedPreferenceRow,
    owner_columns,
    owner_of,
    windows_as_json,
    windows_from_json,
)
from syncr_api.preferences.repository import OWNER_COLUMN, PreferenceRepository
from syncr_api.preferences.service import PreferenceService
from syncr_api.tasks.records import TaskRecord
from syncr_api.tasks.repository import TaskRepository
from syncr_api.user_settings.config import ReviewCadence
from syncr_api.user_settings.records import SettingsRecord
from syncr_api.user_settings.repository import SettingsRepository
from syncr_api.user_settings.solve_inputs import BacklogWideBump, WeekRange
from syncr_domain.habits import BindingSource, CadenceKind, MissPolicy
from syncr_domain.preferences import (
    LocalTimeWindow,
    Preference,
    PreferenceError,
    PreferenceOwner,
    PreferenceOwnerKind,
    PreferenceStrength,
)
from syncr_domain.tasks import Priority, TaskStatus
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from syncr_domain.identifiers import AreaId, HabitId, TaskId, TenantId

LONDON = "Europe/London"

# A Sunday, the last day of 2026-W31, at 09:00 UTC: mid-morning in London, so the local date and the
# UTC date agree and these tests are about preferences rather than about a date boundary.
NOW = datetime(2026, 8, 2, 9, 0, tzinfo=UTC)
WEEK_31 = IsoWeek.parse("2026-W31")

EARLY = LocalTimeWindow(start=time(5, 30), end=time(7, 0))
MIDDAY = LocalTimeWindow(start=time(13, 15), end=time(14, 15))
EVENING = LocalTimeWindow(start=time(19, 0), end=time(21, 0))


class FakePreferenceRepository(PreferenceRepository):
    """The real repository's interface over a list of records, and no database.

    Addressed by owner throughout, as the real one is, so a test cannot reach a preference by an
    identifier no caller holds.
    """

    def __init__(self, tenant_id: TenantId, stored: list[PreferenceRecord] | None = None) -> None:
        self._tenant_id = tenant_id
        self.rows = list(stored or [])

    async def find(self, owner: PreferenceOwner) -> PreferenceRecord | None:
        return next((row for row in self.rows if row.owner == owner), None)

    async def create(self, preference: Preference, *, created_at: datetime) -> PreferenceRecord:
        created = record(self._tenant_id, preference, created_at=created_at)
        self.rows.append(created)
        return created

    async def write(self, preference: Preference) -> None:
        self.rows = [
            replace(
                row,
                windows=tuple(windows_as_json(preference.windows)),
                strength=preference.strength,
                preferred_duration_minutes=preference.preferred_duration_minutes,
                max_per_day_minutes=preference.max_per_day_minutes,
            )
            if row.owner == preference.owner
            else row
            for row in self.rows
        ]

    async def remove(self, owner: PreferenceOwner) -> int:
        kept = [row for row in self.rows if row.owner != owner]
        removed = len(self.rows) - len(kept)
        self.rows = kept
        return removed


class FakeAreaRepository(AreaRepository):
    """Answers whether an Area exists, which is the one thing this service asks of it."""

    def __init__(self, tenant_id: TenantId, stored: list[AreaRecord] | None = None) -> None:
        self._tenant_id = tenant_id
        self.rows = list(stored or [])

    async def find(self, area_id: AreaId) -> AreaRecord | None:
        return next((row for row in self.rows if row.id == area_id), None)


class FakeHabitRepository(HabitRepository):
    """Answers whether a habit exists and which Area it is in, which is all this service reads."""

    def __init__(self, tenant_id: TenantId, stored: list[HabitRecord] | None = None) -> None:
        self._tenant_id = tenant_id
        self.rows = list(stored or [])

    async def find(self, habit_id: HabitId) -> HabitRecord | None:
        return next((row for row in self.rows if row.id == habit_id), None)


class FakeTaskRepository(TaskRepository):
    """Answers whether a task exists and which Area it is in."""

    def __init__(self, tenant_id: TenantId, stored: list[TaskRecord] | None = None) -> None:
        self._tenant_id = tenant_id
        self.rows = list(stored or [])

    async def find(self, task_id: TaskId) -> TaskRecord | None:
        return next((row for row in self.rows if row.id == task_id), None)


class FakeSettingsRepository(SettingsRepository):
    """The home zone, which is what decides which week the bump floors at."""

    def __init__(self, tenant_id: TenantId, home_zone: str = LONDON) -> None:
        self._tenant_id = tenant_id
        self._home_zone = home_zone

    async def read(self) -> SettingsRecord:
        return SettingsRecord(
            tenant_id=self._tenant_id,
            visible_hours=17,
            day_start=time(6, 0),
            day_end=time(23, 0),
            review_cadence=ReviewCadence.ON_DEMAND,
            home_zone=self._home_zone,
        )


class RecordingVersions:
    """Records what would have been bumped, so a bump is assertable without a database."""

    def __init__(self) -> None:
        self.bumped: list[WeekRange] = []

    async def bump(self, weeks: WeekRange) -> None:
        self.bumped.append(weeks)


def record(
    tenant_id: TenantId, preference: Preference, *, created_at: datetime = NOW
) -> PreferenceRecord:
    """A stored row for one preference, as the repository would have written it."""
    return PreferenceRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        owner=preference.owner,
        windows=tuple(windows_as_json(preference.windows)),
        strength=preference.strength,
        preferred_duration_minutes=preference.preferred_duration_minutes,
        max_per_day_minutes=preference.max_per_day_minutes,
        created_at=created_at,
    )


def area(tenant_id: TenantId) -> AreaRecord:
    return AreaRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        parent_id=None,
        name="Fitness",
        pigment_index=0,
        budget_percent=None,
        floor_hours=None,
        created_at=NOW,
    )


def habit(tenant_id: TenantId, area_id: AreaId) -> HabitRecord:
    return HabitRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        area_id=area_id,
        title="Anki",
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


def task(tenant_id: TenantId, area_id: AreaId) -> TaskRecord:
    return TaskRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        area_id=area_id,
        project_id=None,
        title="Essay",
        estimate_minutes=60,
        recorded_minutes=0,
        min_chunk_minutes=15,
        splittable=True,
        priority=Priority.NORMAL,
        status=TaskStatus.OPEN,
        deadline=None,
        completed_at=None,
        created_at=NOW,
    )


def declaration(
    *,
    windows: tuple[LocalTimeWindow, ...] = (EARLY,),
    strength: PreferenceStrength = PreferenceStrength.STRONG,
    preferred_duration_minutes: int | None = None,
    max_per_day_minutes: int | None = None,
) -> PreferenceDeclaration:
    return PreferenceDeclaration(
        windows=tuple(DeclaredWindow(start=window.start, end=window.end) for window in windows),
        strength=strength,
        preferred_duration_minutes=preferred_duration_minutes,
        max_per_day_minutes=max_per_day_minutes,
    )


def a_preference(
    owner: PreferenceOwner,
    *,
    windows: tuple[LocalTimeWindow, ...] = (EARLY,),
    strength: PreferenceStrength = PreferenceStrength.STRONG,
    preferred_duration_minutes: int | None = None,
    max_per_day_minutes: int | None = None,
) -> Preference:
    return Preference(
        owner=owner,
        windows=windows,
        strength=strength,
        preferred_duration_minutes=preferred_duration_minutes,
        max_per_day_minutes=max_per_day_minutes,
    )


class World:
    """One tenant with an Area, a habit and a task inside it, and the service over fakes."""

    def __init__(self, stored: list[Preference] | None = None) -> None:
        self.tenant_id: TenantId = uuid4()
        self.principal = Principal(tenant_id=self.tenant_id, user_id=uuid4(), scopes=ALL_SCOPES)
        self.area = area(self.tenant_id)
        self.habit = habit(self.tenant_id, self.area.id)
        self.task = task(self.tenant_id, self.area.id)
        self.preferences = FakePreferenceRepository(
            self.tenant_id, [record(self.tenant_id, one) for one in (stored or [])]
        )
        self.versions = RecordingVersions()
        self.service = PreferenceService(
            preferences=self.preferences,
            owners=PreferenceOwners(
                areas=FakeAreaRepository(self.tenant_id, [self.area]),
                habits=FakeHabitRepository(self.tenant_id, [self.habit]),
                tasks=FakeTaskRepository(self.tenant_id, [self.task]),
            ),
            bump=BacklogWideBump(
                versions=self.versions, settings=FakeSettingsRepository(self.tenant_id)
            ),
            clock=lambda: NOW,
        )

    @property
    def area_owner(self) -> PreferenceOwner:
        return PreferenceOwner(kind=PreferenceOwnerKind.AREA, id=self.area.id)

    @property
    def habit_owner(self) -> PreferenceOwner:
        return PreferenceOwner(kind=PreferenceOwnerKind.HABIT, id=self.habit.id)

    @property
    def task_owner(self) -> PreferenceOwner:
        return PreferenceOwner(kind=PreferenceOwnerKind.TASK, id=self.task.id)


class TestTheChain:
    async def test_an_area_reads_its_own_preference_as_the_one_in_effect(self) -> None:
        world = World()
        await world.service.replace(
            world.principal, PreferenceOwnerKind.AREA, world.area.id, declaration()
        )

        read = await world.service.read(world.principal, PreferenceOwnerKind.AREA, world.area.id)

        assert read.declared is not None
        assert read.in_effect == read.declared
        assert read.in_effect.owner == world.area_owner

    @pytest.mark.parametrize("kind", ["habit", "task"], ids=["habit", "task"])
    async def test_an_owner_with_no_override_inherits_its_areas_preference(self, kind: str) -> None:
        world = World()
        await world.service.replace(
            world.principal, PreferenceOwnerKind.AREA, world.area.id, declaration()
        )
        owner_id = world.habit.id if kind == "habit" else world.task.id

        read = await world.service.read(world.principal, PreferenceOwnerKind(kind), owner_id)

        assert read.declared is None
        assert read.in_effect is not None
        assert read.in_effect.owner == world.area_owner
        assert read.in_effect.windows == (EARLY,)

    @pytest.mark.parametrize("kind", ["habit", "task"], ids=["habit", "task"])
    async def test_an_override_wins_over_its_area(self, kind: str) -> None:
        world = World()
        await world.service.replace(
            world.principal, PreferenceOwnerKind.AREA, world.area.id, declaration()
        )
        owner_id = world.habit.id if kind == "habit" else world.task.id
        await world.service.replace(
            world.principal,
            PreferenceOwnerKind(kind),
            owner_id,
            declaration(windows=(MIDDAY,), strength=PreferenceStrength.SOFT),
        )

        read = await world.service.read(world.principal, PreferenceOwnerKind(kind), owner_id)

        assert read.declared is not None
        assert read.in_effect is not None
        assert read.in_effect.owner == read.declared.owner
        assert read.in_effect.owner.kind is PreferenceOwnerKind(kind)
        assert read.in_effect.windows == (MIDDAY,)
        assert read.in_effect.strength is PreferenceStrength.SOFT

    async def test_an_owner_whose_area_declares_nothing_has_nothing_in_effect(self) -> None:
        world = World()

        read = await world.service.read(world.principal, PreferenceOwnerKind.HABIT, world.habit.id)

        assert read.declared is None
        assert read.in_effect is None

    async def test_exactly_one_preference_is_in_effect_per_owner(self) -> None:
        # The criterion's own claim, over all three owners at once: each resolves to one
        # preference, and the two overrides resolve to their own rather than to their Area's.
        world = World()
        await world.service.replace(
            world.principal, PreferenceOwnerKind.AREA, world.area.id, declaration()
        )
        await world.service.replace(
            world.principal,
            PreferenceOwnerKind.HABIT,
            world.habit.id,
            declaration(windows=(MIDDAY,)),
        )
        await world.service.replace(
            world.principal,
            PreferenceOwnerKind.TASK,
            world.task.id,
            declaration(windows=(EVENING,)),
        )

        in_effect = [
            (await world.service.read(world.principal, kind, owner_id)).in_effect
            for kind, owner_id in (
                (PreferenceOwnerKind.AREA, world.area.id),
                (PreferenceOwnerKind.HABIT, world.habit.id),
                (PreferenceOwnerKind.TASK, world.task.id),
            )
        ]

        assert [found.owner for found in in_effect if found is not None] == [
            world.area_owner,
            world.habit_owner,
            world.task_owner,
        ]
        assert [found.windows for found in in_effect if found is not None] == [
            (EARLY,),
            (MIDDAY,),
            (EVENING,),
        ]


class TestReplacingWholly:
    async def test_an_override_that_states_no_ideal_duration_does_not_inherit_its_areas(
        self,
    ) -> None:
        # The assertion that separates replacing wholly from merging field by field. A merge would
        # fill the override's null from the Area's 90 and this would read 90.
        world = World()
        await world.service.replace(
            world.principal,
            PreferenceOwnerKind.AREA,
            world.area.id,
            declaration(preferred_duration_minutes=90),
        )
        await world.service.replace(
            world.principal,
            PreferenceOwnerKind.HABIT,
            world.habit.id,
            declaration(windows=(MIDDAY,)),
        )

        read = await world.service.read(world.principal, PreferenceOwnerKind.HABIT, world.habit.id)

        assert read.in_effect is not None
        assert read.in_effect.preferred_duration_minutes is None

    async def test_an_override_with_no_windows_opts_out_of_its_areas_windows(self) -> None:
        world = World()
        await world.service.replace(
            world.principal, PreferenceOwnerKind.AREA, world.area.id, declaration()
        )

        read = await world.service.replace(
            world.principal,
            PreferenceOwnerKind.HABIT,
            world.habit.id,
            declaration(windows=(), strength=PreferenceStrength.SOFT),
        )

        assert read.in_effect is not None
        assert read.in_effect.windows == ()
        assert read.in_effect.owner == world.habit_owner

    async def test_a_second_replacement_clears_a_field_the_first_declared(self) -> None:
        # What PUT means: the stored row is overwritten, so a field the second body left out is
        # null afterwards rather than left at the value the first body set.
        world = World()
        await world.service.replace(
            world.principal,
            PreferenceOwnerKind.AREA,
            world.area.id,
            declaration(preferred_duration_minutes=90, max_per_day_minutes=180),
        )

        read = await world.service.replace(
            world.principal, PreferenceOwnerKind.AREA, world.area.id, declaration()
        )

        assert read.declared is not None
        assert read.declared.preferred_duration_minutes is None
        assert read.declared.max_per_day_minutes is None

    async def test_a_replacement_leaves_one_row_rather_than_two(self) -> None:
        world = World()
        for windows in ((EARLY,), (MIDDAY,), (EVENING,)):
            await world.service.replace(
                world.principal,
                PreferenceOwnerKind.AREA,
                world.area.id,
                declaration(windows=windows),
            )

        assert len(world.preferences.rows) == 1


class TestTheCapIsAnAreasAlone:
    async def test_an_area_may_declare_a_cap(self) -> None:
        world = World()

        read = await world.service.replace(
            world.principal,
            PreferenceOwnerKind.AREA,
            world.area.id,
            declaration(max_per_day_minutes=180),
        )

        assert read.declared is not None
        assert read.declared.max_per_day_minutes == 180

    @pytest.mark.parametrize("kind", ["habit", "task"], ids=["habit", "task"])
    async def test_a_cap_on_an_override_is_refused(self, kind: str) -> None:
        # X13 at the service layer. The request shape has no field for a cap, so this is the layer
        # below the boundary refusal: nothing that reaches the service can store one either.
        world = World()
        owner_id = world.habit.id if kind == "habit" else world.task.id

        with pytest.raises(ValidationFailed) as refused:
            await world.service.replace(
                world.principal,
                PreferenceOwnerKind(kind),
                owner_id,
                declaration(max_per_day_minutes=180),
            )

        assert refused.value.errors is not None
        assert "maxPerDayMinutes" in [error.field for error in refused.value.errors]
        assert world.preferences.rows == []

    async def test_the_effective_preference_of_an_override_never_carries_a_cap(self) -> None:
        # P3 and P5 together: the Area's cap is not something an override's resolution can report,
        # so nothing downstream can read a relaxed one.
        world = World()
        await world.service.replace(
            world.principal,
            PreferenceOwnerKind.AREA,
            world.area.id,
            declaration(max_per_day_minutes=180),
        )
        await world.service.replace(
            world.principal,
            PreferenceOwnerKind.HABIT,
            world.habit.id,
            declaration(windows=(MIDDAY,)),
        )

        read = await world.service.read(world.principal, PreferenceOwnerKind.HABIT, world.habit.id)

        assert read.in_effect is not None
        assert read.in_effect.max_per_day_minutes is None


class TestRemoval:
    @pytest.mark.parametrize("kind", ["habit", "task"], ids=["habit", "task"])
    async def test_removing_an_overrides_preference_restores_its_areas(self, kind: str) -> None:
        world = World()
        owner_id = world.habit.id if kind == "habit" else world.task.id
        await world.service.replace(
            world.principal, PreferenceOwnerKind.AREA, world.area.id, declaration()
        )
        await world.service.replace(
            world.principal, PreferenceOwnerKind(kind), owner_id, declaration(windows=(MIDDAY,))
        )

        read = await world.service.remove(world.principal, PreferenceOwnerKind(kind), owner_id)

        assert read.declared is None
        assert read.in_effect is not None
        assert read.in_effect.owner == world.area_owner
        assert read.in_effect.windows == (EARLY,)

    async def test_removing_an_areas_preference_leaves_its_habits_with_nothing(self) -> None:
        world = World()
        await world.service.replace(
            world.principal, PreferenceOwnerKind.AREA, world.area.id, declaration()
        )

        await world.service.remove(world.principal, PreferenceOwnerKind.AREA, world.area.id)
        read = await world.service.read(world.principal, PreferenceOwnerKind.HABIT, world.habit.id)

        assert read.in_effect is None

    async def test_removing_a_preference_that_was_never_set_changes_nothing(self) -> None:
        world = World()

        read = await world.service.remove(
            world.principal, PreferenceOwnerKind.HABIT, world.habit.id
        )

        assert read.declared is None
        assert world.preferences.rows == []

    async def test_removing_an_override_leaves_its_areas_row_alone(self) -> None:
        world = World()
        await world.service.replace(
            world.principal, PreferenceOwnerKind.AREA, world.area.id, declaration()
        )
        await world.service.replace(
            world.principal,
            PreferenceOwnerKind.HABIT,
            world.habit.id,
            declaration(windows=(MIDDAY,)),
        )

        await world.service.remove(world.principal, PreferenceOwnerKind.HABIT, world.habit.id)

        assert [row.owner for row in world.preferences.rows] == [world.area_owner]


class TestTheVersionBump:
    async def test_declaring_a_preference_bumps_from_this_week_onwards(self) -> None:
        world = World()

        await world.service.replace(
            world.principal, PreferenceOwnerKind.AREA, world.area.id, declaration()
        )

        assert world.versions.bumped == [WeekRange(first=WEEK_31, last=None)]

    async def test_the_range_has_no_end_because_a_preference_has_no_end_date(self) -> None:
        # The open-ended shape, which is `BacklogWideBump`'s: a preference governs every week the
        # user has not yet lived, and past weeks keep the inputs their approved revisions used.
        world = World()

        await world.service.replace(
            world.principal, PreferenceOwnerKind.AREA, world.area.id, declaration()
        )

        assert world.versions.bumped[0].last is None
        assert world.versions.bumped[0].first == WEEK_31

    async def test_a_replacement_that_stores_what_was_already_stored_bumps_nothing(self) -> None:
        world = World()
        await world.service.replace(
            world.principal, PreferenceOwnerKind.AREA, world.area.id, declaration()
        )
        world.versions.bumped.clear()

        await world.service.replace(
            world.principal, PreferenceOwnerKind.AREA, world.area.id, declaration()
        )

        assert world.versions.bumped == []

    async def test_a_replacement_that_only_reorders_windows_bumps_nothing(self) -> None:
        # The entity canonicalizes its windows, so two orders of one set are one preference and the
        # gate reads them as equal rather than as a change.
        world = World()
        await world.service.replace(
            world.principal,
            PreferenceOwnerKind.AREA,
            world.area.id,
            declaration(windows=(EARLY, MIDDAY)),
        )
        world.versions.bumped.clear()

        await world.service.replace(
            world.principal,
            PreferenceOwnerKind.AREA,
            world.area.id,
            declaration(windows=(MIDDAY, EARLY)),
        )

        assert world.versions.bumped == []

    async def test_a_replacement_that_changes_one_field_bumps(self) -> None:
        # The control for the two cases above: without it, a gate that never fired would pass both.
        world = World()
        await world.service.replace(
            world.principal, PreferenceOwnerKind.AREA, world.area.id, declaration()
        )
        world.versions.bumped.clear()

        await world.service.replace(
            world.principal,
            PreferenceOwnerKind.AREA,
            world.area.id,
            declaration(strength=PreferenceStrength.SOFT),
        )

        assert world.versions.bumped == [WeekRange(first=WEEK_31, last=None)]

    async def test_removing_a_preference_that_existed_bumps(self) -> None:
        world = World()
        await world.service.replace(
            world.principal, PreferenceOwnerKind.AREA, world.area.id, declaration()
        )
        world.versions.bumped.clear()

        await world.service.remove(world.principal, PreferenceOwnerKind.AREA, world.area.id)

        assert world.versions.bumped == [WeekRange(first=WEEK_31, last=None)]

    async def test_removing_a_preference_that_did_not_exist_bumps_nothing(self) -> None:
        world = World()

        await world.service.remove(world.principal, PreferenceOwnerKind.AREA, world.area.id)

        assert world.versions.bumped == []

    async def test_a_read_bumps_nothing(self) -> None:
        world = World()

        await world.service.read(world.principal, PreferenceOwnerKind.AREA, world.area.id)

        assert world.versions.bumped == []

    async def test_a_refused_replacement_bumps_nothing(self) -> None:
        world = World()

        with pytest.raises(ValidationFailed):
            await world.service.replace(
                world.principal,
                PreferenceOwnerKind.HABIT,
                world.habit.id,
                declaration(max_per_day_minutes=180),
            )

        assert world.versions.bumped == []


class TestTheOwnerHasToExist:
    @pytest.mark.parametrize("kind", ["area", "habit", "task"], ids=["area", "habit", "task"])
    async def test_reading_an_unknown_owner_is_a_404(self, kind: str) -> None:
        world = World()

        with pytest.raises(NotFound):
            await world.service.read(world.principal, PreferenceOwnerKind(kind), uuid4())

    @pytest.mark.parametrize("kind", ["area", "habit", "task"], ids=["area", "habit", "task"])
    async def test_replacing_on_an_unknown_owner_is_a_404(self, kind: str) -> None:
        world = World()

        with pytest.raises(NotFound):
            await world.service.replace(
                world.principal, PreferenceOwnerKind(kind), uuid4(), declaration()
            )

        assert world.preferences.rows == []

    async def test_removing_from_an_unknown_owner_is_a_404(self) -> None:
        world = World()

        with pytest.raises(NotFound):
            await world.service.remove(world.principal, PreferenceOwnerKind.HABIT, uuid4())

    async def test_a_missing_preference_is_not_a_404(self) -> None:
        # The rule these routes are stated over: they 404 on the OWNER and never on the preference,
        # because an owner declaring none still has one in effect through its Area, or has none.
        world = World()

        read = await world.service.read(world.principal, PreferenceOwnerKind.AREA, world.area.id)

        assert read.owner == world.area_owner
        assert read.declared is None


class TestAuthorization:
    async def test_reading_needs_the_read_scope(self) -> None:
        world = World()
        without = Principal(
            tenant_id=world.tenant_id, user_id=uuid4(), scopes=frozenset({Scope.ADMIN})
        )

        with pytest.raises(Forbidden):
            await world.service.read(without, PreferenceOwnerKind.AREA, world.area.id)

    @pytest.mark.parametrize("method", ["replace", "remove"], ids=["replace", "remove"])
    async def test_mutating_needs_the_admin_scope(self, method: str) -> None:
        world = World()
        without = Principal(
            tenant_id=world.tenant_id, user_id=uuid4(), scopes=frozenset({Scope.PLAN_READ})
        )
        call = (
            world.service.replace(without, PreferenceOwnerKind.AREA, world.area.id, declaration())
            if method == "replace"
            else world.service.remove(without, PreferenceOwnerKind.AREA, world.area.id)
        )

        with pytest.raises(Forbidden):
            await call

    async def test_the_scope_is_checked_before_the_owner_is_read(self) -> None:
        # So an unauthorized caller cannot learn whether an identifier exists.
        world = World()
        without = Principal(tenant_id=world.tenant_id, user_id=uuid4(), scopes=frozenset())

        with pytest.raises(Forbidden):
            await world.service.read(without, PreferenceOwnerKind.AREA, uuid4())


class TestTheOwnerMappings:
    def test_every_kind_of_owner_has_a_table_to_read(self) -> None:
        # The dispatch is a mapping rather than a branch, so a fourth kind of owner is a missing
        # entry. Without this it would be a KeyError in production instead of a red test.
        world = World()
        owners = PreferenceOwners(
            areas=FakeAreaRepository(world.tenant_id),
            habits=FakeHabitRepository(world.tenant_id),
            tasks=FakeTaskRepository(world.tenant_id),
        )

        assert owners.kinds == frozenset(PreferenceOwnerKind)

    def test_every_kind_of_owner_has_a_column_to_be_addressed_through(self) -> None:
        assert set(OWNER_COLUMN) == set(PreferenceOwnerKind)

    async def test_a_habits_chain_climbs_to_its_own_area(self) -> None:
        world = World()
        owners = PreferenceOwners(
            areas=FakeAreaRepository(world.tenant_id, [world.area]),
            habits=FakeHabitRepository(world.tenant_id, [world.habit]),
            tasks=FakeTaskRepository(world.tenant_id, [world.task]),
        )

        resolved = await owners.find(PreferenceOwnerKind.HABIT, world.habit.id)

        assert resolved is not None
        assert resolved.area_id == world.area.id
        assert resolved.area_owner == world.area_owner

    async def test_an_areas_chain_climbs_to_itself(self) -> None:
        world = World()
        owners = PreferenceOwners(
            areas=FakeAreaRepository(world.tenant_id, [world.area]),
            habits=FakeHabitRepository(world.tenant_id),
            tasks=FakeTaskRepository(world.tenant_id),
        )

        resolved = await owners.find(PreferenceOwnerKind.AREA, world.area.id)

        assert resolved is not None
        assert resolved.area_owner == resolved.owner


class TestTheRowMapping:
    """What a schemaless JSONB column can hold that the entity cannot see, refused where it is read.

    The table validates the window list's shape and its length and nothing inside it, so these are
    the refusals the record adds. Each is a 422 naming the field rather than a 500: what broke is
    one row, not the server.
    """

    def test_a_window_list_survives_the_round_trip(self) -> None:
        stored = windows_as_json((EARLY, MIDDAY))

        assert windows_from_json(stored) == (EARLY, MIDDAY)

    def test_a_stored_value_that_is_not_a_list_is_refused(self) -> None:
        with pytest.raises(PreferenceError, match="ordered list"):
            windows_from_json({"start": "05:30:00"})

    def test_a_stored_element_that_is_not_an_object_is_refused(self) -> None:
        with pytest.raises(PreferenceError, match="object naming"):
            windows_from_json(["05:30:00"])

    def test_a_stored_bound_that_is_not_a_string_is_refused(self) -> None:
        with pytest.raises(PreferenceError, match="wall time"):
            windows_from_json([{"start": 530, "end": "07:00:00"}])

    def test_a_stored_bound_that_is_not_a_time_is_refused(self) -> None:
        with pytest.raises(PreferenceError, match="not a time"):
            windows_from_json([{"start": "half five", "end": "07:00:00"}])

    def test_a_stored_bound_missing_altogether_is_refused(self) -> None:
        with pytest.raises(PreferenceError, match="wall time"):
            windows_from_json([{"start": "05:30:00"}])

    def test_a_stored_bound_carrying_an_offset_is_refused_on_the_way_out(self) -> None:
        # The tz-truncation class from the other side. Nothing can write this through the routes,
        # because the boundary refuses an offset, but a JSONB string carries one verbatim rather
        # than dropping it the way a column with no offset would, so a hand-written row is refused
        # where it is read rather than resolved against the wrong hour.
        with pytest.raises(PreferenceError, match="names no zone"):
            windows_from_json([{"start": "05:30:00+01:00", "end": "07:00:00"}])

    @pytest.mark.parametrize("kind", ["area", "habit", "task"], ids=["area", "habit", "task"])
    def test_an_owner_survives_the_round_trip(self, kind: str) -> None:
        owner = PreferenceOwner(kind=PreferenceOwnerKind(kind), id=uuid4())
        area_id, habit_id, task_id = owner_columns(owner)

        assert owner_of(owner.kind, area_id=area_id, habit_id=habit_id, task_id=task_id) == owner

    @pytest.mark.parametrize("kind", ["area", "habit", "task"], ids=["area", "habit", "task"])
    def test_exactly_one_reference_is_set_for_each_kind(self, kind: str) -> None:
        owner = PreferenceOwner(kind=PreferenceOwnerKind(kind), id=uuid4())

        assert [column for column in owner_columns(owner) if column is not None] == [owner.id]

    def test_a_row_naming_a_kind_it_holds_no_identifier_for_is_a_fault(self) -> None:
        # Not a 422: nothing a caller sent is wrong, so there is no field to name. The table's own
        # constraint pairs the discriminator with the reference, so reaching this means that
        # constraint is gone.
        with pytest.raises(UnattributedPreferenceRow, match="belongs to nothing"):
            owner_of(PreferenceOwnerKind.HABIT, area_id=uuid4(), habit_id=None, task_id=None)
