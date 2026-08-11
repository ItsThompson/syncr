"""A revocation racing an approval, over two connections: the order the two rows are taken in.

Both acts write the same two tables. The approval takes the week's version row ``FOR UPDATE``
before it reads anything, because its refusal is decided from what it read, and then writes the
concession. The revocation deletes the concession and bumps the same version row. So the pair is
one lock ordering stated twice, and if the two statements of it disagree the two transactions can
each hold the row the other is waiting for.

```
 the version row first     revoke:   hold(version) -> find -> delete -> bump -> commit
                           approve:  hold(version) -> read -> upsert -> bump -> commit
                           one order, so one waits for the other and both land

 the concession row first  revoke:   find -> delete ......... bump  (waits for the version row)
                           approve:  hold(version) -> read -> upsert (waits for the concession row)
                           a cycle, and Postgres kills one of them
```

Two tests, one per side of the interleaving, and each is sequenced by **observing the other side
blocked** rather than by sleeping: ``a_backend_blocked_on_a_lock`` reads ``pg_stat_activity``, so
the wait is a reading the test can assert on and not a hope about timing. Which statement is found
waiting is the whole difference between the two orderings, so it is asserted rather than printed.

The invariants asserted are over rows, and they differ by which side won because the outcome
legitimately does: an approval that lands after a revocation re-creates the concession it was
solved under, and one that lands before it has its concession revoked.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from syncr_api.approvals.service import ApprovalService
from syncr_api.concessions.service import ConcessionService
from syncr_api.core.db import create_db_engine, create_sessionmaker
from syncr_api.core.principal import Principal
from syncr_api.core.scopes import Scope
from syncr_api.plans.adjustments import WeekAdjustmentRepository
from syncr_api.plans.assembler import AssemblyCaller
from syncr_api.plans.candidates import as_document
from syncr_api.plans.facts import WeekAdjustment as WeekAdjustmentRow
from syncr_api.plans.injection import (
    DEFAULT_DEBOUNCE,
    build_verdict_recorder,
    build_week_assembler,
)
from syncr_api.plans.models import PlanRevision
from syncr_api.plans.proposals import PendingProposalRepository
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_documents import stored_document
from syncr_api.plans.surfaces import VerdictSurface
from syncr_api.plans.verdicts import ProbeCaller, WeekProbe
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.injection import build_solve_coordinator
from syncr_api.solving.lifecycle import OperationLifecycle
from syncr_api.solving.repository import OperationRepository
from syncr_api.user_settings.solve_inputs import TrackedWeekInputVersions
from syncr_domain.plan import AdjustmentKind
from syncr_solver.inputs import WeekAdjustment
from tests.live_tenants import delete_tenant, seed_owner
from tests.plan_documents import WEEK, a_document

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.columns import JsonDocument
    from syncr_api.plans.config import AdjustmentKind as StoredKind
    from syncr_api.plans.records import WeekAdjustmentRecord
    from syncr_domain.identifiers import OperationId, TenantId
    from syncr_domain.weeks import IsoWeek

pytestmark = pytest.mark.integration

BEFORE_THE_WEEK = datetime(2026, 2, 8, tzinfo=UTC)
AT_THE_RACE = datetime(2026, 2, 8, 12, 0, tzinfo=UTC)

# The concession both sides name. One identifier, because the proposal in the slot was solved
# under the row the revocation removes: that is what puts the two transactions on one index entry
# instead of on two rows that never contend.
THE_CONCESSION = uuid4()
THE_AREA = uuid4()
CONCEDED_MINUTES = 45
THE_APPROVALS_MINUTES = 80

BREAKDOWN: dict[str, Any] = {"deadline_risk": 0.0, "budget_deviation": 0.0}
A_VERDICT: dict[str, Any] = {"feasible": True, "shortfall_minutes": 0, "provenance": "solver"}
SLOT_VERSION = 1
WEIGHTS = 3

# Who made a step, and which step. Named, because both connections make the same three and a
# sentence is what a red has to be readable as.
THE_REVOCATION = "the revocation"
THE_APPROVAL = "the approval"
TOOK_THE_VERSION_ROW = "took the version row"
REMOVED_THE_CONCESSION = "removed the concession"
WROTE_THE_CONCESSION = "wrote the concession"
COMMITTED = "committed"

# How long a side waits to find the other one blocked on a lock. Reached in full only when the
# other side is NOT blocked, which is the failure this exists to make visible: a contended row is
# found waiting in single-digit milliseconds.
WINDOW = 3.0
POLL = 0.02

THE_PLAN = a_document(week=WEEK, adjustments=(THE_CONCESSION,))


@dataclass
class Interleaving:
    """What the two connections did, in the order they did it, and what they raised.

    ``blocked`` holds the statement each observed window found another backend waiting on a lock
    for, or ``None`` where nothing was waiting. It is the reading that separates the two lock
    orderings: one blocks the side that arrives second at the version row it has not taken yet, the
    other blocks a write on a row the other side is holding.
    """

    order: list[tuple[str, str]] = field(default_factory=list)
    blocked: list[str | None] = field(default_factory=list)
    raised: list[str] = field(default_factory=list)

    def mark(self, who: str, what: str) -> None:
        self.order.append((who, what))

    def saw(self, statement: str | None) -> None:
        self.blocked.append(statement)

    def finished(self, outcomes: Sequence[object]) -> None:
        """Record what each connection raised, or that it raised nothing."""
        self.raised = [named_cause(one) for one in outcomes if isinstance(one, BaseException)]

    def steps_of(self, who: str) -> list[str]:
        """One connection's own steps, in the order it made them."""
        return [what for one, what in self.order if one == who]

    def apart_from(self, step: tuple[str, str]) -> list[str]:
        """Every step as a sentence, in order, minus one whose position is the loop's to choose.

        A lock grant and the commit that released it land on two connections inside one event-loop
        turn, so which of the two appends its mark first is not the database's decision and is not
        asserted. Every other position here is ordered by the database.
        """
        return [f"{who} {what}" for who, what in self.order if (who, what) != step]


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


