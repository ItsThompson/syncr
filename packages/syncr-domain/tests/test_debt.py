"""Debt: the three miss policies, the cap, and what a miss at the cap does instead.

Each policy has its own group, because each answers a different question and a test that mixed
them would pass while two of them behaved identically.

The cap is asserted three ways: at it, one past it, and over a long generated miss sequence,
because the third is the one that catches an accumulator that drifts rather than one that is
off by one.

The last group is the same attack the cursor suite makes: debt counts, it does not measure, so
a daylight-saving transition, a year boundary, and a change of zone are invisible to it. The
one instant it reads is ``as_of``, and the clip that reads it is asserted at its own boundary.

The discharge has a group of its own, because it is the one place where the log's order is read:
what a make-up must NOT credit is asserted beside what it must, on the cadence where crediting any
completion reads a week of owed occurrences as nothing owed, and on the interleavings where a
credit arrives before the charge it would otherwise settle.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from enum import StrEnum
from itertools import pairwise, permutations
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from syncr_domain import debt
from syncr_domain.debt import DebtReading, debt_cap, debt_reading, outstanding_debt
from syncr_domain.fixtures.dst_weeks import DST_WEEKS, DstWeek
from syncr_domain.habits import (
    MAX_DEBT_CAP_PERIODS,
    BindingSource,
    Cadence,
    Daily,
    Duration,
    EveryApproxDays,
    Habit,
    MissPolicy,
    TimesPerWeek,
)
from syncr_domain.identity import index_occurrence_key
from syncr_domain.outcomes import COMPLETION_STATES, MISS_STATE, HabitOutcome, OutcomeState
from syncr_domain.zones import to_instant

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_domain.identifiers import HabitId
    from syncr_domain.intervals import Instant

MONDAY = datetime(2026, 8, 3, 6, 0, tzinfo=UTC)
# Far enough past every log this file builds that `as_of` clips nothing. The clip has its own
# group of tests, where the instant is the subject rather than the setting.
LATER = datetime(2030, 1, 1, 0, 0, tzinfo=UTC)

COMPLETED = OutcomeState.COMPLETED

# Days in a week, for keying a multi-week log the way a real occurrence key is keyed.
DAYS_IN_A_WEEK = 7


class Event(StrEnum):
    """What one row of a log says, for the cases that build a log one event at a time.

    An enum rather than two strings, because ``a_log`` branches on the value and a mistyped string
    would silently build a miss.
    """

    MISS = "a confirmed skip"
    MAKE_UP_DONE = "a confirmed completion of a made-up occurrence"


def habit(**overrides: object) -> Habit:
    """A four-times-a-week debt habit, capped at the default two periods."""
    fields: dict[str, object] = {
        "id": uuid4(),
        "cadence": TimesPerWeek(4),
        "duration": Duration.fixed(90),
        "miss_policy": MissPolicy.DEBT,
        "binding_source": BindingSource.FIXED,
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
    confirmed_at: Instant | None = None,
    make_up: bool = False,
) -> HabitOutcome:
    """One row. ``confirmed_at`` defaults to twelve hours after the occurrence came due.

    A caller states it outright when the two instants have to differ: a day confirmed weeks late is
    a first-class case, and a fixture that always derives one from the other cannot express it.
    """
    settled = confirmed_at if confirmed_at is not None else at + timedelta(hours=12)
    return HabitOutcome(
        habit_id=habit_id,
        occurrence_key=index_occurrence_key(index),
        state=state,
        occurred_at=at,
        confirmed_at=settled if confirmed else None,
        is_make_up=make_up,
    )


def misses(target: Habit, count: int, *, confirmed: bool = True) -> list[HabitOutcome]:
    """``count`` confirmed skips, one a day, so the log has a real order."""
    return [
        outcome(
            target.id,
            MISS_STATE,
            index=index,
            at=MONDAY + timedelta(days=index),
            confirmed=confirmed,
        )
        for index in range(count)
    ]


def made_up(
    target: Habit,
    count: int,
    *,
    after: int,
    confirmed: bool = True,
    state: OutcomeState = COMPLETED,
) -> list[HabitOutcome]:
    """``count`` outcomes of made-up occurrences, keyed and dated past ``after`` earlier rows.

    A week holding made-up occurrences holds them after its fresh ones, so both the keys and the
    days follow the misses a caller pairs them with: one row per occurrence is the precondition the
    log is read under, and two rows sharing a key would break it.
    """
    return [
        outcome(
            target.id,
            state,
            index=after + offset,
            at=MONDAY + timedelta(days=after + offset),
            confirmed=confirmed,
            make_up=True,
        )
        for offset in range(count)
    ]


def a_log(target: Habit, events: Sequence[Event]) -> list[HabitOutcome]:
    """One row per event, in the order given, one day apart and keyed within its own week.

    For the cases where the ORDER is the subject: a make-up settles a charge the log holds when it
    arrives, so a credit before its charge and a credit after it are different logs.
    """
    return [
        outcome(
            target.id,
            COMPLETED if event is Event.MAKE_UP_DONE else MISS_STATE,
            index=index % DAYS_IN_A_WEEK,
            at=MONDAY + timedelta(days=index),
            make_up=event is Event.MAKE_UP_DONE,
        )
        for index, event in enumerate(events)
    ]


def reading(target: Habit, rows: list[HabitOutcome], *, as_of: Instant = LATER) -> DebtReading:
    return debt_reading(target, rows, as_of)


# --------------------------------------------------------------------------------
# The cap, in cadence periods
# --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cadence", "periods", "expected"),
    [
        (TimesPerWeek(4), 2, 8),
        (TimesPerWeek(1), 2, 2),
        (TimesPerWeek(4), 1, 4),
        (Daily(), 2, 2),
        (EveryApproxDays(7), 2, 2),
        (EveryApproxDays(30), 3, 3),
    ],
)
def test_the_cap_is_cadence_periods_times_occurrences_per_period(
    cadence: Cadence, periods: int, expected: int
) -> None:
    """Each reads as "this many cadence periods behind", which is the figure the user set."""
    assert debt_cap(habit(cadence=cadence, debt_cap_periods=periods)) == expected


def test_the_default_cap_on_a_four_a_week_habit_is_eight_sessions() -> None:
    assert debt_cap(habit()) == 8


# --------------------------------------------------------------------------------
# `debt`: accumulate, then forgive at the cap
# --------------------------------------------------------------------------------


def test_a_habit_with_no_misses_owes_nothing() -> None:
    owed = reading(habit(), [])

    assert (owed.misses, owed.outstanding, owed.forgiven_at_cap) == (0, 0, 0)
    assert not owed.raised_in_weekly_session
    assert owed.statement == "Nothing owed."


@pytest.mark.parametrize("count", [1, 3, 8])
def test_each_miss_below_the_cap_adds_one_to_outstanding_debt(count: int) -> None:
    target = habit()

    assert outstanding_debt(target, misses(target, count), LATER) == count


def test_a_miss_arriving_while_debt_is_at_the_cap_is_forgiven_rather_than_added() -> None:
    """The branch the flowchart names, asserted at exactly the occurrence that crosses it."""
    target = habit()
    at_the_cap = reading(target, misses(target, 8))
    one_more = reading(target, misses(target, 9))

    assert (at_the_cap.outstanding, at_the_cap.forgiven_at_cap) == (8, 0)
    assert not at_the_cap.raised_in_weekly_session
    assert (one_more.outstanding, one_more.forgiven_at_cap) == (8, 1)
    assert one_more.raised_in_weekly_session


def test_reaching_the_cap_raises_the_habit_through_the_field_chronic_skips_use() -> None:
    """One field carries both raises, so the weekly session needs no debt-specific surface."""
    target = habit()
    over_the_cap = reading(target, misses(target, 12))

    assert over_the_cap.raised_in_weekly_session
    assert "which is the cap" in over_the_cap.statement
    assert "forgiven rather than added" in over_the_cap.statement


@given(count=st.integers(min_value=0, max_value=400), periods=st.integers(min_value=1, max_value=8))
def test_debt_never_exceeds_the_cap_over_a_long_miss_sequence(count: int, periods: int) -> None:
    """The property the cap exists for: the backlog cannot fill with a month of missed gym."""
    target = habit(debt_cap_periods=periods)
    owed = reading(target, misses(target, count))

    assert 0 <= owed.outstanding <= debt_cap(target)
    assert owed.outstanding + owed.forgiven_at_cap == owed.misses
    assert owed.raised_in_weekly_session == (owed.forgiven_at_cap > 0)


@pytest.mark.parametrize("state", sorted(COMPLETION_STATES))
def test_no_completion_state_charges_debt(state: OutcomeState) -> None:
    """Four of the five states mean the content was done, so none of them is a miss."""
    target = habit()
    rows = [outcome(target.id, state, index=index) for index in range(4)]

    assert outstanding_debt(target, rows, LATER) == 0


def test_an_unconfirmed_skip_charges_nothing_until_the_day_is_confirmed() -> None:
    """A day the user disengaged from is not a record of a miss. Confirming it later settles it."""
    target = habit()

    assert outstanding_debt(target, misses(target, 3, confirmed=False), LATER) == 0
    assert outstanding_debt(target, misses(target, 3), LATER) == 3


def test_correcting_a_past_confirmation_re_derives_the_debt_with_no_further_action() -> None:
    """The charge disappears because the derivation reads the log from scratch every time."""
    target = habit()
    as_recorded = misses(target, 3)
    assert outstanding_debt(target, as_recorded, LATER) == 3

    corrected = [
        outcome(target.id, OutcomeState.COMPLETED, index=1, at=as_recorded[1].occurred_at)
        if row.occurrence_key == "01"
        else row
        for row in as_recorded
    ]

    assert outstanding_debt(target, corrected, LATER) == 2


def test_another_habit_s_misses_do_not_charge_this_habit() -> None:
    target = habit()
    someone_else = habit()
    mixed = [*misses(target, 2), *misses(someone_else, 5)]

    assert outstanding_debt(target, mixed, LATER) == 2
    assert outstanding_debt(someone_else, mixed, LATER) == 5


# --------------------------------------------------------------------------------
# Doing the make-up: what discharges debt, and what does not
# --------------------------------------------------------------------------------


def test_a_confirmed_completion_of_a_made_up_occurrence_settles_the_miss_it_was_placed_for() -> (
    None
):
    """The rule, at the figure a consumer reads: one miss, one make-up done, nothing owed."""
    target = habit()
    settled = reading(target, [*misses(target, 1), *made_up(target, 1, after=1)])

    assert (settled.misses, settled.outstanding, settled.forgiven_at_cap) == (0, 0, 0)
    assert not settled.raised_in_weekly_session
    assert settled.statement == "Nothing owed."


@pytest.mark.parametrize(("owed", "done"), [(3, 1), (3, 2), (3, 3), (8, 5)])
def test_each_made_up_occurrence_completed_takes_one_off_what_is_owed(owed: int, done: int) -> None:
    target = habit()
    log = [*misses(target, owed), *made_up(target, done, after=owed)]

    assert outstanding_debt(target, log, LATER) == owed - done


def test_a_completion_of_a_fresh_occurrence_discharges_nothing_on_the_four_a_week_case() -> None:
    """The half that "any confirmed completion credits" gets wrong, on the cadence that shows it.

    Four a week, so a week of misses owes four and the following week places four fresh
    occurrences beside four made-up ones. Completing the week as planned settles the fresh four and
    nothing else: crediting any completion would read this log as owing nothing while four
    occurrences are still owed. Only the made-up four move the figure.
    """
    target = habit(cadence=TimesPerWeek(4))
    week_one_missed = misses(target, 4)
    next_monday = MONDAY + timedelta(days=7)
    week_two_fresh_completed = [
        outcome(target.id, COMPLETED, index=key, at=next_monday + timedelta(days=key))
        for key in range(4)
    ]
    week_two_made_up_completed = [
        outcome(
            target.id,
            COMPLETED,
            index=4 + offset,
            at=next_monday + timedelta(days=offset),
            make_up=True,
        )
        for offset in range(4)
    ]

    assert outstanding_debt(target, week_one_missed, LATER) == 4
    assert outstanding_debt(target, [*week_one_missed, *week_two_fresh_completed], LATER) == 4
    assert (
        outstanding_debt(
            target,
            [*week_one_missed, *week_two_fresh_completed, *week_two_made_up_completed],
            LATER,
        )
        == 0
    )


def test_a_habit_at_its_cap_drops_below_it_and_stops_being_raised_once_the_make_ups_are_done() -> (
    None
):
    """The raise starts one occurrence past the cap, so that is where the drop is asserted from.

    A completion is credited against the misses the log holds, and the cap clamps the result of
    that. Past the cap the two are not the same figure, and
    ``test_a_completion_past_the_cap_moves_the_log_and_not_the_shown_backlog`` states the cost.
    """
    target = habit()
    over_the_cap = reading(target, misses(target, 9))
    made_good = reading(target, [*misses(target, 9), *made_up(target, 2, after=9)])

    assert (over_the_cap.outstanding, over_the_cap.forgiven_at_cap) == (8, 1)
    assert over_the_cap.raised_in_weekly_session
    assert (made_good.misses, made_good.outstanding, made_good.forgiven_at_cap) == (7, 7, 0)
    assert not made_good.raised_in_weekly_session
    assert made_good.statement == "7 of 8 owed."


def test_a_completion_past_the_cap_moves_the_log_and_not_the_shown_backlog() -> None:
    """What a completion buys when the log holds more misses than the cap allows.

    A week places ``outstanding`` made-up occurrences, which is the capped figure, so this habit is
    shown eight. Completing all eight moves the shown backlog by four, because each completion is
    credited against the twelve misses the log holds and the cap then clamps the result. The four
    completions the reading has already called forgiven rather than added move nothing.

    Asserted so the exchange is stated rather than implied. Both readings of what a completion past
    the cap should buy are defensible, and this is the one that ships.
    """
    target = habit()
    shown = reading(target, misses(target, 12))
    after = [
        reading(target, [*misses(target, 12), *made_up(target, done, after=12)])
        for done in range(9)
    ]

    assert (shown.outstanding, shown.forgiven_at_cap) == (8, 4)
    assert [owed.outstanding for owed in after] == [8, 8, 8, 8, 8, 7, 6, 5, 4]
    assert [owed.forgiven_at_cap for owed in after] == [4, 3, 2, 1, 0, 0, 0, 0, 0]


def test_a_made_up_occurrence_with_nothing_left_to_settle_owes_nothing_rather_than_less() -> None:
    """Reachable rather than defensive: correcting the miss that placed the make-up leaves this log.

    A negative figure would reach the assembler as a range it cannot expand and the cap as a bound
    on the wrong side, so the floor is where the netting is stated rather than at either consumer.
    """
    target = habit()
    nothing_owed = reading(target, made_up(target, 2, after=0))
    one_owed_two_done = reading(target, [*misses(target, 1), *made_up(target, 2, after=1)])

    assert (nothing_owed.misses, nothing_owed.outstanding) == (0, 0)
    assert nothing_owed.statement == "Nothing owed."
    assert (one_owed_two_done.misses, one_owed_two_done.outstanding) == (0, 0)


def test_an_unconfirmed_completion_of_a_made_up_occurrence_discharges_nothing_yet() -> None:
    """The same deferral the charge has: a day the user disengaged from settles nothing either."""
    target = habit()
    unconfirmed = [*misses(target, 2), *made_up(target, 1, after=2, confirmed=False)]

    assert outstanding_debt(target, unconfirmed, LATER) == 2
    assert outstanding_debt(target, [*misses(target, 2), *made_up(target, 1, after=2)], LATER) == 1


def test_a_made_up_occurrence_the_user_skipped_again_charges_rather_than_discharges() -> None:
    """A make-up not done is a miss of its own, which is what the log records and all it records."""
    target = habit()
    skipped_again = [*misses(target, 1), *made_up(target, 1, after=1, state=MISS_STATE)]

    assert outstanding_debt(target, skipped_again, LATER) == 2


def test_a_made_up_completion_that_has_not_come_due_discharges_nothing_yet() -> None:
    """The clip reads both halves of the netting, so a week's later rows cannot settle it early."""
    target = habit()
    log = [*misses(target, 1), *made_up(target, 1, after=1)]
    due = log[-1].occurred_at

    assert outstanding_debt(target, log, as_of=due - timedelta(microseconds=1)) == 1
    assert outstanding_debt(target, log, as_of=due) == 0


