"""The habit service against fakes: the invariants, the two derivations, and the bump.

The repositories are replaced and the clock is injected, so "today" is a literal date and the
week the bump floors at is assertable without waiting for a Monday. The domain is real
throughout: the entity, the cursor, and the debt are the shipped functions, because a stubbed
derivation would let this suite pass while a cursor sat on the wrong variant.

The outcome log is supplied through the reader seam, which is what lets a cursor and a debt figure
be asserted against an occupied log at all. Production wires ``HabitOutcomeLog`` over
``block_outcomes``; ``NoRecordedOutcomes`` answers with nothing, and one test here reads a habit
that has never had an occurrence recorded against it.

The tests worth reading are the ones about what does NOT happen. No method writes a cursor, and
there is no method that could. Editing a habit leaves the outcome log untouched, so the past reads
as it did. And a ``PATCH`` naming only a binding source is refused when the stored variants
contradict it, which is the case a request schema cannot catch because it cannot see the row.

This is the one suite that reads against ``NoRecordedOutcomes``, and
``test_habit_outcome_reader_seam.py`` is what holds that claim to being true.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syncr_api.areas.records import AreaRecord
from syncr_api.core.errors import Forbidden, NotFound, ValidationFailed
from syncr_api.core.patches import ABSENT
from syncr_api.core.principal import Principal
from syncr_api.core.scopes import ALL_SCOPES, Scope
from syncr_api.habits.declarations import DeclaredCadence, HabitChange, HabitDeclaration
from syncr_api.habits.outcome_log import NoRecordedOutcomes
from syncr_api.habits.records import HabitRecord, columns_of
from syncr_api.habits.repository import HabitRepository
from syncr_api.habits.service import HabitService
from syncr_api.user_settings.solve_inputs import BacklogWideBump, WeekRange
from syncr_domain.habits import BindingSource, CadenceKind, MissPolicy
from syncr_domain.identity import index_occurrence_key
from syncr_domain.intervals import Interval
from syncr_domain.outcomes import MISS_STATE, HabitOutcome, OutcomeState
from syncr_domain.weeks import IsoWeek
from tests.service_fakes import FakeAreaRepository, FakeSettingsRepository

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_domain.habits import Habit
    from syncr_domain.identifiers import AreaId, HabitId, TenantId

LONDON = "Europe/London"

# A Sunday, the last day of 2026-W31, at 09:00 UTC: mid-morning in London, so the local date and
# the UTC date agree and these tests are about habits rather than about a date boundary.
NOW = datetime(2026, 8, 2, 9, 0, tzinfo=UTC)
WEEK_31 = IsoWeek.parse("2026-W31")

GYM_SPLIT = ("Shoulder & Arms", "Legs", "Chest & Back", "Cardio")

FOUR_A_WEEK = DeclaredCadence(kind=CadenceKind.TIMES_PER_WEEK, times_per_week=4, approx_days=None)
DAILY = DeclaredCadence(kind=CadenceKind.DAILY, times_per_week=None, approx_days=None)


class FakeHabitRepository(HabitRepository):
    """The real repository's interface over a list of records, and no database."""

    def __init__(self, tenant_id: TenantId, stored: list[HabitRecord] | None = None) -> None:
        self._tenant_id = tenant_id
        self.rows = list(stored or [])

    async def list_all(self, *, area_id: AreaId | None = None) -> tuple[HabitRecord, ...]:
        ordered = sorted(self.rows, key=lambda row: (row.created_at, row.id))
        return tuple(row for row in ordered if area_id is None or row.area_id == area_id)

    async def find(self, habit_id: HabitId) -> HabitRecord | None:
        return next((row for row in self.rows if row.id == habit_id), None)

    async def create(
        self, *, area_id: AreaId, title: str, habit: Habit, created_at: datetime
    ) -> HabitRecord:
        kind, times_per_week, approx_days = columns_of(habit.cadence)
        created = HabitRecord(
            id=habit.id,
            tenant_id=self._tenant_id,
            area_id=area_id,
            title=title,
            cadence_kind=kind,
            cadence_times_per_week=times_per_week,
            cadence_approx_days=approx_days,
            duration_min_minutes=habit.duration.min_minutes,
            duration_max_minutes=habit.duration.max_minutes,
            miss_policy=habit.miss_policy,
            binding_source=habit.binding_source,
            variants=habit.variants,
            debt_cap_periods=habit.debt_cap_periods,
            charged_misses=0,
            created_at=created_at,
        )
        self.rows.append(created)
        return created

    async def write(self, habit: Habit, *, title: str) -> None:
        kind, times_per_week, approx_days = columns_of(habit.cadence)
        self.rows = [
            replace(
                row,
                title=title,
                cadence_kind=kind,
                cadence_times_per_week=times_per_week,
                cadence_approx_days=approx_days,
                duration_min_minutes=habit.duration.min_minutes,
                duration_max_minutes=habit.duration.max_minutes,
                miss_policy=habit.miss_policy,
                binding_source=habit.binding_source,
                variants=habit.variants,
                debt_cap_periods=habit.debt_cap_periods,
            )
            if row.id == habit.id
            else row
            for row in self.rows
        ]

    async def remove(self, habit_id: HabitId) -> None:
        self.rows = [row for row in self.rows if row.id != habit_id]


