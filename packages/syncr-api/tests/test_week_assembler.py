"""The week assembler's resolutions, each in isolation, against fakes and a stamped instant.

The clock is an argument rather than a dependency, so every test here states the instant its week
is assembled against and none of them waits for a Monday. The domain is real throughout: the zone
resolution, the interval algebra, the two habit derivations, and every value type are the shipped
ones.

The tests worth reading are the ones about what the assembler does NOT do. It writes nothing, so a
tradeoff being evaluated leaves no trace. It reads no clock, so two assemblies of unchanged data
are equal. It emits both occurrences of a routine that overlaps itself, because the alternative
loses a date key an outcome may already reference. And it materializes nothing inside a span the
user declared off, which is the one rule off-plan periods place on this component.

The quantity pairs, the preference chain, the multipliers, and the concession fold are in
``test_week_assembler_quantities.py``: this file is about resolving stored state, that one is about
the figures two consumers read differently.
"""

from __future__ import annotations

import ast
import inspect
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Final
from uuid import uuid4

import pytest

from syncr_api.plans import assembler as assembler_module
from syncr_api.plans.assembler import (
    REPOSITORY_READ_COUNT,
    RESOLUTION_COUNT,
    UNVERSIONED_WEEK,
    AssemblyCaller,
    WeekAssembler,
)
from syncr_api.plans.cadence import occurrences_in_a_week
from syncr_domain.fixtures.dst_weeks import DST_WEEKS, FALL_BACK, LONDON, SPRING_FORWARD
from syncr_domain.habits import (
    BindingSource,
    Daily,
    EveryApproxDays,
    MissPolicy,
    TimesPerWeek,
)
from syncr_domain.identity import date_occurrence_key, index_occurrence_key
from syncr_domain.intervals import Interval, IntervalError
from syncr_domain.outcomes import HabitOutcome, OutcomeState
from syncr_domain.templates import BindingTarget, TemplateEntryKind
from syncr_domain.weeks import IsoWeek
from tests.assembly_fakes import (
    MONDAY,
    NOW,
    WEEK,
    FakeAreas,
    FakeHabits,
    FakeOffPlan,
    FakeOutcomes,
    FakeOverrides,
    FakeRevisions,
    FakeRoutines,
    FakeSettings,
    FakeTemplates,
    FakeVersions,
    FakeWeekPattern,
    a_concrete_entry,
    a_habit,
    a_routine,
    a_slot_entry,
    a_template,
    a_travel_override,
    an_approved_revision,
    an_area,
    an_assembler,
    an_off_plan_period,
    at,
    between,
    every_day,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from prometheus_client.samples import Sample

    from syncr_domain.fixtures.dst_weeks import DstWeek
    from syncr_domain.habits import Cadence

BERLIN = "Europe/Berlin"
APIA = "Pacific/Apia"

MINUTES_PER_HOUR = 60

# A histogram's bucket samples carry their upper bound as a label. It is the client library's own
# and not one this application declares, so the label rule below is stated over what is left when
# it is removed.
BUCKET_BOUND_LABEL = "le"

# How many times one assembly reads each collaborator, for the ones that are not read exactly
# once. The concession table is read per week: the week being assembled has its own approved
# concessions, and so does the week whose boundary-crossing occurrences this one inherits, which
# have to be folded in or the two weeks disagree about how long one night was.
READS_PER_ASSEMBLY: Final[Mapping[str, int]] = {"_adjustments": 2}
ONE_READ: Final = 1


# --------------------------------------------------------------------------------
# `now`, and what makes an assembly reproducible
# --------------------------------------------------------------------------------


async def test_now_is_the_argument_rather_than_a_clock_read() -> None:
    past = datetime(2026, 2, 9, 7, 30, tzinfo=UTC)

    inputs = await an_assembler().assemble(WEEK, past)

    assert inputs.now == past


async def test_two_assemblies_of_unchanged_data_against_one_instant_are_equal() -> None:
    # The property every reproduction of a failure rests on: the same week, the same instant, and
    # the same stored state have to give the same snapshot, so nothing may be ordered by a
    # dictionary's iteration or stamped from a clock.
    area = an_area()
    assembler = an_assembler(
        areas=FakeAreas([area]),
        routines=FakeRoutines([a_routine()]),
        habits=FakeHabits([a_habit(area_id=area.id)]),
    )

    first = await assembler.assemble(WEEK, NOW)
    second = await assembler.assemble(WEEK, NOW)

    assert first == second


async def test_an_instant_carrying_no_zone_is_refused_rather_than_compared() -> None:
    # A naive `now` would compare against an aware interval and raise two layers down, or worse
    # compare successfully against a wall clock.
    with pytest.raises(IntervalError):
        await an_assembler().assemble(WEEK, datetime(2026, 2, 11, 9, 0))  # noqa: DTZ001


async def test_the_seed_is_derived_from_the_week_and_the_input_version() -> None:
    assembler = an_assembler(versions=FakeVersions(7))

    inputs = await assembler.assemble(WEEK, NOW)
    following = await assembler.assemble(WEEK.following(), NOW)

    assert inputs.seed == (await assembler.assemble(WEEK, NOW)).seed
    assert inputs.seed != following.seed


async def test_a_week_nothing_has_referenced_reports_no_version_rather_than_the_first() -> None:
    # A missing row is a MISMATCH to the conditional write, so reporting version 1 here would let
    # two concurrent first solves both believe they held current inputs.
    inputs = await an_assembler(versions=FakeVersions(None)).assemble(WEEK, NOW)

    assert inputs.input_version == UNVERSIONED_WEEK


async def test_the_churn_baseline_names_the_approved_revision_or_states_there_is_none() -> None:
    approved_at = datetime(2026, 2, 8, 20, 0, tzinfo=UTC)

    never = await an_assembler(revisions=FakeRevisions()).assemble(WEEK, NOW)
    after = await an_assembler(
        revisions=FakeRevisions(an_approved_revision(approved_at=approved_at))
    ).assemble(WEEK, NOW)

    assert never.churn_baseline.reason == "never-approved"
    assert never.churn_baseline.revision_id is None
    assert after.churn_baseline.reason == "approved-revision"
    assert after.churn_baseline.approved_at == approved_at


# --------------------------------------------------------------------------------
# The span and the zones
# --------------------------------------------------------------------------------


@pytest.mark.parametrize("week", DST_WEEKS, ids=lambda week: week.label)
async def test_the_span_is_the_weeks_real_length_across_a_transition(week: DstWeek) -> None:
    inputs = await an_assembler(settings=FakeSettings(week.zone)).assemble(week.iso_week, NOW)

    assert inputs.span == week.span
    assert inputs.span.total_minutes() == week.span_minutes


async def test_the_two_transition_weeks_differ_by_two_hours_with_no_special_case() -> None:
    spring = await an_assembler(settings=FakeSettings(LONDON)).assemble(
        SPRING_FORWARD.iso_week, NOW
    )
    autumn = await an_assembler(settings=FakeSettings(LONDON)).assemble(FALL_BACK.iso_week, NOW)

    assert spring.span.total_minutes() == 167 * MINUTES_PER_HOUR
    assert autumn.span.total_minutes() == 169 * MINUTES_PER_HOUR


async def test_each_day_resolves_its_own_zone_across_a_travel_boundary() -> None:
    # Thursday to Sunday in Berlin: the span's two Mondays are London's and the days inside are
    # not one zone, which is why a week carries a mapping rather than a zone.
    override = a_travel_override(
        start_date=date(2026, 2, 12), end_date=date(2026, 2, 15), zone=BERLIN
    )

    inputs = await an_assembler(
        settings=FakeSettings(LONDON), overrides=FakeOverrides([override])
    ).assemble(WEEK, NOW)

    assert set(inputs.zone_by_date) == set(WEEK.dates())
    assert inputs.zone_by_date[date(2026, 2, 11)] == LONDON
    assert inputs.zone_by_date[date(2026, 2, 12)] == BERLIN


async def test_a_travel_override_over_the_following_monday_shortens_the_span() -> None:
    # The span's end is the FOLLOWING Monday's local midnight, so an override covering it moves
    # the end of this week by the offset difference.
    override = a_travel_override(
        start_date=date(2026, 2, 16), end_date=date(2026, 2, 20), zone=BERLIN
    )
    home = await an_assembler(settings=FakeSettings(LONDON)).assemble(WEEK, NOW)

    travelling = await an_assembler(
        settings=FakeSettings(LONDON), overrides=FakeOverrides([override])
    ).assemble(WEEK, NOW)

    assert home.span.total_minutes() - travelling.span.total_minutes() == MINUTES_PER_HOUR


# --------------------------------------------------------------------------------
# The frame
# --------------------------------------------------------------------------------


async def test_a_routine_materializes_one_occurrence_per_day_keyed_by_its_local_date() -> None:
    routine = a_routine(title="Sleep", target_time=time(23, 0))

    inputs = await an_assembler(routines=FakeRoutines([routine])).assemble(WEEK, NOW)

    assert len(inputs.frame) == 7
    assert [entry.occurrence_key for entry in inputs.frame] == [
        date_occurrence_key(on) for on in WEEK.dates()
    ]
    assert {entry.routine_id for entry in inputs.frame} == {routine.id}


async def test_a_frame_occurrence_carries_its_effective_duration_and_its_floor() -> None:
    # The clamp is a domain validation on the assembler rather than a solver constraint, so the
    # floor travels with the occurrence it was applied against.
    routine = a_routine(duration_minutes=480, min_duration_minutes=360)

    inputs = await an_assembler(routines=FakeRoutines([routine])).assemble(WEEK, NOW)

    assert {entry.interval.total_minutes() for entry in inputs.frame} == {480}
    assert {entry.min_duration_minutes for entry in inputs.frame} == {360}


async def test_a_duration_is_elapsed_minutes_so_a_transition_moves_the_end_not_the_length() -> None:
    routine = a_routine(
        target_time=SPRING_FORWARD.frame_target_time,
        duration_minutes=SPRING_FORWARD.frame_duration_minutes,
    )

    inputs = await an_assembler(
        settings=FakeSettings(LONDON), routines=FakeRoutines([routine])
    ).assemble(SPRING_FORWARD.iso_week, NOW)

    sunday = next(
        entry
        for entry in inputs.frame
        if entry.occurrence_key == date_occurrence_key(SPRING_FORWARD.transition_date)
    )
    assert sunday.interval == SPRING_FORWARD.sunday_night_frame
    assert sunday.interval.total_minutes() == SPRING_FORWARD.frame_duration_minutes


async def test_the_last_nights_frame_occurrence_belongs_to_this_week_unclipped() -> None:
    routine = a_routine(target_time=time(23, 0), duration_minutes=8 * MINUTES_PER_HOUR)

    inputs = await an_assembler(routines=FakeRoutines([routine])).assemble(WEEK, NOW)

    sunday = inputs.frame[-1]
    assert sunday.interval.start < inputs.span.end < sunday.interval.end
    assert sunday.interval.total_minutes() == 8 * MINUTES_PER_HOUR


async def test_a_routine_longer_than_its_local_day_emits_both_overlapping_occurrences() -> None:
    # No positive duration cap expresses "an occurrence never reaches its own next one": a
    # spring-forward local day is 23 hours, so 1381 minutes already overlaps. Two frame blocks
    # overlapping is a state the grid draws, and each date keys its own block, so dropping either
    # would lose a key an outcome may already reference.
    routine = a_routine(target_time=time(23, 0), duration_minutes=1381)

    inputs = await an_assembler(
        settings=FakeSettings(LONDON), routines=FakeRoutines([routine])
    ).assemble(SPRING_FORWARD.iso_week, NOW)

    saturday, sunday = inputs.frame[-2], inputs.frame[-1]
    assert saturday.interval.overlaps(sunday.interval)
    assert saturday.occurrence_key != sunday.occurrence_key
    assert len(inputs.frame) == 7


async def test_a_date_a_zone_skips_gives_two_occurrences_one_interval_and_two_keys() -> None:
    # `Pacific/Apia` skipped 2011-12-30 entirely, so that date's occurrence carries onto the 31st
    # and lands exactly on the 31st's. Both are emitted: deduplicating by instant would drop a
    # date key, and the two blocks have distinct identities because a frame block is date-keyed.
    routine = a_routine(title="Wake", target_time=time(5, 0), duration_minutes=30)
    skipped_week = IsoWeek.containing(date(2011, 12, 30))

    inputs = await an_assembler(
        settings=FakeSettings(APIA), routines=FakeRoutines([routine])
    ).assemble(skipped_week, datetime(2011, 12, 28, tzinfo=UTC))

    by_key = {entry.occurrence_key: entry for entry in inputs.frame}
    assert by_key["2011-12-30"].interval == by_key["2011-12-31"].interval
    assert len({entry.occurrence_key for entry in inputs.frame}) == 7


# --------------------------------------------------------------------------------
# Template entries
# --------------------------------------------------------------------------------


async def test_template_entries_materialize_per_date_from_the_week_pattern() -> None:
    area = an_area()
    day_type = uuid4()
    template = a_template(
        day_type_id=day_type,
        entries=[a_slot_entry(template_id=uuid4(), area_id=area.id, target_time=time(18, 0))],
    )

    inputs = await an_assembler(
        areas=FakeAreas([area]),
        week_pattern=FakeWeekPattern(every_day(day_type)),
        templates=FakeTemplates([template]),
    ).assemble(WEEK, NOW)

    assert len(inputs.template_entries) == 7
    assert [entry.occurrence_key for entry in inputs.template_entries] == [
        date_occurrence_key(on) for on in WEEK.dates()
    ]
    assert inputs.template_entries[0].interval == between(18, 19)


async def test_a_slot_names_its_area_and_a_concrete_entry_names_its_content() -> None:
    area = an_area()
    habit = a_habit(area_id=area.id)
    day_type = uuid4()
    template = a_template(
        day_type_id=day_type,
        entries=[
            a_slot_entry(template_id=uuid4(), area_id=area.id),
            a_concrete_entry(
                template_id=uuid4(), target=BindingTarget.HABIT, entity_id=habit.id, area_id=area.id
            ),
        ],
    )

    inputs = await an_assembler(
        areas=FakeAreas([area]),
        habits=FakeHabits([habit]),
        week_pattern=FakeWeekPattern(every_day(day_type)),
        templates=FakeTemplates([template]),
    ).assemble(WEEK, NOW)

    slot = next(e for e in inputs.template_entries if e.kind is TemplateEntryKind.SLOT)
    concrete = next(e for e in inputs.template_entries if e.kind is TemplateEntryKind.CONCRETE)
    assert slot.area_id == area.id
    assert slot.binding is None
    assert slot.title is None
    assert concrete.binding is not None
    assert (concrete.binding.target, concrete.binding.entity_id) == (BindingTarget.HABIT, habit.id)


async def test_a_concrete_entry_carries_its_content_name_and_the_area_it_charges() -> None:
    # A block carries the resolved content name and an Area, and an entry declares neither, so the
    # producer resolves both from the row the binding names. The Area is the CONTENT's rather than
    # the entry's declaration, because the minutes are that habit's work.
    declared = an_area()
    charged = an_area()
    habit = a_habit(area_id=charged.id, title="Shower")
    day_type = uuid4()
    template = a_template(
        day_type_id=day_type,
        entries=[
            a_concrete_entry(
                template_id=uuid4(),
                target=BindingTarget.HABIT,
                entity_id=habit.id,
                area_id=declared.id,
            )
        ],
    )

    inputs = await an_assembler(
        areas=FakeAreas([declared, charged]),
        habits=FakeHabits([habit]),
        week_pattern=FakeWeekPattern(every_day(day_type)),
        templates=FakeTemplates([template]),
    ).assemble(WEEK, NOW)

    assert {(entry.title, entry.area_id) for entry in inputs.template_entries} == {
        ("Shower", charged.id)
    }


async def test_a_concrete_entry_naming_a_routine_charges_the_area_it_declares() -> None:
    # A routine carries no Area, because the frame defines how much time exists rather than
    # competing for it. So an entry naming one has to declare the Area its block is charged to.
    area = an_area()
    routine = a_routine(title="Wake", target_time=time(5, 0), duration_minutes=30)
    day_type = uuid4()
    template = a_template(
        day_type_id=day_type,
        entries=[
            a_concrete_entry(
                template_id=uuid4(),
                target=BindingTarget.ROUTINE,
                entity_id=routine.id,
                area_id=area.id,
            )
        ],
    )

    inputs = await an_assembler(
        areas=FakeAreas([area]),
        routines=FakeRoutines([routine]),
        week_pattern=FakeWeekPattern(every_day(day_type)),
        templates=FakeTemplates([template]),
    ).assemble(WEEK, NOW)

    assert {(entry.title, entry.area_id) for entry in inputs.template_entries} == {
        ("Wake", area.id)
    }


async def test_a_concrete_entry_naming_a_routine_and_declaring_no_area_is_dropped() -> None:
    # Neither side can name an Area, and every block but the frame and an anchor carries one, so
    # the entry cannot become a block at all. Dropped rather than refused: the rest of the day
    # shape is assemblable, and refusing would fail every solve of the week over one row.
    area = an_area()
    routine = a_routine()
    day_type = uuid4()
    template = a_template(
        day_type_id=day_type,
        entries=[
            a_concrete_entry(
                template_id=uuid4(), target=BindingTarget.ROUTINE, entity_id=routine.id
            ),
            a_slot_entry(template_id=uuid4(), area_id=area.id),
        ],
    )

    inputs = await an_assembler(
        areas=FakeAreas([area]),
        routines=FakeRoutines([routine]),
        week_pattern=FakeWeekPattern(every_day(day_type)),
        templates=FakeTemplates([template]),
    ).assemble(WEEK, NOW)

    assert {entry.kind for entry in inputs.template_entries} == {TemplateEntryKind.SLOT}
    assert len(inputs.template_entries) == len(WEEK.dates())


async def test_a_concrete_entry_naming_content_this_tenant_does_not_have_is_dropped() -> None:
    # The entry boundary does not resolve a binding yet, so a concrete entry can name any
    # identifier. It reaches the assembler as content that cannot be found, and the week still
    # assembles.
    area = an_area()
    day_type = uuid4()
    template = a_template(
        day_type_id=day_type,
        entries=[
            a_concrete_entry(
                template_id=uuid4(), target=BindingTarget.HABIT, entity_id=uuid4(), area_id=area.id
            )
        ],
    )

    inputs = await an_assembler(
        areas=FakeAreas([area]),
        week_pattern=FakeWeekPattern(every_day(day_type)),
        templates=FakeTemplates([template]),
    ).assemble(WEEK, NOW)

    assert inputs.template_entries == ()


async def test_a_binding_does_not_resolve_against_the_table_its_target_does_not_name() -> None:
    # The whole reason the target column exists: the two tables have no shared parent, so an
    # identifier alone does not say which to read, and two rows sharing one would otherwise
    # resolve to whichever was looked in first.
    area = an_area()
    routine = a_routine()
    day_type = uuid4()
    template = a_template(
        day_type_id=day_type,
        entries=[
            a_concrete_entry(
                template_id=uuid4(),
                target=BindingTarget.HABIT,
                entity_id=routine.id,
                area_id=area.id,
            )
        ],
    )

    inputs = await an_assembler(
        areas=FakeAreas([area]),
        routines=FakeRoutines([routine]),
        week_pattern=FakeWeekPattern(every_day(day_type)),
        templates=FakeTemplates([template]),
    ).assemble(WEEK, NOW)

    assert inputs.template_entries == ()


async def test_a_routine_suppressed_every_night_still_names_the_entry_that_binds_it() -> None:
    # Why the name is resolved from the ROW rather than joined out of the assembled snapshot. An
    # off-plan period suppresses the frame occurrence and not an entry outside it, so the frame is
    # empty while the entry that names that routine is not. A join against the frame would leave
    # the block with no name at all.
    area = an_area()
    routine = a_routine(title="Sleep", target_time=time(23, 0))
    day_type = uuid4()
    template = a_template(
        day_type_id=day_type,
        entries=[
            a_concrete_entry(
                template_id=uuid4(),
                target=BindingTarget.ROUTINE,
                entity_id=routine.id,
                area_id=area.id,
                target_time=time(9, 0),
            )
        ],
    )
    nights = [
        an_off_plan_period(interval=between(22, 32, day=day)) for day in range(len(WEEK.dates()))
    ]

    inputs = await an_assembler(
        areas=FakeAreas([area]),
        routines=FakeRoutines([routine]),
        off_plan=FakeOffPlan(nights),
        week_pattern=FakeWeekPattern(every_day(day_type)),
        templates=FakeTemplates([template]),
    ).assemble(WEEK, NOW)

    assert inputs.frame == ()
    assert {entry.title for entry in inputs.template_entries} == {"Sleep"}


async def test_a_tenant_with_no_week_pattern_materializes_no_entries() -> None:
    # The first-run state rather than an error: a pattern maps all seven weekdays or it is not a
    # pattern, so there is no partial mapping to interpret.
    template = a_template(day_type_id=uuid4(), entries=[])

    inputs = await an_assembler(
        week_pattern=FakeWeekPattern(None), templates=FakeTemplates([template])
    ).assemble(WEEK, NOW)

    assert inputs.template_entries == ()


async def test_a_day_type_with_no_declared_shape_materializes_nothing_for_its_dates() -> None:
    inputs = await an_assembler(
        week_pattern=FakeWeekPattern(every_day(uuid4())), templates=FakeTemplates([])
    ).assemble(WEEK, NOW)

    assert inputs.template_entries == ()


# --------------------------------------------------------------------------------
# Habit cadence, the cursor, and debt
# --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cadence", "expected"),
    [
        (TimesPerWeek(4), 4),
        (TimesPerWeek(1), 1),
        (Daily(), 7),
        (EveryApproxDays(2), 4),
        (EveryApproxDays(3), 3),
        (EveryApproxDays(7), 1),
        (EveryApproxDays(30), 1),
    ],
)
def test_how_many_occurrences_a_cadence_puts_in_one_week(cadence: Cadence, expected: int) -> None:
    # An interval longer than a week rounds UP to one, which over-schedules a monthly habit to
    # fifty-two a year: deciding it is not due needs a reading of when it last occurred, and no
    # reader supplies one. Over-scheduling is visible to the user and under-scheduling is not.
    assert occurrences_in_a_week(cadence) == expected


