"""Which log the weekly session reads a habit's misses over, driven from stored outcomes.

An ``escalate`` habit is raised for a miss the week under review settled; a ``debt`` habit at its
cap is raised over everything the log holds. Both figures are ``syncr_domain.debt``'s own, so what
is under test here is the WINDOW the session hands it: which stored outcomes reach the raise, and
which session they reach it in.

Every case drives ``SessionSources.read`` over stored outcome rows and reads the raise through
``habit_debt_items``, which is the surface the payload renders. Nothing is asserted against a
reading built beside the log: a hand-built ``DebtReading`` would pass whatever the window did.

**Both consecutive sessions are driven in every case, because a raise is only right if it happens
once.** A miss is settled on the day the user confirms it, which can be weeks after the day it came
due, so the two dates a row carries sit in different weeks whenever a confirmation is late. A window
that reads either date admits such a row twice, in two sessions, which is one miss raised twice.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syncr_api.core.db import create_db_engine, create_sessionmaker
from syncr_api.plans.config import APPLIED
from syncr_api.plans.conflicts import LIST_LIMIT, PlanConflictRepository
from syncr_api.plans.habit_log import HabitOutcomeLog
from syncr_api.plans.pins import PINS_OVER_A_WINDOW, PinRepository
from syncr_api.plans.reality import BlockOutcomeRepository, Presumption
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_documents import stored_document
from syncr_api.promotions.repository import PromotionDeclineRepository
from syncr_api.reviews.config import SESSION_LOOKBACK_WEEKS
from syncr_api.reviews.raised import habit_debt_items
from syncr_api.reviews.session_sources import SessionSources
from syncr_domain.habits import MissPolicy
from syncr_domain.identity import BindingRef, index_occurrence_key
from syncr_domain.outcomes import HabitOutcome, OutcomeState, RecordedOutcome
from syncr_domain.weeks import IsoWeek, week_span
from syncr_domain.zones import ZoneProfile
from tests.assembly_fakes import FakeAnchors, FakeHabits, FakeOutcomes, FakeTasks, a_habit
from tests.live_tenants import delete_tenant, seed_owner
from tests.plan_documents import a_block_holding, a_document, between

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.habits.outcome_log import HabitOutcomeReader
    from syncr_api.habits.records import HabitRecord
    from syncr_api.plans.records import ConflictRecord, PinRecord
    from syncr_domain.identifiers import HabitId, TenantId

HOME_ZONE = "UTC"
PROFILE = ZoneProfile(HOME_ZONE)

# The week a session reviews, and the two sessions that could raise a miss it holds: the one
# planning the week after it, and the one after that.
REVIEWED = IsoWeek(2026, 10)
FIRST_SESSION = REVIEWED.following()
NEXT_SESSION = FIRST_SESSION.following()

# A week far enough behind the reviewed one that no window of either session covers it.
THREE_WEEKS_BACK = REVIEWED.preceding().preceding().preceding()

AREA = uuid4()


def on(week: IsoWeek, *, day: int, hour: int) -> datetime:
    """An instant inside ``week``, ``day`` days after its Monday."""
    return datetime.combine(week.monday() + timedelta(days=day), time(hour), tzinfo=UTC)


def a_planning_morning(planned: IsoWeek) -> datetime:
    """When a session runs: the first morning of the week it plans.

    One clock rule for every case, so a raise that moves between two sessions moves because of the
    window rather than because the two sessions were driven at different times of day.
    """
    return on(planned, day=0, hour=10)


def weeks_ending_at(anchor: IsoWeek) -> tuple[IsoWeek, ...]:
    """The history window a session reads, oldest first, as long as the service's own."""
    walked = [anchor]
    for _ in range(SESSION_LOOKBACK_WEEKS - 1):
        walked.append(walked[-1].preceding())
    return tuple(reversed(walked))


def a_confirmed_skip(
    habit_id: HabitId, *, due: datetime, confirmed: datetime, index: int = 0
) -> HabitOutcome:
    """One occurrence the user answered for by saying it was not done: a miss of the day it was due.

    ``due`` and ``confirmed`` are the two dates a row carries, and they are stated separately in
    every case because a confirmation can arrive any number of weeks after the occurrence.
    """
    return HabitOutcome(
        habit_id=habit_id,
        occurrence_key=index_occurrence_key(index),
        state=OutcomeState.SKIPPED,
        occurred_at=due,
        confirmed_at=confirmed,
    )


