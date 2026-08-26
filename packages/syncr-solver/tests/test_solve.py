"""``solve``: the entry point, and the five properties a produced plan has to hold.

The properties are what the design names as the solver's own test surface, and each is stated over a
week built to be able to fail it. Two of them needed that stated explicitly:

- the determinism property's week HOLDS TIES on every term the comparator reads before its last, so
  a comparator that fell through to arrival order would fail it rather than pass by accident;
- the re-solve property's week holds work a previous solve already placed in UNPINNED blocks, which
  is the arrangement that under-schedules a task permanently if the wrong demand is read.

Every week here has its whole span ahead of ``now`` unless a test is about the clip, so a placement
that did not happen is a refusal rather than an artefact of the past.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from syncr_domain.feasibility import Provenance
from syncr_domain.identity import BindingRef
from syncr_domain.reasons import Pinned, ReasonRecord
from syncr_solver import solve
from syncr_solver.budget import SolveBudget
from syncr_solver.derivation import shadow_blocks
from tests.materialized_weeks import (
    CAREER,
    FITNESS,
    WEEK,
    a_block,
    a_concrete_entry,
    a_frame_entry,
    a_live_plan,
    a_pin,
    a_prep_block,
    a_recovery_window,
    a_slot,
    a_transit_block,
    an_anchor,
    an_area_budget,
    an_off_plan_period,
    between,
)
from tests.objective_weeks import (
    A_TASK,
    ANOTHER_HABIT,
    ANOTHER_TASK,
    a_chunk_block,
    a_preference,
    a_window,
    an_eligible_task,
    an_occurrence,
    hand_tuned_weights,
)
from tests.solve_weeks import QUICK, a_week, blocks_titled, minutes_toward, solved

if TYPE_CHECKING:
    from syncr_domain.plan import PlanDocument
    from syncr_solver.inputs import SolveInputs

# Every field of `SolveInputs` that holds a list whose order must not matter. Named rather than
# derived from the dataclass, so a field added to the struct fails the crossing below until someone
# decides whether its order is observable.
ORDERED_FIELDS = (
    "frame",
    "frame_overhang",
    "anchors",
    "shadow_blocks",
    "forbidden_windows",
    "off_plan",
    "template_entries",
    "habit_occurrences",
    "eligible_tasks",
    "areas",
    "preferences",
    "pins",
    "deadline_demands",
    "adjustments",
)


def a_week_with_ties(**overrides: Any) -> SolveInputs:
    """A week whose candidates tie on every term the comparator reads before its last.

    Two occurrences of one habit tie on all four priorities and separate only on the occurrence key.
    Two tasks of one Area with the same deadline and no floors tie until the entity identifier. Two
    Areas with equal floors and equal targets tie on the first term. So a comparator that fell
    through to arrival order would produce two different plans from two orders of these lists, which
    is exactly what the permutation property is for.
    """
    stated: dict[str, Any] = {
        "frame": (
            a_frame_entry(day=0, interval=between(23, 31)),
            a_frame_entry(day=1, interval=between(23, 31)),
        ),
        "anchors": (an_anchor(interval=between(10, 11, day=1)),),
        "shadow_blocks": (
            a_prep_block(interval=between(9, 10, day=1)),
            a_transit_block(interval=between(11, 11.5, day=1)),
        ),
        "forbidden_windows": (a_recovery_window(interval=between(11.5, 12.5, day=1)),),
        "template_entries": (
            a_concrete_entry(day=2, interval=between(6.75, 7, day=2)),
            a_slot(day=3, area_id=CAREER, interval=between(18, 19, day=3)),
        ),
        "habit_occurrences": (
            an_occurrence(index=0, minutes=60),
            an_occurrence(index=1, minutes=60),
            an_occurrence(habit_id=ANOTHER_HABIT, index=0, minutes=45, area_id=CAREER),
        ),
        "eligible_tasks": (
            an_eligible_task(
                task_id=A_TASK,
                remaining_minutes=120,
                area_id=CAREER,
                title="Papers",
                deadline=between(9, 10, day=4).start,
            ),
            an_eligible_task(
                task_id=ANOTHER_TASK,
                remaining_minutes=120,
                area_id=CAREER,
                title="Notes",
                deadline=between(9, 10, day=4).start,
            ),
        ),
        "areas": (
            an_area_budget(area_id=FITNESS, name="Fitness", floor_minutes=60, target_minutes=300),
            an_area_budget(area_id=CAREER, name="Career", floor_minutes=60, target_minutes=300),
        ),
        "preferences": (
            a_preference(owner_id=FITNESS, windows=(a_window(7, 9, day=2),)),
            a_preference(owner_id=CAREER, windows=(a_window(14, 18, day=3),)),
        ),
    }
    stated.update(overrides)
    return a_week(**stated)


def permuted(week: SolveInputs, order: tuple[int, ...]) -> SolveInputs:
    """This week with every one of its lists reordered by ``order``, and nothing else changed.

    ``order`` is a permutation of the positions a list can hold, applied by dropping the positions
    a shorter list does not have. Every list this week holds is at most as long as ``order``, which
    the control below asserts, so each is genuinely permuted rather than partly reordered.
    """
    changed: dict[str, Any] = {}
    for field in ORDERED_FIELDS:
        held = getattr(week, field)
        changed[field] = tuple(held[index] for index in order if index < len(held))
    reordered = {day: week.zone_by_date[day] for day in reversed(week.iso_week.dates())}
    return replace(week, zone_by_date=reordered, **changed)


def canonical(document: PlanDocument) -> str:
    """One document as text, so two of them are compared byte for byte rather than by equality."""
    return repr(document)


# --------------------------------------------------------------------------------------
# The entry point and what it answers with
# --------------------------------------------------------------------------------------


def test_the_result_carries_the_plan_its_cost_the_verdict_and_the_refusals() -> None:
    result = solved(a_week_with_ties())

    assert result.document.blocks
    assert result.objective_breakdown.total() > 0
    assert result.verdict.provenance is Provenance.SOLVER
    assert result.verdict.input_version == a_week_with_ties().input_version
    assert result.verdict.computed_at == a_week_with_ties().now


def test_the_first_phase_is_materialize_so_a_solve_holds_every_derived_block() -> None:
    """Phase 1 is the same function forever, so what it places a solve places unchanged."""
    from syncr_solver import materialize
    from syncr_solver.metrics import MaterializeCause

    week = a_week_with_ties()
    derived = materialize(week, cause=MaterializeCause.PHASE1)
    solved_document = solved(week).document

    for block in derived.blocks:
        assert block.id in solved_document.blocks_by_id(), block.title


def test_a_solve_leaves_the_forbidden_windows_the_week_declared() -> None:
    week = a_week_with_ties()

    assert solved(week).document.forbidden_windows == week.forbidden_windows


# --------------------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------------------


def test_solving_the_same_inputs_twice_yields_byte_identical_documents() -> None:
    week = a_week_with_ties()

    first = solve(week, hand_tuned_weights(), budget=QUICK)
    second = solve(week, hand_tuned_weights(), budget=QUICK)

    assert canonical(first.document) == canonical(second.document)
    assert first.objective_breakdown == second.objective_breakdown
    assert first.iterations == second.iterations


@given(order=st.permutations(range(3)))
@settings(max_examples=20, deadline=None, derandomize=True)
def test_permuting_the_order_of_every_input_list_changes_nothing(order: list[int]) -> None:
    """Over a week that HOLDS ties, so a comparator falling through to arrival order fails here."""
    week = a_week_with_ties()

    expected = solve(week, hand_tuned_weights(), budget=QUICK)
    found = solve(permuted(week, tuple(order)), hand_tuned_weights(), budget=QUICK)

    assert canonical(found.document) == canonical(expected.document)
    assert found.iterations == expected.iterations


def test_the_permutation_really_reorders_the_lists_it_claims_to() -> None:
    # The control for the property above. A permutation that changed nothing would make it a test
    # that solving one week twice agrees, which the test above already is.
    week = a_week_with_ties()
    reversed_week = permuted(week, (2, 1, 0))

    assert reversed_week.habit_occurrences != week.habit_occurrences
    assert reversed_week.eligible_tasks != week.eligible_tasks
    assert list(reversed_week.zone_by_date) != list(week.zone_by_date)
    assert set(reversed_week.habit_occurrences) == set(week.habit_occurrences)


def test_every_list_the_permutation_reorders_is_a_field_the_struct_holds() -> None:
    # The other control: a field renamed on the struct would leave the property silently reordering
    # nothing at all, and a list longer than the permutation would be only partly reordered.
    week = a_week_with_ties()

    for field in ORDERED_FIELDS:
        held = getattr(week, field)
        assert isinstance(held, tuple), field
        assert len(held) <= 3, field


def test_the_same_inputs_consume_the_same_number_of_iterations() -> None:
    """Which is what makes the bounded budget a contract rather than a wall-clock accident."""
    week = a_week_with_ties()
    counted = {solve(week, hand_tuned_weights(), budget=QUICK).iterations for _ in range(3)}

    assert len(counted) == 1


# --------------------------------------------------------------------------------------
# Pins, and off-plan spans
# --------------------------------------------------------------------------------------


def test_every_pin_in_the_input_appears_at_exactly_its_interval_in_the_output() -> None:
    week = a_week_with_ties(
        pins=(
            a_pin(binding=BindingRef.for_task(A_TASK), interval=between(15, 16, day=5)),
            a_pin(
                binding=BindingRef.for_habit(ANOTHER_HABIT, index=0),
                interval=between(8, 8.75, day=6),
            ),
        )
    )

    held = solved(week).document.blocks

    for pin in week.pins:
        assert any(
            block.binding == pin.binding and block.interval == pin.interval for block in held
        ), pin.binding


def test_a_pin_on_a_block_derivation_determined_outranks_the_span_derivation_chose() -> None:
    """Which is how a longer-than-usual commute is expressed."""
    anchor = an_anchor(interval=between(10, 11, day=1))
    transit = a_transit_block(anchor_id=anchor.anchor_id, interval=between(9.5, 10, day=1))
    week = a_week(
        anchors=(anchor,),
        shadow_blocks=(transit,),
        pins=(a_pin(binding=transit.binding, interval=between(8, 9.5, day=1)),),
        areas=(an_area_budget(area_id=CAREER, name="Career", target_minutes=300),),
    )

    placed = blocks_titled(solved(week).document, "Leave for Uni")

    assert placed[0].interval == between(8, 9.5, day=1)


def test_a_pin_naming_content_the_week_holds_nowhere_is_refused_rather_than_dropped() -> None:
    from syncr_solver.errors import SolveError

    week = a_week(pins=(a_pin(binding=BindingRef.for_habit(uuid4(), index=3)),))

    with pytest.raises(SolveError, match="names content this week does not hold"):
        solved(week)


def test_a_pin_on_a_binding_derivation_refused_is_honored_at_the_interval_the_user_chose() -> None:
    """A buffer whose span its own commitment spent is refused by materialization yet still held.

    The week holds the content: the buffer is in the inputs and only its span was refused. So the
    pin is honored by lookup across the four collections that spell a derived block, at the
    interval the user chose rather than at the refused one -- and no operation fails claiming the
    solver raised.
    """
    anchor = an_anchor(interval=between(10, 11, day=1))
    transit = a_transit_block(anchor_id=anchor.anchor_id, interval=between(9.5, 11, day=1))
    pin_interval = between(8, 9.5, day=2)
    week = a_week(
        anchors=(anchor,),
        shadow_blocks=(transit,),
        pins=(a_pin(binding=transit.binding, interval=pin_interval),),
        areas=(an_area_budget(area_id=CAREER, name="Career", target_minutes=300),),
    )

    placed = blocks_titled(solved(week).document, "Leave for Uni")

    assert [block.interval for block in placed] == [pin_interval]


def test_the_pinned_block_derivation_refused_carries_derivations_own_bound_clause() -> None:
    """Which is what makes the lookup a reuse of derivation rather than a second spelling of it."""
    anchor = an_anchor(interval=between(10, 11, day=1))
    transit = a_transit_block(anchor_id=anchor.anchor_id, interval=between(9.5, 11, day=1))
    pin_interval = between(8, 9.5, day=2)
    week = a_week(
        anchors=(anchor,),
        shadow_blocks=(transit,),
        pins=(a_pin(binding=transit.binding, interval=pin_interval),),
    )

    placed = blocks_titled(solved(week).document, "Leave for Uni")
    (built,) = shadow_blocks((transit,), iso_week=WEEK)

    # The document appends the pin's own clause to every pinned block, so the expected reason is
    # derivation's clauses plus that one clause, spelled in full rather than stripped out of the
    # comparison: every field, including the reason, is asserted against an expected value.
    assert placed[0] == replace(
        built,
        interval=pin_interval,
        reason=ReasonRecord((*built.reason.clauses, Pinned(pin_interval, week.pins[0].pinned_on))),
    )


def test_a_pin_on_a_concrete_template_entry_derivation_refused_is_honored_too() -> None:
    """The lookup spans all four collections, so a refused entry is not a second way to fail."""
    anchor = an_anchor(interval=between(10, 11, day=1))
    entry = a_concrete_entry(day=1, interval=between(10, 11.25, day=1))
    pin_interval = between(8, 8.25, day=3)
    week = a_week(
        anchors=(anchor,),
        template_entries=(entry,),
        pins=(a_pin(binding=entry.block_binding, interval=pin_interval),),
    )

    placed = blocks_titled(solved(week).document, "Shower")

    assert [block.interval for block in placed] == [pin_interval]


def test_a_pin_naming_a_slot_still_raises_slots_bind_late_and_name_no_content() -> None:
    """A slot names no content, so the week holds nothing at all for a pin naming one."""
    from syncr_solver.errors import SolveError

    slot = a_slot(day=3)
    week = a_week(
        template_entries=(slot,),
        pins=(a_pin(binding=slot.block_binding, interval=between(9, 10, day=4)),),
    )

    with pytest.raises(SolveError, match="names content this week does not hold"):
        solved(week)


def test_no_block_the_user_did_not_pin_lands_inside_an_off_plan_span() -> None:
    off_plan = an_off_plan_period(interval=between(0, 24, day=5), label="Rome")
    week = a_week_with_ties(off_plan=(off_plan,))

    document = solved(week).document

    for block in document.blocks:
        assert not block.interval.overlaps(off_plan.interval), block.title


def test_a_pin_inside_an_off_plan_span_is_the_one_thing_that_survives_it() -> None:
    """Which is how "off, except this one thing" is expressed, and why the span needs no control."""
    off_plan = an_off_plan_period(interval=between(0, 24, day=5), label="Rome")
    week = a_week_with_ties(
        off_plan=(off_plan,),
        pins=(a_pin(binding=BindingRef.for_task(A_TASK), interval=between(15, 16, day=5)),),
    )

    inside = [
        block
        for block in solved(week).document.blocks
        if block.interval.overlaps(off_plan.interval)
    ]

    assert [block.interval for block in inside] == [between(15, 16, day=5)]


# --------------------------------------------------------------------------------------
# A re-solve never shrinks the work
# --------------------------------------------------------------------------------------


def a_week_holding_two_unpinned_hours_of_a_four_hour_task() -> SolveInputs:
    """The arrangement that permanently under-schedules a task if the probe's demand is read.

    ``remaining_minutes`` is 240, which is the SOLVER's quantity: the two hours the previous solve
    placed are unpinned and in the future, so nothing nets them and the solver re-places them. The
    probe's own demand for the same week is 120, and reading THAT here would place two hours,
    report nothing wrong, and do it again on every re-solve.
    """
    task = an_eligible_task(
        task_id=A_TASK, remaining_minutes=240, min_chunk_minutes=60, area_id=CAREER, title="Papers"
    )
    return a_week(
        eligible_tasks=(task,),
        areas=(an_area_budget(area_id=CAREER, name="Career", target_minutes=600),),
        live_plan=a_live_plan(
            a_chunk_block(
                task_id=A_TASK,
                index=0,
                of=2,
                interval=between(10, 11, day=3),
                title="Papers",
                area_id=CAREER,
            ),
            a_chunk_block(
                task_id=A_TASK,
                index=1,
                of=2,
                interval=between(10, 11, day=4),
                title="Papers",
                area_id=CAREER,
            ),
        ),
    )


def test_a_task_with_four_hours_left_and_two_placed_unpinned_re_solves_to_four() -> None:
    week = a_week_holding_two_unpinned_hours_of_a_four_hour_task()

    assert minutes_toward(solved(week).document, A_TASK) == 240


def test_re_solving_repeatedly_leaves_the_total_placed_minutes_unchanged() -> None:
    week = a_week_holding_two_unpinned_hours_of_a_four_hour_task()

    placed = [minutes_toward(solved(week).document, A_TASK) for _ in range(3)]

    assert placed == [240, 240, 240]


def test_a_pinned_hour_reduces_the_work_still_to_place_and_stays_in_the_document() -> None:
    """The exception: a pin cannot move, so the pin IS part of the total.

    The assembler nets a pin out of ``remaining_minutes``, so the demand here is 180 and the plan
    holds 240: three fresh hours plus the pinned one.
    """
    pinned = a_block(
        binding=BindingRef.for_task(A_TASK),
        interval=between(10, 11, day=3),
        title="Papers",
        area_id=CAREER,
    )
    week = a_week(
        eligible_tasks=(
            an_eligible_task(
                task_id=A_TASK,
                remaining_minutes=180,
                min_chunk_minutes=60,
                area_id=CAREER,
                title="Papers",
            ),
        ),
        areas=(an_area_budget(area_id=CAREER, name="Career", target_minutes=600),),
        live_plan=a_live_plan(pinned),
        pins=(a_pin(binding=pinned.binding, interval=pinned.interval),),
    )

    document = solved(week).document

    assert minutes_toward(document, A_TASK) == 240
    assert any(block.interval == pinned.interval for block in document.blocks)


def test_a_block_that_has_begun_stays_where_it_is_and_counts_toward_the_total() -> None:
    """The other half of the exception: the moment has passed, so the solver cannot move it."""
    begun = a_block(
        binding=BindingRef.for_task(A_TASK),
        interval=between(8, 9, day=0),
        title="Papers",
        area_id=CAREER,
    )
    week = a_week(
        now=between(12, 13, day=0).start,
        eligible_tasks=(
            an_eligible_task(
                task_id=A_TASK,
                remaining_minutes=180,
                min_chunk_minutes=60,
                area_id=CAREER,
                title="Papers",
            ),
        ),
        areas=(an_area_budget(area_id=CAREER, name="Career", target_minutes=600),),
        live_plan=a_live_plan(begun),
    )

    document = solved(week).document

    assert any(block.interval == begun.interval for block in document.blocks)
    assert minutes_toward(document, A_TASK) == 240


def test_a_solve_never_places_work_over_a_span_a_block_that_has_begun_already_holds() -> None:
    """H4 measures over what the state holds, and a solve seeds it."""
    begun = a_block(
        binding=BindingRef.for_habit(ANOTHER_HABIT, index=0),
        interval=between(8, 12, day=0),
        title="Gym",
        area_id=FITNESS,
    )
    week = a_week(
        now=between(9, 10, day=0).start,
        eligible_tasks=(
            an_eligible_task(remaining_minutes=180, area_id=FITNESS, title="Leetcode"),
        ),
        areas=(an_area_budget(target_minutes=600),),
        live_plan=a_live_plan(begun),
    )

    document = solved(week).document

    for block in document.blocks:
        if block.binding == begun.binding:
            continue
        assert not block.interval.overlaps(begun.interval), block.title


def test_a_day_whose_cap_is_already_met_by_pinned_work_refuses_more_of_that_area() -> None:
    """The safe half: H8 measures over what the state holds too, so the seeding completes it."""
    pinned = a_block(
        binding=BindingRef.for_task(A_TASK),
        interval=between(14, 15, day=2),
        title="Papers",
        area_id=CAREER,
    )
    week = a_week(
        eligible_tasks=(
            an_eligible_task(task_id=A_TASK, remaining_minutes=60, area_id=CAREER, title="Papers"),
            an_eligible_task(
                task_id=ANOTHER_TASK, remaining_minutes=60, area_id=CAREER, title="Notes"
            ),
        ),
        areas=(
            an_area_budget(
                area_id=CAREER, name="Career", target_minutes=600, max_per_day_minutes=60
            ),
        ),
        live_plan=a_live_plan(pinned),
        pins=(a_pin(binding=pinned.binding, interval=pinned.interval),),
    )

    document = solved(week).document
    on_that_day = [
        block
        for block in document.blocks
        if block.area_id == CAREER and block.interval.overlaps(between(0, 24, day=2))
    ]

    assert [block.interval for block in on_that_day] == [pinned.interval]


# --------------------------------------------------------------------------------------
# The budget, and the cancellation checkpoint
# --------------------------------------------------------------------------------------


def test_a_smaller_budget_produces_a_legal_plan_rather_than_a_partial_one() -> None:
    week = a_week_with_ties()

    stopped = SolveBudget(scored_windows=1, move_evaluations=0)
    tight = solve(week, hand_tuned_weights(), budget=stopped)
    generous = solve(week, hand_tuned_weights(), budget=QUICK)

    assert tight.iterations == 0
    assert tight.document.blocks
    assert generous.objective_breakdown.total() <= tight.objective_breakdown.total()


def test_a_solve_cancelled_after_construction_spends_no_move_and_still_costs_its_plan() -> None:
    week = a_week_with_ties()

    stopped = solve(week, hand_tuned_weights(), budget=QUICK, cancelled=lambda: True)

    assert stopped.iterations == 0
    assert stopped.document.blocks
    assert stopped.objective_breakdown.total() > 0
