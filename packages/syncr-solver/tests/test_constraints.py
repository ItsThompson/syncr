"""The hard-constraint vocabulary, the table it is crossed against, and the occupancy rules.

Two kinds of test are here and they fail for different reasons. The vocabulary tests are stated
over the INVENTORY: the enum, the table, and the withdrawn numbers are compared with each other in
both directions, so a rule added without a name fails, a name added without a rule fails, and a
number that is both declared and withdrawn fails. That is what lets a later slice add the nine
rules a derived plan does not need as behaviour rather than as vocabulary.

The rule tests drive each occupancy rule at the boundary it exists for, and each asserts the
rejection's rule, window and detail rather than only that something was refused: the triple is
what the ``blocked`` clause renders, and a rejection that cannot say what rejected it teaches the
user nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from syncr_domain.gaps import ForbiddenKind, ForbiddenScope, ForbiddenWindow
from syncr_domain.identity import BindingRef
from syncr_solver.constraints import (
    HARD_CONSTRAINTS,
    INHERITED_FRAME,
    OCCUPANCY_RULES,
    WITHDRAWN_RULES,
    BlockedCandidate,
    ConstraintCheck,
    ConstraintRule,
    PartialPlan,
    Placement,
)
from tests.materialized_weeks import (
    CAREER,
    FITNESS,
    a_frame_entry,
    a_recovery_window,
    an_anchor,
    between,
    inputs,
)

if TYPE_CHECKING:
    from syncr_domain.identifiers import AreaId
    from syncr_domain.intervals import Interval

# The highest number the table reaches. Two of the fifteen were withdrawn, and the numbering is
# preserved rather than compacted, so this is not the count of rules.
HIGHEST_NUMBER = 15

# One content identity every candidate here carries. A candidate's own content is not what any of
# these rules read, so it is stated once rather than per test.
A_TASK = UUID("00000000-0000-4000-8000-0000000000aa")


def a_candidate(
    interval: Interval | None = None,
    *,
    title: str = "Shoulder & Arms",
    area_id: AreaId = FITNESS,
) -> Placement:
    return Placement(
        binding=BindingRef.for_task(A_TASK),
        interval=interval or between(10, 11),
        title=title,
        area_id=area_id,
    )


def test_every_rule_in_the_table_has_a_name_and_every_name_has_a_rule() -> None:
    # An equality both ways rather than a count, because the two failures it catches are opposite:
    # a rule with no member cannot report itself, and a member with no rule renders in a clause
    # nothing can produce, which a property test per rule would pass vacuously forever.
    named = {row.rule for row in HARD_CONSTRAINTS}

    assert named == set(ConstraintRule)
    assert len(HARD_CONSTRAINTS) == len(ConstraintRule)


def test_the_table_holds_one_row_per_number_and_states_what_each_forbids() -> None:
    numbers = [row.number for row in HARD_CONSTRAINTS]

    assert len(set(numbers)) == len(numbers)
    assert numbers == sorted(numbers)
    assert all(row.forbids for row in HARD_CONSTRAINTS)


def test_the_numbering_covers_every_number_once_as_a_rule_or_as_a_withdrawal() -> None:
    # The gaps are enumerated rather than explained in prose, so a missing number cannot read as
    # an omission and a rule cannot be both declared and withdrawn.
    declared = {row.number for row in HARD_CONSTRAINTS}

    assert declared | set(WITHDRAWN_RULES) == set(range(1, HIGHEST_NUMBER + 1))
    assert declared & set(WITHDRAWN_RULES) == set()
    assert all(reason for reason in WITHDRAWN_RULES.values())


def test_the_rules_in_force_are_the_occupancy_subset_and_the_others_are_vocabulary_only() -> None:
    # What a derived plan needs: it places nothing over a commitment, an absolute window, the
    # frame, or something it already placed. The remaining nine are named by the enum and checked
    # by nothing yet, which is a value at the call site rather than a hidden state of the module.
    space = PartialPlan.of(inputs(anchors=(an_anchor(),)))
    reported = {
        rejection.rule
        for rule in OCCUPANCY_RULES
        if (rejection := rule(a_candidate(), space)) is not None
    }

    assert len(OCCUPANCY_RULES) == 4
    assert reported <= {
        ConstraintRule.ANCHOR_OVERLAP,
        ConstraintRule.FORBIDDEN_WINDOW,
        ConstraintRule.FRAME_OVERLAP,
        ConstraintRule.BLOCK_OVERLAP,
    }


def test_a_candidate_over_an_anchor_is_rejected_by_the_commitment_that_holds_the_time() -> None:
    anchor = an_anchor(interval=between(10, 11), title="Kontron Placement Interview")
    candidate = a_candidate(between(10.5, 11.5))

    rejection = ConstraintCheck().check(candidate, PartialPlan.of(inputs(anchors=(anchor,))))

    assert rejection is not None
    assert (rejection.rule, rejection.window, rejection.detail) == (
        ConstraintRule.ANCHOR_OVERLAP,
        candidate.interval,
        "Kontron Placement Interview",
    )


def test_a_candidate_over_an_absolute_window_is_rejected_and_a_scoped_one_is_not() -> None:
    # H2 reads only the windows that forbid every Area. A window scoped to named Areas is H13's,
    # and reading it here would be the two readings of one window drifting apart again.
    absolute = a_recovery_window(interval=between(11, 12), label="recovery · Lecture")
    scoped = a_recovery_window(
        interval=between(11, 12), scope=ForbiddenScope.AREAS, forbidden_area_ids=(FITNESS,)
    )
    candidate = a_candidate(between(11, 11.5))

    refused = ConstraintCheck().check(
        candidate, PartialPlan.of(inputs(forbidden_windows=(absolute,)))
    )
    allowed = ConstraintCheck().check(
        candidate, PartialPlan.of(inputs(forbidden_windows=(scoped,)))
    )

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

    rejection = ConstraintCheck().check(
        a_candidate(between(9, 10), area_id=CAREER),
        PartialPlan.of(inputs(forbidden_windows=(buffer,))),
    )

    assert rejection is not None
    assert rejection.rule is ConstraintRule.FORBIDDEN_WINDOW


def test_a_candidate_over_the_frame_is_rejected_by_the_routine_that_bounds_the_day() -> None:
    entry = a_frame_entry(interval=between(23, 31), title="Sleep")

    rejection = ConstraintCheck().check(
        a_candidate(between(23.5, 24)), PartialPlan.of(inputs(frame=(entry,)))
    )

    assert rejection is not None
    assert (rejection.rule, rejection.detail) == (ConstraintRule.FRAME_OVERLAP, "Sleep")


def test_a_candidate_over_an_inherited_frame_span_is_rejected_without_naming_a_routine() -> None:
    # The week that owns a boundary-crossing occurrence holds the whole interval and materializes
    # the one block, so this week carries the span and not the name. The rejection says so rather
    # than borrowing a title from a different occurrence.
    overhang = between(0, 7)

    rejection = ConstraintCheck().check(
        a_candidate(between(6, 8)), PartialPlan.of(inputs(frame_overhang=(overhang,)))
    )

    assert rejection is not None
    assert (rejection.rule, rejection.detail) == (ConstraintRule.FRAME_OVERLAP, INHERITED_FRAME)


def test_a_candidate_over_something_already_placed_is_rejected_by_what_holds_the_span() -> None:
    placed = Placement(
        binding=BindingRef.for_anchor_prep(an_anchor().anchor_id),
        interval=between(8, 9),
        title="Interview prep",
        area_id=CAREER,
    )

    rejection = ConstraintCheck().check(
        a_candidate(between(8.5, 9.5)), PartialPlan.of(inputs()).with_placed(placed)
    )

    assert rejection is not None
    assert (rejection.rule, rejection.detail) == (
        ConstraintRule.BLOCK_OVERLAP,
        "Interview prep",
    )


def test_a_candidate_that_breaks_nothing_is_accepted_with_nothing_to_report() -> None:
    # Acceptance is the absence of a rejection rather than a value: there is nothing an accepted
    # placement has to say, and a caller that must not lose a rejection reads `is not None`.
    state = PartialPlan.of(
        inputs(anchors=(an_anchor(interval=between(10, 11)),), frame=(a_frame_entry(),))
    )

    assert ConstraintCheck().check(a_candidate(between(12, 13)), state) is None


def test_a_candidate_abutting_a_commitment_is_not_overlapping_it() -> None:
    # The boundary the whole occupancy half rests on: a transit block that ends exactly when its
    # commitment starts is the ordinary case, not a collision.
    state = PartialPlan.of(inputs(anchors=(an_anchor(interval=between(10, 11)),)))

    assert ConstraintCheck().check(a_candidate(between(9.5, 10)), state) is None
    assert ConstraintCheck().check(a_candidate(between(11, 11.5)), state) is None


def test_the_first_rule_a_candidate_breaks_is_the_one_reported() -> None:
    # One rejection per candidate, in the table's own order, because the clause budget renders two
    # rejected windows per block and each names one rule. The order is the table's rather than the
    # order the checks happened to run in.
    state = PartialPlan.of(
        inputs(
            anchors=(an_anchor(interval=between(10, 11)),),
            frame=(a_frame_entry(interval=between(10, 11)),),
        )
    )

    rejection = ConstraintCheck().check(a_candidate(between(10, 10.5)), state)

    assert rejection is not None
    assert rejection.rule is ConstraintRule.ANCHOR_OVERLAP


def test_the_state_holds_its_members_in_span_order_whatever_order_they_arrived_in() -> None:
    # Two members overlapping one candidate would otherwise be reported by whichever the inputs
    # happened to list first, so permuting an input list would change a reason clause while
    # changing no placement.
    early = an_anchor(interval=between(9, 11), title="Lecture")
    late = an_anchor(interval=between(10, 12), title="Kontron Placement Interview")

    forwards = ConstraintCheck().check(
        a_candidate(between(10.5, 10.75)), PartialPlan.of(inputs(anchors=(early, late)))
    )
    backwards = ConstraintCheck().check(
        a_candidate(between(10.5, 10.75)), PartialPlan.of(inputs(anchors=(late, early)))
    )

    assert forwards is not None
    assert forwards == backwards
    assert forwards.detail == "Lecture"


def test_a_rejection_becomes_a_log_row_naming_the_binding_that_was_refused() -> None:
    # The block was never placed, so the row carries the binding rather than a block: what the log
    # has to answer later is which content could not be placed and why.
    candidate = a_candidate(between(10, 11))
    rejection = ConstraintCheck().check(candidate, PartialPlan.of(inputs(anchors=(an_anchor(),))))

    assert rejection is not None
    assert BlockedCandidate.of(candidate.binding, rejection) == BlockedCandidate(
        binding=candidate.binding,
        window=rejection.window,
        rule=rejection.rule,
        detail=rejection.detail,
    )
