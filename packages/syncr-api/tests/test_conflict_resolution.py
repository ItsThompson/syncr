"""Resolving a conflict, against a real Postgres: every row of the resolution table.

"Move the block" means something different depending on what fixed the block's time, and each row
of that table is a different act on real rows. This suite drives all of them through the service
with real repositories, because every claim is about what was written: whether the week's input
version moved, whether a solve was queued, whether the pin was released, and whether the answer was
recorded at all.

Five groups.

**The three answers.** ``moved`` frees the block and queues a pass; ``kept-both`` records the answer
and changes nothing else, which makes it the one mutating path in this product that bumps no input
version; ``retyped`` changes what the commitment reserves and queues a pass.

**What ``moved`` does, per row of the table.** An unpinned block the solver placed needs no pin
released and no window stored, because the commitment is hard occupancy the solver may not fill. A
pinned block has its pin released first. A materialized template entry is refused, naming the two
paths, and the conflict stays open. So does a routine of the circadian frame and a derived buffer,
for the same reason and by the same rule.

**A conflict is answered once**, and the record of the answer is permanent.

**The commitment may have left the calendar**, and a retype of a commitment that is gone is refused
rather than raising a 404 about a conflict that exists.

**Another tenant's conflict is a 404**, and answering it changes nothing.

**Who can move a block is answered for every origin there is**, asserted over the vocabulary itself
rather than trusted from a comment: an origin added later fails a test rather than raising a
``KeyError`` on a request.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest

from syncr_api.anchors.injection import get_anchor_service
from syncr_api.anchors.repository import AnchorRepository
from syncr_api.anchors.type_repository import AnchorTypeRepository
from syncr_api.calendars.config import ANCHOR_SOURCE, ICS
from syncr_api.calendars.repository import CalendarSourceRepository
from syncr_api.conflicts.declarations import ChosenResolution
from syncr_api.conflicts.overlapped import MOVABILITY_BY_ORIGIN, Movability, overlapped_block
from syncr_api.conflicts.service import ConflictService
from syncr_api.core.db import create_db_engine, create_sessionmaker
from syncr_api.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from syncr_api.core.patches import ABSENT
from syncr_api.core.principal import Principal
from syncr_api.core.scopes import ALL_SCOPES, Scope
from syncr_api.plans.config import (
    FIRST_INPUT_VERSION,
    KEPT_BOTH_RESOLUTION,
    MOVED_RESOLUTION,
    RETYPED_RESOLUTION,
)
from syncr_api.plans.conflicts import PlanConflictRepository
from syncr_api.plans.overlaps import DetectedConflict
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_documents import stored_document
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.config import SOLVE
from syncr_api.solving.lifecycle import OperationLifecycle
from syncr_api.solving.repository import OperationRepository
from syncr_domain.identity import BindingRef, Origin, TransitLeg, is_placed_by_the_solver
from syncr_domain.intervals import Interval
from tests.anchor_specifications import INTERVIEW as INTERVIEW_TYPE
from tests.live_tenants import delete_tenant, seed_owner
from tests.plan_documents import WEEK, a_block, a_block_holding, a_document, between

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.plans.records import ConflictRecord
    from syncr_domain.identifiers import AnchorId, TenantId
    from syncr_domain.plan import Block, PlanDocument
    from syncr_domain.weeks import IsoWeek

pytestmark = pytest.mark.integration

NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)
BREAKDOWN = {"budget_deviation": 12.5}

GYM = BindingRef.for_habit(uuid4(), index=0)
LEETCODE = BindingRef.for_task(uuid4())
SLEEP = BindingRef.for_routine(uuid4(), on=WEEK.monday())
STANDUP_ENTRY = BindingRef.for_template_entry(uuid4(), on=WEEK.monday())


@dataclass
class ReleasedPins:
    """A pin release that records what it was asked to free.

    The seam's production implementation releases nothing, because nothing writes a pin yet. This
    is what makes the pinned row of the resolution table the real code path rather than a claim.
    """

    held: set[BindingRef] = field(default_factory=set)
    released: list[tuple[IsoWeek, BindingRef]] = field(default_factory=list)

    async def release(self, iso_week: IsoWeek, binding: BindingRef) -> bool:
        self.released.append((iso_week, binding))
        return binding in self.held


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


@pytest.fixture
def principal(owner: UserRecord) -> Principal:
    return Principal(tenant_id=owner.tenant_id, user_id=owner.id, scopes=ALL_SCOPES)


@pytest.fixture
def pins() -> ReleasedPins:
    return ReleasedPins()


def pinned(one: Block) -> Block:
    """``one`` as the user's own edit, which is what makes the user the one who can move it."""
    return replace(one, pinned=True, superseded_placement=between(20, 21), objective_delta=1.5)


