"""Phases 2 and 3: what content is eligible, how long it is placed for, and what a slot says.

Four groups, in the order a solve reaches them: which content becomes a candidate at all, how an
elastic occurrence's length is chosen, how a slot is filled or explained, and what the packer does
with the rest of the week.

Every test drives ``solve`` or the phase itself against literals. The week's whole span is ahead of
``now`` unless a test states its own clock, which the two about a slot the week has already reached
do, because what those two measure is the clip itself.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from syncr_domain.gaps import EmptySlotReason
from syncr_domain.habits import BindingSource
from syncr_domain.identity import is_placed_by_the_solver
from syncr_solver.attempt import Attempt
from syncr_solver.binding import bind_slots
from syncr_solver.candidates import candidates_for
from syncr_solver.constraints import ConstraintRule
from syncr_solver.elastic import sizes_for
from syncr_solver.filling import fill_gaps
from syncr_solver.reading import demand_key
from tests.materialized_weeks import (
    CAREER,
    FITNESS,
    NOW,
    a_frame_entry,
    a_slot,
    an_area_budget,
    an_off_plan_period,
    between,
)
from tests.objective_weeks import (
    A_TASK,
    ANOTHER_TASK,
    an_eligible_task,
    an_occurrence,
    hand_tuned_weights,
)
from tests.solve_weeks import QUICK, a_week, blocks_titled, minutes_toward, solved

if TYPE_CHECKING:
    from syncr_solver.inputs import SolveInputs

A_QUEUE_HABIT = uuid4()


def an_attempt(week: SolveInputs) -> Attempt:
    """A week with nothing placed, which is what a phase is driven against on its own."""
    return Attempt.of(week)


# --------------------------------------------------------------------------------------
# Which content becomes a candidate
# --------------------------------------------------------------------------------------


def test_a_task_with_nothing_left_to_place_is_not_a_candidate() -> None:
    week = a_week(eligible_tasks=(an_eligible_task(remaining_minutes=60),))

    offered = candidates_for(week, placed_minutes={}, floor_shortfalls={})
    exhausted = candidates_for(
        week,
        placed_minutes={demand_key(candidate.binding): 60 for candidate in offered},
        floor_shortfalls={},
    )

    assert [candidate.title for candidate in offered] == ["Leetcode"]
    assert exhausted == ()


def test_four_occurrences_of_one_habit_are_four_candidates_and_all_four_are_placed() -> None:
    """The demand key keeps the occurrence, so placing the first does not exhaust the other three.

    Read as content rather than as a demand, three of the four looked already placed the moment the
    first one landed, and a habit at four times a week was scheduled once.
    """
    week = a_week(
        habit_occurrences=tuple(an_occurrence(index=index, minutes=60) for index in range(4)),
        areas=(an_area_budget(target_minutes=600),),
    )

    document = solved(week).document

    assert len(blocks_titled(document, "Gym")) == 4


def test_a_queue_occurrence_names_the_backlog_item_it_drew_and_the_habit_it_is() -> None:
    week = a_week(
        habit_occurrences=(
            an_occurrence(
                habit_id=A_QUEUE_HABIT,
                minutes=60,
                title="Leetcode session",
                binding_source=BindingSource.QUEUE,
                area_id=CAREER,
            ),
        ),
        eligible_tasks=(
            an_eligible_task(task_id=A_TASK, remaining_minutes=60, area_id=CAREER, title="Trees"),
        ),
        areas=(an_area_budget(area_id=CAREER, name="Career", target_minutes=600),),
    )

    document = solved(week).document
    bound = blocks_titled(document, "Leetcode session")

    assert len(bound) == 1
    assert bound[0].title == "Leetcode session · Trees"
    assert bound[0].reason.clauses[0].source is BindingSource.QUEUE  # type: ignore[union-attr]
    assert bound[0].reason.clauses[0].selected == "Trees"  # type: ignore[union-attr]


def test_a_queue_occurrence_whose_area_has_an_empty_backlog_is_not_eligible_at_all() -> None:
    """The cadence is due and there is no content for it, which is the one unplaceable state."""
    week = a_week(
        habit_occurrences=(
            an_occurrence(
                habit_id=A_QUEUE_HABIT,
                minutes=60,
                title="Leetcode session",
                binding_source=BindingSource.QUEUE,
                area_id=CAREER,
            ),
        ),
        areas=(an_area_budget(area_id=CAREER, name="Career", target_minutes=600),),
    )

    document = solved(week).document

    assert blocks_titled(document, "Leetcode session") == ()


def test_a_rotation_occurrence_names_the_variant_its_cursor_resolved() -> None:
    week = a_week(
        habit_occurrences=(an_occurrence(minutes=60, variant="Shoulder & Arms"),),
        areas=(an_area_budget(target_minutes=600),),
    )

    placed = blocks_titled(solved(week).document, "Gym")

    assert placed[0].title == "Gym · Shoulder & Arms"
    assert placed[0].reason.clauses[0].cursor == "Shoulder & Arms"  # type: ignore[union-attr]


# --------------------------------------------------------------------------------------
# How long an elastic occurrence is placed for. One test per branch of the rule
# --------------------------------------------------------------------------------------


def test_the_largest_length_in_the_range_is_taken_where_it_fits() -> None:
    week = a_week(
        habit_occurrences=(an_occurrence(minutes=45, max_minutes=90),),
        areas=(an_area_budget(target_minutes=600),),
    )

    placed = blocks_titled(solved(week).document, "Gym")

    assert placed[0].interval.total_minutes() == 90


def test_a_length_that_would_pass_the_areas_weekly_target_is_not_offered() -> None:
    """Bounded by the target rather than the floor: one elastic habit would eat the remainder."""
    week = a_week(
        habit_occurrences=(an_occurrence(minutes=45, max_minutes=90),),
        areas=(an_area_budget(target_minutes=75),),
    )

    assert list(
        sizes_for(candidates_for(week, placed_minutes={}, floor_shortfalls={})[0], an_attempt(week))
    ) == [75, 60, 45]


def test_a_length_over_the_areas_daily_cap_is_refused_by_the_rule_that_owns_the_cap() -> None:
    """H8 answers the rule's third condition, over the local dates the placement reaches."""
    week = a_week(
        habit_occurrences=(an_occurrence(minutes=45, max_minutes=90),),
        areas=(an_area_budget(target_minutes=600, max_per_day_minutes=60),),
    )

    placed = blocks_titled(solved(week).document, "Gym")

    assert placed[0].interval.total_minutes() == 60


