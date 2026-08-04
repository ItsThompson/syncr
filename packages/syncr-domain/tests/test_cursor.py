"""The rotation cursor: what advances it, what does not, and what cannot reach it.

Three groups of tests, and the third is the one that matters most.

**What advances it.** A confirmed completion, once per occurrence, in whatever order the log
arrives in. Four of the five outcome states are a completion and exactly one is a miss, so the
partition is asserted state by state rather than for the two obvious ones.

**What does not.** A skip, an unconfirmed day, another habit's outcomes, and any API path at
all: there is no setter here to call.

**What cannot reach it.** The cursor is a count modulo the variant count, so it reads no
calendar. That is asserted rather than assumed, by moving one log across a spring-forward
transition, a fall-back transition, a year boundary, and a tenant whose zone changed, and
requiring the same answer every time. A cursor that did date arithmetic would move under at
least one of those.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from syncr_domain import cursor as cursor_module
from syncr_domain.cursor import CursorReading, NoRotationCursor, cursor_reading, derive_cursor
from syncr_domain.fixtures.dst_weeks import DST_WEEKS, DstWeek
from syncr_domain.habits import (
    BindingSource,
    Duration,
    Habit,
    MissPolicy,
    TimesPerWeek,
)
from syncr_domain.identity import index_occurrence_key
from syncr_domain.intervals import IntervalError
from syncr_domain.outcomes import COMPLETION_STATES, MISS_STATE, HabitOutcome, OutcomeState
from syncr_domain.zones import to_instant

if TYPE_CHECKING:
    from syncr_domain.identifiers import HabitId
    from syncr_domain.intervals import Instant

GYM_SPLIT = ("Shoulder & Arms", "Legs", "Chest & Back", "Cardio")

MONDAY = datetime(2026, 8, 3, 6, 0, tzinfo=UTC)


def rotating(**overrides: object) -> Habit:
    fields: dict[str, object] = {
        "id": uuid4(),
        "cadence": TimesPerWeek(4),
        "duration": Duration.fixed(90),
        "miss_policy": MissPolicy.FORGIVE,
        "binding_source": BindingSource.ROTATION,
        "variants": GYM_SPLIT,
    }
    fields.update(overrides)
    return Habit(**fields)  # type: ignore[arg-type]


def outcome(
    habit_id: HabitId,
    state: OutcomeState,
    *,
    index: int = 0,
    at: Instant = MONDAY,
    confirmed: bool = True,
) -> HabitOutcome:
    return HabitOutcome(
        habit_id=habit_id,
        occurrence_key=index_occurrence_key(index),
        state=state,
        occurred_at=at,
        confirmed_at=at + timedelta(hours=12) if confirmed else None,
    )


def log(habit: Habit, *states: OutcomeState, confirmed: bool = True) -> list[HabitOutcome]:
    """One outcome per state, each a day apart so the log has a real order to permute."""
    return [
        outcome(
            habit.id, state, index=index, at=MONDAY + timedelta(days=index), confirmed=confirmed
        )
        for index, state in enumerate(states)
    ]


# --------------------------------------------------------------------------------
# What advances the cursor
# --------------------------------------------------------------------------------


def test_a_fresh_habit_sits_on_its_first_variant() -> None:
    habit = rotating()

    assert derive_cursor(habit, []) == 0


@pytest.mark.parametrize("state", sorted(COMPLETION_STATES))
def test_every_confirmed_completion_state_advances_the_cursor(state: OutcomeState) -> None:
    """Four of the five states mean the content was done, so four of them advance it."""
    habit = rotating()

    assert derive_cursor(habit, log(habit, state)) == 1


def test_the_cursor_advances_once_per_confirmed_completion() -> None:
    habit = rotating()
    completions = log(habit, *[OutcomeState.COMPLETED] * 3)

    assert derive_cursor(habit, completions) == 3
    assert habit.variants[derive_cursor(habit, completions)] == "Cardio"


def test_the_cursor_wraps_at_the_end_of_the_variant_list() -> None:
    habit = rotating()
    a_full_cycle = log(habit, *[OutcomeState.COMPLETED] * len(GYM_SPLIT))

    assert derive_cursor(habit, a_full_cycle) == 0


# --------------------------------------------------------------------------------
# What does not advance it
# --------------------------------------------------------------------------------


def test_a_skip_does_not_advance_the_cursor_so_the_next_occurrence_offers_the_same_variant() -> (
    None
):
    """Missing Tuesday must not skip a muscle group. This is the whole reason the cursor exists."""
    habit = rotating()
    skipped_after_one = log(habit, OutcomeState.COMPLETED, MISS_STATE, MISS_STATE)

    assert derive_cursor(habit, skipped_after_one) == 1
    assert habit.variants[derive_cursor(habit, skipped_after_one)] == "Legs"


@pytest.mark.parametrize("state", sorted(OutcomeState))
def test_an_unconfirmed_day_advances_nothing_whatever_it_claims(state: OutcomeState) -> None:
    """A day the user disengaged from must not be recorded as perfect, or as anything."""
    habit = rotating()

    assert derive_cursor(habit, log(habit, state, confirmed=False)) == 0


def test_another_habit_s_outcomes_do_not_move_this_habit_s_cursor() -> None:
    """The re-derivation keys on the outcome's binding, which names the habit."""
    habit = rotating()
    someone_else = rotating()
    mixed = [*log(habit, OutcomeState.COMPLETED), *log(someone_else, OutcomeState.COMPLETED)]

    assert derive_cursor(habit, mixed) == 1
    assert derive_cursor(someone_else, mixed) == 1