class RecordingVersions:
    """Records what would have been bumped, so a bump is assertable without a database."""

    def __init__(self) -> None:
        self.bumped: list[WeekRange] = []

    async def bump(self, weeks: WeekRange) -> None:
        self.bumped.append(weeks)


class RecordedOutcomes:
    """The outcome log the two derivations read, supplied through the production seam."""

    def __init__(self, log: Sequence[HabitOutcome] = ()) -> None:
        self.log = tuple(log)
        self.reads: list[tuple[HabitId, ...]] = []

    async def read(self, habit_ids: Sequence[HabitId]) -> tuple[HabitOutcome, ...]:
        self.reads.append(tuple(habit_ids))
        return self.log

    async def latest(
        self, habit_ids: Sequence[HabitId], *, since: datetime
    ) -> dict[HabitId, datetime | None]:
        # The same reduction the production reader performs, so a future long-interval case here
        # reads as overdue rather than as never recorded.
        latest_seen: dict[HabitId, datetime | None] = dict.fromkeys(habit_ids)
        for row in self.log:
            if row.habit_id in latest_seen and row.occurred_at >= since:
                seen = latest_seen[row.habit_id]
                if seen is None or row.occurred_at > seen:
                    latest_seen[row.habit_id] = row.occurred_at
        return latest_seen

    async def settled_within(
        self, habit_ids: Sequence[HabitId], *, span: Interval
    ) -> tuple[HabitOutcome, ...]:
        return ()


