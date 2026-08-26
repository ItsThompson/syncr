"""The baseline read, proven over a revision history whose two newest rows disagree.

``test_churn_baseline.py`` drives the seam against a fake repository, which cannot produce
the one case the baseline exists to refuse: a week whose newest ``applied`` revision is
newer than its newest ``approved`` one. Only the real table can hold that history, so here
the week is stored as a user leaves it -- approved on Monday, re-applied by the worker since
-- and one assembly of it answers which document the baseline carries.

If the assembly read ``latest()`` where it reads ``latest_approved()``, the baseline would be
the applied plan, the evaluated plan would equal its own baseline, and churn would read zero.
That failure is what every assertion here is shaped to catch: the named revision, the carried
document, and the priced churn each separate the approved row from the applied one.
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
from syncr_api.learned.config import P0_WEIGHTS
from syncr_api.learned.repository import WeightSetRepository
from syncr_api.learned.weight_reading import as_weight_set
from syncr_api.plans.assembler import AssemblyCaller
from syncr_api.plans.config import APPLIED, APPROVED
from syncr_api.plans.injection import build_week_assembler
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_documents import stored_document
from syncr_api.tasks.models import TaskRow
from syncr_api.tasks.repository import TaskRepository
from syncr_api.user_settings.repository import SettingsRepository
from syncr_domain.habits import BindingSource
from syncr_domain.identity import BindingRef
from syncr_domain.intervals import Interval
from syncr_domain.plan import Block, PlanDocument
from syncr_domain.reasons import Bound, ReasonRecord
from syncr_domain.tasks import Priority
from syncr_domain.weeks import IsoWeek
from syncr_solver.inputs import ChurnBaseline
from syncr_solver.objective import evaluate
from syncr_solver.weights import OBJECTIVE_TERMS, WeightSet
from tests.live_tenants import delete_tenant, seed_owner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_domain.identifiers import TenantId
    from syncr_solver.inputs import SolveInputs

pytestmark = pytest.mark.integration

LONDON = "Europe/London"
WEEK = IsoWeek(2026, 7)
# Wednesday morning, matching the rest of the integration tier.
NOW = datetime(2026, 2, 11, 9, 0, tzinfo=UTC)

# The approval happened a day before the re-apply, and the re-apply is newer than ``now``
# minus minutes only in CREATED order, which is the order ``latest`` reads by. Both revisions
# predate the instant the assembly is stamped with, so nothing about the pins or outcomes
# matters and none are stored.
APPROVED_CREATED = datetime(2026, 2, 10, 9, 0, tzinfo=UTC)
APPROVED_AT = APPROVED_CREATED + timedelta(minutes=5)
APPLIED_CREATED = datetime(2026, 2, 11, 8, 0, tzinfo=UTC)

TASK_ID = uuid4()
AREA_ID = uuid4()

BLOCK_MINUTES = 60
THE_APPROVED_PLACEMENT = datetime(2026, 2, 12, 10, 0, tzinfo=UTC)
THE_APPLIED_PLACEMENT = datetime(2026, 2, 12, 14, 0, tzinfo=UTC)

# What the churn term costs for the single move between the two documents under the shipped
# weights, derived by hand rather than by re-running the term's own arithmetic: one move
# against a tolerance of three is a third of the way to the knee, and the knee's shape is one
# over one plus the inverse squared, so 1/(1+9).
ONE_MOVE_UNDER_THE_SHIPPED_TOLERANCE = 0.1


def an_hour(start: datetime) -> Interval:
    return Interval(start, start + timedelta(minutes=BLOCK_MINUTES))


def a_block(start: datetime) -> Block:
    return Block(
        iso_week=WEEK,
        interval=an_hour(start),
        binding=BindingRef.for_task(TASK_ID),
        title="Past papers",
        reason=ReasonRecord((Bound(source=BindingSource.QUEUE, selected="picked"),)),
        area_id=AREA_ID,
    )


def a_plan(block_start: datetime) -> PlanDocument:
    week_minutes = 7 * 14 * 60
    blocks = (a_block(block_start),)
    return PlanDocument(
        iso_week=WEEK,
        zone_by_date=dict.fromkeys(WEEK.dates(), LONDON),
        discretionary_minutes=week_minutes,
        unallocated_minutes=week_minutes - sum(b.interval.total_minutes() for b in blocks),
        oversubscription_minutes=0,
        blocks=blocks,
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


async def seed_the_disagreement(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    """Approve a plan, then let the worker apply a newer one that moved the block.

    The bindings the documents hold must name the row just created, so the task id is forced
    rather than threaded, the way ``test_netting_against_a_stored_revision.py`` seeds.
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
        await WeightSetRepository(session, tenant_id).seed_hand_tuned(at=NOW)
        # The block in both documents carries an Area, so the row exists and the id is forced,
        # the way the documents' task binding is below.
        area = await AreaRepository(session, tenant_id).create(
            parent_id=None,
            name="Career",
            pigment_index=1,
            budget_percent=Decimal(50),
            floor_hours=Decimal(3),
            created_at=NOW,
        )
        await session.execute(update(AreaRow).where(AreaRow.id == area.id).values(id=AREA_ID))
        created = await TaskRepository(session, tenant_id).create(
            area_id=AREA_ID,
            project_id=None,
            title="Past papers",
            estimate_minutes=120,
            deadline=datetime(2026, 2, 13, 12, 0, tzinfo=UTC),
            priority=Priority.NORMAL,
            min_chunk_minutes=30,
            splittable=True,
            created_at=NOW,
        )
        await session.execute(update(TaskRow).where(TaskRow.id == created.id).values(id=TASK_ID))
        revisions = PlanRepository(session, tenant_id)
        approved = await revisions.append(
            document=stored_document(a_plan(THE_APPROVED_PLACEMENT)),
            objective_breakdown=dict.fromkeys(OBJECTIVE_TERMS, 0.0),
            status=APPROVED,
            reason="user_approved",
            weight_set_version=1,
            input_version=1,
            created_at=APPROVED_CREATED,
            approved_at=APPROVED_AT,
        )
        await revisions.append(
            document=stored_document(a_plan(THE_APPLIED_PLACEMENT)),
            objective_breakdown=dict.fromkeys(OBJECTIVE_TERMS, 0.0),
            status=APPLIED,
            reason="auto_applied_fill",
            weight_set_version=1,
            input_version=2,
            created_at=APPLIED_CREATED,
            supersedes_id=approved.id,
        )


