"""The plan of record, the pending slot, and the concessions, against a real Postgres.

A fake database would not catch any of what is asserted here. The append-only guarantee is
structural and is asserted by the boundary suite; what needs a real server is everything the
SCHEMA enforces and everything a single statement has to do atomically:

- an approved revision with no instant of assent is rejected by a check constraint, so the
  repository's guard is not the only thing standing between the caller and a broken row;
- a second proposal for a week is rejected by a primary key, so replacement can only be an
  upsert;
- a second concession for one kind and target REPLACES the first, so approving a tradeoff
  twice does not double its effect;
- a reduction naming a date the concession's own week does not hold is refused on the write,
  because stored it would claim to have been honoured while pairing with no occurrence;
- and every statement that reaches Postgres carries the tenant predicate.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from syncr_api.core.db import create_db_engine, create_sessionmaker
from syncr_api.plans.adjustments import WeekAdjustmentRepository
from syncr_api.plans.config import APPLIED, APPROVED, PLAN_REVISIONS_TABLE, AdjustmentKind
from syncr_api.plans.errors import AdjustmentRejected
from syncr_api.plans.models import PlanRevision
from syncr_api.plans.proposals import PendingProposalRepository
from syncr_api.plans.repository import PlanRepository
from syncr_domain.weeks import IsoWeek
from tests.control_models import recording
from tests.live_tenants import delete_tenant, seed_owner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.plans.records import PlanRevisionRecord
    from syncr_domain.identifiers import TenantId
    from tests.control_models import StatementRecorder

pytestmark = pytest.mark.integration

WEEK = IsoWeek(2026, 7)
OTHER_WEEK = IsoWeek(2026, 8)
NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)
LATER = NOW + timedelta(minutes=5)

WEIGHT_SET_VERSION = 1


def document(week: IsoWeek = WEEK, **extra: Any) -> dict[str, Any]:
    """A plan document, as far as storage is concerned.

    The interior is not validated here and does not need to be: JSONB is schemaless at the
    database level and the shape is enforced by the Pydantic model that writes one. What the
    week is, however, IS read, because every document-describing column is derived from it.
    """
    return {"iso_week": str(week), "blocks": [], "discretionary_minutes": 4_320, **extra}


BREAKDOWN = {"deadline_risk": 0.0, "budget_deviation": 12.5}


@pytest.fixture
async def engine(live_database_url: str) -> AsyncIterator[AsyncEngine]:
    """An engine owned by this test's own event loop."""
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


async def append_revision(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    **overrides: Any,
) -> PlanRevisionRecord:
    """Append one revision, in its own transaction, with the fixture's defaults."""
    values: dict[str, Any] = {
        "document": document(),
        "objective_breakdown": BREAKDOWN,
        "status": APPLIED,
        "reason": "auto_applied_fill",
        "weight_set_version": WEIGHT_SET_VERSION,
        "input_version": 1,
        "created_at": NOW,
        **overrides,
    }
    async with sessions() as session, session.begin():
        return await PlanRepository(session, tenant_id).append(**values)


# --------------------------------------------------------------------------------
# Appending, and reading back
# --------------------------------------------------------------------------------


