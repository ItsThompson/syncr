"""The netting arithmetic, over literals: the two placement sets, and where they part.

Everything here is stated against instants and minute counts with no repository anywhere, because
the arithmetic is the thing three review rounds found defects in and it is decidable from four
numbers. What the assembler suite adds on top is that each quantity reads the set it claims to.

The boundary these tests are most about is ``now``. A placement is immovable when it HAS STARTED,
which is the reading the hard constraint takes, so the boundary is the start rather than the end
and a block straddling the instant is immovable for the whole of its span.

Which placements a figure nets and what span it counts of each are two separate questions, and the
second one parts the two Area figures: an Area's placed minutes count the time a placement occupies
and its floor reading counts the time the user gave the Area inside that span.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, NamedTuple
from uuid import UUID, uuid4

import pytest

from syncr_api.plans.netting import NO_CONTENT_AREAS, PlacedTime, areas_of_content, placements
from syncr_domain.identity import BindingKind, BindingRef
from syncr_domain.intervals import Interval
from syncr_domain.outcomes import MISS_STATE, OutcomeState, RecordedOutcome
from syncr_domain.templates import TemplateEntryKind
from tests.assembly_fakes import (
    NOW,
    a_habit,
    a_habit_block,
    a_pin,
    a_plan,
    a_task_block,
    at,
    between,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syncr_domain.plan import PlanDocument
    from syncr_solver.inputs import Pin

TASK = uuid4()
OTHER_TASK = uuid4()
FITNESS = uuid4()
CAREER = uuid4()

AN_HOUR = timedelta(hours=1)


class _Entry(NamedTuple):
    """The three facts the Area index reads off a template entry."""

    entry_id: UUID
    kind: TemplateEntryKind
    area_id: UUID


def placed_time(
    *,
    live_plan: PlanDocument | None = None,
    pins: tuple[Pin, ...] | list[Pin] = (),
    outcomes: tuple[RecordedOutcome, ...] | list[RecordedOutcome] = (),
    now: datetime = NOW,
    areas_of: Mapping[tuple[BindingKind, UUID], UUID] | None = None,
) -> PlacedTime:
    return PlacedTime(
        placements(
            live_plan,
            pins,
            now=now,
            outcomes=outcomes,
            areas_of=NO_CONTENT_AREAS if areas_of is None else areas_of,
        ),
        now=now,
    )


def test_a_block_that_has_not_started_is_movable_and_nets_from_neither_quantity() -> None:
    # Thursday, a day after `now`: the solver will discard and re-place it.
    plan = a_plan(
        blocks=[a_task_block(task_id=TASK, area_id=FITNESS, interval=between(9, 10, day=3))]
    )

    placed = placed_time(live_plan=plan)

    assert placed.immovable_minutes_of_task(TASK) == 0
    assert placed.immovable_minutes_of_area(FITNESS) == 0
    assert placed.minutes_of_area(FITNESS) == 60


def test_a_block_that_started_before_now_is_immovable() -> None:
    plan = a_plan(
        blocks=[a_task_block(task_id=TASK, area_id=FITNESS, interval=between(9, 10, day=1))]
    )

    placed = placed_time(live_plan=plan)

    assert placed.immovable_minutes_of_task(TASK) == 60
    assert placed.minutes_of_area(FITNESS) == 60


@pytest.mark.parametrize(
    ("label", "start", "immovable_minutes"),
    [
        ("starting_one_minute_before_now", NOW - timedelta(minutes=1), 60),
        ("starting_exactly_at_now", NOW, 60),
        ("starting_one_minute_after_now", NOW + timedelta(minutes=1), 0),
    ],
)
def test_the_boundary_is_the_start_and_now_itself_has_started(
    label: str, start: datetime, immovable_minutes: int
) -> None:
    # A block running ACROSS `now` is immovable for its whole span rather than for its elapsed
    # part: the rule is about whether the solver may move the block, not about how much of it
    # has happened.
    interval = Interval(start, start + AN_HOUR)
    plan = a_plan(blocks=[a_task_block(task_id=TASK, area_id=FITNESS, interval=interval)])

    placed = placed_time(live_plan=plan)

    assert placed.immovable_minutes_of_task(TASK) == immovable_minutes, label


def test_a_pin_makes_a_future_block_immovable_without_changing_what_is_placed() -> None:
    interval = between(9, 10, day=3)
    plan = a_plan(blocks=[a_task_block(task_id=TASK, area_id=FITNESS, interval=interval)])
    pin = a_pin(binding=BindingRef.for_task(TASK), interval=interval)

    before = placed_time(live_plan=plan)
    after = placed_time(live_plan=plan, pins=[pin])

    assert before.minutes_of_area(FITNESS) == after.minutes_of_area(FITNESS) == 60
    assert before.immovable_minutes_of_task(TASK) == 0
    assert after.immovable_minutes_of_task(TASK) == 60
    # The pinned hour is Thursday's, which has not happened. It still lowers the floor the solver
    # must place, because the solver may no longer move it: an hour it is holding is an hour of the
    # floor it does not have to find room for.
    assert before.immovable_minutes_of_area(FITNESS) == 0
    assert after.immovable_minutes_of_area(FITNESS) == 60


def test_a_pin_and_the_block_it_pins_are_one_placement_at_the_pins_interval() -> None:
    # Counted twice, a pinned hour would net twice out of every quantity that reads it, and the
    # effect would be invisible: every figure would merely be lower than the truth.
    plan = a_plan(
        blocks=[a_task_block(task_id=TASK, area_id=FITNESS, interval=between(9, 10, day=3))]
    )
    pin = a_pin(binding=BindingRef.for_task(TASK), interval=between(14, 15, day=3))

    committed = placements(plan, [pin], now=NOW)
    placed = placed_time(live_plan=plan, pins=[pin])

    assert [item.interval for item in committed] == [pin.interval]
    assert placed.immovable_minutes_of_task(TASK) == 60
    assert placed.minutes_of_area(FITNESS) == 60


def test_the_pins_interval_is_where_the_block_is_and_it_decides_what_falls_before() -> None:
    # The half a minute count cannot see. The plan placed the work on Wednesday, before Friday's
    # deadline; the user pinned it to Saturday, after it. Read at the plan's interval, the demand
    # counts two hours that no longer fall before the deadline and reports the task as further on
    # than it is.
    friday_09 = at(9, day=4)
    plan = a_plan(
        blocks=[a_task_block(task_id=TASK, area_id=CAREER, interval=between(9, 11, day=3))]
    )
    pin = a_pin(binding=BindingRef.for_task(TASK), interval=between(9, 11, day=5))

    placed = placed_time(live_plan=plan, pins=[pin])

    attributed = placed.attributed_to_task_before(TASK, friday_09)
    assert (attributed.past, attributed.future) == (0, 0)
    assert placed.immovable_minutes_of_task(TASK) == 120


def test_an_orphan_pin_takes_its_area_from_the_entity_its_binding_names() -> None:
    # The user's edit outlives a re-solve that dropped the block. The pin carries no Area of its
    # own, so it takes its task's, and the hour stays committed time an Area figure sees.
    pin = a_pin(binding=BindingRef.for_task(TASK), interval=between(9, 10, day=3))

    placed = placed_time(pins=[pin], areas_of={(BindingKind.TASK, TASK): FITNESS})

    assert placed.immovable_minutes_of_task(TASK) == 60
    assert placed.minutes_of_area(FITNESS) == 60
    # Immovable, the pinned hour honours the floor too: the solver may not move it.
    assert placed.immovable_minutes_of_area(FITNESS) == 60


def test_an_orphan_pin_over_content_no_entity_answers_carries_no_area() -> None:
    # A binding whose entity no longer exists resolves to nothing rather than to a guess.
    pin = a_pin(binding=BindingRef.for_task(TASK), interval=between(9, 10, day=3))

    placed = placed_time(pins=[pin])

    assert placed.immovable_minutes_of_task(TASK) == 60
    assert placed.minutes_of_area(FITNESS) == 0


def test_a_paired_pin_keeps_the_blocks_area_rather_than_the_resolved_one() -> None:
    # Pairing wins over resolution: the pin moves the block, not whose it is, so a stale index
    # cannot move a pinned block's minutes to another Area.
    plan = a_plan(
        blocks=[a_task_block(task_id=TASK, area_id=CAREER, interval=between(9, 10, day=3))]
    )
    pin = a_pin(binding=BindingRef.for_task(TASK), interval=between(14, 15, day=3))

    placed = placed_time(live_plan=plan, pins=[pin], areas_of={(BindingKind.TASK, TASK): FITNESS})

    assert placed.minutes_of_area(CAREER) == 60
    assert placed.minutes_of_area(FITNESS) == 0


def test_an_orphan_habit_pin_takes_its_area_from_its_habit() -> None:
    # A habit occurrence is pinnable content the same way a task block is, and its habit never
    # moves between Areas: the index answers it like any other entity.
    habit = a_habit(area_id=FITNESS)
    pin = a_pin(binding=BindingRef.for_habit(habit.id, index=2), interval=between(9, 10, day=3))

    placed = placed_time(pins=[pin], areas_of=areas_of_content(habits=[habit]))

    assert placed.minutes_of_area(FITNESS) == 60


def test_the_area_index_answers_a_concrete_entry_and_not_a_slot() -> None:
    # A slot binds late and becomes no block of its own, so no pin can ever name one: mapping it
    # would answer a binding nothing carries.
    concrete_id, slot_id = uuid4(), uuid4()
    entries = [
        _Entry(entry_id=slot_id, kind=TemplateEntryKind.SLOT, area_id=FITNESS),
        _Entry(entry_id=concrete_id, kind=TemplateEntryKind.CONCRETE, area_id=CAREER),
    ]

    areas = areas_of_content(template_entries=entries)

    assert dict(areas) == {(BindingKind.TEMPLATE_ENTRY, concrete_id): CAREER}


def test_two_blocks_of_one_area_covering_one_minute_contribute_that_minute_once() -> None:
    # A user-authored overlap is legitimate, so a summed pair would let a floor read as satisfied
    # by time that does not exist.
    plan = a_plan(
        blocks=[
            a_task_block(task_id=TASK, area_id=FITNESS, interval=between(9, 11, day=1)),
            a_habit_block(habit_id=uuid4(), area_id=FITNESS, interval=between(10, 12, day=1)),
        ]
    )

    placed = placed_time(live_plan=plan)

    assert placed.minutes_of_area(FITNESS) == 3 * 60


def test_a_chunk_of_a_divided_task_is_that_tasks_placement() -> None:
    plan = a_plan(
        blocks=[
            a_task_block(
                task_id=TASK, area_id=CAREER, interval=between(9, 10, day=1), split_index=0
            ),
            a_task_block(
                task_id=TASK, area_id=CAREER, interval=between(9, 10, day=2), split_index=1
            ),
        ]
    )

    placed = placed_time(live_plan=plan)

    assert placed.immovable_minutes_of_task(TASK) == 120


def test_a_placement_is_attributed_to_its_own_task_only() -> None:
    plan = a_plan(
        blocks=[a_task_block(task_id=OTHER_TASK, area_id=CAREER, interval=between(9, 10, day=1))]
    )

    placed = placed_time(live_plan=plan)

    assert placed.immovable_minutes_of_task(TASK) == 0
    assert placed.immovable_minutes_of_task(OTHER_TASK) == 60


def test_minutes_before_a_deadline_are_split_at_now_and_a_later_block_is_not_counted() -> None:
    # Three placements of one task are three CHUNKS of it, because a document refuses two blocks
    # sharing a binding and a task's binding is keyed by its chunk.
    friday_09 = at(9, day=4)
    plan = a_plan(
        blocks=[
            a_task_block(
                task_id=TASK,
                area_id=CAREER,
                interval=between(9, 10, day=1),
                split_index=0,
                split_count=3,
            ),
            a_task_block(
                task_id=TASK,
                area_id=CAREER,
                interval=between(9, 11, day=3),
                split_index=1,
                split_count=3,
            ),
            a_task_block(
                task_id=TASK,
                area_id=CAREER,
                interval=between(9, 10, day=5),
                split_index=2,
                split_count=3,
            ),
        ]
    )

    attributed = placed_time(live_plan=plan).attributed_to_task_before(TASK, friday_09)

    assert attributed.past == 60
    assert attributed.future == 120


def test_a_placement_straddling_the_deadline_contributes_only_the_part_before_it() -> None:
    # An hour begun before a deadline and finished after it did half an hour of the work.
    deadline = at(9.5, day=3)
    plan = a_plan(
        blocks=[a_task_block(task_id=TASK, area_id=CAREER, interval=between(9, 10, day=3))]
    )

    attributed = placed_time(live_plan=plan).attributed_to_task_before(TASK, deadline)

    assert attributed.future == 30


def test_a_placement_straddling_now_is_past_for_the_minutes_that_have_elapsed() -> None:
    # Immovability is decided on the whole block and attribution is decided per minute: the two
    # answer different questions, and reading either as the other inverts a verdict.
    plan = a_plan(
        blocks=[
            a_task_block(
                task_id=TASK, area_id=CAREER, interval=Interval(NOW - AN_HOUR, NOW + AN_HOUR)
            )
        ]
    )
    placed = placed_time(live_plan=plan)

    attributed = placed.attributed_to_task_before(TASK, at(9, day=5))

    assert (attributed.past, attributed.future) == (60, 60)
    assert placed.immovable_minutes_of_task(TASK) == 120
    # An hour of it is still to come and the solver may not move any of it, so the whole two hours
    # count toward the Area's floor: nothing about a block in progress says the user is not doing
    # the second half of it.
    assert placed.immovable_minutes_of_area(CAREER) == 120


def test_a_deadline_at_or_before_the_earliest_placement_attributes_nothing() -> None:
    plan = a_plan(
        blocks=[a_task_block(task_id=TASK, area_id=CAREER, interval=between(9, 10, day=1))]
    )

    attributed = placed_time(live_plan=plan).attributed_to_task_before(TASK, at(9, day=1))

    assert (attributed.past, attributed.future) == (0, 0)


def test_a_week_holding_no_plan_and_no_pin_has_committed_nothing() -> None:
    placed = placed_time()

    assert placed.immovable_minutes_of_task(TASK) == 0
    assert placed.minutes_of_area(FITNESS) == 0
    assert placed.attributed_to_task_before(TASK, at(9, day=4)).past == 0


def test_placements_are_emitted_in_one_order_whatever_order_they_arrived_in() -> None:
    # Two assemblies of unchanged data must be equal, so every collection the assembler emits
    # needs a total order that does not depend on a dictionary's iteration.
    early = a_task_block(task_id=TASK, area_id=CAREER, interval=between(9, 10, day=1))
    late = a_task_block(task_id=OTHER_TASK, area_id=CAREER, interval=between(9, 10, day=3))

    forward = placements(a_plan(blocks=[early, late]), (), now=NOW)
    backward = placements(a_plan(blocks=[late, early]), (), now=NOW)

    assert forward == backward
    assert [item.interval for item in forward] == [early.interval, late.interval]


# --------------------------------------------------------------------------------
# What an outcome changes, and the column of the table that is uniform
# --------------------------------------------------------------------------------

FRIDAY_09 = at(9, day=4)


def a_past_task_hour() -> PlanDocument:
    """Monday 09:00-10:00 of Career work on ``TASK``, an hour behind ``now``."""
    return a_plan(
        blocks=[a_task_block(task_id=TASK, area_id=CAREER, interval=between(9, 10, day=1))]
    )


def an_outcome(
    state: OutcomeState,
    *,
    actual_minutes: int | None = None,
    actual_interval: Interval | None = None,
) -> RecordedOutcome:
    return RecordedOutcome(
        binding=BindingRef.for_task(TASK),
        state=state,
        actual_minutes=actual_minutes,
        actual_interval=actual_interval,
    )


def test_a_skipped_past_block_stops_counting_toward_its_task() -> None:
    # The user said the work was not done, so the hour is no longer
    # attributed and the demand this figure is subtracted from rises by it. Without this the
    # product counts work the user explicitly denied doing.
    plan = a_past_task_hour()

    presumed = placed_time(live_plan=plan)
    skipped = placed_time(live_plan=plan, outcomes=[an_outcome(MISS_STATE)])

    assert presumed.attributed_to_task_before(TASK, FRIDAY_09).past == 60
    assert skipped.attributed_to_task_before(TASK, FRIDAY_09).past == 0


def test_a_partial_past_block_is_attributed_the_minutes_it_reports() -> None:
    plan = a_past_task_hour()

    placed = placed_time(
        live_plan=plan, outcomes=[an_outcome(OutcomeState.PARTIAL, actual_minutes=20)]
    )

    assert placed.attributed_to_task_before(TASK, FRIDAY_09).past == 20


def test_a_moved_block_is_attributed_where_it_really_happened() -> None:
    # The half a minute count cannot see, and the reason `moved` carries an interval rather than a
    # length: the work planned for Monday really happened on Saturday, which does no work due on
    # Friday. Attributing 60 minutes because the span was an hour long would credit the deadline
    # with work done after it.
    plan = a_past_task_hour()
    saturday = between(9, 10, day=5)

    placed = placed_time(
        live_plan=plan, outcomes=[an_outcome(OutcomeState.MOVED, actual_interval=saturday)]
    )

    before_friday = placed.attributed_to_task_before(TASK, FRIDAY_09)
    whole_week = placed.attributed_to_task_before(TASK, at(9, day=6))
    assert (before_friday.past, before_friday.future) == (0, 0)
    assert whole_week.future == 60


@pytest.mark.parametrize(
    "outcome",
    [
        None,
        OutcomeState.PRESUMED,
        OutcomeState.COMPLETED,
        OutcomeState.PARTIAL,
        OutcomeState.SKIPPED,
        OutcomeState.MOVED,
    ],
    ids=["no row", "presumed", "completed", "partial", "skipped", "moved"],
)
def test_no_outcome_returns_a_span_to_capacity_or_makes_a_past_block_movable(
    outcome: OutcomeState | None,
) -> None:
    # The uniform column of the outcome-state table, asserted over the whole vocabulary rather than
    # over the one state that tempted it. If `skipped` returned its hour to capacity, skipping
    # work would make the week read as MORE feasible, which is the inversion the split between
    # attribution and capacity exists to prevent.
    #
    # What each state gives the Area's floor reading is the column that VARIES, and it is asserted
    # over the same vocabulary in the test below.
    plan = a_past_task_hour()
    recorded = (
        []
        if outcome is None
        else [
            an_outcome(
                outcome,
                actual_minutes=20 if outcome is OutcomeState.PARTIAL else None,
                actual_interval=between(9, 10, day=5) if outcome is OutcomeState.MOVED else None,
            )
        ]
    )

    placed = placed_time(live_plan=plan, outcomes=recorded)

    assert placed.minutes_of_area(CAREER) == 60
    assert placed.immovable_minutes_of_task(TASK) == 60


@pytest.mark.parametrize(
    ("recorded", "honoured_minutes"),
    [
        (None, 60),
        (an_outcome(OutcomeState.PRESUMED), 60),
        (an_outcome(OutcomeState.COMPLETED), 60),
        (an_outcome(OutcomeState.PARTIAL, actual_minutes=20), 20),
        (an_outcome(OutcomeState.PARTIAL, actual_minutes=90), 60),
        (an_outcome(MISS_STATE), 0),
        (an_outcome(OutcomeState.MOVED, actual_interval=between(9, 10, day=5)), 0),
    ],
    ids=[
        "no row",
        "presumed",
        "completed",
        "partial",
        "partial over the block",
        "skipped",
        "moved off the span",
    ],
)
def test_the_areas_floor_reading_counts_what_the_user_gave_it_inside_the_span(
    recorded: RecordedOutcome | None, honoured_minutes: int
) -> None:
    # The figure the solver's floor arrives netted of. A skipped hour honours no floor, so the
    # minutes the solver must still place RISE by it: read over the placement's own span instead,
    # the floor reads as met by work the user said did not happen.
    #
    # A `partial` reporting MORE than the block was planned for is legitimate and is not refused:
    # the user is reporting how long the work took. The hour the plan holds is what honours the
    # floor, so ninety reported minutes honour sixty, which is the other place the upper bound of
    # this reading does work.
    plan = a_past_task_hour()

    placed = placed_time(live_plan=plan, outcomes=[] if recorded is None else [recorded])

    assert placed.immovable_minutes_of_area(CAREER) == honoured_minutes
    # The pair, on one row: the hour is committed time whatever the user said happened in it.
    assert placed.minutes_of_area(CAREER) == 60


@pytest.mark.parametrize(
    ("actual", "honoured_minutes"),
    [
        (Interval(at(9.25, day=1), at(9.75, day=1)), 30),
        (between(9.5, 10.5, day=1), 30),
    ],
    ids=["inside the hour", "half of it outside"],
)
def test_a_move_is_honoured_for_the_part_of_it_the_placement_still_holds(
    actual: Interval, honoured_minutes: int
) -> None:
    # The rule is the part of the attributed span the placement holds rather than "a move counts
    # for nothing": half an hour reported inside the planned hour is half an hour of Career time
    # the solver may not re-place, and half an hour reported after the block ends is time the plan
    # does not hold, so the floor still needs it placed.
    plan = a_past_task_hour()

    placed = placed_time(
        live_plan=plan, outcomes=[an_outcome(OutcomeState.MOVED, actual_interval=actual)]
    )

    assert placed.immovable_minutes_of_area(CAREER) == honoured_minutes
    assert placed.minutes_of_area(CAREER) == 60


def test_an_outcome_naming_a_binding_no_placement_holds_changes_nothing() -> None:
    # The row is retained at this layer because it is a fact about a week that happened, and a week
    # whose plan no longer holds the block has nothing for it to change.
    plan = a_past_task_hour()
    stale = RecordedOutcome(binding=BindingRef.for_task(OTHER_TASK), state=MISS_STATE)

    placed = placed_time(live_plan=plan, outcomes=[stale])

    assert placed.attributed_to_task_before(TASK, FRIDAY_09).past == 60
    assert placed.minutes_of_area(CAREER) == 60


def test_an_outcome_is_read_against_the_pins_interval_rather_than_the_plans() -> None:
    # A pin is where the block IS, so a partial reported on a pinned block reports minutes of the
    # pinned hour. Read against the plan's interval instead, the reported minutes would be
    # attributed to a span the block no longer occupies.
    plan = a_plan(
        blocks=[a_task_block(task_id=TASK, area_id=CAREER, interval=between(9, 10, day=3))]
    )
    pin = a_pin(binding=BindingRef.for_task(TASK), interval=between(9, 10, day=1))

    placed = placed_time(
        live_plan=plan,
        pins=[pin],
        outcomes=[an_outcome(OutcomeState.PARTIAL, actual_minutes=30)],
    )

    attributed = placed.attributed_to_task_before(TASK, FRIDAY_09)
    assert (attributed.past, attributed.future) == (30, 0)


def test_a_move_onto_another_chunks_hour_is_counted_once_rather_than_twice() -> None:
    # Minutes are counted through an interval UNION, so a `moved` span landing on another placement
    # of the same task collapses into it: two hours become one. That is the right answer (the user
    # cannot have done two hours inside one) and it is the safe direction, because the demand this
    # figure is subtracted from rises. Pinned because it is a consequence of attributing SPANS
    # rather than counts, and nothing else in the suite would notice if the union became a sum.
    morning = a_task_block(
        task_id=TASK, area_id=CAREER, interval=between(9, 10, day=1), split_index=0, split_count=2
    )
    afternoon = a_task_block(
        task_id=TASK, area_id=CAREER, interval=between(14, 15, day=1), split_index=1, split_count=2
    )
    plan = a_plan(blocks=[morning, afternoon])
    onto_the_afternoon = RecordedOutcome(
        binding=morning.binding,
        state=OutcomeState.MOVED,
        actual_interval=afternoon.interval,
    )

    before = placed_time(live_plan=plan)
    after = placed_time(live_plan=plan, outcomes=[onto_the_afternoon])

    assert before.attributed_to_task_before(TASK, FRIDAY_09).past == 120
    assert after.attributed_to_task_before(TASK, FRIDAY_09).past == 60
    # Capacity is untouched, as it is for every outcome: both hours are still committed time.
    assert after.minutes_of_area(CAREER) == 120
