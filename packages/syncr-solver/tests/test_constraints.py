"""The hard-constraint inventory, and the checker that reads a tuple of it.

Stated over the INVENTORY rather than over behaviour: the enum, the table, the withdrawn numbers
and the rule functions are compared with each other in every direction, so a rule added without a
name fails, a name added without a rule fails, a number both declared and withdrawn fails, and a
rule reporting a member other than its own row's fails. That is what makes each rule's own suite an
assertion about behaviour rather than about vocabulary.

Each rule is driven at the boundary it exists for in the module named after what it reads:
``test_occupancy``, ``test_shape``, ``test_allocation`` and ``test_immovability``. The property per
rule, and the demonstration that each property can fail, are in ``test_hard_rules``.
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
from syncr_solver.rules import HARD_RULES, RULE_BY_NAME
from syncr_solver.state import PartialPlan
from tests.materialized_weeks import a_candidate, a_frame_entry, an_anchor, between, inputs

# The highest number the table reaches. Two of the fifteen were withdrawn, and the numbering is
# preserved rather than compacted, so this is not the count of rules.
HIGHEST_NUMBER = 15


def a_check() -> ConstraintCheck:
    """The checker holding every hard constraint, which is what a solve states."""
    return ConstraintCheck(HARD_RULES)


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


def test_every_name_is_checked_by_exactly_one_rule_and_the_order_is_the_tables() -> None:
    # The third statement of the inventory, crossed against the other two. A member the mapping
    # does not hold cannot reach `HARD_RULES` at all, because the table is read by key, so what is
    # left for this to catch is a member the mapping holds and the table does not order.
    assert set(RULE_BY_NAME) == set(ConstraintRule)
    assert len(HARD_RULES) == len(HARD_CONSTRAINTS)
    assert tuple(RULE_BY_NAME[row.rule] for row in HARD_CONSTRAINTS) == HARD_RULES


def test_the_rules_a_derived_plan_needs_are_the_ones_about_a_span_already_spent() -> None:
    # A derivation chooses no content, sizes nothing and moves nothing, so the only way one of its
    # placements can be illegal is that the span is already spent: by a commitment, an absolute
    # window, the frame, something this pass placed, or a window forbidding the block's own Area.
    # The other eight are named by the enum and are a longer tuple at a solve's own call site.
    assert set(OCCUPANCY_RULES) == {
        RULE_BY_NAME[rule]
        for rule in (
            ConstraintRule.ANCHOR_OVERLAP,
            ConstraintRule.FORBIDDEN_WINDOW,
            ConstraintRule.FRAME_OVERLAP,
            ConstraintRule.BLOCK_OVERLAP,
            ConstraintRule.FORBIDDEN_AREA,
        )
    }
    assert tuple(OCCUPANCY_RULES) == tuple(
        rule for rule in HARD_RULES if rule in set(OCCUPANCY_RULES)
    )


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