async def test_occurrences_are_keyed_by_zero_padded_index_in_expansion_order() -> None:
    area = an_area()
    habit = a_habit(area_id=area.id, times_per_week=4)

    inputs = await an_assembler(areas=FakeAreas([area]), habits=FakeHabits([habit])).assemble(
        WEEK, NOW
    )

    assert [entry.binding.occurrence_key for entry in inputs.habit_occurrences] == [
        index_occurrence_key(index) for index in range(4)
    ]
    assert {entry.binding.entity_id for entry in inputs.habit_occurrences} == {habit.id}


async def test_a_rotation_advances_across_the_week_from_where_the_log_leaves_it() -> None:
    area = an_area()
    variants = ("Shoulder & Arms", "Legs", "Chest & Back", "Cardio")
    habit = a_habit(
        area_id=area.id,
        times_per_week=4,
        binding_source=BindingSource.ROTATION,
        variants=variants,
    )
    log = [
        HabitOutcome(
            habit_id=habit.id,
            occurrence_key=index_occurrence_key(0),
            state=OutcomeState.COMPLETED,
            occurred_at=at(9, day=0),
            confirmed_at=at(21, day=0),
        )
    ]

    inputs = await an_assembler(
        areas=FakeAreas([area]),
        habits=FakeHabits([habit]),
        outcomes=FakeOutcomes(log),
    ).assemble(WEEK, NOW)

    assert [entry.variant for entry in inputs.habit_occurrences] == [
        "Legs",
        "Chest & Back",
        "Cardio",
        "Shoulder & Arms",
    ]


