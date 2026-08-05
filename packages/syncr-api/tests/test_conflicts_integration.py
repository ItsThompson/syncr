"""The conflict record against a real Postgres: raised once, retained, and answered for.

A fake would not catch any of this. Every rule asserted here is enforced by a statement or by the
schema rather than by the code that calls it:

- a second raise of an overlap the user is already looking at inserts nothing, because the
  partial unique index covers exactly the rows that carry an unanswered question;
- an overlap the user accepted is never raised again, and one they asked to be moved is, which is
  the same index read the other way;
- two answers arriving together produce one resolution, because the update matches only an
  unresolved row;
- a resolved conflict is still readable, because there is no delete path at all;
- and every statement carries the tenant predicate.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syncr_api.core.db import create_db_engine, create_sessionmaker
from syncr_api.plans.config import (
    CONFLICTS_TABLE,
    KEPT_BOTH_RESOLUTION,
    MOVED_RESOLUTION,
    RETYPED_RESOLUTION,
)
from syncr_api.plans.conflicts import PlanConflictRepository
from syncr_api.plans.overlaps import DetectedConflict
from syncr_domain.identity import BindingRef
from syncr_domain.intervals import Interval
from syncr_domain.weeks import IsoWeek
from tests.control_models import recording
from tests.live_tenants import delete_tenant, seed_owner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.plans.records import ConflictRecord
    from syncr_domain.identifiers import AnchorId, TenantId
    from tests.control_models import StatementRecorder

pytestmark = pytest.mark.integration

WEEK = IsoWeek(2026, 7)
OTHER_WEEK = IsoWeek(2026, 8)
NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)
LATER = NOW + timedelta(minutes=30)

LEETCODE = BindingRef.for_task(uuid4())
GYM = BindingRef.for_habit(uuid4(), index=0)


def between(start_hour: float, end_hour: float) -> Interval:
    monday = datetime(2026, 2, 9, tzinfo=UTC)
    return Interval(monday + timedelta(hours=start_hour), monday + timedelta(hours=end_hour))


def detected(
    anchor_id: AnchorId,
    *,
    binding: BindingRef = LEETCODE,
    iso_week: IsoWeek = WEEK,
    overlap: Interval | None = None,
) -> DetectedConflict:
    return DetectedConflict(
        anchor_id=anchor_id,
        iso_week=iso_week,
        binding=binding,
        overlap=overlap if overlap is not None else between(9, 10),
    )


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
    """A second tenant, so a scoped read has another tenant's rows to not return."""
    account = await seed_owner(sessions)
    yield account
    await delete_tenant(sessions, account.tenant_id)


@pytest.fixture
def recorder(engine: AsyncEngine) -> Iterator[StatementRecorder]:
    yield from recording(engine)


async def raise_all(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    *detections: DetectedConflict,
    at: datetime = NOW,
) -> tuple[ConflictRecord, ...]:
    async with sessions() as session, session.begin():
        return await PlanConflictRepository(session, tenant_id).raise_all(detections, at=at)


async def resolve(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    conflict: ConflictRecord,
    resolution: str,
    *,
    at: datetime = LATER,
) -> ConflictRecord | None:
    async with sessions() as session, session.begin():
        return await PlanConflictRepository(session, tenant_id).resolve(
            conflict.id,
            resolution=resolution,  # type: ignore[arg-type]
            at=at,
        )