def principal_of(owner: UserRecord) -> Principal:
    return Principal(tenant_id=owner.tenant_id, user_id=owner.id, scopes=frozenset(Scope))


def the_candidate() -> WeekAdjustment:
    """The concession the proposal in the slot was solved under: the revoked one, again."""
    return WeekAdjustment(
        adjustment_id=THE_CONCESSION,
        kind=AdjustmentKind.BREACH_FLOOR,
        target_id=THE_AREA,
        delta_minutes=THE_APPROVALS_MINUTES,
    )


class AnnouncingVersions(WeekInputVersionRepository):
    """The version row, with its acquisition announced and a hook to run once it is held.

    The hook is where a test opens its window: it runs inside the transaction, with the row held,
    which is the only place from which the other connection's wait can be observed.
    """

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: TenantId,
        *,
        name: str,
        watched: Interleaving,
        then: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        super().__init__(session, tenant_id)
        self._name = name
        self._watched = watched
        self._then = then

    async def hold(self, iso_week: IsoWeek) -> int | None:
        held = await super().hold(iso_week)
        self._watched.mark(self._name, TOOK_THE_VERSION_ROW)
        if self._then is not None:
            await self._then()
        return held


class AnnouncingAdjustments(WeekAdjustmentRepository):
    """The concession table, with both writes announced and a hook to run after the delete."""

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: TenantId,
        *,
        name: str,
        watched: Interleaving,
        then: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        super().__init__(session, tenant_id)
        self._name = name
        self._watched = watched
        self._then = then

    async def remove(self, adjustment_id: UUID) -> None:
        await super().remove(adjustment_id)
        self._watched.mark(self._name, REMOVED_THE_CONCESSION)
        if self._then is not None:
            await self._then()

    async def upsert(
        self,
        *,
        iso_week: IsoWeek,
        kind: StoredKind,
        target_id: UUID,
        created_at: datetime,
        created_by_operation_id: OperationId,
        adjustment_id: UUID | None = None,
        reductions: JsonDocument | None = None,
        delta_minutes: int | None = None,
    ) -> WeekAdjustmentRecord:
        stored = await super().upsert(
            iso_week=iso_week,
            kind=kind,
            target_id=target_id,
            created_at=created_at,
            created_by_operation_id=created_by_operation_id,
            adjustment_id=adjustment_id,
            reductions=reductions,
            delta_minutes=delta_minutes,
        )
        self._watched.mark(self._name, WROTE_THE_CONCESSION)
        return stored