def test_two_rows_for_one_occurrence_advance_the_cursor_twice() -> None:
    """The precondition the reader owes, pinned as behaviour rather than left to a docstring.

    A count cannot tell a duplicate from a second occurrence, so a log delivering one occurrence
    twice moves the cursor twice. This is not a defect in the derivation: it is why the reader that
    supplies the log owes at most one row per occurrence, and it is asserted so that a later change
    which starts de-duplicating here fails this test and has to update that contract with it.
    """
    habit = rotating()
    once = [outcome(habit.id, OutcomeState.COMPLETED, index=0)]
    twice = [*once, outcome(habit.id, OutcomeState.COMPLETED, index=0)]

    assert derive_cursor(habit, once) == 1
    assert derive_cursor(habit, twice) == 2


def test_a_correction_replacing_a_row_advances_once_where_two_rows_would_advance_twice() -> None:
    """The same shape read the other way: a correction REPLACES, it does not accumulate."""
    habit = rotating()
    corrected = [outcome(habit.id, OutcomeState.COMPLETED, index=0)]
    accumulated = [outcome(habit.id, MISS_STATE, index=0), *corrected]

    assert derive_cursor(habit, corrected) == 1
    # A miss counts nothing, so this pair happens to agree; the point is that the reader must
    # deliver the corrected row INSTEAD OF the original rather than beside it.
    assert derive_cursor(habit, accumulated) == 1


def test_an_outcome_carrying_a_naive_datetime_is_refused_where_it_is_built() -> None:
    """Two naive datetimes compare without error, which is how a zone defect becomes invisible.

    Normalized through the same guard an ``Interval`` uses, so a reader composing rows from a
    driver that hands back naive values learns it at construction rather than as a comparison
    against a wall clock two layers down.
    """
    habit = rotating()

    with pytest.raises(IntervalError, match="names no instant"):
        HabitOutcome(
            habit_id=habit.id,
            occurrence_key="00",
            state=OutcomeState.COMPLETED,
            occurred_at=datetime(2026, 8, 3, 6, 0),  # noqa: DTZ001 - the value under test
            confirmed_at=None,
        )


def test_an_outcome_s_instants_are_normalized_to_utc_on_construction() -> None:
    """An aware datetime in any zone names one instant, and that is what the row holds."""
    habit = rotating()
    in_auckland = to_instant(MONDAY.time(), MONDAY.date(), "Pacific/Auckland")

    recorded = outcome(habit.id, OutcomeState.COMPLETED, at=in_auckland)

    assert recorded.occurred_at.utcoffset() == timedelta(0)
    assert recorded.occurred_at == in_auckland


def test_correcting_a_past_confirmation_re_derives_the_cursor_with_no_further_action() -> None:
    """The user fixes the day on Today; nothing else is called.

    The corrected row replaces the one for that occurrence, keyed by the same binding, and the
    cursor is read from the log again. There is no stored value for the correction to update,
    which is what makes "no further action" true rather than merely convenient.
    """
    habit = rotating()
    as_recorded = log(habit, OutcomeState.COMPLETED, MISS_STATE, OutcomeState.COMPLETED)
    assert derive_cursor(habit, as_recorded) == 2

    corrected = [
        outcome(habit.id, OutcomeState.COMPLETED, index=1, at=MONDAY + timedelta(days=1))
        if row.occurrence_key == "01"
        else row
        for row in as_recorded
    ]

    assert [row.occurrence_key for row in corrected] == ["00", "01", "02"]
    assert derive_cursor(habit, corrected) == 3


# --------------------------------------------------------------------------------
# No API path sets it, and no habit that does not rotate holds one
# --------------------------------------------------------------------------------