def test_another_habit_s_made_up_completion_does_not_settle_this_habit_s_debt() -> None:
    target = habit()
    someone_else = habit()
    mixed = [*misses(target, 2), *misses(someone_else, 2), *made_up(someone_else, 2, after=2)]

    assert outstanding_debt(target, mixed, LATER) == 2
    assert outstanding_debt(someone_else, mixed, LATER) == 0


def test_a_make_up_settles_a_charge_the_log_holds_when_it_arrives_and_carries_nothing_forward() -> (
    None
):
    """Two logs holding one miss and one made-up completion, differing only in their order.

    A credit that arrived before its charge would have to be banked to reach it, and a banked credit
    is a credit that outlives the miss it settled.
    """
    target = habit()

    assert reading(target, a_log(target, [Event.MISS, Event.MAKE_UP_DONE])).misses == 0
    assert reading(target, a_log(target, [Event.MAKE_UP_DONE, Event.MISS])).misses == 1


def test_a_correction_leaves_no_credit_behind_for_a_later_unrelated_miss() -> None:
    """The path the floor exists for, walked to its end rather than read at one instant.

    A miss, the make-up placed for it completed, and then the user corrects the original day. The
    log now holds a completion whose charge is gone. A fresh miss weeks later is a miss: nothing in
    the log has made it good, and the credit that settled the corrected day is spent.
    """
    target = habit()
    skipped = outcome(target.id, MISS_STATE, index=0, at=MONDAY)
    made_it_up = outcome(target.id, COMPLETED, index=4, at=MONDAY + timedelta(days=7), make_up=True)
    corrected = outcome(target.id, COMPLETED, index=0, at=MONDAY)
    a_fresh_miss = outcome(target.id, MISS_STATE, index=1, at=MONDAY + timedelta(days=56))

    assert outstanding_debt(target, [skipped], LATER) == 1
    assert outstanding_debt(target, [skipped, made_it_up], LATER) == 0
    assert outstanding_debt(target, [corrected, made_it_up], LATER) == 0
    assert outstanding_debt(target, [corrected, made_it_up, a_fresh_miss], LATER) == 1