async def store_live_plan(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, *blocks: Block
) -> PlanDocument:
    """Append a live plan holding these blocks, as the plan of record for the week."""
    document: PlanDocument = a_document(blocks=blocks)
    async with sessions() as session, session.begin():
        await PlanRepository(session, tenant_id).append(
            document=stored_document(document),
            objective_breakdown=BREAKDOWN,
            status="applied",
            reason="auto_applied_fill",
            weight_set_version=1,
            input_version=1,
            created_at=NOW,
        )
    return document


async def raise_conflict(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    *,
    binding: BindingRef,
    anchor_id: AnchorId | None = None,
) -> ConflictRecord:
    async with sessions() as session, session.begin():
        (raised,) = await PlanConflictRepository(session, tenant_id).raise_all(
            (
                DetectedConflict(
                    anchor_id=anchor_id or uuid4(),
                    iso_week=WEEK,
                    binding=binding,
                    overlap=between(9.5, 10),
                ),
            ),
            at=NOW,
        )
    return raised


async def add_anchor(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, *, typed: bool = False
) -> AnchorId:
    """One commitment on one ICS source, optionally already carrying a type."""
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
        anchor_type = (
            None
            if not typed
            else await AnchorTypeRepository(session, tenant_id).create(
                rule_order=0, specification=INTERVIEW_TYPE, created_at=NOW
            )
        )
        created = await AnchorRepository(session, tenant_id).create(
            source_id=source.id,
            external_uid=uuid4().hex,
            series_uid=None,
            title="Kontron Interview",
            interval=Interval(NOW, NOW + timedelta(hours=1)),
            location=None,
            anchor_type_id=None if anchor_type is None else anchor_type.id,
            type_overridden=False,
        )
    return created.id


async def declare_a_type(sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId) -> Any:
    async with sessions() as session, session.begin():
        return await AnchorTypeRepository(session, tenant_id).create(
            rule_order=1, specification=INTERVIEW_TYPE, created_at=NOW
        )


def a_service(
    session: AsyncSession, principal: Principal, pins: ReleasedPins | None = None
) -> ConflictService:
    """The service as a request composes it, with the pin release the caller wants.

    Built here rather than through ``get_conflict_service`` for one reason: the pin seam is what
    makes the pinned row of the resolution table reachable, and a test that could not substitute it
    would assert about a branch nothing reaches. Every other collaborator is the real one, and the
    routes suite drives the production wiring end to end.
    """
    operations = OperationRepository(session, principal.tenant_id)
    return ConflictService(
        conflicts=PlanConflictRepository(session, principal.tenant_id),
        revisions=PlanRepository(session, principal.tenant_id),
        versions=WeekInputVersionRepository(session, principal.tenant_id),
        operations=operations,
        lifecycle=OperationLifecycle(operations, lambda: NOW),
        anchors=get_anchor_service(principal, session),
        pins=pins or ReleasedPins(),
        clock=lambda: NOW,
    )


async def resolve(
    sessions: async_sessionmaker[AsyncSession],
    principal: Principal,
    conflict: ConflictRecord,
    resolution: str,
    *,
    pins: ReleasedPins | None = None,
    anchor_type: Any = ABSENT,
) -> Any:
    """Answer one conflict through the service."""
    async with sessions() as session, session.begin():
        return await a_service(session, principal, pins).resolve(
            principal,
            conflict.id,
            ChosenResolution(
                resolution=resolution,  # type: ignore[arg-type]
                anchor_type=anchor_type,
            ),
        )