def test_the_minimum_is_taken_when_no_longer_length_satisfies_all_three() -> None:
    week = a_week(
        habit_occurrences=(an_occurrence(minutes=45, max_minutes=90),),
        areas=(an_area_budget(target_minutes=45),),
    )

    placed = blocks_titled(solved(week).document, "Gym")

    assert placed[0].interval.total_minutes() == 45


def test_an_occurrence_whose_minimum_does_not_fit_is_not_placed_and_the_gap_stays() -> None:
    """Every gap of this week is fifteen minutes, and the occurrence needs an hour."""
    week = a_week(
        frame=(
            a_frame_entry(day=0, interval=between(0, 8)),
            a_frame_entry(day=0, interval=between(8.25, 24), routine_id=uuid4()),
            *(a_frame_entry(day=day, interval=between(0, 24, day=day)) for day in range(1, 7)),
        ),
        habit_occurrences=(an_occurrence(minutes=60, max_minutes=60),),
        areas=(an_area_budget(target_minutes=600),),
    )

    document = solved(week).document

    assert blocks_titled(document, "Gym") == ()
    assert document.unallocated_minutes == 15


# --------------------------------------------------------------------------------------
# Phase 2: a slot is filled, or it says why it is not. Three refusals, three tests
# --------------------------------------------------------------------------------------


def test_a_slot_whose_areas_content_cannot_take_its_duration_is_not_filled_by_it() -> None:
    """Found by a bite that removed the duration test and reddened nothing: a missing test.

    The slot declares an hour of Career and the Area's only task has fifteen minutes left, which is
    below the minimum chunk it declares, so nothing in the Area can take the hour. Without the
    check the slot would be filled by a fifteen-minute task placed over a sixty-minute span, which
    is a block claiming four times the work it holds.
    """
    week = a_week(
        template_entries=(a_slot(area_id=CAREER, interval=between(18, 19)),),
        eligible_tasks=(
            an_eligible_task(
                remaining_minutes=15,
                min_chunk_minutes=15,
                area_id=CAREER,
                title="Papers",
            ),
        ),
        areas=(an_area_budget(area_id=CAREER, name="Career", target_minutes=600),),
    )

    document = solved(week).document

    assert document.empty_slots[0].reason is EmptySlotReason.NO_ELIGIBLE_CONTENT
    assert all(block.interval != between(18, 19) for block in document.blocks)