def test_the_order_the_walk_reads_is_the_log_s_own_and_not_the_sequence_it_arrives_in() -> None:
    """The reader states no order, so the derivation cannot take one from the sequence it is given.

    Every permutation of one set of rows is one figure. Asserted over all of them rather than over a
    reversal, because a reversal of a sequence chosen for its content rather than for its order
    happens to agree: the first version of this case reversed and rotated a log whose every
    arrangement charged the same, so it could not fail on a derivation that read the sequence.

    The log holds a credit before its first charge, which is what makes the arrangements differ: a
    credit read before the charge it would settle is spent on nothing.
    """
    target = habit()
    rows = a_log(
        target, [Event.MAKE_UP_DONE, Event.MISS, Event.MAKE_UP_DONE, Event.MISS, Event.MISS]
    )

    assert reading(target, rows).misses == 2
    assert {reading(target, list(order)).misses for order in permutations(rows)} == {2}


def test_a_charge_and_a_credit_that_came_due_at_one_instant_settle_each_other() -> None:
    """The tie the walk has to break, and the direction it breaks in.

    Two occurrences of one habit can be due at the same instant. Reading the charge as standing when
    the credit arrives is the direction that never leaves the user's completed work unspent.
    """
    target = habit()
    both_at_once = [
        outcome(target.id, MISS_STATE, index=0, at=MONDAY),
        outcome(target.id, COMPLETED, index=1, at=MONDAY, make_up=True),
    ]

    assert reading(target, both_at_once).misses == 0
    assert reading(target, list(reversed(both_at_once))).misses == 0