async def test_outstanding_debt_adds_made_up_occurrences_after_the_fresh_ones() -> None:
    area = an_area()
    habit = a_habit(
        area_id=area.id,
        times_per_week=2,
        miss_policy=MissPolicy.DEBT,
        debt_cap_periods=2,
    )
    log = [
        HabitOutcome(
            habit_id=habit.id,
            occurrence_key=index_occurrence_key(index),
            state=OutcomeState.SKIPPED,
            occurred_at=at(9, day=index),
            confirmed_at=at(21, day=index),
        )
        for index in range(3)
    ]

    inputs = await an_assembler(
        areas=FakeAreas([area]), habits=FakeHabits([habit]), outcomes=FakeOutcomes(log)
    ).assemble(WEEK, NOW)

    assert [entry.is_debt for entry in inputs.habit_occurrences] == [False, False, True, True, True]
    assert [entry.binding.occurrence_key for entry in inputs.habit_occurrences] == [
        index_occurrence_key(index) for index in range(5)
    ]


async def test_debt_is_capped_so_a_month_of_misses_does_not_fill_a_week() -> None:
    area = an_area()
    habit = a_habit(
        area_id=area.id, times_per_week=2, miss_policy=MissPolicy.DEBT, debt_cap_periods=1
    )
    log = [
        HabitOutcome(
            habit_id=habit.id,
            occurrence_key=index_occurrence_key(index),
            state=OutcomeState.SKIPPED,
            occurred_at=at(9, day=index % 7),
            confirmed_at=at(21, day=index % 7),
        )
        for index in range(6)
    ]

    inputs = await an_assembler(
        areas=FakeAreas([area]), habits=FakeHabits([habit]), outcomes=FakeOutcomes(log)
    ).assemble(WEEK, NOW)

    # The cap is one cadence period, which for a twice-weekly habit is two occurrences.
    assert sum(1 for entry in inputs.habit_occurrences if entry.is_debt) == 2