def test_a_slot_takes_content_whose_range_covers_its_duration_exactly() -> None:
    # The control for the test above: with the range widened to cover the hour, the slot fills, so
    # what the assertion above measures is the range and not the Area or the span.
    week = a_week(
        template_entries=(a_slot(area_id=CAREER, interval=between(18, 19)),),
        eligible_tasks=(
            an_eligible_task(
                remaining_minutes=60,
                min_chunk_minutes=15,
                area_id=CAREER,
                title="Papers",
            ),
        ),
        areas=(an_area_budget(area_id=CAREER, name="Career", target_minutes=600),),
    )

    assert solved(week).document.empty_slots == ()


def test_a_slot_resolves_to_the_highest_ordered_content_of_its_own_area() -> None:
    week = a_week(
        template_entries=(a_slot(area_id=CAREER, interval=between(18, 19)),),
        eligible_tasks=(
            an_eligible_task(task_id=A_TASK, remaining_minutes=60, area_id=CAREER, title="Papers"),
        ),
        areas=(an_area_budget(area_id=CAREER, name="Career", target_minutes=600),),
    )

    document = solved(week).document
    filled = blocks_titled(document, "Papers")

    assert document.empty_slots == ()
    assert filled[0].interval == between(18, 19)


def test_a_slot_whose_area_has_no_eligible_content_stays_at_its_declared_span() -> None:
    """The first refusal: never shrunk. Its span is exactly what the template declared."""
    week = a_week(
        template_entries=(a_slot(area_id=CAREER, interval=between(18, 19)),),
        areas=(an_area_budget(area_id=CAREER, name="Career"),),
    )

    document = solved(week).document

    assert len(document.empty_slots) == 1
    assert document.empty_slots[0].interval == between(18, 19)
    assert document.empty_slots[0].reason is EmptySlotReason.NO_ELIGIBLE_CONTENT


def test_a_slot_is_never_filled_from_a_different_area() -> None:
    """The second refusal. The backlog holds an hour of Fitness and the slot wants Career."""
    week = a_week(
        template_entries=(a_slot(area_id=CAREER, interval=between(18, 19)),),
        eligible_tasks=(an_eligible_task(remaining_minutes=60, area_id=FITNESS, title="Leetcode"),),
        areas=(
            an_area_budget(area_id=CAREER, name="Career"),
            an_area_budget(area_id=FITNESS, name="Fitness", target_minutes=600),
        ),
    )

    document = solved(week).document
    unfilled = document.empty_slots[0]

    assert unfilled.reason is EmptySlotReason.NO_ELIGIBLE_CONTENT
    assert unfilled.area_id == CAREER
    assert all(block.area_id != CAREER for block in document.blocks)


def test_an_unfilled_slots_span_counts_as_unallocated_rather_than_as_scheduled() -> None:
    """The third refusal, read as arithmetic: nothing pretends the hour was spent."""
    week = a_week(
        template_entries=(a_slot(area_id=CAREER, interval=between(18, 19)),),
        areas=(an_area_budget(area_id=CAREER, name="Career"),),
    )

    document = solved(week).document

    assert document.unallocated_minutes == document.discretionary_minutes


def test_a_slot_inside_a_span_the_user_declared_off_says_so_rather_than_naming_a_constraint() -> (
    None
):
    week = a_week(
        template_entries=(a_slot(area_id=CAREER, interval=between(18, 19)),),
        off_plan=(an_off_plan_period(interval=between(12, 24), label="Rome"),),
        eligible_tasks=(an_eligible_task(remaining_minutes=60, area_id=CAREER, title="Papers"),),
        areas=(an_area_budget(area_id=CAREER, name="Career", target_minutes=600),),
    )

    document = solved(week).document

    assert document.empty_slots[0].reason is EmptySlotReason.OFF_PLAN