def test_the_walk_reads_when_an_occurrence_came_due_and_not_when_the_day_was_confirmed() -> None:
    """A day confirmed weeks after it came due still charges where it came due.

    Confirming late is a first-class case: an unconfirmed day settles in whichever direction the
    user later chooses, and a miss settled weeks afterwards is still a miss of the day it was due.
    So the make-up placed for it finds the charge standing, whichever day the user got around to
    confirming. Ordering by the confirmation instead would put the credit first and spend it on
    nothing.

    Every other case in this file confirms a day twelve hours after it came due, which is what makes
    the two instants agree everywhere else and this case the only one that separates them.
    """
    target = habit()
    settled_much_later = outcome(
        target.id,
        MISS_STATE,
        index=0,
        at=MONDAY,
        confirmed_at=MONDAY + timedelta(days=60),
    )
    made_it_up = outcome(target.id, COMPLETED, index=4, at=MONDAY + timedelta(days=7), make_up=True)

    assert settled_much_later.confirmed_at is not None
    assert settled_much_later.confirmed_at > made_it_up.occurred_at, (
        "the miss must be confirmed after the make-up came due, or the two instants agree"
    )
    assert reading(target, [settled_much_later]).misses == 1
    assert reading(target, [settled_much_later, made_it_up]).misses == 0
    assert reading(target, [made_it_up, settled_much_later]).misses == 0