async def test_a_miss_that_has_not_come_due_yet_charges_nothing() -> None:
    # `now` is what clips the debt derivation: a session still ahead of the user has not been
    # missed, so charging it would owe them work they have not had the chance to do.
    area = an_area()
    habit = a_habit(area_id=area.id, times_per_week=1, miss_policy=MissPolicy.DEBT)
    log = [
        HabitOutcome(
            habit_id=habit.id,
            occurrence_key=index_occurrence_key(0),
            state=OutcomeState.SKIPPED,
            occurred_at=at(9, day=6),
            confirmed_at=at(21, day=6),
        )
    ]

    inputs = await an_assembler(
        areas=FakeAreas([area]), habits=FakeHabits([habit]), outcomes=FakeOutcomes(log)
    ).assemble(WEEK, NOW)

    assert [entry.is_debt for entry in inputs.habit_occurrences] == [False]


async def test_the_outcome_log_is_asked_for_exactly_the_habits_the_week_holds() -> None:
    area = an_area()
    habits = [a_habit(area_id=area.id, title="Gym"), a_habit(area_id=area.id, title="Anki")]
    log = FakeOutcomes()

    await an_assembler(areas=FakeAreas([area]), habits=FakeHabits(habits), outcomes=log).assemble(
        WEEK, NOW
    )

    assert sorted(log.asked_for) == sorted(habit.id for habit in habits)