async def assemble(sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId) -> SolveInputs:
    async with sessions() as session:
        assembler = build_week_assembler(session, tenant_id, caller=AssemblyCaller.WORKER)
        return await assembler.assemble(WEEK, NOW)


async def shipped_weights(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> WeightSet:
    async with sessions() as session:
        active = await WeightSetRepository(session, tenant_id).active()
    assert active is not None
    return as_weight_set(active)


async def test_the_baseline_is_the_approved_revision_while_the_week_holds_the_applied_one(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    await seed_the_disagreement(sessions, owner.tenant_id)

    inputs = await assemble(sessions, owner.tenant_id)

    # The disagreement is real: the week's live plan IS the applied document, so an assembly
    # that answered "the newest revision" twice would measure churn against itself.
    assert inputs.live_plan == a_plan(THE_APPLIED_PLACEMENT)

    assert inputs.churn_baseline.reason == ChurnBaseline.APPROVED_REVISION
    assert inputs.churn_baseline.is_measured is True
    # The APPROVED revision and its instant, not the applied one that superseded it.
    assert inputs.churn_baseline.approved_at == APPROVED_AT
    # The plan the approved revision stored, not the plan the week now holds: the two differ
    # by the moved block, so handing the applied document over fails this line.
    assert inputs.churn_baseline.document == a_plan(THE_APPROVED_PLACEMENT)
    assert inputs.churn_baseline.document != inputs.live_plan


async def test_churn_is_priced_non_zero_against_that_approved_plan(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    """Churn measured against the applied document would be zero: it would compare with itself."""
    await seed_the_disagreement(sessions, owner.tenant_id)

    inputs = await assemble(sessions, owner.tenant_id)
    weights = await shipped_weights(sessions, owner.tenant_id)

    assert inputs.live_plan is not None
    cost = evaluate(inputs.live_plan, inputs=inputs, weights=weights).churn

    assert cost > 0
    assert cost == pytest.approx(P0_WEIGHTS["churn"] * ONE_MOVE_UNDER_THE_SHIPPED_TOLERANCE)
