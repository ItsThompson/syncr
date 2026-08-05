"""What a proposed change is, and what a set of them refuses to be.

Three groups.

**A change derives its identity rather than storing one.** There is no ``block_id`` field and no
argument to pass, so a change and the block it names cannot disagree about which block that is.
The structural assertion is the point: a rule enforced by the absence of a field cannot be broken.

**Which list a change is in is what kind of change it is**, and the diff enforces the pair of
placements each list means, in both directions. An addition carrying a placement it replaces and a
move missing one are both refused, because each renders something the plan is not proposing.

**A diff is one week's, and it proposes one thing per block.** Both are asserted by building a
diff that breaks them, because both make the pairing the grid and the approval path perform
ambiguous.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from syncr_domain.identity import BindingKind, Origin, block_id
from syncr_domain.proposals import BlockChange, ProposalDiff, ProposalError
from syncr_domain.weeks import IsoWeek
from tests.plan_values import a_binding, a_block, a_block_of, between


def test_a_change_derives_the_block_it_names_from_the_week_and_the_binding() -> None:
    block = a_block()

    change = BlockChange.added(block)

    assert change.block_id == block_id(block.iso_week, block.binding)
    assert change.block_id == block.id


def test_a_change_has_no_field_holding_an_identity() -> None:
    fields = {field.name for field in BlockChange.__dataclass_fields__.values()}

    assert "block_id" not in fields


def test_an_addition_states_where_the_candidate_wants_the_block_and_nothing_it_replaced() -> None:
    block = a_block(interval=between(9, 10))

    change = BlockChange.added(block)

    assert change.after == between(9, 10)
    assert change.before is None
    assert change.title == block.title
    assert change.area_id == block.area_id
    assert change.reason == block.reason


def test_a_removal_states_where_the_block_was_and_carries_the_live_plans_own_reason() -> None:
    block = a_block(interval=between(9, 10))

    change = BlockChange.removed(block)

    assert change.before == between(9, 10)
    assert change.after is None
    assert change.reason == block.reason


def test_a_move_states_both_placements_and_describes_what_the_candidate_wants() -> None:
    binding = a_binding()
    live = a_block(binding=binding, interval=between(9, 10), title="Gym · Legs")
    candidate = a_block(binding=binding, interval=between(17, 18), title="Gym · Push")

    change = BlockChange.moved(live=live, candidate=candidate)

    assert (change.before, change.after) == (between(9, 10), between(17, 18))
    assert change.title == "Gym · Push"


def test_a_move_of_two_different_blocks_is_refused() -> None:
    live = a_block(binding=a_binding(), interval=between(9, 10))
    candidate = a_block(binding=a_binding(), interval=between(17, 18))

    with pytest.raises(ProposalError, match="is not the same block as"):
        BlockChange.moved(live=live, candidate=candidate)


def test_an_empty_diff_proposes_nothing() -> None:
    assert ProposalDiff().is_empty()


def test_a_diff_holding_any_change_proposes_something() -> None:
    diff = ProposalDiff(removed=(BlockChange.removed(a_block()),))

    assert not diff.is_empty()
    assert list(diff.changes()) == list(diff.removed)


def test_every_change_is_reachable_whichever_list_it_is_in() -> None:
    binding = a_binding(BindingKind.TASK)
    live = a_block_of(Origin.TASK, binding=binding, interval=between(9, 10))
    candidate = a_block_of(Origin.TASK, binding=binding, interval=between(11, 12))

    diff = ProposalDiff(
        added=(BlockChange.added(a_block()),),
        removed=(BlockChange.removed(a_block_of(Origin.FRAME)),),
        moved=(BlockChange.moved(live=live, candidate=candidate),),
    )

    assert len(list(diff.changes())) == 3


def test_an_addition_that_states_a_placement_it_replaced_is_refused() -> None:
    displaced = replace(BlockChange.added(a_block()), before=between(8, 9))

    with pytest.raises(ProposalError, match=r"an addition .* carries placement it replaces"):
        ProposalDiff(added=(displaced,))


def test_an_addition_stating_no_placement_at_all_is_refused() -> None:
    nowhere = replace(BlockChange.added(a_block()), after=None)

    with pytest.raises(ProposalError, match=r"an addition .* states no placement it wants"):
        ProposalDiff(added=(nowhere,))


def test_a_removal_that_states_where_the_candidate_wants_the_block_is_refused() -> None:
    kept = replace(BlockChange.removed(a_block()), after=between(11, 12))

    with pytest.raises(ProposalError, match=r"a removal .* carries placement it wants"):
        ProposalDiff(removed=(kept,))


def test_a_move_missing_either_placement_is_refused() -> None:
    binding = a_binding()
    change = BlockChange.moved(
        live=a_block(binding=binding, interval=between(9, 10)),
        candidate=a_block(binding=binding, interval=between(17, 18)),
    )

    with pytest.raises(ProposalError, match=r"a move .* states no placement it replaces"):
        ProposalDiff(moved=(replace(change, before=None),))
    with pytest.raises(ProposalError, match=r"a move .* states no placement it wants"):
        ProposalDiff(moved=(replace(change, after=None),))


def test_a_change_in_the_wrong_list_is_refused_naming_both_halves() -> None:
    with pytest.raises(ProposalError, match="carries placement it replaces and states no"):
        ProposalDiff(added=(BlockChange.removed(a_block()),))


def test_a_move_that_leaves_the_block_where_it_is_is_refused() -> None:
    binding = a_binding()
    live = a_block(binding=binding, interval=between(9, 10))
    unmoved = replace(BlockChange.moved(live=live, candidate=live), after=between(9, 10))

    with pytest.raises(ProposalError, match="leaves it where it is"):
        ProposalDiff(moved=(unmoved,))


def test_a_diff_naming_two_weeks_is_refused() -> None:
    here = BlockChange.added(a_block())
    elsewhere = replace(BlockChange.added(a_block(binding=a_binding())), iso_week=IsoWeek(2026, 9))

    with pytest.raises(ProposalError, match="2026-W07, 2026-W09"):
        ProposalDiff(added=(here, elsewhere))


def test_a_block_named_twice_in_one_diff_is_refused_across_two_lists() -> None:
    binding = a_binding()
    block = a_block(binding=binding, interval=between(9, 10))
    moved = BlockChange.moved(
        live=block, candidate=a_block(binding=binding, interval=between(17, 18))
    )

    with pytest.raises(ProposalError, match="appears twice"):
        ProposalDiff(removed=(BlockChange.removed(block),), moved=(moved,))


def test_a_block_named_twice_in_one_list_is_refused() -> None:
    block = a_block()

    with pytest.raises(ProposalError, match="appears twice"):
        ProposalDiff(added=(BlockChange.added(block), BlockChange.added(block)))


def test_the_lists_are_tuples_whatever_the_caller_passed() -> None:
    """So a diff cannot be changed through the list it was built from."""
    changes = [BlockChange.added(a_block())]

    diff = ProposalDiff(added=changes)  # type: ignore[arg-type]

    changes.clear()
    assert len(diff.added) == 1
    assert isinstance(diff.added, tuple)