# --------------------------------------------------------------------------------
# Off-plan periods
# --------------------------------------------------------------------------------


async def test_off_plan_periods_are_clipped_to_the_span() -> None:
    # A Friday-to-next-Tuesday declaration is one row that two weeks read. The snapshot names no
    # instant outside the week it describes, so a reader cannot derive a figure from a span the
    # week does not hold.
    period = an_off_plan_period(interval=Interval(at(14, day=4), at(9, day=8)))

    inputs = await an_assembler(off_plan=FakeOffPlan([period])).assemble(WEEK, NOW)

    assert len(inputs.off_plan) == 1
    assert inputs.off_plan[0].interval == Interval(at(14, day=4), inputs.span.end)


async def test_a_period_outside_the_week_reaches_the_snapshot_at_all() -> None:
    inside = an_off_plan_period(interval=between(9, 17, day=2))
    outside = an_off_plan_period(interval=Interval(at(9, day=10), at(17, day=10)))

    inputs = await an_assembler(off_plan=FakeOffPlan([inside, outside])).assemble(WEEK, NOW)

    assert [period.interval for period in inputs.off_plan] == [inside.interval]


async def test_a_period_suppresses_the_frame_unless_it_keeps_it() -> None:
    routine = a_routine(title="Lunch", target_time=time(12, 0), duration_minutes=45)
    wednesday_off = between(9, 17, day=2)

    dropped = await an_assembler(
        routines=FakeRoutines([routine]),
        off_plan=FakeOffPlan([an_off_plan_period(interval=wednesday_off, keep_frame=False)]),
    ).assemble(WEEK, NOW)
    kept = await an_assembler(
        routines=FakeRoutines([routine]),
        off_plan=FakeOffPlan([an_off_plan_period(interval=wednesday_off, keep_frame=True)]),
    ).assemble(WEEK, NOW)

    assert len(dropped.frame) == 6
    assert len(kept.frame) == 7


