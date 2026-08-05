"""H1 to H4 and H13: the five rules that ask whether a span is already spent.

Each is driven at the boundary it exists for, and each assertion reads the rejection's rule, window
and detail rather than only that something was refused: the triple is what the ``blocked`` clause
renders, and a rejection that cannot say what rejected it teaches the user nothing.

Every rule here is also driven at a case it must NOT reject, because a rule that refuses everything
passes a suite that only ever hands it a violation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from syncr_domain.fixtures import recovery_scopes as scopes
from syncr_domain.gaps import ForbiddenKind, ForbiddenScope, ForbiddenWindow
from syncr_domain.identity import BindingRef, TransitLeg
from syncr_solver.constraints import ConstraintCheck, ConstraintRule
from syncr_solver.occupancy import (
    INHERITED_FRAME,
    OCCUPANCY_RULES,
    forbidden_area,
    forbidden_window,
)
from syncr_solver.state import PartialPlan, Placement
from tests.materialized_weeks import (
    CAREER,
    FITNESS,
    WEEK,
    a_block,
    a_candidate,
    a_frame_entry,
    a_live_plan,
    a_pin,
    a_recovery_window,
    an_anchor,
    between,
    inputs,
)

if TYPE_CHECKING:
    from syncr_domain.intervals import Interval

AN_ANCHOR_ID = UUID("00000000-0000-4000-8000-0000000000bb")
ANOTHER_ANCHOR_ID = UUID("00000000-0000-4000-8000-0000000000cc")


def a_check() -> ConstraintCheck:
    """The checker holding the rules a derived plan needs, which the caller always states."""
    return ConstraintCheck(OCCUPANCY_RULES)


def a_journey_home(*, anchor_id: UUID, interval: Interval) -> Placement:
    """The return leg an anchor's type casts, which begins where the commitment ends."""
    return Placement(
        binding=BindingRef.for_anchor_transit(anchor_id, leg=TransitLeg.BACK),
        interval=interval,
        title="Go Home",
        area_id=CAREER,
    )


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
# H2 and H13, the two readings of a forbidden window
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


def test_a_scoped_window_refuses_a_forbidden_area_and_leaves_every_other_one_free() -> None:
    # The settled record's own case: an Interview forbids Career and Study afterwards, so the gym
    # is still fine. Two candidates, one window, and the only thing that varies is the Area.
    window = a_recovery_window(
        interval=between(16.75, 18),
        scope=ForbiddenScope.AREAS,
        forbidden_area_ids=(CAREER,),
        label="recovery · Kontron Interview",
    )
    state = PartialPlan.of(inputs(forbidden_windows=(window,)))

    refused = a_check().check(a_candidate(between(17, 18), area_id=CAREER), state)
    allowed = a_check().check(a_candidate(between(17, 18), area_id=FITNESS), state)

    assert refused is not None
    assert (refused.rule, refused.window, refused.detail) == (
        ConstraintRule.FORBIDDEN_AREA,
        between(17, 18),
        "recovery · Kontron Interview",
    )
    assert allowed is None


def test_a_candidate_carrying_no_area_is_refused_by_no_scoped_window() -> None:
    # A block with no Area is the frame or an imported commitment, and both define the space rather
    # than competing inside it, so a window naming Areas names none of theirs.
    window = a_recovery_window(
        interval=between(11, 12), scope=ForbiddenScope.AREAS, forbidden_area_ids=(FITNESS, CAREER)
    )
    commitment = Placement(
        binding=BindingRef.for_anchor(AN_ANCHOR_ID),
        interval=between(11, 11.5),
        title="Kontron Placement Interview",
    )

    assert a_check().check(commitment, PartialPlan.of(inputs(forbidden_windows=(window,)))) is None


# --------------------------------------------------------------------------------
# The two scopes crossed against the fixture the denominator and the probe already read
# --------------------------------------------------------------------------------


def test_the_fixture_describes_the_same_week_this_suite_does() -> None:
    # The crossing below is only a crossing if the two are talking about one week. The fixture is
    # `Europe/London` 2026-W07 and so is this suite, so the spans coincide and neither side has to
    # restate the other's geometry.
    assert scopes.WEEK == WEEK
    assert inputs().span == scopes.SPAN