def test_the_netting_is_stated_over_the_log_rather_than_over_the_policy() -> None:
    """``misses`` is one figure whatever the policy, so the discharge is not a fourth policy.

    Only ``debt`` places a made-up occurrence, so the other two answer about a habit whose policy
    changed after the log was written. Netting there keeps the figure meaning one thing; branching
    on the policy would make it mean two.
    """
    readings = []
    for policy in MissPolicy:
        target = habit(miss_policy=policy)
        readings.append(reading(target, [*misses(target, 1), *made_up(target, 1, after=1)]))

    assert all(owed.misses == 0 for owed in readings)
    assert not any(owed.raised_in_weekly_session for owed in readings)


@given(
    events=st.lists(st.sampled_from(Event), max_size=24),
    periods=st.integers(min_value=1, max_value=8),
)
def test_the_figure_holds_every_miss_that_arrived_after_the_last_make_up_was_done(
    events: list[Event], periods: int
) -> None:
    """Over any interleaving, not only over misses-then-make-ups.

    The property a banked credit breaks: a make-up cannot reach past its own arrival, so every miss
    after the last completed make-up is still owed. The bounds beside it are the two a sign error
    and a missing floor break.
    """
    target = habit(debt_cap_periods=periods)
    owed = reading(target, a_log(target, events))
    charged = events.count(Event.MISS)
    since_the_last_credit = (
        len(events) - 1 - events[::-1].index(Event.MAKE_UP_DONE)
        if Event.MAKE_UP_DONE in events
        else -1
    )

    assert owed.misses >= events[since_the_last_credit + 1 :].count(Event.MISS)
    assert 0 <= owed.misses <= charged
    assert owed.outstanding + owed.forgiven_at_cap == owed.misses


