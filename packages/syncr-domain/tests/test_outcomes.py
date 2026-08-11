"""The outcome projection: which states are a completion, which is a miss, and what each attributes.

Two partitions of the same five states live here, and neither is asserted by listing the states
twice. The completion partition is what both derivations rest on: a state added to the vocabulary
and left out of both sets would be silently neither, and both derivations would ignore it. The
attribution table is what the probe's demand rests on, and it is total over the vocabulary for the
same reason.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from syncr_domain.identity import BindingRef, index_occurrence_key
from syncr_domain.intervals import Interval
from syncr_domain.outcomes import (
    COMPLETION_STATES,
    MIN_ACTUAL_MINUTES,
    MISS_STATE,
    HabitOutcome,
    OutcomeError,
    OutcomeState,
    RecordedOutcome,
    attributed_span,
)

AT = datetime(2026, 8, 3, 6, 0, tzinfo=UTC)
HABIT = uuid4()

# One planned hour, so a partial's prefix and the planned span are told apart by their ends.
PLANNED = Interval(AT, AT + timedelta(hours=1))

# Two hours later than planned, and half as long, so neither bound nor the length coincides.
ELSEWHERE = Interval(AT + timedelta(hours=2), AT + timedelta(hours=2, minutes=30))

BINDING = BindingRef.for_habit(HABIT, index=0)


def recorded(
    state: OutcomeState,
    *,
    actual_minutes: int | None = None,
    actual_interval: Interval | None = None,
) -> RecordedOutcome:
    """One block's outcome, with whatever its state carries supplied by the caller."""
    return RecordedOutcome(
        binding=BINDING,
        state=state,
        actual_minutes=actual_minutes,
        actual_interval=actual_interval,
    )


