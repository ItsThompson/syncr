"""The operation lifecycle against a real Postgres: the machine, the retry, and the reaper.

The state machine is enforced by the ``WHERE`` clause of each step's own statement, so it cannot be
proved with a fake: what makes a step legal is a predicate the database evaluates, and a fake would
be asserting the reading this suite exists to check. Every test here therefore drives real rows.

Four groups.

**Every step the machine names, and every step it does not.** Each of the legal steps is driven, and
each illegal one is driven from the status that cannot take it, asserted to name the status the row
was actually in rather than to write it anyway.

**A failure decides its own retry.** The attempt rises, the next due instant is pushed out, and the
snapshot is kept on the last attempt and on no earlier one, because the table forbids a snapshot on
any status but ``failed`` and a retried row is ``pending``.

**Supersession is not a failure.** The words differ and the sentences differ, which is the whole
point: presenting a displaced solve as a failure would make editing quickly look broken.

**The reaper and the retention sweep.** An abandoned claim comes back with its attempt raised, an
abandoned claim on its last attempt fails terminally instead of looping forever, and the sweep takes
the two status sets past their windows and nothing else.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syncr_api.core.db import create_db_engine, create_sessionmaker
from syncr_api.solving.config import (
    CALENDAR_SYNC,
    FAILED,
    FAILED_RETENTION,
    FIRST_ATTEMPT,
    LEASE,
    LEASE_EXPIRED,
    MAX_ATTEMPTS,
    PENDING,
    RETRY_BACKOFF,
    RUNNING,
    SOLVE,
    SUCCEEDED,
    SUCCEEDED_RETENTION,
    SUPERSEDED,
)
from syncr_api.solving.errors import IllegalTransition, OperationMovedOn, OperationNotFound
from syncr_api.solving.lifecycle import OperationLifecycle
from syncr_api.solving.maintenance import OperationMaintenance, maintenance_for
from syncr_api.solving.outcomes import Failed, Succeeded, Superseded
from syncr_api.solving.reporting import STATEMENT_BY_STATUS, statement
from syncr_api.solving.repository import OperationRepository
from syncr_api.solving.sweeps import OperationSweeps
from syncr_api.solving.transitions import (
    LEGAL_TRANSITIONS,
    is_terminal,
    may_retry,
    may_transition,
    statuses_that_may_become,
)
from syncr_domain.weeks import IsoWeek
from tests.live_tenants import delete_tenant, seed_owner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.solving.config import OperationStatus
    from syncr_api.solving.records import OperationRecord
    from syncr_domain.identifiers import OperationId

pytestmark = pytest.mark.integration

WEEK = IsoWeek(2026, 7)
NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)

A_SNAPSHOT = {"iso_week": str(WEEK), "areas": []}


class Ticking:
    """A clock a test moves by hand, so a lease and a backoff are arithmetic rather than a sleep."""

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


type Lifecycle = Callable[[AsyncSession], OperationLifecycle]


@pytest.fixture
def lifecycle(owner: UserRecord, clock: Ticking) -> Lifecycle:
    """A lifecycle over a caller-supplied session, so a test owns its transaction."""

    def build(session: AsyncSession) -> OperationLifecycle:
        return OperationLifecycle(OperationRepository(session, owner.tenant_id), clock)

    return build


async def enqueued(
    sessions: async_sessionmaker[AsyncSession], lifecycle: Lifecycle, **overrides: object
) -> OperationRecord:
    """One pending solve for the week, committed, so a later step reads a real row."""
    fields: dict[str, object] = {"kind": SOLVE, "iso_week": WEEK} | overrides
    async with sessions() as session, session.begin():
        return await lifecycle(session).enqueue(**fields)  # type: ignore[arg-type]


async def stepped(
    sessions: async_sessionmaker[AsyncSession],
    lifecycle: Lifecycle,
    step: Callable[[OperationLifecycle], Awaitable[OperationRecord]],
) -> OperationRecord:
    """One step, in its own committed transaction, so the next read sees what it wrote."""
    async with sessions() as session, session.begin():
        return await step(lifecycle(session))


async def held(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, operation_id: OperationId
) -> OperationRecord:
    """The stored row, read through the repository: the read service answers a request, so it wants
    a principal this suite has no reason to build.
    """
    async with sessions() as session:
        found = await OperationRepository(session, owner.tenant_id).find(operation_id)
    assert found is not None
    return found


# --------------------------------------------------------------------------------
# The machine
# --------------------------------------------------------------------------------


def test_the_machine_names_a_step_out_of_every_status() -> None:
    """The table is total over the vocabulary, so no status is a state with no reading."""
    from syncr_api.solving.config import OPERATION_STATUSES

    assert set(LEGAL_TRANSITIONS) == set(OPERATION_STATUSES)


@pytest.mark.parametrize(
    ("leaving", "to"),
    [
        (PENDING, RUNNING),
        (PENDING, SUPERSEDED),
        (RUNNING, SUCCEEDED),
        (RUNNING, SUPERSEDED),
        (RUNNING, FAILED),
        (FAILED, PENDING),
    ],
    ids=lambda value: str(value),
)
def test_each_step_the_diagram_draws_exists(leaving: OperationStatus, to: OperationStatus) -> None:
    assert may_transition(at_status=leaving, to=to)
    assert leaving in statuses_that_may_become(to)


@pytest.mark.parametrize(
    ("leaving", "to"),
    [
        (PENDING, SUCCEEDED),
        (PENDING, FAILED),
        (RUNNING, PENDING),
        (SUCCEEDED, PENDING),
        (SUPERSEDED, RUNNING),
        (FAILED, RUNNING),
    ],
    ids=lambda value: str(value),
)
def test_no_other_step_exists(leaving: OperationStatus, to: OperationStatus) -> None:
    """``running`` to ``pending`` is deliberately absent: a dying worker is a failure."""
    assert not may_transition(at_status=leaving, to=to)


def test_a_succeeded_operation_is_terminal_whatever_its_attempt() -> None:
    assert is_terminal(status=SUCCEEDED, attempt=FIRST_ATTEMPT)
    assert is_terminal(status=SUPERSEDED, attempt=MAX_ATTEMPTS)


def test_a_failure_is_terminal_only_once_its_attempts_are_spent() -> None:
    assert not is_terminal(status=FAILED, attempt=FIRST_ATTEMPT)
    assert is_terminal(status=FAILED, attempt=MAX_ATTEMPTS)
    assert not may_retry(status=FAILED, attempt=MAX_ATTEMPTS)


def test_a_non_terminal_status_is_never_terminal() -> None:
    assert not is_terminal(status=PENDING, attempt=MAX_ATTEMPTS)
    assert not is_terminal(status=RUNNING, attempt=MAX_ATTEMPTS)


async def test_an_operation_runs_from_pending_through_running_to_succeeded(
    sessions: async_sessionmaker[AsyncSession], lifecycle: Lifecycle, clock: Ticking
) -> None:
    created = await enqueued(sessions, lifecycle)
    assert (created.status, created.attempt, created.started_at) == (PENDING, FIRST_ATTEMPT, None)

    claimed = await stepped(sessions, lifecycle, lambda one: one.claim(created.id))
    assert (claimed.status, claimed.started_at) == (RUNNING, clock.at)

    finished = await stepped(sessions, lifecycle, lambda one: one.finish(created.id, Succeeded()))
    assert (finished.status, finished.finished_at) == (SUCCEEDED, clock.at)


async def test_a_pending_operation_cannot_succeed_without_running(
    sessions: async_sessionmaker[AsyncSession], lifecycle: Lifecycle
) -> None:
    created = await enqueued(sessions, lifecycle)

    with pytest.raises(OperationMovedOn, match=f"cannot become '{SUCCEEDED}' from '{PENDING}'"):
        await stepped(sessions, lifecycle, lambda one: one.finish(created.id, Succeeded()))


async def test_a_succeeded_operation_cannot_be_claimed_again(
    sessions: async_sessionmaker[AsyncSession], lifecycle: Lifecycle
) -> None:
    created = await enqueued(sessions, lifecycle)
    await stepped(sessions, lifecycle, lambda one: one.claim(created.id))
    await stepped(sessions, lifecycle, lambda one: one.finish(created.id, Succeeded()))

    with pytest.raises(OperationMovedOn, match=f"from '{SUCCEEDED}'"):
        await stepped(sessions, lifecycle, lambda one: one.claim(created.id))


async def test_a_pending_operation_may_be_superseded_by_an_immediate_request(
    sessions: async_sessionmaker[AsyncSession], lifecycle: Lifecycle
) -> None:
    """The one step out of ``pending`` that is not a claim, and it is not an error."""
    created = await enqueued(sessions, lifecycle)
    follow_up = uuid4()

    closed = await stepped(
        sessions, lifecycle, lambda one: one.finish(created.id, Superseded(superseded_by=follow_up))
    )

    assert (closed.status, closed.superseded_by) == (SUPERSEDED, follow_up)


async def test_another_tenants_operation_cannot_be_stepped(
    sessions: async_sessionmaker[AsyncSession], lifecycle: Lifecycle
) -> None:
    """An absent row is a caller defect and has its own type: nothing races one into existence."""
    with pytest.raises(OperationNotFound, match="this tenant has no such row"):
        await stepped(sessions, lifecycle, lambda one: one.claim(uuid4()))


async def test_a_succeeded_operation_names_the_revision_it_appended(
    sessions: async_sessionmaker[AsyncSession], lifecycle: Lifecycle
) -> None:
    created = await enqueued(
        sessions, lifecycle, kind=CALENDAR_SYNC, iso_week=None, source_id=uuid4()
    )
    await stepped(sessions, lifecycle, lambda one: one.claim(created.id))

    finished = await stepped(sessions, lifecycle, lambda one: one.finish(created.id, Succeeded()))

    # A sync appends no revision, which is why the field is nullable rather than absent.
    assert finished.result_revision_id is None


# --------------------------------------------------------------------------------
# A failure decides its own retry
# --------------------------------------------------------------------------------


async def test_a_first_failure_comes_back_as_the_next_attempt(
    sessions: async_sessionmaker[AsyncSession], lifecycle: Lifecycle, clock: Ticking
) -> None:
    created = await enqueued(sessions, lifecycle)
    await stepped(sessions, lifecycle, lambda one: one.claim(created.id))

    retried = await stepped(
        sessions,
        lifecycle,
        lambda one: one.finish(created.id, Failed(code="solver_raised", message="it raised")),
    )

    assert retried.status == PENDING
    assert retried.attempt == FIRST_ATTEMPT + 1
    assert retried.scheduled_for == clock.at + RETRY_BACKOFF
    assert retried.finished_at is None, "a row that will run again is not finished"
    assert retried.error_code == "solver_raised", "a retrying job must not be silent"


async def test_the_backoff_doubles_with_the_attempts_already_spent(
    sessions: async_sessionmaker[AsyncSession], lifecycle: Lifecycle, clock: Ticking
) -> None:
    created = await enqueued(sessions, lifecycle)
    delays = []
    for _ in range(MAX_ATTEMPTS - 1):
        await stepped(sessions, lifecycle, lambda one: one.claim(created.id))
        retried = await stepped(
            sessions,
            lifecycle,
            lambda one: one.finish(created.id, Failed(code="solver_raised", message="it raised")),
        )
        delays.append(retried.scheduled_for - clock.at)

    assert delays == [RETRY_BACKOFF, RETRY_BACKOFF * 2]


async def test_the_last_failure_is_terminal_and_keeps_the_inputs_it_read(
    sessions: async_sessionmaker[AsyncSession], lifecycle: Lifecycle, owner: UserRecord
) -> None:
    created = await enqueued(sessions, lifecycle)
    for _ in range(MAX_ATTEMPTS):
        await stepped(sessions, lifecycle, lambda one: one.claim(created.id))
        last = await stepped(
            sessions,
            lifecycle,
            lambda one: one.finish(
                created.id,
                Failed(code="solver_raised", message="it raised", snapshot=A_SNAPSHOT),
            ),
        )

    assert last.status == FAILED
    assert last.attempt == MAX_ATTEMPTS
    async with sessions() as session:
        held = await OperationRepository(session, owner.tenant_id).read_failed_input_snapshot(
            created.id
        )
    assert held == A_SNAPSHOT, "the snapshot is what reproduces a production failure locally"


async def test_a_retried_failure_keeps_no_snapshot(
    sessions: async_sessionmaker[AsyncSession], lifecycle: Lifecycle, owner: UserRecord
) -> None:
    """The table forbids one on any status but ``failed``, and a retried row is ``pending``."""
    created = await enqueued(sessions, lifecycle)
    await stepped(sessions, lifecycle, lambda one: one.claim(created.id))

    await stepped(
        sessions,
        lifecycle,
        lambda one: one.finish(
            created.id, Failed(code="solver_raised", message="it raised", snapshot=A_SNAPSHOT)
        ),
    )

    async with sessions() as session:
        held = await OperationRepository(session, owner.tenant_id).read_failed_input_snapshot(
            created.id
        )
    assert held is None


# --------------------------------------------------------------------------------
# Supersession is not a failure
# --------------------------------------------------------------------------------


def test_a_superseded_operation_is_reported_differently_from_a_failed_one() -> None:
    """The status word and the sentence both differ, which is the criterion in full.

    Presenting supersession as a failure would make normal use look broken: it is what happens when
    the user edits quickly, and a follow-up is already running.
    """
    assert SUPERSEDED != FAILED
    assert statement(SUPERSEDED) != statement(FAILED)


def test_the_superseded_sentence_says_nothing_went_wrong() -> None:
    assert "Nothing went wrong" in statement(SUPERSEDED)
    assert "could not complete" not in statement(SUPERSEDED)


def test_the_failed_sentence_names_what_still_works() -> None:
    assert "still projected" in statement(FAILED)


def test_every_status_has_its_own_sentence() -> None:
    from syncr_api.solving.config import OPERATION_STATUSES

    assert set(STATEMENT_BY_STATUS) == set(OPERATION_STATUSES)
    assert len(set(STATEMENT_BY_STATUS.values())) == len(OPERATION_STATUSES)


# --------------------------------------------------------------------------------
# The reaper and the retention sweep
# --------------------------------------------------------------------------------


async def test_an_abandoned_claim_comes_back_with_its_attempt_raised(
    sessions: async_sessionmaker[AsyncSession],
    lifecycle: Lifecycle,
    clock: Ticking,
    owner: UserRecord,
) -> None:
    created = await enqueued(sessions, lifecycle)
    await stepped(sessions, lifecycle, lambda one: one.claim(created.id))
    clock.advance(LEASE + timedelta(seconds=1))

    async with sessions() as session, session.begin():
        swept = await maintenance_for(session, owner.tenant_id, clock).sweep()

    assert swept.reaped == 1
    reaped = await held(sessions, owner, created.id)
    assert (reaped.status, reaped.attempt) == (PENDING, FIRST_ATTEMPT + 1)
    assert reaped.error_code == LEASE_EXPIRED


async def test_a_claim_inside_its_lease_is_left_alone(
    sessions: async_sessionmaker[AsyncSession],
    lifecycle: Lifecycle,
    clock: Ticking,
    owner: UserRecord,
) -> None:
    created = await enqueued(sessions, lifecycle)
    await stepped(sessions, lifecycle, lambda one: one.claim(created.id))
    clock.advance(LEASE - timedelta(seconds=1))

    async with sessions() as session, session.begin():
        swept = await maintenance_for(session, owner.tenant_id, clock).sweep()

    assert swept.reaped == 0
    still_claimed = await held(sessions, owner, created.id)
    assert still_claimed.status == RUNNING


async def test_an_abandoned_claim_on_its_last_attempt_stops_retrying(
    sessions: async_sessionmaker[AsyncSession],
    lifecycle: Lifecycle,
    clock: Ticking,
    owner: UserRecord,
) -> None:
    """The attempt bound applies to a dying worker, so a poison operation is not an endless loop.

    This is what the reaper being a failure buys: with a ``running`` to ``pending`` step of its own
    it would have needed a second reading of the bound, or none.
    """
    created = await enqueued(sessions, lifecycle)
    for _ in range(MAX_ATTEMPTS):
        await stepped(sessions, lifecycle, lambda one: one.claim(created.id))
        clock.advance(LEASE + timedelta(seconds=1))
        async with sessions() as session, session.begin():
            await maintenance_for(session, owner.tenant_id, clock).sweep()

    spent = await held(sessions, owner, created.id)
    assert (spent.status, spent.attempt) == (FAILED, MAX_ATTEMPTS)


async def test_the_sweep_prunes_a_succeeded_operation_past_thirty_days(
    sessions: async_sessionmaker[AsyncSession],
    lifecycle: Lifecycle,
    clock: Ticking,
    owner: UserRecord,
) -> None:
    created = await enqueued(sessions, lifecycle)
    await stepped(sessions, lifecycle, lambda one: one.claim(created.id))
    await stepped(sessions, lifecycle, lambda one: one.finish(created.id, Succeeded()))
    clock.advance(SUCCEEDED_RETENTION + timedelta(seconds=1))

    async with sessions() as session, session.begin():
        swept = await maintenance_for(session, owner.tenant_id, clock).sweep()

    assert swept.pruned == 1


async def test_the_sweep_keeps_a_failure_for_ninety_days(
    sessions: async_sessionmaker[AsyncSession],
    lifecycle: Lifecycle,
    clock: Ticking,
    owner: UserRecord,
) -> None:
    """A failure is diagnostic, so it outlives a success by two months rather than by nothing."""
    created = await enqueued(sessions, lifecycle)
    for _ in range(MAX_ATTEMPTS):
        await stepped(sessions, lifecycle, lambda one: one.claim(created.id))
        await stepped(
            sessions,
            lifecycle,
            lambda one: one.finish(created.id, Failed(code="solver_raised", message="raised")),
        )
    clock.advance(SUCCEEDED_RETENTION + timedelta(days=1))

    async with sessions() as session, session.begin():
        kept = await maintenance_for(session, owner.tenant_id, clock).sweep()
    clock.advance(FAILED_RETENTION - SUCCEEDED_RETENTION)
    async with sessions() as session, session.begin():
        taken = await maintenance_for(session, owner.tenant_id, clock).sweep()

    assert (kept.pruned, taken.pruned) == (0, 1)


async def test_the_sweep_prunes_nothing_that_is_not_terminal(
    sessions: async_sessionmaker[AsyncSession],
    lifecycle: Lifecycle,
    clock: Ticking,
    owner: UserRecord,
) -> None:
    """A pending operation has no ``finished_at`` at all, and a running one has none either."""
    pending = await enqueued(sessions, lifecycle)
    clock.advance(FAILED_RETENTION * 2)

    async with sessions() as session, session.begin():
        swept = await maintenance_for(session, owner.tenant_id, clock).sweep()

    assert swept.pruned == 0
    async with sessions() as session:
        assert await OperationRepository(session, owner.tenant_id).find(pending.id) is not None


async def test_the_sweep_takes_only_the_statuses_the_windows_name(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, clock: Ticking
) -> None:
    """The control on the windows: nothing else in the table is pruned by this duty.

    A retried failure is ``pending`` with a ``finished_at`` of null, and a sweep keyed on the
    instant alone would have taken it out from under its own retry.
    """
    async with sessions() as session, session.begin():
        sweeps = OperationSweeps(session, owner.tenant_id)
        assert await sweeps.delete_finished_before(clock.at, statuses=(PENDING, RUNNING)) == 0


# --------------------------------------------------------------------------------
# Two callers racing on one row
# --------------------------------------------------------------------------------


async def test_only_one_of_two_concurrent_claimers_gets_the_operation(
    sessions: async_sessionmaker[AsyncSession], lifecycle: Lifecycle, owner: UserRecord
) -> None:
    """The ticket's central atomicity claim, driven rather than reasoned about.

    Legality is the ``WHERE`` clause of the step's own statement, so under READ COMMITTED Postgres
    re-evaluates the qualification after taking the row lock: the loser matches zero rows. Asserted
    over TWO SESSIONS, because a sequential pair of steps cannot tell that apart from a check
    performed before the write, which is the shape this design exists to avoid.
    """
    created = await enqueued(sessions, lifecycle)

    async with sessions() as first, sessions() as second:
        async with first.begin():
            winner = await lifecycle(first).claim(created.id)
        with pytest.raises(OperationMovedOn) as refused:
            async with second.begin():
                await lifecycle(second).claim(created.id)

    assert winner.status == RUNNING
    assert refused.value.held == RUNNING, "the loser is told what the row actually holds"
    assert refused.value.attempted == RUNNING
    assert refused.value.operation_id == created.id


async def test_only_one_of_two_concurrent_finishers_closes_the_operation(
    sessions: async_sessionmaker[AsyncSession], lifecycle: Lifecycle, owner: UserRecord
) -> None:
    """The same property on the terminal step, which is the one the reaper races on."""
    created = await enqueued(sessions, lifecycle)
    await stepped(sessions, lifecycle, lambda one: one.claim(created.id))

    async with sessions() as first, sessions() as second:
        async with first.begin():
            await lifecycle(first).finish(created.id, Succeeded())
        with pytest.raises(OperationMovedOn) as refused:
            async with second.begin():
                await lifecycle(second).finish(created.id, Succeeded())

    assert refused.value.held == SUCCEEDED
    assert (await held(sessions, owner, created.id)).status == SUCCEEDED


def test_the_two_refusals_are_different_types() -> None:
    """Ticket 40's claim scan branches on this: a lost race is a skip, not a failure.

    Both remain an ``IllegalTransition``, so a caller that does not care catches one type.
    """
    assert issubclass(OperationMovedOn, IllegalTransition)
    assert issubclass(OperationNotFound, IllegalTransition)
    assert not issubclass(OperationMovedOn, OperationNotFound)


class MovedOnSweeps:
    """A scan whose answer is already stale, which is what a lost race looks like from inside.

    The race is a row changing between the reaper's scan and its write, and nothing outside a method
    that owns both can interleave them. The scan is a database read, so substituting it is the
    external boundary this suite is allowed to substitute; the prune goes to the real one, because
    the assertion is that the prune still happens.
    """

    def __init__(self, real: OperationSweeps, stale: OperationRecord) -> None:
        self._real = real
        self._stale = stale

    async def running_since_before(self, cutoff: datetime) -> list[OperationRecord]:
        return [self._stale]

    async def delete_finished_before(
        self, cutoff: datetime, *, statuses: tuple[OperationStatus, ...]
    ) -> int:
        return await self._real.delete_finished_before(cutoff, statuses=statuses)


async def test_a_reaper_that_loses_the_race_does_not_roll_back_the_prune(
    sessions: async_sessionmaker[AsyncSession],
    lifecycle: Lifecycle,
    clock: Ticking,
    owner: UserRecord,
) -> None:
    """The failure mode the runbook itself makes reachable: two concurrent sweeps.

    `stuck-operation.md` tells an operator to run the sweep inside the live worker during an
    incident, which is a second reaper by construction. Without a boundary per operation the loser's
    refusal raises out of the whole transaction, taking every tenant's prune with it, and the
    operator sees a traceback caused by following the instruction.
    """
    prunable = await enqueued(sessions, lifecycle)
    await stepped(sessions, lifecycle, lambda one: one.claim(prunable.id))
    await stepped(sessions, lifecycle, lambda one: one.finish(prunable.id, Succeeded()))
    clock.advance(SUCCEEDED_RETENTION + timedelta(seconds=1))

    # Already succeeded, so the reaper's write cannot apply to it: the state the other sweep left.
    moved_on = await held(sessions, owner, prunable.id)

    async with sessions() as session, session.begin():
        swept = await OperationMaintenance(
            MovedOnSweeps(OperationSweeps(session, owner.tenant_id), moved_on),  # type: ignore[arg-type]
            OperationLifecycle(OperationRepository(session, owner.tenant_id), clock),
            clock,
        ).sweep()

    assert swept.races_lost == 1, "the lost race is counted rather than raised"
    assert swept.reaped == 0
    assert swept.pruned == 1, "the prune still happened, which is what the boundary buys"


async def test_the_reaper_race_test_would_fail_without_the_stale_answer(
    sessions: async_sessionmaker[AsyncSession],
    lifecycle: Lifecycle,
    clock: Ticking,
    owner: UserRecord,
) -> None:
    """The control: with the REAL scan the same row is not returned at all, so no race is driven.

    Without this, a substituted scan that answered with nothing would make the test above pass while
    asserting nothing about containment.
    """
    prunable = await enqueued(sessions, lifecycle)
    await stepped(sessions, lifecycle, lambda one: one.claim(prunable.id))
    await stepped(sessions, lifecycle, lambda one: one.finish(prunable.id, Succeeded()))
    clock.advance(LEASE + timedelta(seconds=1))

    async with sessions() as session:
        expired = await OperationSweeps(session, owner.tenant_id).running_since_before(
            clock.at - LEASE
        )

    assert expired == [], "a succeeded row is not running, so the real scan cannot return it"
