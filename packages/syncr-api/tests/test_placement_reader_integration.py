"""Which table a live plan comes from, against a real Postgres.

The seam answers with the newest REVISION, and a pending proposal is a row in another table. So
the rule "a proposal nobody has approved has committed no capacity" is carried by the schema
rather than by a branch: ``StoredPlacements.read`` asks ``PlanRepository.latest`` and asks the
slot nothing. Two tables and one reader is a design no assertion inside the reader can see, which
is why it is asserted here rather than inferred from the absence of a second query.

What a widened reader would cost, and why the second case seeds both tables: a reader answering
with "the newest document this week holds" nets a plan the user may reject into every quantity the
netting rules take over placements. Every figure would merely be lower than the truth, so the two
documents here hold different bindings at different hours and the Area figures separate them. A
union of the two tables reads 120 placed minutes where the revision alone reads 60.

Both cases assemble through ``build_week_assembler``, so the reader under test is the one
production wires, and the document is rebuilt through the projection a solve reads it through.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import update

from syncr_api.areas.models import AreaRow
from syncr_api.areas.repository import AreaRepository
from syncr_api.core.db import create_db_engine, create_sessionmaker
from syncr_api.learned.repository import WeightSetRepository
from syncr_api.plans.assembler import AssemblyCaller
from syncr_api.plans.injection import build_week_assembler
from syncr_api.plans.proposals import PendingProposalRepository
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_documents import stored_document
from syncr_api.plans.stored_proposals import stored_proposal_diff
from syncr_api.plans.stored_verdicts import stored_verdict
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.config import SOLVE
from syncr_api.solving.lifecycle import OperationLifecycle
from syncr_api.solving.repository import OperationRepository
from syncr_api.user_settings.repository import SettingsRepository
from syncr_domain.feasibility import Provenance, Verdict
from syncr_domain.habits import BindingSource
from syncr_domain.identity import BindingKind, BindingRef
from syncr_domain.intervals import Interval
from syncr_domain.plan import Block, PlanDocument
from syncr_domain.proposals import BlockChange, ProposalDiff
from syncr_domain.reasons import Bound, ReasonRecord
from syncr_domain.weeks import IsoWeek
from syncr_solver.weights import OBJECTIVE_TERMS
from tests.live_tenants import delete_tenant, seed_owner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_domain.identifiers import TenantId
    from syncr_solver.inputs import AreaBudget, SolveInputs

pytestmark = pytest.mark.integration

LONDON = "Europe/London"
WEEK = IsoWeek(2026, 7)
# Wednesday morning, so both documents below hold a block in the week's FUTURE and neither is
# immovable for having started. What separates the Area's two floor quantities here is therefore
# the table a placement came from and nothing else.
NOW = datetime(2026, 2, 11, 9, 0, tzinfo=UTC)
MONDAY_MIDNIGHT = datetime(2026, 2, 9, 0, 0, tzinfo=UTC)

AREA_ID = uuid4()
AREA_NAME = "Fitness"
DECLARED_FLOOR_MINUTES = 180

# Two different tasks, so a reader that unioned the two tables would count two placements. One
# binding in both documents would collapse to one placement whatever the reader read, and the
# figures could not tell a union from the revision alone.
IN_THE_REVISION = BindingRef(kind=BindingKind.TASK, entity_id=uuid4(), occurrence_key="00")
IN_THE_SLOT = BindingRef(kind=BindingKind.TASK, entity_id=uuid4(), occurrence_key="00")

THURSDAY = 3
REVISION_HOUR = 14
SLOT_HOUR = 17
BLOCK_MINUTES = 60


def a_block(binding: BindingRef, start_hour: int, *, title: str) -> Block:
    """One future task block of this week, charged to the declared Area."""
    start = MONDAY_MIDNIGHT + timedelta(days=THURSDAY, hours=start_hour)
    return Block(
        iso_week=WEEK,
        interval=Interval(start, start + timedelta(minutes=BLOCK_MINUTES)),
        binding=binding,
        title=title,
        reason=ReasonRecord((Bound(source=BindingSource.QUEUE, selected="picked"),)),
        area_id=AREA_ID,
    )


def a_document(*blocks: Block) -> PlanDocument:
    """A week holding these blocks, with its own figures consistent with them."""
    week_minutes = 7 * 14 * 60
    return PlanDocument(
        iso_week=WEEK,
        zone_by_date=dict.fromkeys(WEEK.dates(), LONDON),
        discretionary_minutes=week_minutes,
        unallocated_minutes=week_minutes - sum(b.interval.total_minutes() for b in blocks),
        oversubscription_minutes=0,
        blocks=blocks,
    )


THE_REVISIONS_BLOCK = a_block(IN_THE_REVISION, REVISION_HOUR, title="Gym · approved")
THE_SLOTS_BLOCK = a_block(IN_THE_SLOT, SLOT_HOUR, title="Gym · proposed")


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


async def declare_the_minimum(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    """A home zone, the Area both documents charge their blocks to, a weight set, and a version.

    The Area's floor is what makes the two floor quantities readable at all: with no floor
    declared both are zero and neither netting rule has anything to net out of.
    """
    async with sessions() as session, session.begin():
        settings = SettingsRepository(session, tenant_id)
        locked = await settings.lock(created_at=NOW)
        await settings.write(
            visible_hours=locked.visible_hours,
            day_start=locked.day_start,
            day_end=locked.day_end,
            review_cadence=locked.review_cadence,
            home_zone=LONDON,
        )
        created = await AreaRepository(session, tenant_id).create(
            parent_id=None,
            name=AREA_NAME,
            pigment_index=1,
            budget_percent=Decimal(50),
            floor_hours=Decimal(DECLARED_FLOOR_MINUTES) / Decimal(60),
            created_at=NOW,
        )
        # The identifier is overridden rather than threaded through, so the two documents above
        # can be module constants and a reader sees which Area their blocks are charged to.
        await session.execute(update(AreaRow).where(AreaRow.id == created.id).values(id=AREA_ID))
        await WeightSetRepository(session, tenant_id).seed_hand_tuned(at=NOW)
        await WeekInputVersionRepository(session, tenant_id).bump(WEEK, at=NOW)


async def append_a_revision(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, document: PlanDocument
) -> None:
    """The week's plan of record, appended through the repository a solve appends it through."""
    async with sessions() as session, session.begin():
        await PlanRepository(session, tenant_id).append(
            document=stored_document(document),
            objective_breakdown=dict.fromkeys(OBJECTIVE_TERMS, 0.0),
            status="applied",
            reason="auto_applied_fill",
            weight_set_version=1,
            input_version=1,
            created_at=NOW,
        )


