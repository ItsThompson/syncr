"""Conflict detection at ingest, against a real Postgres and the real shadow generator.

C1's own claim: a conflict is detected against the live plan when the commitment arrives, not
discovered later by a solve. That is what lets the notice name the block affected, and it is why
this suite runs the whole chain rather than the pure detector: the geometry a commitment casts is
generated here by the generator a solve reads, from a type the tenant really declared.

Five groups.

**A commitment landing on a planned block is raised**, naming the block and the commitment.

**The third overlap class end to end**: a transit leg the commitment casts landing on a PINNED
block, attributed to the commitment rather than to the leg, through a real anchor type.

**What is not raised**: a week with no live plan, a week outside the projection horizon, a
commitment that lands in empty space, and a commitment over a block that has already started.

**Raising is idempotent**, so the fifteen-minute poll does not ask the same question every tick.

**A tenant sees only its own**, because every read the detection performs is scoped.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syncr_api.anchors.repository import AnchorRepository
from syncr_api.anchors.type_repository import AnchorTypeRepository
from syncr_api.areas.repository import AreaRepository
from syncr_api.calendars.config import ANCHOR_SOURCE, ICS
from syncr_api.calendars.repository import CalendarSourceRepository
from syncr_api.conflicts.ingest import IngestConflicts
from syncr_api.core.db import create_db_engine, create_sessionmaker
from syncr_api.plans.conflicts import PlanConflictRepository
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_documents import stored_document
from syncr_domain.identity import BindingRef
from syncr_domain.intervals import Interval
from syncr_domain.weeks import IsoWeek
from tests.anchor_specifications import INTERVIEW, STANDUP, with_areas
from tests.live_tenants import delete_tenant, seed_owner
from tests.plan_documents import WEEK, a_block_holding, a_document, between

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.anchors.records import AnchorTypeSpecification
    from syncr_api.plans.records import ConflictRecord
    from syncr_domain.identifiers import AnchorId, TenantId
    from syncr_domain.plan import Block

pytestmark = pytest.mark.integration

# The Sunday before the week under test, so every block in it is still in the future and the
# default fourteen-day horizon covers the week.
NOW = datetime(2026, 2, 8, 12, 0, tzinfo=UTC)
FAR_WEEK = IsoWeek(2026, 20)

GYM = BindingRef.for_habit(uuid4(), index=0)
LEETCODE = BindingRef.for_task(uuid4())

# The Interview type's own geometry: a 16:00 commitment casts its outbound leg at 15:00-15:30.
COMMITMENT = between(16, 16.75)
OUTBOUND_LEG = between(15, 15.5)


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


def pinned(one: Block) -> Block:
    return replace(one, pinned=True, superseded_placement=between(20, 21), objective_delta=1.5)


async def store_live_plan(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    *blocks: Block,
    week: IsoWeek = WEEK,
) -> None:
    async with sessions() as session, session.begin():
        await PlanRepository(session, tenant_id).append(
            document=stored_document(a_document(week=week, blocks=blocks)),
            objective_breakdown={"budget_deviation": 1.0},
            status="applied",
            reason="auto_applied_fill",
            weight_set_version=1,
            input_version=1,
            created_at=NOW,
        )


async def add_commitment(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    *,
    interval: Interval = COMMITMENT,
    specification: AnchorTypeSpecification | None = None,
) -> AnchorId:
    """One commitment on one ICS source, carrying the type ``specification`` declares.

    The type's Areas are real ones, because a buffer with an Area is a block and a buffer without
    one is a forbidden window: the third overlap class needs the block.
    """
    async with sessions() as session, session.begin():
        source = await CalendarSourceRepository(session, tenant_id).create(
            provider=ICS,
            role=ANCHOR_SOURCE,
            display_name="University timetable",
            external_id=f"https://example.ac.uk/{uuid4().hex}.ics",
            included=True,
            horizon_days=None,
            created_at=NOW,
        )
        anchor_type = None
        if specification is not None:
            area = await AreaRepository(session, tenant_id).create(
                parent_id=None,
                name=f"Transit {uuid4().hex[:6]}",
                pigment_index=0,
                budget_percent=None,
                floor_hours=None,
                created_at=NOW,
            )
            anchor_type = await AnchorTypeRepository(session, tenant_id).create(
                rule_order=0,
                # The forbidden set follows the declaration's own scope: a type that forbids
                # named Areas has to name some, and one that forbids nothing may name none.
                specification=with_areas(
                    specification,
                    transit=area.id,
                    prep=area.id,
                    forbidden=() if not specification.forbidden_area_ids else (area.id,),
                ),
                created_at=NOW,
            )
        created = await AnchorRepository(session, tenant_id).create(
            source_id=source.id,
            external_uid=uuid4().hex,
            series_uid=None,
            title="Kontron Interview",
            interval=interval,
            location=None,
            anchor_type_id=None if anchor_type is None else anchor_type.id,
            type_overridden=False,
        )
    return created.id


async def detect(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    *,
    now: datetime = NOW,
) -> tuple[ConflictRecord, ...]:
    async with sessions() as session, session.begin():
        return await IngestConflicts(session, tenant_id).detect(now=now)


async def held(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> tuple[ConflictRecord, ...]:
    async with sessions() as session:
        return await PlanConflictRepository(session, tenant_id).list_all()


async def test_a_commitment_over_a_planned_block_is_raised_naming_both(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    await store_live_plan(sessions, owner.tenant_id, a_block_holding(GYM, between(16, 17)))
    anchor_id = await add_commitment(sessions, owner.tenant_id)

    (raised,) = await detect(sessions, owner.tenant_id)

    assert raised.anchor_id == anchor_id
    assert raised.binding == GYM
    assert raised.iso_week == WEEK
    assert raised.overlap == COMMITMENT
    assert not raised.is_resolved


async def test_a_transit_leg_over_a_pinned_block_is_raised_against_the_commitment(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # The third overlap class, through the real generator: the user pinned something at 15:00, an
    # interview arrives at 16:00, and the outbound leg the type casts lands on the pin. H11 makes
    # both immovable and the solver created neither, so nothing else in the model catches it.
    await store_live_plan(sessions, owner.tenant_id, pinned(a_block_holding(GYM, between(15, 16))))
    anchor_id = await add_commitment(sessions, owner.tenant_id, specification=INTERVIEW)

    (raised,) = await detect(sessions, owner.tenant_id)

    assert raised.anchor_id == anchor_id
    assert raised.binding == GYM
    assert raised.overlap == OUTBOUND_LEG


async def test_a_transit_leg_over_an_unpinned_block_raises_nothing(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # The geometry is immediate and the adoption still obeys the authority rule: displacing an
    # unpinned block is a proposal the solve path produces, not a question the user must answer.
    await store_live_plan(sessions, owner.tenant_id, a_block_holding(GYM, between(15, 16)))
    await add_commitment(sessions, owner.tenant_id, specification=INTERVIEW)

    raised = await detect(sessions, owner.tenant_id)

    assert [conflict.overlap for conflict in raised] == []


async def test_a_commitment_landing_in_empty_space_raises_nothing(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    await store_live_plan(sessions, owner.tenant_id, a_block_holding(GYM, between(9, 10)))
    await add_commitment(sessions, owner.tenant_id, specification=STANDUP)

    assert await detect(sessions, owner.tenant_id) == ()


async def test_a_week_with_no_live_plan_raises_nothing(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    await add_commitment(sessions, owner.tenant_id)

    assert await detect(sessions, owner.tenant_id) == ()


async def test_a_commitment_over_a_block_that_has_started_raises_nothing(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # A resolution moves the block or removes the pin holding it, and neither is possible once the
    # week has reached it, so raising the only notification this product sends would ask a question
    # no answer could act on.
    await store_live_plan(sessions, owner.tenant_id, a_block_holding(GYM, between(16, 17)))
    await add_commitment(sessions, owner.tenant_id)

    assert await detect(sessions, owner.tenant_id, now=between(16, 17).start) == ()


async def test_a_week_outside_the_projection_horizon_is_not_read(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # Thirteen weeks out: the maintainer has not planned it, and a conflict there could not be
    # projected. The plan and the commitment both exist, so the bound is what makes this empty.
    far_block = a_block_holding(LEETCODE, between(16, 17, week=FAR_WEEK), week=FAR_WEEK)
    await store_live_plan(sessions, owner.tenant_id, far_block, week=FAR_WEEK)
    await add_commitment(sessions, owner.tenant_id, interval=between(16, 16.75, week=FAR_WEEK))

    assert await detect(sessions, owner.tenant_id) == ()


async def test_the_same_overlap_is_asked_about_once_however_often_a_feed_polls(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    await store_live_plan(sessions, owner.tenant_id, a_block_holding(GYM, between(16, 17)))
    await add_commitment(sessions, owner.tenant_id)
    first = await detect(sessions, owner.tenant_id)

    again = await detect(sessions, owner.tenant_id, now=NOW + timedelta(minutes=15))

    assert len(first) == 1
    assert again == ()
    assert len(await held(sessions, owner.tenant_id)) == 1


async def test_a_moved_commitment_raises_the_new_collision_and_keeps_the_old_record(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # The ordinary case a poll produces: the timetable moved a lecture onto something else.
    await store_live_plan(
        sessions,
        owner.tenant_id,
        a_block_holding(GYM, between(16, 17)),
        a_block_holding(LEETCODE, between(11, 12)),
    )
    anchor_id = await add_commitment(sessions, owner.tenant_id)
    await detect(sessions, owner.tenant_id)

    async with sessions() as session, session.begin():
        await AnchorRepository(session, owner.tenant_id).update_fact(
            anchor_id,
            series_uid=None,
            title="Kontron Interview",
            interval=between(11, 11.75),
            location=None,
            anchor_type_id=None,
            type_overridden=False,
        )
    raised = await detect(sessions, owner.tenant_id)

    assert [conflict.binding for conflict in raised] == [LEETCODE]
    assert {conflict.binding for conflict in await held(sessions, owner.tenant_id)} == {
        GYM,
        LEETCODE,
    }


async def test_another_tenants_plan_is_not_read_and_raises_nothing(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, other_owner: UserRecord
) -> None:
    await store_live_plan(sessions, other_owner.tenant_id, a_block_holding(GYM, between(16, 17)))
    await add_commitment(sessions, other_owner.tenant_id)

    assert await detect(sessions, owner.tenant_id) == ()
    assert await held(sessions, owner.tenant_id) == ()


def test_the_geometry_this_suite_rests_on_is_the_types_own() -> None:
    """The leg's span is read from the declaration rather than asserted as a literal twice."""
    lead = timedelta(minutes=INTERVIEW.transit_lead_minutes or 0)
    duration = timedelta(minutes=INTERVIEW.transit_duration_minutes)

    assert Interval(COMMITMENT.start - lead, COMMITMENT.start - lead + duration) == OUTBOUND_LEG
