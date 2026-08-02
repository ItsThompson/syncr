"""The input-version counter and the guard, including the two races only Postgres can show.

This row is the single serialization point for anything that invalidates a running solve. Four
of its properties cannot be shown without a real server and two real connections.

**A bump is atomic.** Two mutations landing together must produce two increments, not one: a
read-modify-write would let both read 41 and both write 42, and the solve running against 41
would then commit against inputs that had changed twice.

**A missing row is created at version 1 by the first reference.** The horizon maintainer solves
weeks nobody has touched, so no row is the normal state on first contact.

**A missing row is a MISMATCH.** ``SELECT ... FOR UPDATE`` on an absent row takes no lock and
has nothing to compare, so failing open would let two concurrent first solves both commit. The
test below runs exactly that race.

**The guard holds its lock to the end of the transaction.** Reading the version, comparing it,
and appending the revision must not interleave with another mutation's bump, and the control
runs a bump against a held guard to show it waits.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from syncr_api.core.db import create_db_engine, create_sessionmaker
from syncr_api.plans.config import FIRST_INPUT_VERSION
from syncr_api.plans.models import WeekInputVersion
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_domain.weeks import IsoWeek
from tests.live_tenants import delete_tenant, seed_owner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_domain.identifiers import TenantId

pytestmark = pytest.mark.integration

WEEK = IsoWeek(2026, 7)
OTHER_WEEK = IsoWeek(2026, 8)
NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)
LATER = NOW + timedelta(minutes=1)

# Long enough that a real lock wait resolves within it, short enough that a deadlock fails the
# test instead of hanging the suite.
LOCK_TIMEOUT_SECONDS = 5
# How long a contended statement is given to prove it is NOT waiting. A lock wait that resolves
# inside this would make the serialization assertion pass for the wrong reason.
WAIT_PROOF_SECONDS = 0.3


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
async def other_owner(sessions: async_sessionmaker[AsyncSession]) -> AsyncIterator[UserRecord]:
    account = await seed_owner(sessions)
    yield account
    await delete_tenant(sessions, account.tenant_id)


async def bump(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, week: IsoWeek = WEEK
) -> int:
    async with sessions() as session, session.begin():
        return await WeekInputVersionRepository(session, tenant_id).bump(week, at=NOW)


async def current(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, week: IsoWeek = WEEK
) -> int | None:
    async with sessions() as session:
        return await WeekInputVersionRepository(session, tenant_id).current(week)


# --------------------------------------------------------------------------------
# The counter
# --------------------------------------------------------------------------------


async def test_a_week_nobody_has_touched_has_no_version(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    assert await current(sessions, owner.tenant_id) is None


async def test_the_first_bump_creates_the_row_at_one_and_later_bumps_increment(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    first = await bump(sessions, owner.tenant_id)
    second = await bump(sessions, owner.tenant_id)

    assert (first, second) == (FIRST_INPUT_VERSION, FIRST_INPUT_VERSION + 1)
    assert await current(sessions, owner.tenant_id) == FIRST_INPUT_VERSION + 1


async def test_each_week_and_each_tenant_counts_separately(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, other_owner: UserRecord
) -> None:
    await bump(sessions, owner.tenant_id)
    await bump(sessions, owner.tenant_id)
    await bump(sessions, owner.tenant_id, OTHER_WEEK)
    await bump(sessions, other_owner.tenant_id)

    assert await current(sessions, owner.tenant_id) == 2
    assert await current(sessions, owner.tenant_id, OTHER_WEEK) == 1
    assert await current(sessions, other_owner.tenant_id) == 1
    async with sessions() as session:
        assert await WeekInputVersionRepository(session, owner.tenant_id).current(OTHER_WEEK) == 1


async def test_two_bumps_landing_together_produce_two_increments(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # The read-modify-write failure, run for real: both would read the same value and write the
    # same successor, and the solve guarded on the old one would commit.
    await bump(sessions, owner.tenant_id)

    async def contend() -> int:
        async with sessions() as session, session.begin():
            return await WeekInputVersionRepository(session, owner.tenant_id).bump(WEEK, at=LATER)

    landed = await asyncio.wait_for(
        asyncio.gather(contend(), contend()), timeout=LOCK_TIMEOUT_SECONDS
    )

    assert sorted(landed) == [2, 3]
    assert await current(sessions, owner.tenant_id) == 3


# --------------------------------------------------------------------------------
# The conditional-write guard
# --------------------------------------------------------------------------------


async def test_the_guard_matches_the_version_the_solve_read(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    read = await bump(sessions, owner.tenant_id)

    async with sessions() as session, session.begin():
        versions = WeekInputVersionRepository(session, owner.tenant_id)
        assert await versions.holds_version(WEEK, read, at=NOW) is True


async def test_the_guard_reports_a_mismatch_after_a_mutation_landed(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # The whole staleness mechanism: the solve read 1, a pin bumped it to 2, so the result is
    # discarded and one follow-up is enqueued.
    read = await bump(sessions, owner.tenant_id)
    await bump(sessions, owner.tenant_id)

    async with sessions() as session, session.begin():
        versions = WeekInputVersionRepository(session, owner.tenant_id)
        assert await versions.holds_version(WEEK, read, at=NOW) is False


async def test_a_missing_row_is_a_mismatch_and_is_created_at_one(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # V6 and V7 together. The maintainer solves weeks nobody has touched, so the guard has to
    # create the row it will compare against next time, and it must not report a match against
    # a row that did not exist.
    async with sessions() as session, session.begin():
        versions = WeekInputVersionRepository(session, owner.tenant_id)
        held = await versions.holds_version(WEEK, FIRST_INPUT_VERSION, at=NOW)

    assert held is False
    assert await current(sessions, owner.tenant_id) == FIRST_INPUT_VERSION


async def test_two_concurrent_first_solves_cannot_both_commit(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # The race the fail-closed rule exists for, driven rather than hoped for: both solves
    # assembled a plan for a week with no version row, so both reach the guard believing the
    # week is at version 1. Adopting both would apply two independently computed plans to one
    # week.
    #
    # The interleaving is explicit because the outcome depends on it. The first guard's insert
    # is not committed while it runs, so the second guard sees no row either, and its own insert
    # waits on the first: whichever way the scheduler orders them, neither may be told the week
    # still holds what it read.
    first_guarded = asyncio.Event()
    release_first = asyncio.Event()

    async def first_solve() -> bool:
        async with sessions() as session, session.begin():
            versions = WeekInputVersionRepository(session, owner.tenant_id)
            held = await versions.holds_version(WEEK, FIRST_INPUT_VERSION, at=NOW)
            first_guarded.set()
            await release_first.wait()
            return held

    async def second_solve() -> bool:
        await first_guarded.wait()
        async with sessions() as session, session.begin():
            versions = WeekInputVersionRepository(session, owner.tenant_id)
            return await versions.holds_version(WEEK, FIRST_INPUT_VERSION, at=LATER)

    first = asyncio.create_task(first_solve())
    second = asyncio.create_task(second_solve())
    await first_guarded.wait()

    _, pending = await asyncio.wait({second}, timeout=WAIT_PROOF_SECONDS)
    assert pending == {second}, (
        "the second guard finished while the first still held the row it created, so the two "
        "are not serialized against each other"
    )

    release_first.set()
    outcomes = await asyncio.wait_for(asyncio.gather(first, second), timeout=LOCK_TIMEOUT_SECONDS)

    assert list(outcomes) == [False, False], (
        "a first solve was told the week still held the version it read, so two solves for one "
        "week would both have committed"
    )
    # Each of them enqueues exactly one follow-up, and the follow-up finds the row they created.
    assert await current(sessions, owner.tenant_id) == FIRST_INPUT_VERSION + 1


async def test_the_guard_holds_its_row_against_a_concurrent_bump(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # `FOR UPDATE` is what makes the guard atomic. Without it, a mutation could bump between the
    # comparison and the append, and the appended revision would name a version nobody read.
    read = await bump(sessions, owner.tenant_id)
    guard_holds = asyncio.Event()
    release_guard = asyncio.Event()

    async def hold_the_guard() -> bool:
        async with sessions() as session, session.begin():
            versions = WeekInputVersionRepository(session, owner.tenant_id)
            held = await versions.holds_version(WEEK, read, at=NOW)
            guard_holds.set()
            await release_guard.wait()
            return held

    async def bump_while_held() -> int:
        await guard_holds.wait()
        async with sessions() as session, session.begin():
            return await WeekInputVersionRepository(session, owner.tenant_id).bump(WEEK, at=LATER)

    guarded = asyncio.create_task(hold_the_guard())
    mutation = asyncio.create_task(bump_while_held())
    await guard_holds.wait()

    _, pending = await asyncio.wait({mutation}, timeout=WAIT_PROOF_SECONDS)
    assert pending == {mutation}, (
        "the bump completed while the guard held the row, so the read, the comparison and the "
        "write are not atomic and a stale plan can be adopted"
    )

    release_guard.set()
    held, bumped = await asyncio.wait_for(
        asyncio.gather(guarded, mutation), timeout=LOCK_TIMEOUT_SECONDS
    )

    assert held is True
    assert bumped == read + 1


async def test_a_version_below_one_is_rejected_by_the_database(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # The counter is monotonic from 1, so a zero or a negative would be a version no solve could
    # have read.
    async with sessions() as session:
        session.add(
            WeekInputVersion(
                tenant_id=owner.tenant_id, iso_week=str(WEEK), version=0, updated_at=NOW
            )
        )
        with pytest.raises(IntegrityError, match="version_starts_at_one"):
            await session.flush()
        await session.rollback()


async def test_another_tenants_version_row_is_invisible(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, other_owner: UserRecord
) -> None:
    await bump(sessions, other_owner.tenant_id)

    assert await current(sessions, owner.tenant_id) is None
    async with sessions() as session, session.begin():
        # Fails closed for this tenant, and creates ITS row rather than reading the other's.
        versions = WeekInputVersionRepository(session, owner.tenant_id)
        assert await versions.holds_version(WEEK, FIRST_INPUT_VERSION, at=NOW) is False
    assert await current(sessions, other_owner.tenant_id) == FIRST_INPUT_VERSION
    assert await current(sessions, owner.tenant_id) == FIRST_INPUT_VERSION


async def test_the_row_carries_the_instant_of_its_last_bump(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    await bump(sessions, owner.tenant_id)
    async with sessions() as session, session.begin():
        await WeekInputVersionRepository(session, owner.tenant_id).bump(WEEK, at=LATER)

    async with sessions() as session:
        stored = await session.scalar(
            select(WeekInputVersion).where(
                WeekInputVersion.tenant_id == owner.tenant_id,
                WeekInputVersion.iso_week == str(WEEK),
            )
        )

    assert stored is not None
    assert stored.updated_at == LATER