def a_concession_service(
    session: AsyncSession,
    tenant_id: TenantId,
    *,
    watched: Interleaving,
    after_the_delete: Callable[[], Awaitable[None]] | None = None,
) -> ConcessionService:
    """The production composition, with the two tables under test announcing what they did.

    Every collaborator is the real one and the wiring mirrors ``concessions/injection.py``: what
    this replaces is the announcement, not the behaviour, so the transaction under test is the one
    a ``DELETE`` request makes.
    """
    versions = AnnouncingVersions(session, tenant_id, name=THE_REVOCATION, watched=watched)
    return ConcessionService(
        assembler=build_week_assembler(session, tenant_id, caller=AssemblyCaller.REQUEST),
        probe=WeekProbe(caller=ProbeCaller.REQUEST),
        adjustments=AnnouncingAdjustments(
            session, tenant_id, name=THE_REVOCATION, watched=watched, then=after_the_delete
        ),
        verdicts=build_verdict_recorder(
            session, tenant_id, surface=VerdictSurface.TRADEOFF, session_mode_active=False
        ),
        coordinator=build_solve_coordinator(
            session, tenant_id, clock=lambda: AT_THE_RACE, debounce=DEFAULT_DEBOUNCE
        ),
        current=versions,
        versions=TrackedWeekInputVersions(versions, clock=lambda: AT_THE_RACE),
        clock=lambda: AT_THE_RACE,
    )


def an_approval_service(
    session: AsyncSession,
    tenant_id: TenantId,
    *,
    watched: Interleaving,
    after_the_hold: Callable[[], Awaitable[None]] | None = None,
) -> ApprovalService:
    """The production composition, with the same two tables announcing what they did."""
    return ApprovalService(
        revisions=PlanRepository(session, tenant_id),
        proposals=PendingProposalRepository(session, tenant_id),
        adjustments=AnnouncingAdjustments(session, tenant_id, name=THE_APPROVAL, watched=watched),
        versions=AnnouncingVersions(
            session, tenant_id, name=THE_APPROVAL, watched=watched, then=after_the_hold
        ),
        operations=OperationLifecycle(OperationRepository(session, tenant_id), lambda: AT_THE_RACE),
        clock=lambda: AT_THE_RACE,
    )


async def seed(sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId) -> None:
    """A live plan, a proposal that changes nothing about it, the concession, and a version row.

    The slot's document IS the live plan and its diff is empty, so the approval asks for no change
    and cannot be refused by the assent rule: whatever the rows say afterwards was decided by this
    interleaving.

    **The version row has to exist.** ``hold`` locks a row and creates none, so a week with no row
    serializes nothing, and a fixture without one would let both orderings pass for the wrong
    reason. A week that holds a concession has been solved, so the row is the ordinary state.
    """
    async with sessions() as session, session.begin():
        await PlanRepository(session, tenant_id).append(
            document=stored_document(THE_PLAN),
            objective_breakdown=BREAKDOWN,
            status="applied",
            reason="auto_applied_fill",
            weight_set_version=WEIGHTS,
            input_version=SLOT_VERSION,
            created_at=BEFORE_THE_WEEK,
        )
        await PendingProposalRepository(session, tenant_id).replace(
            document=stored_document(THE_PLAN),
            proposal_diff={"added": [], "removed": [], "moved": []},
            objective_breakdown=BREAKDOWN,
            verdict=A_VERDICT,
            weight_set_version=WEIGHTS,
            input_version=SLOT_VERSION,
            operation_id=uuid4(),
            created_at=BEFORE_THE_WEEK,
            candidate_adjustment=as_document(the_candidate()),
        )
        await WeekAdjustmentRepository(session, tenant_id).upsert(
            iso_week=WEEK,
            kind=AdjustmentKind.BREACH_FLOOR.value,
            target_id=THE_AREA,
            created_at=BEFORE_THE_WEEK,
            created_by_operation_id=uuid4(),
            adjustment_id=THE_CONCESSION,
            delta_minutes=CONCEDED_MINUTES,
        )
        await WeekInputVersionRepository(session, tenant_id).bump(WEEK, at=BEFORE_THE_WEEK)


