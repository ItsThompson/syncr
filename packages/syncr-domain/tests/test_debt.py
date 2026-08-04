"""Debt: the three miss policies, the cap, and what a miss at the cap does instead.

Each policy has its own group, because each answers a different question and a test that mixed
them would pass while two of them behaved identically.

The cap is asserted three ways: at it, one past it, and over a long generated miss sequence,
because the third is the one that catches an accumulator that drifts rather than one that is
off by one.

The last group is the same attack the cursor suite makes: debt counts, it does not measure, so
a daylight-saving transition, a year boundary, and a change of zone are invisible to it. The
one instant it reads is ``as_of``, and the clip that reads it is asserted at its own boundary.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

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
from syncr_domain.outcomes import COMPLETION_STATES, MISS_STATE, HabitOutcome, OutcomeState
from syncr_domain.zones import to_instant

if TYPE_CHECKING:
    from syncr_domain.identifiers import HabitId
    from syncr_domain.intervals import Instant

MONDAY = datetime(2026, 8, 3, 6, 0, tzinfo=UTC)
# Far enough past every log this file builds that `as_of` clips nothing. The clip has its own
# group of tests, where the instant is the subject rather than the setting.
LATER = datetime(2030, 1, 1, 0, 0, tzinfo=UTC)


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
) -> HabitOutcome:
    return HabitOutcome(
        habit_id=habit_id,
        occurrence_key=f"{index:02d}",
        state=state,
        occurred_at=at,
        confirmed_at=at + timedelta(hours=12) if confirmed else None,
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
def test_a_daylight_saving_transition_does_not_change_the_debt(week: DstWeek) -> None:
    """A cap measured in elapsed days would move here; one counted in occurrences cannot."""
    target = habit()
    ordinary = misses(target, 5)
    on_the_transition = [
        HabitOutcome(
            habit_id=row.habit_id,
            occurrence_key=row.occurrence_key,
            state=row.state,
            occurred_at=row.occurred_at + (week.span.start - ordinary[0].occurred_at),
            confirmed_at=None
            if row.confirmed_at is None
            else row.confirmed_at + (week.span.start - ordinary[0].occurred_at),
        )
        for row in ordinary
    ]

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