class FakeConflicts(PlanConflictRepository):
    """No conflict rows: a collision is a raise of its own and no habit's misses reach it."""

    def __init__(self) -> None:
        """No session and no tenant, because nothing here reaches a database."""

    async def for_weeks(
        self, weeks: Sequence[IsoWeek], *, limit: int = LIST_LIMIT
    ) -> tuple[ConflictRecord, ...]:
        return ()


class FakePins(PinRepository):
    """No pins: a promotion candidate is read from these and no habit's misses reach it."""

    def __init__(self) -> None:
        """No session and no tenant, because nothing here reaches a database."""

    async def for_weeks(
        self, weeks: Sequence[IsoWeek], *, limit: int = PINS_OVER_A_WINDOW
    ) -> tuple[PinRecord, ...]:
        return ()


class FakeDeclines(PromotionDeclineRepository):
    """Nothing silenced, which is what a tenant who has declined no candidate holds."""

    def __init__(self) -> None:
        """No session and no tenant, because nothing here reaches a database."""

    async def silenced_at(self, moment: datetime) -> frozenset[str]:
        return frozenset()


async def raised_habits(
    *, planned: IsoWeek, habits: Sequence[HabitRecord], outcomes: HabitOutcomeReader
) -> list[str]:
    """The habits the session planning ``planned`` raises, named as the payload names them.

    ``outcomes`` is the seam the session reads the log through, so a case drives either rows held in
    memory or the production reader over rows in a database, and asserts the same figure.
    """
    sources = SessionSources(
        tasks=FakeTasks(),
        habits=FakeHabits(habits),
        outcomes=outcomes,
        anchors=FakeAnchors(),
        conflicts=FakeConflicts(),
        pins=FakePins(),
        declines=FakeDeclines(),
    )
    facts = await sources.read(
        planned=planned,
        reviewed=weeks_ending_at(planned.preceding()),
        profile=PROFILE,
        home_zone=HOME_ZONE,
        now=a_planning_morning(planned),
    )
    return [item.title for item in habit_debt_items(facts.habits, facts.debt)]


class TestAMissConfirmedLateIsRaisedExactlyOnce:
    """The week a miss belongs to is the week its day was confirmed in."""

    async def test_a_miss_due_three_weeks_back_and_confirmed_inside_the_week_is_raised(
        self,
    ) -> None:
        # The day came due long before any window either session covers, and the user answered for
        # it on the Friday of the week under review. Reading the day it came due leaves the miss
        # outside every session's window, so it is never raised at all.
        habit = a_habit(area_id=AREA, title="Gym", miss_policy=MissPolicy.ESCALATE)
        stored = FakeOutcomes(
            [
                a_confirmed_skip(
                    habit.id,
                    due=on(THREE_WEEKS_BACK, day=0, hour=9),
                    confirmed=on(REVIEWED, day=4, hour=21),
                )
            ]
        )

        assert await raised_habits(planned=FIRST_SESSION, habits=[habit], outcomes=stored) == [
            "Gym"
        ]

    async def test_that_miss_is_not_raised_again_in_the_session_after(self) -> None:
        habit = a_habit(area_id=AREA, title="Gym", miss_policy=MissPolicy.ESCALATE)
        stored = FakeOutcomes(
            [
                a_confirmed_skip(
                    habit.id,
                    due=on(THREE_WEEKS_BACK, day=0, hour=9),
                    confirmed=on(REVIEWED, day=4, hour=21),
                )
            ]
        )

        assert await raised_habits(planned=NEXT_SESSION, habits=[habit], outcomes=stored) == []

    async def test_a_confirmation_after_the_week_it_answers_for_is_raised_once_and_not_twice(
        self,
    ) -> None:
        # The Sunday of the reviewed week, answered for on the Monday after it. The two dates sit in
        # two different weeks, so a window admitting EITHER of them raises this miss in both
        # sessions. It is raised in the session that follows the confirmation.
        habit = a_habit(area_id=AREA, title="Gym", miss_policy=MissPolicy.ESCALATE)
        stored = FakeOutcomes(
            [
                a_confirmed_skip(
                    habit.id,
                    due=on(REVIEWED, day=6, hour=9),
                    confirmed=on(FIRST_SESSION, day=0, hour=8),
                )
            ]
        )

        first = await raised_habits(planned=FIRST_SESSION, habits=[habit], outcomes=stored)
        after = await raised_habits(planned=NEXT_SESSION, habits=[habit], outcomes=stored)

        assert [*first, *after] == ["Gym"], "one miss, one raise, across two consecutive sessions"


