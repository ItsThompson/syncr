"""The netting rules, proven against a stored revision rather than supplied fixtures.

``test_assembly_netting.py`` states the arithmetic over literals, which is what makes it
decidable. What it cannot show is that the figures survive the trip through storage: a week
whose plan of record, pins, and outcomes sit in real rows and reach the arithmetic through
the production ``StoredPlacements``, composed the way ``build_week_assembler`` wires it.

One week carries everything the rules read.

**A pinned hour is netted once.** The plan of record holds a task block and a pin moves it:
paired by binding, the pin's interval wins, so the week reads one committed hour where an
unpaired reading would read two. The Area figures are where a double count shows up first,
because ``placed_minutes`` feeds the reservation directly.

**A pin whose placement the week has reached is not carried.** The row sits in the pins table,
so only the assembly's own ``constraining`` filter stands between it and the solve: what the
assertions see is that the stored row was read (its block still nets) and its pin did not
arrive. If the filter ever stopped dropping such a pin, the pin tuple here would grow.

**A partial outcome attributes a prefix, not the block's span.** Recorded against the elapsed
block through the outcome log the reader also reads, it splits the two remaining-work readings:
the solver nets the block's own span, the probe nets only the minutes the user said were done.
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
from syncr_api.plans.declarations import PinToHold
from syncr_api.plans.injection import build_week_assembler
from syncr_api.plans.pins import PinRepository
from syncr_api.plans.reality import BlockOutcomeRepository
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_documents import stored_document
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.tasks.models import TaskRow
from syncr_api.tasks.repository import TaskRepository
from syncr_api.user_settings.repository import SettingsRepository
from syncr_domain.habits import BindingSource
from syncr_domain.identity import BindingRef, block_id
from syncr_domain.intervals import Interval
from syncr_domain.outcomes import OutcomeState, RecordedOutcome
from syncr_domain.plan import Block, PlanDocument
from syncr_domain.reasons import Bound, ReasonRecord
from syncr_domain.tasks import Priority
from syncr_domain.weeks import IsoWeek
from syncr_solver.weights import OBJECTIVE_TERMS
from tests.live_tenants import delete_tenant, seed_owner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.plans.records import PlanRevisionRecord
    from syncr_domain.identifiers import TenantId
    from syncr_solver.inputs import SolveInputs

pytestmark = pytest.mark.integration

LONDON = "Europe/London"
WEEK = IsoWeek(2026, 7)
# Wednesday morning. Monday's block has been lived, Thursday's and Friday's have not, so the
# elapsed pin and the live one are separated by exactly the rule under test.
NOW = datetime(2026, 2, 11, 9, 0, tzinfo=UTC)
MONDAY_MIDNIGHT = datetime(2026, 2, 9, 0, 0, tzinfo=UTC)

AREA_ID = uuid4()
AREA_NAME = "Career"
DECLARED_FLOOR_MINUTES = 240

PINNED_TASK = uuid4()
ELAPSED_TASK = uuid4()
FUTURE_TASK = uuid4()

BLOCK_MINUTES = 60
PARTIAL_MINUTES = 30


def monday(hour: int) -> datetime:
    return MONDAY_MIDNIGHT + timedelta(hours=hour)


def thursday(hour: int) -> datetime:
    return MONDAY_MIDNIGHT + timedelta(days=3, hours=hour)


def friday(hour: int) -> datetime:
    return MONDAY_MIDNIGHT + timedelta(days=4, hours=hour)


def an_hour(start: datetime) -> Interval:
    return Interval(start, start + timedelta(minutes=BLOCK_MINUTES))


def a_block(binding: BindingRef, start: datetime, *, title: str) -> Block:
    return Block(
        iso_week=WEEK,
        interval=an_hour(start),
        binding=binding,
        title=title,
        reason=ReasonRecord((Bound(source=BindingSource.QUEUE, selected="picked"),)),
        area_id=AREA_ID,
    )


def a_document(*blocks: Block) -> PlanDocument:
    week_minutes = 7 * 14 * 60
    return PlanDocument(
        iso_week=WEEK,
        zone_by_date=dict.fromkeys(WEEK.dates(), LONDON),
        discretionary_minutes=week_minutes,
        unallocated_minutes=week_minutes - sum(b.interval.total_minutes() for b in blocks),
        oversubscription_minutes=0,
        blocks=blocks,
    )


THE_PINNED_PLACEMENT = thursday(14)
THE_PINNED_HOUR = thursday(17)
THE_ELAPSED_PLACEMENT = monday(10)
THE_ELAPSED_PIN = monday(12)
THE_FUTURE_PLACEMENT = friday(9)

THE_REVISION = a_document(
    a_block(BindingRef.for_task(PINNED_TASK), THE_PINNED_PLACEMENT, title="Pinned · planned"),
    a_block(BindingRef.for_task(ELAPSED_TASK), THE_ELAPSED_PLACEMENT, title="Elapsed · lived"),
    a_block(BindingRef.for_task(FUTURE_TASK), THE_FUTURE_PLACEMENT, title="Future · movable"),
)

PINNED_DEADLINE = datetime(2026, 2, 14, 12, 0, tzinfo=UTC)
ELAPSED_DEADLINE = datetime(2026, 2, 10, 12, 0, tzinfo=UTC)


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


async def seed_the_week(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> PlanRevisionRecord:
    """The week as a user leaves it: a plan of record, two pins, one partial outcome.

    The pin on the future block MOVES it, so pairing by binding is observable in figures. The
    pin on the elapsed block restates a placement Monday already lived, so only ``constraining``
    keeps it out of the assembly. The partial outcome says half the elapsed block was done,
    which is what parts the solver's remaining figure from the probe's.
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
        # Overridden so every block above can charge the one Area these assertions read.
        await session.execute(update(AreaRow).where(AreaRow.id == created.id).values(id=AREA_ID))
        await WeightSetRepository(session, tenant_id).seed_hand_tuned(at=NOW)
        await WeekInputVersionRepository(session, tenant_id).bump(WEEK, at=NOW)
        tasks = TaskRepository(session, tenant_id)
        pinned = await tasks.create(
            area_id=AREA_ID,
            project_id=None,
            title="Pinned",
            estimate_minutes=120,
            deadline=PINNED_DEADLINE,
            priority=Priority.NORMAL,
            min_chunk_minutes=30,
            splittable=True,
            created_at=NOW,
        )
        elapsed = await tasks.create(
            area_id=AREA_ID,
            project_id=None,
            title="Elapsed",
            estimate_minutes=180,
            deadline=ELAPSED_DEADLINE,
            priority=Priority.NORMAL,
            min_chunk_minutes=30,
            splittable=True,
            created_at=NOW,
        )
        future = await tasks.create(
            area_id=AREA_ID,
            project_id=None,
            title="Future",
            estimate_minutes=90,
            deadline=None,
            priority=Priority.NORMAL,
            min_chunk_minutes=30,
            splittable=True,
            created_at=NOW,
        )
        # The bindings the document holds must name the rows just created, so the three task ids
        # are forced rather than threaded: the document stays a readable module constant.
        for constant, row in (
            (PINNED_TASK, pinned),
            (ELAPSED_TASK, elapsed),
            (FUTURE_TASK, future),
        ):
            await session.execute(update(TaskRow).where(TaskRow.id == row.id).values(id=constant))
        revision = await PlanRepository(session, tenant_id).append(
            document=stored_document(THE_REVISION),
            objective_breakdown=dict.fromkeys(OBJECTIVE_TERMS, 0.0),
            status="applied",
            reason="auto_applied_fill",
            weight_set_version=1,
            input_version=1,
            created_at=NOW,
        )
        pins = PinRepository(session, tenant_id)
        await pins.hold(
            PinToHold(
                iso_week=WEEK,
                block_id=block_id(WEEK, BindingRef.for_task(PINNED_TASK)),
                binding=BindingRef.for_task(PINNED_TASK),
                interval=an_hour(THE_PINNED_HOUR),
                superseded_placement=an_hour(THE_PINNED_PLACEMENT),
                objective_delta=0.0,
                weight_set_version=1,
                created_at=NOW,
            )
        )
        await pins.hold(
            PinToHold(
                iso_week=WEEK,
                block_id=block_id(WEEK, BindingRef.for_task(ELAPSED_TASK)),
                binding=BindingRef.for_task(ELAPSED_TASK),
                interval=an_hour(THE_ELAPSED_PIN),
                superseded_placement=an_hour(THE_ELAPSED_PLACEMENT),
                objective_delta=0.0,
                weight_set_version=1,
                created_at=NOW,
            )
        )
        await BlockOutcomeRepository(session, tenant_id).record(
            RecordedOutcome(
                binding=BindingRef.for_task(ELAPSED_TASK),
                state=OutcomeState.PARTIAL,
                actual_minutes=PARTIAL_MINUTES,
            ),
            block_id=block_id(WEEK, BindingRef.for_task(ELAPSED_TASK)),
            revision_id=revision.id,
            occurred_at=THE_ELAPSED_PLACEMENT,
        )
        return revision


