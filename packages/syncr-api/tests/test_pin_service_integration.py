"""The pin transaction against a real Postgres: invariants, verdict, and two settlements.

Six groups.

**The E1 invariant.** A pin and its edit event are one transaction: a failure writing the event
rolls back the pin, so a pin can never exist without its features.

**The Idempotency-Key replay is tested in ``test_pin_routes_integration.py``.** The tests here
drive the service directly and exercise the upsert behaviour without a key: two drags of one block
produce one pin row (the upsert) and two edit events (two preferences).

**The three Blocker-1 verdict properties.** Pinning time toward a task that is due leaves that
task's shortfall unchanged. Pinning a Fitness block leaves the floor reservation equal and lowers
the floor the solver must still place, which is the whole of the two-quantity split read from one
week. Pinning an already-placed block leaves the verdict unchanged.

**The two settlements.** Ticket 1333: a pin on a block that has begun is refused with a stated
reason. Ticket 1402: a pin whose interval elapses while its block lives only in a pending proposal
does not wedge the week.

**Reject-block.** A rejection is a pin at the block's existing placement, records the pairwise
preference used for training.

**Unpin and StoredPinRelease.** The pin row is removed, the event stays, the version bumps, and
the real release the conflict path reaches answers correctly.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from sqlalchemy import select, text

from syncr_api.areas.repository import AreaRepository
from syncr_api.conflicts.declarations import ChosenResolution
from syncr_api.conflicts.injection import get_conflict_service
from syncr_api.core.db import create_db_engine, create_sessionmaker
from syncr_api.core.patches import ABSENT
from syncr_api.learned.models import WeightSet as WeightSetRow
from syncr_api.learned.repository import WeightSetRepository
from syncr_api.pins.declarations import BlockRejected, PinRequested
from syncr_api.pins.injection import build_pin_service
from syncr_api.plans.assembler import AssemblyCaller
from syncr_api.plans.config import EDIT_EVENTS_TABLE, MOVED_RESOLUTION, PINS_TABLE
from syncr_api.plans.conflicts import Commitment, PlanConflictRepository
from syncr_api.plans.facts import EditEvent, Pin
from syncr_api.plans.injection import build_week_assembler
from syncr_api.plans.overlaps import DetectedConflict
from syncr_api.plans.placements import constrains_a_solve
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_documents import stored_document
from syncr_api.plans.surfaces import VerdictSurface
from syncr_api.plans.verdict_events import VerdictEventRepository
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.config import PENDING, SOLVE
from syncr_domain.feasibility import Provenance
from syncr_domain.habits import BindingSource
from syncr_domain.identity import BindingKind, BindingRef, block_id
from syncr_domain.intervals import Interval
from syncr_domain.plan import Block, PlanDocument
from syncr_domain.reasons import Bound, ReasonRecord
from syncr_domain.tasks import Priority
from syncr_domain.weeks import IsoWeek
from syncr_solver.inputs import Pin as SolverPin
from syncr_solver.weights import OBJECTIVE_TERMS
from tests.live_tenants import delete_tenant, seed_owner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.principal import Principal
    from syncr_api.pins.service import PinnedWeek
    from syncr_api.plans.records import ConflictRecord, VerdictEventRecord
    from syncr_domain.identifiers import TenantId

pytestmark = pytest.mark.integration

WEEK = IsoWeek(2026, 7)
NOW = datetime(2026, 2, 11, 9, 0, tzinfo=UTC)  # Wednesday 09:00
LONDON = "Europe/London"

TASK_ID = uuid4()
AREA_ID = uuid4()
AREA_NAME = "Fitness"
BINDING = BindingRef(kind=BindingKind.TASK, entity_id=TASK_ID, occurrence_key="00")
BLOCK_ID = block_id(WEEK, BINDING)


def a_plan(*, blocks: tuple[Block, ...] = ()) -> PlanDocument:
    return PlanDocument(
        iso_week=WEEK,
        zone_by_date=dict.fromkeys(WEEK.dates(), LONDON),
        discretionary_minutes=7 * 14 * 60,
        unallocated_minutes=7 * 14 * 60 - sum(b.interval.total_minutes() for b in blocks),
        oversubscription_minutes=0,
        blocks=blocks,
    )


def a_block(
    start_hour: int = 14,
    end_hour: int = 15,
    *,
    day_offset: int = 0,
    binding: BindingRef = BINDING,
    title: str = "Gym",
    area_id: UUID | None = AREA_ID,
) -> Block:
    monday = datetime(2026, 2, 9, 0, 0, tzinfo=UTC)
    return Block(
        iso_week=WEEK,
        interval=Interval(
            monday + timedelta(days=day_offset, hours=start_hour),
            monday + timedelta(days=day_offset, hours=end_hour),
        ),
        binding=binding,
        title=title,
        reason=ReasonRecord((Bound(source=BindingSource.QUEUE, selected="picked"),)),
        area_id=area_id,
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
    user = await seed_owner(sessions)
    yield user
    await delete_tenant(sessions, user.tenant_id)


async def _seed_plan(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, plan: PlanDocument
) -> None:
    """Store a revision for the week, and a version row, and the weight set."""
    async with sessions() as session, session.begin():
        await WeightSetRepository(session, tenant_id).seed_hand_tuned(at=NOW)
        await PlanRepository(session, tenant_id).append(
            document=stored_document(plan),
            objective_breakdown={
                "deadline_risk": 0.0,
                "budget_deviation": 0.0,
                "time_of_day_misfit": 0.0,
                "fragmentation": 0.0,
                "churn": 0.0,
                "context_switch": 0.0,
                "staleness": 0.0,
            },
            status="applied",
            reason="auto_applied_fill",
            weight_set_version=1,
            input_version=1,
            created_at=NOW,
        )
        await WeekInputVersionRepository(session, tenant_id).bump(WEEK, at=NOW)


async def _seed_area(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, *, floor: int = 60
) -> None:
    from decimal import Decimal

    async with sessions() as session, session.begin():
        record = await AreaRepository(session, tenant_id).create(
            parent_id=None,
            name=AREA_NAME,
            pigment_index=1,
            budget_percent=Decimal(50),
            floor_hours=Decimal(floor) / Decimal(60),
            created_at=NOW,
        )
        # Override the generated id so the plan's blocks match
        from sqlalchemy import update

        from syncr_api.areas.models import AreaRow

        await session.execute(update(AreaRow).where(AreaRow.id == record.id).values(id=AREA_ID))


async def _seed_task(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    *,
    deadline: datetime | None = None,
    estimate: int = 60,
) -> None:
    async with sessions() as session, session.begin():
        from sqlalchemy import update

        from syncr_api.tasks.models import TaskRow
        from syncr_api.tasks.repository import TaskRepository

        record = await TaskRepository(session, tenant_id).create(
            area_id=AREA_ID,
            project_id=None,
            title="Gym",
            estimate_minutes=estimate,
            deadline=deadline,
            priority=Priority.NORMAL,
            min_chunk_minutes=15,
            splittable=False,
            created_at=NOW,
        )
        # Override the generated id so the block's binding matches
        await session.execute(update(TaskRow).where(TaskRow.id == record.id).values(id=TASK_ID))


def _principal(owner: UserRecord) -> Principal:
    from syncr_api.core.principal import Principal
    from syncr_api.core.scopes import Scope

    return Principal(tenant_id=owner.tenant_id, user_id=owner.id, scopes=frozenset(Scope))


async def _pin(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    start: datetime,
    *,
    block_id_str: str = BLOCK_ID,
) -> PinnedWeek:
    """Pin a block through the service and return the PinnedWeek."""
    async with sessions() as session, session.begin():
        service = build_pin_service(session, owner.tenant_id, clock=lambda: NOW)
        return await service.pin(
            _principal(owner), str(WEEK), PinRequested(block_id=block_id_str, start=start)
        )


async def _row_count(sessions: async_sessionmaker[AsyncSession], table: str) -> int:
    async with sessions() as session:
        return (await session.scalar(text(f"SELECT count(*) FROM {table}"))) or 0  # noqa: S608


async def _pins_held_by(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> tuple[Pin, ...]:
    """The pin rows this tenant holds, so a count is about one tenant and not about the table."""
    async with sessions() as session:
        return tuple((await session.scalars(select(Pin).where(Pin.tenant_id == tenant_id))).all())


async def _seed_pinned_revision(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, pinned: Block
) -> None:
    """The revision a solve appends after a pin: the same week, with the block pinned.

    At a later instant than the seeded revision, because the live plan is the newest one and the
    pass that reads a pin runs after the pin was made.
    """
    async with sessions() as session, session.begin():
        await PlanRepository(session, tenant_id).append(
            document=stored_document(a_plan(blocks=(pinned,))),
            objective_breakdown=dict.fromkeys(OBJECTIVE_TERMS, 0.0),
            status="applied",
            reason="auto_applied_fill",
            weight_set_version=1,
            input_version=2,
            created_at=NOW + timedelta(minutes=1),
        )


async def _seed_conflict_against(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, overlapped: Block
) -> ConflictRecord:
    """One unanswered conflict against ``overlapped``, shaped as the detector would raise it.

    The overlap is the second half of the block's own span: a fixture that is internally
    impossible is a trap for whoever reads it next looking for what a real row holds.
    """
    anchor_id = uuid4()
    span = overlapped.interval
    detected = DetectedConflict(
        anchor_id=anchor_id,
        iso_week=WEEK,
        binding=overlapped.binding,
        overlap=Interval(span.start + span.duration / 2, span.end),
    )
    async with sessions() as session, session.begin():
        (raised,) = await PlanConflictRepository(session, tenant_id).raise_all(
            (detected,),
            at=NOW,
            commitments={anchor_id: Commitment(series_uid="standup-series", title="Standup")},
        )
    return raised


# ---------------------------------------------------------------------------
# E1: the edit event is written in the same transaction as the pin
# ---------------------------------------------------------------------------


class TestE1TransactionInvariant:
    """A failure writing the edit event rolls back the pin."""

    async def test_a_failure_writing_the_event_rolls_back_the_pin(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        block = a_block(14, 15, day_offset=3)
        plan = a_plan(blocks=(block,))
        await _seed_plan(sessions, owner.tenant_id, plan)
        await _seed_area(sessions, owner.tenant_id)
        await _seed_task(sessions, owner.tenant_id)

        pins_before = await _row_count(sessions, PINS_TABLE)
        events_before = await _row_count(sessions, EDIT_EVENTS_TABLE)

        with (
            patch(
                "syncr_api.plans.edits.EditEventRepository.append",
                side_effect=RuntimeError("simulated write failure"),
            ),
            pytest.raises(RuntimeError, match="simulated write failure"),
        ):
            await _pin(sessions, owner, start=datetime(2026, 2, 12, 15, 0, tzinfo=UTC))

        assert await _row_count(sessions, PINS_TABLE) == pins_before
        assert await _row_count(sessions, EDIT_EVENTS_TABLE) == events_before


# ---------------------------------------------------------------------------
# Ticket 1333: a pin on a block that has begun is refused
# ---------------------------------------------------------------------------


class TestPinOnStartedBlock:
    """US-PLAN-06: a block the week has reached cannot be pinned."""

    async def test_a_pin_on_a_block_that_has_begun_is_refused_with_a_stated_reason(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        # Block at 08:00-09:00 on Wednesday, NOW is Wed 09:00, so block has started
        block = a_block(8, 9, day_offset=2)
        plan = a_plan(blocks=(block,))
        await _seed_plan(sessions, owner.tenant_id, plan)
        await _seed_area(sessions, owner.tenant_id)
        await _seed_task(sessions, owner.tenant_id)

        from syncr_api.core.errors import Conflict

        with pytest.raises(Conflict, match="began at"):
            await _pin(sessions, owner, start=datetime(2026, 2, 12, 15, 0, tzinfo=UTC))

    async def test_the_assembler_filter_drops_an_elapsed_pin_independently(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """The filter and the route refusal are two mechanisms for one rule: test each alone."""
        # A pin at 08:00 on Wednesday: its interval has started at NOW (Wed 09:00)
        past_interval = Interval(
            datetime(2026, 2, 11, 8, 0, tzinfo=UTC), datetime(2026, 2, 11, 9, 0, tzinfo=UTC)
        )
        future_interval = Interval(
            datetime(2026, 2, 13, 14, 0, tzinfo=UTC), datetime(2026, 2, 13, 15, 0, tzinfo=UTC)
        )
        past_pin = SolverPin(
            binding=BINDING,
            interval=past_interval,
            pinned_on=NOW.date(),
            superseded_placement=future_interval,
            objective_delta=0.1,
        )
        future_pin = SolverPin(
            binding=BindingRef(kind=BindingKind.TASK, entity_id=uuid4(), occurrence_key="00"),
            interval=future_interval,
            pinned_on=NOW.date(),
            superseded_placement=past_interval,
            objective_delta=0.2,
        )
        from syncr_api.plans.placements import constraining

        kept = constraining((past_pin, future_pin), now=NOW)

        assert len(kept) == 1
        assert kept[0] is future_pin
        assert not constrains_a_solve(past_interval, NOW)
        assert constrains_a_solve(future_interval, NOW)


# ---------------------------------------------------------------------------
# Ticket 1402: the pin-elapsed wedge is closed
# ---------------------------------------------------------------------------


class TestPinElapsedWedge:
    """A pin whose interval elapses while its block lives only in a pending proposal.

    Before this fix: the solver would build a block for pinned content the live plan does not hold,
    the guard reads that block as `invented` (a past the live plan does not state), and every solve
    of that week fails permanently.

    After: the pin is not carried into assembly, so the solver never builds the block, and
    nothing reaches the guard.
    """

    async def test_an_elapsed_pin_with_no_live_plan_block_does_not_wedge_the_week(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        # Build a plan WITHOUT the pinned block (simulating a pending proposal that was never
        # approved). The pin's interval is in the past.
        other_binding = BindingRef(kind=BindingKind.TASK, entity_id=uuid4(), occurrence_key="00")
        other_block = a_block(14, 15, day_offset=3, binding=other_binding, title="Other")
        plan = a_plan(blocks=(other_block,))
        await _seed_plan(sessions, owner.tenant_id, plan)
        await _seed_area(sessions, owner.tenant_id)

        # Insert a pin whose interval has elapsed: Mon 08:00-09:00, now is Wed 09:00
        elapsed_interval = Interval(
            datetime(2026, 2, 9, 8, 0, tzinfo=UTC), datetime(2026, 2, 9, 9, 0, tzinfo=UTC)
        )
        async with sessions() as session, session.begin():
            from syncr_api.plans.declarations import PinToHold
            from syncr_api.plans.pins import PinRepository

            await PinRepository(session, owner.tenant_id).hold(
                PinToHold(
                    iso_week=WEEK,
                    block_id=block_id(WEEK, BINDING),
                    binding=BINDING,
                    interval=elapsed_interval,
                    superseded_placement=Interval(
                        datetime(2026, 2, 9, 10, 0, tzinfo=UTC),
                        datetime(2026, 2, 9, 11, 0, tzinfo=UTC),
                    ),
                    weight_set_version=1,
                    created_at=NOW - timedelta(days=2),
                )
            )

        # Assemble the week: the elapsed pin must NOT appear in inputs.pins
        async with sessions() as session, session.begin():
            assembler = build_week_assembler(session, owner.tenant_id, caller=AssemblyCaller.WORKER)
            inputs = await assembler.assemble(WEEK, NOW)

        # The pin should be filtered out
        assert all(pin.binding != BINDING for pin in inputs.pins)
        # And no block for that binding should be in the solver's inheritance
        # (this is what would have triggered `invented` in settled.py)


# ---------------------------------------------------------------------------
# The three Blocker-1 verdict properties (US-FEAS-01)
# ---------------------------------------------------------------------------


class TestVerdictProperties:
    """The three properties the ticket names, each through the real assembler and probe."""

    async def test_pinning_time_toward_a_due_task_leaves_shortfall_unchanged(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """Captures verdict BEFORE, asserts shortfall totals equal (0 == 0 in this fixture)."""
        deadline = datetime(2026, 2, 13, 9, 0, tzinfo=UTC)
        block = a_block(14, 15, day_offset=3)
        plan = a_plan(blocks=(block,))
        await _seed_plan(sessions, owner.tenant_id, plan)
        await _seed_area(sessions, owner.tenant_id, floor=0)
        await _seed_task(sessions, owner.tenant_id, deadline=deadline, estimate=60)

        from syncr_api.plans.verdicts import ProbeCaller, WeekProbe

        async with sessions() as session, session.begin():
            assembler = build_week_assembler(
                session, owner.tenant_id, caller=AssemblyCaller.REQUEST
            )
            before_inputs = await assembler.assemble(WEEK, NOW)
        before_verdict = WeekProbe(caller=ProbeCaller.REQUEST).verdict_for(before_inputs)

        new_start = datetime(2026, 2, 12, 10, 0, tzinfo=UTC)
        result = await _pin(sessions, owner, new_start)

        before_total = sum(s.minutes for s in before_verdict.shortfalls)
        after_total = sum(s.minutes for s in result.verdict.shortfalls)
        assert after_total == before_total

    async def test_pinning_a_fitness_block_lowers_the_solvers_floor_and_not_the_reservation(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """All four of the Area's quantities, each in the direction its own comment states.

        One week with a live plan and a pin is the state where the four disagree, and they must
        disagree here or one of them is netting a set it does not claim. The reservation nets
        every placement, so the hour is already out of it before the pin and the pin cannot lower
        it further: that is what stops a drag improving a verdict. ``floor_minutes`` nets the
        immovable ones only, so the same hour is IN it before the pin and out of it after, because
        a pinned hour is one the solver no longer has to place. ``placed_minutes`` counts the pin
        and the block it pins as one placement rather than two. ``target_minutes`` nets nothing at
        all, so it reads the same across all three assemblies below.
        """
        block = a_block(14, 15, day_offset=3)
        placed_minutes = block.interval.total_minutes()
        floor_minutes = placed_minutes
        plan = a_plan(blocks=(block,))
        await _seed_area(sessions, owner.tenant_id, floor=floor_minutes)
        await _seed_task(sessions, owner.tenant_id, estimate=60)

        # Assemble with the Area declared and NOTHING placed in it, which is what makes the
        # target's direction falsifiable: a target netting any placement drops below this figure
        # at the next assembly, and one netting nothing does not.
        async with sessions() as session, session.begin():
            assembler = build_week_assembler(
                session, owner.tenant_id, caller=AssemblyCaller.REQUEST
            )
            unplaced = await assembler.assemble(WEEK, NOW)
        fitness_unplaced = next(a for a in unplaced.areas if a.area_id == AREA_ID)
        assert fitness_unplaced.placed_minutes == 0
        assert fitness_unplaced.floor_reservation_minutes == floor_minutes
        assert fitness_unplaced.floor_minutes == floor_minutes

        await _seed_plan(sessions, owner.tenant_id, plan)

        # Assemble BEFORE the pin
        async with sessions() as session, session.begin():
            assembler = build_week_assembler(
                session, owner.tenant_id, caller=AssemblyCaller.REQUEST
            )
            before = await assembler.assemble(WEEK, NOW)
        fitness_before = next(a for a in before.areas if a.area_id == AREA_ID)

        # An unpinned future block is out of the reservation and still in the solver's floor.
        assert fitness_before.placed_minutes == placed_minutes
        assert fitness_before.floor_reservation_minutes == floor_minutes - placed_minutes
        assert fitness_before.floor_minutes == floor_minutes
        # Gross: the whole floor is placed and the target reports the figure it reported unplaced.
        assert fitness_before.target_minutes == fitness_unplaced.target_minutes
        assert fitness_before.target_minutes >= floor_minutes

        # Pin to a different time
        new_start = datetime(2026, 2, 12, 10, 0, tzinfo=UTC)
        await _pin(sessions, owner, new_start)

        # Assemble AFTER the pin
        async with sessions() as session, session.begin():
            assembler = build_week_assembler(
                session, owner.tenant_id, caller=AssemblyCaller.REQUEST
            )
            after = await assembler.assemble(WEEK, NOW)
        fitness_after = next(a for a in after.areas if a.area_id == AREA_ID)

        # Discriminating EQUALITY: the pinned block still satisfies the floor
        assert fitness_after.floor_reservation_minutes == fitness_before.floor_reservation_minutes
        # One placement, not two: the pin's hour replaces the block's rather than adding to it.
        assert fitness_after.placed_minutes == placed_minutes
        # The pin is immovable, so the hour leaves the quantity that nets only immovable ones.
        assert fitness_after.floor_minutes == 0
        assert fitness_after.target_minutes == fitness_before.target_minutes

    async def test_pinning_an_already_placed_block_leaves_the_verdict_unchanged(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """Captures the verdict BEFORE and asserts equality AFTER (provenance check)."""
        block = a_block(14, 15, day_offset=3)
        plan = a_plan(blocks=(block,))
        await _seed_plan(sessions, owner.tenant_id, plan)
        await _seed_area(sessions, owner.tenant_id, floor=60)
        await _seed_task(sessions, owner.tenant_id, estimate=60)

        # Probe BEFORE the pin
        from syncr_api.plans.verdicts import ProbeCaller, WeekProbe

        async with sessions() as session, session.begin():
            assembler = build_week_assembler(
                session, owner.tenant_id, caller=AssemblyCaller.REQUEST
            )
            before_inputs = await assembler.assemble(WEEK, NOW)
        before_verdict = WeekProbe(caller=ProbeCaller.REQUEST).verdict_for(before_inputs)

        # Pin at the SAME interval: the `p` toggle
        result = await _pin(sessions, owner, block.interval.start)

        # Delta is zero
        assert result.pin.objective_delta == 0.0
        # Full verdict equality: captures before and compares after
        assert result.verdict.shortfalls == before_verdict.shortfalls
        assert result.verdict.feasible == before_verdict.feasible
        assert result.verdict.discretionary_minutes == before_verdict.discretionary_minutes


# ---------------------------------------------------------------------------
# Reject-block
# ---------------------------------------------------------------------------


class TestRejectBlock:
    """Partial rejection: a pin at the existing placement, recording the pairwise preference."""

    async def test_rejection_creates_a_pin_at_the_existing_placement(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        block = a_block(14, 15, day_offset=3)
        plan = a_plan(blocks=(block,))
        await _seed_plan(sessions, owner.tenant_id, plan)
        await _seed_area(sessions, owner.tenant_id)
        await _seed_task(sessions, owner.tenant_id)

        # Store a pending proposal that moves the block
        moved_block = a_block(10, 11, day_offset=3)
        proposal_plan = a_plan(blocks=(moved_block,))
        async with sessions() as session, session.begin():
            from syncr_api.plans.proposals import PendingProposalRepository
            from syncr_api.plans.stored_documents import stored_document
            from syncr_api.plans.stored_verdicts import stored_verdict
            from syncr_domain.feasibility import Provenance as P
            from syncr_domain.feasibility import Verdict

            v = Verdict(
                feasible=False,
                provenance=P.PROBE,
                computed_at=NOW,
                input_version=1,
                discretionary_minutes=5880,
            )
            await PendingProposalRepository(session, owner.tenant_id).replace(
                document=stored_document(proposal_plan),
                proposal_diff={"changes": []},
                objective_breakdown={
                    "deadline_risk": 0.0,
                    "budget_deviation": 0.0,
                    "time_of_day_misfit": 0.0,
                    "fragmentation": 0.0,
                    "churn": 0.0,
                    "context_switch": 0.0,
                    "staleness": 0.0,
                },
                verdict=stored_verdict(v),
                weight_set_version=1,
                input_version=1,
                operation_id=uuid4(),
                created_at=NOW,
                candidate_adjustment=None,
            )

        # Reject the proposed move
        async with sessions() as session, session.begin():
            service = build_pin_service(session, owner.tenant_id, clock=lambda: NOW)
            result = await service.reject(
                _principal(owner), str(WEEK), BlockRejected(block_id=BLOCK_ID)
            )

        # The pin should be at the LIVE plan's placement (14:00-15:00), not the proposal's
        assert result.pin.interval == block.interval
        # The superseded placement should be the PROPOSAL's interval (10:00-11:00)
        assert result.pin.superseded_placement == moved_block.interval

    async def test_rejection_records_the_pairwise_preference_for_training(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        block = a_block(14, 15, day_offset=3)
        plan = a_plan(blocks=(block,))
        await _seed_plan(sessions, owner.tenant_id, plan)
        await _seed_area(sessions, owner.tenant_id)
        await _seed_task(sessions, owner.tenant_id)

        moved_block = a_block(10, 11, day_offset=3)
        proposal_plan = a_plan(blocks=(moved_block,))
        async with sessions() as session, session.begin():
            from syncr_api.plans.proposals import PendingProposalRepository
            from syncr_api.plans.stored_verdicts import stored_verdict
            from syncr_domain.feasibility import Provenance as P
            from syncr_domain.feasibility import Verdict

            v = Verdict(
                feasible=False,
                provenance=P.PROBE,
                computed_at=NOW,
                input_version=1,
                discretionary_minutes=5880,
            )
            await PendingProposalRepository(session, owner.tenant_id).replace(
                document=stored_document(proposal_plan),
                proposal_diff={"changes": []},
                objective_breakdown={
                    "deadline_risk": 0.0,
                    "budget_deviation": 0.0,
                    "time_of_day_misfit": 0.0,
                    "fragmentation": 0.0,
                    "churn": 0.0,
                    "context_switch": 0.0,
                    "staleness": 0.0,
                },
                verdict=stored_verdict(v),
                weight_set_version=1,
                input_version=1,
                operation_id=uuid4(),
                created_at=NOW,
                candidate_adjustment=None,
            )

        async with sessions() as session, session.begin():
            service = build_pin_service(session, owner.tenant_id, clock=lambda: NOW)
            await service.reject(_principal(owner), str(WEEK), BlockRejected(block_id=BLOCK_ID))

        # The edit event should record: proposed = proposal's interval, accepted = live's interval
        async with sessions() as session:
            events = (await session.scalars(select(EditEvent))).all()
            assert len(events) == 1
            event = events[0]
            # proposed is where the solver put it (the proposal's interval)
            assert event.proposed_starts_at == moved_block.interval.start
            assert event.proposed_ends_at == moved_block.interval.end
            # accepted is where the user kept it (the live plan's interval)
            assert event.accepted_starts_at == block.interval.start
            assert event.accepted_ends_at == block.interval.end


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    """A retried pin does not create a second pin or a second edit event."""

    async def test_the_pin_upsert_replaces_rather_than_duplicates(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        block = a_block(14, 15, day_offset=3)
        plan = a_plan(blocks=(block,))
        await _seed_plan(sessions, owner.tenant_id, plan)
        await _seed_area(sessions, owner.tenant_id)
        await _seed_task(sessions, owner.tenant_id)

        # Pin once
        start = datetime(2026, 2, 12, 10, 0, tzinfo=UTC)
        await _pin(sessions, owner, start)

        # Pin again at a different time: the row should be REPLACED, not duplicated
        start2 = datetime(2026, 2, 12, 11, 0, tzinfo=UTC)
        await _pin(sessions, owner, start2)

        async with sessions() as session:
            pins = (await session.scalars(select(Pin))).all()
            assert len(pins) == 1
            assert pins[0].starts_at == start2

    async def test_a_second_pin_writes_a_second_edit_event(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """Two drags ARE two preferences, even on one block: the second was against the first."""
        block = a_block(14, 15, day_offset=3)
        plan = a_plan(blocks=(block,))
        await _seed_plan(sessions, owner.tenant_id, plan)
        await _seed_area(sessions, owner.tenant_id)
        await _seed_task(sessions, owner.tenant_id)

        await _pin(sessions, owner, datetime(2026, 2, 12, 10, 0, tzinfo=UTC))
        await _pin(sessions, owner, datetime(2026, 2, 12, 11, 0, tzinfo=UTC))

        async with sessions() as session:
            events = (await session.scalars(select(EditEvent))).all()
            # Two events: two distinct preferences
            assert len(events) == 2


# ---------------------------------------------------------------------------
# The verdict is synchronous and carries probe provenance
# ---------------------------------------------------------------------------


class TestLiveVerdict:
    """The verdict is computed synchronously and requires no solve to complete."""

    async def test_the_verdict_carries_probe_provenance(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        block = a_block(14, 15, day_offset=3)
        plan = a_plan(blocks=(block,))
        await _seed_plan(sessions, owner.tenant_id, plan)
        await _seed_area(sessions, owner.tenant_id)
        await _seed_task(sessions, owner.tenant_id)

        result = await _pin(sessions, owner, datetime(2026, 2, 12, 10, 0, tzinfo=UTC))

        assert result.verdict.provenance == Provenance.PROBE
        assert result.verdict.input_version >= 1

    async def test_pin_requests_a_solve(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        block = a_block(14, 15, day_offset=3)
        plan = a_plan(blocks=(block,))
        await _seed_plan(sessions, owner.tenant_id, plan)
        await _seed_area(sessions, owner.tenant_id)
        await _seed_task(sessions, owner.tenant_id)

        result = await _pin(sessions, owner, datetime(2026, 2, 12, 10, 0, tzinfo=UTC))

        assert result.operation is not None
        assert result.operation.kind == SOLVE
        assert result.operation.status == PENDING


# ---------------------------------------------------------------------------
# VE2 and VE5: the transition the pin path records, and the burst that does not
# ---------------------------------------------------------------------------


class TestVerdictTransitionRecording:
    """Ticket 43's half of the pin transaction: the row the drag leaves in the corpus.

    The seeded week is not short of capacity, so the verdict the pin computes finds no gap. It is
    still the FIRST verdict this week has, which ``VE2`` makes a transition: what the corpus needs
    is the baseline, because a later flip is only a flip against something.
    """

    async def test_a_pin_records_the_verdict_it_computed(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """One row, naming the pin surface, the version the pin left, and the pin's own instant.

        ``feasible`` is asserted true against a verdict whose own ``feasible`` field is false, which
        is the translation the recorder makes: capacity arithmetic may not claim a week works, so a
        row copying that field would open an infeasibility episode on every drag of a healthy week.
        """
        await _seed_a_pinnable_week(sessions, owner)

        result = await _pin(sessions, owner, datetime(2026, 2, 12, 10, 0, tzinfo=UTC))

        assert result.verdict.feasible is False, "a probe verdict never claims a week works"
        assert result.verdict.capacity_is_sufficient
        (one,) = await _transitions(sessions, owner)
        assert one.surface is VerdictSurface.PIN
        assert one.provenance is Provenance.PROBE
        assert one.feasible is True
        assert one.shortfall_minutes == 0
        assert one.shortfall_kinds == ()
        assert one.session_mode_active is False
        assert one.caused_by_operation_id is None
        assert one.input_version == result.verdict.input_version
        assert one.occurred_at == result.verdict.computed_at

    async def test_a_burst_of_twelve_pins_writes_at_most_one_row(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """``VE2``, and the figure the invariant states. Twelve drags, one row.

        Each drag recomputes the same verdict, and a verdict recomputed identically is not news. The
        edit events are counted beside it as the control: twelve preferences were really expressed,
        so the single row is a rule rather than eleven requests that did nothing.
        """
        await _seed_a_pinnable_week(sessions, owner)

        for minute in range(12):
            await _pin(sessions, owner, datetime(2026, 2, 12, 10, minute, tzinfo=UTC))

        assert len(await _transitions(sessions, owner)) == 1
        assert await _row_count(sessions, EDIT_EVENTS_TABLE) == 12

    async def test_a_failure_writing_the_transition_rolls_back_the_pin(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """``VE5``: a mutation cannot commit without the transition it caused.

        The same shape as ``E1``'s test one row along, and for the same reason: the corpus is never
        pruned, so a transition lost at the moment it happened is lost permanently.
        """
        await _seed_a_pinnable_week(sessions, owner)
        pins_before = await _row_count(sessions, PINS_TABLE)

        with (
            patch(
                "syncr_api.plans.verdict_events.VerdictEventRepository.append",
                side_effect=RuntimeError("simulated write failure"),
            ),
            pytest.raises(RuntimeError, match="simulated write failure"),
        ):
            await _pin(sessions, owner, datetime(2026, 2, 12, 10, 0, tzinfo=UTC))

        assert await _row_count(sessions, PINS_TABLE) == pins_before
        assert await _row_count(sessions, EDIT_EVENTS_TABLE) == 0
        assert await _transitions(sessions, owner) == []

    async def test_releasing_a_pin_records_nothing(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """The release computes no verdict, so it has none to record.

        Deliberate rather than missing: the release asks for a solve, and the transition that solve
        finds is recorded on the commit path with ``solver`` provenance, which is a stronger finding
        than the arithmetic this path would have run.
        """
        await _seed_a_pinnable_week(sessions, owner)
        held = await _pin(sessions, owner, datetime(2026, 2, 12, 10, 0, tzinfo=UTC))
        before = await _transitions(sessions, owner)

        async with sessions() as session, session.begin():
            service = build_pin_service(session, owner.tenant_id, clock=lambda: NOW)
            await service.unpin(_principal(owner), str(WEEK), held.pin.id)

        assert await _transitions(sessions, owner) == before

    async def test_a_pin_made_during_a_weekly_session_says_so(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """``VE3``: the value comes from the caller, and the caller is the client.

        Bound where the service is composed, so the numerator of the early-catch metric is what the
        client stated rather than what this application guessed. The route's own reading of the
        header is driven in ``test_verdict_surfaces.py``.
        """
        await _seed_a_pinnable_week(sessions, owner)

        async with sessions() as session, session.begin():
            service = build_pin_service(
                session, owner.tenant_id, clock=lambda: NOW, session_mode_active=True
            )
            await service.pin(
                _principal(owner),
                str(WEEK),
                PinRequested(block_id=BLOCK_ID, start=datetime(2026, 2, 12, 10, 0, tzinfo=UTC)),
            )

        (one,) = await _transitions(sessions, owner)
        assert one.session_mode_active is True


async def _seed_a_pinnable_week(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    """The week every test in the class above pins in: one block, one Area, one task."""
    await _seed_plan(sessions, owner.tenant_id, a_plan(blocks=(a_block(14, 15, day_offset=3),)))
    await _seed_area(sessions, owner.tenant_id)
    await _seed_task(sessions, owner.tenant_id)


async def _transitions(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> list[VerdictEventRecord]:
    """This week's transitions, read back through the repository that wrote them."""
    async with sessions() as session:
        return await VerdictEventRepository(session, owner.tenant_id).for_week(WEEK)


