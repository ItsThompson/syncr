"""H1 to H4: the four rules a plan derived from nothing else can break.

Each is driven at the boundary it exists for, and each assertion reads the rejection's rule, window
and detail rather than only that something was refused: the triple is what the ``blocked`` clause
renders, and a rejection that cannot say what rejected it teaches the user nothing.

Every rule here is also driven at a case it must NOT reject, because a rule that refuses everything
passes a suite that only ever hands it a violation.
"""

from __future__ import annotations

from uuid import UUID

from syncr_domain.gaps import ForbiddenKind, ForbiddenScope, ForbiddenWindow
from syncr_domain.identity import BindingRef
from syncr_solver.constraints import ConstraintCheck, ConstraintRule
from syncr_solver.occupancy import INHERITED_FRAME, OCCUPANCY_RULES
from syncr_solver.state import PartialPlan, Placement
from tests.materialized_weeks import (
    CAREER,
    a_candidate,
    a_frame_entry,
    a_recovery_window,
    an_anchor,
    between,
    inputs,
)

AN_ANCHOR_ID = UUID("00000000-0000-4000-8000-0000000000bb")
ANOTHER_ANCHOR_ID = UUID("00000000-0000-4000-8000-0000000000cc")


def a_check() -> ConstraintCheck:
    """The checker holding the rules a derived plan needs, which the caller always states."""
    return ConstraintCheck(OCCUPANCY_RULES)


# --------------------------------------------------------------------------------
# H1, the imported commitment
# --------------------------------------------------------------------------------


def test_a_candidate_over_an_anchor_is_rejected_by_the_commitment_that_holds_the_time() -> None:
    anchor = an_anchor(interval=between(10, 11), title="Kontron Placement Interview")
    candidate = a_candidate(between(10.5, 11.5))

    rejection = a_check().check(candidate, PartialPlan.of(inputs(anchors=(anchor,))))

    assert rejection is not None
    assert (rejection.rule, rejection.window, rejection.detail) == (
        ConstraintRule.ANCHOR_OVERLAP,
        candidate.interval,
        "Kontron Placement Interview",
    )


def test_a_candidate_abutting_a_commitment_is_not_overlapping_it() -> None:
    # The boundary the whole occupancy half rests on: a transit block that ends exactly when its
    # commitment starts is the ordinary case, not a collision.
    state = PartialPlan.of(inputs(anchors=(an_anchor(interval=between(10, 11)),)))

    assert a_check().check(a_candidate(between(9.5, 10)), state) is None
    assert a_check().check(a_candidate(between(11, 11.5)), state) is None


# --------------------------------------------------------------------------------
# H2, a window that forbids every Area
# --------------------------------------------------------------------------------


def test_a_candidate_over_an_absolute_window_is_rejected_and_a_scoped_one_is_not() -> None:
    # H2 reads only the windows that forbid every Area. A window scoped to named Areas is H13's,
    # and reading it here would be the two readings of one window drifting apart again.
    absolute = a_recovery_window(interval=between(11, 12), label="recovery · Lecture")
    scoped = a_recovery_window(
        interval=between(11, 12), scope=ForbiddenScope.AREAS, forbidden_area_ids=(CAREER,)
    )
    candidate = a_candidate(between(11, 11.5))

    refused = a_check().check(candidate, PartialPlan.of(inputs(forbidden_windows=(absolute,))))
    allowed = a_check().check(candidate, PartialPlan.of(inputs(forbidden_windows=(scoped,))))

    assert refused is not None
    assert (refused.rule, refused.detail) == (
        ConstraintRule.FORBIDDEN_WINDOW,
        "recovery · Lecture",
    )
    assert allowed is None


def test_an_unattributed_buffer_forbids_a_candidate_of_every_area() -> None:
    # A prep buffer whose type named no Area became a window rather than a block, so there is no
    # Area to scope it to and nothing may be placed inside it.
    buffer = ForbiddenWindow(
        between(9, 9.5),
        ForbiddenKind.PREP_UNATTRIBUTED,
        ForbiddenScope.ALL,
        (),
        "prep · Lecture",
        an_anchor().anchor_id,
    )

    rejection = a_check().check(
        a_candidate(between(9, 10), area_id=CAREER),
        PartialPlan.of(inputs(forbidden_windows=(buffer,))),
    )

    assert rejection is not None
    assert rejection.rule is ConstraintRule.FORBIDDEN_WINDOW


def test_a_candidate_over_the_frame_is_rejected_by_the_routine_that_bounds_the_day() -> None:
    entry = a_frame_entry(interval=between(23, 31), title="Sleep")

    rejection = a_check().check(
        a_candidate(between(23.5, 24)), PartialPlan.of(inputs(frame=(entry,)))
    )

    assert rejection is not None
    assert (rejection.rule, rejection.detail) == (ConstraintRule.FRAME_OVERLAP, "Sleep")


def test_a_candidate_over_an_inherited_frame_span_is_rejected_without_naming_a_routine() -> None:
    # The week that owns a boundary-crossing occurrence holds the whole interval and materializes
    # the one block, so this week carries the span and not the name. The rejection says so rather
    # than borrowing a title from a different occurrence.
    overhang = between(0, 7)

    rejection = a_check().check(
        a_candidate(between(6, 8)), PartialPlan.of(inputs(frame_overhang=(overhang,)))
    )

    assert rejection is not None
    assert (rejection.rule, rejection.detail) == (ConstraintRule.FRAME_OVERLAP, INHERITED_FRAME)


def test_the_inherited_channel_names_a_routine_whatever_shape_the_span_came_from() -> None:
    # The channel H3 reads carries spans and no titles, so any OTHER boundary-crossing shape routed
    # through it would be reported as a routine. A late template entry running into the following
    # week is the shape that reaches this: it is occupancy nobody hands over today, and whichever
    # field carries it decides whether this clause tells the truth.
    entry_running_past_midnight = between(0, 0.5)

    rejection = a_check().check(
        a_candidate(between(0, 1)),
        PartialPlan.of(inputs(frame_overhang=(entry_running_past_midnight,))),
    )

    assert rejection is not None
    assert rejection.detail == INHERITED_FRAME


# --------------------------------------------------------------------------------
# H4, the overlap the solve itself would create
# --------------------------------------------------------------------------------


def test_a_candidate_over_something_already_placed_is_rejected_by_what_holds_the_span() -> None:
    placed = Placement(
        binding=BindingRef.for_anchor_prep(an_anchor().anchor_id),
        interval=between(8, 9),
        title="Interview prep",
        area_id=CAREER,
    )

    rejection = a_check().check(
        a_candidate(between(8.5, 9.5)), PartialPlan.of(inputs()).with_placed(placed)
    )

    assert rejection is not None
    assert (rejection.rule, rejection.detail) == (
        ConstraintRule.BLOCK_OVERLAP,
        "Interview prep",
    )


def test_the_state_holds_its_members_in_span_order_whatever_order_they_arrived_in() -> None:
    # Two members overlapping one candidate would otherwise be reported by whichever the inputs
    # happened to list first, so permuting an input list would change a reason clause while
    # changing no placement.
    early = an_anchor(interval=between(9, 11), title="Lecture")
    late = an_anchor(interval=between(10, 12), title="Kontron Placement Interview")

    forwards = a_check().check(
        a_candidate(between(10.5, 10.75)), PartialPlan.of(inputs(anchors=(early, late)))
    )
    backwards = a_check().check(
        a_candidate(between(10.5, 10.75)), PartialPlan.of(inputs(anchors=(late, early)))
    )

    assert forwards is not None
    assert forwards == backwards
    assert forwards.detail == "Lecture"