async def fill_the_slot(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, document: PlanDocument
) -> None:
    """One pending proposal, written through the repository a solve fills the slot through.

    Its diff names the block the document holds as an addition, because a proposal that asks for
    nothing is a different state with a different consequence, and a slot whose diff disagrees
    with its own document is a fixture nobody could reach.
    """
    async with sessions() as session, session.begin():
        operation = await OperationLifecycle(
            OperationRepository(session, tenant_id), lambda: NOW
        ).enqueue(kind=SOLVE, iso_week=WEEK)
        await PendingProposalRepository(session, tenant_id).replace(
            document=stored_document(document),
            proposal_diff=stored_proposal_diff(
                ProposalDiff(added=tuple(BlockChange.added(block) for block in document.blocks))
            ),
            objective_breakdown=dict.fromkeys(OBJECTIVE_TERMS, 0.0),
            verdict=stored_verdict(
                Verdict(
                    feasible=True,
                    provenance=Provenance.SOLVER,
                    computed_at=NOW,
                    input_version=1,
                    discretionary_minutes=document.discretionary_minutes,
                )
            ),
            weight_set_version=1,
            input_version=1,
            operation_id=operation.id,
            created_at=NOW,
        )


async def assemble(sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId) -> SolveInputs:
    async with sessions() as session, session.begin():
        assembler = build_week_assembler(session, tenant_id, caller=AssemblyCaller.WORKER)
        return await assembler.assemble(WEEK, NOW)


def the_declared_area(inputs: SolveInputs) -> AreaBudget:
    return next(area for area in inputs.areas if area.area_id == AREA_ID)


async def test_a_week_holding_only_a_pending_proposal_assembles_with_no_live_plan(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    """The slot is full, the revision table is empty, and the assembly holds no plan.

    The Area figures are the discriminating half: a reader that saw the slot would report the
    proposal's hour as committed, so the floor reservation would read an hour short of the floor
    the user declared against a plan they have not agreed to.
    """
    await declare_the_minimum(sessions, owner.tenant_id)
    await fill_the_slot(sessions, owner.tenant_id, a_document(THE_SLOTS_BLOCK))

    inputs = await assemble(sessions, owner.tenant_id)

    assert inputs.live_plan is None
    area = the_declared_area(inputs)
    assert area.placed_minutes == 0
    assert area.floor_reservation_minutes == DECLARED_FLOOR_MINUTES
    assert area.floor_minutes == DECLARED_FLOOR_MINUTES


async def test_a_week_holding_both_reads_the_revision_and_not_the_slot(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    """One week, two tables, and the plan of record is what the assembly holds.

    The blocks are asserted by binding and by interval rather than by count, because a union of
    the two tables and the revision alone are both "a live plan": what separates them is whose
    block it is.
    """
    await declare_the_minimum(sessions, owner.tenant_id)
    await append_a_revision(sessions, owner.tenant_id, a_document(THE_REVISIONS_BLOCK))
    await fill_the_slot(sessions, owner.tenant_id, a_document(THE_SLOTS_BLOCK))

    inputs = await assemble(sessions, owner.tenant_id)

    assert inputs.live_plan is not None
    assert [block.binding for block in inputs.live_plan.blocks] == [IN_THE_REVISION]
    assert [block.interval for block in inputs.live_plan.blocks] == [THE_REVISIONS_BLOCK.interval]
    area = the_declared_area(inputs)
    assert area.placed_minutes == BLOCK_MINUTES
    assert area.floor_reservation_minutes == DECLARED_FLOOR_MINUTES - BLOCK_MINUTES
