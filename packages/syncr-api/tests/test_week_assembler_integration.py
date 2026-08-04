"""One whole assembly against a real Postgres: sixteen reads, and the figures they produce.

Sixteen repositories interacting is not a unit concern. The tier-2 suite drives each resolution
against fakes, which is where a rule is asserted; what only a real server can show is that the
sixteen reads compose into one snapshot at all, and that each one finds the rows it is scoped to.

Four things are decidable only here, and each is a place a defect would hide.

**Every read is tenant-scoped.** A second tenant's routines, tasks, habits, Areas, preferences,
off-plan periods, and concessions are stored alongside the first's, and the assembly must see
none of them. A scoping fault in any one of sixteen statements is invisible to a fake.

**The stored shapes round-trip into the resolutions.** A record is built from columns and the
resolution reads the record: a wall time stored as ``time``, a JSONB window list, a cadence's
three columns, and a decimal floor each survive the trip or the figure is wrong.

**The week pattern's seven rows compose into a pattern.** It is stored as one row per weekday and
read back as a value that refuses a partial mapping, so a missing row fails the read rather than
materializing five days out of seven.

**The assembly writes nothing.** A read that bumped a version or created a row would invalidate
the running solve it was asked on behalf of. The version and the row counts are compared before
and after.

**The widened anchor read finds a commitment the week does not contain.** The span an assembly
reads is derived from the anchor types a tenant stored, and the anchors it returns come back
through a real keyset-ordered statement, so this is where the derived span and the SQL predicate
meet. A commitment in the following week casting prep into this one is the case a page boundary or
a wrong direction would silently lose.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from syncr_api.anchors.repository import AnchorRepository
from syncr_api.anchors.type_repository import AnchorTypeRepository
from syncr_api.areas.repository import AreaRepository
from syncr_api.calendars.config import ANCHOR_SOURCE, ICS
from syncr_api.calendars.repository import CalendarSourceRepository
from syncr_api.core.db import create_db_engine, create_sessionmaker
from syncr_api.habits.repository import HabitRepository
from syncr_api.learned.repository import WeightSetRepository
from syncr_api.offplan.models import OffPlanPeriodRow
from syncr_api.offplan.repository import OffPlanPeriodRepository
from syncr_api.plans.adjustments import WeekAdjustmentRepository
from syncr_api.plans.assembler import UNVERSIONED_WEEK, AssemblyCaller
from syncr_api.plans.injection import build_week_assembler
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.preferences.repository import PreferenceRepository
from syncr_api.routines.repository import RoutineRepository
from syncr_api.tasks.repository import TaskRepository
from syncr_api.templates.declarations import ConcreteEntry, SlotEntry
from syncr_api.templates.repository import (
    DayTypeRepository,
    TemplateRepository,
    WeekPatternRepository,
)
from syncr_api.user_settings.repository import SettingsRepository
from syncr_domain.habits import (
    BindingSource,
    Duration,
    Habit,
    MissPolicy,
    TimesPerWeek,
)
from syncr_domain.identity import date_occurrence_key, index_occurrence_key
from syncr_domain.intervals import Interval
from syncr_domain.preferences import (
    LocalTimeWindow,
    Preference,
    PreferenceOwner,
    PreferenceOwnerKind,
    PreferenceStrength,
)
from syncr_domain.tasks import Priority
from syncr_domain.templates import BindingTarget, EntrySpan, WeekPattern
from syncr_domain.weeks import IsoWeek, Weekday
from tests.anchor_specifications import EXAM, with_areas
from tests.live_tenants import delete_tenant, seed_owner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.anchors.records import AnchorTypeSpecification
    from syncr_domain.identifiers import (
        AreaId,
        HabitId,
        RoutineId,
        TaskId,
        TemplateEntryId,
        TenantId,
    )
    from syncr_solver.inputs import SolveInputs

pytestmark = pytest.mark.integration

LONDON = "Europe/London"
BERLIN = "Europe/Berlin"

WEEK = IsoWeek(2026, 7)
MONDAY = WEEK.monday()
WEDNESDAY = MONDAY + timedelta(days=2)
# Wednesday mid-morning, so half the week is past: the immovable half of a netting rule is
# reachable and the debt clip has something to clip.
NOW = datetime(2026, 2, 11, 9, 0, tzinfo=UTC)
FRIDAY_09 = datetime(2026, 2, 13, 9, 0, tzinfo=UTC)

MINUTES_PER_HOUR = 60


@pytest.fixture
async def engine(live_database_url: str) -> AsyncIterator[AsyncEngine]:
    live = create_db_engine(live_database_url)
    yield live
    await live.dispose()


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_sessionmaker(engine)


@pytest.fixture
async def owner(sessions: async_sessionmaker[AsyncSession]) -> AsyncIterator[UserRecord]:
    account = await seed_owner(sessions)
    yield account
    await delete_tenant(sessions, account.tenant_id)


@pytest.fixture
async def other_owner(sessions: async_sessionmaker[AsyncSession]) -> AsyncIterator[UserRecord]:
    account = await seed_owner(sessions)
    yield account
    await delete_tenant(sessions, account.tenant_id)


@dataclass(frozen=True, slots=True)
class DeclaredWeek:
    """The identifiers one declared week's rows took, so an assertion names the row it is about."""

    fitness: AreaId
    career: AreaId
    sleep: RoutineId
    gym: HabitId
    task: TaskId
    slot: TemplateEntryId
    shower: TemplateEntryId