async def a_backend_blocked_on_a_lock(
    sessions: async_sessionmaker[AsyncSession],
) -> str | None:
    """The statement another connection of this database is waiting on a lock for.

    A third connection, because the two under test are both inside transactions of their own. The
    block is READ rather than assumed: a test that slept instead could not tell a serialized wait
    from a fast path that never contended at all, and would pass under either lock ordering.

    ``None`` when nothing was found waiting inside ``WINDOW``, which is itself a reading.
    """
    waiting = text(
        "SELECT query FROM pg_stat_activity "
        "WHERE datname = current_database() AND pid <> pg_backend_pid() "
        "AND wait_event_type = 'Lock' LIMIT 1"
    )
    deadline = asyncio.get_running_loop().time() + WINDOW
    async with sessions() as session:
        while asyncio.get_running_loop().time() < deadline:
            found = await session.scalar(waiting)
            if found is not None:
                return str(found)
            # Postgres caches the backend-status snapshot for the rest of the reading
            # transaction, so a poll that stayed in one transaction would re-read its first
            # answer forever.
            await session.rollback()
            await asyncio.sleep(POLL)
    return None


def named_cause(raised: BaseException) -> str:
    """One exception as one line: its type, and its message when it has one.

    A message may be empty, and the lost side of ``gather(return_exceptions=True)`` is the case that
    matters rather than a hypothetical one: a ``CancelledError`` carries none. Indexing into its
    lines would raise from inside the assertion this exists to make readable.
    """
    lines = str(raised).splitlines()
    if not lines:
        return type(raised).__name__
    return f"{type(raised).__name__}: {lines[0]}"


