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

from syncr_domain.identity import BindingRef, index_occurrence_key
from syncr_domain.outcomes import (
    COMPLETION_STATES,
    MISS_STATE,
    HabitOutcome,
    OutcomeError,
    OutcomeState,
)

AT = datetime(2026, 8, 3, 6, 0, tzinfo=UTC)
HABIT = uuid4()


def outcome(state: OutcomeState, *, confirmed: bool = True) -> HabitOutcome:
    return HabitOutcome(
        habit_id=uuid4(),
        occurrence_key="00",
        state=state,
        occurred_at=AT,
        confirmed_at=AT + timedelta(hours=12) if confirmed else None,
    )


def outcome_keyed(occurrence_key: str) -> HabitOutcome:
    return HabitOutcome(
        habit_id=HABIT,
        occurrence_key=occurrence_key,
        state=OutcomeState.COMPLETED,
        occurred_at=AT,
        confirmed_at=AT,
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


class TestTheOccurrenceKeyIsTheOneKeyABlockCouldCarry:
    """One derivation of a habit occurrence key exists, and this row is checked against it.

    This is a real defect class rather than tidiness: an outcome is matched to a block by its
    binding, so a key no block can carry means the match never fires and reports nothing. Nothing
    performs that match yet, which is why the two spellings are held together now rather than
    after the first silent miss.
    """

    @pytest.mark.parametrize("index", [0, 1, 12, 200])
    def test_the_derivation_of_a_key_is_what_a_row_may_hold(self, index: int) -> None:
        row = outcome_keyed(index_occurrence_key(index))

        assert row.occurrence_key == index_occurrence_key(index)

    @pytest.mark.parametrize(
        "key",
        ["2", "٢", "1_0", " 2", "-1", "", "2026-02-09", "out"],
        ids=[
            "an unpadded index",
            "an Arabic-Indic digit",
            "an underscore separator",
            "a leading space",
            "a negative index",
            "no key at all",
            "a date",
            "a transit leg",
        ],
    )
    def test_a_key_no_block_could_carry_is_refused(self, key: str) -> None:
        """``int('٢')`` is 2, so a check that only parsed would accept a key nothing produces."""
        with pytest.raises(OutcomeError, match="zero-padded index"):
            outcome_keyed(key)

    def test_the_two_statements_of_the_key_cannot_disagree(self) -> None:
        """The pair the reconciliation with the cursor's precondition rests on.

        A row's key and a block's key are now checked by the same derivation, so a key one
        accepts and the other refuses is not representable.
        """
        for index in range(200):
            derived = index_occurrence_key(index)

            assert outcome_keyed(derived).occurrence_key == derived
            assert BindingRef.for_habit(HABIT, index=index).occurrence_key == derived
