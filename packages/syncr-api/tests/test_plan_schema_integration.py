"""The guards the schema itself holds, asserted by trying to break each one.

Every rule here is enforced by Postgres rather than by the code that writes a row, and each is
asserted by inserting the row it must refuse. That distinction matters because these tables are
written by code that does not exist yet: the outcome path, the conflict detector, the verdict
recorder, and the solve coordinator all arrive later, and what stops them from writing a row
that lies is the constraint rather than a review of their repository.

The three partial and unique indexes carry the invariants the deployment notes call structural:
one non-terminal solve per tenant per week, one active weight set per tenant, and one outcome
per block and plan of record. Each is asserted to BITE here; the boundary suite asserts each is
declared, which is the half that fails when a later migration drops one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from syncr_api.core.db import create_db_engine, create_sessionmaker
from syncr_api.learned.config import FIRST_WEIGHT_SET_VERSION, HAND_TUNED, P0_WEIGHTS
from syncr_api.learned.models import WeightSet
from syncr_api.learned.repository import WeightSetRepository
from syncr_api.plans.config import APPLIED
from syncr_api.plans.facts import BlockOutcome, EditEvent, Pin, PlanConflict, VerdictEvent
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_documents import stored_binding
from syncr_api.solving.config import FAILED, RUNNING, SUCCEEDED, SUPERSEDED
from syncr_api.solving.models import Operation
from syncr_api.solving.repository import OperationRepository
from syncr_domain.identity import BindingRef, block_id
from syncr_domain.weeks import IsoWeek
from tests.live_tenants import delete_tenant, seed_owner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_domain.identifiers import PlanRevisionId, TenantId

pytestmark = pytest.mark.integration

WEEK = IsoWeek(2026, 7)
OTHER_WEEK = IsoWeek(2026, 8)
NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)
LATER = NOW + timedelta(minutes=30)
# Built through the domain rather than written out. The tables accept a malformed identity -- a
# JSONB column holds any object, and the id column is a `varchar(64)`, so a shorter digest fits --
# so the one hand-written example in the repository is derived instead, and stays legal.
A_BINDING = BindingRef.for_habit(uuid4(), index=0)
BLOCK_ID = block_id(WEEK, A_BINDING)
BINDING = stored_binding(A_BINDING)


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
async def revision_id(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> PlanRevisionId:
    """A live revision for the week, because an outcome names the plan of record it belongs to."""
    async with sessions() as session, session.begin():
        appended = await PlanRepository(session, owner.tenant_id).append(
            document={"iso_week": str(WEEK), "blocks": []},
            objective_breakdown={},
            status=APPLIED,
            reason="materialized",
            weight_set_version=FIRST_WEIGHT_SET_VERSION,
            input_version=1,
            created_at=NOW,
        )
    return appended.id


async def refuses(sessions: async_sessionmaker[AsyncSession], row: object, constraint: str) -> None:
    """Assert Postgres rejects ``row``, naming the constraint that did it."""
    async with sessions() as session:
        session.add(row)
        with pytest.raises(IntegrityError, match=constraint):
            await session.flush()
        await session.rollback()


async def accepts(sessions: async_sessionmaker[AsyncSession], row: object) -> None:
    """Assert Postgres accepts ``row``, which is what makes each rejection above specific."""
    async with sessions() as session, session.begin():
        session.add(row)
        await session.flush()


def outcome(tenant_id: TenantId, revision: PlanRevisionId, **overrides: Any) -> BlockOutcome:
    values: dict[str, Any] = {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "block_id": BLOCK_ID,
        "binding": BINDING,
        "revision_id": revision,
        "state": "presumed",
        "occurred_at": NOW,
        **overrides,
    }
    return BlockOutcome(**values)


# --------------------------------------------------------------------------------
# Outcomes: the required halves, and the identity
# --------------------------------------------------------------------------------


async def test_a_partial_outcome_must_state_its_minutes(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, revision_id: PlanRevisionId
) -> None:
    # The sole source of the duration-estimate signal. A `partial` without minutes is a row that
    # claims to teach something and teaches nothing, and the estimate-accuracy metric dies on it.
    await refuses(
        sessions,
        outcome(owner.tenant_id, revision_id, state="partial"),
        "partial_states_its_minutes",
    )
    await accepts(
        sessions, outcome(owner.tenant_id, revision_id, state="partial", actual_minutes=35)
    )


async def test_a_moved_outcome_must_state_when_it_happened(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, revision_id: PlanRevisionId
) -> None:
    # `moved` is the time-of-day fitness signal, and without the interval it says only that
    # something did not happen when planned.
    await refuses(
        sessions, outcome(owner.tenant_id, revision_id, state="moved"), "moved_states_when"
    )
    await accepts(
        sessions,
        outcome(
            owner.tenant_id,
            revision_id,
            state="moved",
            actual_starts_at=LATER,
            actual_ends_at=LATER + timedelta(minutes=45),
        ),
    )


async def test_half_an_actual_interval_is_refused(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, revision_id: PlanRevisionId
) -> None:
    await refuses(
        sessions,
        outcome(owner.tenant_id, revision_id, state="completed", actual_starts_at=LATER),
        "actual_interval_is_whole",
    )


async def test_an_outcome_state_the_vocabulary_does_not_name_is_refused(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, revision_id: PlanRevisionId
) -> None:
    await refuses(
        sessions, outcome(owner.tenant_id, revision_id, state="probably"), "state_is_known"
    )


async def test_one_outcome_per_block_and_plan_of_record(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, revision_id: PlanRevisionId
) -> None:
    # `(block_id, revision_id)` identifies an outcome. Two rows for one pair would make "what
    # happened to this block" have two answers, and the retro would count it twice.
    await accepts(sessions, outcome(owner.tenant_id, revision_id, state="completed"))

    await refuses(
        sessions,
        outcome(owner.tenant_id, revision_id, state="skipped"),
        "uq_block_outcomes_tenant_id_block_id_revision_id",
    )


async def test_the_same_block_in_a_later_plan_of_record_is_a_second_outcome(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, revision_id: PlanRevisionId
) -> None:
    # The control for the index above: the pair is what identifies an outcome, so the same block
    # under a different revision is a different fact rather than a duplicate.
    async with sessions() as session, session.begin():
        later_revision = await PlanRepository(session, owner.tenant_id).append(
            document={"iso_week": str(WEEK), "blocks": []},
            objective_breakdown={},
            status=APPLIED,
            reason="anchor_delta",
            weight_set_version=FIRST_WEIGHT_SET_VERSION,
            input_version=2,
            created_at=LATER,
        )

    await accepts(sessions, outcome(owner.tenant_id, revision_id, state="completed"))
    await accepts(sessions, outcome(owner.tenant_id, later_revision.id, state="completed"))


async def test_an_outcome_whose_binding_no_longer_exists_is_still_readable(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, revision_id: PlanRevisionId
) -> None:
    # Why `binding` is denormalized onto the row: the outcome is a fact about a
    # week that happened, and the habit it belonged to may since have been deleted. There is no
    # foreign key to break, which is the point.
    await accepts(sessions, outcome(owner.tenant_id, revision_id, state="completed"))

    async with sessions() as session:
        stored = await session.scalar(
            select(BlockOutcome).where(BlockOutcome.tenant_id == owner.tenant_id)
        )

    assert stored is not None
    assert stored.binding == BINDING


# --------------------------------------------------------------------------------
# Pins, conflicts, verdict events
# --------------------------------------------------------------------------------


async def test_a_pin_that_records_half_a_superseded_placement_is_refused(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # A pin persists what the solver had chosen AND what the pin cost. Half of an interval
    # would render a reason panel that cannot say where the block would have been.
    await refuses(
        sessions,
        Pin(
            id=uuid4(),
            tenant_id=owner.tenant_id,
            iso_week=str(WEEK),
            binding=BINDING,
            starts_at=NOW,
            ends_at=LATER,
            superseded_starts_at=NOW,
            weight_set_version=FIRST_WEIGHT_SET_VERSION,
            created_at=NOW,
        ),
        "superseded_placement_is_whole",
    )


async def test_a_pin_whose_interval_is_not_half_open_is_refused(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    await refuses(
        sessions,
        Pin(
            id=uuid4(),
            tenant_id=owner.tenant_id,
            iso_week=str(WEEK),
            binding=BINDING,
            starts_at=LATER,
            ends_at=NOW,
            weight_set_version=FIRST_WEIGHT_SET_VERSION,
            created_at=NOW,
        ),
        "interval_is_half_open",
    )


async def test_a_resolved_conflict_states_both_when_and_how(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # A resolved conflict is retained, and the weekly session reads repeated collisions out
    # of these rows. A resolution instant with no resolution would be a row nobody can report.
    def conflict(**overrides: Any) -> PlanConflict:
        values: dict[str, Any] = {
            "id": uuid4(),
            "tenant_id": owner.tenant_id,
            "iso_week": str(WEEK),
            "anchor_id": uuid4(),
            "block_id": BLOCK_ID,
            "overlap_starts_at": NOW,
            "overlap_ends_at": LATER,
            "detected_at": NOW,
            **overrides,
        }
        return PlanConflict(**values)

    await refuses(sessions, conflict(resolved_at=LATER), "resolution_states_when")
    await refuses(sessions, conflict(resolution="moved"), "resolution_states_when")
    await refuses(
        sessions, conflict(resolved_at=LATER, resolution="ignored"), "resolution_is_known"
    )
    await accepts(sessions, conflict())
    await accepts(sessions, conflict(resolved_at=LATER, resolution="kept-both"))


async def test_a_feasible_verdict_cannot_carry_a_shortfall(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # The early-catch metric counts episodes of infeasibility, so a feasible row with minutes
    # attached would be counted as one and would make the ratio report a number that is not true.
    def event(**overrides: Any) -> VerdictEvent:
        values: dict[str, Any] = {
            "id": uuid4(),
            "tenant_id": owner.tenant_id,
            "iso_week": str(WEEK),
            "occurred_at": NOW,
            "provenance": "probe",
            "feasible": True,
            "shortfall_minutes": 0,
            "shortfall_kinds": [],
            "surface": "pin",
            "session_mode_active": True,
            "input_version": 1,
            **overrides,
        }
        return VerdictEvent(**values)

    await refuses(sessions, event(shortfall_minutes=90), "feasible_has_no_shortfall")
    await refuses(
        sessions, event(feasible=False, shortfall_minutes=-1), "shortfall_is_not_negative"
    )
    await refuses(sessions, event(surface="week_screen"), "surface_is_known")
    await refuses(sessions, event(provenance="assembler"), "provenance_is_known")
    await accepts(
        sessions,
        event(
            feasible=False,
            shortfall_minutes=90,
            shortfall_kinds=["deadline_capacity"],
            surface="maintainer",
            session_mode_active=False,
        ),
    )


async def test_an_edit_event_records_a_proposal_and_what_was_kept_instead(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # The pair the learning layer trains on. It must be written from the first pin, because a
    # fact not captured when it happened cannot be reconstructed later.
    await accepts(
        sessions,
        EditEvent(
            id=uuid4(),
            tenant_id=owner.tenant_id,
            iso_week=str(WEEK),
            binding=BINDING,
            proposed_starts_at=NOW,
            proposed_ends_at=NOW + timedelta(hours=1),
            accepted_starts_at=LATER,
            accepted_ends_at=LATER + timedelta(hours=1),
            objective_delta=1.75,
            context={"weekday": 0, "objective_breakdown": {"churn": 1.75}},
            weight_set_version=FIRST_WEIGHT_SET_VERSION,
            created_at=NOW,
        ),
    )

    async with sessions() as session:
        stored = await session.scalar(
            select(EditEvent).where(EditEvent.tenant_id == owner.tenant_id)
        )

    assert stored is not None
    assert stored.objective_delta == 1.75
    assert stored.context["objective_breakdown"] == {"churn": 1.75}


# --------------------------------------------------------------------------------
# Operations: the single-flight index
# --------------------------------------------------------------------------------


async def test_a_second_in_flight_solve_for_one_week_is_refused(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # The single-flight invariant. A mutation arriving while a solve runs must bump the week's
    # input version and create no second operation; if a caller tried, this is what stops two
    # solves racing to write one week.
    async with sessions() as session, session.begin():
        await OperationRepository(session, owner.tenant_id).enqueue(
            kind="solve", iso_week=WEEK, scheduled_for=NOW
        )

    async with sessions() as session, session.begin():
        with pytest.raises(
            IntegrityError, match="uq_operations_tenant_id_iso_week_in_flight_solve"
        ):
            await OperationRepository(session, owner.tenant_id).enqueue(
                kind="solve", iso_week=WEEK, scheduled_for=LATER
            )


@pytest.mark.parametrize("terminal", [SUCCEEDED, SUPERSEDED, FAILED])
async def test_a_solve_can_be_enqueued_once_the_previous_one_is_terminal(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, terminal: str
) -> None:
    # The control for the index: it is partial on purpose. A week solves many times over its
    # life, and only the non-terminal ones are unique.
    async with sessions() as session, session.begin():
        first = await OperationRepository(session, owner.tenant_id).enqueue(
            kind="solve", iso_week=WEEK, scheduled_for=NOW
        )
        stored = await session.get(Operation, first.id)
        assert stored is not None
        stored.status = terminal
        stored.finished_at = LATER

    async with sessions() as session, session.begin():
        second = await OperationRepository(session, owner.tenant_id).enqueue(
            kind="solve", iso_week=WEEK, scheduled_for=LATER
        )

    assert second.id != first.id


async def test_the_index_is_scoped_to_solves_and_to_one_week_and_tenant(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, other_owner: UserRecord
) -> None:
    # Three controls in one: a materialize alongside a solve, the next week alongside this one,
    # and another tenant's solve for the same week. Each has to be allowed, or the index is
    # holding more than the invariant it exists for.
    async with sessions() as session, session.begin():
        mine = OperationRepository(session, owner.tenant_id)
        await mine.enqueue(kind="solve", iso_week=WEEK, scheduled_for=NOW)
        await mine.enqueue(kind="materialize", iso_week=WEEK, scheduled_for=NOW)
        await mine.enqueue(kind="solve", iso_week=OTHER_WEEK, scheduled_for=NOW)
        await OperationRepository(session, other_owner.tenant_id).enqueue(
            kind="solve", iso_week=WEEK, scheduled_for=NOW
        )

    async with sessions() as session:
        in_flight = await OperationRepository(session, owner.tenant_id).in_flight(
            WEEK, kind="solve"
        )

    assert in_flight is not None
    assert in_flight.iso_week == WEEK
    assert in_flight.input_version is None, "the version is stamped when the worker loads inputs"
    assert in_flight.attempt == 1


async def test_an_operation_targets_a_week_or_a_source_and_never_both(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    async with sessions() as session, session.begin():
        calendar_sync = await OperationRepository(session, owner.tenant_id).enqueue(
            kind="calendar_sync", source_id=uuid4(), scheduled_for=NOW
        )
    assert calendar_sync.iso_week is None
    assert calendar_sync.source_id is not None

    async with sessions() as session, session.begin():
        with pytest.raises(IntegrityError, match="target_is_one_thing"):
            await OperationRepository(session, owner.tenant_id).enqueue(
                kind="solve", iso_week=WEEK, source_id=uuid4(), scheduled_for=NOW
            )

    async with sessions() as session, session.begin():
        with pytest.raises(IntegrityError, match="target_is_one_thing"):
            await OperationRepository(session, owner.tenant_id).enqueue(
                kind="solve", scheduled_for=NOW
            )


async def test_a_failure_snapshot_belongs_to_a_failure(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # The snapshot exists so a production failure is reproducible locally, and it is pruned with
    # the row. Attached to anything but a failure it would be a week of plan data nobody reads.
    def operation(**overrides: Any) -> Operation:
        values: dict[str, Any] = {
            "id": uuid4(),
            "tenant_id": owner.tenant_id,
            "kind": "solve",
            "status": RUNNING,
            "iso_week": str(WEEK),
            "scheduled_for": NOW,
            "attempt": 1,
            **overrides,
        }
        return Operation(**values)

    await refuses(
        sessions,
        operation(failed_input_snapshot={"iso_week": str(WEEK)}),
        "snapshot_belongs_to_a_failure",
    )
    await refuses(sessions, operation(error_code="solver_timeout"), "error_states_both_halves")
    await accepts(
        sessions,
        operation(
            status=FAILED,
            finished_at=LATER,
            error_code="solver_timeout",
            error_message="the solver exceeded its budget; the previous live plan is untouched",
            failed_input_snapshot={"iso_week": str(WEEK)},
        ),
    )


# --------------------------------------------------------------------------------
# Weight sets: one active per tenant
# --------------------------------------------------------------------------------


async def test_seeding_gives_the_tenant_version_one_with_the_p0_weights(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    async with sessions() as session, session.begin():
        await WeightSetRepository(session, owner.tenant_id).seed_hand_tuned(at=NOW)

    async with sessions() as session:
        active = await WeightSetRepository(session, owner.tenant_id).active()

    assert active is not None
    assert (active.version, active.origin, active.active) == (
        FIRST_WEIGHT_SET_VERSION,
        HAND_TUNED,
        True,
    )
    assert active.deadline_risk == P0_WEIGHTS["deadline_risk"]
    assert active.churn_tolerance == P0_WEIGHTS["churn_tolerance"]
    # A parameter below its maturity gate is not applied at all, so nothing fitted starts at a
    # neutral value: absence is what "unlearned" looks like to the solver.
    assert active.duration_multiplier == {}
    assert active.time_of_day_fitness == {}
    assert active.skip_probability == {}
    assert active.maturity == []
    assert active.fitted_at is None


async def test_a_second_active_weight_set_for_one_tenant_is_refused(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # Two rows both claiming to be the weights in use would make the solve path pick whichever
    # the scan returned first, and a plan would be explained under weights that did not produce
    # it.
    async with sessions() as session, session.begin():
        await WeightSetRepository(session, owner.tenant_id).seed_hand_tuned(at=NOW)

    await refuses(
        sessions,
        WeightSet(
            tenant_id=owner.tenant_id,
            version=FIRST_WEIGHT_SET_VERSION + 1,
            active=True,
            origin="fitted",
            fitted_at=LATER,
            created_at=LATER,
            **P0_WEIGHTS,
        ),
        "uq_weight_sets_tenant_id_active",
    )


async def test_an_inactive_later_version_is_accepted(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # The control for the partial index: comparison and rollback are the reason versions exist,
    # so several versions per tenant is the normal state and only one of them is active.
    async with sessions() as session, session.begin():
        await WeightSetRepository(session, owner.tenant_id).seed_hand_tuned(at=NOW)

    await accepts(
        sessions,
        WeightSet(
            tenant_id=owner.tenant_id,
            version=FIRST_WEIGHT_SET_VERSION + 1,
            active=False,
            origin="fitted",
            fitted_at=LATER,
            created_at=LATER,
            **P0_WEIGHTS,
        ),
    )

    async with sessions() as session:
        repository = WeightSetRepository(session, owner.tenant_id)
        versions = await repository.versions()
        active = await repository.active()

    assert [row.version for row in versions] == [2, 1]
    assert active is not None
    assert active.version == FIRST_WEIGHT_SET_VERSION


async def test_a_hand_tuned_set_that_claims_to_have_been_fitted_is_refused(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    await refuses(
        sessions,
        WeightSet(
            tenant_id=owner.tenant_id,
            version=FIRST_WEIGHT_SET_VERSION,
            active=True,
            origin=HAND_TUNED,
            fitted_at=NOW,
            created_at=NOW,
            **P0_WEIGHTS,
        ),
        "fitted_states_when",
    )


async def test_each_tenant_has_its_own_active_weight_set(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, other_owner: UserRecord
) -> None:
    # The index is per tenant, so seeding a second tenant must not be rejected by the first
    # tenant's active row.
    async with sessions() as session, session.begin():
        await WeightSetRepository(session, owner.tenant_id).seed_hand_tuned(at=NOW)
        await WeightSetRepository(session, other_owner.tenant_id).seed_hand_tuned(at=NOW)

    async with sessions() as session:
        mine = await WeightSetRepository(session, owner.tenant_id).active()
        theirs = await WeightSetRepository(session, other_owner.tenant_id).active()

    assert mine is not None
    assert theirs is not None
    assert mine.tenant_id == owner.tenant_id
    assert theirs.tenant_id == other_owner.tenant_id


async def test_a_tenant_with_no_weight_set_reads_as_nothing(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    async with sessions() as session:
        repository = WeightSetRepository(session, owner.tenant_id)

        assert await repository.active() is None
        assert await repository.versions() == []
