"""The outcome projection: which states are a completion, which is a miss, and the partition.

The partition is the whole content of this module, and it is what both derivations rest on. It
is asserted mechanically rather than by listing five states twice: a state added to the
vocabulary and left out of both sets would otherwise be silently neither, and both derivations
would ignore it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from syncr_domain.outcomes import (
    COMPLETION_STATES,
    MISS_STATE,
    HabitOutcome,
    OutcomeState,
)

AT = datetime(2026, 8, 3, 6, 0, tzinfo=UTC)


def outcome(state: OutcomeState, *, confirmed: bool = True) -> HabitOutcome:
    return HabitOutcome(
        habit_id=uuid4(),
        occurrence_key="00",
        state=state,
        occurred_at=AT,
        confirmed_at=AT + timedelta(hours=12) if confirmed else None,
    )


def test_the_five_states_are_the_whole_vocabulary() -> None:
    assert {state.value for state in OutcomeState} == {
        "presumed",
        "completed",
        "partial",
        "skipped",
        "moved",
    }


def test_the_completion_set_and_the_miss_partition_every_state() -> None:
    """A sixth state added to the vocabulary joins one side or fails here.

    The completion set is DERIVED from the miss rather than listed, so the two cannot drift
    and a new state cannot fall outside both.
    """
    assert COMPLETION_STATES | {MISS_STATE} == set(OutcomeState)
    assert MISS_STATE not in COMPLETION_STATES
    assert len(COMPLETION_STATES) == 4


def test_the_one_miss_state_is_the_one_that_says_the_content_was_not_done() -> None:
    assert MISS_STATE is OutcomeState.SKIPPED


@pytest.mark.parametrize("state", sorted(COMPLETION_STATES))
def test_a_confirmed_completion_state_reads_as_a_completion_and_not_as_a_miss(
    state: OutcomeState,
) -> None:
    recorded = outcome(state)

    assert recorded.is_confirmed_completion
    assert not recorded.is_confirmed_miss


def test_a_confirmed_skip_reads_as_a_miss_and_not_as_a_completion() -> None:
    recorded = outcome(MISS_STATE)

    assert recorded.is_confirmed_miss
    assert not recorded.is_confirmed_completion


@pytest.mark.parametrize("state", sorted(OutcomeState))
def test_an_unconfirmed_row_is_neither_a_completion_nor_a_miss(state: OutcomeState) -> None:
    """The user disengaged from the day, so the row says nothing yet in either direction."""
    unconfirmed = outcome(state, confirmed=False)

    assert not unconfirmed.is_confirmed
    assert not unconfirmed.is_confirmed_completion
    assert not unconfirmed.is_confirmed_miss


def test_a_presumed_row_reads_as_a_completion_only_once_the_day_is_confirmed() -> None:
    """`presumed` is the default and it teaches nothing until the user confirms the day."""
    assert not outcome(OutcomeState.PRESUMED, confirmed=False).is_confirmed_completion
    assert outcome(OutcomeState.PRESUMED).is_confirmed_completion