async def revoking(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    watched: Interleaving,
    *,
    when: asyncio.Event | None = None,
    after_the_delete: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """One revocation, over its own connection, as the route makes it: one transaction."""
    if when is not None:
        await when.wait()
    async with sessions() as session, session.begin():
        service = a_concession_service(
            session, owner.tenant_id, watched=watched, after_the_delete=after_the_delete
        )
        await service.revoke(principal_of(owner), str(WEEK), THE_CONCESSION)
    watched.mark(THE_REVOCATION, COMMITTED)


async def approving(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    watched: Interleaving,
    *,
    when: asyncio.Event | None = None,
    after_the_hold: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """One approval, over its own connection, as the route makes it: one transaction."""
    if when is not None:
        await when.wait()
    async with sessions() as session, session.begin():
        service = an_approval_service(
            session, owner.tenant_id, watched=watched, after_the_hold=after_the_hold
        )
        await service.approve(principal_of(owner), str(WEEK))
    watched.mark(THE_APPROVAL, COMMITTED)


async def the_revocation_first(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> Interleaving:
    """The revocation opens the window, and the approval arrives inside it."""
    watched = Interleaving()
    go = asyncio.Event()

    async def open_the_window() -> None:
        go.set()
        watched.saw(await a_backend_blocked_on_a_lock(sessions))

    outcomes = await asyncio.gather(
        revoking(sessions, owner, watched, after_the_delete=open_the_window),
        approving(sessions, owner, watched, when=go),
        return_exceptions=True,
    )
    watched.finished(outcomes)
    return watched


async def the_approval_first(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> Interleaving:
    """The approval opens the window, and the revocation arrives inside it."""
    watched = Interleaving()
    go = asyncio.Event()

    async def open_the_window() -> None:
        go.set()
        watched.saw(await a_backend_blocked_on_a_lock(sessions))

    outcomes = await asyncio.gather(
        approving(sessions, owner, watched, after_the_hold=open_the_window),
        revoking(sessions, owner, watched, when=go),
        return_exceptions=True,
    )
    watched.finished(outcomes)
    return watched


async def concessions_of(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> Sequence[WeekAdjustmentRow]:
    async with sessions() as session:
        found = await session.scalars(
            select(WeekAdjustmentRow).where(WeekAdjustmentRow.tenant_id == tenant_id)
        )
        return list(found)


async def version_of(sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId) -> int | None:
    async with sessions() as session:
        return await WeekInputVersionRepository(session, tenant_id).current(WEEK)


async def revisions_of(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> Sequence[PlanRevision]:
    async with sessions() as session:
        found = await session.scalars(
            select(PlanRevision)
            .where(PlanRevision.tenant_id == tenant_id)
            .order_by(PlanRevision.created_at, PlanRevision.id)
        )
        return list(found)


def was_a_wait_for_the_version_row(statement: str | None) -> bool:
    """Whether the observed wait was for the version row rather than for a table's own write.

    This is what the ordering decides. With the version row taken first, the side that arrives
    second waits at its own ``SELECT ... FOR UPDATE`` and has written nothing yet. With the
    concession row taken first, the wait is at an ``INSERT`` instead, and each side is already
    holding a row the other one needs.
    """
    if statement is None:
        return False
    return "week_input_versions" in statement and "FOR UPDATE" in statement


class TestARevocationRacingAnApproval:
    async def test_the_approval_waits_for_the_version_row_and_both_transactions_land(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """The revocation holds the version row from its first statement, so nothing deadlocks.

        The approval arrives after the concession row is already deleted and waits at its own hold,
        having written nothing. It then re-creates the concession its proposal was solved under,
        which is the honest outcome of approving a tradeoff after the same one was revoked.
        """
        await seed(sessions, owner.tenant_id)

        watched = await the_revocation_first(sessions, owner)

        assert watched.raised == []
        assert watched.steps_of(THE_REVOCATION) == [
            TOOK_THE_VERSION_ROW,
            REMOVED_THE_CONCESSION,
            COMMITTED,
        ]
        assert watched.steps_of(THE_APPROVAL) == [
            TOOK_THE_VERSION_ROW,
            WROTE_THE_CONCESSION,
            COMMITTED,
        ]
        assert watched.apart_from((THE_APPROVAL, TOOK_THE_VERSION_ROW)) == [
            "the revocation took the version row",
            "the revocation removed the concession",
            "the revocation committed",
            "the approval wrote the concession",
            "the approval committed",
        ]
        # The wait itself, read out of pg_stat_activity: the approval was held at the version row
        # and not at a write of its own.
        assert [was_a_wait_for_the_version_row(one) for one in watched.blocked] == [True]

        stored = await concessions_of(sessions, owner.tenant_id)
        assert [(one.id, one.delta_minutes) for one in stored] == [
            (THE_CONCESSION, THE_APPROVALS_MINUTES)
        ]
        assert await version_of(sessions, owner.tenant_id) == 3
        assert [one.status for one in await revisions_of(sessions, owner.tenant_id)] == [
            "applied",
            "approved",
        ]

    async def test_the_revocation_waits_for_the_version_row_and_removes_what_the_approval_wrote(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """The same ordering from the other side, and the control on the test above.

        With the approval holding the version row first, the revocation waits at its own hold
        rather than deleting a row the approval is about to write. It then removes the concession
        the approval had just made real. Without this case the test above could pass because
        nothing in the fixture makes the two transactions contend at all.
        """
        await seed(sessions, owner.tenant_id)

        watched = await the_approval_first(sessions, owner)

        assert watched.raised == []
        assert watched.steps_of(THE_APPROVAL) == [
            TOOK_THE_VERSION_ROW,
            WROTE_THE_CONCESSION,
            COMMITTED,
        ]
        assert watched.steps_of(THE_REVOCATION) == [
            TOOK_THE_VERSION_ROW,
            REMOVED_THE_CONCESSION,
            COMMITTED,
        ]
        assert watched.apart_from((THE_REVOCATION, TOOK_THE_VERSION_ROW)) == [
            "the approval took the version row",
            "the approval wrote the concession",
            "the approval committed",
            "the revocation removed the concession",
            "the revocation committed",
        ]
        assert [was_a_wait_for_the_version_row(one) for one in watched.blocked] == [True]

        assert await concessions_of(sessions, owner.tenant_id) == []
        assert await version_of(sessions, owner.tenant_id) == 3
        assert [one.status for one in await revisions_of(sessions, owner.tenant_id)] == [
            "applied",
            "approved",
        ]


class TestNamingWhatWasRaised:
    """``named_cause`` is the whole diagnostic the two cases above have, so it may not raise itself.

    Driven directly rather than through the interleaving, because the shape that breaks it is one no
    ordering of the two transactions produces: an exception whose message is empty.
    """

    def test_a_cause_with_no_message_is_named_by_its_type(self) -> None:
        # `CancelledError` rather than a bare `Exception`, because it is the one that actually
        # arrives: `gather(return_exceptions=True)` hands back the cancellation of a side that lost.
        assert named_cause(asyncio.CancelledError()) == "CancelledError"

    def test_a_cause_with_a_message_is_named_by_both_and_bounded_to_one_line(self) -> None:
        assert (
            named_cause(RuntimeError("deadlock detected\nand a second line nobody needs"))
            == "RuntimeError: deadlock detected"
        )
