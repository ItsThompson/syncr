"""The hard-constraint inventory, and the checker that reads a tuple of it.

Stated over the INVENTORY rather than over behaviour: the enum, the table and the withdrawn numbers
are compared with each other in both directions, so a rule added without a name fails, a name added
without a rule fails, and a number that is both declared and withdrawn fails. That is what lets a
later slice add the rules a derived plan does not need as behaviour rather than as vocabulary.

Each rule is driven at the boundary it exists for in the module named after what it reads, starting
with ``test_occupancy`` for the ones about a span already spent.
"""

from __future__ import annotations

from syncr_solver.constraints import (
    HARD_CONSTRAINTS,
    WITHDRAWN_RULES,
    BlockedCandidate,
    ConstraintCheck,
    ConstraintRule,
)
from syncr_solver.occupancy import OCCUPANCY_RULES
from syncr_solver.state import PartialPlan
from tests.materialized_weeks import a_candidate, a_frame_entry, an_anchor, between, inputs

# The highest number the table reaches. Two of the fifteen were withdrawn, and the numbering is
# preserved rather than compacted, so this is not the count of rules.
HIGHEST_NUMBER = 15


def a_check() -> ConstraintCheck:
    """The checker holding the rules a derived plan needs, which the caller always states."""
    return ConstraintCheck(OCCUPANCY_RULES)


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
    # frame, or something it already placed. The remaining rules are named by the enum and checked
    # by nothing yet, which is a value at the call site rather than a hidden state of the module.
    space = PartialPlan.of(inputs(anchors=(an_anchor(),)))
    reported = {
        rejection.rule
        for rule in OCCUPANCY_RULES
        if (rejection := rule(a_candidate(), space)) is not None
    }

    assert len(OCCUPANCY_RULES) == 4
    assert reported == {ConstraintRule.ANCHOR_OVERLAP}


def test_a_candidate_that_breaks_nothing_is_accepted_with_nothing_to_report() -> None:
    # Acceptance is the absence of a rejection rather than a value: there is nothing an accepted
    # placement has to say, and a caller that must not lose a rejection reads `is not None`.
    state = PartialPlan.of(
        inputs(anchors=(an_anchor(interval=between(10, 11)),), frame=(a_frame_entry(),))
    )

    assert a_check().check(a_candidate(between(12, 13)), state) is None


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

    rejection = a_check().check(a_candidate(between(10, 10.5)), state)

    assert rejection is not None
    assert rejection.rule is ConstraintRule.ANCHOR_OVERLAP


def test_a_rejection_becomes_a_log_row_naming_the_binding_that_was_refused() -> None:
    # The block was never placed, so the row carries the binding rather than a block: what the log
    # has to answer later is which content could not be placed and why.
    candidate = a_candidate(between(10, 11))
    rejection = a_check().check(candidate, PartialPlan.of(inputs(anchors=(an_anchor(),))))

    assert rejection is not None
    assert BlockedCandidate.of(candidate.binding, rejection) == BlockedCandidate(
        binding=candidate.binding,
        window=rejection.window,
        rule=rejection.rule,
        detail=rejection.detail,
    )