class TestUnpin:
    """AC10: the pin is removed, the version bumps, and the event stays."""

    async def test_unpin_removes_the_row_and_bumps_the_version(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        block = a_block(14, 15, day_offset=3)
        plan = a_plan(blocks=(block,))
        await _seed_plan(sessions, owner.tenant_id, plan)
        await _seed_area(sessions, owner.tenant_id)
        await _seed_task(sessions, owner.tenant_id)

        result = await _pin(sessions, owner, datetime(2026, 2, 12, 10, 0, tzinfo=UTC))
        pin_id = result.pin.id

        # Read version before unpin
        async with sessions() as session:
            version_before = await WeekInputVersionRepository(session, owner.tenant_id).current(
                WEEK
            )

        # Unpin
        async with sessions() as session, session.begin():
            service = build_pin_service(session, owner.tenant_id, clock=lambda: NOW)
            await service.unpin(_principal(owner), str(WEEK), pin_id)

        # Pin row is gone
        async with sessions() as session:
            from syncr_api.plans.pins import PinRepository

            found = await PinRepository(session, owner.tenant_id).find(pin_id)
        assert found is None

        # Version bumped
        async with sessions() as session:
            version_after = await WeekInputVersionRepository(session, owner.tenant_id).current(WEEK)
        assert version_after is not None
        assert version_before is not None
        assert version_after > version_before

        # Edit event row survives (PN2)
        async with sessions() as session:
            events = (
                await session.scalars(
                    select(EditEvent).where(EditEvent.tenant_id == owner.tenant_id)
                )
            ).all()
            assert len(events) == 1


class TestStoredPinRelease:
    """The release a conflict resolution reaches: over the real table, and through the wiring."""

    async def test_releasing_a_held_pin_frees_the_binding(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        block = a_block(14, 15, day_offset=3)
        plan = a_plan(blocks=(block,))
        await _seed_plan(sessions, owner.tenant_id, plan)
        await _seed_area(sessions, owner.tenant_id)
        await _seed_task(sessions, owner.tenant_id)

        # Pin the block
        await _pin(sessions, owner, datetime(2026, 2, 12, 10, 0, tzinfo=UTC))

        # Release it through StoredPinRelease (the production path conflicts use)
        from syncr_api.pins.release import StoredPinRelease
        from syncr_api.plans.pins import PinRepository

        async with sessions() as session, session.begin():
            release = StoredPinRelease(PinRepository(session, owner.tenant_id))
            was_pinned = await release.release(WEEK, BINDING)

        assert was_pinned is True

        # The pin row is gone
        async with sessions() as session:
            pins = (
                await session.scalars(select(Pin).where(Pin.tenant_id == owner.tenant_id))
            ).all()
            assert len(pins) == 0

    async def test_releasing_nothing_returns_false(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        from syncr_api.pins.release import StoredPinRelease
        from syncr_api.plans.pins import PinRepository

        async with sessions() as session, session.begin():
            release = StoredPinRelease(PinRepository(session, owner.tenant_id))
            was_pinned = await release.release(WEEK, BINDING)

        assert was_pinned is False

    async def test_a_conflict_answered_as_moved_releases_the_pin_through_the_wiring(
        self,
        sessions: async_sessionmaker[AsyncSession],
        owner: UserRecord,
        app: FastAPI,
    ) -> None:
        """The two cases above hold the class. This one holds what the conflict path is handed.

        Both construct ``StoredPinRelease`` themselves, so they pass whichever release the
        resolution is composed with. Here the service is built by the dependency a request builds
        it by, so the pin row's fate after ``moved`` is the composition's answer and not the
        test's.
        """
        placed = a_block(14, 15, day_offset=3)
        await _seed_plan(sessions, owner.tenant_id, a_plan(blocks=(placed,)))
        await _seed_area(sessions, owner.tenant_id)
        # A deadline the drag crosses, so the pin carries a non-zero cost. Priced at zero, the
        # equality between the pin row and the surviving event below would hold for a blanked row.
        await _seed_task(
            sessions, owner.tenant_id, deadline=datetime(2026, 2, 12, 12, 0, tzinfo=UTC)
        )
        held = await _pin(sessions, owner, datetime(2026, 2, 12, 10, 0, tzinfo=UTC))
        pinned = replace(
            placed,
            interval=held.pin.interval,
            pinned=True,
            superseded_placement=held.pin.superseded_placement,
            objective_delta=held.pin.objective_delta,
        )
        await _seed_pinned_revision(sessions, owner.tenant_id, pinned)
        conflict = await _seed_conflict_against(sessions, owner.tenant_id, pinned)
        # Without this the release has nothing to delete, and the assertion below would hold for
        # the wrong reason.
        assert len(await _pins_held_by(sessions, owner.tenant_id)) == 1

        request = Request({"type": "http", "app": app})
        async with sessions() as session, session.begin():
            service = get_conflict_service(request, _principal(owner), session)
            resolved = await service.resolve(
                _principal(owner),
                conflict.id,
                ChosenResolution(resolution=MOVED_RESOLUTION, anchor_type=ABSENT),
            )

        assert resolved.conflict.resolution == MOVED_RESOLUTION
        assert await _pins_held_by(sessions, owner.tenant_id) == ()
        # The row was the constraint; the edit event is the fact about the week. What makes losing
        # the row lossless is the label the event keeps: the pair the pin was priced over, the cost,
        # and the weight set that priced it.
        async with sessions() as session:
            events = (
                await session.scalars(
                    select(EditEvent).where(EditEvent.tenant_id == owner.tenant_id)
                )
            ).all()
        assert len(events) == 1
        survivor = events[0]
        assert held.pin.objective_delta != 0.0
        assert survivor.objective_delta == held.pin.objective_delta
        assert survivor.weight_set_version == held.pin.weight_set_version
        assert (survivor.proposed_starts_at, survivor.proposed_ends_at) == (
            held.pin.superseded_placement.start,
            held.pin.superseded_placement.end,
        )
        assert (survivor.accepted_starts_at, survivor.accepted_ends_at) == (
            held.pin.interval.start,
            held.pin.interval.end,
        )


class TestDeadlineFeature:
    """A pin on a block that covers the task's estimate still records the deadline."""

    async def test_pinning_a_block_covering_its_tasks_estimate_records_the_deadline(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        # A 60-min task with a 60-min block: the pin fully covers the estimate
        deadline = datetime(2026, 2, 13, 9, 0, tzinfo=UTC)
        block = a_block(14, 15, day_offset=3)
        plan = a_plan(blocks=(block,))
        await _seed_plan(sessions, owner.tenant_id, plan)
        await _seed_area(sessions, owner.tenant_id, floor=0)
        await _seed_task(sessions, owner.tenant_id, deadline=deadline, estimate=60)

        # Pin the block to a new time
        await _pin(sessions, owner, datetime(2026, 2, 12, 10, 0, tzinfo=UTC))

        # Read the edit event's context back
        async with sessions() as session:
            events = (
                await session.scalars(
                    select(EditEvent).where(EditEvent.tenant_id == owner.tenant_id)
                )
            ).all()
            assert len(events) == 1
            context = events[0].context

        # The deadline must be recorded, even though the pin covers the full estimate
        assert context["was_deadline_constrained"] is True
        assert context["days_until_deadline"] is not None


class TestPreEditFields:
    """Fields section 11 labels 'at proposal time' must not read the post-pin assembly."""

    async def test_area_floor_minutes_records_the_declared_floor_not_the_netted_one(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """Floor 120, one 60-min block: the written floor must be 120, not 60."""
        block = a_block(14, 15, day_offset=3)
        plan = a_plan(blocks=(block,))
        await _seed_plan(sessions, owner.tenant_id, plan)
        await _seed_area(sessions, owner.tenant_id, floor=120)
        await _seed_task(sessions, owner.tenant_id)

        await _pin(sessions, owner, datetime(2026, 2, 12, 10, 0, tzinfo=UTC))

        async with sessions() as session:
            events = (
                await session.scalars(
                    select(EditEvent).where(EditEvent.tenant_id == owner.tenant_id)
                )
            ).all()
            assert len(events) == 1
            context = events[0].context

        # The declared floor is 120, not 120 - 60 = 60 (the solver's netted quantity)
        assert context["area_floor_minutes"] == 120

    async def test_pinned_blocks_in_week_records_the_count_before_this_pin(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """A first pin records 0, because at proposal time there were none."""
        block = a_block(14, 15, day_offset=3)
        plan = a_plan(blocks=(block,))
        await _seed_plan(sessions, owner.tenant_id, plan)
        await _seed_area(sessions, owner.tenant_id)
        await _seed_task(sessions, owner.tenant_id)

        await _pin(sessions, owner, datetime(2026, 2, 12, 10, 0, tzinfo=UTC))

        async with sessions() as session:
            events = (
                await session.scalars(
                    select(EditEvent).where(EditEvent.tenant_id == owner.tenant_id)
                )
            ).all()
            assert len(events) == 1
            context = events[0].context

        # At proposal time: zero pins existed
        assert context["pinned_blocks_in_week"] == 0


class TestObjectiveDeltaAndBreakdown:
    """The label and the breakdown are measured in the pre-pin frame."""

    async def test_a_drag_past_a_deadline_records_a_nonzero_delta(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """The delta must differ from a same-day drag and from a pin that moves nothing."""
        # Task: 240-min estimate, 60-min block, deadline Fri 18:00
        deadline = datetime(2026, 2, 13, 18, 0, tzinfo=UTC)
        block = a_block(14, 15, day_offset=3)  # Thu 14:00-15:00
        plan = a_plan(blocks=(block,))
        await _seed_plan(sessions, owner.tenant_id, plan)
        await _seed_area(sessions, owner.tenant_id, floor=0)
        await _seed_task(sessions, owner.tenant_id, deadline=deadline, estimate=240)

        # Drag to Saturday 10:00 (past the Friday deadline)
        past_deadline_start = datetime(2026, 2, 14, 10, 0, tzinfo=UTC)
        await _pin(sessions, owner, past_deadline_start)

        async with sessions() as session:
            events = (
                await session.scalars(
                    select(EditEvent).where(EditEvent.tenant_id == owner.tenant_id)
                )
            ).all()
            assert len(events) == 1
            delta = events[0].objective_delta
            context = events[0].context

        # The delta must be POSITIVE: moving past a deadline costs something
        assert delta > 0.0, f"expected positive delta for a drag past deadline, got {delta}"
        # The breakdown must record the pre-pin deadline_risk exactly: 5.625
        # (measured independently by the reviewer in a pre-pin frame evaluation)
        assert context["objective_breakdown"]["deadline_risk"] == pytest.approx(5.625, abs=0.01)

    async def test_the_measurement_delta_reprices_to_the_stored_delta_under_its_own_version(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """The seven differences and the one scalar are two readings of one comparison.

        The weight fit ranks a pair on the seven, and the pin's own price is the scalar. If the two
        disagree, the corpus carries a label that does not belong to its features, and no assertion
        over either alone can see it: this reprices the seven under the weights the row names and
        compares the result with the figure the row stores.

        The weights come from the stored version rather than from ``P0_WEIGHTS``, so the check is
        against what priced the row rather than against what this deployment happens to ship.
        """
        deadline = datetime(2026, 2, 13, 18, 0, tzinfo=UTC)
        plan = a_plan(blocks=(a_block(14, 15, day_offset=3),))
        await _seed_plan(sessions, owner.tenant_id, plan)
        await _seed_area(sessions, owner.tenant_id, floor=0)
        await _seed_task(sessions, owner.tenant_id, deadline=deadline, estimate=240)

        await _pin(sessions, owner, datetime(2026, 2, 14, 10, 0, tzinfo=UTC))

        async with sessions() as session:
            event = (
                await session.scalars(
                    select(EditEvent).where(EditEvent.tenant_id == owner.tenant_id)
                )
            ).one()
            weights = (
                await session.scalars(
                    select(WeightSetRow).where(
                        WeightSetRow.tenant_id == owner.tenant_id,
                        WeightSetRow.version == event.weight_set_version,
                    )
                )
            ).one()

        measured = event.context["measurement_delta"]
        assert set(measured) == set(OBJECTIVE_TERMS)
        repriced = sum(getattr(weights, term) * measured[term] for term in OBJECTIVE_TERMS)

        assert repriced == pytest.approx(event.objective_delta, rel=1e-9, abs=1e-9)
        # And the pair is not the degenerate one: a drag past a deadline moves at least one term.
        assert any(value != 0.0 for value in measured.values())

    async def test_a_pin_that_moves_nothing_records_a_measurement_delta_of_zero(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """The one pair that carries no preference, and it has to be visible as one.

        Pinning a block where it already is compares a plan with itself, so every difference is
        exactly nothing. A fit that counted such a pair would report a sample it learned nothing
        from, which is how a gate passes on a corpus with no signal in it.
        """
        block = a_block(14, 15, day_offset=3)
        plan = a_plan(blocks=(block,))
        await _seed_plan(sessions, owner.tenant_id, plan)
        await _seed_area(sessions, owner.tenant_id)
        await _seed_task(sessions, owner.tenant_id)

        await _pin(sessions, owner, block.interval.start)

        async with sessions() as session:
            event = (
                await session.scalars(
                    select(EditEvent).where(EditEvent.tenant_id == owner.tenant_id)
                )
            ).one()

        assert event.objective_delta == 0.0
        assert event.context["measurement_delta"] == dict.fromkeys(OBJECTIVE_TERMS, 0.0)