async def assemble(sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId) -> SolveInputs:
    async with sessions() as session, session.begin():
        assembler = build_week_assembler(session, tenant_id, caller=AssemblyCaller.WORKER)
        return await assembler.assemble(WEEK, NOW)


async def test_a_stored_week_nets_every_figure_through_the_production_reader(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    """Every netting figure, read off one assembly of a week stored across all three tables.

    Minute arithmetic, with nothing scaled: no multiplier is fitted for the Area, so estimates
    pass through unchanged.
    """
    await seed_the_week(sessions, owner.tenant_id)

    inputs = await assemble(sessions, owner.tenant_id)

    # The live pin arrived; the elapsed one did not. Both rows sit in the pins table, so this
    # pair of assertions is the constraining filter biting over stored state.
    assert [pin.binding.entity_id for pin in inputs.pins] == [PINNED_TASK]
    assert [pin.interval for pin in inputs.pins] == [an_hour(THE_PINNED_HOUR)]

    # A pin and the block it pins are ONE placement: the plan's three hours minus zero, not the
    # four an unpaired reading of the moved block plus its pin would count.
    assert inputs.live_plan is not None
    assert len(inputs.live_plan.blocks) == 3
    assert inputs.committed_occupancy().total_minutes() == 3 * BLOCK_MINUTES

    area = next(a for a in inputs.areas if a.area_id == AREA_ID)
    assert area.placed_minutes == 3 * BLOCK_MINUTES
    assert area.floor_reservation_minutes == DECLARED_FLOOR_MINUTES - 3 * BLOCK_MINUTES
    # The solver's set nets IMMOVABLE placements only: the pinned hour in full and, of the
    # elapsed block, the prefix the partial outcome attributed inside its own span.
    assert area.floor_minutes == DECLARED_FLOOR_MINUTES - BLOCK_MINUTES - PARTIAL_MINUTES

    remaining = {t.binding.entity_id: t.remaining_minutes for t in inputs.eligible_tasks}
    # The pinned hour nets from the pinned task's own span once, at the pin's location.
    assert remaining[PINNED_TASK] == 120 - BLOCK_MINUTES
    # The elapsed block nets whole, whatever the outcome attributed: the solver cannot
    # re-place any of it.
    assert remaining[ELAPSED_TASK] == 180 - BLOCK_MINUTES
    # The movable hour deliberately nets nothing.
    assert remaining[FUTURE_TASK] == 90

    # The probe's demand takes the outcome's reading: only the reported prefix of the elapsed
    # block counts toward it, and the pinned hour counts at the pin's new location.
    demands = {(d.deadline, d.remaining_minutes) for d in inputs.deadline_demands}
    assert demands == {
        (ELAPSED_DEADLINE, 180 - PARTIAL_MINUTES),
        (PINNED_DEADLINE, 120 - BLOCK_MINUTES),
    }