def outcome(state: OutcomeState, *, confirmed: bool = True, make_up: bool = False) -> HabitOutcome:
    return HabitOutcome(
        habit_id=uuid4(),
        occurrence_key="00",
        state=state,
        occurred_at=AT,
        confirmed_at=AT + timedelta(hours=12) if confirmed else None,
        is_make_up=make_up,
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


def test_the_mark_s_default_is_declared_on_the_field() -> None:
    """Read off the field's own declaration, so no construction anywhere can stand in for it.

    The case below reads the default through a construction, which is what a stored row omitting the
    mark does. That reading is only an assertion about the default while the construction omits the
    field, and a helper supplying it would silently take the assertion away. This one cannot be
    routed through a helper: there is no construction in it.
    """
    declared = {field.name: field.default for field in dataclasses.fields(HabitOutcome)}

    assert declared["is_make_up"] is False


def test_an_occurrence_is_a_fresh_one_unless_the_row_says_otherwise() -> None:
    """Built without the field, because that is the row a reader of stored data constructs.

    The omission IS the assertion. Passing the field here, through a helper or otherwise, would
    leave the case green against any default.
    """
    unmarked = HabitOutcome(
        habit_id=HABIT,
        occurrence_key="00",
        state=OutcomeState.COMPLETED,
        occurred_at=AT,
        confirmed_at=AT,
    )

    assert not unmarked.is_make_up
    assert not unmarked.is_confirmed_make_up_completion
    assert outcome(OutcomeState.COMPLETED, make_up=True).is_make_up


def test_two_rows_differing_only_in_the_mark_are_not_the_same_row() -> None:
    """The mark is a field of the projection rather than a fact about it, so a log holds both."""
    fresh = outcome(OutcomeState.COMPLETED)
    made_up = HabitOutcome(
        habit_id=fresh.habit_id,
        occurrence_key=fresh.occurrence_key,
        state=fresh.state,
        occurred_at=fresh.occurred_at,
        confirmed_at=fresh.confirmed_at,
        is_make_up=True,
    )

    assert made_up != fresh


@pytest.mark.parametrize("state", sorted(COMPLETION_STATES))
def test_every_completion_state_settles_a_make_up_when_the_day_is_confirmed(
    state: OutcomeState,
) -> None:
    """Four of the five states mean the content was done, and doing it is what settles a make-up."""
    assert outcome(state, make_up=True).is_confirmed_make_up_completion


def test_a_skipped_make_up_settles_nothing() -> None:
    """The occurrence was placed to make an earlier miss good and the user did not do it."""
    assert not outcome(MISS_STATE, make_up=True).is_confirmed_make_up_completion


def test_a_completed_fresh_occurrence_settles_no_make_up() -> None:
    assert not outcome(OutcomeState.COMPLETED).is_confirmed_make_up_completion


@pytest.mark.parametrize("state", sorted(OutcomeState))
def test_an_unconfirmed_make_up_settles_nothing_until_the_day_is_confirmed(
    state: OutcomeState,
) -> None:
    assert not outcome(state, confirmed=False, make_up=True).is_confirmed_make_up_completion


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


class TestWhatEachStateAttributes:
    """The attribution table, and the two properties that make it a table rather than a list.

    It is TOTAL over the vocabulary, so a sixth state cannot be silently unattributed, and exactly
    one member attributes nothing. Both are asserted mechanically, because the failure a listed
    table produces is a state that quietly contributes its planned span forever.
    """

    def test_a_block_with_no_row_at_all_attributes_its_planned_span(self) -> None:
        # O1: a block is presumed complete with no user action, so the absence of a row is a
        # reading rather than a gap. Without this the common case would attribute nothing.
        assert attributed_span(PLANNED, None) == PLANNED

    @pytest.mark.parametrize(
        "state", [OutcomeState.PRESUMED, OutcomeState.COMPLETED], ids=["presumed", "completed"]
    )
    def test_a_presumed_or_completed_block_attributes_its_planned_span(
        self, state: OutcomeState
    ) -> None:
        assert attributed_span(PLANNED, recorded(state)) == PLANNED

    def test_a_partial_block_attributes_its_actual_minutes_from_the_planned_start(self) -> None:
        # The prefix rather than a bare count: every reader clips this against a deadline and
        # against `now`, and a count would have to be placed somewhere before it could be clipped.
        span = attributed_span(PLANNED, recorded(OutcomeState.PARTIAL, actual_minutes=20))

        assert span == Interval(PLANNED.start, PLANNED.start + timedelta(minutes=20))

    def test_a_partial_reporting_longer_than_planned_attributes_past_the_planned_end(self) -> None:
        # Stated rather than clamped. The user is reporting how long the work took, and the state
        # they chose is theirs; clamping would silently discard the figure the signal is read from.
        span = attributed_span(PLANNED, recorded(OutcomeState.PARTIAL, actual_minutes=90))

        assert span is not None
        assert span.total_minutes() == 90
        assert span.end > PLANNED.end

    def test_a_moved_block_attributes_the_interval_it_really_happened_in(self) -> None:
        span = attributed_span(PLANNED, recorded(OutcomeState.MOVED, actual_interval=ELSEWHERE))

        assert span == ELSEWHERE
        assert span.total_minutes() == 30

    def test_a_skipped_block_attributes_nothing(self) -> None:
        # The row 1290 settled. The user said the work was not done, so the minutes are not held
        # against the task: the demand stays gross for work that is genuinely still outstanding.
        assert attributed_span(PLANNED, recorded(MISS_STATE)) is None

    @pytest.mark.parametrize("state", sorted(OutcomeState))
    def test_every_state_in_the_vocabulary_has_an_attribution(self, state: OutcomeState) -> None:
        span = attributed_span(PLANNED, _any_outcome(state))

        assert span is None or span.total_minutes() > 0

    def test_exactly_one_state_attributes_nothing_and_it_is_the_miss(self) -> None:
        # The property that pairs the two partitions: the state that says the content was not done
        # is the one that contributes no minutes, and no completion state contributes none.
        unattributed = {
            state for state in OutcomeState if attributed_span(PLANNED, _any_outcome(state)) is None
        }

        assert unattributed == {MISS_STATE}
        assert not unattributed & COMPLETION_STATES


class TestTheDataTwoOfTheStatesCarry:
    """O2 and O7's first half, each checked in both directions.

    The reverse direction is not tidiness. A figure on a state that does not name one is a value
    no reader looks at, so it can disagree with the span the block was planned for and nothing
    would report the disagreement.
    """

    def test_a_partial_without_its_minutes_is_refused(self) -> None:
        with pytest.raises(OutcomeError, match="duration-estimate signal"):
            recorded(OutcomeState.PARTIAL)

    @pytest.mark.parametrize(
        "state",
        [OutcomeState.PRESUMED, OutcomeState.COMPLETED, OutcomeState.SKIPPED, OutcomeState.MOVED],
    )
    def test_a_state_that_names_no_minutes_may_not_carry_them(self, state: OutcomeState) -> None:
        interval = ELSEWHERE if state is OutcomeState.MOVED else None
        with pytest.raises(OutcomeError, match="only a 'partial' outcome states its own minutes"):
            recorded(state, actual_minutes=20, actual_interval=interval)

    def test_a_partial_of_no_minutes_is_the_other_state_and_is_refused(self) -> None:
        with pytest.raises(OutcomeError, match="which has its own state"):
            recorded(OutcomeState.PARTIAL, actual_minutes=MIN_ACTUAL_MINUTES - 1)

    def test_a_partial_of_the_smallest_reportable_figure_is_accepted(self) -> None:
        # The bound distinguishes rather than refusing a figure: one minute is a real partial.
        span = attributed_span(
            PLANNED, recorded(OutcomeState.PARTIAL, actual_minutes=MIN_ACTUAL_MINUTES)
        )

        assert span is not None
        assert span.total_minutes() == MIN_ACTUAL_MINUTES

    def test_a_move_that_does_not_say_when_is_refused(self) -> None:
        with pytest.raises(OutcomeError, match="states the interval it really happened in"):
            recorded(OutcomeState.MOVED)

    @pytest.mark.parametrize(
        "state",
        [OutcomeState.PRESUMED, OutcomeState.COMPLETED, OutcomeState.SKIPPED, OutcomeState.PARTIAL],
    )
    def test_a_state_that_names_no_interval_may_not_carry_one(self, state: OutcomeState) -> None:
        minutes = 20 if state is OutcomeState.PARTIAL else None
        with pytest.raises(OutcomeError, match="only a 'moved' outcome states when"):
            recorded(state, actual_minutes=minutes, actual_interval=ELSEWHERE)


def _any_outcome(state: OutcomeState) -> RecordedOutcome:
    """A legal outcome of ``state``, whichever half that state has to carry."""
    return RecordedOutcome(
        binding=BINDING,
        state=state,
        actual_minutes=20 if state is OutcomeState.PARTIAL else None,
        actual_interval=ELSEWHERE if state is OutcomeState.MOVED else None,
    )