def test_the_scoped_form_of_the_fixtures_window_forbids_study_and_leaves_fitness_free() -> None:
    # One commitment, one recovery span, and the scope is the only thing that varies. The fixture is
    # the value the denominator's subtraction table and the probe's projection are both stated over,
    # so reading it here is what makes the three answer about the SAME two spans rather than about
    # three descriptions of one.
    state = PartialPlan.of(inputs(forbidden_windows=(scopes.FORBIDDING_STUDY,)))
    study = a_candidate(scopes.RECOVERY, area_id=scopes.STUDY, title="Dissertation")
    fitness = a_candidate(scopes.RECOVERY, area_id=scopes.FITNESS, title="Shoulder & Arms")

    refused = a_check().check(study, state)
    allowed = a_check().check(fitness, state)

    assert refused is not None
    assert (refused.rule, refused.window, refused.detail) == (
        ConstraintRule.FORBIDDEN_AREA,
        scopes.RECOVERY,
        scopes.LABEL,
    )
    assert allowed is None


def test_the_absolute_form_of_the_same_window_forbids_the_area_the_scoped_form_left_free() -> None:
    # The asymmetry the fixture exists for, read as legality rather than as capacity: converting the
    # scoped form to the absolute one may only take capacity away. From Study, nothing, because
    # Study was already forbidden; from every other Area, the whole span.
    absolute = PartialPlan.of(inputs(forbidden_windows=(scopes.FORBIDDING_EVERY_AREA,)))
    scoped = PartialPlan.of(inputs(forbidden_windows=(scopes.FORBIDDING_STUDY,)))
    fitness = a_candidate(scopes.RECOVERY, area_id=scopes.FITNESS, title="Shoulder & Arms")
    study = a_candidate(scopes.RECOVERY, area_id=scopes.STUDY, title="Dissertation")

    for candidate in (fitness, study):
        rejection = a_check().check(candidate, absolute)
        assert rejection is not None
        assert (rejection.rule, rejection.detail) == (
            ConstraintRule.FORBIDDEN_WINDOW,
            scopes.LABEL,
        )
    assert a_check().check(study, scoped) is not None
    assert a_check().check(fitness, scoped) is None


def test_the_scoped_form_is_invisible_to_the_rule_that_reads_the_absolute_one() -> None:
    # The split that keeps the two readings of one window from drifting: H2 sees only the windows
    # that forbid every Area, so the scoped form reaches the candidate through H13 or not at all.
    scoped = PartialPlan.of(inputs(forbidden_windows=(scopes.FORBIDDING_STUDY,)))
    study = a_candidate(scopes.RECOVERY, area_id=scopes.STUDY, title="Dissertation")

    assert forbidden_window(study, scoped) is None
    assert forbidden_area(study, scoped) is not None


# --------------------------------------------------------------------------------
# The one exemption: an anchor's own derived blocks against its own recovery window
# --------------------------------------------------------------------------------


def test_a_journey_home_sits_inside_its_own_commitments_recovery_window() -> None:
    # A return leg and recovery both begin at anchor.end, because recovery is measured from the
    # commitment rather than from the end of the journey. Without the exemption the one block a
    # lecture reliably casts could never be placed at all.
    window = a_recovery_window(interval=between(11, 12.25), anchor_id=AN_ANCHOR_ID)
    state = PartialPlan.of(inputs(forbidden_windows=(window,)))

    assert (
        a_check().check(a_journey_home(anchor_id=AN_ANCHOR_ID, interval=between(11, 11.5)), state)
        is None
    )


def test_another_commitments_journey_home_is_refused_by_the_same_window() -> None:
    # The exemption is about the pair rather than about the kind of block: a second lecture's
    # journey home is ordinary content inside this commitment's recovery.
    window = a_recovery_window(interval=between(11, 12.25), anchor_id=AN_ANCHOR_ID)
    state = PartialPlan.of(inputs(forbidden_windows=(window,)))

    rejection = a_check().check(
        a_journey_home(anchor_id=ANOTHER_ANCHOR_ID, interval=between(11, 11.5)), state
    )

    assert rejection is not None
    assert rejection.rule is ConstraintRule.FORBIDDEN_WINDOW


def test_the_exemption_holds_for_a_window_of_either_scope() -> None:
    # A user retyping one anchor from 'forbids everything' to 'forbids these Areas' must not strand
    # its journey home, so the two rules read the exemption through one statement of it.
    scoped = a_recovery_window(
        interval=between(11, 12.25),
        anchor_id=AN_ANCHOR_ID,
        scope=ForbiddenScope.AREAS,
        forbidden_area_ids=(CAREER,),
    )
    state = PartialPlan.of(inputs(forbidden_windows=(scoped,)))

    assert (
        a_check().check(a_journey_home(anchor_id=AN_ANCHOR_ID, interval=between(11, 11.5)), state)
        is None
    )


