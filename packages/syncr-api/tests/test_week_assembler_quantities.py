"""The figures two consumers read differently, and the concessions that modify them.

Four subjects, and each is a pair rather than a field: the solver's remaining work against the
probe's demand, the solver's floor minutes against the probe's floor reservation, an Area's
declaration against an override of it, and a stored concession against a candidate one.

Every test here is stated in hours and minutes with the arithmetic worked in the comment, because
the failures this suite exists to catch are quiet: a merged pair reports a shortfall on a healthy
week, or schedules a task at half its size, and in both directions the two sides agree so nothing
else notices.

What a preferred window does on a daylight-saving transition date is in
``test_preference_windows_across_dst.py``: one mechanism with five answers, which reads better
beside its own table than inside the chain resolution.
"""

from __future__ import annotations

import dataclasses
import io
import json
from dataclasses import replace
from datetime import time
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syncr_api.plans.config import ADJUSTMENT_KINDS
from syncr_common.logging import configure_logging
from syncr_domain.habits import BindingSource, Duration
from syncr_domain.identity import BindingRef, date_occurrence_key
from syncr_domain.outcomes import MISS_STATE, RecordedOutcome
from syncr_domain.plan import AdjustmentKind
from syncr_domain.preferences import PreferenceStrength
from syncr_domain.reasons import Bound, Floor, ReasonRecord
from syncr_solver import reasons
from syncr_solver.inputs import AreaBudget, ResolvedPreference, WeekAdjustment
from tests.assembly_fakes import (
    MONDAY,
    NOW,
    WEEK,
    FakeAdjustments,
    FakeAreas,
    FakeHabits,
    FakePlacements,
    FakePreferences,
    FakeRoutines,
    FakeSettings,
    FakeTasks,
    FakeWeights,
    a_habit,
    a_habit_block,
    a_habit_owner,
    a_pin,
    a_plan,
    a_preference,
    a_routine,
    a_task,
    a_task_block,
    a_weight_set,
    a_window,
    an_adjustment,
    an_area,
    an_area_owner,
    an_assembler,
    at,
    between,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from syncr_domain.plan import PlanDocument

MINUTES_PER_HOUR = 60
FOUR_HOURS = 4 * MINUTES_PER_HOUR


# --------------------------------------------------------------------------------
# The solver's remaining work
# --------------------------------------------------------------------------------


async def test_remaining_work_is_the_estimate_less_what_the_outcome_log_recorded() -> None:
    area = an_area()
    task = a_task(area_id=area.id, estimate_minutes=FOUR_HOURS, recorded_minutes=90)

    inputs = await an_assembler(areas=FakeAreas([area]), tasks=FakeTasks([task])).assemble(
        WEEK, NOW
    )

    assert [entry.remaining_minutes for entry in inputs.eligible_tasks] == [150]


async def test_a_past_block_is_netted_from_the_solvers_remaining_work() -> None:
    # Monday's hour cannot be re-placed, so the solver has three hours left of a four-hour task.
    area = an_area()
    task = a_task(area_id=area.id, estimate_minutes=FOUR_HOURS)
    plan = a_plan(
        blocks=[a_task_block(task_id=task.id, area_id=area.id, interval=between(9, 10, day=1))]
    )

    inputs = await an_assembler(
        areas=FakeAreas([area]),
        tasks=FakeTasks([task]),
        placements=FakePlacements(live_plan=plan),
    ).assemble(WEEK, NOW)

    assert [entry.remaining_minutes for entry in inputs.eligible_tasks] == [3 * MINUTES_PER_HOUR]


async def test_an_unpinned_future_block_is_not_netted_from_the_solvers_remaining_work() -> None:
    # THE defect this pair exists to prevent. The solver discards and re-places Thursday's block,
    # so netting it would place two hours of a four-hour task, report no shortfall because both
    # sides agree, and leave the state stable and permanently wrong.
    area = an_area()
    task = a_task(area_id=area.id, estimate_minutes=FOUR_HOURS)
    plan = a_plan(
        blocks=[a_task_block(task_id=task.id, area_id=area.id, interval=between(9, 11, day=3))]
    )

    inputs = await an_assembler(
        areas=FakeAreas([area]),
        tasks=FakeTasks([task]),
        placements=FakePlacements(live_plan=plan),
    ).assemble(WEEK, NOW)

    assert [entry.remaining_minutes for entry in inputs.eligible_tasks] == [FOUR_HOURS]


async def test_pinning_that_future_block_nets_it_because_the_solver_can_no_longer_move_it() -> None:
    area = an_area()
    task = a_task(area_id=area.id, estimate_minutes=FOUR_HOURS)
    interval = between(9, 11, day=3)
    plan = a_plan(blocks=[a_task_block(task_id=task.id, area_id=area.id, interval=interval)])

    inputs = await an_assembler(
        areas=FakeAreas([area]),
        tasks=FakeTasks([task]),
        placements=FakePlacements(
            live_plan=plan, pins=[a_pin(binding=BindingRef.for_task(task.id), interval=interval)]
        ),
    ).assemble(WEEK, NOW)

    assert [entry.remaining_minutes for entry in inputs.eligible_tasks] == [2 * MINUTES_PER_HOUR]


async def test_a_task_whose_work_is_wholly_immovable_is_not_offered_to_the_solver_again() -> None:
    area = an_area()
    task = a_task(area_id=area.id, estimate_minutes=MINUTES_PER_HOUR)
    plan = a_plan(
        blocks=[a_task_block(task_id=task.id, area_id=area.id, interval=between(9, 10, day=1))]
    )

    inputs = await an_assembler(
        areas=FakeAreas([area]),
        tasks=FakeTasks([task]),
        placements=FakePlacements(live_plan=plan),
    ).assemble(WEEK, NOW)

    assert inputs.eligible_tasks == ()


# --------------------------------------------------------------------------------
# The probe's demand, and where the two quantities part
# --------------------------------------------------------------------------------


async def test_the_probes_demand_nets_the_same_unpinned_block_the_solvers_figure_ignores() -> None:
    # One week, one task, two figures. The probe's free capacity has already subtracted Thursday's
    # two hours, so its demand must subtract them too or it reports a shortfall the week does not
    # have. The solver's must not, or the task is scheduled at half its size.
    area = an_area()
    task = a_task(area_id=area.id, estimate_minutes=FOUR_HOURS, deadline=at(9, day=4))
    plan = a_plan(
        blocks=[a_task_block(task_id=task.id, area_id=area.id, interval=between(9, 11, day=3))]
    )

    inputs = await an_assembler(
        areas=FakeAreas([area]),
        tasks=FakeTasks([task]),
        placements=FakePlacements(live_plan=plan),
    ).assemble(WEEK, NOW)

    assert [entry.remaining_minutes for entry in inputs.eligible_tasks] == [FOUR_HOURS]
    assert [demand.remaining_minutes for demand in inputs.deadline_demands] == [
        2 * MINUTES_PER_HOUR
    ]


async def test_a_placement_after_the_deadline_does_not_satisfy_it() -> None:
    # An hour placed on Saturday does not do work due on Friday.
    area = an_area()
    task = a_task(area_id=area.id, estimate_minutes=FOUR_HOURS, deadline=at(9, day=4))
    plan = a_plan(
        blocks=[a_task_block(task_id=task.id, area_id=area.id, interval=between(9, 11, day=5))]
    )

    inputs = await an_assembler(
        areas=FakeAreas([area]),
        tasks=FakeTasks([task]),
        placements=FakePlacements(live_plan=plan),
    ).assemble(WEEK, NOW)

    assert [demand.remaining_minutes for demand in inputs.deadline_demands] == [FOUR_HOURS]


async def test_a_recorded_past_block_is_counted_once_rather_than_twice() -> None:
    # The block ran Monday 09:00-10:00 and the confirmed outcome recorded 60 minutes. Counting both
    # would report the task as two hours further on than it is, which is the double count the
    # `max()` exists to remove.
    area = an_area()
    task = a_task(
        area_id=area.id,
        estimate_minutes=FOUR_HOURS,
        recorded_minutes=MINUTES_PER_HOUR,
        deadline=at(9, day=4),
    )
    plan = a_plan(
        blocks=[a_task_block(task_id=task.id, area_id=area.id, interval=between(9, 10, day=1))]
    )

    inputs = await an_assembler(
        areas=FakeAreas([area]),
        tasks=FakeTasks([task]),
        placements=FakePlacements(live_plan=plan),
    ).assemble(WEEK, NOW)

    assert [demand.remaining_minutes for demand in inputs.deadline_demands] == [
        3 * MINUTES_PER_HOUR
    ]


async def test_a_confirmed_outcome_longer_than_the_block_carries_the_truth() -> None:
    # The block was an hour and the user recorded ninety minutes, because it ran long. The greater
    # of the two is the honest figure, so two and a half hours are left rather than three.
    area = an_area()
    task = a_task(
        area_id=area.id, estimate_minutes=FOUR_HOURS, recorded_minutes=90, deadline=at(9, day=4)
    )
    plan = a_plan(
        blocks=[a_task_block(task_id=task.id, area_id=area.id, interval=between(9, 10, day=1))]
    )

    inputs = await an_assembler(
        areas=FakeAreas([area]),
        tasks=FakeTasks([task]),
        placements=FakePlacements(live_plan=plan),
    ).assemble(WEEK, NOW)

    assert [demand.remaining_minutes for demand in inputs.deadline_demands] == [150]


async def test_a_confirmed_skip_raises_the_demand_for_the_task_it_was_placed_for() -> None:
    # A confirmed skip, end to end through the assembly. The user's Monday hour was placed and then
    # marked skipped, so the four-hour task still owes four hours rather than three: the demand
    # RISES by the hour the user said they did not work, which is the truth and the opposite of
    # what the netting formula alone produced.
    area = an_area()
    task = a_task(area_id=area.id, estimate_minutes=FOUR_HOURS, deadline=at(9, day=4))
    plan = a_plan(
        blocks=[a_task_block(task_id=task.id, area_id=area.id, interval=between(9, 10, day=1))]
    )
    skipped = RecordedOutcome(binding=BindingRef.for_task(task.id), state=MISS_STATE)

    presumed_inputs = await an_assembler(
        areas=FakeAreas([area]),
        tasks=FakeTasks([task]),
        placements=FakePlacements(live_plan=plan),
    ).assemble(WEEK, NOW)
    skipped_inputs = await an_assembler(
        areas=FakeAreas([area]),
        tasks=FakeTasks([task]),
        placements=FakePlacements(live_plan=plan, outcomes=[skipped]),
    ).assemble(WEEK, NOW)

    assert [demand.remaining_minutes for demand in presumed_inputs.deadline_demands] == [
        3 * MINUTES_PER_HOUR
    ]
    assert [demand.remaining_minutes for demand in skipped_inputs.deadline_demands] == [FOUR_HOURS]


async def test_a_confirmed_skip_leaves_the_solvers_own_figure_where_it_was() -> None:
    # The asymmetry, pinned so it is not read as a rule. The solver's remaining work nets what it
    # cannot RE-PLACE, and a past hour stays unmovable whatever the user said happened in it. The
    # two readings genuinely disagree here and only the probe's is settled; whether the solver's
    # should read the log too is open.
    area = an_area()
    task = a_task(area_id=area.id, estimate_minutes=FOUR_HOURS, deadline=at(9, day=4))
    plan = a_plan(
        blocks=[a_task_block(task_id=task.id, area_id=area.id, interval=between(9, 10, day=1))]
    )
    skipped = RecordedOutcome(binding=BindingRef.for_task(task.id), state=MISS_STATE)

    inputs = await an_assembler(
        areas=FakeAreas([area]),
        tasks=FakeTasks([task]),
        placements=FakePlacements(live_plan=plan, outcomes=[skipped]),
    ).assemble(WEEK, NOW)

    assert [entry.remaining_minutes for entry in inputs.eligible_tasks] == [3 * MINUTES_PER_HOUR]


async def test_a_task_with_no_deadline_demands_nothing() -> None:
    area = an_area()
    task = a_task(area_id=area.id, estimate_minutes=FOUR_HOURS, deadline=None)

    inputs = await an_assembler(areas=FakeAreas([area]), tasks=FakeTasks([task])).assemble(
        WEEK, NOW
    )

    assert inputs.deadline_demands == ()
    assert len(inputs.eligible_tasks) == 1


async def test_two_tasks_sharing_a_deadline_in_one_area_are_one_demand_naming_both() -> None:
    # The probe compares a demand against the capacity that Area has before that instant, so two
    # demands would each be checked against the whole of it.
    area = an_area()
    friday = at(9, day=4)
    first = a_task(area_id=area.id, title="Anki", estimate_minutes=60, deadline=friday)
    second = a_task(area_id=area.id, title="Past Papers", estimate_minutes=120, deadline=friday)

    inputs = await an_assembler(areas=FakeAreas([area]), tasks=FakeTasks([first, second])).assemble(
        WEEK, NOW
    )

    assert len(inputs.deadline_demands) == 1
    demand = inputs.deadline_demands[0]
    assert demand.remaining_minutes == 180
    assert demand.labels == ("Anki", "Past Papers")
    assert demand.area_id == area.id


async def test_demands_of_two_areas_at_one_deadline_stay_separate() -> None:
    fitness, career = an_area(name="Fitness"), an_area(name="Career")
    friday = at(9, day=4)

    inputs = await an_assembler(
        areas=FakeAreas([fitness, career]),
        tasks=FakeTasks(
            [
                a_task(area_id=fitness.id, title="Programme", estimate_minutes=60, deadline=friday),
                a_task(
                    area_id=career.id, title="Applications", estimate_minutes=60, deadline=friday
                ),
            ]
        ),
    ).assemble(WEEK, NOW)

    assert {demand.area_id for demand in inputs.deadline_demands} == {fitness.id, career.id}


# --------------------------------------------------------------------------------
# The two floor quantities
# --------------------------------------------------------------------------------


async def test_floors_met_by_unpinned_blocks_reserve_nothing_and_still_bind_the_solver() -> None:
    # The healthy state of the product: a solved week's floors are met by solver-placed blocks, and
    # solver-placed blocks are unpinned. Merged into one quantity, the probe reports a six-hour
    # `floors_exceed_capacity` gap here, because its free capacity has already subtracted the very
    # blocks the reservation would then reserve against.
    fitness = an_area(name="Fitness", floor_hours=Decimal(5))
    career = an_area(name="Career", floor_hours=Decimal(3))
    plan = a_plan(
        blocks=[
            a_habit_block(habit_id=uuid4(), area_id=fitness.id, interval=between(9, 14, day=3)),
            a_habit_block(habit_id=uuid4(), area_id=career.id, interval=between(14, 17, day=3)),
        ]
    )

    inputs = await an_assembler(
        areas=FakeAreas([fitness, career]), placements=FakePlacements(live_plan=plan)
    ).assemble(WEEK, NOW)

    by_area = {budget.area_id: budget for budget in inputs.areas}
    assert by_area[fitness.id].floor_minutes == 5 * MINUTES_PER_HOUR
    assert by_area[career.id].floor_minutes == 3 * MINUTES_PER_HOUR
    assert by_area[fitness.id].floor_reservation_minutes == 0
    assert by_area[career.id].floor_reservation_minutes == 0


async def test_pinning_an_already_placed_block_cannot_improve_the_verdict() -> None:
    # The assertion that catches the defect. The probe's reservation already netted the block, so
    # pinning it changes nothing the probe reads and a pin cannot make a week look more feasible.
    #
    # The solver's quantity DOES fall, by exactly the pinned block's minutes, and that is correct
    # rather than asymmetric: the solver now has an hour less to place in order to honour a
    # five-hour floor, because the hour it is holding is one it may no longer move.
    fitness = an_area(name="Fitness", floor_hours=Decimal(5))
    interval = between(9, 10, day=3)
    block = a_habit_block(habit_id=uuid4(), area_id=fitness.id, interval=interval)
    plan = a_plan(blocks=[block])

    unpinned = await an_assembler(
        areas=FakeAreas([fitness]), placements=FakePlacements(live_plan=plan)
    ).assemble(WEEK, NOW)
    pinned = await an_assembler(
        areas=FakeAreas([fitness]),
        placements=FakePlacements(
            live_plan=plan, pins=[a_pin(binding=block.binding, interval=interval)]
        ),
    ).assemble(WEEK, NOW)

    assert unpinned.areas[0].floor_reservation_minutes == pinned.areas[0].floor_reservation_minutes
    assert unpinned.areas[0].floor_minutes == 5 * MINUTES_PER_HOUR
    assert pinned.areas[0].floor_minutes == 4 * MINUTES_PER_HOUR


async def test_a_past_block_lowers_both_floor_quantities_because_it_is_in_both_sets() -> None:
    fitness = an_area(name="Fitness", floor_hours=Decimal(5))
    plan = a_plan(
        blocks=[a_habit_block(habit_id=uuid4(), area_id=fitness.id, interval=between(9, 10, day=1))]
    )

    inputs = await an_assembler(
        areas=FakeAreas([fitness]), placements=FakePlacements(live_plan=plan)
    ).assemble(WEEK, NOW)

    assert inputs.areas[0].floor_minutes == 4 * MINUTES_PER_HOUR
    assert inputs.areas[0].floor_reservation_minutes == 4 * MINUTES_PER_HOUR


async def test_a_confirmed_skip_raises_the_floor_minutes_the_solver_must_still_place() -> None:
    # A confirmed skip, end to end through the assembly. Tuesday's Fitness hour was placed and then
    # marked skipped, so a five-hour floor still needs five hours placed rather than four: read over
    # the placement's own span, the floor reads as honoured by an hour the user said did not happen
    # and the solver never offers those minutes again.
    #
    # The probe's reservation and the Area's placed minutes do not move, which is what keeps a pin
    # from improving the verdict: both count committed time, and a skipped hour is still committed.
    fitness = an_area(name="Fitness", floor_hours=Decimal(5))
    block = a_habit_block(habit_id=uuid4(), area_id=fitness.id, interval=between(9, 10, day=1))
    plan = a_plan(blocks=[block])
    skipped = RecordedOutcome(binding=block.binding, state=MISS_STATE)

    presumed = await an_assembler(
        areas=FakeAreas([fitness]), placements=FakePlacements(live_plan=plan)
    ).assemble(WEEK, NOW)
    confirmed = await an_assembler(
        areas=FakeAreas([fitness]),
        placements=FakePlacements(live_plan=plan, outcomes=[skipped]),
    ).assemble(WEEK, NOW)

    assert presumed.areas[0].floor_minutes == 4 * MINUTES_PER_HOUR
    assert confirmed.areas[0].floor_minutes == 5 * MINUTES_PER_HOUR
    assert presumed.areas[0].floor_reservation_minutes == 4 * MINUTES_PER_HOUR
    assert confirmed.areas[0].floor_reservation_minutes == 4 * MINUTES_PER_HOUR
    assert presumed.areas[0].placed_minutes == confirmed.areas[0].placed_minutes == MINUTES_PER_HOUR


async def test_the_floor_clause_a_reader_sees_states_the_figure_the_skip_moved() -> None:
    # The clause the user reads, composed from the same budgets: `floor` renders `floor_minutes` as
    # the floor the rule worked to, and `placed of of` over the reservation's set. So the skip moves
    # the clause's own figure and leaves the pair around it alone, and a reader is not told a
    # five-hour floor is a four-hour one because they skipped an hour.
    fitness = an_area(name="Fitness", floor_hours=Decimal(5))
    chosen = replace(
        a_habit_block(habit_id=uuid4(), area_id=fitness.id, interval=between(9, 10, day=1)),
        reason=ReasonRecord((Bound(BindingSource.FIXED, "Gym · 4 / wk"),)),
    )
    plan = a_plan(blocks=[chosen])
    skipped = RecordedOutcome(binding=chosen.binding, state=MISS_STATE)

    presumed = await an_assembler(
        areas=FakeAreas([fitness]), placements=FakePlacements(live_plan=plan)
    ).assemble(WEEK, NOW)
    confirmed = await an_assembler(
        areas=FakeAreas([fitness]),
        placements=FakePlacements(live_plan=plan, outcomes=[skipped]),
    ).assemble(WEEK, NOW)

    assert _floor_clauses(plan, presumed.areas) == [
        Floor(area_id=fitness.id, floor_minutes=4 * MINUTES_PER_HOUR, placed=60, of=300)
    ]
    assert _floor_clauses(plan, confirmed.areas) == [
        Floor(area_id=fitness.id, floor_minutes=5 * MINUTES_PER_HOUR, placed=60, of=300)
    ]


def _floor_clauses(plan: PlanDocument, areas: Sequence[AreaBudget]) -> list[Floor]:
    """Every ``floor`` clause the plan's blocks carry once their records are assembled."""
    records = reasons.assemble(plan, blocked_log=(), breakdown=None, pins=(), areas=areas)
    return [clause for record in records for clause in record.clauses if isinstance(clause, Floor)]


async def test_an_over_satisfied_floor_reserves_nothing_rather_than_a_negative() -> None:
    fitness = an_area(name="Fitness", floor_hours=Decimal(1))
    plan = a_plan(
        blocks=[a_habit_block(habit_id=uuid4(), area_id=fitness.id, interval=between(9, 14, day=1))]
    )

    inputs = await an_assembler(
        areas=FakeAreas([fitness]), placements=FakePlacements(live_plan=plan)
    ).assemble(WEEK, NOW)

    assert inputs.areas[0].floor_minutes == 0
    assert inputs.areas[0].floor_reservation_minutes == 0


async def test_placed_minutes_counts_every_placement_in_the_area() -> None:
    # Named so the `floor` reason clause cannot disagree with whichever reservation a reader
    # compares it against: this figure and the probe's reservation count one set.
    fitness = an_area(name="Fitness", floor_hours=Decimal(5))
    plan = a_plan(
        blocks=[
            a_habit_block(habit_id=uuid4(), area_id=fitness.id, interval=between(9, 10, day=1)),
            a_habit_block(habit_id=uuid4(), area_id=fitness.id, interval=between(9, 10, day=3)),
        ]
    )

    inputs = await an_assembler(
        areas=FakeAreas([fitness]), placements=FakePlacements(live_plan=plan)
    ).assemble(WEEK, NOW)

    assert inputs.areas[0].placed_minutes == 2 * MINUTES_PER_HOUR
    assert inputs.areas[0].floor_reservation_minutes == 3 * MINUTES_PER_HOUR


async def test_a_target_is_gross_and_nets_no_placement_at_all() -> None:
    # A target is a reporting figure rather than a reservation, which is what lets
    # oversubscription measure the declared demand honestly.
    fitness = an_area(name="Fitness", floor_hours=Decimal(5), budget_percent=Decimal(10))
    plan = a_plan(
        blocks=[a_habit_block(habit_id=uuid4(), area_id=fitness.id, interval=between(9, 14, day=1))]
    )

    without = await an_assembler(areas=FakeAreas([fitness])).assemble(WEEK, NOW)
    with_placements = await an_assembler(
        areas=FakeAreas([fitness]), placements=FakePlacements(live_plan=plan)
    ).assemble(WEEK, NOW)

    assert without.areas[0].target_minutes == with_placements.areas[0].target_minutes
    assert without.areas[0].target_minutes > 5 * MINUTES_PER_HOUR


async def test_a_daily_cap_comes_from_an_area_preference_and_travels_on_the_budget() -> None:
    # An override cannot carry a cap, so there is no shape in which one could relax a hard
    # constraint: the cap is on the Area's budget and a resolved preference has no field for it.
    fitness = an_area(name="Fitness")
    habit = a_habit(area_id=fitness.id)

    inputs = await an_assembler(
        areas=FakeAreas([fitness]),
        habits=FakeHabits([habit]),
        preferences=FakePreferences(
            [
                a_preference(owner=an_area_owner(fitness.id), max_per_day_minutes=90),
                a_preference(
                    owner=a_habit_owner(habit.id), windows=[a_window(time(6, 0), time(8, 0))]
                ),
            ]
        ),
    ).assemble(WEEK, NOW)

    assert inputs.areas[0].max_per_day_minutes == 90
    assert "max_per_day_minutes" not in {
        field.name for field in dataclasses.fields(ResolvedPreference)
    }


def test_the_area_budget_carries_both_floor_quantities_and_nothing_has_merged_them() -> None:
    # Bounded by the inventory of what an Area budget may carry, so merging the pair fails here
    # rather than turning up as a shortfall on a healthy week.
    assert {field.name for field in dataclasses.fields(AreaBudget)} == {
        "area_id",
        "name",
        "floor_minutes",
        "floor_reservation_minutes",
        "target_minutes",
        "placed_minutes",
        "max_per_day_minutes",
    }


async def test_an_area_budget_carries_the_name_a_shortfall_renders() -> None:
    # The probe performs no lookup, so the words a refusal is written in have to arrive with the
    # figures. An identifier in a panel is not a refusal the user can act on.
    fitness = an_area(name="Fitness")

    inputs = await an_assembler(areas=FakeAreas([fitness])).assemble(WEEK, NOW)

    assert inputs.areas[0].name == "Fitness"
    assert inputs.for_probe().area_floor_reservations[0].label == "Fitness"


# --------------------------------------------------------------------------------
# The preference chain, and the windows
# --------------------------------------------------------------------------------


async def test_an_areas_preference_is_carried_by_its_habits_and_its_tasks() -> None:
    # The solver walks no chain: what it holds per content is already the answer.
    fitness = an_area(name="Fitness")
    habit = a_habit(area_id=fitness.id)
    task = a_task(area_id=fitness.id)
    window = a_window(time(5, 30), time(7, 0))

    inputs = await an_assembler(
        areas=FakeAreas([fitness]),
        habits=FakeHabits([habit]),
        tasks=FakeTasks([task]),
        preferences=FakePreferences(
            [a_preference(owner=an_area_owner(fitness.id), windows=[window])]
        ),
    ).assemble(WEEK, NOW)

    owners = {resolved.owner.id for resolved in inputs.preferences}
    assert owners == {fitness.id, habit.id, task.id}
    assert {len(resolved.windows) for resolved in inputs.preferences} == {7}


async def test_an_override_replaces_its_areas_declaration_wholly() -> None:
    # A habit that declares windows and no ideal duration has none, whatever its Area declares,
    # which is what makes an override a replacement rather than a merge.
    fitness = an_area(name="Fitness")
    habit = a_habit(area_id=fitness.id)

    inputs = await an_assembler(
        areas=FakeAreas([fitness]),
        habits=FakeHabits([habit]),
        preferences=FakePreferences(
            [
                a_preference(
                    owner=an_area_owner(fitness.id),
                    windows=[a_window(time(5, 30), time(7, 0))],
                    preferred_duration_minutes=60,
                    strength=PreferenceStrength.SOFT,
                ),
                a_preference(
                    owner=a_habit_owner(habit.id),
                    windows=[a_window(time(13, 15), time(14, 15))],
                    strength=PreferenceStrength.STRONG,
                ),
            ]
        ),
    ).assemble(WEEK, NOW)

    resolved = next(entry for entry in inputs.preferences if entry.owner.id == habit.id)
    assert resolved.strength is PreferenceStrength.STRONG
    assert resolved.preferred_duration_minutes is None
    assert resolved.windows[0] == between(13.25, 14.25)


async def test_an_override_naming_no_window_opts_out_of_its_areas_preference() -> None:
    fitness = an_area(name="Fitness")
    habit = a_habit(area_id=fitness.id)

    inputs = await an_assembler(
        areas=FakeAreas([fitness]),
        habits=FakeHabits([habit]),
        preferences=FakePreferences(
            [
                a_preference(
                    owner=an_area_owner(fitness.id), windows=[a_window(time(5, 30), time(7, 0))]
                ),
                a_preference(owner=a_habit_owner(habit.id), windows=[]),
            ]
        ),
    ).assemble(WEEK, NOW)

    resolved = next(entry for entry in inputs.preferences if entry.owner.id == habit.id)
    assert resolved.windows == ()


async def test_a_declared_window_resolves_against_each_days_own_zone() -> None:
    # Wall time, so `05:30` is 05:30 wherever the user is. Seven dates, one interval each.
    fitness = an_area(name="Fitness")

    inputs = await an_assembler(
        areas=FakeAreas([fitness]),
        settings=FakeSettings("Europe/London"),
        preferences=FakePreferences(
            [
                a_preference(
                    owner=an_area_owner(fitness.id), windows=[a_window(time(5, 30), time(7, 0))]
                )
            ]
        ),
    ).assemble(WEEK, NOW)

    windows = inputs.preferences[0].windows
    assert len(windows) == 7
    assert windows[0] == between(5.5, 7)
    assert windows[6] == between(5.5, 7, day=6)


async def test_an_area_with_no_preference_and_no_override_resolves_nothing() -> None:
    fitness = an_area(name="Fitness")
    habit = a_habit(area_id=fitness.id)

    inputs = await an_assembler(
        areas=FakeAreas([fitness]), habits=FakeHabits([habit]), preferences=FakePreferences([])
    ).assemble(WEEK, NOW)

    assert inputs.preferences == ()


# --------------------------------------------------------------------------------
# The duration multiplier and its maturity gate
# --------------------------------------------------------------------------------


async def test_a_multiplier_corrects_an_estimate_where_the_weight_set_names_the_area() -> None:
    fitness = an_area(name="Fitness")
    task = a_task(area_id=fitness.id, estimate_minutes=FOUR_HOURS)

    inputs = await an_assembler(
        areas=FakeAreas([fitness]),
        tasks=FakeTasks([task]),
        weights=FakeWeights(a_weight_set(duration_multiplier={str(fitness.id): 1.2})),
    ).assemble(WEEK, NOW)

    assert [entry.remaining_minutes for entry in inputs.eligible_tasks] == [288]


async def test_an_area_the_weight_set_does_not_name_is_scaled_by_nothing() -> None:
    # A parameter below its maturity gate is not applied at all rather than at a reduced weight,
    # and an Area absent from the map is exactly that state.
    fitness, career = an_area(name="Fitness"), an_area(name="Career")
    task = a_task(area_id=career.id, estimate_minutes=FOUR_HOURS)

    inputs = await an_assembler(
        areas=FakeAreas([fitness, career]),
        tasks=FakeTasks([task]),
        weights=FakeWeights(a_weight_set(duration_multiplier={str(fitness.id): 1.2})),
    ).assemble(WEEK, NOW)

    assert [entry.remaining_minutes for entry in inputs.eligible_tasks] == [FOUR_HOURS]


async def test_an_elastic_habit_range_is_scaled_and_moved_back_onto_the_grid() -> None:
    fitness = an_area(name="Fitness")
    habit = a_habit(
        area_id=fitness.id,
        times_per_week=1,
        duration=Duration.elastic(min_minutes=30, max_minutes=90),
    )

    inputs = await an_assembler(
        areas=FakeAreas([fitness]),
        habits=FakeHabits([habit]),
        weights=FakeWeights(a_weight_set(duration_multiplier={str(fitness.id): 1.5})),
    ).assemble(WEEK, NOW)

    assert inputs.habit_occurrences[0].duration == Duration.elastic(min_minutes=45, max_minutes=135)


async def test_a_fixed_habit_duration_is_the_users_declaration_and_is_left_alone() -> None:
    # `Gym - Legs` is ninety minutes or nothing, so scaling it would overrule a declaration rather
    # than correct an estimate.
    fitness = an_area(name="Fitness")
    habit = a_habit(area_id=fitness.id, times_per_week=1, duration=Duration.fixed(90))

    inputs = await an_assembler(
        areas=FakeAreas([fitness]),
        habits=FakeHabits([habit]),
        weights=FakeWeights(a_weight_set(duration_multiplier={str(fitness.id): 1.5})),
    ).assemble(WEEK, NOW)

    assert inputs.habit_occurrences[0].duration == Duration.fixed(90)


async def test_an_unreadable_multiplier_is_not_applied_rather_than_failing_the_assembly() -> None:
    # Taking the assembly down would stop every pin, every verdict, and every solve over an
    # optional correction, and the fallback is exactly the state of an unfitted Area.
    fitness = an_area(name="Fitness")
    task = a_task(area_id=fitness.id, estimate_minutes=FOUR_HOURS)

    inputs = await an_assembler(
        areas=FakeAreas([fitness]),
        tasks=FakeTasks([task]),
        weights=FakeWeights(
            a_weight_set(
                duration_multiplier={str(fitness.id): 0, "not-an-area": 1.2, "x": float("inf")}
            )
        ),
    ).assemble(WEEK, NOW)

    assert [entry.remaining_minutes for entry in inputs.eligible_tasks] == [FOUR_HOURS]


async def test_a_tenant_with_no_active_weight_set_is_sized_at_their_own_estimates() -> None:
    fitness = an_area(name="Fitness")
    task = a_task(area_id=fitness.id, estimate_minutes=FOUR_HOURS)

    inputs = await an_assembler(
        areas=FakeAreas([fitness]), tasks=FakeTasks([task]), weights=FakeWeights(None)
    ).assemble(WEEK, NOW)

    assert [entry.remaining_minutes for entry in inputs.eligible_tasks] == [FOUR_HOURS]


# --------------------------------------------------------------------------------
# Folding the four concessions
# --------------------------------------------------------------------------------


def test_every_stored_concession_kind_is_one_the_fold_knows() -> None:
    # Bounded by the inventory the column may hold, so a fifth kind cannot reach the fold as a
    # concession nothing applies.
    assert {kind.value for kind in AdjustmentKind} == set(ADJUSTMENT_KINDS)


async def test_dropping_an_item_removes_it_from_eligibility_and_from_every_demand() -> None:
    # Without the second half, the probe keeps demanding work for a task nothing will schedule, so
    # a phantom shortfall persists and the backlog keeps marking the task at risk.
    area = an_area()
    task = a_task(area_id=area.id, estimate_minutes=FOUR_HOURS, deadline=at(9, day=4))

    inputs = await an_assembler(
        areas=FakeAreas([area]),
        tasks=FakeTasks([task]),
        adjustments=FakeAdjustments(
            [an_adjustment(kind=AdjustmentKind.DROP_ITEM.value, target_id=task.id)]
        ),
    ).assemble(WEEK, NOW)

    assert inputs.eligible_tasks == ()
    assert inputs.deadline_demands == ()


async def test_accepting_a_partial_clears_the_deadline_and_drops_the_demand() -> None:
    # Without the first half the panel goes quiet while the objective still strains against the
    # deadline the user excused, because deadline risk reads the eligibility and not the demand.
    area = an_area()
    task = a_task(area_id=area.id, estimate_minutes=FOUR_HOURS, deadline=at(9, day=4))

    inputs = await an_assembler(
        areas=FakeAreas([area]),
        tasks=FakeTasks([task]),
        adjustments=FakeAdjustments(
            [an_adjustment(kind=AdjustmentKind.ACCEPT_PARTIAL.value, target_id=task.id)]
        ),
    ).assemble(WEEK, NOW)

    assert [entry.deadline for entry in inputs.eligible_tasks] == [None]
    assert [entry.remaining_minutes for entry in inputs.eligible_tasks] == [FOUR_HOURS]
    assert inputs.deadline_demands == ()


async def test_breaching_a_floor_lowers_both_of_the_areas_floor_quantities() -> None:
    # Without the second half the concession does not close the shortfall it was offered for: the
    # user approves the breach and the verdict panel reports the same gap.
    fitness = an_area(name="Fitness", floor_hours=Decimal(5))

    inputs = await an_assembler(
        areas=FakeAreas([fitness]),
        adjustments=FakeAdjustments(
            [
                an_adjustment(
                    kind=AdjustmentKind.BREACH_FLOOR.value, target_id=fitness.id, delta_minutes=80
                )
            ]
        ),
    ).assemble(WEEK, NOW)

    assert inputs.areas[0].floor_minutes == 5 * MINUTES_PER_HOUR - 80
    assert inputs.areas[0].floor_reservation_minutes == 5 * MINUTES_PER_HOUR - 80


async def test_reducing_a_routine_shortens_the_named_date_only() -> None:
    routine = a_routine(duration_minutes=480, min_duration_minutes=360)
    wednesday = MONDAY.replace(day=MONDAY.day + 2)

    inputs = await an_assembler(
        routines=FakeRoutines([routine]),
        adjustments=FakeAdjustments(
            [
                an_adjustment(
                    kind=AdjustmentKind.REDUCE_ROUTINE.value,
                    target_id=routine.id,
                    reductions={date_occurrence_key(wednesday): 60},
                )
            ]
        ),
    ).assemble(WEEK, NOW)

    by_key = {entry.occurrence_key: entry for entry in inputs.frame}
    assert by_key[date_occurrence_key(wednesday)].interval.total_minutes() == 420
    assert by_key[date_occurrence_key(MONDAY)].interval.total_minutes() == 480


async def test_a_reduction_below_the_routines_floor_is_clamped_to_it() -> None:
    # The clamp to the routine's own minimum, and the sleep floor is this clamp on the sleep
    # routine: the solver may propose spending it and may never spend it silently, so a concession
    # cannot cut below what the user set.
    routine = a_routine(duration_minutes=480, min_duration_minutes=360)

    inputs = await an_assembler(
        routines=FakeRoutines([routine]),
        adjustments=FakeAdjustments(
            [
                an_adjustment(
                    kind=AdjustmentKind.REDUCE_ROUTINE.value,
                    target_id=routine.id,
                    reductions={date_occurrence_key(MONDAY): 240},
                )
            ]
        ),
    ).assemble(WEEK, NOW)

    monday = next(
        entry for entry in inputs.frame if entry.occurrence_key == date_occurrence_key(MONDAY)
    )
    assert monday.interval.total_minutes() == 360


async def test_a_candidate_concession_folds_by_the_same_path_and_persists_nothing() -> None:
    # Requesting a tradeoff must leave no trace, which is why the candidate is an argument rather
    # than a row: the assembly that follows it reads the week as it was.
    fitness = an_area(name="Fitness", floor_hours=Decimal(5))
    candidate = WeekAdjustment(
        adjustment_id=uuid4(),
        kind=AdjustmentKind.BREACH_FLOOR,
        target_id=fitness.id,
        delta_minutes=60,
    )
    assembler = an_assembler(areas=FakeAreas([fitness]))

    evaluated = await assembler.assemble(WEEK, NOW, candidate)
    after = await assembler.assemble(WEEK, NOW)

    assert evaluated.areas[0].floor_minutes == 4 * MINUTES_PER_HOUR
    assert evaluated.adjustments == (candidate,)
    assert after.areas[0].floor_minutes == 5 * MINUTES_PER_HOUR
    assert after.adjustments == ()


async def test_an_approved_concession_is_carried_so_a_reason_can_cite_it() -> None:
    fitness = an_area(name="Fitness", floor_hours=Decimal(5))
    stored = an_adjustment(
        kind=AdjustmentKind.BREACH_FLOOR.value, target_id=fitness.id, delta_minutes=60
    )

    inputs = await an_assembler(
        areas=FakeAreas([fitness]), adjustments=FakeAdjustments([stored])
    ).assemble(WEEK, NOW)

    assert [entry.adjustment_id for entry in inputs.adjustments] == [stored.id]
    assert inputs.adjustments[0].kind is AdjustmentKind.BREACH_FLOOR


async def test_a_stored_concession_and_a_candidate_on_one_target_compound() -> None:
    # The storage index makes two STORED concessions on one kind and target unreachable, and it does
    # not cover a candidate, which is an argument rather than a row. So the two apply in turn:
    # ``delta_minutes`` is an INCREMENT against the figure as it stands, computed over an
    # already-folded assembly, so a second concession on one target lowers what the first left.
    # Compounding is therefore correct arithmetic rather than a defect.
    fitness = an_area(name="Fitness", floor_hours=Decimal(5))
    stored = an_adjustment(
        kind=AdjustmentKind.BREACH_FLOOR.value, target_id=fitness.id, delta_minutes=60
    )
    candidate = WeekAdjustment(
        adjustment_id=uuid4(),
        kind=AdjustmentKind.BREACH_FLOOR,
        target_id=fitness.id,
        delta_minutes=120,
    )

    inputs = await an_assembler(
        areas=FakeAreas([fitness]), adjustments=FakeAdjustments([stored])
    ).assemble(WEEK, NOW, candidate)

    assert inputs.areas[0].floor_minutes == 5 * MINUTES_PER_HOUR - 180
    assert len(inputs.adjustments) == 2


async def test_concessions_on_one_target_apply_in_either_order_to_one_figure() -> None:
    # The half of the order claim that does hold: successive clamped subtraction commutes, so the
    # figure does not depend on which concession the list carries first.
    fitness = an_area(name="Fitness", floor_hours=Decimal(5))
    smaller = an_adjustment(
        kind=AdjustmentKind.BREACH_FLOOR.value, target_id=fitness.id, delta_minutes=60
    )
    larger = WeekAdjustment(
        adjustment_id=uuid4(),
        kind=AdjustmentKind.BREACH_FLOOR,
        target_id=fitness.id,
        delta_minutes=120,
    )
    swapped = an_adjustment(
        kind=AdjustmentKind.BREACH_FLOOR.value, target_id=fitness.id, delta_minutes=120
    )
    smaller_candidate = WeekAdjustment(
        adjustment_id=uuid4(),
        kind=AdjustmentKind.BREACH_FLOOR,
        target_id=fitness.id,
        delta_minutes=60,
    )

    forward = await an_assembler(
        areas=FakeAreas([fitness]), adjustments=FakeAdjustments([smaller])
    ).assemble(WEEK, NOW, larger)
    backward = await an_assembler(
        areas=FakeAreas([fitness]), adjustments=FakeAdjustments([swapped])
    ).assemble(WEEK, NOW, smaller_candidate)

    assert forward.areas[0].floor_minutes == backward.areas[0].floor_minutes


async def test_a_breach_of_a_negative_figure_lowers_nothing_rather_than_raising_the_floor() -> None:
    # Subtracting a negative would RAISE a 5h floor to 15h, so a concession whose whole meaning is
    # to relax a hard constraint would tighten one. The column is nullable with no check constraint
    # and nothing writes it yet, so the fold is where the absurd state stops.
    fitness = an_area(name="Fitness", floor_hours=Decimal(5))

    inputs = await an_assembler(
        areas=FakeAreas([fitness]),
        adjustments=FakeAdjustments(
            [
                an_adjustment(
                    kind=AdjustmentKind.BREACH_FLOOR.value,
                    target_id=fitness.id,
                    delta_minutes=-600,
                )
            ]
        ),
    ).assemble(WEEK, NOW)

    assert inputs.areas[0].floor_minutes == 5 * MINUTES_PER_HOUR
    assert inputs.areas[0].floor_reservation_minutes == 5 * MINUTES_PER_HOUR


async def test_a_reduction_naming_a_date_this_week_does_not_hold_is_dropped() -> None:
    # A concession is week-scoped, so a foreign date names an occurrence another week's assembly
    # owns: carried through, it would sit on the snapshot applying to nothing while the concession
    # claimed to have been honoured.
    routine = a_routine(duration_minutes=480, min_duration_minutes=360)

    inputs = await an_assembler(
        routines=FakeRoutines([routine]),
        adjustments=FakeAdjustments(
            [
                an_adjustment(
                    kind=AdjustmentKind.REDUCE_ROUTINE.value,
                    target_id=routine.id,
                    reductions={"2030-01-01": 60, date_occurrence_key(MONDAY): 60},
                )
            ]
        ),
    ).assemble(WEEK, NOW)

    assert set(inputs.adjustments[0].reductions) == {MONDAY}
    by_key = {entry.occurrence_key: entry for entry in inputs.frame}
    assert by_key[date_occurrence_key(MONDAY)].interval.total_minutes() == 420


@pytest.fixture
def captured_log() -> Iterator[io.StringIO]:
    """Render to a captured stream, then hand the configuration back.

    Logging configuration is process-global, and ``conftest.py`` fails the test that leaves it
    changed, so the restore is part of the fixture rather than an afterthought.
    """
    stream = io.StringIO()
    configure_logging(environment="production", log_level="info", stream=stream)
    yield stream
    configure_logging(environment="test", log_level="info")


async def test_a_malformed_key_and_a_foreign_date_are_reported_as_different_causes(
    captured_log: io.StringIO,
) -> None:
    # Both are dropped for one consequence, and an operator reading one event should not hunt for
    # the other fault: a foreign date is perfectly readable and merely out of scope.
    routine = a_routine()

    await an_assembler(
        routines=FakeRoutines([routine]),
        adjustments=FakeAdjustments(
            [
                an_adjustment(
                    kind=AdjustmentKind.REDUCE_ROUTINE.value,
                    target_id=routine.id,
                    reductions={
                        "not-a-date": 30,
                        "2030-01-01": 60,
                        date_occurrence_key(MONDAY): 60,
                    },
                )
            ]
        ),
    ).assemble(WEEK, NOW)

    reported = {
        line["event"]: line.get("entries")
        for line in (json.loads(line) for line in captured_log.getvalue().splitlines() if line)
        if line["event"].startswith("plans.adjustment.")
    }
    assert reported == {
        "plans.adjustment.unreadable_reduction": 1,
        "plans.adjustment.reduction_outside_the_week": 1,
    }