def test_a_slot_every_candidate_is_refused_in_names_a_constraint() -> None:
    """A frame occurrence over the slot's span, so the content is eligible and the span is not."""
    week = a_week(
        template_entries=(a_slot(area_id=CAREER, interval=between(18, 19)),),
        frame=(a_frame_entry(day=0, interval=between(17, 20), title="Sleep"),),
        eligible_tasks=(an_eligible_task(remaining_minutes=60, area_id=CAREER, title="Papers"),),
        areas=(an_area_budget(area_id=CAREER, name="Career", target_minutes=600),),
    )

    result = solved(week)

    assert result.document.empty_slots[0].reason is EmptySlotReason.BLOCKED_BY_CONSTRAINT
    assert any(row.rule is ConstraintRule.FRAME_OVERLAP for row in result.blocked_log)


def test_no_solve_ever_leaves_a_slot_saying_nobody_looked_at_the_backlog() -> None:
    """``not_solved`` is materialization's reason, and this phase is the looking."""
    week = a_week(
        template_entries=(a_slot(area_id=CAREER), a_slot(area_id=FITNESS, interval=between(9, 10))),
        areas=(an_area_budget(area_id=CAREER, name="Career"), an_area_budget()),
    )

    document = solved(week).document

    assert len(document.empty_slots) == 2
    assert all(slot.reason is not EmptySlotReason.NOT_SOLVED for slot in document.empty_slots)


def test_a_slot_the_week_has_already_reached_is_left_unbound_and_says_it_has_passed() -> None:
    """Three slots against one clock: Monday's is spent, Wednesday's half spent, Friday's not.

    The straddling slot is what decides where the boundary sits. A slot is never shrunk, so
    binding that one would place a block over the half hour that has gone, which is the same
    minute the packer's own clip already refuses to hand out.
    """
    week = a_week(
        now=NOW,
        template_entries=(
            a_slot(area_id=CAREER, day=0),
            a_slot(area_id=CAREER, day=2, interval=between(8.5, 9.5, day=2)),
            a_slot(area_id=CAREER, day=4),
        ),
        eligible_tasks=(
            an_eligible_task(
                remaining_minutes=180, min_chunk_minutes=60, area_id=CAREER, title="Papers"
            ),
        ),
        areas=(an_area_budget(area_id=CAREER, name="Career", target_minutes=600),),
    )

    attempt = bind_slots(an_attempt(week))

    assert [(slot.interval, slot.reason) for slot in attempt.slots] == [
        (between(18, 19, day=0), EmptySlotReason.ELAPSED),
        (between(8.5, 9.5, day=2), EmptySlotReason.ELAPSED),
    ]
    assert [block.interval for block in attempt.blocks()] == [between(18, 19, day=4)]


def test_a_solve_of_a_week_already_half_lived_places_nothing_it_chose_in_the_past() -> None:
    """One slot a day and a clock at Wednesday morning, so two of the seven cannot be filled.

    Phase 3 clips the gaps it packs to ``now`` and phase 2 now reads the same instant, so no
    part of the solve hands out time the week has spent. What the guard on the plan of record
    refuses is exactly a chosen block the live plan does not already hold in the past, so this
    is that refusal made unreachable rather than caught.
    """
    week = a_week(
        now=NOW,
        template_entries=tuple(a_slot(area_id=CAREER, day=day) for day in range(7)),
        eligible_tasks=(
            an_eligible_task(
                remaining_minutes=300, min_chunk_minutes=60, area_id=CAREER, title="Papers"
            ),
        ),
        areas=(an_area_budget(area_id=CAREER, name="Career", target_minutes=600),),
    )

    document = solved(week).document
    chosen = tuple(block for block in document.blocks if is_placed_by_the_solver(block.origin))

    # The control for the assertion under it, which an empty solve would satisfy on its own.
    assert {between(18, 19, day=day) for day in (2, 3, 4, 5, 6)} <= {
        block.interval for block in chosen
    }
    assert [block.title for block in chosen if block.interval.start < NOW] == []
    assert [(slot.interval, slot.reason) for slot in document.empty_slots] == [
        (between(18, 19, day=0), EmptySlotReason.ELAPSED),
        (between(18, 19, day=1), EmptySlotReason.ELAPSED),
    ]


# --------------------------------------------------------------------------------------
# Phase 3: the gaps, the division, and the log
# --------------------------------------------------------------------------------------