@pytest.mark.parametrize("source", [BindingSource.FIXED, BindingSource.QUEUE])
def test_a_habit_that_does_not_rotate_holds_no_cursor_to_read(source: BindingSource) -> None:
    habit = rotating(binding_source=source, variants=())

    with pytest.raises(NoRotationCursor, match="holds no rotation cursor"):
        derive_cursor(habit, [])


@pytest.mark.parametrize("source", [BindingSource.FIXED, BindingSource.QUEUE])
def test_a_habit_that_does_not_rotate_displays_no_cursor_at_all(source: BindingSource) -> None:
    """`None` rather than a rejection: a list of habits asks this of every one of them."""
    habit = rotating(binding_source=source, variants=())

    assert cursor_reading(habit, []) is None


def test_the_cursor_module_offers_nothing_that_sets_a_cursor() -> None:
    """The affordance does not exist, asserted against the module's own surface.

    A setter added here would be the first half of a route that could desync the cursor from
    the log that produced it, so the absence is checked rather than reviewed.
    """
    public = {name for name in vars(cursor_module) if not name.startswith("_")}
    writers = {name for name in public if any(verb in name for verb in ("set", "advance", "write"))}

    assert writers == set(), f"{writers} could move a cursor the outcome log did not move"


# --------------------------------------------------------------------------------
# The reading, and its provenance
# --------------------------------------------------------------------------------


def test_a_reading_names_the_variant_and_why_the_cursor_is_on_it() -> None:
    habit = rotating()
    reading = cursor_reading(habit, log(habit, OutcomeState.COMPLETED, OutcomeState.COMPLETED))

    assert reading is not None
    assert reading.index == 2
    assert reading.variant == "Chest & Back"
    assert reading.previous_variant == "Legs"
    assert reading.confirmed_completions == 2
    assert "Chest & Back because Legs was confirmed complete" in reading.statement
    assert "no control to set it" in reading.statement


def test_a_reading_with_no_confirmed_completion_says_so_rather_than_naming_a_variant() -> None:
    habit = rotating()
    reading = cursor_reading(habit, log(habit, MISS_STATE))

    assert reading is not None
    assert (reading.index, reading.previous_variant, reading.advanced_at) == (0, None, None)
    assert "no completion has been confirmed yet" in reading.statement


def test_a_reading_names_when_the_cursor_last_advanced() -> None:
    habit = rotating()
    completions = log(habit, OutcomeState.COMPLETED, OutcomeState.COMPLETED)

    reading = cursor_reading(habit, completions)

    assert reading is not None
    assert reading.advanced_at == max(row.confirmed_at for row in completions if row.confirmed_at)


def test_a_full_cycle_reads_as_back_at_the_start_because_the_last_variant_was_completed() -> None:
    """The wrap case the provenance has to get right: index 0 with a previous variant."""
    habit = rotating()
    reading = cursor_reading(habit, log(habit, *[OutcomeState.COMPLETED] * len(GYM_SPLIT)))

    assert reading is not None
    assert (reading.index, reading.previous_variant) == (0, "Cardio")
    assert "On Shoulder & Arms because Cardio was confirmed complete" in reading.statement


def test_a_one_variant_rotation_states_a_return_rather_than_naming_itself_as_the_cause() -> None:
    """``On Legs because Legs was confirmed complete`` states a loop rather than an advance.

    A one-variant rotation is legal and the entity supports it, so the sentence it produces has to
    read as one. The same branch covers a list that repeats a variant adjacently.
    """
    one = rotating(variants=("Full body",))
    reading = cursor_reading(one, log(one, OutcomeState.COMPLETED))

    assert reading is not None
    assert (reading.index, reading.variant, reading.previous_variant) == (
        0,
        "Full body",
        "Full body",
    )
    assert "On Full body again: the rotation returns to it" in reading.statement
    assert "because" not in reading.statement


# --------------------------------------------------------------------------------
# X8: order cannot change the answer
# --------------------------------------------------------------------------------

_STATES = st.sampled_from(sorted(OutcomeState))


@given(states=st.lists(_STATES, max_size=40), confirmations=st.lists(st.booleans(), max_size=40))
def test_x8_the_same_outcome_log_yields_the_same_cursor_whatever_order_it_is_read_in(
    states: list[OutcomeState], confirmations: list[bool]
) -> None:
    """The cursor is a count, and addition commutes. Nothing here needs a stable sort."""
    habit = rotating()
    rows = [
        outcome(
            habit.id,
            state,
            index=index,
            at=MONDAY + timedelta(days=index),
            confirmed=index < len(confirmations) and confirmations[index],
        )
        for index, state in enumerate(states)
    ]

    assert derive_cursor(habit, rows) == derive_cursor(habit, list(reversed(rows)))
    assert cursor_reading(habit, rows) == cursor_reading(habit, list(reversed(rows)))