async def declare_a_week(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, *, home_zone: str = LONDON
) -> DeclaredWeek:
    """One tenant's whole declared week: every table the assembly reads, populated once.

    Written through the real repositories, so a column a record cannot round-trip fails here rather
    than in a figure two layers away.
    """
    async with sessions() as session, session.begin():
        settings = SettingsRepository(session, tenant_id)
        locked = await settings.lock(created_at=NOW)
        await settings.write(
            visible_hours=locked.visible_hours,
            day_start=locked.day_start,
            day_end=locked.day_end,
            review_cadence=locked.review_cadence,
            home_zone=home_zone,
        )
        areas = AreaRepository(session, tenant_id)
        fitness = await areas.create(
            parent_id=None,
            name="Fitness",
            pigment_index=1,
            budget_percent=Decimal(20),
            floor_hours=Decimal(5),
            created_at=NOW,
        )
        career = await areas.create(
            parent_id=None,
            name="Career",
            pigment_index=2,
            budget_percent=Decimal(30),
            floor_hours=Decimal(3),
            created_at=NOW,
        )

        sleep = await RoutineRepository(session, tenant_id).create(
            title="Sleep",
            target_time=time(23, 0),
            duration_minutes=8 * MINUTES_PER_HOUR,
            min_duration_minutes=6 * MINUTES_PER_HOUR,
            flex_band_minutes=30,
            created_at=NOW,
        )

        gym = Habit(
            id=uuid4(),
            cadence=TimesPerWeek(4),
            duration=Duration.elastic(min_minutes=30, max_minutes=90),
            miss_policy=MissPolicy.DEBT,
            binding_source=BindingSource.ROTATION,
            variants=("Shoulder & Arms", "Legs", "Chest & Back", "Cardio"),
        )
        await HabitRepository(session, tenant_id).create(
            area_id=fitness.id, title="Gym", habit=gym, created_at=NOW
        )

        past_papers = await TaskRepository(session, tenant_id).create(
            area_id=career.id,
            project_id=None,
            title="F&F Past Papers",
            estimate_minutes=4 * MINUTES_PER_HOUR,
            deadline=FRIDAY_09,
            priority=Priority.HIGH,
            min_chunk_minutes=30,
            splittable=True,
            created_at=NOW,
        )

        day_type = await DayTypeRepository(session, tenant_id).create(
            name="Weekday", created_at=NOW
        )
        templates = TemplateRepository(session, tenant_id)
        weekday = await templates.create(day_type_id=day_type.id, name="Weekday", created_at=NOW)
        slot_span = EntrySpan(target_time=time(18, 0), duration_minutes=60, flex_band_minutes=15)
        slot = await templates.create_entry(
            template_id=weekday.id,
            span=slot_span,
            content=SlotEntry(span=slot_span, area_id=career.id).content(),
        )
        shower_span = EntrySpan(target_time=time(6, 45), duration_minutes=15, flex_band_minutes=0)
        shower = await templates.create_entry(
            template_id=weekday.id,
            span=shower_span,
            content=ConcreteEntry(
                span=shower_span,
                binding_target=BindingTarget.HABIT,
                binding_ref=gym.id,
                area_id=fitness.id,
            ).content(),
        )
        await WeekPatternRepository(session, tenant_id).replace(
            WeekPattern(dict.fromkeys(Weekday, day_type.id))
        )

        await PreferenceRepository(session, tenant_id).create(
            Preference(
                owner=PreferenceOwner(kind=PreferenceOwnerKind.AREA, id=fitness.id),
                windows=(LocalTimeWindow(start=time(5, 30), end=time(7, 0)),),
                strength=PreferenceStrength.STRONG,
                preferred_duration_minutes=60,
                max_per_day_minutes=90,
            ),
            created_at=NOW,
        )

        await OffPlanPeriodRepository(session, tenant_id).create(
            interval=Interval(
                datetime(2026, 2, 13, 14, 0, tzinfo=UTC), datetime(2026, 2, 17, 9, 0, tzinfo=UTC)
            ),
            keep_frame=False,
            label="Away",
            created_at=NOW,
        )

        await WeightSetRepository(session, tenant_id).seed_hand_tuned(at=NOW)
        await WeekInputVersionRepository(session, tenant_id).bump(WEEK, at=NOW)

    return DeclaredWeek(
        fitness=fitness.id,
        career=career.id,
        sleep=sleep.id,
        gym=gym.id,
        task=past_papers.id,
        slot=slot.id,
        shower=shower.id,
    )


