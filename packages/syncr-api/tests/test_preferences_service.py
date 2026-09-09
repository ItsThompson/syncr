"""The preference service against fakes: the chain, the cap's owner, and the bump's gate.

The repositories are replaced and the clock is injected, so "today" is a literal date and the week
the bump floors at is assertable without waiting for a Monday. The domain is real throughout: the
entity and the resolution are the shipped functions, because a stubbed resolution would let this
suite pass while an override was silently ignored.

Three tests are the ones to read.

``test_removing_an_overrides_preference_restores_its_areas`` is the rule stated as behavior: a
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
from syncr_api.core.errors import Forbidden, NotFound, ValidationFailed
from syncr_api.core.principal import Principal
from syncr_api.core.scopes import ALL_SCOPES, Scope
from syncr_api.habits.records import HabitRecord
from syncr_api.habits.repository import HabitRepository
from syncr_api.plans.resolved_preferences import resolved_preferences
from syncr_api.preferences.declarations import DeclaredWindow, PreferenceDeclaration
from syncr_api.preferences.owners import (
    MAX_AREA_DEPTH,
    PreferenceOwners,
    UnreadableAreaAncestry,
)
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
from syncr_api.user_settings.solve_inputs import BacklogWideBump, WeekRange
from syncr_domain.habits import BindingSource, CadenceKind, MissPolicy
from syncr_domain.identity import BindingRef
from syncr_domain.preferences import (
    MAX_WINDOWS,
    LocalTimeWindow,
    Preference,
    PreferenceError,
    PreferenceOwner,
    PreferenceOwnerKind,
    PreferenceStrength,
)
from syncr_domain.tasks import Priority, TaskStatus
from syncr_domain.weeks import IsoWeek, active_zone_by_date
from syncr_domain.zones import ZoneProfile
from syncr_solver.inputs import EligibleTask
from tests.service_fakes import FakeAreaRepository, FakeSettingsRepository

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
    identifier no caller holds. :meth:`upsert` stores one row per owner for the same reason the
    real one does: the three unique indexes.
    """

    def __init__(self, tenant_id: TenantId, stored: list[PreferenceRecord] | None = None) -> None:
        self._tenant_id = tenant_id
        self.rows = list(stored or [])

    async def find(self, owner: PreferenceOwner) -> PreferenceRecord | None:
        return next((row for row in self.rows if row.owner == owner), None)

    async def upsert(self, preference: Preference, *, created_at: datetime) -> None:
        if not any(row.owner == preference.owner for row in self.rows):
            self.rows.append(record(self._tenant_id, preference, created_at=created_at))
            return
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

    async def list_all(self) -> tuple[PreferenceRecord, ...]:
        return tuple(self.rows)


class CountingAreas(FakeAreaRepository):
    """Counts how many times the whole table was listed, so the one-statement rule is assertable."""

    def __init__(self, tenant_id: TenantId, stored: list[AreaRecord] | None = None) -> None:
        super().__init__(tenant_id, stored)
        self.reads = 0

    async def list_all(self) -> tuple[AreaRecord, ...]:
        self.reads += 1
        return await super().list_all()


class CountingPreferences(FakePreferenceRepository):
    """Counts how many times every preference was listed, for the same assertion."""

    def __init__(self, tenant_id: TenantId, stored: list[PreferenceRecord] | None = None) -> None:
        super().__init__(tenant_id, stored)
        self.listings = 0

    async def list_all(self) -> tuple[PreferenceRecord, ...]:
        self.listings += 1
        return await super().list_all()


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


def area(
    tenant_id: TenantId,
    *,
    name: str = "Fitness",
    parent_id: AreaId | None = None,
    pigment_index: int = 0,
) -> AreaRecord:
    return AreaRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        parent_id=parent_id,
        name=name,
        pigment_index=pigment_index,
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
        charged_misses=0,
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