@given(
    events=st.lists(st.sampled_from(Event), max_size=16),
)
def test_one_more_miss_charges_one_and_one_more_make_up_settles_at_most_one(
    events: list[Event],
) -> None:
    """The step either event takes, from wherever the log already stands.

    A miss always charges, which is what a banked credit breaks: appended to a surplus it would
    charge nothing. A make-up settles one or nothing, never more and never less than nothing.
    """
    target = habit()
    standing = reading(target, a_log(target, events)).misses
    then_a_miss = reading(target, a_log(target, [*events, Event.MISS])).misses
    then_a_make_up = reading(target, a_log(target, [*events, Event.MAKE_UP_DONE])).misses

    assert then_a_miss == standing + 1
    assert max(standing - 1, 0) == then_a_make_up


@given(
    owed=st.integers(min_value=0, max_value=40),
    done=st.integers(min_value=0, max_value=40),
    periods=st.integers(min_value=1, max_value=8),
)
def test_completing_a_make_up_lowers_the_debt_or_leaves_it_and_never_goes_below_zero(
    owed: int, done: int, periods: int
) -> None:
    """The direction, over any pairing: a make-up cannot raise what is owed and cannot overshoot."""
    target = habit(debt_cap_periods=periods)
    charged = reading(target, misses(target, owed))
    settled = reading(target, [*misses(target, owed), *made_up(target, done, after=owed)])

    assert 0 <= settled.outstanding <= charged.outstanding
    assert (settled.outstanding == 0) == (done >= owed)
    assert settled.outstanding + settled.forgiven_at_cap == settled.misses
    assert settled.raised_in_weekly_session == (settled.forgiven_at_cap > 0)


# --------------------------------------------------------------------------------
# `forgive` and `escalate`
# --------------------------------------------------------------------------------


def test_forgive_makes_a_missed_occurrence_vanish_with_no_downstream_effect() -> None:
    """No debt, no raise, whatever the log holds. The occurrence simply stops existing."""
    target = habit(miss_policy=MissPolicy.FORGIVE)
    forgiven = reading(target, misses(target, 20))

    assert (forgiven.outstanding, forgiven.forgiven_at_cap) == (0, 0)
    assert not forgiven.raised_in_weekly_session
    assert forgiven.misses == 20


def test_escalate_raises_the_habit_in_the_next_weekly_session_and_accumulates_nothing() -> None:
    """It raises rather than rescheduling, which is what makes it not a second spelling of debt."""
    target = habit(miss_policy=MissPolicy.ESCALATE)
    escalated = reading(target, misses(target, 1))

    assert escalated.raised_in_weekly_session
    assert (escalated.outstanding, escalated.forgiven_at_cap) == (0, 0)
    assert "raised in the next weekly session" in escalated.statement


def test_escalate_raises_nothing_when_the_log_holds_no_miss() -> None:
    target = habit(miss_policy=MissPolicy.ESCALATE)

    assert not reading(target, []).raised_in_weekly_session


def test_an_escalate_raise_is_about_the_log_the_caller_slices_and_nothing_else() -> None:
    """The current contract, pinned so passing the whole log is a choice rather than an accident.

    ``escalate`` raises the habit while the outcomes it is given hold a miss, and `as_of` cannot
    express "the week that just happened" because the clip is one-sided. So the scope is the
    caller's: a weekly session reviewing one week passes that week's outcomes and the habit is
    raised once, and reviewing the next week it is not. Passed the WHOLE log the same habit is
    raised forever after a single miss, which is a nag rather than an escalation.

    This test exists so that whoever gives the reading its first real caller sees the contract as an
    assertion rather than as a sentence in a docstring.
    """
    target = habit(miss_policy=MissPolicy.ESCALATE)
    missed_week = misses(target, 2)
    a_clean_week_later = [
        outcome(
            target.id,
            OutcomeState.COMPLETED,
            index=index,
            at=MONDAY + timedelta(days=7 + index),
        )
        for index in range(2)
    ]

    assert reading(target, missed_week).raised_in_weekly_session
    assert not reading(target, a_clean_week_later).raised_in_weekly_session
    # The whole log, which is what the assembler passes and what a session must not:
    assert reading(target, [*missed_week, *a_clean_week_later]).raised_in_weekly_session


def test_a_miss_far_in_the_past_still_raises_an_escalate_habit_over_the_whole_log() -> None:
    """The consequence of the above, stated as its own case: nothing here ages a miss out."""
    target = habit(miss_policy=MissPolicy.ESCALATE)
    long_ago = [outcome(target.id, MISS_STATE, at=MONDAY - timedelta(days=400))]

    assert reading(target, long_ago).raised_in_weekly_session


def test_the_three_policies_answer_one_log_differently() -> None:
    """Side by side, because a policy that silently behaved like another would still pass alone."""
    rows_by_policy = {
        policy: reading(target := habit(miss_policy=policy), misses(target, 9))
        for policy in MissPolicy
    }

    assert [
        (owed.outstanding, owed.forgiven_at_cap, owed.raised_in_weekly_session)
        for owed in rows_by_policy.values()
    ] == [(0, 0, False), (8, 1, True), (0, 0, True)]