async def test_a_raised_conflict_reads_back_naming_the_block_and_the_commitment(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    anchor_id = uuid4()

    (raised,) = await raise_all(sessions, owner.tenant_id, detected(anchor_id))

    assert raised.anchor_id == anchor_id
    assert raised.binding == LEETCODE
    assert raised.block_id == detected(anchor_id).block_id
    assert raised.iso_week == WEEK
    assert raised.overlap == between(9, 10)
    assert (raised.detected_at, raised.resolved_at, raised.resolution) == (NOW, None, None)
    assert not raised.is_resolved


async def test_raising_nothing_writes_nothing(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    assert await raise_all(sessions, owner.tenant_id) == ()

    async with sessions() as session:
        assert await PlanConflictRepository(session, owner.tenant_id).list_all() == ()


async def test_the_same_overlap_raised_twice_is_asked_about_once(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # Detection runs on every sync that moved a commitment and on every solve's commit path.
    anchor_id = uuid4()
    await raise_all(sessions, owner.tenant_id, detected(anchor_id))

    again = await raise_all(sessions, owner.tenant_id, detected(anchor_id, overlap=between(9, 11)))

    assert again == ()
    async with sessions() as session:
        held = await PlanConflictRepository(session, owner.tenant_id).list_all()
    assert [conflict.overlap for conflict in held] == [between(9, 10)]


async def test_one_raise_answers_with_what_was_news_and_not_with_what_was_already_open(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # The notification is the only one this product sends, so the caller has to be handed the
    # set that is news rather than every overlap that still exists.
    standup, interview = uuid4(), uuid4()
    await raise_all(sessions, owner.tenant_id, detected(standup))

    raised = await raise_all(
        sessions, owner.tenant_id, detected(standup), detected(interview, binding=GYM)
    )

    assert [conflict.anchor_id for conflict in raised] == [interview]


async def test_an_accepted_overlap_is_never_raised_again(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    anchor_id = uuid4()
    (raised,) = await raise_all(sessions, owner.tenant_id, detected(anchor_id))
    await resolve(sessions, owner.tenant_id, raised, KEPT_BOTH_RESOLUTION)

    assert await raise_all(sessions, owner.tenant_id, detected(anchor_id)) == ()


@pytest.mark.parametrize("asked_for_a_change", [MOVED_RESOLUTION, RETYPED_RESOLUTION])
async def test_a_collision_that_returns_after_a_change_was_asked_for_is_raised_again(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, asked_for_a_change: str
) -> None:
    # Both answers asked for something to change. The same collision afterwards is the change
    # not having settled it, which the user has to see.
    anchor_id = uuid4()
    (raised,) = await raise_all(sessions, owner.tenant_id, detected(anchor_id))
    await resolve(sessions, owner.tenant_id, raised, asked_for_a_change)

    (again,) = await raise_all(sessions, owner.tenant_id, detected(anchor_id), at=LATER)

    assert again.id != raised.id
    assert again.detected_at == LATER


async def test_one_commitment_over_two_blocks_raises_two_conflicts(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    anchor_id = uuid4()

    raised = await raise_all(
        sessions,
        owner.tenant_id,
        detected(anchor_id, binding=LEETCODE),
        detected(anchor_id, binding=GYM, overlap=between(11, 12)),
    )

    assert {conflict.binding for conflict in raised} == {LEETCODE, GYM}


async def test_one_block_hit_in_two_weeks_raises_two_conflicts(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # The retained pair is what a repeated collision is computed over, and a block id is a
    # digest of the week, so the two rows differ by more than the week column.
    anchor_id = uuid4()

    raised = await raise_all(
        sessions,
        owner.tenant_id,
        detected(anchor_id, iso_week=WEEK),
        detected(anchor_id, iso_week=OTHER_WEEK),
    )

    assert {conflict.iso_week for conflict in raised} == {WEEK, OTHER_WEEK}
    assert len({conflict.block_id for conflict in raised}) == 2
    assert {conflict.binding for conflict in raised} == {LEETCODE}


async def test_a_resolution_states_both_when_and_how(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    (raised,) = await raise_all(sessions, owner.tenant_id, detected(uuid4()))

    resolved = await resolve(sessions, owner.tenant_id, raised, MOVED_RESOLUTION)

    assert resolved is not None
    assert (resolved.resolution, resolved.resolved_at) == (MOVED_RESOLUTION, LATER)
    assert resolved.is_resolved


async def test_a_second_answer_to_one_conflict_changes_nothing(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # The statement decides legality, so two answers arriving together produce one resolution
    # rather than the second overwriting the first.
    (raised,) = await raise_all(sessions, owner.tenant_id, detected(uuid4()))
    await resolve(sessions, owner.tenant_id, raised, KEPT_BOTH_RESOLUTION)

    assert await resolve(sessions, owner.tenant_id, raised, MOVED_RESOLUTION) is None

    async with sessions() as session:
        held = await PlanConflictRepository(session, owner.tenant_id).find(raised.id)
    assert held is not None
    assert held.resolution == KEPT_BOTH_RESOLUTION


async def test_a_resolved_conflict_is_retained_and_still_listed(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    (raised,) = await raise_all(sessions, owner.tenant_id, detected(uuid4()))
    await resolve(sessions, owner.tenant_id, raised, KEPT_BOTH_RESOLUTION)

    async with sessions() as session:
        conflicts = PlanConflictRepository(session, owner.tenant_id)

        assert await conflicts.list_all(resolved=False) == ()
        assert [held.id for held in await conflicts.list_all(resolved=True)] == [raised.id]
        assert [held.id for held in await conflicts.list_all()] == [raised.id]


async def test_the_open_list_is_ordered_by_when_the_overlap_happens(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    await raise_all(
        sessions,
        owner.tenant_id,
        detected(uuid4(), binding=GYM, overlap=between(17, 18)),
        detected(uuid4(), binding=LEETCODE, overlap=between(9, 10)),
    )

    async with sessions() as session:
        held = await PlanConflictRepository(session, owner.tenant_id).list_all(resolved=False)

    assert [conflict.overlap for conflict in held] == [between(9, 10), between(17, 18)]


async def test_one_weeks_conflicts_are_read_by_the_week_they_were_raised_in(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    anchor_id = uuid4()
    await raise_all(
        sessions,
        owner.tenant_id,
        detected(anchor_id, iso_week=WEEK),
        detected(anchor_id, iso_week=OTHER_WEEK),
    )

    async with sessions() as session:
        held = await PlanConflictRepository(session, owner.tenant_id).for_week(OTHER_WEEK)

    assert [conflict.iso_week for conflict in held] == [OTHER_WEEK]


async def test_another_tenants_conflict_is_neither_read_nor_resolved(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, other_owner: UserRecord
) -> None:
    (theirs,) = await raise_all(sessions, other_owner.tenant_id, detected(uuid4()))

    async with sessions() as session:
        mine = PlanConflictRepository(session, owner.tenant_id)

        assert await mine.find(theirs.id) is None
        assert await mine.list_all() == ()
    assert await resolve(sessions, owner.tenant_id, theirs, MOVED_RESOLUTION) is None


async def test_every_read_and_update_carries_the_tenant_predicate(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, recorder: StatementRecorder
) -> None:
    # Compiling a statement proves what was built; this proves what reached Postgres. The INSERT
    # is deliberately outside the claim: it carries the tenant as a column VALUE rather than as a
    # predicate, so a scope check over one would be reading for something that is not there.
    (raised,) = await raise_all(sessions, owner.tenant_id, detected(uuid4()))
    await resolve(sessions, owner.tenant_id, raised, MOVED_RESOLUTION)
    async with sessions() as session:
        conflicts = PlanConflictRepository(session, owner.tenant_id)
        await conflicts.find(raised.id)
        await conflicts.list_all(resolved=False)
        await conflicts.for_week(WEEK)

    scoped = [
        statement
        for statement in recorder.against(CONFLICTS_TABLE)
        if statement.startswith(("SELECT", "UPDATE"))
    ]
    unscoped = [
        statement
        for statement in recorder.without_a_tenant_predicate(CONFLICTS_TABLE)
        if statement.startswith(("SELECT", "UPDATE"))
    ]

    assert scoped, "no read or update of conflicts reached the database"
    assert unscoped == []
