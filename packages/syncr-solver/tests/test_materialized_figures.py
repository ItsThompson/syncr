"""The figures a materialized document carries, and the two properties they hold under.

Three figures and one denominator, all four computed from the same arithmetic the budget report
uses. Each test states the minutes it expects rather than a direction, because a figure that is
merely "smaller" would pass while over-subtracting: on the worked inputs the difference between
summing the subtrahends and unioning them is nine hours of a week.

The determinism properties are here because they are properties of a document rather than of a
placement. Two of them: the same inputs materialize byte for byte identically, and permuting every
input list changes nothing. The second is the one that catches an accidental dependence on
iteration order, which no assertion about a single build can see.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hypothesis import given, settings
from hypothesis import strategies as st

from syncr_domain.gaps import ForbiddenScope
from syncr_domain.identity import TransitLeg
from syncr_solver import materialize
from syncr_solver.metrics import MaterializeCause
from tests.materialized_weeks import (
    CAREER,
    FITNESS,
    WEEK,
    WEEK_MINUTES,
    a_concrete_entry,
    a_frame_entry,
    a_recovery_window,
    a_slot,
    a_transit_block,
    an_anchor,
    an_area_budget,
    an_off_plan_period,
    between,
    inputs,
    on,
)

if TYPE_CHECKING:
    from random import Random

    from syncr_domain.plan import PlanDocument
    from syncr_solver.inputs import SolveInputs

PHASE1 = MaterializeCause.PHASE1
HOUR = 60


def canonical(document: PlanDocument) -> bytes:
    """A document as one canonical text, so two of them can be compared byte for byte.

    Text rather than value equality, because equality between two mappings ignores the order their
    keys are held in and a document's own order is part of what determinism means here. It is the
    value's ``repr`` rather than a stored form: nothing serializes a document yet, so this states
    what it can honestly state, which is that two builds are the same value in the same order.
    """
    return repr(document).encode("utf-8")


def figures(document: PlanDocument) -> tuple[int, int, int]:
    return (
        document.discretionary_minutes,
        document.unallocated_minutes,
        document.oversubscription_minutes,
    )


# --------------------------------------------------------------------------------
# The denominator
# --------------------------------------------------------------------------------


def test_a_week_with_nothing_in_it_is_discretionary_and_unallocated_throughout() -> None:
    document = materialize(inputs(), cause=PHASE1)

    assert figures(document) == (WEEK_MINUTES, WEEK_MINUTES, 0)


def test_the_frame_the_commitments_the_absolute_windows_and_the_off_plan_spans_come_out() -> None:
    # The four subtrahends, each contributing one hour and none of them overlapping, so the figure
    # is the same whether they are summed or unioned. What they have in common is that no Area can
    # claim them.
    week = inputs(
        frame=(a_frame_entry(interval=between(1, 2)),),
        anchors=(an_anchor(interval=between(3, 4)),),
        forbidden_windows=(a_recovery_window(interval=between(5, 6)),),
        off_plan=(an_off_plan_period(interval=between(7, 8)),),
    )

    document = materialize(week, cause=PHASE1)

    assert document.discretionary_minutes == WEEK_MINUTES - 4 * HOUR


def test_overlapping_subtrahends_are_unioned_rather_than_summed() -> None:
    # Three of the four routinely overlap: a frame span sits inside a long off-plan period, and a
    # recovery window abuts the commitment that cast it. Summing over-subtracts, and the arithmetic
    # this reads unions first, so a minute counted twice is counted once.
    week = inputs(
        frame=(a_frame_entry(interval=between(1, 3)),),
        anchors=(an_anchor(interval=between(2, 4)),),
        off_plan=(an_off_plan_period(interval=between(1, 4)),),
    )

    document = materialize(week, cause=PHASE1)

    assert document.discretionary_minutes == WEEK_MINUTES - 3 * HOUR


def test_the_inherited_half_of_the_frame_leaves_the_denominator_too() -> None:
    # The night the preceding week spent runs into this one, and the time is genuinely occupied. A
    # reader of this week's own occurrences alone would count it as free.
    week = inputs(frame_overhang=(between(0, 7),))

    document = materialize(week, cause=PHASE1)

    assert document.discretionary_minutes == WEEK_MINUTES - 7 * HOUR


def test_a_recovery_window_scoped_to_named_areas_stays_in_the_denominator() -> None:
    # Only the named Areas are excluded, so every other Area may still claim that time. Unfilled it
    # becomes unallocated, which is the honest answer rather than removing it from the week.
    scoped = a_recovery_window(
        interval=between(5, 6), scope=ForbiddenScope.AREAS, forbidden_area_ids=(FITNESS,)
    )

    document = materialize(inputs(forbidden_windows=(scoped,)), cause=PHASE1)

    assert figures(document) == (WEEK_MINUTES, WEEK_MINUTES, 0)


def test_a_buffer_carrying_an_area_stays_in_the_denominator_and_claims_its_time() -> None:
    # The narrowing the pure package states: prep and transit are anchor shadows and they are NOT
    # subtracted, because they carry an Area. Subtracting them would take the time out of the
    # denominator and charge it to an Area as well.
    week = inputs(shadow_blocks=(a_transit_block(interval=between(9, 10), area_id=CAREER),))

    document = materialize(week, cause=PHASE1)

    assert document.discretionary_minutes == WEEK_MINUTES
    assert document.unallocated_minutes == WEEK_MINUTES - HOUR


# --------------------------------------------------------------------------------
# Unallocated time
# --------------------------------------------------------------------------------


def test_a_block_carrying_an_area_claims_its_span_and_the_frame_and_a_commitment_do_not() -> None:
    week = inputs(
        frame=(a_frame_entry(interval=between(1, 2)),),
        anchors=(an_anchor(interval=between(3, 4)),),
        template_entries=(a_concrete_entry(interval=between(12, 13)),),
    )

    document = materialize(week, cause=PHASE1)

    assert document.discretionary_minutes == WEEK_MINUTES - 2 * HOUR
    assert document.unallocated_minutes == WEEK_MINUTES - 3 * HOUR


def test_an_unfilled_slot_increases_unallocated_time() -> None:
    # An empty slot is discretionary time nothing was placed in. Subtracting it would make an
    # unfillable week read as a fully budgeted one, when the honest answer is that the time is
    # unallocated.
    filled = inputs(template_entries=(a_concrete_entry(interval=between(18, 19)),))
    unfilled = inputs(template_entries=(a_slot(interval=between(18, 19)),))

    with_content = materialize(filled, cause=PHASE1)
    without = materialize(unfilled, cause=PHASE1)

    assert with_content.unallocated_minutes == WEEK_MINUTES - HOUR
    assert without.unallocated_minutes == WEEK_MINUTES


def test_a_refused_placement_leaves_its_span_unallocated_rather_than_claimed() -> None:
    # A candidate the occupancy rules refused holds nothing, so nothing claims its time. The
    # denominator does not move either: what a week has is not a function of how much of it was
    # placed.
    anchor = an_anchor(interval=between(10, 11))
    week = inputs(
        anchors=(anchor,), template_entries=(a_concrete_entry(interval=between(10.5, 11)),)
    )

    document = materialize(week, cause=PHASE1)

    assert figures(document) == (WEEK_MINUTES - HOUR, WEEK_MINUTES - HOUR, 0)


def test_two_area_carrying_blocks_claim_both_their_spans() -> None:
    # A minute claimed by two Areas would leave the residual once, and no materialized week can
    # hold one: H4 refuses the second of two overlapping placements, so the two spans here are
    # disjoint and both are claimed. The union that would absorb a shared minute is
    # ``IntervalSet``'s own normalisation rather than a rule this figure states.
    anchor = an_anchor(interval=between(20, 21))
    week = inputs(
        shadow_blocks=(
            a_transit_block(anchor_id=anchor.anchor_id, interval=between(12, 13), area_id=CAREER),
            a_transit_block(
                anchor_id=anchor.anchor_id,
                leg=TransitLeg.BACK,
                interval=between(13, 13.5),
                area_id=FITNESS,
            ),
        ),
    )

    document = materialize(week, cause=PHASE1)

    assert len(document.blocks) == 2
    assert document.unallocated_minutes == WEEK_MINUTES - 90


# --------------------------------------------------------------------------------
# Oversubscription
# --------------------------------------------------------------------------------


def test_targets_that_fit_the_week_oversubscribe_it_by_nothing() -> None:
    week = inputs(
        areas=(
            an_area_budget(area_id=FITNESS, target_minutes=5 * HOUR),
            an_area_budget(area_id=CAREER, target_minutes=10 * HOUR),
        )
    )

    document = materialize(week, cause=PHASE1)

    assert document.oversubscription_minutes == 0


def test_targets_beyond_the_denominator_are_reported_rather_than_refused() -> None:
    # Percentages summing past 100 are accepted and reported. The figure is how far the Areas' own
    # targets exceed the time available, which is a different quantity from unallocated time.
    week = inputs(
        frame=(a_frame_entry(interval=between(1, 2)),),
        areas=(an_area_budget(area_id=FITNESS, target_minutes=WEEK_MINUTES),),
    )

    document = materialize(week, cause=PHASE1)

    assert document.oversubscription_minutes == HOUR
    assert document.unallocated_minutes == WEEK_MINUTES - HOUR


# --------------------------------------------------------------------------------
# The rest of the document
# --------------------------------------------------------------------------------


def test_the_zones_are_captured_at_materialize_time_in_the_week_s_own_date_order() -> None:
    # A travel override declared later cannot re-read a stored week, and the order is the week's
    # rather than the order the mapping arrived in, so a document is identical however it was
    # assembled.
    travelling = {day: "Asia/Tokyo" if day == on(3) else "Europe/London" for day in WEEK.dates()}
    reversed_arrival = dict(reversed(list(travelling.items())))

    document = materialize(inputs(zone_by_date=reversed_arrival), cause=PHASE1)

    assert list(document.zone_by_date.items()) == list(travelling.items())


def test_the_concessions_the_week_was_derived_under_are_named_on_the_document() -> None:
    # So a week never looks feasible for a reason the user cannot see. They are already folded into
    # the inputs, so this carries the identifiers rather than applying anything.
    week = inputs()

    document = materialize(week, cause=PHASE1)

    assert document.adjustments == ()


# --------------------------------------------------------------------------------
# The two determinism properties
# --------------------------------------------------------------------------------


def a_dense_week() -> SolveInputs:
    """A week with two of everything, several members colliding, so an order can be felt."""
    first = an_anchor(interval=between(10, 11), title="Kontron Placement Interview")
    second = an_anchor(interval=between(10.5, 12), title="Dentist")
    return inputs(
        frame=tuple(a_frame_entry(day=day, interval=between(23, 31, day=day)) for day in range(3)),
        frame_overhang=(between(0, 6),),
        anchors=(first, second),
        shadow_blocks=(
            a_transit_block(anchor_id=first.anchor_id, interval=between(9.5, 10)),
            a_transit_block(
                anchor_id=first.anchor_id, leg=TransitLeg.BACK, interval=between(9.75, 10.5)
            ),
        ),
        forbidden_windows=(
            a_recovery_window(interval=between(12, 13)),
            a_recovery_window(
                interval=between(14, 15), scope=ForbiddenScope.AREAS, forbidden_area_ids=(FITNESS,)
            ),
        ),
        off_plan=(an_off_plan_period(interval=between(20, 22, day=6)),),
        template_entries=(
            a_concrete_entry(interval=between(6.75, 7)),
            a_concrete_entry(day=1, interval=between(12.5, 13)),
            a_slot(),
            a_slot(day=2, interval=between(19, 20, day=2)),
        ),
        areas=(
            an_area_budget(area_id=FITNESS, target_minutes=8 * HOUR),
            an_area_budget(area_id=CAREER, target_minutes=6 * HOUR),
        ),
    )


def test_materializing_the_same_inputs_twice_yields_byte_identical_documents() -> None:
    week = a_dense_week()

    assert canonical(materialize(week, cause=PHASE1)) == canonical(materialize(week, cause=PHASE1))


def test_a_document_holds_the_windows_of_one_commitment_in_an_order_its_inputs_cannot_change() -> (
    None
):
    # The windows reach the document in the order the state holds them, and one commitment casts up
    # to four, so a key stopping at the anchor would order two of them by input arrival. Recovery is
    # the one kind whose scope the user chooses, which is what makes this pair constructible.
    absolute = a_recovery_window(interval=between(11, 12))
    scoped = a_recovery_window(
        interval=between(11, 12),
        scope=ForbiddenScope.AREAS,
        forbidden_area_ids=(FITNESS,),
        anchor_id=absolute.anchor_id,
        label=absolute.label,
    )

    forwards = materialize(inputs(forbidden_windows=(absolute, scoped)), cause=PHASE1)
    backwards = materialize(inputs(forbidden_windows=(scoped, absolute)), cause=PHASE1)

    assert canonical(forwards) == canonical(backwards)
    assert len(forwards.forbidden_windows) == 2


def test_two_blocks_alike_in_span_and_title_are_held_in_an_order_their_identities_decide() -> None:
    # The tie the block order has to break, and it is reachable twice over: one commitment synced
    # from two sources arrives as two anchors with one title and one span, and a date a zone skips
    # entirely gives one routine two occurrences at one interval. Ordered by input order, a
    # document would depend on which arrived first while describing the same week.
    first = an_anchor(interval=between(10, 11), title="Kontron Placement Interview")
    second = an_anchor(interval=between(10, 11), title="Kontron Placement Interview")

    forwards = materialize(inputs(anchors=(first, second)), cause=PHASE1)
    backwards = materialize(inputs(anchors=(second, first)), cause=PHASE1)

    assert canonical(forwards) == canonical(backwards)
    assert len(forwards.blocks) == 2


PERMUTABLE = (
    "frame",
    "frame_overhang",
    "anchors",
    "shadow_blocks",
    "forbidden_windows",
    "off_plan",
    "template_entries",
    "areas",
)


@given(seed=st.randoms(use_true_random=False))
@settings(max_examples=25, deadline=None)
def test_permuting_every_input_list_changes_nothing_about_the_document(seed: Random) -> None:
    # The property that catches a dependence on iteration order, which no assertion about one build
    # can see. Every list a derived week reads is shuffled, including the ones a rejection's detail
    # is drawn from, so a reason clause that varied with input order fails here too.
    week = a_dense_week()
    shuffled = inputs(
        **{
            name: tuple(seed.sample(list(getattr(week, name)), len(getattr(week, name))))
            for name in PERMUTABLE
        }
    )

    assert canonical(materialize(shuffled, cause=PHASE1)) == canonical(
        materialize(week, cause=PHASE1)
    )


@given(
    hours=st.lists(st.integers(min_value=0, max_value=160), min_size=0, max_size=12, unique=True),
    targets=st.lists(st.integers(min_value=0, max_value=20 * HOUR), max_size=4),
)
@settings(max_examples=50, deadline=None)
def test_unallocated_time_is_never_negative_and_never_more_than_the_denominator(
    hours: list[int], targets: list[int]
) -> None:
    # Non-negative by construction rather than by a clamp: it is a subtraction of sets. The upper
    # bound is the other half, and the document itself refuses a pair that breaks either, so this
    # asserts what materialization can hand it over a generated week.
    week = inputs(
        frame=tuple(
            a_frame_entry(interval=between(hour, hour + 1)) for hour in hours if hour % 3 == 0
        ),
        shadow_blocks=tuple(
            a_transit_block(interval=between(hour, hour + 1)) for hour in hours if hour % 3 == 1
        ),
        template_entries=tuple(
            a_slot(interval=between(hour, hour + 1)) for hour in hours if hour % 3 == 2
        ),
        areas=tuple(an_area_budget(target_minutes=target) for target in targets),
    )

    document = materialize(week, cause=PHASE1)

    assert 0 <= document.unallocated_minutes <= document.discretionary_minutes
    assert document.oversubscription_minutes >= 0
