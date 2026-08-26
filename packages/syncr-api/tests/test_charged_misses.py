"""The one writer of a habit's stored charge, and the walk it restates from.

``charged_misses`` is exact wherever the log is because it is ``syncr_domain.debt``'s own walk,
run inside the transaction that changed the rows. These cases drive the maintainer over a log
supplied through the reader seam and assert the count it writes, so the floor per credit and the
confirmed-only narrowing are pinned where they are actually executed -- not re-derived in a test
double that would agree with whatever bug it mirrored.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from syncr_api.habits.charged import StoredChargedMisses
from syncr_domain.debt import debt_cap
from syncr_domain.habits import MissPolicy
from syncr_domain.identity import index_occurrence_key
from syncr_domain.outcomes import HabitOutcome, OutcomeState
from tests.assembly_fakes import FakeOutcomes, a_habit

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_api.habits.records import HabitRecord
    from syncr_domain.identifiers import HabitId

NOW = datetime(2026, 9, 16, 12, tzinfo=UTC)


class RowsWithAStoredCharge:
    """Habit rows that remember their charge, as the table does."""

    def __init__(self, records: Sequence[HabitRecord]) -> None:
        self.rows = list(records)
        self.written: dict[HabitId, int] = {}
        self.locked: list[HabitId] = []

    async def hold(self, habit_ids: Sequence[HabitId]) -> tuple[HabitRecord, ...]:
        self.locked = sorted(habit_ids)
        return tuple(row for row in self.rows if row.id in set(self.locked))

    async def write_charged_misses(self, habit_id: HabitId, *, charged: int) -> None:
        self.written[habit_id] = charged
        self.rows = [
            replace(row, charged_misses=charged) if row.id == habit_id else row for row in self.rows
        ]


def a_maintainer(habits: RowsWithAStoredCharge, log: Sequence[HabitOutcome]) -> StoredChargedMisses:
    return StoredChargedMisses(habits, FakeOutcomes(log), clock=lambda: NOW)  # type: ignore[arg-type]


def a_confirmed_skip(habit_id: HabitId, *, index: int) -> HabitOutcome:
    occurred_at = NOW - timedelta(days=index + 7)
    return HabitOutcome(
        habit_id=habit_id,
        occurrence_key=index_occurrence_key(index),
        state=OutcomeState.SKIPPED,
        occurred_at=occurred_at,
        confirmed_at=occurred_at + timedelta(hours=12),
    )


def a_completed_make_up(habit_id: HabitId, *, index: int) -> HabitOutcome:
    occurred_at = NOW - timedelta(days=2)
    return HabitOutcome(
        habit_id=habit_id,
        occurrence_key=index_occurrence_key(index),
        state=OutcomeState.COMPLETED,
        occurred_at=occurred_at,
        confirmed_at=occurred_at + timedelta(hours=1),
        is_make_up=True,
    )


async def test_three_confirmed_skips_charge_three_and_the_row_hears_about_it() -> None:
    habit = a_habit(area_id=uuid4(), miss_policy=MissPolicy.DEBT)
    rows = RowsWithAStoredCharge([habit])
    log = [a_confirmed_skip(habit.id, index=index) for index in range(3)]

    await a_maintainer(rows, log).refresh([habit.id])

    assert rows.written == {habit.id: 3}


async def test_unconfirmed_skips_charge_nothing() -> None:
    habit = a_habit(area_id=uuid4(), miss_policy=MissPolicy.DEBT)
    rows = RowsWithAStoredCharge([habit])
    log = [
        replace(a_confirmed_skip(habit.id, index=index), confirmed_at=None) for index in range(3)
    ]

    await a_maintainer(rows, log).refresh([habit.id])

    assert rows.written == {}


async def test_a_completed_make_up_discharges_one_charge() -> None:
    habit = a_habit(area_id=uuid4(), miss_policy=MissPolicy.DEBT, debt_cap_periods=2)
    rows = RowsWithAStoredCharge([replace(habit, charged_misses=2)])
    log = [
        *([a_confirmed_skip(habit.id, index=index) for index in range(2)]),
        a_completed_make_up(habit.id, index=0),
    ]

    await a_maintainer(rows, log).refresh([habit.id])

    assert rows.written == {habit.id: 1}
    # And the reading answers through the cap arithmetic over the restated count.
    assert debt_cap(habit.as_habit()) == 8


async def test_a_credit_that_arrives_with_nothing_standing_is_dropped_not_carried() -> None:
    """The floor is per credit: a completion with no standing charge settles nothing.

    The credit is walked first because it came due first, hits a count already at zero, and is
    dropped there rather than carried as a minus -- so the skip confirmed afterwards still reads
    as one owed, not zero.
    """
    habit = a_habit(area_id=uuid4(), miss_policy=MissPolicy.DEBT)
    rows = RowsWithAStoredCharge([habit])
    credit = replace(a_completed_make_up(habit.id, index=0), occurred_at=NOW - timedelta(days=9))
    late_skip = replace(
        a_confirmed_skip(habit.id, index=1),
        occurred_at=NOW - timedelta(days=3),
        confirmed_at=NOW - timedelta(hours=12),
    )

    await a_maintainer(rows, [credit, late_skip]).refresh([habit.id])

    assert rows.written == {habit.id: 1}


async def test_a_count_that_already_matches_writes_nothing() -> None:
    """The common case is a presumption landing unconfirmed: no change, no statement."""
    habit = replace(a_habit(area_id=uuid4(), miss_policy=MissPolicy.DEBT), charged_misses=2)
    rows = RowsWithAStoredCharge([habit])
    log = [a_confirmed_skip(habit.id, index=index) for index in range(2)]

    await a_maintainer(rows, log).refresh([habit.id])

    assert rows.written == {}


async def test_only_the_rows_of_the_named_habits_are_walked() -> None:
    ours = a_habit(area_id=uuid4(), miss_policy=MissPolicy.DEBT, title="Anki")
    theirs = a_habit(area_id=uuid4(), miss_policy=MissPolicy.DEBT, title="Gym")
    rows = RowsWithAStoredCharge([ours])
    log = [
        *([a_confirmed_skip(theirs.id, index=index) for index in range(4)]),
        a_confirmed_skip(ours.id, index=0),
    ]
    maintainer = a_maintainer(rows, log)

    await maintainer.refresh([ours.id])

    assert rows.written == {ours.id: 1}
    assert rows.locked == [ours.id], "only the touched habits' rows are held"


async def test_an_empty_request_holds_nothing_and_reads_nothing() -> None:
    habit = a_habit(area_id=uuid4(), miss_policy=MissPolicy.DEBT)
    rows = RowsWithAStoredCharge([habit])
    log = FakeOutcomes()

    await StoredChargedMisses(rows, log, clock=lambda: NOW).refresh([])  # type: ignore[arg-type]

    assert rows.written == {}
    assert log.asked_for == []