def test_a_task_longer_than_any_gap_is_divided_into_the_pieces_that_fit() -> None:
    """Two two-hour gaps and four hours of work, so the division is decided by the week."""
    week = a_week(
        frame=(
            a_frame_entry(day=0, interval=between(0, 9)),
            a_frame_entry(day=0, interval=between(11, 14), routine_id=uuid4()),
            a_frame_entry(day=0, interval=between(16, 24), routine_id=uuid4()),
            *(a_frame_entry(day=day, interval=between(0, 24, day=day)) for day in range(1, 7)),
        ),
        eligible_tasks=(an_eligible_task(remaining_minutes=240, min_chunk_minutes=60),),
        areas=(an_area_budget(target_minutes=600),),
    )

    document = solved(week).document
    pieces = blocks_titled(document, "Leetcode")

    assert len(pieces) == 2
    assert {piece.split_count for piece in pieces} == {2}
    assert {piece.split_index for piece in pieces} == {0, 1}
    assert minutes_toward(document, A_TASK) == 240


def test_a_task_placed_whole_carries_neither_a_chunk_number_nor_a_count() -> None:
    """One chunk is the whole task, which the domain spells by carrying no number at all."""
    week = a_week(
        eligible_tasks=(an_eligible_task(remaining_minutes=120),),
        areas=(an_area_budget(target_minutes=600),),
    )

    placed = blocks_titled(solved(week).document, "Leetcode")

    assert len(placed) == 1
    assert placed[0].split_index is None
    assert placed[0].split_count is None


def test_a_piece_below_the_minimum_chunk_is_offered_so_the_rule_that_names_it_records_it() -> None:
    """Every gap is thirty minutes and the task cannot be placed in less than fifty."""
    week = _a_week_of_half_hour_gaps()

    result = solved(week)

    assert blocks_titled(result.document, "Papers") == ()
    assert [row.rule for row in result.blocked_log] == [ConstraintRule.BELOW_MIN_CHUNK] * 2


def test_the_log_keeps_two_rows_per_binding_and_no_more() -> None:
    """Two is the clause budget's own figure for rejected windows, so a third could never render."""
    week = _a_week_of_half_hour_gaps()

    result = solved(week)

    assert len(result.blocked_log) == 2
    assert len({row.binding for row in result.blocked_log}) == 1


def _a_week_of_half_hour_gaps() -> SolveInputs:
    """A week whose only discretionary time is four half-hour gaps on the Monday."""
    frame = (
        a_frame_entry(day=0, interval=between(0, 9)),
        a_frame_entry(day=0, interval=between(9.5, 10), routine_id=uuid4()),
        a_frame_entry(day=0, interval=between(10.5, 11), routine_id=uuid4()),
        a_frame_entry(day=0, interval=between(11.5, 12), routine_id=uuid4()),
        a_frame_entry(day=0, interval=between(12.5, 24), routine_id=uuid4()),
        *(
            a_frame_entry(day=day, interval=between(0, 24, day=day), routine_id=uuid4())
            for day in range(1, 7)
        ),
    )
    return a_week(
        frame=frame,
        eligible_tasks=(
            an_eligible_task(
                task_id=ANOTHER_TASK,
                remaining_minutes=120,
                min_chunk_minutes=50,
                area_id=CAREER,
                title="Papers",
                deadline=between(0, 1, day=5).start,
            ),
        ),
        areas=(an_area_budget(area_id=CAREER, name="Career", target_minutes=600),),
    )


def test_nothing_is_placed_before_the_instant_the_assembly_was_stamped_with() -> None:
    """The probe clips its capacity to ``now`` and so does the packer, for the same reason."""
    week = a_week(
        now=between(0, 1, day=3).start,
        eligible_tasks=(an_eligible_task(remaining_minutes=60),),
        areas=(an_area_budget(target_minutes=600),),
    )

    placed = blocks_titled(solved(week).document, "Leetcode")

    assert placed[0].interval.start >= week.now


def test_the_phases_place_the_same_thing_whether_they_run_together_or_apart() -> None:
    """Phase 2 then phase 3, driven directly, reach the plan the entry point's construction does."""
    week = a_week(
        template_entries=(a_slot(area_id=CAREER, interval=between(18, 19)),),
        eligible_tasks=(
            an_eligible_task(task_id=A_TASK, remaining_minutes=120, area_id=CAREER, title="Papers"),
        ),
        areas=(an_area_budget(area_id=CAREER, name="Career", target_minutes=600),),
    )

    apart = fill_gaps(bind_slots(an_attempt(week)), hand_tuned_weights(), budget=QUICK)
    together = solved(week, budget=QUICK)

    assert [block.interval for block in apart.document().blocks] == [
        block.interval for block in together.document.blocks
    ]