def stretches(*bounds: tuple[time, time]) -> PreferenceDeclaration:
    """A declaration stating each stretch as a request states it: two wall times, unsplit.

    Separate from ``declaration`` rather than a mode of it, because a stretch that wraps past
    midnight is not a domain window and cannot be built as one: the split is what this shape is
    handed to the service to perform.
    """
    return PreferenceDeclaration(
        windows=tuple(DeclaredWindow(start=start, end=end) for start, end in bounds),
        strength=PreferenceStrength.STRONG,
        preferred_duration_minutes=None,
        max_per_day_minutes=None,
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
    """One tenant with two nested Areas, a habit and a task in each, and the service over fakes.

    The child subtree exists so the ancestry is exercisable without a second world: ``area`` is
    the root, ``child_area`` hangs under it, and the child's habit and task live inside it. Every
    existing test addresses owners by identifier, so the extra rows change nothing for them.
    """

    def __init__(self, stored: list[Preference] | None = None) -> None:
        self.tenant_id: TenantId = uuid4()
        self.principal = Principal(tenant_id=self.tenant_id, user_id=uuid4(), scopes=ALL_SCOPES)
        self.area = area(self.tenant_id)
        self.child_area = area(self.tenant_id, name="Fitness / Running", parent_id=self.area.id)
        self.habit = habit(self.tenant_id, self.area.id)
        self.task = task(self.tenant_id, self.area.id)
        self.child_habit = habit(self.tenant_id, self.child_area.id)
        self.child_task = task(self.tenant_id, self.child_area.id)
        self.preferences = FakePreferenceRepository(
            self.tenant_id, [record(self.tenant_id, one) for one in (stored or [])]
        )
        self.versions = RecordingVersions()
        self.service = PreferenceService(
            preferences=self.preferences,
            owners=PreferenceOwners(
                areas=FakeAreaRepository(self.tenant_id, [self.area, self.child_area]),
                habits=FakeHabitRepository(self.tenant_id, [self.habit, self.child_habit]),
                tasks=FakeTaskRepository(self.tenant_id, [self.task, self.child_task]),
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
    def child_area_owner(self) -> PreferenceOwner:
        return PreferenceOwner(kind=PreferenceOwnerKind.AREA, id=self.child_area.id)

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
        # The rule's own claim, over all three owners at once: each resolves to one
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


class TestTheChainClimbsTheAncestry:
    """A preference declared above an owner is read below it, nearest ancestor winning.

    The walk lives in ``PreferenceOwners.ancestry``; these tests drive it through the service,
    because what the routes answer is the contract: a preference on ``Fitness`` reaches
    ``Fitness / Running`` and everything inside it.
    """

    async def test_a_preference_on_the_parent_area_is_read_by_the_child_area(self) -> None:
        world = World()
        await world.service.replace(
            world.principal, PreferenceOwnerKind.AREA, world.area.id, declaration()
        )

        read = await world.service.read(
            world.principal, PreferenceOwnerKind.AREA, world.child_area.id
        )

        assert read.declared is None
        assert read.in_effect is not None
        assert read.in_effect.owner == world.area_owner
        assert read.in_effect.windows == (EARLY,)

    @pytest.mark.parametrize("kind", ["habit", "task"], ids=["habit", "task"])
    async def test_a_preference_on_the_parent_area_is_read_inside_the_child(
        self, kind: str
    ) -> None:
        world = World()
        await world.service.replace(
            world.principal, PreferenceOwnerKind.AREA, world.area.id, declaration()
        )
        owner_id = world.child_habit.id if kind == "habit" else world.child_task.id

        read = await world.service.read(world.principal, PreferenceOwnerKind(kind), owner_id)

        assert read.declared is None
        assert read.in_effect is not None
        assert read.in_effect.owner == world.area_owner
        assert read.in_effect.windows == (EARLY,)

    async def test_the_route_and_assembler_agree_for_every_owner_in_three_area_levels(self) -> None:
        world = World()
        trail = area(
            world.tenant_id,
            name="Fitness / Running / Trail",
            parent_id=world.child_area.id,
        )
        trail_habit = habit(world.tenant_id, trail.id)
        trail_task = task(world.tenant_id, trail.id)
        areas = [world.area, world.child_area, trail]
        habits = [world.habit, world.child_habit, trail_habit]
        tasks = [world.task, world.child_task, trail_task]
        world.service = PreferenceService(
            preferences=world.preferences,
            owners=PreferenceOwners(
                areas=FakeAreaRepository(world.tenant_id, areas),
                habits=FakeHabitRepository(world.tenant_id, habits),
                tasks=FakeTaskRepository(world.tenant_id, tasks),
            ),
            bump=BacklogWideBump(
                versions=world.versions,
                settings=FakeSettingsRepository(world.tenant_id),
            ),
            clock=lambda: NOW,
        )
        await world.service.replace(
            world.principal, PreferenceOwnerKind.AREA, world.area.id, declaration()
        )
        route_answers = {
            read.owner: read.in_effect
            for read in [
                await world.service.read(world.principal, PreferenceOwnerKind.AREA, area.id)
                for area in areas
            ]
            + [
                await world.service.read(world.principal, PreferenceOwnerKind.HABIT, habit.id)
                for habit in habits
            ]
            + [
                await world.service.read(world.principal, PreferenceOwnerKind.TASK, task.id)
                for task in tasks
            ]
        }
        assembled = resolved_preferences(
            world.preferences.rows,
            areas=areas,
            habits=habits,
            tasks=[
                EligibleTask(
                    binding=BindingRef.for_task(task.id),
                    remaining_minutes=task.estimate_minutes,
                    priority=task.priority,
                    min_chunk_minutes=task.min_chunk_minutes,
                    splittable=task.splittable,
                    area_id=task.area_id,
                    title=task.title,
                    deadline=task.deadline,
                )
                for task in tasks
            ],
            zone_by_date=active_zone_by_date(WEEK_31, ZoneProfile(LONDON)),
        )

        assert all(preference is not None for preference in route_answers.values())
        assert {preference.owner for preference in assembled} == set(route_answers)
        assert {
            preference.owner: (preference.strength, preference.preferred_duration_minutes)
            for preference in assembled
        } == {
            owner: (preference.strength, preference.preferred_duration_minutes)
            for owner, preference in route_answers.items()
            if preference is not None
        }
        assert {len(preference.windows) for preference in assembled} == {7}

    async def test_the_nearest_ancestor_wins_over_its_own_ancestors(self) -> None:
        world = World()
        await world.service.replace(
            world.principal, PreferenceOwnerKind.AREA, world.area.id, declaration()
        )
        await world.service.replace(
            world.principal,
            PreferenceOwnerKind.AREA,
            world.child_area.id,
            declaration(windows=(MIDDAY,), strength=PreferenceStrength.SOFT),
        )

        read = await world.service.read(
            world.principal, PreferenceOwnerKind.HABIT, world.child_habit.id
        )

        assert read.in_effect is not None
        assert read.in_effect.owner == world.child_area_owner
        assert read.in_effect.windows == (MIDDAY,)
        assert read.in_effect.strength is PreferenceStrength.SOFT

    async def test_an_override_declared_on_the_child_replaces_the_parents_wholly(self) -> None:
        # Whole replacement at depth: the child Area declares windows and no ideal duration, so
        # the parent's 90 does not reach anything that resolves through the child.
        world = World()
        await world.service.replace(
            world.principal,
            PreferenceOwnerKind.AREA,
            world.area.id,
            declaration(preferred_duration_minutes=90),
        )
        await world.service.replace(
            world.principal, PreferenceOwnerKind.AREA, world.child_area.id, declaration()
        )

        read = await world.service.read(
            world.principal, PreferenceOwnerKind.HABIT, world.child_habit.id
        )

        assert read.in_effect is not None
        assert read.in_effect.owner == world.child_area_owner
        assert read.in_effect.preferred_duration_minutes is None

    async def test_an_override_inside_the_child_still_wins_over_both_areas(self) -> None:
        world = World()
        await world.service.replace(
            world.principal, PreferenceOwnerKind.AREA, world.area.id, declaration()
        )
        await world.service.replace(
            world.principal,
            PreferenceOwnerKind.AREA,
            world.child_area.id,
            declaration(windows=(EVENING,)),
        )
        await world.service.replace(
            world.principal,
            PreferenceOwnerKind.HABIT,
            world.child_habit.id,
            declaration(windows=(MIDDAY,), strength=PreferenceStrength.SOFT),
        )

        read = await world.service.read(
            world.principal, PreferenceOwnerKind.HABIT, world.child_habit.id
        )

        assert read.in_effect is not None
        assert read.in_effect.owner.kind is PreferenceOwnerKind.HABIT
        assert read.in_effect.windows == (MIDDAY,)

    async def test_removing_the_child_areas_preference_falls_back_to_the_parent(self) -> None:
        world = World()
        await world.service.replace(
            world.principal, PreferenceOwnerKind.AREA, world.area.id, declaration()
        )
        await world.service.replace(
            world.principal,
            PreferenceOwnerKind.AREA,
            world.child_area.id,
            declaration(windows=(MIDDAY,)),
        )

        read = await world.service.remove(
            world.principal, PreferenceOwnerKind.AREA, world.child_area.id
        )

        assert read.declared is None
        assert read.in_effect is not None
        assert read.in_effect.owner == world.area_owner


class TestTheAncestryWalk:
    """The walk itself: one read, nearest first, refusing stored cycles by name."""

    def owners(self, world: World) -> PreferenceOwners:
        return PreferenceOwners(
            areas=FakeAreaRepository(world.tenant_id, [world.area, world.child_area]),
            habits=FakeHabitRepository(world.tenant_id),
            tasks=FakeTaskRepository(world.tenant_id),
        )

    async def test_the_walk_answers_nearest_first_and_ends_at_the_root(self) -> None:
        world = World()

        found = await self.owners(world).ancestry(world.child_area.id)

        assert [one.name for one in found] == ["Fitness / Running", "Fitness"]

    async def test_the_root_areas_ancestry_is_itself_alone(self) -> None:
        world = World()

        found = await self.owners(world).ancestry(world.area.id)

        assert [one.id for one in found] == [world.area.id]

    async def test_a_cycle_in_the_stored_parent_links_is_refused_naming_the_areas(self) -> None:
        # Only data written around the application can close a loop: the Areas module confirms a
        # declared parent exists and an Area never moves. So this is a stored-data fault, not a
        # request fault, and it is raised as one.
        world = World()
        looping = replace(world.child_area, parent_id=world.child_area.id)
        owners = PreferenceOwners(
            areas=FakeAreaRepository(world.tenant_id, [world.area, looping]),
            habits=FakeHabitRepository(world.tenant_id),
            tasks=FakeTaskRepository(world.tenant_id),
        )

        with pytest.raises(UnreadableAreaAncestry, match="Fitness / Running") as refused:
            await owners.ancestry(world.child_area.id)

        assert "Fitness / Running -> Fitness / Running" in str(refused.value)

    async def test_a_cycle_through_an_ancestor_names_every_area_it_passes(self) -> None:
        world = World()
        looping = replace(world.area, parent_id=world.child_area.id)
        owners = PreferenceOwners(
            areas=FakeAreaRepository(world.tenant_id, [looping, world.child_area]),
            habits=FakeHabitRepository(world.tenant_id),
            tasks=FakeTaskRepository(world.tenant_id),
        )

        with pytest.raises(
            UnreadableAreaAncestry, match="Fitness / Running -> Fitness -> Fitness / Running"
        ):
            await owners.ancestry(world.child_area.id)

    async def test_an_ancestry_deeper_than_the_cap_is_refused(self) -> None:
        world = World()
        deepest = world.child_area
        rows = [world.area, deepest]
        for _ in range(MAX_AREA_DEPTH):
            deepest = area(world.tenant_id, name="Deeper", parent_id=deepest.id)
            rows.append(deepest)
        owners = PreferenceOwners(
            areas=FakeAreaRepository(world.tenant_id, rows),
            habits=FakeHabitRepository(world.tenant_id),
            tasks=FakeTaskRepository(world.tenant_id),
        )

        with pytest.raises(UnreadableAreaAncestry, match=str(MAX_AREA_DEPTH)):
            await owners.ancestry(deepest.id)

    async def test_exactly_the_caps_depth_of_areas_is_walked(self) -> None:
        # The control for the refusal above: without it, a walk that stopped at one link would
        # pass both.
        world = World()
        deepest = world.child_area
        rows = [world.area, deepest]
        for _ in range(MAX_AREA_DEPTH - 2):
            deepest = area(world.tenant_id, name="Deeper", parent_id=deepest.id)
            rows.append(deepest)
        owners = PreferenceOwners(
            areas=FakeAreaRepository(world.tenant_id, rows),
            habits=FakeHabitRepository(world.tenant_id),
            tasks=FakeTaskRepository(world.tenant_id),
        )

        found = await owners.ancestry(deepest.id)

        assert len(found) == MAX_AREA_DEPTH

    async def test_a_parent_identifier_naming_no_row_of_this_tenant_ends_the_walk(self) -> None:
        # Another tenant's identifier reads as no parent at all: the scoped listing never
        # returned it, so the walk stops short rather than crossing tenants or hanging.
        world = World()
        orphaned = replace(world.child_area, parent_id=uuid4())
        owners = PreferenceOwners(
            areas=FakeAreaRepository(world.tenant_id, [world.area, orphaned]),
            habits=FakeHabitRepository(world.tenant_id),
            tasks=FakeTaskRepository(world.tenant_id),
        )

        found = await owners.ancestry(world.child_area.id)

        assert [one.id for one in found] == [orphaned.id]

    async def test_a_read_issues_one_listing_per_table_whatever_the_depth(self) -> None:
        # The one-statement rule observed at the seam: however deep the ancestry, one read of the
        # Areas and one of the preferences serve the whole chain.
        world = World()
        await world.service.replace(
            world.principal, PreferenceOwnerKind.AREA, world.area.id, declaration()
        )
        areas = CountingAreas(world.tenant_id, [world.area, world.child_area])
        preferences = CountingPreferences(
            world.tenant_id,
            [record(world.tenant_id, declaration().as_preference(world.area_owner))],
        )
        service = PreferenceService(
            preferences=preferences,
            owners=PreferenceOwners(
                areas=areas,
                habits=FakeHabitRepository(world.tenant_id, [world.child_habit]),
                tasks=FakeTaskRepository(world.tenant_id),
            ),
            bump=BacklogWideBump(
                versions=RecordingVersions(), settings=FakeSettingsRepository(world.tenant_id)
            ),
            clock=lambda: NOW,
        )

        await service.read(world.principal, PreferenceOwnerKind.HABIT, world.child_habit.id)

        assert areas.reads == 1
        assert preferences.listings == 1


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


class TestAStretchAcrossMidnightIsSplitWhereItIsAuthored:
    """The wrap, driven through the service that stores it rather than through the entity.

    Every case here reaches the split through ``PreferenceService.replace``, which is the only
    caller that turns a request's two wall times into stored windows, and reads the stored ROWS
    rather than the returned entity: the halves have to survive the JSON mapping to be a
    declaration the user can read back.
    """

    async def test_a_wrap_is_stored_as_two_windows_split_at_midnight(self) -> None:
        world = World()

        read = await world.service.replace(
            world.principal,
            PreferenceOwnerKind.AREA,
            world.area.id,
            stretches((time(23, 0), time(1, 0))),
        )

        assert read.declared is not None
        assert [str(window) for window in read.declared.windows] == ["00:00-01:00", "23:00-00:00"]
        assert [dict(window) for window in world.preferences.rows[0].windows] == [
            {"start": "00:00:00", "end": "01:00:00"},
            {"start": "23:00:00", "end": "00:00:00"},
        ]

    async def test_a_stored_wrap_reads_back_as_the_two_windows_it_was_split_into(self) -> None:
        # The row is mapped back through the entity on the way out, so an end of 00:00 has to be
        # readable as well as writable: a reader that refused it would make the wrap unreadable.
        world = World()
        await world.service.replace(
            world.principal,
            PreferenceOwnerKind.AREA,
            world.area.id,
            stretches((time(23, 0), time(1, 0))),
        )

        read = await world.service.read(world.principal, PreferenceOwnerKind.AREA, world.area.id)

        assert read.in_effect is not None
        assert [str(window) for window in read.in_effect.windows] == ["00:00-01:00", "23:00-00:00"]

    async def test_a_stretch_inside_one_day_is_stored_as_one_window(self) -> None:
        # The control. A split on every declaration would store two windows here.
        world = World()

        read = await world.service.replace(
            world.principal,
            PreferenceOwnerKind.AREA,
            world.area.id,
            stretches((time(5, 30), time(7, 0))),
        )

        assert read.declared is not None
        assert [str(window) for window in read.declared.windows] == ["05:30-07:00"]

    async def test_a_stretch_that_ends_at_midnight_is_stored_as_one_window(self) -> None:
        world = World()

        read = await world.service.replace(
            world.principal,
            PreferenceOwnerKind.AREA,
            world.area.id,
            stretches((time(23, 0), time(0, 0))),
        )

        assert read.declared is not None
        assert [str(window) for window in read.declared.windows] == ["23:00-00:00"]

    @pytest.mark.parametrize("bound", [time(23, 0), time(0, 0)], ids=["a time of day", "midnight"])
    async def test_a_stretch_that_ends_where_it_starts_is_refused_and_stores_nothing(
        self, bound: time
    ) -> None:
        world = World()

        with pytest.raises(ValidationFailed) as refused:
            await world.service.replace(
                world.principal, PreferenceOwnerKind.AREA, world.area.id, stretches((bound, bound))
            )

        assert refused.value.errors is not None
        assert [error.field for error in refused.value.errors] == ["windows"]
        assert world.preferences.rows == []

    async def test_a_wrap_whose_union_with_another_stretch_is_one_window_is_refused(self) -> None:
        world = World()

        with pytest.raises(ValidationFailed) as refused:
            await world.service.replace(
                world.principal,
                PreferenceOwnerKind.AREA,
                world.area.id,
                stretches((time(22, 0), time(23, 30)), (time(23, 0), time(1, 0))),
            )

        assert "overlap" in str(refused.value)
        assert world.preferences.rows == []

    async def test_a_wrap_consumes_two_of_the_permitted_windows(self) -> None:
        world = World()
        room = tuple((time(2 + index, 0), time(2 + index, 30)) for index in range(MAX_WINDOWS - 2))

        read = await world.service.replace(
            world.principal,
            PreferenceOwnerKind.AREA,
            world.area.id,
            stretches((time(23, 0), time(1, 0)), *room),
        )

        assert read.declared is not None
        assert len(read.declared.windows) == MAX_WINDOWS

    async def test_one_window_past_the_bound_is_refused_when_a_wrap_is_among_them(self) -> None:
        # The declaration names six stretches, which the request shape permits; the wrap makes
        # them seven windows, which is what the user is told they have.
        world = World()
        room = tuple((time(2 + index, 0), time(2 + index, 30)) for index in range(MAX_WINDOWS - 1))

        with pytest.raises(ValidationFailed) as refused:
            await world.service.replace(
                world.principal,
                PreferenceOwnerKind.AREA,
                world.area.id,
                stretches((time(23, 0), time(1, 0)), *room),
            )

        assert str(MAX_WINDOWS) in str(refused.value)
        assert world.preferences.rows == []

    async def test_an_empty_declaration_still_names_no_window_at_all(self) -> None:
        # The split runs over each declared stretch, so a declaration of none flattens to none
        # rather than to one window nobody asked for.
        world = World()

        read = await world.service.replace(
            world.principal, PreferenceOwnerKind.AREA, world.area.id, stretches()
        )

        assert read.declared is not None
        assert read.declared.windows == ()


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
        # The Area-only cap at the service layer. The request shape has no field for a cap, so this
        # is the layer below the boundary refusal: nothing that reaches the service can store one
        # either.
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
        # The cap and the resolution together: the Area's cap is not something an override's
        # resolution can report, so nothing downstream can read a relaxed one.
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