async def test_an_appended_revision_reads_back_with_its_document_intact(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # The document is the authority, so what comes out of JSONB has to be what went in,
    # nesting included.
    blocks = [{"id": "abc", "interval": {"start": "2026-02-09T09:00:00Z"}, "pinned": True}]

    appended = await append_revision(
        sessions, owner.tenant_id, document=document(blocks=blocks), input_version=41
    )

    async with sessions() as session:
        found = await PlanRepository(session, owner.tenant_id).latest(WEEK)
    assert found is not None
    assert found.id == appended.id
    assert found.document["blocks"] == blocks
    assert found.objective_breakdown == BREAKDOWN
    assert found.input_version == 41
    assert found.weight_set_version == WEIGHT_SET_VERSION
    assert found.status == APPLIED
    assert found.approved_at is None


async def test_a_record_holds_a_copy_a_caller_cannot_reach_the_row_through(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # The record is frozen, so its fields cannot be reassigned. Its JSONB payloads are copied
    # too, and DEEPLY: a document holds a list of blocks, so a top-level copy would hand back
    # the row's own list and a caller appending to it would change the value the row holds.
    #
    # The mapped row is held here on purpose. The session's identity map is weak and a record
    # keeps no reference to the row it was read from, so a row nothing else holds is usually
    # collected and the next read decodes the column again. That makes the aliasing
    # unobservable by luck rather than by design, and this is the case where the luck runs
    # out: anything in the same session that holds the row sees what a caller did to its value.
    blocks = [{"id": "abc", "pinned": True}]
    appended = await append_revision(sessions, owner.tenant_id, document=document(blocks=blocks))

    async with sessions() as session:
        row = await session.scalar(select(PlanRevision).where(PlanRevision.id == appended.id))
        assert row is not None
        record = await PlanRepository(session, owner.tenant_id).find(appended.id)
        assert record is not None
        record.document["blocks"].append({"id": "smuggled"})
        record.document["discretionary_minutes"] = 0

        assert row.document["blocks"] == blocks
        assert row.document["discretionary_minutes"] == 4_320


async def test_the_stored_week_is_the_document_s_week(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # The column is derived from the document, so a revision cannot be filed under a week its
    # document does not name: a read of that week would otherwise miss it forever.
    await append_revision(sessions, owner.tenant_id, document=document(OTHER_WEEK))

    async with sessions() as session:
        repository = PlanRepository(session, owner.tenant_id)
        under_the_document_s_week = await repository.latest(OTHER_WEEK)
        under_the_other_week = await repository.latest(WEEK)

    assert under_the_document_s_week is not None
    assert under_the_document_s_week.iso_week == OTHER_WEEK
    assert under_the_other_week is None


async def test_the_live_plan_is_the_newest_revision_and_the_baseline_is_the_approved_one(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # Two reads with different jobs: the live plan is whatever changed last, and churn is
    # measured against the last plan the user assented to.
    approved = await append_revision(
        sessions,
        owner.tenant_id,
        status=APPROVED,
        reason="user_approved",
        approved_at=NOW,
    )
    applied = await append_revision(
        sessions, owner.tenant_id, created_at=LATER, supersedes_id=approved.id
    )

    async with sessions() as session:
        repository = PlanRepository(session, owner.tenant_id)
        live = await repository.latest(WEEK)
        baseline = await repository.latest_approved(WEEK)
        history = await repository.history(WEEK)

    assert live is not None
    assert live.id == applied.id
    assert live.supersedes_id == approved.id
    assert baseline is not None
    assert baseline.id == approved.id
    assert baseline.is_approved() is True
    assert [revision.id for revision in history] == [applied.id, approved.id]


async def test_a_week_with_no_revision_reads_as_nothing(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    async with sessions() as session:
        repository = PlanRepository(session, owner.tenant_id)

        assert await repository.latest(WEEK) is None
        assert await repository.latest_approved(WEEK) is None
        assert await repository.history(WEEK) == []
        assert await repository.find(uuid4()) is None


async def test_another_tenants_revision_is_not_readable(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, other_owner: UserRecord
) -> None:
    theirs = await append_revision(sessions, other_owner.tenant_id)

    async with sessions() as session:
        mine = PlanRepository(session, owner.tenant_id)

        assert await mine.find(theirs.id) is None
        assert await mine.latest(WEEK) is None
        assert await mine.history(WEEK) == []


async def test_every_statement_the_revision_repository_executes_carries_the_tenant(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, recorder: StatementRecorder
) -> None:
    # Compiling a statement proves what was built; this proves what reached Postgres. Stated
    # over the reads: an INSERT carries the tenant as a column VALUE rather than as a
    # predicate, so a scope check over one would be reading for something that is not there.
    await append_revision(sessions, owner.tenant_id)
    async with sessions() as session:
        repository = PlanRepository(session, owner.tenant_id)
        await repository.latest(WEEK)
        await repository.latest_approved(WEEK)
        await repository.history(WEEK)

    reads = [
        statement
        for statement in recorder.against(PLAN_REVISIONS_TABLE)
        if statement.startswith("SELECT")
    ]
    unscoped = [
        statement
        for statement in recorder.without_a_tenant_predicate(PLAN_REVISIONS_TABLE)
        if statement.startswith("SELECT")
    ]

    assert reads, "no read of plan_revisions reached the database"
    assert unscoped == []


# --------------------------------------------------------------------------------
# The approved-instant pair, as the database sees it
# --------------------------------------------------------------------------------


async def test_an_approved_revision_without_its_instant_is_rejected_by_the_database(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # The repository guards the same pair. This is the half that holds for every other writer
    # there will ever be, including a psql session.
    async with sessions() as session:
        session.add(
            PlanRevision(
                id=uuid4(),
                tenant_id=owner.tenant_id,
                iso_week=str(WEEK),
                status=APPROVED,
                reason="user_approved",
                document=document(),
                objective_breakdown=BREAKDOWN,
                weight_set_version=WEIGHT_SET_VERSION,
                input_version=1,
                created_at=NOW,
                approved_at=None,
            )
        )
        with pytest.raises(IntegrityError, match="approved_states_when"):
            await session.flush()
        await session.rollback()


async def test_an_approved_revision_with_its_instant_is_accepted(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # The control for the constraint above: it rejects the pair rather than the status.
    approved = await append_revision(
        sessions, owner.tenant_id, status=APPROVED, reason="user_approved", approved_at=NOW
    )

    assert approved.approved_at == NOW
    assert approved.is_approved() is True


async def test_a_revision_status_the_vocabulary_does_not_name_is_rejected(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    async with sessions() as session:
        session.add(
            PlanRevision(
                id=uuid4(),
                tenant_id=owner.tenant_id,
                iso_week=str(WEEK),
                status="pending",
                reason="user_approved",
                document=document(),
                objective_breakdown=BREAKDOWN,
                weight_set_version=WEIGHT_SET_VERSION,
                input_version=1,
                created_at=NOW,
                approved_at=None,
            )
        )
        with pytest.raises(IntegrityError, match="status_is_known"):
            await session.flush()
        await session.rollback()


# --------------------------------------------------------------------------------
# The single pending slot
# --------------------------------------------------------------------------------


async def replace_proposal(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, **overrides: Any
) -> None:
    values: dict[str, Any] = {
        "document": document(),
        "proposal_diff": {"added": [], "removed": [], "moved": []},
        "objective_breakdown": BREAKDOWN,
        "verdict": {"feasible": True, "provenance": "solver"},
        "weight_set_version": 1,
        "input_version": 1,
        "operation_id": uuid4(),
        "created_at": NOW,
        **overrides,
    }
    async with sessions() as session, session.begin():
        await PendingProposalRepository(session, tenant_id).replace(**values)


async def test_replacing_the_slot_leaves_one_proposal_holding_the_newest_one(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # Twelve pins during a weekly session replace the slot twelve times, in place. What must
    # never happen is twelve proposals, because then "the pending proposal" has no answer.
    await replace_proposal(
        sessions, owner.tenant_id, input_version=41, candidate_adjustment={"kind": "breach_floor"}
    )
    await replace_proposal(sessions, owner.tenant_id, input_version=42, created_at=LATER)

    async with sessions() as session:
        found = await PendingProposalRepository(session, owner.tenant_id).find(WEEK)
    assert found is not None
    assert found.input_version == 42
    assert found.created_at == LATER
    # The concession rode in the slot, so replacing the slot discarded it.
    assert found.candidate_adjustment is None


async def test_each_week_has_its_own_slot(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    await replace_proposal(sessions, owner.tenant_id, input_version=7)
    await replace_proposal(
        sessions, owner.tenant_id, document=document(OTHER_WEEK), input_version=9
    )

    async with sessions() as session:
        proposals = PendingProposalRepository(session, owner.tenant_id)
        this_week = await proposals.find(WEEK)
        next_week = await proposals.find(OTHER_WEEK)

    assert this_week is not None
    assert next_week is not None
    assert (this_week.input_version, next_week.input_version) == (7, 9)


async def test_clearing_the_slot_reports_whether_it_held_anything(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # Approval clears the slot in the transaction that appends the approved revision, so the
    # answer is what tells a second approval that there is nothing left to approve.
    await replace_proposal(sessions, owner.tenant_id)

    async with sessions() as session, session.begin():
        proposals = PendingProposalRepository(session, owner.tenant_id)
        first = await proposals.clear(WEEK)
        second = await proposals.clear(WEEK)

    assert (first, second) == (True, False)
    async with sessions() as session:
        assert await PendingProposalRepository(session, owner.tenant_id).find(WEEK) is None


async def test_another_tenants_proposal_is_not_readable(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, other_owner: UserRecord
) -> None:
    await replace_proposal(sessions, other_owner.tenant_id)

    async with sessions() as session:
        assert await PendingProposalRepository(session, owner.tenant_id).find(WEEK) is None


# --------------------------------------------------------------------------------
# One concession per week, kind, and target
# --------------------------------------------------------------------------------


async def test_approving_the_same_concession_twice_does_not_double_it(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # The failure this replaces: clicking "breach the floor by 1h20m" twice breaching it by
    # 2h40m. The unique index is what makes the second approval a replacement.
    target = uuid4()

    async with sessions() as session, session.begin():
        adjustments = WeekAdjustmentRepository(session, owner.tenant_id)
        first = await adjustments.upsert(
            iso_week=WEEK,
            kind="breach_floor",
            target_id=target,
            delta_minutes=80,
            created_at=NOW,
            created_by_operation_id=uuid4(),
        )
        second = await adjustments.upsert(
            iso_week=WEEK,
            kind="breach_floor",
            target_id=target,
            delta_minutes=80,
            created_at=LATER,
            created_by_operation_id=uuid4(),
        )

    async with sessions() as session:
        stored = await WeekAdjustmentRepository(session, owner.tenant_id).for_week(WEEK)

    assert len(stored) == 1
    assert stored[0].delta_minutes == 80
    assert stored[0].created_at == LATER
    # The identity is kept, because a plan document already records the adjustments it was
    # solved under by identifier.
    assert first.id == second.id == stored[0].id


async def test_concessions_of_different_kinds_and_targets_coexist(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # The control for the collapse above: composition is the normal case, because each
    # concession names a distinct target and kind.
    area, task = uuid4(), uuid4()
    composed: tuple[tuple[AdjustmentKind, UUID], ...] = (
        ("breach_floor", area),
        ("drop_item", task),
        ("accept_partial", task),
    )

    async with sessions() as session, session.begin():
        adjustments = WeekAdjustmentRepository(session, owner.tenant_id)
        for kind, target in composed:
            await adjustments.upsert(
                iso_week=WEEK,
                kind=kind,
                target_id=target,
                created_at=NOW,
                created_by_operation_id=uuid4(),
            )

    async with sessions() as session:
        stored = await WeekAdjustmentRepository(session, owner.tenant_id).for_week(WEEK)

    assert sorted(row.kind for row in stored) == ["accept_partial", "breach_floor", "drop_item"]


async def test_a_concession_does_not_carry_into_the_next_week(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # A hard week must not silently become the new normal.
    async with sessions() as session, session.begin():
        await WeekAdjustmentRepository(session, owner.tenant_id).upsert(
            iso_week=WEEK,
            kind="reduce_routine",
            target_id=uuid4(),
            reductions={"2026-02-10": 20, "2026-02-11": 20, "2026-02-12": 20},
            created_at=NOW,
            created_by_operation_id=uuid4(),
        )

    async with sessions() as session:
        adjustments = WeekAdjustmentRepository(session, owner.tenant_id)
        this_week = await adjustments.for_week(WEEK)
        next_week = await adjustments.for_week(OTHER_WEEK)

    assert [row.reductions for row in this_week] == [
        {"2026-02-10": 20, "2026-02-11": 20, "2026-02-12": 20}
    ]
    assert next_week == []


async def test_a_concession_kind_the_vocabulary_does_not_name_is_rejected(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # The annotation is erased at runtime, and a later migration or a `psql` session is not
    # type-checked at all, so the check constraint is what actually closes the vocabulary.
    async with sessions() as session, session.begin():
        with pytest.raises(IntegrityError, match="kind_is_known"):
            await WeekAdjustmentRepository(session, owner.tenant_id).upsert(
                iso_week=WEEK,
                kind="cancel_the_week",  # type: ignore[arg-type]  # the point of the test
                target_id=uuid4(),
                created_at=NOW,
                created_by_operation_id=uuid4(),
            )


# --------------------------------------------------------------------------------
# WA7, and revoking a concession
# --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reductions", "refused"),
    [
        ({"2026-03-02": 20}, "is not a date"),
        ({"2026-02-10": 0}, "positive count"),
        ({"2026-02-10": -20}, "positive count"),
        ({"2026-02-10": True}, "positive count"),
    ],
)
async def test_a_reduction_no_week_could_honour_is_refused_rather_than_stored(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    reductions: dict[str, Any],
    refused: str,
) -> None:
    # WA7, on the write. A date outside the concession's own week pairs with no occurrence, and a
    # figure of zero or less either does nothing or LENGTHENS the routine a concession exists to
    # shorten. Either one stored would claim to have been honoured while changing nothing.
    async with sessions() as session, session.begin():
        with pytest.raises(AdjustmentRejected, match=refused):
            await WeekAdjustmentRepository(session, owner.tenant_id).upsert(
                iso_week=WEEK,
                kind="reduce_routine",
                target_id=uuid4(),
                reductions=reductions,
                created_at=NOW,
                created_by_operation_id=uuid4(),
            )

    async with sessions() as session:
        assert await WeekAdjustmentRepository(session, owner.tenant_id).for_week(WEEK) == []


async def test_revoking_a_concession_leaves_the_week_resolving_without_it(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # WA8's storage half: removing a concession changes the inputs, so the row goes and the next
    # assembly reads the week as it was declared. Deleted rather than marked revoked, because the
    # revision history already records which concessions each document was solved under.
    async with sessions() as session, session.begin():
        adjustments = WeekAdjustmentRepository(session, owner.tenant_id)
        stored = await adjustments.upsert(
            iso_week=WEEK,
            kind="breach_floor",
            target_id=uuid4(),
            delta_minutes=80,
            created_at=NOW,
            created_by_operation_id=uuid4(),
        )

    async with sessions() as session, session.begin():
        adjustments = WeekAdjustmentRepository(session, owner.tenant_id)
        found = await adjustments.find(stored.id)
        await adjustments.remove(stored.id)

    async with sessions() as session:
        adjustments = WeekAdjustmentRepository(session, owner.tenant_id)
        assert found is not None
        assert found.id == stored.id
        assert await adjustments.for_week(WEEK) == []
        assert await adjustments.find(stored.id) is None


async def test_another_tenants_concession_reads_as_absent_rather_than_as_forbidden(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # Which is what makes the 404 a revocation raises truthful, and what stops one tenant learning
    # that another holds a row by that identifier.
    async with sessions() as session, session.begin():
        stored = await WeekAdjustmentRepository(session, owner.tenant_id).upsert(
            iso_week=WEEK,
            kind="breach_floor",
            target_id=uuid4(),
            delta_minutes=80,
            created_at=NOW,
            created_by_operation_id=uuid4(),
        )

    async with sessions() as session, session.begin():
        stranger = WeekAdjustmentRepository(session, uuid4())
        assert await stranger.find(stored.id) is None
        await stranger.remove(stored.id)

    async with sessions() as session:
        assert await WeekAdjustmentRepository(session, owner.tenant_id).find(stored.id) is not None
