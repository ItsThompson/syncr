"""The boundary between a proposal diff as a value and as a stored column, in both directions.

``pending_proposals.proposal_diff`` is what the grid renders proposal targets from, so the shape it
holds is a contract rather than an implementation detail. Three groups.

**A round trip is an equality**, over all three change classes at once and over the optional halves
of a change: a change with no Area, and the pair of placements each class carries.

**What is NOT written.** A change's identity is derived from the week and the binding, and the week
is the row's own, so neither is in the serialized form. A stored id would be a cache of the
derivation and could only disagree with it.

**A row that cannot be rebuilt says so where it is read**, naming the position of the change it
could not rebuild, because a diff's changes are not named.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from syncr_api.plans.errors import StoredDocumentCorrupt
from syncr_api.plans.stored_proposals import (
    ADDED,
    AFTER,
    BEFORE,
    MOVED,
    REMOVED,
    read_proposal_diff,
    stored_proposal_diff,
)
from syncr_domain.identity import Origin
from syncr_domain.proposals import BlockChange, ProposalDiff
from syncr_domain.weeks import IsoWeek
from tests.plan_documents import WEEK, a_block, between

if TYPE_CHECKING:
    from syncr_api.core.columns import JsonObject


def a_diff() -> ProposalDiff:
    """One change of each class, so a round trip covers all three at once."""
    gym = a_block(Origin.HABIT, interval=between(9, 10))
    return ProposalDiff(
        added=(BlockChange.added(a_block(Origin.TASK, interval=between(14, 15))),),
        removed=(BlockChange.removed(a_block(Origin.ANCHOR, interval=between(19, 20))),),
        moved=(BlockChange.moved(live=gym, candidate=replace(gym, interval=between(17, 18))),),
    )


def test_a_diff_written_and_read_back_is_the_same_value() -> None:
    diff = a_diff()

    assert read_proposal_diff(stored_proposal_diff(diff), WEEK) == diff


def test_a_change_with_no_area_round_trips_as_one() -> None:
    """A commitment carries no Area, so the column carries a null rather than a missing key."""
    diff = ProposalDiff(removed=(BlockChange.removed(a_block(Origin.ANCHOR)),))

    (change,) = read_proposal_diff(stored_proposal_diff(diff), WEEK).removed

    assert change.area_id is None


def test_each_class_keeps_the_placements_its_list_means() -> None:
    stored = stored_proposal_diff(a_diff())

    read = read_proposal_diff(stored, WEEK)

    assert (read.added[0].before, read.added[0].after) == (None, between(14, 15))
    assert (read.removed[0].before, read.removed[0].after) == (between(19, 20), None)
    assert (read.moved[0].before, read.moved[0].after) == (between(9, 10), between(17, 18))


def test_neither_an_identity_nor_a_week_is_written() -> None:
    stored = stored_proposal_diff(a_diff())

    for change in _every_change(stored):
        assert "block_id" not in change
        assert "iso_week" not in change


def test_a_change_is_rebuilt_against_the_week_its_row_names() -> None:
    stored = stored_proposal_diff(a_diff())

    read = read_proposal_diff(stored, IsoWeek(2026, 9))

    assert {str(change.iso_week) for change in read.changes()} == {"2026-W09"}
    assert read.added[0].block_id != a_diff().added[0].block_id


def test_a_change_in_a_list_that_is_not_a_list_is_refused_naming_the_key() -> None:
    with pytest.raises(StoredDocumentCorrupt, match=MOVED):
        read_proposal_diff({ADDED: [], REMOVED: [], MOVED: {}}, WEEK)


def test_a_change_whose_binding_names_no_entity_is_refused_naming_its_position() -> None:
    stored = stored_proposal_diff(a_diff())
    stored[REMOVED][0]["binding"]["entity_id"] = "not a uuid"

    with pytest.raises(StoredDocumentCorrupt, match=r"removed\[0\]"):
        read_proposal_diff(stored, WEEK)


def test_a_stored_move_that_moves_nothing_is_refused_by_the_value_type() -> None:
    stored = stored_proposal_diff(a_diff())
    stored[MOVED][0][BEFORE] = stored[MOVED][0][AFTER]

    with pytest.raises(StoredDocumentCorrupt, match="the proposal diff"):
        read_proposal_diff(stored, WEEK)


def test_a_stored_addition_carrying_a_placement_it_replaced_is_refused() -> None:
    stored = stored_proposal_diff(a_diff())
    stored[ADDED][0][BEFORE] = stored[ADDED][0][AFTER]

    with pytest.raises(StoredDocumentCorrupt, match="the proposal diff"):
        read_proposal_diff(stored, WEEK)


def test_an_empty_diff_round_trips_as_an_empty_one() -> None:
    stored = stored_proposal_diff(ProposalDiff())

    assert stored == {ADDED: [], REMOVED: [], MOVED: []}
    assert read_proposal_diff(stored, WEEK).is_empty()


def test_a_diff_naming_one_block_twice_is_refused_where_it_is_read() -> None:
    stored = stored_proposal_diff(a_diff())
    stored[ADDED].append(stored[ADDED][0])

    with pytest.raises(StoredDocumentCorrupt, match="the proposal diff"):
        read_proposal_diff(stored, WEEK)


def _every_change(stored: JsonObject) -> list[JsonObject]:
    return [change for key in (ADDED, REMOVED, MOVED) for change in stored[key]]
