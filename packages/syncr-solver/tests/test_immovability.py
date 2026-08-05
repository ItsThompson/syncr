"""H10, H11 and H12: what the solver may not move, and what it may not intrude on.

H10 and H11 are refusals to MOVE, so each is driven twice over the same week: once with the
candidate where the week already holds it, which must be accepted, and once with it somewhere else,
which must be refused. A suite that only ever offers the moved case would pass against a rule that
refuses every candidate of a held binding, including the one preserving it.

H12's exception is the user's own placement, and it is read from the pin rather than from H11 having
already run, so the rejection is driven with the rules in isolation.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from syncr_domain.identity import BindingRef
from syncr_domain.intervals import Interval
from syncr_solver.constraints import ConstraintRule
from syncr_solver.immovability import UNNAMED_OFF_PLAN, immovable_block, off_plan, past_block
from syncr_solver.state import FIXED_BY_DERIVATION, PINNED, PartialPlan
from tests.materialized_weeks import (
    CAREER,
    a_block,
    a_candidate,
    a_concrete_entry,
    a_frame_entry,
    a_live_plan,
    a_pin,
    a_transit_block,
    an_anchor,
    an_off_plan_period,
    at,
    between,
    inputs,
)

GYM = BindingRef.for_task(UUID(int=21))
READING = BindingRef.for_task(UUID(int=22))
AN_ANCHOR_ID = UUID("00000000-0000-4000-8000-0000000000bb")


# --------------------------------------------------------------------------------
# H10: a block that has begun
# --------------------------------------------------------------------------------


def test_a_block_that_has_begun_may_not_be_placed_anywhere_else() -> None:
    week = inputs(live_plan=a_live_plan(a_block(binding=GYM, interval=between(8, 9), title="Gym")))

    rejection = past_block(a_candidate(between(14, 15), binding=GYM), PartialPlan.of(week))

    assert rejection is not None
    assert (rejection.rule, rejection.window, rejection.detail) == (
        ConstraintRule.PAST_BLOCK,
        between(14, 15),
        "Gym",
    )


def test_a_block_that_has_begun_is_accepted_exactly_where_it_already_is() -> None:
    # The rule is a refusal to move rather than a refusal to place: the candidate preserving the
    # placement is the one a re-solve has to produce.
    week = inputs(live_plan=a_live_plan(a_block(binding=GYM, interval=between(8, 9), title="Gym")))

    assert past_block(a_candidate(between(8, 9), binding=GYM), PartialPlan.of(week)) is None


def test_a_block_still_ahead_of_the_stamped_instant_may_be_moved() -> None:
    # The whole point of the split between the two demand quantities: the solver discards and
    # re-places an unpinned future block, so refusing that here would freeze every week.
    week = inputs(
        live_plan=a_live_plan(a_block(binding=GYM, interval=between(14, 15, day=4), title="Gym"))
    )

    assert past_block(a_candidate(between(10, 11), binding=GYM), PartialPlan.of(week)) is None


def test_a_week_with_no_plan_yet_holds_no_block_anywhere() -> None:
    assert past_block(a_candidate(between(10, 11), binding=GYM), PartialPlan.of(inputs())) is None


def test_a_different_binding_is_not_the_block_that_has_begun() -> None:
    # The index is by content identity, so one task's past block does not freeze another's.
    week = inputs(live_plan=a_live_plan(a_block(binding=GYM, interval=between(8, 9), title="Gym")))

    assert past_block(a_candidate(between(14, 15), binding=READING), PartialPlan.of(week)) is None


# --------------------------------------------------------------------------------
# H11: both senses of immovable
# --------------------------------------------------------------------------------


def test_a_pinned_block_may_not_be_placed_anywhere_but_where_the_user_put_it() -> None:
    week = inputs(
        pins=(a_pin(binding=GYM, interval=between(13, 14)),),
        live_plan=a_live_plan(a_block(binding=GYM, interval=between(13, 14), title="Gym")),
    )

    moved = immovable_block(a_candidate(between(10, 11), binding=GYM), PartialPlan.of(week))
    kept = immovable_block(a_candidate(between(13, 14), binding=GYM), PartialPlan.of(week))

    assert moved is not None
    assert (moved.rule, moved.detail) == (ConstraintRule.IMMOVABLE_BLOCK, f"Gym, {PINNED}")
    assert kept is None


def test_a_block_fixed_by_derivation_may_not_be_placed_anywhere_else_either() -> None:
    transit = a_transit_block(anchor_id=AN_ANCHOR_ID, interval=between(9.5, 10))
    week = inputs(shadow_blocks=(transit,))

    moved = immovable_block(
        a_candidate(between(11, 11.5), binding=transit.binding, area_id=CAREER),
        PartialPlan.of(week),
    )
    kept = immovable_block(
        a_candidate(between(9.5, 10), binding=transit.binding, area_id=CAREER),
        PartialPlan.of(week),
    )

    assert moved is not None
    assert (moved.rule, moved.detail) == (
        ConstraintRule.IMMOVABLE_BLOCK,
        f"Leave for Uni, {FIXED_BY_DERIVATION}",
    )
    assert kept is None


def test_both_senses_report_one_rule_and_differ_only_in_what_the_clause_says() -> None:
    # They are the same to the checker and differ in everything else: one is a user act with
    # training value and the other is a structural fact, and the detail is the one place that shows.
    transit = a_transit_block(anchor_id=AN_ANCHOR_ID, interval=between(9.5, 10))
    derived = immovable_block(
        a_candidate(between(11, 11.5), binding=transit.binding, area_id=CAREER),
        PartialPlan.of(inputs(shadow_blocks=(transit,))),
    )
    pinned = immovable_block(
        a_candidate(between(11, 11.5), binding=GYM),
        PartialPlan.of(inputs(pins=(a_pin(binding=GYM, interval=between(13, 14)),))),
    )

    assert derived is not None
    assert pinned is not None
    assert derived.rule is pinned.rule
    assert derived.detail != pinned.detail


@pytest.mark.parametrize(
    "shape",
    ["frame", "anchor", "shadow", "template_entry"],
)
def test_every_shape_derivation_determines_is_immovable(shape: str) -> None:
    anchor = an_anchor(anchor_id=AN_ANCHOR_ID, interval=between(10, 11))
    frame = a_frame_entry(interval=between(23, 31), title="Sleep")
    shadow = a_transit_block(anchor_id=AN_ANCHOR_ID, interval=between(9.5, 10))
    entry = a_concrete_entry(interval=between(6.75, 7))
    week = inputs(
        frame=(frame,), anchors=(anchor,), shadow_blocks=(shadow,), template_entries=(entry,)
    )
    binding = {
        "frame": frame.block_binding,
        "anchor": BindingRef.for_anchor(anchor.anchor_id),
        "shadow": shadow.binding,
        "template_entry": entry.block_binding,
    }[shape]
    area_id = None if shape in {"frame", "anchor"} else CAREER

    rejection = immovable_block(
        a_candidate(between(15, 16), binding=binding, area_id=area_id), PartialPlan.of(week)
    )

    assert rejection is not None
    assert rejection.detail is not None
    assert rejection.detail.endswith(FIXED_BY_DERIVATION)


def test_content_the_week_holds_nowhere_may_be_placed_freely() -> None:
    assert (
        immovable_block(a_candidate(between(10, 11), binding=GYM), PartialPlan.of(inputs())) is None
    )


# --------------------------------------------------------------------------------
# H12: a declared off-plan span
# --------------------------------------------------------------------------------


def test_a_candidate_inside_an_off_plan_span_is_refused_and_names_the_period() -> None:
    period = an_off_plan_period(interval=between(0, 48), label="Rome")

    rejection = off_plan(a_candidate(between(10, 11)), PartialPlan.of(inputs(off_plan=(period,))))

    assert rejection is not None
    assert (rejection.rule, rejection.window, rejection.detail) == (
        ConstraintRule.OFF_PLAN,
        between(10, 11),
        "Rome",
    )


def test_a_span_the_user_gave_no_name_is_still_named_in_the_rejection() -> None:
    rejection = off_plan(
        a_candidate(between(10, 11)),
        PartialPlan.of(inputs(off_plan=(an_off_plan_period(interval=between(0, 48)),))),
    )

    assert rejection is not None
    assert rejection.detail == UNNAMED_OFF_PLAN


def test_a_pin_inside_the_span_is_honoured_which_is_how_mostly_off_is_expressed() -> None:
    week = inputs(
        off_plan=(an_off_plan_period(interval=between(0, 48)),),
        pins=(a_pin(binding=GYM, interval=between(10, 11)),),
    )

    assert off_plan(a_candidate(between(10, 11), binding=GYM), PartialPlan.of(week)) is None


def test_a_pin_offered_anywhere_but_its_own_interval_is_still_refused_by_the_span() -> None:
    # The exception is read from the pin's own interval, so this rule is decidable on its own rather
    # than resting on H11 having already refused the move.
    week = inputs(
        off_plan=(an_off_plan_period(interval=between(0, 48)),),
        pins=(a_pin(binding=GYM, interval=between(10, 11)),),
    )

    rejection = off_plan(a_candidate(between(14, 15), binding=GYM), PartialPlan.of(week))

    assert rejection is not None
    assert rejection.rule is ConstraintRule.OFF_PLAN


def test_a_candidate_abutting_the_span_is_outside_it() -> None:
    # The half-open convention: a period ending Monday 09:00 leaves 09:00 itself on plan.
    week = inputs(off_plan=(an_off_plan_period(interval=between(0, 9)),))

    assert off_plan(a_candidate(between(9, 10)), PartialPlan.of(week)) is None


def test_keeping_the_frame_changes_nothing_about_what_may_be_placed_inside_the_span() -> None:
    # Whether routines survive the span is the user's own choice on the period, resolved before the
    # frame reaches the solver. Nothing else survives either way, so this rule reads no such field.
    kept = an_off_plan_period(interval=between(0, 48), keep_frame=True)
    dropped = an_off_plan_period(interval=between(0, 48))

    for period in (kept, dropped):
        rejection = off_plan(
            a_candidate(between(10, 11)), PartialPlan.of(inputs(off_plan=(period,)))
        )
        assert rejection is not None
        assert rejection.rule is ConstraintRule.OFF_PLAN


def test_the_period_a_candidate_reaches_only_partly_still_refuses_it() -> None:
    # A candidate half inside the span is half inside a period the user declared off, and there is
    # no half of a block to place.
    week = inputs(off_plan=(an_off_plan_period(interval=between(9, 10)),))

    rejection = off_plan(a_candidate(between(9.75, 10.75)), PartialPlan.of(week))

    assert rejection is not None
    assert rejection.rule is ConstraintRule.OFF_PLAN


def test_a_week_declaring_nothing_off_refuses_nothing() -> None:
    assert off_plan(a_candidate(between(10, 11)), PartialPlan.of(inputs())) is None


def test_the_span_is_read_as_instants_rather_than_as_a_count_of_days() -> None:
    # A period is an arbitrary interval with instant precision, so Friday 14:00 to Monday 09:00 is
    # one declaration rather than three days plus two part-days.
    week = inputs(off_plan=(an_off_plan_period(interval=Interval(at(14, day=4), at(9, day=7))),))

    assert off_plan(a_candidate(between(13, 14, day=4)), PartialPlan.of(week)) is None
    assert off_plan(a_candidate(between(15, 16, day=4)), PartialPlan.of(week)) is not None