def outcome(
    habit_id: HabitId,
    state: OutcomeState,
    *,
    index: int = 0,
    days_before: int = 7,
    confirmed: bool = True,
) -> HabitOutcome:
    at = NOW - timedelta(days=days_before)
    return HabitOutcome(
        habit_id=habit_id,
        occurrence_key=index_occurrence_key(index),
        state=state,
        occurred_at=at,
        confirmed_at=at + timedelta(hours=12) if confirmed else None,
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


def declaration(area_id: AreaId, **overrides: object) -> HabitDeclaration:
    fields: dict[str, object] = {
        "area_id": area_id,
        "title": "Gym",
        "cadence": FOUR_A_WEEK,
        "min_duration_minutes": 90,
        "max_duration_minutes": None,
        "miss_policy": MissPolicy.FORGIVE,
        "binding_source": BindingSource.FIXED,
        "variants": (),
        "debt_cap_periods": 2,
    }
    fields.update(overrides)
    return HabitDeclaration(**fields)  # type: ignore[arg-type]


def nothing_stated() -> HabitChange:
    """A ``PATCH`` that stated no field at all. Every test starts from this and replaces one."""
    return HabitChange(
        title=ABSENT,
        cadence=ABSENT,
        min_duration_minutes=ABSENT,
        max_duration_minutes=ABSENT,
        miss_policy=ABSENT,
        binding_source=ABSENT,
        variants=ABSENT,
        debt_cap_periods=ABSENT,
    )


class Fixture:
    """The service, its fakes, and the principal, assembled once per test."""

    def __init__(
        self,
        log: Sequence[HabitOutcome] = (),
        home_zone: str = LONDON,
        at: datetime = NOW,
    ) -> None:
        self.tenant_id = uuid4()
        self.principal = Principal(tenant_id=self.tenant_id, user_id=uuid4(), scopes=ALL_SCOPES)
        self.area = area(self.tenant_id)
        self.habits = FakeHabitRepository(self.tenant_id)
        self.areas = FakeAreaRepository(self.tenant_id, [self.area])
        self.versions = RecordingVersions()
        self.outcomes = RecordedOutcomes(log)
        self.service = HabitService(
            habits=self.habits,
            areas=self.areas,
            outcomes=self.outcomes,
            bump=BacklogWideBump(
                versions=self.versions,
                settings=FakeSettingsRepository(self.tenant_id, home_zone=home_zone),
            ),
            clock=lambda: at,
        )


@pytest.fixture
def fixture() -> Fixture:
    return Fixture()


# --------------------------------------------------------------------------------
# Declaring
# --------------------------------------------------------------------------------


async def test_declaring_a_habit_stores_it_and_reports_both_derived_figures(
    fixture: Fixture,
) -> None:
    read = await fixture.service.create(fixture.principal, declaration(fixture.area.id))

    assert read.habit.title == "Gym"
    assert read.habit.cadence_kind is CadenceKind.TIMES_PER_WEEK
    assert (read.habit.duration_min_minutes, read.habit.duration_max_minutes) == (90, 90)
    assert read.cursor is None
    assert (read.debt.outstanding, read.debt.cap) == (0, 8)
    assert fixture.habits.rows == [read.habit]


async def test_an_omitted_ceiling_makes_the_duration_fixed(fixture: Fixture) -> None:
    """Fixed is min == max, so a caller writes the number once and reads it twice."""
    read = await fixture.service.create(
        fixture.principal, declaration(fixture.area.id, min_duration_minutes=45)
    )

    assert (read.habit.duration_min_minutes, read.habit.duration_max_minutes) == (45, 45)
    assert read.habit.as_habit().duration.is_fixed


async def test_a_stated_ceiling_makes_the_duration_elastic(fixture: Fixture) -> None:
    read = await fixture.service.create(
        fixture.principal,
        declaration(fixture.area.id, min_duration_minutes=30, max_duration_minutes=90),
    )

    assert not read.habit.as_habit().duration.is_fixed


async def test_a_habit_in_an_area_that_does_not_exist_is_refused_and_not_stored(
    fixture: Fixture,
) -> None:
    with pytest.raises(ValidationFailed) as refused:
        await fixture.service.create(fixture.principal, declaration(uuid4()))

    assert refused.value.errors is not None
    assert refused.value.errors[0].field == "areaId"
    assert fixture.habits.rows == []


async def test_a_rotation_without_variants_is_refused_at_the_service_and_not_stored(
    fixture: Fixture,
) -> None:
    """X3 through the service. The entity is what says so, and this is what maps it to a 422."""
    with pytest.raises(ValidationFailed, match="needs an ordered variant list"):
        await fixture.service.create(
            fixture.principal,
            declaration(fixture.area.id, binding_source=BindingSource.ROTATION, variants=()),
        )

    assert fixture.habits.rows == []


@pytest.mark.parametrize("source", [BindingSource.FIXED, BindingSource.QUEUE])
async def test_a_habit_that_does_not_rotate_carrying_variants_is_refused(
    fixture: Fixture, source: BindingSource
) -> None:
    """X4 through the service, for both of the sources it applies to."""
    with pytest.raises(ValidationFailed, match="carries no variants"):
        await fixture.service.create(
            fixture.principal,
            declaration(fixture.area.id, binding_source=source, variants=GYM_SPLIT),
        )

    assert fixture.habits.rows == []


async def test_a_cadence_whose_numbers_do_not_match_its_kind_is_a_stated_rejection(
    fixture: Fixture,
) -> None:
    """`daily` with a count is refused where the entity is built, not at a 500."""
    daily_with_a_count = DeclaredCadence(kind=CadenceKind.DAILY, times_per_week=4, approx_days=None)

    with pytest.raises(ValidationFailed, match="carries no times_per_week"):
        await fixture.service.create(
            fixture.principal, declaration(fixture.area.id, cadence=daily_with_a_count)
        )

    assert fixture.habits.rows == []


async def test_an_off_grid_duration_is_refused_where_the_declaration_is_read(
    fixture: Fixture,
) -> None:
    with pytest.raises(ValidationFailed, match="grid"):
        await fixture.service.create(
            fixture.principal, declaration(fixture.area.id, min_duration_minutes=25)
        )

    assert fixture.habits.rows == []


# --------------------------------------------------------------------------------
# The two derivations, over a real outcome log
# --------------------------------------------------------------------------------


async def test_a_rotation_habit_reports_its_cursor_read_only_with_its_provenance() -> None:
    fixture = Fixture()
    read = await fixture.service.create(
        fixture.principal,
        declaration(fixture.area.id, binding_source=BindingSource.ROTATION, variants=GYM_SPLIT),
    )
    fixture.outcomes.log = (
        outcome(read.habit.id, OutcomeState.COMPLETED, index=0),
        outcome(read.habit.id, OutcomeState.COMPLETED, index=1),
    )

    with_a_log = await fixture.service.read(fixture.principal, read.habit.id)

    assert with_a_log.cursor is not None
    assert (with_a_log.cursor.index, with_a_log.cursor.variant) == (2, "Chest & Back")
    assert with_a_log.cursor.previous_variant == "Legs"
    assert "no control to set it" in with_a_log.cursor.statement


async def test_a_fixed_source_habit_reports_no_cursor_at_all(fixture: Fixture) -> None:
    read = await fixture.service.create(fixture.principal, declaration(fixture.area.id))

    assert read.cursor is None


async def test_a_skip_leaves_the_cursor_where_it_was() -> None:
    fixture = Fixture()
    read = await fixture.service.create(
        fixture.principal,
        declaration(fixture.area.id, binding_source=BindingSource.ROTATION, variants=GYM_SPLIT),
    )
    fixture.outcomes.log = (
        outcome(read.habit.id, OutcomeState.COMPLETED, index=0),
        outcome(read.habit.id, MISS_STATE, index=1),
    )

    with_a_skip = await fixture.service.read(fixture.principal, read.habit.id)

    assert with_a_skip.cursor is not None
    assert with_a_skip.cursor.variant == "Legs"


async def test_the_current_debt_figure_is_visible_on_the_habit() -> None:
    """The charge reads off the row the outcome write restates, not off a walk taken here."""
    fixture = Fixture()
    read = await fixture.service.create(
        fixture.principal, declaration(fixture.area.id, miss_policy=MissPolicy.DEBT)
    )
    fixture.habits.rows = [replace(read.habit, charged_misses=3)]

    owed = await fixture.service.read(fixture.principal, read.habit.id)

    assert (owed.debt.outstanding, owed.debt.cap, owed.debt.misses) == (3, 8, 3)
    assert not owed.debt.raised_in_weekly_session
    # Nothing was read to answer it: the figure is the row's own.
    assert fixture.outcomes.reads == []


async def test_a_miss_at_the_cap_is_forgiven_and_raises_the_habit_for_the_weekly_session() -> None:
    fixture = Fixture()
    read = await fixture.service.create(
        fixture.principal,
        declaration(fixture.area.id, miss_policy=MissPolicy.DEBT, cadence=DAILY),
    )
    # A daily habit capped at two periods owes at most two days, so the third miss is forgiven.
    fixture.habits.rows = [replace(read.habit, charged_misses=3)]

    owed = await fixture.service.read(fixture.principal, read.habit.id)

    assert (owed.debt.outstanding, owed.debt.cap, owed.debt.forgiven_at_cap) == (2, 2, 1)
    assert owed.debt.raised_in_weekly_session


async def test_a_list_reads_the_outcome_log_once_for_the_whole_collection(
    fixture: Fixture,
) -> None:
    """One read per response rather than one per habit, so twenty rotations are one query."""
    for title in ("Gym", "Anki", "Laundry"):
        await fixture.service.create(
            fixture.principal,
            declaration(
                fixture.area.id,
                title=title,
                binding_source=BindingSource.ROTATION,
                variants=(title,),
            ),
        )
    fixture.outcomes.reads.clear()

    found = await fixture.service.list_all(fixture.principal)

    assert len(found) == 3
    assert len(fixture.outcomes.reads) == 1
    assert len(fixture.outcomes.reads[0]) == 3


async def test_a_collection_of_nothing_rotating_reads_the_outcome_log_not_at_all(
    fixture: Fixture,
) -> None:
    """The cursor is the one figure that derives here, so no rotation means no read.

    This is the bound stated where the read lives: a tenant whose habits all bind fixed content
    answers both figures without touching ``block_outcomes`` at all.
    """
    for title in ("Gym", "Anki", "Laundry"):
        await fixture.service.create(fixture.principal, declaration(fixture.area.id, title=title))
    fixture.outcomes.reads.clear()

    found = await fixture.service.list_all(fixture.principal)

    assert len(found) == 3
    assert fixture.outcomes.reads == []


async def test_the_charge_stands_when_nothing_of_the_log_is_reached() -> None:
    """A charge the log's whole history cannot answer still reads in full.

    Whatever leaves any window a reader takes, the figure a user acts on comes off the row the
    outcome write restated, so it cannot fall because rows aged out of somebody's reach.
    """
    fixture = Fixture(log=())
    read = await fixture.service.create(
        fixture.principal, declaration(fixture.area.id, miss_policy=MissPolicy.DEBT)
    )
    fixture.habits.rows = [replace(read.habit, charged_misses=3)]

    owed = await fixture.service.read(fixture.principal, read.habit.id)

    assert (owed.debt.misses, owed.debt.outstanding, owed.debt.cap) == (3, 3, 8)


async def test_a_list_can_be_narrowed_to_one_area(fixture: Fixture) -> None:
    elsewhere = area(fixture.tenant_id)
    fixture.areas.rows.append(elsewhere)
    await fixture.service.create(fixture.principal, declaration(fixture.area.id, title="Gym"))
    await fixture.service.create(fixture.principal, declaration(elsewhere.id, title="Anki"))

    found = await fixture.service.list_all(fixture.principal, area_id=elsewhere.id)

    assert [read.habit.title for read in found] == ["Anki"]


async def test_a_habit_with_no_recorded_outcome_reads_off_an_empty_log() -> None:
    """The reading `NoRecordedOutcomes` exists to state: nothing recorded, for any habit asked."""
    assert await NoRecordedOutcomes().read([uuid4()]) == ()


# --------------------------------------------------------------------------------
# Changing, and what a change does not touch
# --------------------------------------------------------------------------------


async def test_editing_a_habit_changes_future_occurrences_and_leaves_the_past_untouched() -> None:
    """A habit's edit writes one row. The outcome log is not read for writing and not written."""
    fixture = Fixture()
    read = await fixture.service.create(
        fixture.principal, declaration(fixture.area.id, miss_policy=MissPolicy.DEBT)
    )
    fixture.habits.rows = [replace(read.habit, charged_misses=3)]

    changed = await fixture.service.update(
        fixture.principal,
        read.habit.id,
        replace(nothing_stated(), cadence=DAILY, title="Gym, mornings"),
    )

    assert changed.habit.cadence_kind is CadenceKind.DAILY
    assert changed.habit.title == "Gym, mornings"
    # The edit restates what the user authored, and the charge is not one of those values: the
    # walk that produced it belongs to the outcome write alone.
    assert changed.habit.charged_misses == 3
    # The cap moved because the cadence did, and the same three misses are still counted.
    assert (changed.debt.misses, changed.debt.cap, changed.debt.outstanding) == (3, 2, 2)


async def test_a_patch_that_states_nothing_changes_nothing_and_still_bumps(
    fixture: Fixture,
) -> None:
    """Every mutation bumps, and a no-op PATCH is still a mutation the solver must re-read."""
    read = await fixture.service.create(fixture.principal, declaration(fixture.area.id))
    fixture.versions.bumped.clear()

    unchanged = await fixture.service.update(fixture.principal, read.habit.id, nothing_stated())

    assert unchanged.habit == read.habit
    assert fixture.versions.bumped == [WeekRange(first=WEEK_31, last=None)]


async def test_a_patch_naming_only_a_source_is_refused_when_the_stored_variants_contradict_it() -> (
    None
):
    """The case a request schema cannot catch, because it cannot see the row it is patching."""
    fixture = Fixture()
    read = await fixture.service.create(
        fixture.principal,
        declaration(fixture.area.id, binding_source=BindingSource.ROTATION, variants=GYM_SPLIT),
    )

    with pytest.raises(ValidationFailed, match="carries no variants"):
        await fixture.service.update(
            fixture.principal,
            read.habit.id,
            replace(nothing_stated(), binding_source=BindingSource.FIXED),
        )

    assert fixture.habits.rows[0].binding_source is BindingSource.ROTATION


async def test_switching_a_rotation_off_states_the_source_and_the_empty_list_together() -> None:
    fixture = Fixture()
    read = await fixture.service.create(
        fixture.principal,
        declaration(fixture.area.id, binding_source=BindingSource.ROTATION, variants=GYM_SPLIT),
    )

    changed = await fixture.service.update(
        fixture.principal,
        read.habit.id,
        replace(nothing_stated(), binding_source=BindingSource.FIXED, variants=()),
    )

    assert changed.habit.binding_source is BindingSource.FIXED
    assert changed.habit.variants == ()
    assert changed.cursor is None


async def test_a_patch_may_raise_a_ceiling_without_restating_the_floor(fixture: Fixture) -> None:
    """The two bounds are patched independently, which is why they are two fields not one."""
    read = await fixture.service.create(
        fixture.principal, declaration(fixture.area.id, min_duration_minutes=30)
    )

    changed = await fixture.service.update(
        fixture.principal, read.habit.id, replace(nothing_stated(), max_duration_minutes=90)
    )

    assert (changed.habit.duration_min_minutes, changed.habit.duration_max_minutes) == (30, 90)


async def test_a_patch_whose_merged_duration_runs_backwards_is_refused(fixture: Fixture) -> None:
    read = await fixture.service.create(
        fixture.principal,
        declaration(fixture.area.id, min_duration_minutes=30, max_duration_minutes=90),
    )

    with pytest.raises(ValidationFailed, match="runs backwards"):
        await fixture.service.update(
            fixture.principal, read.habit.id, replace(nothing_stated(), min_duration_minutes=120)
        )

    assert fixture.habits.rows[0].duration_min_minutes == 30


async def test_no_service_method_can_write_a_cursor_or_a_debt_figure(fixture: Fixture) -> None:
    """Asserted against the repository's own surface, inherited members included.

    "No API path sets the cursor" holds because there is nothing below the service that could store
    one: no column, no repository method, no request field. That shape is what carries the property.
    This is a name-based heuristic on top of it, so a writer called `store_derived_figures` would
    pass, and it earns its place by failing the obvious addition rather than by being airtight.
    """
    surface = {name for name in dir(HabitRepository) if not name.startswith("_")}

    assert not {name for name in surface if "cursor" in name or "debt" in name}


# --------------------------------------------------------------------------------
# Removing
# --------------------------------------------------------------------------------


async def test_removing_a_habit_deletes_the_row_and_bumps(fixture: Fixture) -> None:
    read = await fixture.service.create(fixture.principal, declaration(fixture.area.id))
    fixture.versions.bumped.clear()

    await fixture.service.remove(fixture.principal, read.habit.id)

    assert fixture.habits.rows == []
    assert fixture.versions.bumped == [WeekRange(first=WEEK_31, last=None)]


async def test_removing_a_habit_that_does_not_exist_is_a_404(fixture: Fixture) -> None:
    with pytest.raises(NotFound):
        await fixture.service.remove(fixture.principal, uuid4())


# --------------------------------------------------------------------------------
# Tenancy, authorization, and the bump
# --------------------------------------------------------------------------------


async def test_another_tenant_s_identifier_reads_as_absent_rather_than_forbidden(
    fixture: Fixture,
) -> None:
    read = await fixture.service.create(fixture.principal, declaration(fixture.area.id))
    someone_else = Principal(tenant_id=uuid4(), user_id=uuid4(), scopes=ALL_SCOPES)
    # The scoped SELECT is what produces the 404 in production; the fake has no scope, so this
    # asserts the defense-in-depth check that sits behind it.
    with pytest.raises(NotFound):
        await fixture.service.read(someone_else, read.habit.id)


@pytest.mark.parametrize(
    "scope", [Scope.PLAN_READ, Scope.PLAN_WRITE], ids=lambda scope: scope.value
)
async def test_a_credential_without_admin_cannot_declare_a_habit(
    fixture: Fixture, scope: Scope
) -> None:
    narrow = Principal(tenant_id=fixture.tenant_id, user_id=uuid4(), scopes=frozenset({scope}))

    with pytest.raises(Forbidden):
        await fixture.service.create(narrow, declaration(fixture.area.id))

    assert fixture.habits.rows == []


async def test_a_credential_without_plan_read_cannot_list_habits(fixture: Fixture) -> None:
    narrow = Principal(
        tenant_id=fixture.tenant_id, user_id=uuid4(), scopes=frozenset({Scope.ADMIN})
    )

    with pytest.raises(Forbidden):
        await fixture.service.list_all(narrow)


async def test_reading_a_habit_bumps_nothing(fixture: Fixture) -> None:
    read = await fixture.service.create(fixture.principal, declaration(fixture.area.id))
    fixture.versions.bumped.clear()

    await fixture.service.read(fixture.principal, read.habit.id)
    await fixture.service.list_all(fixture.principal)

    assert fixture.versions.bumped == []


async def test_the_bump_floors_at_the_week_holding_today_s_local_date() -> None:
    """A past week's approved revision is immutable, so the range starts at the current week."""
    fixture = Fixture()

    await fixture.service.create(fixture.principal, declaration(fixture.area.id))

    assert fixture.versions.bumped == [WeekRange(first=WEEK_31, last=None)]
    assert fixture.versions.bumped[0].covers(WEEK_31.following())
    assert not fixture.versions.bumped[0].covers(IsoWeek.parse("2026-W30"))


async def test_the_bump_reads_the_home_zone_so_a_date_boundary_resolves_where_the_user_is() -> None:
    """At 13:00 UTC on Sunday 2026-08-02 it is still Sunday in London and Monday in Auckland.

    So the two zones disagree about which week a change first affects, and the figure the bump
    floors at has to come from the HOME zone rather than from UTC. A bump resolved in UTC would
    give both tenants week 31 and leave the Auckland user's current week uninvalidated.
    """
    across_a_boundary = datetime(2026, 8, 2, 13, 0, tzinfo=UTC)
    in_london = Fixture(home_zone=LONDON, at=across_a_boundary)
    in_auckland = Fixture(home_zone="Pacific/Auckland", at=across_a_boundary)

    await in_london.service.create(in_london.principal, declaration(in_london.area.id))
    await in_auckland.service.create(in_auckland.principal, declaration(in_auckland.area.id))

    assert in_london.versions.bumped[0].first == WEEK_31
    assert in_auckland.versions.bumped[0].first == IsoWeek.parse("2026-W32")