async def test_a_period_suppresses_a_template_entry_whichever_way_it_keeps_the_frame() -> None:
    # A template entry is content, and content does not materialize inside a declared span
    # whatever the frame does: `keep_frame` is about routines and about nothing else.
    area = an_area()
    day_type = uuid4()
    template = a_template(
        day_type_id=day_type,
        entries=[a_slot_entry(template_id=uuid4(), area_id=area.id, target_time=time(12, 0))],
    )
    period = an_off_plan_period(interval=between(9, 17, day=2), keep_frame=True)

    inputs = await an_assembler(
        areas=FakeAreas([area]),
        week_pattern=FakeWeekPattern(every_day(day_type)),
        templates=FakeTemplates([template]),
        off_plan=FakeOffPlan([period]),
    ).assemble(WEEK, NOW)

    assert len(inputs.template_entries) == 6
    assert date_occurrence_key(MONDAY + timedelta(days=2)) not in {
        entry.occurrence_key for entry in inputs.template_entries
    }


async def test_an_occurrence_overlapping_the_edge_of_a_period_is_suppressed_whole() -> None:
    # Suppression is by OVERLAP rather than by where the occurrence starts, so nothing sits inside
    # a span the user declared off. Clipping it instead would report a duration the routine does
    # not have and change the span an outcome is keyed against.
    routine = a_routine(title="Lunch", target_time=time(12, 0), duration_minutes=60)
    starts_before_the_period = an_off_plan_period(interval=between(12.5, 17, day=2))

    inputs = await an_assembler(
        routines=FakeRoutines([routine]),
        off_plan=FakeOffPlan([starts_before_the_period]),
    ).assemble(WEEK, NOW)

    assert len(inputs.frame) == 6