async def declare_a_commitment(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    *,
    prep_area_id: AreaId,
    transit_area_id: AreaId,
    start: datetime,
    minutes: int = 120,
    title: str = "Analysis Exam",
) -> None:
    """One stored calendar source, one stored anchor type, and one commitment carrying it.

    Written through the real repositories for the same reason the week is: the type's geometry
    passes the table's own check constraints, and the anchor comes back through the statement the
    assembly really issues.
    """
    async with sessions() as session, session.begin():
        source = await CalendarSourceRepository(session, tenant_id).create(
            provider=ICS,
            role=ANCHOR_SOURCE,
            display_name="University timetable",
            external_id=f"https://example.ac.uk/{tenant_id}.ics",
            included=True,
            horizon_days=None,
            created_at=NOW,
        )
        anchor_type = await AnchorTypeRepository(session, tenant_id).create(
            rule_order=0,
            specification=_an_exam_declaration(prep_area_id, transit_area_id),
            created_at=NOW,
        )
        await AnchorRepository(session, tenant_id).create(
            source_id=source.id,
            external_uid=f"{title}@example.ac.uk",
            series_uid=None,
            title=title,
            interval=Interval(start, start + timedelta(minutes=minutes)),
            location="Exam Hall",
            anchor_type_id=anchor_type.id,
            type_overridden=False,
        )


def _an_exam_declaration(prep_area_id: AreaId, transit_area_id: AreaId) -> AnchorTypeSpecification:
    """The settled ``Exam`` row, with this tenant's own Areas on the blocks it casts.

    Its fourteen-hour prep lead is what puts prep the evening before a morning exam, which is the
    whole reason the anchor read is widened past the week's own end. Both Areas are named, so this
    declaration casts three blocks and one window and a test can tell the rule apart from itself.
    """
    return with_areas(EXAM, prep=prep_area_id, transit=transit_area_id, forbidden=[prep_area_id])


