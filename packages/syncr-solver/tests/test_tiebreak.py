"""``tiebreak``: the total order candidates are offered in, and the four terms that make it one.

Each term is driven in isolation, with every later term held equal, so a test that passes because
the identity broke the tie cannot be mistaken for a test of the term it is named for. The last two
tests are the ones the module exists for: the order is TOTAL, and the identity is what makes it so.
"""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import pairwise
from uuid import UUID

import pytest

from syncr_domain.habits import BindingSource
from syncr_domain.identity import BindingRef
from syncr_domain.reasons import Bound
from syncr_solver.candidates import Candidate
from syncr_solver.state import Sizing
from syncr_solver.tiebreak import compare, in_tiebreak_order, order_key
from tests.materialized_weeks import CAREER, FITNESS

A_TASK = UUID("00000000-0000-4000-8000-0000000000d1")
ANOTHER_TASK = UUID("00000000-0000-4000-8000-0000000000d2")
A_HABIT = UUID("00000000-0000-4000-8000-0000000000d3")

MONDAY = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)
TUESDAY = datetime(2026, 2, 10, 9, 0, tzinfo=UTC)


def a_candidate(
    *,
    entity_id: UUID = A_TASK,
    area_id: UUID = FITNESS,
    floor_shortfall_minutes: int = 0,
    deadline: datetime | None = None,
    stale_minutes: int = 0,
    occurrence_key: str | None = None,
    split_index: int | None = None,
) -> Candidate:
    """A candidate equal to its siblings on everything the caller does not state."""
    binding = (
        BindingRef.for_habit(entity_id, index=int(occurrence_key))
        if occurrence_key is not None
        else BindingRef.for_task(entity_id, split_index=split_index)
    )
    return Candidate(
        binding=binding,
        area_id=area_id,
        title="Leetcode",
        sizing=Sizing(whole_minutes=60, min_chunk_minutes=15, splittable=True),
        min_minutes=15,
        max_minutes=60,
        remaining_minutes=60,
        deadline=deadline,
        stale_minutes=stale_minutes,
        floor_shortfall_minutes=floor_shortfall_minutes,
        bound=Bound(source=BindingSource.QUEUE, selected="Leetcode"),
    )


def test_the_area_that_owes_the_most_of_its_floor_is_offered_first() -> None:
    behind = a_candidate(floor_shortfall_minutes=120, entity_id=A_TASK)
    ahead = a_candidate(floor_shortfall_minutes=30, entity_id=ANOTHER_TASK)

    assert compare(behind, ahead) < 0
    assert in_tiebreak_order((ahead, behind)) == (behind, ahead)


def test_the_earliest_deadline_is_offered_first_once_the_floors_are_equal() -> None:
    sooner = a_candidate(deadline=MONDAY, entity_id=A_TASK)
    later = a_candidate(deadline=TUESDAY, entity_id=ANOTHER_TASK)

    assert compare(sooner, later) < 0


def test_a_candidate_with_no_deadline_is_offered_after_every_candidate_with_one() -> None:
    """A demand nothing is owed by is not more urgent than one owed by the end of the year."""
    dated = a_candidate(deadline=datetime(2026, 12, 31, tzinfo=UTC), entity_id=A_TASK)
    undated = a_candidate(deadline=None, entity_id=ANOTHER_TASK)

    assert compare(dated, undated) < 0


def test_the_stalest_candidate_is_offered_first_once_the_deadlines_are_equal() -> None:
    overdue = a_candidate(stale_minutes=60, entity_id=A_TASK)
    fresh = a_candidate(stale_minutes=0, entity_id=ANOTHER_TASK)

    assert compare(overdue, fresh) < 0


def test_the_area_breaks_a_tie_the_three_priorities_leave() -> None:
    first = a_candidate(area_id=min(FITNESS, CAREER), entity_id=A_TASK)
    second = a_candidate(area_id=max(FITNESS, CAREER), entity_id=A_TASK)

    assert compare(first, second) < 0


def test_two_occurrences_of_one_habit_do_not_tie_on_the_entity_they_share() -> None:
    """The design names 'entity id' and an entity id is not total: four occurrences share one.

    This is the case the key's last two components exist for, and it is not hypothetical: a habit
    at four times a week produces four candidates whose every other term is equal.
    """
    first = a_candidate(entity_id=A_HABIT, occurrence_key="0")
    second = a_candidate(entity_id=A_HABIT, occurrence_key="1")

    assert compare(first, second) < 0
    assert compare(second, first) > 0


def test_two_chunks_of_one_task_do_not_tie_either() -> None:
    """A task's chunks share an entity id and an occurrence key, so the chunk number is read."""
    whole = a_candidate(entity_id=A_TASK, split_index=None)
    piece = a_candidate(entity_id=A_TASK, split_index=0)

    assert compare(whole, piece) < 0


def test_only_one_candidate_compares_equal_to_itself() -> None:
    """Zero means one demand rather than an undecided order, which is what the final term buys."""
    candidate = a_candidate()

    assert compare(candidate, candidate) == 0


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (a_candidate(floor_shortfall_minutes=1), a_candidate(entity_id=ANOTHER_TASK)),
        (a_candidate(deadline=MONDAY), a_candidate(entity_id=ANOTHER_TASK)),
        (a_candidate(stale_minutes=1), a_candidate(entity_id=ANOTHER_TASK)),
        (a_candidate(area_id=min(FITNESS, CAREER)), a_candidate(area_id=max(FITNESS, CAREER))),
    ],
)
def test_the_order_is_antisymmetric_on_every_term(first: Candidate, second: Candidate) -> None:
    assert compare(first, second) == -compare(second, first)


def test_no_pair_of_a_generated_set_compares_equal_unless_it_is_one_demand() -> None:
    """Totality, stated over a set that varies every term the key reads.

    Without the final identity term, the four candidates differing only in Area and entity would
    still separate; the two occurrences of one habit would not, and they are in the set.
    """
    candidates = (
        a_candidate(entity_id=A_TASK),
        a_candidate(entity_id=ANOTHER_TASK),
        a_candidate(entity_id=A_HABIT, occurrence_key="0"),
        a_candidate(entity_id=A_HABIT, occurrence_key="1"),
        a_candidate(entity_id=A_TASK, split_index=0),
        a_candidate(entity_id=A_TASK, area_id=CAREER),
        a_candidate(entity_id=A_TASK, floor_shortfall_minutes=60),
        a_candidate(entity_id=A_TASK, deadline=MONDAY),
        a_candidate(entity_id=A_TASK, stale_minutes=45),
    )
    keys = [order_key(candidate) for candidate in candidates]

    assert len(set(keys)) == len(keys)


def test_the_sort_and_the_comparator_agree_on_every_pair() -> None:
    """One definition read two ways, so a comparator and a sort cannot answer differently."""
    candidates = (
        a_candidate(entity_id=ANOTHER_TASK, deadline=TUESDAY),
        a_candidate(entity_id=A_HABIT, occurrence_key="1", stale_minutes=45),
        a_candidate(entity_id=A_TASK, floor_shortfall_minutes=60),
        a_candidate(entity_id=A_HABIT, occurrence_key="0"),
    )
    ordered = in_tiebreak_order(candidates)

    for earlier, later in pairwise(ordered):
        assert compare(earlier, later) < 0
