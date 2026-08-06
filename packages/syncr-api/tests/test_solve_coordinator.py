"""The single-flight invariant, the debounce window, and the claim scan, against a real Postgres.

The invariant is a partial unique index and the claim's atomicity is the ``WHERE`` clause of its own
statement, so neither can be proved with a fake: a fake would be asserting the reading this suite
exists to check. Every test here drives real rows.

Five groups.

**Idempotence per week, and the one exception.** With nothing in flight a request creates one
pending operation; with one pending and not immediate it leaves it, which is the coalescing step;
with one pending and immediate it pulls the due instant forward; with one running it does nothing at
all, because the mutation that asked has already bumped the version.

**A tradeoff request is the exception**, and it may never join: it supersedes a pending operation
and takes its place, it is refused rather than queued while a solve is running, and a pending
tradeoff is left alone by an ordinary mutation so its concession is not lost.

**The window is fixed from the first mutation of a burst, not slid by later ones.** A burst of two
hundred edits resolves within one window of its start and creates exactly one operation, which is
the property the whole design rests on.

**Supersession enqueues exactly one follow-up, which carries the candidate forward** and is named
on the row it displaced.

**The claim scan takes one due operation and skips a lost race**, because a tradeoff request and the
reaper can both finish a row between the scan's read and its claim.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from syncr_api.core.db import create_db_engine, create_sessionmaker
from syncr_api.core.settings import DEFAULT_SOLVE_DEBOUNCE_MS
from syncr_api.solving.config import (
    PENDING,
    RUNNING,
    SOLVE,
    SUPERSEDED,
)
from syncr_api.solving.coordinator import SolveCoordinator
from syncr_api.solving.errors import SolveIsRunning
from syncr_api.solving.injection import build_solve_coordinator, debounce_window
from syncr_api.solving.lifecycle import OperationLifecycle
from syncr_api.solving.metrics import SOLVE_TALLY
from syncr_api.solving.outcomes import Superseded
from syncr_api.solving.repository import OperationRepository
from syncr_common.metrics import REGISTRY
from syncr_domain.weeks import IsoWeek
from tests.live_tenants import delete_tenant, seed_owner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.solving.records import OperationRecord

pytestmark = pytest.mark.integration

WEEK = IsoWeek(2026, 7)
NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)

# The version a caller reports having acknowledged. Compared to nothing by design, so its value is
# arbitrary and a test that asserted on it would be asserting the opposite of the rule.
AT_VERSION = 47

A_CANDIDATE = {
    "adjustmentId": "0f5b7d0a-1c7d-4a6c-9b64-2a2b0e7d9f11",
    "kind": "breach_floor",
    "targetId": "1a2b3c4d-5e6f-4a8b-9c0d-1e2f3a4b5c6d",
    "reductions": {},
    "deltaMinutes": 60,
}
ANOTHER_CANDIDATE = A_CANDIDATE | {"deltaMinutes": 30}


class Ticking:
    """A clock a test moves by hand, so a debounce window is arithmetic rather than a sleep."""

    def __init__(self, at: datetime = NOW) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at

    def advance(self, by: timedelta) -> None:
        self.at += by


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


@pytest.fixture
def clock() -> Ticking:
    return Ticking()


type Build = Callable[[AsyncSession], SolveCoordinator]


@pytest.fixture
def coordinator(owner: UserRecord, clock: Ticking) -> Build:
    """A coordinator over a caller-supplied session, so a test owns its transaction."""

    def build(session: AsyncSession) -> SolveCoordinator:
        return build_solve_coordinator(
            session,
            owner.tenant_id,
            clock=clock,
            debounce=debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS),
        )

    return build


async def requested(
    sessions: async_sessionmaker[AsyncSession], coordinator: Build, **overrides: object
) -> OperationRecord:
    """One request, committed, so the next one reads a real row."""
    async with sessions() as session, session.begin():
        return await coordinator(session).request_solve(WEEK, AT_VERSION, **overrides)  # type: ignore[arg-type]


async def solves(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> list[OperationRecord]:
    """Every solve this tenant holds, newest first."""
    async with sessions() as session:
        return await OperationRepository(session, owner.tenant_id).page(limit=500, kind=SOLVE)


async def read(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, operation: OperationRecord
) -> OperationRecord:
    async with sessions() as session:
        found = await OperationRepository(session, owner.tenant_id).find(operation.id)
    assert found is not None
    return found


class TestIdempotencePerWeek:
    async def test_a_request_against_nothing_schedules_one_solve_at_the_end_of_the_window(
        self, sessions: async_sessionmaker[AsyncSession], coordinator: Build, owner: UserRecord
    ) -> None:
        created = await requested(sessions, coordinator)

        assert created.status == PENDING
        assert created.scheduled_for == NOW + debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS)
        assert [one.id for one in await solves(sessions, owner)] == [created.id]

    async def test_an_immediate_request_against_nothing_is_due_now(
        self, sessions: async_sessionmaker[AsyncSession], coordinator: Build
    ) -> None:
        created = await requested(sessions, coordinator, immediate=True)

        assert created.scheduled_for == NOW

    async def test_a_second_ordinary_request_joins_the_pending_one(
        self, sessions: async_sessionmaker[AsyncSession], coordinator: Build, owner: UserRecord
    ) -> None:
        first = await requested(sessions, coordinator)

        joined = await requested(sessions, coordinator)

        assert joined.id == first.id
        assert len(await solves(sessions, owner)) == 1

    async def test_the_window_is_not_extended_by_a_later_mutation_inside_it(
        self,
        sessions: async_sessionmaker[AsyncSession],
        coordinator: Build,
        clock: Ticking,
    ) -> None:
        # The whole reason the window is fixed from the first mutation: slid forward per edit, a
        # user editing continuously would never get a solve at all.
        first = await requested(sessions, coordinator)
        clock.advance(timedelta(milliseconds=900))

        joined = await requested(sessions, coordinator)

        assert joined.scheduled_for == first.scheduled_for

    async def test_an_immediate_request_pulls_a_pending_window_forward(
        self, sessions: async_sessionmaker[AsyncSession], coordinator: Build, clock: Ticking
    ) -> None:
        await requested(sessions, coordinator)
        clock.advance(timedelta(milliseconds=200))

        pulled = await requested(sessions, coordinator, immediate=True)

        assert pulled.scheduled_for == clock.at

    async def test_a_request_while_one_is_running_creates_nothing(
        self,
        sessions: async_sessionmaker[AsyncSession],
        coordinator: Build,
        owner: UserRecord,
        clock: Ticking,
    ) -> None:
        # The mutation that asked has already bumped the version, so the running solve's own
        # conditional write is what notices. No flag and no second operation are needed.
        running = await claimed(sessions, coordinator, owner, clock)

        joined = await requested(sessions, coordinator)

        assert joined.id == running.id
        assert joined.status == RUNNING
        assert len(await solves(sessions, owner)) == 1


class TestABurstWastesAtMostOneSolve:
    @pytest.mark.parametrize("edits", [12, 200], ids=["twelve edits", "two hundred edits"])
    async def test_a_burst_of_any_length_produces_exactly_one_solve(
        self,
        sessions: async_sessionmaker[AsyncSession],
        coordinator: Build,
        owner: UserRecord,
        clock: Ticking,
        edits: int,
    ) -> None:
        """The bounded-waste guarantee, from the coalescing side.

        Every edit of the burst requests a solve inside the window the first one opened, and the
        week ends with ONE pending operation: the waste a supersession costs is bounded because
        there is only ever one solve to discard.
        """
        for _ in range(edits):
            await requested(sessions, coordinator)
            clock.advance(timedelta(milliseconds=5))

        assert len(await solves(sessions, owner)) == 1

    async def test_the_burst_resolves_within_one_window_of_its_start(
        self, sessions: async_sessionmaker[AsyncSession], coordinator: Build, clock: Ticking
    ) -> None:
        window = debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS)
        opened = clock.at

        first = await requested(sessions, coordinator)
        for _ in range(20):
            clock.advance(timedelta(milliseconds=50))
            await requested(sessions, coordinator)

        assert first.scheduled_for == opened + window


class TestATradeoffNeverJoins:
    async def test_a_request_carrying_a_candidate_supersedes_the_pending_one(
        self, sessions: async_sessionmaker[AsyncSession], coordinator: Build, owner: UserRecord
    ) -> None:
        # A pin made two seconds earlier would otherwise absorb the concession, and the proposal
        # would come back without it, which reads as syncr having ignored the request.
        pin = await requested(sessions, coordinator)

        tradeoff = await requested(sessions, coordinator, candidate=A_CANDIDATE)

        assert tradeoff.id != pin.id
        assert tradeoff.candidate_adjustment == A_CANDIDATE
        assert tradeoff.scheduled_for == NOW
        displaced = await read(sessions, owner, pin)
        assert displaced.status == SUPERSEDED
        assert displaced.superseded_by == tradeoff.id

    async def test_a_candidate_against_a_running_solve_is_refused_rather_than_queued(
        self,
        sessions: async_sessionmaker[AsyncSession],
        coordinator: Build,
        owner: UserRecord,
        clock: Ticking,
    ) -> None:
        # Queueing it would need a second non-terminal solve for the week, which is the invariant
        # this component exists to hold. The refusal is bounded by the solve's own budget.
        await claimed(sessions, coordinator, owner, clock)

        with pytest.raises(SolveIsRunning):
            await requested(sessions, coordinator, candidate=A_CANDIDATE)

        assert len(await solves(sessions, owner)) == 1

    async def test_an_ordinary_mutation_leaves_a_pending_tradeoff_alone(
        self, sessions: async_sessionmaker[AsyncSession], coordinator: Build, owner: UserRecord
    ) -> None:
        # Its own version bump supersedes the tradeoff after it runs, and the follow-up carries the
        # candidate forward, so the concession survives without being displaced here.
        tradeoff = await requested(sessions, coordinator, candidate=A_CANDIDATE)

        joined = await requested(sessions, coordinator)

        assert joined.id == tradeoff.id
        assert joined.candidate_adjustment == A_CANDIDATE

    async def test_an_immediate_mutation_does_not_pull_a_pending_tradeoff_forward_either(
        self, sessions: async_sessionmaker[AsyncSession], coordinator: Build, clock: Ticking
    ) -> None:
        tradeoff = await requested(sessions, coordinator, candidate=A_CANDIDATE)
        clock.advance(timedelta(seconds=5))

        joined = await requested(sessions, coordinator, immediate=True)

        assert joined.scheduled_for == tradeoff.scheduled_for

    async def test_a_second_tradeoff_supersedes_the_first(
        self, sessions: async_sessionmaker[AsyncSession], coordinator: Build, owner: UserRecord
    ) -> None:
        first = await requested(sessions, coordinator, candidate=A_CANDIDATE)

        second = await requested(sessions, coordinator, candidate=ANOTHER_CANDIDATE)

        assert second.candidate_adjustment == ANOTHER_CANDIDATE
        assert (await read(sessions, owner, first)).status == SUPERSEDED


class TestSupersessionEnqueuesExactlyOneFollowUp:
    async def test_a_superseded_solve_leaves_one_follow_up_that_names_it(
        self,
        sessions: async_sessionmaker[AsyncSession],
        coordinator: Build,
        owner: UserRecord,
        clock: Ticking,
    ) -> None:
        running = await claimed(sessions, coordinator, owner, clock)

        async with sessions() as session, session.begin():
            superseded = await coordinator(session).finish(running, Superseded())

        pending = [one for one in await solves(sessions, owner) if one.status == PENDING]
        assert len(pending) == 1
        assert superseded.status == SUPERSEDED
        assert superseded.superseded_by == pending[0].id

    async def test_the_follow_up_carries_the_candidate_forward(
        self,
        sessions: async_sessionmaker[AsyncSession],
        coordinator: Build,
        owner: UserRecord,
        clock: Ticking,
    ) -> None:
        # Otherwise a pin landing mid-solve discards the concession the user asked for.
        tradeoff = await requested(sessions, coordinator, candidate=A_CANDIDATE, immediate=True)
        async with sessions() as session, session.begin():
            running = await OperationLifecycle(
                OperationRepository(session, owner.tenant_id), clock
            ).claim(tradeoff.id)

        async with sessions() as session, session.begin():
            await coordinator(session).finish(running, Superseded())

        pending = [one for one in await solves(sessions, owner) if one.status == PENDING]
        assert [one.candidate_adjustment for one in pending] == [A_CANDIDATE]

    async def test_a_supersession_is_counted_and_the_ratio_follows_the_counter(
        self,
        sessions: async_sessionmaker[AsyncSession],
        coordinator: Build,
        owner: UserRecord,
        clock: Ticking,
    ) -> None:
        # The ratio is the health signal the debounce value is read from, and it is set from the
        # same tally that increments the counter so the two cannot disagree about how many there
        # were.
        before = dict(SOLVE_TALLY.counts)
        running = await claimed(sessions, coordinator, owner, clock)

        async with sessions() as session, session.begin():
            await coordinator(session).finish(running, Superseded())

        assert SOLVE_TALLY.counts[SUPERSEDED] == before[SUPERSEDED] + 1
        ratio = REGISTRY.get_sample_value("syncr_solve_superseded_ratio")
        assert ratio == pytest.approx(
            SOLVE_TALLY.counts[SUPERSEDED] / sum(SOLVE_TALLY.counts.values())
        )


class TestTheClaimScan:
    async def test_nothing_due_claims_nothing(
        self, sessions: async_sessionmaker[AsyncSession], coordinator: Build
    ) -> None:
        await requested(sessions, coordinator)

        async with sessions() as session, session.begin():
            assert await coordinator(session).claim_next() is None

    async def test_a_due_solve_is_claimed_atomically(
        self, sessions: async_sessionmaker[AsyncSession], coordinator: Build, clock: Ticking
    ) -> None:
        created = await requested(sessions, coordinator)
        clock.advance(debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS))

        async with sessions() as session, session.begin():
            claimed_row = await coordinator(session).claim_next()

        assert claimed_row is not None
        assert claimed_row.id == created.id
        assert claimed_row.status == RUNNING

    async def test_a_lost_claim_race_is_skipped_rather_than_failed(
        self,
        sessions: async_sessionmaker[AsyncSession],
        coordinator: Build,
        owner: UserRecord,
        clock: Ticking,
    ) -> None:
        """A row the scan read as pending and something else finished is a skip, not a fault.

        The scan and the claim are separate statements, and the window between them cannot be
        opened from outside the coordinator: a second session's commit is visible to the scan's own
        read. So the queue is the seam, standing for a row that moved in that window, and what is
        driven is the branch the real race reaches: the claim matching no row, counted and skipped.
        """
        created = await requested(sessions, coordinator)
        async with sessions() as session, session.begin():
            await OperationLifecycle(OperationRepository(session, owner.tenant_id), clock).finish(
                created.id, Superseded()
            )
        before = REGISTRY.get_sample_value("syncr_solve_claim_races_lost_total") or 0.0

        async with sessions() as session, session.begin():
            assert await self._scanning(session, owner, clock, stale=created).claim_next() is None

        lost = REGISTRY.get_sample_value("syncr_solve_claim_races_lost_total") or 0.0
        assert lost == before + 1.0

    async def test_the_scan_takes_the_next_due_operation_after_a_lost_race(
        self,
        sessions: async_sessionmaker[AsyncSession],
        coordinator: Build,
        owner: UserRecord,
        clock: Ticking,
    ) -> None:
        # The control for the skip: losing one claim must not stop the pass, or a tenant whose
        # oldest row keeps moving would never have a later one claimed.
        gone = await requested(sessions, coordinator)
        async with sessions() as session, session.begin():
            await OperationLifecycle(OperationRepository(session, owner.tenant_id), clock).finish(
                gone.id, Superseded()
            )
        clock.advance(debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS))
        live = await requested(sessions, coordinator, immediate=True)

        async with sessions() as session, session.begin():
            claimed_row = await self._scanning(
                session, owner, clock, stale=gone, also=live
            ).claim_next()

        assert claimed_row is not None
        assert claimed_row.id == live.id

    @staticmethod
    def _scanning(
        session: AsyncSession,
        owner: UserRecord,
        clock: Ticking,
        *,
        stale: OperationRecord,
        also: OperationRecord | None = None,
    ) -> SolveCoordinator:
        """A coordinator whose scan answers with a row that has already moved on."""
        operations = OperationRepository(session, owner.tenant_id)
        return SolveCoordinator(
            operations=operations,
            queue=StaleQueue((stale, *(() if also is None else (also,)))),
            lifecycle=OperationLifecycle(operations, clock),
            clock=clock,
            debounce=debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS),
        )


class StaleQueue:
    """A queue answering with rows as they were, standing for the window between read and claim."""

    def __init__(self, due: tuple[OperationRecord, ...]) -> None:
        self._due = due

    async def due(self, **_asked: object) -> tuple[OperationRecord, ...]:
        return self._due


async def claimed(
    sessions: async_sessionmaker[AsyncSession],
    coordinator: Build,
    owner: UserRecord,
    clock: Ticking,
) -> OperationRecord:
    """One solve of the week, requested and claimed, so a test can drive the running case."""
    created = await requested(sessions, coordinator, immediate=True)
    async with sessions() as session, session.begin():
        return await OperationLifecycle(OperationRepository(session, owner.tenant_id), clock).claim(
            created.id
        )