async def test_a_period_abutting_an_occurrence_suppresses_nothing() -> None:
    # Half-open bounds: a period beginning where an occurrence ends covers no common instant.
    routine = a_routine(title="Lunch", target_time=time(12, 0), duration_minutes=60)
    period = an_off_plan_period(interval=between(13, 17, day=2))

    inputs = await an_assembler(
        routines=FakeRoutines([routine]), off_plan=FakeOffPlan([period])
    ).assemble(WEEK, NOW)

    assert len(inputs.frame) == 7


# --------------------------------------------------------------------------------
# The stated resolution count, and the metric
# --------------------------------------------------------------------------------


def test_the_pipeline_states_one_resolution_count_and_lists_that_many_bullets() -> None:
    # The figure is load-bearing: a latency budget and an alert are calibrated to it, and the way
    # it rots is a resolution being added to the method without the docstring being counted again.
    bullets = _pipeline_bullets(assembler_module.__doc__ or "")

    assert len(bullets) == RESOLUTION_COUNT, bullets


def test_the_bullet_count_reads_the_pipeline_rather_than_every_line_of_the_docstring() -> None:
    # The control for the reading above. Without it, a walk that counted the wrong lines would
    # keep passing after someone shortened the pipeline to match it.
    listing = """
    pipeline
      ├── one
      │     ├── not a resolution of its own
      └── two
    """

    assert _pipeline_bullets(listing) == ["one", "two"]