async def assemble(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    *,
    week: IsoWeek = WEEK,
    caller: AssemblyCaller = AssemblyCaller.REQUEST,
) -> SolveInputs:
    """One assembly, wired exactly as a request path wires it."""
    async with sessions() as session:
        return await build_week_assembler(session, tenant_id, caller=caller).assemble(week, NOW)


async def test_a_whole_declared_week_assembles_into_one_snapshot(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    declared = await declare_a_week(sessions, owner.tenant_id)

    inputs = await assemble(sessions, owner.tenant_id)

    assert inputs.iso_week == WEEK
    assert inputs.now == NOW
    assert inputs.input_version == 1
    assert set(inputs.zone_by_date) == set(WEEK.dates())
    # Friday 14:00 onwards is declared off, so Friday's, Saturday's and Sunday's Sleep and the
    # entries on those dates do not materialize.
    assert [entry.occurrence_key for entry in inputs.frame] == [
        date_occurrence_key(on) for on in WEEK.dates()[:4]
    ]
    assert {entry.routine_id for entry in inputs.frame} == {declared.sleep}
    assert [occurrence.binding.occurrence_key for occurrence in inputs.habit_occurrences] == [
        index_occurrence_key(index) for index in range(4)
    ]
    assert [task.binding.entity_id for task in inputs.eligible_tasks] == [declared.task]
    assert {budget.area_id for budget in inputs.areas} == {declared.fitness, declared.career}
    assert len(inputs.off_plan) == 1


async def test_the_stored_declarations_round_trip_into_the_resolutions(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    declared = await declare_a_week(sessions, owner.tenant_id)

    inputs = await assemble(sessions, owner.tenant_id)

    monday_sleep = inputs.frame[0]
    assert monday_sleep.interval == Interval(
        datetime(2026, 2, 9, 23, 0, tzinfo=UTC), datetime(2026, 2, 10, 7, 0, tzinfo=UTC)
    )
    assert monday_sleep.min_duration_minutes == 6 * MINUTES_PER_HOUR
    # A rotation habit's cursor sits at its first variant while nothing is confirmed, and the
    # elastic range is the stored one because no multiplier has been fitted.
    assert inputs.habit_occurrences[0].variant == "Shoulder & Arms"
    assert inputs.habit_occurrences[0].duration == Duration.elastic(min_minutes=30, max_minutes=90)
    # A window declared as wall time becomes one interval per date, in that date's zone.
    fitness_preference = next(
        entry for entry in inputs.preferences if entry.owner.id == declared.fitness
    )
    assert len(fitness_preference.windows) == 7
    assert fitness_preference.windows[0] == Interval(
        datetime(2026, 2, 9, 5, 30, tzinfo=UTC), datetime(2026, 2, 9, 7, 0, tzinfo=UTC)
    )
    assert fitness_preference.strength is PreferenceStrength.STRONG
    # The cap is the Area's, read from an Area preference and carried on the budget.
    by_area = {budget.area_id: budget for budget in inputs.areas}
    assert by_area[declared.fitness].max_per_day_minutes == 90
    assert by_area[declared.career].max_per_day_minutes is None
    assert by_area[declared.fitness].floor_minutes == 5 * MINUTES_PER_HOUR
    assert by_area[declared.career].floor_minutes == 3 * MINUTES_PER_HOUR


async def test_the_week_pattern_and_the_day_shapes_materialize_per_date(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    declared = await declare_a_week(sessions, owner.tenant_id)

    inputs = await assemble(sessions, owner.tenant_id)

    # Two entries a day on the four dates before the off-plan span, plus Friday's 06:45 entry,
    # which ends at 07:00 and so does not reach the 14:00 the span starts at. Friday's 18:00 slot
    # and both entries of Saturday and Sunday are inside it and do not materialize.
    assert len(inputs.template_entries) == 9
    friday = date_occurrence_key(MONDAY + timedelta(days=4))
    assert [
        entry.entry_id for entry in inputs.template_entries if entry.occurrence_key == friday
    ] == [declared.shower]
    slot = next(entry for entry in inputs.template_entries if entry.entry_id == declared.slot)
    concrete = next(entry for entry in inputs.template_entries if entry.entry_id == declared.shower)
    assert slot.area_id == declared.career
    assert slot.binding is None
    assert concrete.binding is not None
    assert concrete.binding.entity_id == declared.gym
    assert concrete.binding.target is BindingTarget.HABIT


async def test_a_deadline_bearing_task_reaches_the_probes_demand(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    declared = await declare_a_week(sessions, owner.tenant_id)

    inputs = await assemble(sessions, owner.tenant_id)

    # Nothing is placed in this deployment, so both quantities read the whole estimate. What this
    # asserts is that the demand is COMPUTED and reaches the snapshot, keyed by the deadline and
    # the Area the row declared.
    assert [demand.remaining_minutes for demand in inputs.deadline_demands] == [
        4 * MINUTES_PER_HOUR
    ]
    assert inputs.deadline_demands[0].deadline == FRIDAY_09
    assert inputs.deadline_demands[0].area_id == declared.career
    assert inputs.deadline_demands[0].labels == ("F&F Past Papers",)


async def test_an_approved_concession_is_folded_into_the_figures_it_modifies(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    declared = await declare_a_week(sessions, owner.tenant_id)
    async with sessions() as session, session.begin():
        await WeekAdjustmentRepository(session, owner.tenant_id).upsert(
            iso_week=WEEK,
            kind="breach_floor",
            target_id=declared.fitness,
            reductions={},
            delta_minutes=80,
            created_at=NOW,
            created_by_operation_id=uuid4(),
        )

    inputs = await assemble(sessions, owner.tenant_id)

    fitness = next(budget for budget in inputs.areas if budget.area_id == declared.fitness)
    assert fitness.floor_minutes == 5 * MINUTES_PER_HOUR - 80
    assert fitness.floor_reservation_minutes == 5 * MINUTES_PER_HOUR - 80
    assert [entry.kind.value for entry in inputs.adjustments] == ["breach_floor"]


async def test_an_assembly_sees_only_the_tenant_it_was_scoped_to(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, other_owner: UserRecord
) -> None:
    # Sixteen statements, each of which has to carry the tenant predicate. A scoping fault in any
    # one of them is invisible to a fake repository.
    await declare_a_week(sessions, owner.tenant_id)
    await declare_a_week(sessions, other_owner.tenant_id, home_zone=BERLIN)

    theirs = await assemble(sessions, other_owner.tenant_id)
    mine = await assemble(sessions, owner.tenant_id)

    assert len(mine.frame) == len(theirs.frame)
    assert {entry.routine_id for entry in mine.frame} != {
        entry.routine_id for entry in theirs.frame
    }
    assert {budget.area_id for budget in mine.areas} & {
        budget.area_id for budget in theirs.areas
    } == set()
    assert {task.binding.entity_id for task in mine.eligible_tasks} != {
        task.binding.entity_id for task in theirs.eligible_tasks
    }
    # A Berlin week is an hour ahead of a London one, so the two spans are not the same instants.
    assert mine.span != theirs.span


async def test_a_week_nothing_has_referenced_assembles_and_reports_no_version(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    await declare_a_week(sessions, owner.tenant_id)

    inputs = await assemble(sessions, owner.tenant_id, week=WEEK.following())

    assert inputs.input_version == UNVERSIONED_WEEK
    assert inputs.iso_week == WEEK.following()
    # The off-plan span runs to Tuesday 09:00, so Monday night's Sleep is inside it and does not
    # materialize, while Tuesday's starts at 23:00 and is clear of it. One declaration reaching
    # across a week boundary is read by both weeks, from one row.
    assert len(inputs.frame) == 6
    assert inputs.frame[0].occurrence_key == date_occurrence_key(
        WEEK.following().monday() + timedelta(days=1)
    )


async def test_an_assembly_writes_nothing_at_all(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # A read that bumped a version would invalidate the running solve it was asked on behalf of,
    # and a read that created a row would make the maintainer's background assemblies mutate the
    # week they were only measuring.
    await declare_a_week(sessions, owner.tenant_id)
    before = await _week_state(sessions, owner.tenant_id)

    await assemble(sessions, owner.tenant_id)
    await assemble(sessions, owner.tenant_id, week=WEEK.following())
    await assemble(sessions, owner.tenant_id, caller=AssemblyCaller.MAINTAINER)

    assert await _week_state(sessions, owner.tenant_id) == before


async def test_two_assemblies_of_one_stored_week_against_one_instant_are_equal(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    await declare_a_week(sessions, owner.tenant_id)

    first = await assemble(sessions, owner.tenant_id)
    second = await assemble(sessions, owner.tenant_id)

    assert first == second
    assert first.seed == second.seed


async def test_a_commitment_in_the_following_week_casts_its_prep_into_this_one(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # The widened read, against a real statement. The exam is at 09:30 on the Monday that STARTS
    # the declared week, and its fourteen-hour prep lead puts prep at 19:30 the evening before,
    # which is the last evening of the week before it. A read that stopped at that week's own end
    # would return no rows at all and the evening would silently read as free.
    declared = await declare_a_week(sessions, owner.tenant_id)
    exam_starts = datetime(2026, 2, 9, 9, 30, tzinfo=UTC)
    await declare_a_commitment(
        sessions,
        owner.tenant_id,
        prep_area_id=declared.career,
        transit_area_id=declared.fitness,
        start=exam_starts,
    )

    inputs = await assemble(sessions, owner.tenant_id, week=WEEK.preceding())

    assert [(block.interval, block.area_id) for block in inputs.shadow_blocks] == [
        (
            Interval(
                datetime(2026, 2, 8, 19, 30, tzinfo=UTC), datetime(2026, 2, 8, 20, 30, tzinfo=UTC)
            ),
            declared.career,
        )
    ]
    # The commitment itself is the following week's occupancy, so this week states what it cast
    # and not the commitment. Its outbound leg leaves at 08:45 on the Monday, which is that week's
    # too, and so is its recovery.
    assert inputs.anchors == ()
    assert inputs.forbidden_windows == ()


async def test_a_commitment_inside_the_week_is_hard_occupancy_and_casts_its_own_buffers(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    declared = await declare_a_week(sessions, owner.tenant_id)
    exam_starts = datetime(2026, 2, 11, 14, 0, tzinfo=UTC)
    await declare_a_commitment(
        sessions,
        owner.tenant_id,
        prep_area_id=declared.career,
        transit_area_id=declared.fitness,
        start=exam_starts,
    )

    inputs = await assemble(sessions, owner.tenant_id)

    assert [(anchor.interval, anchor.title) for anchor in inputs.anchors] == [
        (Interval(exam_starts, exam_starts + timedelta(minutes=120)), "Analysis Exam")
    ]
    # Prep at 00:00 from a fourteen-hour lead, the outbound leg 45 minutes before the exam, and
    # the journey home from its end. The recovery window runs from that same end, beside the
    # journey rather than after it.
    assert [block.interval.start for block in inputs.shadow_blocks] == [
        datetime(2026, 2, 11, 0, 0, tzinfo=UTC),
        datetime(2026, 2, 11, 13, 15, tzinfo=UTC),
        datetime(2026, 2, 11, 16, 0, tzinfo=UTC),
    ]
    assert [window.kind.value for window in inputs.forbidden_windows] == ["recovery"]
    assert inputs.forbidden_windows[0].interval == Interval(
        datetime(2026, 2, 11, 16, 0, tzinfo=UTC), datetime(2026, 2, 11, 17, 0, tzinfo=UTC)
    )
    assert inputs.forbidden_windows[0].forbidden_area_ids == (declared.career,)


async def test_an_assembly_reads_only_its_own_tenants_commitments(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, other_owner: UserRecord
) -> None:
    # Two more statements that have to carry the tenant predicate, and a fault in either is
    # invisible to a fake: another tenant's anchor types would widen this tenant's read, and
    # another tenant's commitments would occupy this tenant's week.
    mine = await declare_a_week(sessions, owner.tenant_id)
    theirs = await declare_a_week(sessions, other_owner.tenant_id)
    await declare_a_commitment(
        sessions,
        owner.tenant_id,
        prep_area_id=mine.career,
        transit_area_id=mine.fitness,
        start=datetime(2026, 2, 11, 14, 0, tzinfo=UTC),
        title="My Exam",
    )
    await declare_a_commitment(
        sessions,
        other_owner.tenant_id,
        prep_area_id=theirs.career,
        transit_area_id=theirs.fitness,
        start=datetime(2026, 2, 12, 14, 0, tzinfo=UTC),
        title="Their Exam",
    )

    inputs = await assemble(sessions, owner.tenant_id)

    assert [anchor.title for anchor in inputs.anchors] == ["My Exam"]
    assert {block.area_id for block in inputs.shadow_blocks} == {mine.career, mine.fitness}


async def test_the_night_this_week_inherits_is_what_the_week_before_resolved(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # Two stored weeks, one Sleep declaration, and the equality that makes them one answer. The
    # week before has no off-plan span, so its Sunday night is resolved, owned there whole, and
    # this week states the seven hours it runs into.
    await declare_a_week(sessions, owner.tenant_id)

    before = await assemble(sessions, owner.tenant_id, week=WEEK.preceding())
    inputs = await assemble(sessions, owner.tenant_id)

    crossing = [
        entry.interval.clipped_to(inputs.span)
        for entry in before.frame
        if entry.interval.overlaps(inputs.span)
    ]
    assert inputs.frame_overhang == tuple(crossing)
    assert inputs.frame_overhang[0] == Interval(
        inputs.span.start, datetime(2026, 2, 9, 7, 0, tzinfo=UTC)
    )
    # The occurrence itself belongs to the week its start falls in, at the routine's own duration,
    # and it is not a second occurrence of this week's frame.
    assert before.frame[-1].interval.total_minutes() == 8 * MINUTES_PER_HOUR
    assert date_occurrence_key(WEEK.preceding().dates()[-1]) not in {
        entry.occurrence_key for entry in inputs.frame
    }


async def test_a_night_its_own_week_suppressed_is_inherited_by_nobody(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # The stored off-plan span runs from Friday 14:00 to the following Tuesday 09:00, so this
    # week's own Sunday night never materializes. The week after therefore inherits nothing:
    # judged against ITS OWN periods instead, the same night would be occupied in one week and
    # suspended in the other.
    await declare_a_week(sessions, owner.tenant_id)

    owning = await assemble(sessions, owner.tenant_id)
    following = await assemble(sessions, owner.tenant_id, week=WEEK.following())

    assert len(owning.frame) == 4
    assert following.frame_overhang == ()


async def _week_state(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> tuple[int | None, int]:
    """The week's input version and how many off-plan rows this tenant has."""
    async with sessions() as session:
        version = await WeekInputVersionRepository(session, tenant_id).current(WEEK)
        periods = await session.scalar(
            select(func.count(OffPlanPeriodRow.id)).where(OffPlanPeriodRow.tenant_id == tenant_id)
        )
    return (version, periods or 0)