# --------------------------------------------------------------------------------
# Only a confirmed skip is a miss, pinned at the figures a consumer reads
# --------------------------------------------------------------------------------


def test_an_unconfirmed_skip_leaves_a_debt_habit_owing_zero_and_unraised() -> None:
    """The narrowing read where a consumer reads it: the figures, not the predicate.

    ``_misses`` holds the guard, but nothing outside this module reads ``_misses``, so the pin is
    what the reading reports: an unconfirmed skipped occurrence charges no debt and raises nothing.
    """
    target = habit()
    disengaged = misses(target, 3, confirmed=False)

    assert outstanding_debt(target, disengaged, LATER) == 0
    owed = reading(target, disengaged)

    assert owed.outstanding == 0
    assert not owed.raised_in_weekly_session
    assert owed.statement == "Nothing owed."


def test_an_escalate_habit_with_an_unconfirmed_skip_is_not_raised() -> None:
    """The policy that exists to chase the user goes quiet for the user who disengaged."""
    target = habit(miss_policy=MissPolicy.ESCALATE)
    escalated = reading(target, misses(target, 1, confirmed=False))

    assert not escalated.raised_in_weekly_session
    assert escalated.misses == 0


def test_confirming_the_skipped_day_later_produces_the_charge() -> None:
    """The narrowing defers rather than loses: settling the day settles it as a miss.

    The same three occurrences, unconfirmed and then confirmed weeks afterwards. The charge appears
    only once the user has said the day was missed, which is what makes holding it back safe.
    """
    target = habit()
    while_disengaged = misses(target, 3, confirmed=False)
    settled_late = [
        outcome(
            target.id,
            row.state,
            index=index,
            at=row.occurred_at,
            confirmed_at=MONDAY + timedelta(days=30),
        )
        for index, row in enumerate(while_disengaged)
    ]
    settled = settled_late[0].confirmed_at
    assert settled is not None
    assert all(row.confirmed_at == settled for row in settled_late), (
        "the log must differ from the disengaged one only in that the days were confirmed"
    )

    assert outstanding_debt(target, while_disengaged, LATER) == 0
    assert outstanding_debt(target, settled_late, LATER) == 3


def test_the_module_states_the_narrowing_and_its_product_consequence() -> None:
    """The ratified rule travels with the code that narrows, stated in ``debt.py`` itself.

    The sentence and its consequence are cited from the module's own docstring, which is inside the
    tree, so the check moves with the rule rather than pointing at anything external.
    """
    stated = debt.__doc__ or ""

    assert "Only a CONFIRMED skip is a miss" in stated
    assert "accrues no debt" in stated
    # The consequence sentence wraps mid-phrase in the source, so the citation stops at the break.
    assert "Confirming the day later" in stated


# --------------------------------------------------------------------------------
# `as_of`: the one instant this module reads
# --------------------------------------------------------------------------------


def test_an_occurrence_that_has_not_come_due_is_not_a_miss() -> None:
    """A week's plan can already hold rows for occurrences later in the week."""
    target = habit()
    rows = misses(target, 4)

    assert outstanding_debt(target, rows, as_of=rows[0].occurred_at) == 1
    assert outstanding_debt(target, rows, as_of=rows[3].occurred_at) == 4


def test_the_clip_is_inclusive_at_the_instant_the_occurrence_came_due() -> None:
    """The boundary itself: an occurrence due exactly at `as_of` has come due."""
    target = habit()
    rows = misses(target, 1)
    due = rows[0].occurred_at

    assert outstanding_debt(target, rows, as_of=due - timedelta(microseconds=1)) == 0
    assert outstanding_debt(target, rows, as_of=due) == 1


def test_the_clip_reads_the_scheduled_instant_rather_than_the_confirmation() -> None:
    """An occurrence is missed when it was due, not when the user got around to saying so.

    Confirming a whole week on the following Sunday must not move which occurrences count.
    """
    target = habit()
    due = MONDAY
    confirmed_much_later = HabitOutcome(
        habit_id=target.id,
        occurrence_key="00",
        state=MISS_STATE,
        occurred_at=due,
        confirmed_at=due + timedelta(days=30),
    )

    assert outstanding_debt(target, [confirmed_much_later], as_of=due) == 1


# --------------------------------------------------------------------------------
# What debt cannot see: a transition, a year boundary, a change of zone
# --------------------------------------------------------------------------------