def test_every_repository_the_assembler_holds_is_read_once_per_assembly() -> None:
    # The read count is the other half of the budget's basis, and a collaborator the constructor
    # takes and the method never asks is a dependency nothing needs. Counted PER COLLABORATOR
    # against a declared inventory rather than as a total, because the figure a latency budget
    # rests on is reads rather than collaborators, and a second read of any of them has to be
    # declared below rather than absorbed into a total that still adds up.
    held = _constructor_collaborators(WeekAssembler)
    reads = Counter(_awaited_collaborators(WeekAssembler))

    assert held == set(reads), {
        "held but never read": sorted(held - set(reads)),
        "read but not held": sorted(set(reads) - held),
    }
    assert reads == Counter({name: READS_PER_ASSEMBLY.get(name, ONE_READ) for name in held}), {
        "read a different number of times than declared": sorted(
            name for name in held if reads[name] != READS_PER_ASSEMBLY.get(name, ONE_READ)
        )
    }
    assert sum(reads.values()) == REPOSITORY_READ_COUNT


def test_the_assembly_histogram_carries_the_caller_and_no_other_label() -> None:
    # Labelled by caller because the alert is scoped to the interactive one: hundreds of
    # background assemblies a day must neither mask it nor trigger it. Asserted through the
    # samples a scraper reads rather than through the collector's own attributes.
    for caller in AssemblyCaller:
        assembler_module.ASSEMBLY_DURATION.labels(caller=caller.value).observe(0.0)

    labels = {
        tuple(sorted(set(sample.labels) - {BUCKET_BOUND_LABEL}))
        for sample in _assembly_samples()
        if sample.labels
    }
    values = {sample.labels["caller"] for sample in _assembly_samples() if sample.labels}

    assert labels == {("caller",)}
    assert values == {caller.value for caller in AssemblyCaller}


async def test_an_assembly_observes_its_duration_under_its_own_callers_label() -> None:
    before = _observations(AssemblyCaller.MAINTAINER)

    await an_assembler(caller=AssemblyCaller.MAINTAINER).assemble(WEEK, NOW)

    assert _observations(AssemblyCaller.MAINTAINER) == before + 1


def _assembly_samples() -> list[Sample]:
    return [
        sample
        for metric in assembler_module.ASSEMBLY_DURATION.collect()
        for sample in metric.samples
    ]


def _observations(caller: AssemblyCaller) -> float:
    """How many assemblies this caller's histogram has recorded, read from its own samples."""
    return next(
        (
            sample.value
            for sample in _assembly_samples()
            if sample.name.endswith("_count") and sample.labels.get("caller") == caller.value
        ),
        0.0,
    )


def _pipeline_bullets(text: str) -> list[str]:
    """The top-level steps of the pipeline listing, which are the resolutions it performs.

    A nested bullet is part of the step above it rather than a step of its own, so only the
    outermost prefix counts. Read from the docstring because that is the one place the pipeline is
    written down, which is what makes the count and the listing impossible to disagree.
    """
    bullets: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        prefix = next((mark for mark in ("├── ", "└── ") if stripped.startswith(mark)), None)
        if prefix is None or "│" in line[: line.index(prefix[0])]:
            continue
        bullets.append(stripped.removeprefix(prefix).strip())
    return bullets


def _constructor_collaborators(service: type) -> set[str]:
    """Every keyword the constructor takes that is stored as a collaborator."""
    parameters = inspect.signature(service).parameters
    return {f"_{name}" for name in parameters if name != "caller"}


def _awaited_collaborators(service: type) -> list[str]:
    """Every ``self._x`` a method of ``service`` awaits, read from the source, one entry per await.

    A list rather than a set, so a repository read twice is visible: the count is what a latency
    budget is calibrated against, and two reads of one collaborator cost two round trips.
    """
    tree = ast.parse(inspect.getsource(service))
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Await):
            continue
        call = node.value
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
            continue
        owner = call.func.value
        if isinstance(owner, ast.Attribute) and isinstance(owner.value, ast.Name):
            found.append(owner.attr)
    return found