def test_an_anchors_own_block_is_still_refused_by_a_window_that_is_not_recovery() -> None:
    # Bounded to the kind the geometry makes unavoidable. An unattributed buffer overlapping a block
    # the same anchor cast is a collision the generator resolves, not a span this excuses.
    buffer = ForbiddenWindow(
        between(11, 11.5),
        ForbiddenKind.TRANSIT_UNATTRIBUTED,
        ForbiddenScope.ALL,
        (),
        "transit · Lecture",
        AN_ANCHOR_ID,
    )

    rejection = a_check().check(
        a_journey_home(anchor_id=AN_ANCHOR_ID, interval=between(11, 11.25)),
        PartialPlan.of(inputs(forbidden_windows=(buffer,))),
    )

    assert rejection is not None
    assert rejection.rule is ConstraintRule.FORBIDDEN_WINDOW


def test_ordinary_content_of_the_anchors_own_area_is_still_refused() -> None:
    # The exemption reads the binding rather than the Area, so a task in the Area a buffer happens
    # to carry gains nothing from it.
    window = a_recovery_window(interval=between(11, 12.25), anchor_id=AN_ANCHOR_ID)

    rejection = a_check().check(
        a_candidate(between(11, 11.5), area_id=CAREER),
        PartialPlan.of(inputs(forbidden_windows=(window,))),
    )

    assert rejection is not None
    assert rejection.rule is ConstraintRule.FORBIDDEN_WINDOW


# --------------------------------------------------------------------------------
# H3, the circadian frame
# --------------------------------------------------------------------------------


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


def test_two_overlapping_pins_are_both_placeable_in_either_order() -> None:
    # H4 binds the solver rather than the plan. A user-authored overlap is legitimate, so a re-solve
    # reproduces it: each pin is accepted at its own interval whatever is already there, and the
    # answer does not depend on which of the two was offered first.
    gym, reading = BindingRef.for_task(UUID(int=1)), BindingRef.for_task(UUID(int=2))
    week = inputs(
        pins=(
            a_pin(binding=gym, interval=between(10, 11)),
            a_pin(binding=reading, interval=between(10.5, 11.5)),
        )
    )
    first = a_candidate(between(10, 11), binding=gym, title="Gym")
    second = a_candidate(between(10.5, 11.5), binding=reading, title="Reading")

    forwards = a_check().check(second, PartialPlan.of(week).with_placed(first))
    backwards = a_check().check(first, PartialPlan.of(week).with_placed(second))

    assert forwards is None
    assert backwards is None


def test_content_the_user_did_not_pin_still_gives_way_to_the_pin() -> None:
    # The exception is the user's own placement rather than every placement: without that
    # distinction the pin would merely be the first thing placed and everything could overlap it.
    gym = BindingRef.for_task(UUID(int=1))
    pinned = a_candidate(between(10, 11), binding=gym, title="Gym")
    state = PartialPlan.of(
        inputs(pins=(a_pin(binding=gym, interval=between(10, 11)),))
    ).with_placed(pinned)

    rejection = a_check().check(a_candidate(between(10.5, 11.5)), state)

    assert rejection is not None
    assert (rejection.rule, rejection.detail) == (ConstraintRule.BLOCK_OVERLAP, "Gym")


def test_a_pin_moved_off_its_own_interval_is_no_longer_the_users_own_placement() -> None:
    # The exception reads the interval as well as the binding, so it is decidable on its own rather
    # than resting on H11 having already refused the move.
    gym = BindingRef.for_task(UUID(int=1))
    week = inputs(
        pins=(a_pin(binding=gym, interval=between(10, 11)),),
        live_plan=a_live_plan(a_block(binding=gym, interval=between(10, 11), title="Gym")),
    )
    placed = a_candidate(between(13, 14), title="Reading")

    rejection = a_check().check(
        a_candidate(between(13.5, 14), binding=gym, title="Gym"),
        PartialPlan.of(week).with_placed(placed),
    )

    assert rejection is not None
    assert rejection.rule is ConstraintRule.BLOCK_OVERLAP


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