@pytest.mark.parametrize("week", DST_WEEKS, ids=lambda week: week.label)
def test_the_clip_charges_the_same_occurrences_across_a_daylight_saving_transition(
    week: DstWeek,
) -> None:
    """Seven occurrences at the same LOCAL time each day, on a week whose offset changes.

    Their absolute spacing is therefore NOT uniform: one gap is 23 or 25 hours, which the test
    asserts before relying on it. A clip that measured elapsed days from the first occurrence would
    miscount across that gap. The clip compares absolute instants, so charging each day's local noon
    in turn charges exactly the occurrences that had come due, for every day of the week.

    This is the case that gives the DST claim force. A `DebtReading` carries no instant fields, so a
    version of this test that only compared two readings would be satisfied by any pure count.
    """
    target = habit(debt_cap_periods=MAX_DEBT_CAP_PERIODS)
    monday = week.iso_week.monday()
    days = [monday + timedelta(days=index) for index in range(7)]
    every_morning = [
        outcome(target.id, MISS_STATE, index=index, at=to_instant(time(6, 0), day, week.zone))
        for index, day in enumerate(days)
    ]

    gaps = {later.occurred_at - earlier.occurred_at for earlier, later in pairwise(every_morning)}
    assert len(gaps) == 2, (
        f"this week's offset must change inside it for the case to say anything, got {gaps}"
    )
    assert timedelta(days=1) in gaps

    for index, day in enumerate(days):
        noon = to_instant(time(12, 0), day, week.zone)
        assert outstanding_debt(target, every_morning, noon) == index + 1


@pytest.mark.parametrize("week", DST_WEEKS, ids=lambda week: week.label)
def test_a_daylight_saving_transition_does_not_change_the_debt(week: DstWeek) -> None:
    """The same log translated onto a transition week reads identically. A cap counted in
    occurrences cannot move; one measured in elapsed days would."""
    target = habit()
    ordinary = misses(target, 5)
    offset = week.span.start - ordinary[0].occurred_at
    on_the_transition = [
        outcome(
            target.id,
            MISS_STATE,
            index=index,
            at=MONDAY + timedelta(days=index) + offset,
        )
        for index in range(5)
    ]

    assert {row.occurred_at for row in on_the_transition} != {row.occurred_at for row in ordinary}
    assert reading(target, on_the_transition) == reading(target, ordinary)


def test_a_miss_sequence_spanning_a_year_boundary_accumulates_the_same_way() -> None:
    """ISO years do not align with calendar years, and neither figure here reads either."""
    target = habit()
    new_year = datetime(2026, 12, 28, 6, tzinfo=UTC)
    across = [
        outcome(target.id, MISS_STATE, index=index, at=new_year + timedelta(days=index))
        for index in range(6)
    ]

    assert outstanding_debt(target, across, LATER) == 6


def test_debt_reads_the_same_whichever_zone_the_tenant_was_in() -> None:
    """One wall-clock schedule in two zones is two instant sets, and one debt figure."""
    target = habit()
    days = [MONDAY.date() + timedelta(days=offset) for offset in range(5)]

    def rows(zone: str) -> list[HabitOutcome]:
        return [
            outcome(target.id, MISS_STATE, index=index, at=to_instant(MONDAY.time(), day, zone))
            for index, day in enumerate(days)
        ]

    london = rows("Europe/London")
    auckland = rows("Pacific/Auckland")

    assert {row.occurred_at for row in london} != {row.occurred_at for row in auckland}
    assert reading(target, london) == reading(target, auckland)
    assert outstanding_debt(target, london, LATER) == 5


def test_the_cap_at_its_own_bound_is_still_a_cap() -> None:
    """The widest cap the entity allows, on the busiest cadence, still bounds the answer."""
    target = habit(cadence=TimesPerWeek(4), debt_cap_periods=MAX_DEBT_CAP_PERIODS)
    owed = reading(target, misses(target, 4 * MAX_DEBT_CAP_PERIODS + 3))

    assert owed.outstanding == debt_cap(target) == 4 * MAX_DEBT_CAP_PERIODS
    assert owed.forgiven_at_cap == 3


# --------------------------------------------------------------------------------
# What the module says about itself, against what it does
# --------------------------------------------------------------------------------

# The sentence the discharge rule replaced, refused by name. A correction with nothing holding it
# is a correction that drifts back.
RETRACTED = "Nothing here discharges debt"


def test_the_module_does_not_state_that_nothing_discharges_debt() -> None:
    """One spelling, which is the whole of what a text check can hold.

    A denial worded some other way escapes this, and the group above is what catches that: it
    asserts the figure falling, which no wording can make true or false.
    """
    assert debt.__doc__ is not None
    assert RETRACTED not in debt.__doc__


def test_outstanding_debt_reads_the_way_its_own_docstring_states_it() -> None:
    """The claim and the reading in one place, so neither can move without the other."""
    target = habit()
    stated = outstanding_debt.__doc__ or ""

    assert "not yet made up" in stated
    assert outstanding_debt(target, misses(target, 1), LATER) == 1
    assert outstanding_debt(target, [*misses(target, 1), *made_up(target, 1, after=1)], LATER) == 0