async def current_version(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> int | None:
    async with sessions() as session:
        return await WeekInputVersionRepository(session, tenant_id).current(WEEK)


async def in_flight_solve(sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId) -> Any:
    async with sessions() as session:
        return await OperationRepository(session, tenant_id).in_flight(WEEK, kind=SOLVE)


class TestMovedByRowOfTheResolutionTable:
    async def test_an_unpinned_block_the_solver_placed_is_freed_by_a_solve_alone(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord, principal: Principal
    ) -> None:
        # No window is stored anywhere: the commitment is hard occupancy now, so the rules the
        # solve is subject to already close the window this block was in.
        await store_live_plan(sessions, owner.tenant_id, a_block_holding(GYM, between(9, 10)))
        conflict = await raise_conflict(sessions, owner.tenant_id, binding=GYM)
        pins = ReleasedPins()

        resolved = await resolve(sessions, principal, conflict, MOVED_RESOLUTION, pins=pins)

        assert resolved.conflict.resolution == MOVED_RESOLUTION
        assert resolved.conflict.resolved_at is not None
        assert pins.released == []
        assert resolved.operation is not None
        assert resolved.operation.kind == SOLVE
        assert await current_version(sessions, owner.tenant_id) == FIRST_INPUT_VERSION

    async def test_a_pinned_block_has_its_pin_released_first(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord, principal: Principal
    ) -> None:
        await store_live_plan(
            sessions, owner.tenant_id, pinned(a_block_holding(GYM, between(9, 10)))
        )
        conflict = await raise_conflict(sessions, owner.tenant_id, binding=GYM)
        pins = ReleasedPins(held={GYM})

        resolved = await resolve(sessions, principal, conflict, MOVED_RESOLUTION, pins=pins)

        assert pins.released == [(WEEK, GYM)]
        assert resolved.conflict.resolution == MOVED_RESOLUTION
        assert resolved.operation is not None

    async def test_a_pinned_block_overlapped_by_a_derived_buffer_is_the_same_act(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord, principal: Principal
    ) -> None:
        # The third overlap class. The buffer cannot move at all, so removing the pin is the only
        # thing that can, which is what makes this row the same act as the one above it.
        await store_live_plan(
            sessions, owner.tenant_id, pinned(a_block_holding(GYM, between(15, 16)))
        )
        anchor_id = uuid4()
        conflict = await raise_conflict(sessions, owner.tenant_id, binding=GYM, anchor_id=anchor_id)
        pins = ReleasedPins(held={GYM})

        resolved = await resolve(sessions, principal, conflict, MOVED_RESOLUTION, pins=pins)

        assert pins.released == [(WEEK, GYM)]
        assert resolved.conflict.anchor_id == anchor_id

    @pytest.mark.parametrize(
        "binding", [STANDUP_ENTRY, SLEEP], ids=["template_entry", "circadian_frame"]
    )
    async def test_a_block_a_declaration_fixes_is_refused_with_the_two_paths(
        self,
        sessions: async_sessionmaker[AsyncSession],
        owner: UserRecord,
        principal: Principal,
        binding: BindingRef,
    ) -> None:
        # TE3's own rule: a collision raises a conflict rather than displacing the entry, so
        # something has to decide whether this week is an exception or the shape was wrong.
        await store_live_plan(sessions, owner.tenant_id, a_block_holding(binding, between(9, 10)))
        conflict = await raise_conflict(sessions, owner.tenant_id, binding=binding)
        pins = ReleasedPins()

        with pytest.raises(Conflict, match="pin this occurrence somewhere else"):
            await resolve(sessions, principal, conflict, MOVED_RESOLUTION, pins=pins)

        assert pins.released == []
        async with sessions() as session:
            held = await PlanConflictRepository(session, owner.tenant_id).find(conflict.id)
        assert held is not None
        assert not held.is_resolved

    async def test_a_pinned_template_entry_is_the_users_to_move_rather_than_a_refusal(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord, principal: Principal
    ) -> None:
        # The pin is what put the block where it is, whatever the origin says about where it
        # would otherwise have gone, so releasing the pin is what moves it.
        await store_live_plan(
            sessions, owner.tenant_id, pinned(a_block_holding(STANDUP_ENTRY, between(9, 10)))
        )
        conflict = await raise_conflict(sessions, owner.tenant_id, binding=STANDUP_ENTRY)
        pins = ReleasedPins(held={STANDUP_ENTRY})

        resolved = await resolve(sessions, principal, conflict, MOVED_RESOLUTION, pins=pins)

        assert pins.released == [(WEEK, STANDUP_ENTRY)]
        assert resolved.conflict.resolution == MOVED_RESOLUTION

    async def test_a_derived_buffer_of_another_commitment_is_refused_too(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord, principal: Principal
    ) -> None:
        # A buffer's time is measured from its own commitment's, so nothing may move it.
        leg = BindingRef.for_anchor_transit(uuid4(), leg=TransitLeg.OUT)
        await store_live_plan(sessions, owner.tenant_id, a_block_holding(leg, between(9, 10)))
        conflict = await raise_conflict(sessions, owner.tenant_id, binding=leg)

        with pytest.raises(Conflict, match="fixed by something you declared"):
            await resolve(sessions, principal, conflict, MOVED_RESOLUTION)

    async def test_a_block_the_live_plan_no_longer_holds_is_answered_by_a_solve(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord, principal: Principal
    ) -> None:
        # A later revision already relocated it. There is no pin to release and nothing to refuse.
        await store_live_plan(sessions, owner.tenant_id, a_block_holding(LEETCODE, between(14, 15)))
        conflict = await raise_conflict(sessions, owner.tenant_id, binding=GYM)

        resolved = await resolve(sessions, principal, conflict, MOVED_RESOLUTION)

        assert resolved.conflict.resolution == MOVED_RESOLUTION
        assert resolved.operation is not None

    async def test_a_week_with_no_live_plan_is_answered_by_a_solve(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord, principal: Principal
    ) -> None:
        conflict = await raise_conflict(sessions, owner.tenant_id, binding=GYM)

        resolved = await resolve(sessions, principal, conflict, MOVED_RESOLUTION)

        assert resolved.conflict.resolution == MOVED_RESOLUTION


class TestKeptBothChangesNothingElse:
    async def test_the_overlap_is_left_and_no_solve_is_asked_for(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord, principal: Principal
    ) -> None:
        # The one mutating path in this product that bumps no input version: it changes neither
        # the solve inputs nor the live plan.
        await store_live_plan(sessions, owner.tenant_id, a_block_holding(GYM, between(9, 10)))
        conflict = await raise_conflict(sessions, owner.tenant_id, binding=GYM)

        resolved = await resolve(sessions, principal, conflict, KEPT_BOTH_RESOLUTION)

        assert resolved.conflict.resolution == KEPT_BOTH_RESOLUTION
        assert resolved.operation is None
        assert await current_version(sessions, owner.tenant_id) is None
        assert await in_flight_solve(sessions, owner.tenant_id) is None

    async def test_it_is_recorded_even_for_a_block_nothing_may_move(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord, principal: Principal
    ) -> None:
        # Accepting the overlap needs nobody to move anything, which is why the refusal that
        # `moved` raises for such a block does not apply here.
        await store_live_plan(
            sessions, owner.tenant_id, a_block_holding(STANDUP_ENTRY, between(9, 10))
        )
        conflict = await raise_conflict(sessions, owner.tenant_id, binding=STANDUP_ENTRY)

        resolved = await resolve(sessions, principal, conflict, KEPT_BOTH_RESOLUTION)

        assert resolved.conflict.is_resolved


class TestRetypedChangesWhatTheCommitmentReserves:
    async def test_a_retype_applies_the_type_and_asks_for_a_solve(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord, principal: Principal
    ) -> None:
        await store_live_plan(sessions, owner.tenant_id, a_block_holding(GYM, between(9, 10)))
        anchor_id = await add_anchor(sessions, owner.tenant_id)
        conflict = await raise_conflict(sessions, owner.tenant_id, binding=GYM, anchor_id=anchor_id)
        declared = await declare_a_type(sessions, owner.tenant_id)

        resolved = await resolve(
            sessions, principal, conflict, RETYPED_RESOLUTION, anchor_type=declared.id
        )

        assert resolved.conflict.resolution == RETYPED_RESOLUTION
        assert resolved.operation is not None
        async with sessions() as session:
            retyped = await AnchorRepository(session, owner.tenant_id).find(anchor_id)
        assert retyped is not None
        assert retyped.anchor_type_id == declared.id

    async def test_a_retype_to_no_type_leaves_the_commitment_as_opaque_busy_time(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord, principal: Principal
    ) -> None:
        # Which is often the right answer for a buffer that collided: the commitment casts nothing.
        anchor_id = await add_anchor(sessions, owner.tenant_id, typed=True)
        conflict = await raise_conflict(sessions, owner.tenant_id, binding=GYM, anchor_id=anchor_id)

        await resolve(sessions, principal, conflict, RETYPED_RESOLUTION, anchor_type=None)

        async with sessions() as session:
            retyped = await AnchorRepository(session, owner.tenant_id).find(anchor_id)
        assert retyped is not None
        assert retyped.anchor_type_id is None

    async def test_a_retype_that_states_no_type_at_all_is_refused(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord, principal: Principal
    ) -> None:
        # An omitted field and an explicit null are different requests, and clearing the type a
        # commitment carries is a destructive act to arrive at by leaving a field out.
        anchor_id = await add_anchor(sessions, owner.tenant_id, typed=True)
        conflict = await raise_conflict(sessions, owner.tenant_id, binding=GYM, anchor_id=anchor_id)

        with pytest.raises(ValidationFailed, match="Retyping states which"):
            await resolve(sessions, principal, conflict, RETYPED_RESOLUTION)

        async with sessions() as session:
            held = await PlanConflictRepository(session, owner.tenant_id).find(conflict.id)
        assert held is not None
        assert not held.is_resolved

    async def test_a_commitment_that_has_left_the_calendar_is_refused_rather_than_missing(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord, principal: Principal
    ) -> None:
        conflict = await raise_conflict(sessions, owner.tenant_id, binding=GYM)

        with pytest.raises(Conflict, match="no longer on your calendar"):
            await resolve(sessions, principal, conflict, RETYPED_RESOLUTION, anchor_type=None)

    @pytest.mark.parametrize("resolution", [MOVED_RESOLUTION, KEPT_BOTH_RESOLUTION])
    async def test_an_answer_that_changes_no_type_may_not_name_one(
        self,
        sessions: async_sessionmaker[AsyncSession],
        owner: UserRecord,
        principal: Principal,
        resolution: str,
    ) -> None:
        await store_live_plan(sessions, owner.tenant_id, a_block_holding(GYM, between(9, 10)))
        conflict = await raise_conflict(sessions, owner.tenant_id, binding=GYM)

        with pytest.raises(ValidationFailed, match="changes no commitment type"):
            await resolve(sessions, principal, conflict, resolution, anchor_type=None)


class TestOneAnswerPerConflict:
    async def test_a_conflict_already_answered_is_refused_naming_the_answer(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord, principal: Principal
    ) -> None:
        await store_live_plan(sessions, owner.tenant_id, a_block_holding(GYM, between(9, 10)))
        conflict = await raise_conflict(sessions, owner.tenant_id, binding=GYM)
        await resolve(sessions, principal, conflict, KEPT_BOTH_RESOLUTION)

        with pytest.raises(Conflict, match=f"already answered as {KEPT_BOTH_RESOLUTION}"):
            await resolve(sessions, principal, conflict, MOVED_RESOLUTION)

    async def test_the_open_list_holds_what_has_not_been_answered(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord, principal: Principal
    ) -> None:
        await store_live_plan(sessions, owner.tenant_id, a_block_holding(GYM, between(9, 10)))
        answered = await raise_conflict(sessions, owner.tenant_id, binding=GYM)
        open_one = await raise_conflict(sessions, owner.tenant_id, binding=LEETCODE)
        await resolve(sessions, principal, answered, KEPT_BOTH_RESOLUTION)

        async with sessions() as session:
            service = a_service(session, principal)
            still_open = await service.list_all(principal, resolved=False)
            every = await service.list_all(principal, resolved=None)

        assert [conflict.id for conflict in still_open] == [open_one.id]
        assert len(every) == 2


class TestAuthorization:
    async def test_another_tenants_conflict_is_a_404_and_changes_nothing(
        self,
        sessions: async_sessionmaker[AsyncSession],
        owner: UserRecord,
        other_owner: UserRecord,
        principal: Principal,
    ) -> None:
        theirs = await raise_conflict(sessions, other_owner.tenant_id, binding=GYM)

        with pytest.raises(NotFound):
            await resolve(sessions, principal, theirs, MOVED_RESOLUTION)

        async with sessions() as session:
            held = await PlanConflictRepository(session, other_owner.tenant_id).find(theirs.id)
        assert held is not None
        assert not held.is_resolved

    async def test_a_credential_without_the_write_scope_may_not_answer(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        reader = Principal(
            tenant_id=owner.tenant_id, user_id=owner.id, scopes=frozenset({Scope.PLAN_READ})
        )
        conflict = await raise_conflict(sessions, owner.tenant_id, binding=GYM)

        with pytest.raises(Forbidden, match=Scope.PLAN_WRITE.value):
            await resolve(sessions, reader, conflict, KEPT_BOTH_RESOLUTION)

    async def test_a_credential_without_the_read_scope_may_not_list(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        writer = Principal(
            tenant_id=owner.tenant_id, user_id=owner.id, scopes=frozenset({Scope.PLAN_WRITE})
        )

        async with sessions() as session:
            service = a_service(session, writer)
            with pytest.raises(Forbidden, match=Scope.PLAN_READ.value):
                await service.list_all(writer, resolved=False)


class TestWhoCanMoveABlockIsAnsweredForEveryOrigin:
    """The map's completeness, and where the bite for it now lives.

    The table is derived from ``syncr_domain.identity.PLACED_BY``, so a missing origin is
    impossible here and the completeness bite is in the domain's own suite, beside the
    vocabulary. What is still assertable here is that the derivation says what this package
    means by it: who chose the time decides who may move the block, and the third answer is
    the pin's rather than an origin's.
    """

    @pytest.mark.parametrize("origin", list(Origin))
    def test_a_block_the_solve_placed_is_the_solvers_to_move_and_no_other_is(
        self, origin: Origin
    ) -> None:
        expected = Movability.THE_SOLVER if is_placed_by_the_solver(origin) else Movability.NOBODY

        assert MOVABILITY_BY_ORIGIN[origin] is expected

    def test_the_map_answers_two_of_the_three_and_the_pin_answers_the_third(self) -> None:
        # `THE_USER` is deliberately not an origin's answer, because a pin is what put the block
        # where it is, whatever the origin says about where it would otherwise have gone.
        assert set(MOVABILITY_BY_ORIGIN.values()) == {Movability.THE_SOLVER, Movability.NOBODY}

    @pytest.mark.parametrize("origin", list(Origin))
    def test_a_pinned_block_of_any_origin_is_the_users_to_move(self, origin: Origin) -> None:
        # The pin-before-origin order, over the whole vocabulary rather than over one row of it.
        held = pinned(a_block(origin, interval=between(9, 10)))
        document = a_document(blocks=(held,))

        assert overlapped_block(document, held.id).movable_by is Movability.THE_USER

    @pytest.mark.parametrize("origin", list(Origin))
    def test_an_unpinned_block_of_any_origin_is_answered_without_a_lookup(
        self, origin: Origin
    ) -> None:
        # Driven through the function the service calls, so the answer comes from the same path a
        # request takes rather than from the mapping alone.
        held = a_block(origin, interval=between(9, 10))
        document = a_document(blocks=(held,))

        overlapped = overlapped_block(document, held.id)

        assert overlapped.movable_by is MOVABILITY_BY_ORIGIN[origin]
        assert overlapped.origin is origin