@given(permutation=st.permutations(range(6)))
def test_x8_holds_for_every_permutation_rather_than_only_for_the_reverse(
    permutation: list[int],
) -> None:
    habit = rotating()
    rows = log(
        habit,
        OutcomeState.COMPLETED,
        MISS_STATE,
        OutcomeState.PARTIAL,
        OutcomeState.MOVED,
        MISS_STATE,
        OutcomeState.PRESUMED,
    )

    shuffled = [rows[position] for position in permutation]

    # Four of the six are completions, and four variants wrap to the start again.
    assert derive_cursor(habit, shuffled) == 0
    assert cursor_reading(habit, shuffled) == cursor_reading(habit, rows)
    assert _reading_of(habit, shuffled).confirmed_completions == 4


# --------------------------------------------------------------------------------
# What the cursor cannot see: a transition, a year boundary, a change of zone
# --------------------------------------------------------------------------------


def _moved_to(rows: list[HabitOutcome], offset: timedelta) -> list[HabitOutcome]:
    return [
        HabitOutcome(
            habit_id=row.habit_id,
            occurrence_key=row.occurrence_key,
            state=row.state,
            occurred_at=row.occurred_at + offset,
            confirmed_at=None if row.confirmed_at is None else row.confirmed_at + offset,
        )
        for row in rows
    ]


def _reading_of(habit: Habit, rows: list[HabitOutcome]) -> CursorReading:
    reading = cursor_reading(habit, rows)
    assert reading is not None
    return reading


@pytest.mark.parametrize("week", DST_WEEKS, ids=lambda week: week.label)
def test_a_daylight_saving_transition_does_not_move_the_cursor(week: DstWeek) -> None:
    """A cursor that measured elapsed days would move here. This one counts, so it cannot.

    The log is moved wholesale onto the transition week, so every outcome straddles the change
    of offset. The index and the whole reading's derived fields are the same as on an ordinary
    week; only the instants travel with it.
    """
    habit = rotating()
    ordinary = log(habit, OutcomeState.COMPLETED, MISS_STATE, OutcomeState.COMPLETED)
    on_the_transition = _moved_to(ordinary, week.span.start - ordinary[0].occurred_at)

    assert derive_cursor(habit, on_the_transition) == derive_cursor(habit, ordinary) == 2
    before = _reading_of(habit, ordinary)
    after = _reading_of(habit, on_the_transition)
    assert (after.index, after.variant, after.confirmed_completions, after.previous_variant) == (
        before.index,
        before.variant,
        before.confirmed_completions,
        before.previous_variant,
    )


def test_an_outcome_log_spanning_a_year_boundary_does_not_move_the_cursor() -> None:
    """ISO years do not align with calendar years, and the cursor reads neither."""
    habit = rotating()
    across = [
        outcome(
            habit.id, OutcomeState.COMPLETED, index=0, at=datetime(2026, 12, 30, 6, tzinfo=UTC)
        ),
        outcome(habit.id, MISS_STATE, index=1, at=datetime(2026, 12, 31, 6, tzinfo=UTC)),
        outcome(habit.id, OutcomeState.COMPLETED, index=2, at=datetime(2027, 1, 1, 6, tzinfo=UTC)),
    ]

    assert derive_cursor(habit, across) == 2


def test_the_cursor_reads_the_same_whichever_zone_the_tenant_was_in() -> None:
    """One wall-clock schedule in two zones is two different instant sets, and one cursor.

    The same three local mornings are resolved in London and then in Auckland, which puts the
    second set most of a day away from the first and crosses a date boundary. A cursor keyed on
    a local date would differ; this one does not.
    """
    habit = rotating()
    states = (OutcomeState.COMPLETED, MISS_STATE, OutcomeState.COMPLETED)
    days = (MONDAY.date(), MONDAY.date() + timedelta(days=1), MONDAY.date() + timedelta(days=2))

    def rows(zone: str) -> list[HabitOutcome]:
        return [
            outcome(habit.id, state, index=index, at=to_instant(MONDAY.time(), day, zone))
            for index, (state, day) in enumerate(zip(states, days, strict=True))
        ]

    london = rows("Europe/London")
    auckland = rows("Pacific/Auckland")

    assert {row.occurred_at for row in london} != {row.occurred_at for row in auckland}
    assert derive_cursor(habit, london) == derive_cursor(habit, auckland) == 2
    assert _reading_of(habit, london).index == _reading_of(habit, auckland).index