class TestAMissTheReviewedWeekSettledIsStillRaisedNextSession:
    async def test_a_miss_due_and_confirmed_inside_the_reviewed_week_is_raised(self) -> None:
        habit = a_habit(area_id=AREA, title="Gym", miss_policy=MissPolicy.ESCALATE)
        stored = FakeOutcomes(
            [
                a_confirmed_skip(
                    habit.id,
                    due=on(REVIEWED, day=2, hour=9),
                    confirmed=on(REVIEWED, day=2, hour=21),
                )
            ]
        )

        assert await raised_habits(planned=FIRST_SESSION, habits=[habit], outcomes=stored) == [
            "Gym"
        ]

    async def test_it_is_not_raised_again_in_the_session_after(self) -> None:
        habit = a_habit(area_id=AREA, title="Gym", miss_policy=MissPolicy.ESCALATE)
        stored = FakeOutcomes(
            [
                a_confirmed_skip(
                    habit.id,
                    due=on(REVIEWED, day=2, hour=9),
                    confirmed=on(REVIEWED, day=2, hour=21),
                )
            ]
        )

        assert await raised_habits(planned=NEXT_SESSION, habits=[habit], outcomes=stored) == []

    async def test_a_miss_settled_three_weeks_back_reaches_neither_session(self) -> None:
        # Both dates sit outside both windows, which is what makes the window a window: an
        # `escalate` habit read over the whole log is raised in every session it ever has.
        habit = a_habit(area_id=AREA, title="Gym", miss_policy=MissPolicy.ESCALATE)
        stored = FakeOutcomes(
            [
                a_confirmed_skip(
                    habit.id,
                    due=on(THREE_WEEKS_BACK, day=0, hour=9),
                    confirmed=on(THREE_WEEKS_BACK, day=0, hour=21),
                )
            ]
        )

        assert await raised_habits(planned=FIRST_SESSION, habits=[habit], outcomes=stored) == []
        assert await raised_habits(planned=NEXT_SESSION, habits=[habit], outcomes=stored) == []


class TestTheWindowIsHalfOpenLikeEverySpanInThisProduct:
    async def test_a_confirmation_at_the_first_instant_of_the_reviewed_week_is_inside_it(
        self,
    ) -> None:
        habit = a_habit(area_id=AREA, title="Gym", miss_policy=MissPolicy.ESCALATE)
        stored = FakeOutcomes(
            [
                a_confirmed_skip(
                    habit.id,
                    due=on(THREE_WEEKS_BACK, day=0, hour=9),
                    confirmed=on(REVIEWED, day=0, hour=0),
                )
            ]
        )

        first = await raised_habits(planned=FIRST_SESSION, habits=[habit], outcomes=stored)
        after = await raised_habits(planned=NEXT_SESSION, habits=[habit], outcomes=stored)

        assert (first, after) == (["Gym"], [])

    async def test_a_confirmation_at_the_first_instant_after_it_belongs_to_the_week_that_holds_it(
        self,
    ) -> None:
        # The instant the reviewed week ends is the instant the next one starts, and it is the next
        # one's: a window closed on both sides raises this miss in both sessions.
        habit = a_habit(area_id=AREA, title="Gym", miss_policy=MissPolicy.ESCALATE)
        stored = FakeOutcomes(
            [
                a_confirmed_skip(
                    habit.id,
                    due=on(THREE_WEEKS_BACK, day=0, hour=9),
                    confirmed=on(FIRST_SESSION, day=0, hour=0),
                )
            ]
        )

        first = await raised_habits(planned=FIRST_SESSION, habits=[habit], outcomes=stored)
        after = await raised_habits(planned=NEXT_SESSION, habits=[habit], outcomes=stored)

        assert (first, after) == ([], ["Gym"])


class TestADebtHabitAtItsCapIsRaisedWhicheverWeekTheSessionCovers:
    async def test_a_backlog_settled_three_weeks_back_is_raised_in_both_sessions(self) -> None:
        # A `debt` habit's cap is an accumulated figure over the whole log, so the window the
        # `escalate` raise takes must not narrow it. The charge reads off the row the outcome write
        # restated -- here carried past every session's window as a stored count of two, from two
        # misses three weeks back that no window either session covers. One a week capped at one
        # period owes at most one session, and two misses put it over.
        habit = replace(
            a_habit(
                area_id=AREA,
                title="Anki",
                miss_policy=MissPolicy.DEBT,
                times_per_week=1,
                debt_cap_periods=1,
            ),
            charged_misses=2,
        )
        stored = FakeOutcomes()

        assert await raised_habits(planned=FIRST_SESSION, habits=[habit], outcomes=stored) == [
            "Anki"
        ]
        assert await raised_habits(planned=NEXT_SESSION, habits=[habit], outcomes=stored) == [
            "Anki"
        ]


