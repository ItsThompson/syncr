"""The candidate and the state: the pairing a candidate owes, the three indexes, and the orders.

Two kinds of test. The pairing and the indexes are behaviour: what the state answers about a binding
decides whether three of the thirteen rules can fire at all, so each index is driven at the case it
was built for and at the case it must not claim.

The ordering tests are about determinism rather than legality. Each collection is sorted so a
candidate overlapping two members names the earlier one whatever order the inputs arrived in, and
that holds only while a key can separate two unequal values.
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta
from uuid import UUID

import pytest

from syncr_domain.gaps import ForbiddenScope
from syncr_domain.identity import BindingRef, TransitLeg
from syncr_domain.plan import PlanError
from syncr_solver.state import (
    FIXED_BY_DERIVATION,
    PINNED,
    UNNAMED_PIN,
    PartialPlan,
    Placement,
    Sizing,
)
from tests.materialized_weeks import (
    CAREER,
    FITNESS,
    NOW,
    WEEK_MINUTES,
    a_block,
    a_candidate,
    a_concrete_entry,
    a_frame_entry,
    a_live_plan,
    a_pin,
    a_prep_block,
    a_recovery_window,
    a_sizing,
    a_slot,
    a_transit_block,
    an_anchor,
    an_area_budget,
    an_off_plan_period,
    between,
    inputs,
)

A_TASK_ID = UUID("00000000-0000-4000-8000-0000000000aa")
A_HABIT_ID = UUID("00000000-0000-4000-8000-0000000000ab")

AN_ANCHOR_ID = UUID("00000000-0000-4000-8000-0000000000bb")
ANOTHER_ANCHOR_ID = UUID("00000000-0000-4000-8000-0000000000cc")


# --------------------------------------------------------------------------------
# A candidate states how much of its demand it places, for exactly the two kinds that choose
# --------------------------------------------------------------------------------


def test_a_task_and_an_occurrence_each_state_a_sizing() -> None:
    task = a_candidate(binding=BindingRef.for_task(A_TASK_ID))
    occurrence = a_candidate(binding=BindingRef.for_habit(A_HABIT_ID, index=0))

    assert task.sizing is not None
    assert occurrence.sizing is not None


@pytest.mark.parametrize(
    "binding",
    [
        BindingRef.for_task(A_TASK_ID),
        BindingRef.for_habit(A_HABIT_ID, index=0),
    ],
    ids=["task", "habit"],
)
def test_a_candidate_whose_size_the_solver_chose_cannot_arrive_without_it(
    binding: BindingRef,
) -> None:
    # Without the sizing both rules about how small a block may be would pass over it, which is a
    # rule that cannot fire rather than a rule that found nothing.
    with pytest.raises(PlanError, match="how much of its demand"):
        Placement(binding=binding, interval=between(10, 11), title="Leetcode", area_id=FITNESS)


@pytest.mark.parametrize(
    "binding",
    [
        BindingRef.for_anchor(AN_ANCHOR_ID),
        BindingRef.for_anchor_prep(AN_ANCHOR_ID),
        BindingRef.for_anchor_transit(AN_ANCHOR_ID, leg=TransitLeg.OUT),
        BindingRef.for_routine(UUID(int=3), on=between(0, 1).start.date()),
        BindingRef.for_template_entry(UUID(int=4), on=between(0, 1).start.date()),
    ],
    ids=["anchor", "prep", "transit", "routine", "template_entry"],
)
def test_a_candidate_derivation_sized_cannot_claim_a_choice_nobody_made(
    binding: BindingRef,
) -> None:
    with pytest.raises(PlanError, match="states no sizing"):
        Placement(
            binding=binding,
            interval=between(10, 11),
            title="Interview prep",
            area_id=CAREER,
            sizing=a_sizing(),
        )


def test_the_two_kinds_that_carry_a_sizing_are_the_two_the_solver_sizes() -> None:
    # Bounded by the inventory of binding kinds rather than by the two anyone listed: an eighth kind
    # fails one of the two parametrized suites above until it is placed on a side.
    sized = {BindingRef.for_task(A_TASK_ID).kind, BindingRef.for_habit(A_HABIT_ID, index=0).kind}
    derived = {
        BindingRef.for_anchor(AN_ANCHOR_ID).kind,
        BindingRef.for_anchor_prep(AN_ANCHOR_ID).kind,
        BindingRef.for_anchor_transit(AN_ANCHOR_ID, leg=TransitLeg.OUT).kind,
        BindingRef.for_routine(UUID(int=3), on=between(0, 1).start.date()).kind,
        BindingRef.for_template_entry(UUID(int=4), on=between(0, 1).start.date()).kind,
    }

    assert sized | derived == set(type(next(iter(sized))))
    assert not sized & derived


@pytest.mark.parametrize(
    ("whole", "chunk"), [(0, 15), (60, 0), (-30, 15)], ids=["no-whole", "no-chunk", "negative"]
)
def test_a_sizing_counts_minutes_so_neither_figure_is_below_one(whole: int, chunk: int) -> None:
    with pytest.raises(PlanError, match="counts the minutes"):
        Sizing(whole_minutes=whole, min_chunk_minutes=chunk, splittable=True)


# --------------------------------------------------------------------------------
# The index of what has begun, which is decided against the instant the assembly was stamped with
# --------------------------------------------------------------------------------


def test_a_block_that_has_started_is_indexed_and_one_that_has_not_is_left_out() -> None:
    # `now` is Wednesday 09:00, so Monday's block is behind it and Friday's is ahead.
    started = a_block(binding=BindingRef.for_task(UUID(int=1)), interval=between(8, 10))
    later = a_block(binding=BindingRef.for_task(UUID(int=2)), interval=between(14, 15, day=4))

    state = PartialPlan.of(inputs(live_plan=a_live_plan(started, later)))

    assert set(state.started) == {started.binding}
    assert state.started[started.binding].interval == between(8, 10)


def test_a_block_beginning_exactly_at_the_stamped_instant_has_started() -> None:
    # The boundary the whole rule turns on. `now` is Wednesday 09:00, so a block opening then is
    # under way and one opening a minute later is not.
    opening = a_block(binding=BindingRef.for_task(UUID(int=1)), interval=between(9, 10, day=2))
    after = a_block(
        binding=BindingRef.for_task(UUID(int=2)),
        interval=between(9.25, 10, day=2),
    )

    state = PartialPlan.of(inputs(live_plan=a_live_plan(opening, after)))

    assert opening.binding in state.started
    assert after.binding not in state.started


def test_re_stamping_the_assembly_changes_which_blocks_have_begun() -> None:
    # The rule has no reference instant of its own: it reads the one the assembler stamped, so an
    # assembly is reproducible and a caller can assemble against a past instant.
    block = a_block(binding=BindingRef.for_task(UUID(int=1)), interval=between(14, 15, day=4))
    week = inputs(live_plan=a_live_plan(block))

    assert block.binding not in PartialPlan.of(week).started
    assert (
        block.binding
        in PartialPlan.of(dataclasses.replace(week, now=NOW + timedelta(days=3))).started
    )


# --------------------------------------------------------------------------------
# The index of what may not move, in both senses of immovable
# --------------------------------------------------------------------------------


def test_every_shape_derivation_determines_is_held_at_the_span_it_determined() -> None:
    entry = a_frame_entry(interval=between(23, 31), title="Sleep")
    anchor = an_anchor(interval=between(10, 11))
    prep = a_prep_block(anchor_id=anchor.anchor_id, interval=between(8, 9))
    concrete = a_concrete_entry(interval=between(6.75, 7))

    state = PartialPlan.of(
        inputs(
            frame=(entry,),
            anchors=(anchor,),
            shadow_blocks=(prep,),
            template_entries=(concrete,),
        )
    )

    assert {binding: held.interval for binding, held in state.immovable.items()} == {
        entry.block_binding: between(23, 31),
        BindingRef.for_anchor(anchor.anchor_id): between(10, 11),
        prep.binding: between(8, 9),
        concrete.block_binding: between(6.75, 7),
    }
    assert all(held.detail.endswith(FIXED_BY_DERIVATION) for held in state.immovable.values())


def test_a_slot_holds_no_block_yet_so_nothing_of_it_is_held() -> None:
    # Its span is declared and its content binds late, so there is no block to be held anywhere.
    state = PartialPlan.of(inputs(template_entries=(a_slot(),)))

    assert state.immovable == {}


def test_a_pin_is_held_at_the_interval_the_user_chose_and_names_that_sense() -> None:
    pinned = BindingRef.for_task(UUID(int=1))
    week = inputs(
        pins=(a_pin(binding=pinned, interval=between(13, 14)),),
        live_plan=a_live_plan(a_block(binding=pinned, interval=between(10, 11), title="Gym")),
    )

    state = PartialPlan.of(week)

    assert state.immovable[pinned].interval == between(13, 14)
    assert state.immovable[pinned].detail == f"Gym, {PINNED}"


def test_a_pin_the_week_has_no_block_for_still_says_what_it_is() -> None:
    # A pin is a placement rather than content, so a week whose plan does not hold the block has
    # nothing to call it. It is named as the user's own edit rather than left unexplained.
    pinned = BindingRef.for_task(UUID(int=1))

    state = PartialPlan.of(inputs(pins=(a_pin(binding=pinned, interval=between(13, 14)),)))

    assert state.immovable[pinned].detail == f"{UNNAMED_PIN}, {PINNED}"


def test_a_pin_outranks_the_span_derivation_chose_for_the_same_binding() -> None:
    # A prep or transit block is fixed by derivation, and the user may still pin one elsewhere,
    # which is how a longer-than-usual commute is expressed. Composed the other way that pin would
    # be refused for not being where it was derived.
    transit = a_transit_block(anchor_id=AN_ANCHOR_ID, interval=between(9.5, 10))

    state = PartialPlan.of(
        inputs(
            shadow_blocks=(transit,),
            pins=(a_pin(binding=transit.binding, interval=between(9, 10)),),
        )
    )

    assert state.immovable[transit.binding].interval == between(9, 10)
    assert state.immovable[transit.binding].detail == f"Leave for Uni, {PINNED}"


def test_the_pins_index_holds_the_users_own_placements_and_nothing_derivation_fixed() -> None:
    # Two rules except the user's own placement rather than every immovable one, so the two indexes
    # answer different questions and are not one with a flag.
    transit = a_transit_block(anchor_id=AN_ANCHOR_ID, interval=between(9.5, 10))
    pinned = BindingRef.for_task(UUID(int=1))

    state = PartialPlan.of(
        inputs(shadow_blocks=(transit,), pins=(a_pin(binding=pinned, interval=between(13, 14)),))
    )

    assert state.pins == {pinned: between(13, 14)}
    assert set(state.immovable) == {transit.binding, pinned}


# --------------------------------------------------------------------------------
# What the state reads about the week itself
# --------------------------------------------------------------------------------


def test_the_claimable_time_is_the_week_less_the_four_spans_no_area_can_claim() -> None:
    week = inputs(
        frame=(a_frame_entry(interval=between(1, 2)),),
        anchors=(an_anchor(interval=between(3, 4)),),
        forbidden_windows=(a_recovery_window(interval=between(5, 6)),),
        off_plan=(an_off_plan_period(interval=between(7, 8)),),
    )

    assert PartialPlan.of(week).discretionary().total_minutes() == WEEK_MINUTES - 4 * 60


def test_a_window_scoped_to_named_areas_stays_claimable_because_another_area_may_take_it() -> None:
    scoped = a_recovery_window(
        interval=between(5, 6), scope=ForbiddenScope.AREAS, forbidden_area_ids=(FITNESS,)
    )

    assert (
        PartialPlan.of(inputs(forbidden_windows=(scoped,))).discretionary().total_minutes()
        == WEEK_MINUTES
    )


def test_the_week_is_seven_local_days_the_state_can_measure_a_daily_cap_on() -> None:
    days = PartialPlan.of(inputs()).days

    assert [day.interval.total_minutes() for day in days] == [24 * 60] * 7


def test_placing_something_carries_every_field_of_the_state_forward() -> None:
    # A field added to the state and not carried here would leave the rule that reads it judging an
    # empty collection from the second candidate onwards.
    state = PartialPlan.of(
        inputs(
            frame=(a_frame_entry(),),
            anchors=(an_anchor(),),
            forbidden_windows=(a_recovery_window(),),
            off_plan=(an_off_plan_period(interval=between(7, 8)),),
            areas=(an_area_budget(),),
            frame_overhang=(between(0, 1),),
            pins=(a_pin(interval=between(13, 14)),),
        )
    )

    after = state.with_placed(a_candidate(between(16, 17)))

    unchanged = {
        field.name: getattr(state, field.name)
        for field in dataclasses.fields(state)
        if field.name != "placed"
    }
    assert {name: getattr(after, name) for name in unchanged} == unchanged
    assert len(after.placed) == 1