@pytest.mark.integration
async def test_the_settled_read_is_half_open_over_stored_confirmations(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    """The bounded read's window is ``start <= confirmed_at < end``, against real rows.

    A confirmation at the reviewed week's first instant is inside it; a confirmation at the
    instant the week ends belongs to the session that follows, not to this one.
    """
    habit = a_habit(area_id=AREA, title="Gym", miss_policy=MissPolicy.ESCALATE)
    binding = BindingRef.for_habit(habit.id, index=0)
    await store_a_confirmed_skip(
        sessions,
        owner.tenant_id,
        binding=binding,
        week=THREE_WEEKS_BACK,
        confirmed=on(REVIEWED, day=0, hour=0),
    )
    await store_a_confirmed_skip(
        sessions,
        owner.tenant_id,
        binding=BindingRef.for_habit(habit.id, index=1),
        week=THREE_WEEKS_BACK,
        confirmed=on(FIRST_SESSION, day=0, hour=0),
    )

    async with sessions() as session:
        log = HabitOutcomeLog(session, owner.tenant_id)
        found = await log.settled_within(
            [habit.id], span=week_span(REVIEWED, ZoneProfile(HOME_ZONE))
        )

    keys = {row.occurrence_key for row in found}
    assert keys == {index_occurrence_key(0)}, "the end instant belongs to the next week"


@pytest.fixture
async def engine(live_database_url: str) -> AsyncIterator[AsyncEngine]:
    live = create_db_engine(live_database_url)
    yield live
    await live.dispose()


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_sessionmaker(engine)


@pytest.fixture
async def owner(sessions: async_sessionmaker[AsyncSession]) -> AsyncIterator[UserRecord]:
    account = await seed_owner(sessions)
    yield account
    await delete_tenant(sessions, account.tenant_id)


async def store_a_confirmed_skip(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    *,
    binding: BindingRef,
    week: IsoWeek,
    confirmed: datetime,
) -> None:
    """One skip of one occurrence of ``week``, through the two writers the Today screen drives.

    ``record`` states what the user said happened and ``settle`` stamps the day they answered for,
    which is the pair that makes a confirmed miss: an unstamped row is presumed rather than missed.
    The revision is what the row references, because the schema holds the log to plans that exist.
    """
    placed = between(9, 10, week=week)
    block = a_block_holding(binding, placed, week=week)
    async with sessions() as session, session.begin():
        revision = await PlanRepository(session, tenant_id).append(
            document=stored_document(a_document(week=week, blocks=(block,))),
            objective_breakdown={},
            status=APPLIED,
            reason="materialized",
            weight_set_version=1,
            input_version=1,
            created_at=placed.start,
        )
        outcomes = BlockOutcomeRepository(session, tenant_id)
        await outcomes.record(
            RecordedOutcome(binding=binding, state=OutcomeState.SKIPPED),
            block_id=block.id,
            revision_id=revision.id,
            occurred_at=placed.start,
        )
        await outcomes.settle(
            [
                Presumption(
                    block_id=block.id,
                    binding=binding,
                    revision_id=revision.id,
                    occurred_at=placed.start,
                )
            ],
            at=confirmed,
        )


@pytest.mark.integration
async def test_a_stored_confirmation_is_the_week_the_raise_reads(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    """The same property over rows in Postgres, read through the production projection.

    The two dates reach the window as columns rather than as constructed values, which is what says
    the confirmation instant survives the write path: a projection that dropped it would leave every
    ``escalate`` habit silent, and no reading in memory could tell.
    """
    habit = a_habit(area_id=AREA, title="Gym", miss_policy=MissPolicy.ESCALATE)
    binding = BindingRef.for_habit(habit.id, index=0)
    await store_a_confirmed_skip(
        sessions,
        owner.tenant_id,
        binding=binding,
        week=THREE_WEEKS_BACK,
        confirmed=on(REVIEWED, day=4, hour=21),
    )

    async with sessions() as session:
        log = HabitOutcomeLog(session, owner.tenant_id)
        first = await raised_habits(planned=FIRST_SESSION, habits=[habit], outcomes=log)
        after = await raised_habits(planned=NEXT_SESSION, habits=[habit], outcomes=log)

    assert (first, after) == (["Gym"], []), "one stored miss, one raise, two consecutive sessions"
