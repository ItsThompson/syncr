"""The remedy a solver verdict's gap carries, enumerated where the assembly is already paid for.

The probe's read path enumerates tradeoffs over a fresh assembly every time it answers, because it
has no other; the solve's write has the assembly in hand, and the figures its gaps were measured
against with it. This suite drives the commit transaction over a real Postgres and a substituted
solver, and reads the answer back through ``GET /api/v1/weeks/{iso_week}``:

*A verdict naming a packing failure serves a remedy against that failure.* The slot holds the only
persisted solver verdict, and the week read serves that slot verbatim while it is current -- so the
enumeration frozen into the verdict at commit time is what the panel sees.

*The served figures do not move while the slot is current.* The week is mutated underneath the
slot -- directly, so no version bump marks it -- into one whose fresh enumeration would recover a
different figure, and the read still serves the figure the gap was measured against. The mutation
is also enumerated fresh, which is what shows the guard has bite: the figure really did move under
the week, and the served answer did not follow it.

*A feasible week serves none.* A verdict with no gap enumerates nothing, so the slot holds an
empty list rather than remedies for shortfalls that do not exist.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.areas.repository import AreaRepository
from syncr_api.concessions.config import WEEKS_PREFIX
from syncr_api.core.app_factory import create_app
from syncr_api.core.db import (
    create_database,
    create_db_engine,
    create_db_lifespan,
    create_sessionmaker,
)
from syncr_api.core.settings import (
    DEFAULT_SOLVE_DEBOUNCE_MS,
    DEV_ALLOWED_ORIGINS,
    WORKER_SERVICE,
    EnvSettings,
    build_service_settings,
)
from syncr_api.learned.repository import WeightSetRepository
from syncr_api.plans.assembler import AssemblyCaller
from syncr_api.plans.injection import build_week_assembler
from syncr_api.plans.tradeoffs import offered_tradeoffs
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.config import SUCCEEDED
from syncr_api.solving.dispatch import SolveDispatch
from syncr_api.solving.injection import build_solve_coordinator, debounce_window
from syncr_api.tasks.repository import TaskRepository
from syncr_api.templates.repository import DayTypeRepository, WeekPatternRepository
from syncr_api.user_settings.repository import SettingsRepository
from syncr_api.worker.main import WorkerContext
from syncr_domain.feasibility import Provenance, Verdict, minimum_chunk_shortfall
from syncr_domain.tasks import Priority
from syncr_domain.templates import WeekPattern
from syncr_domain.weeks import IsoWeek, Weekday
from syncr_solver.solve import SolveResult
from tests.live_tenants import PASSWORD, delete_tenant, seed_owner
from tests.test_solve_runner_integration import _NO_COST, _one_block_at, _placing_one_block

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Iterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings
    from syncr_api.solving.records import OperationRecord
    from syncr_domain.identifiers import TenantId
    from syncr_solver.inputs import SolveInputs

pytestmark = pytest.mark.integration

BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]

# Far enough ahead that the whole week is future capacity whenever this suite runs.
WEEK = IsoWeek.containing(datetime.now(UTC).date() + timedelta(days=60))
MONDAY = WEEK.monday()

# Monday morning of the week, so the block the substituted solver places on Tuesday is future and
# the deadline on Wednesday morning is reachable.
NOW = datetime(MONDAY.year, MONDAY.month, MONDAY.day, 9, tzinfo=UTC)
DEADLINE = datetime(MONDAY.year, MONDAY.month, MONDAY.day, 9, tzinfo=UTC) + timedelta(days=2)

TASK_TITLE = "Deep work"
TASK_ESTIMATE_MINUTES = 120
MUTATED_ESTIMATE_MINUTES = 30

# What the packing failure leaves unplaced, and the chunk nothing can place it in. The recovery a
# drop offer states is min(gap, remaining): the whole gap before the mutation, and the reduced
# remainder after it -- which is exactly the figure the freshness guard asserts does not travel.
GAP_MINUTES = 50
CHUNK_MINUTES = 50

# Where the moving solve puts the block: Tuesday 14:00 needs assent, and a proposal is what puts a
# verdict in the pending slot at all.
MOVED_HOUR = 14


class Ticking:
    """A clock fixed at the week's Monday morning, as every writer of this flow reads it."""

    def __call__(self) -> datetime:
        return NOW


@pytest.fixture
async def engine(live_database_url: str) -> AsyncIterator[AsyncEngine]:
    live = create_db_engine(live_database_url)
    yield live
    await live.dispose()


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_sessionmaker(engine)


@pytest.fixture
async def owners(
    sessions: async_sessionmaker[AsyncSession],
) -> AsyncIterator[Callable[[], Awaitable[UserRecord]]]:
    """A maker of tenants, each deleted with everything that cascades from it.

    The packing-failure cases and the feasible control each need their own tenant on the week, and
    the fixture body would otherwise be written twice. Every tenant made here is torn down whether
    or not its test reached the read.
    """
    made: list[UserRecord] = []

    async def make() -> UserRecord:
        account = await seed_owner(sessions)
        made.append(account)
        return account

    yield make
    for account in made:
        await delete_tenant(sessions, account.tenant_id)


@pytest.fixture
def clock() -> Ticking:
    return Ticking()


@pytest.fixture
async def context(live_database_url: str) -> AsyncIterator[WorkerContext]:
    worker = build_service_settings(service=WORKER_SERVICE, env=EnvSettings(_env_file=None))
    database = create_database(live_database_url)
    yield WorkerContext(settings=worker, database=database)
    await database.engine.dispose()


@pytest.fixture
def http(live_database_url: str, settings: ServiceSettings) -> Iterator[TestClient]:
    """A client against an app wired to the same database the worker side writes."""
    database = create_database(live_database_url)
    app = create_app(settings, lifespan=create_db_lifespan(database.engine))
    app.state.db = database
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def sign_in(http: TestClient, email: str) -> dict[str, str]:
    answered = http.post(
        f"{AUTH_PREFIX}/login",
        json={"email": email, "password": PASSWORD},
        headers={"Origin": BROWSER_ORIGIN},
    )
    assert answered.status_code == HTTPStatus.OK, answered.text
    cookie = answered.headers["set-cookie"]
    token = cookie.split(f"{SESSION_COOKIE_NAME}=", 1)[1].split(";", 1)[0]
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}", "Origin": BROWSER_ORIGIN}


async def declare_a_task_week(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> UUID:
    """A home zone, one Area, a day shape, a weight set, and one deadline-bearing task."""
    async with sessions() as session, session.begin():
        settings = SettingsRepository(session, tenant_id)
        locked = await settings.lock(created_at=NOW)
        await settings.write(
            visible_hours=locked.visible_hours,
            day_start=locked.day_start,
            day_end=locked.day_end,
            review_cadence=locked.review_cadence,
            home_zone="UTC",
        )
        area = await AreaRepository(session, tenant_id).create(
            parent_id=None,
            name="Career",
            pigment_index=1,
            budget_percent=Decimal(100),
            floor_hours=None,
            created_at=NOW,
        )
        day_type = await DayTypeRepository(session, tenant_id).create(
            name="Weekday", created_at=NOW
        )
        await WeekPatternRepository(session, tenant_id).replace(
            WeekPattern(dict.fromkeys(Weekday, day_type.id))
        )
        task = await TaskRepository(session, tenant_id).create(
            area_id=area.id,
            project_id=None,
            title=TASK_TITLE,
            estimate_minutes=TASK_ESTIMATE_MINUTES,
            deadline=DEADLINE,
            priority=Priority.NORMAL,
            min_chunk_minutes=CHUNK_MINUTES - 20,
            splittable=True,
            created_at=NOW,
        )
        await WeightSetRepository(session, tenant_id).seed_hand_tuned(at=NOW)
        return task.id


async def bump(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, clock: Ticking
) -> int:
    async with sessions() as session, session.begin():
        return await WeekInputVersionRepository(session, owner.tenant_id).bump(WEEK, at=clock())


async def request_a_solve(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, clock: Ticking
) -> None:
    """One immediate solve of the week, as a mutation of its inputs leaves behind."""
    async with sessions() as session, session.begin():
        await build_solve_coordinator(
            session,
            owner.tenant_id,
            clock=clock,
            debounce=debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS),
        ).request_solve(WEEK, 1, immediate=True, session_mode_active=False)


async def claimed(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, clock: Ticking
) -> OperationRecord:
    async with sessions() as session, session.begin():
        claim = await build_solve_coordinator(
            session,
            owner.tenant_id,
            clock=clock,
            debounce=debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS),
        ).claim_next()
    assert claim is not None, "the coordinator had no due operation to claim"
    return claim


def a_dispatch(context: WorkerContext, owner: UserRecord, clock: Ticking) -> SolveDispatch:
    return SolveDispatch(
        context.database,
        owner.tenant_id,
        clock=clock,
        debounce=debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS),
    )


async def run_the_commit_transaction(
    sessions: async_sessionmaker[AsyncSession],
    context: WorkerContext,
    owner: UserRecord,
    clock: Ticking,
    monkeypatch: pytest.MonkeyPatch,
    *,
    second_solver: Callable[..., SolveResult],
) -> UUID:
    """One fill solve to give the week a plan, then one moving solve with ``second_solver``.

    The first solve's candidate asks for no assent, so it appends the revision and leaves the slot
    empty; the second moves the block it placed, which replaces the slot -- and the slot's verdict
    column is what this whole suite reads back. Answered with the task id, which is the target the
    offers name.
    """
    task_id = await declare_a_task_week(sessions, owner.tenant_id)
    await bump(sessions, owner, clock)
    dispatch = a_dispatch(context, owner, clock)
    monkeypatch.setattr("syncr_api.solving.dispatch.solve", _placing_one_block)
    await request_a_solve(sessions, owner, clock)
    first = await dispatch.run(await claimed(sessions, owner, clock), WEEK)
    assert first.status == SUCCEEDED, "the fill solve did not land, so there is nothing to move"
    monkeypatch.setattr("syncr_api.solving.dispatch.solve", second_solver)
    await request_a_solve(sessions, owner, clock)
    second = await dispatch.run(await claimed(sessions, owner, clock), WEEK)
    assert second.status == SUCCEEDED, "the moving solve did not land, so the slot holds nothing"
    return task_id


def _an_unpackable_verdict(inputs: SolveInputs) -> Verdict:
    """What a completed attempt proves when the chunk would not go in: the named packing failure.

    Stamped from ``inputs`` the way the real solver stamps its own verdict, so the stored document
    names the version the write was guarded on.
    """
    return Verdict(
        feasible=False,
        provenance=Provenance.SOLVER,
        computed_at=inputs.now,
        input_version=inputs.input_version,
        discretionary_minutes=6000,
        shortfalls=(
            minimum_chunk_shortfall(
                minutes=GAP_MINUTES,
                chunk_minutes=CHUNK_MINUTES,
                against=(TASK_TITLE,),
                deadline=DEADLINE,
            ),
        ),
    )


def _solving_and_leaving_unpackable(
    inputs: SolveInputs, _weights: Any, **_asked: Any
) -> SolveResult:
    """The block moved past assent, beside a verdict whose only gap is the packing failure."""
    return SolveResult(
        document=_one_block_at(inputs, MOVED_HOUR),
        objective_breakdown=_NO_COST,
        verdict=_an_unpackable_verdict(inputs),
        blocked_log=(),
        iterations=1,
    )


def _moving_and_feasible(inputs: SolveInputs, _weights: Any, **_asked: Any) -> SolveResult:
    """The same move, beside a verdict that found nothing wrong: the control's solver."""
    return SolveResult(
        document=_one_block_at(inputs, MOVED_HOUR),
        objective_breakdown=_NO_COST,
        verdict=Verdict(
            feasible=True,
            provenance=Provenance.SOLVER,
            computed_at=inputs.now,
            input_version=inputs.input_version,
            discretionary_minutes=6000,
        ),
        blocked_log=(),
        iterations=1,
    )


def read_the_week(http: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    answered = http.get(f"{WEEKS_PREFIX}/{WEEK}", headers=headers)
    assert answered.status_code == HTTPStatus.OK, answered.text
    return cast("dict[str, Any]", answered.json())


def the_drop_offer(verdict: dict[str, Any]) -> dict[str, Any]:
    """The take-the-task-out remedy among those the read served, if any."""
    found = [
        one
        for one in verdict["tradeoffs"]
        if one["kind"] == "drop_item" and TASK_TITLE in one["label"]
    ]
    return found[0] if found else {}


class TestACommitTimeEnumerationFrozenInTheSlot:
    async def test_a_packing_failure_serves_its_remedy_through_the_week_read(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owners: Callable[[], Awaitable[UserRecord]],
        clock: Ticking,
        http: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        owner = await owners()
        task_id = await run_the_commit_transaction(
            sessions,
            context,
            owner,
            clock,
            monkeypatch,
            second_solver=_solving_and_leaving_unpackable,
        )

        served = read_the_week(http, sign_in(http, owner.email))["verdict"]

        assert served["provenance"] == "solver"
        assert any(gap["kind"] == "minimum_chunk_unplaceable" for gap in served["shortfalls"]), (
            f"the fixture gap is missing from {served['shortfalls']}"
        )
        offer = the_drop_offer(served)
        assert offer, "a gap with no remedy is a refusal without a way out"
        assert UUID(offer["targetId"]) == task_id
        assert offer["deltaMinutes"] == GAP_MINUTES

    async def test_the_served_figures_do_not_move_while_the_slot_is_current(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owners: Callable[[], Awaitable[UserRecord]],
        clock: Ticking,
        http: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The anti-freshness half: the figures were measured once, at the commit.

        The task shrinks underneath the slot by a direct repository write, which bumps no version,
        so the slot stays current and the read keeps serving the slot's own verdict. A fresh
        enumeration over the mutated week WOULD recover less -- asserted beside, so the test cannot
        pass on a mutation that never moved anything.
        """
        owner = await owners()
        task_id = await run_the_commit_transaction(
            sessions,
            context,
            owner,
            clock,
            monkeypatch,
            second_solver=_solving_and_leaving_unpackable,
        )
        headers = sign_in(http, owner.email)
        before = the_drop_offer(read_the_week(http, headers)["verdict"])
        assert before["deltaMinutes"] == GAP_MINUTES

        async with sessions() as session, session.begin():
            tasks = TaskRepository(session, owner.tenant_id)
            held = await tasks.find(task_id)
            assert held is not None, "the task this week was declared with is gone"
            await tasks.write(
                task_id,
                project_id=held.project_id,
                title=held.title,
                estimate_minutes=MUTATED_ESTIMATE_MINUTES,
                deadline=held.deadline,
                priority=held.priority,
                min_chunk_minutes=held.min_chunk_minutes,
                splittable=held.splittable,
            )
        async with sessions() as session:
            assembler = build_week_assembler(
                session, owner.tenant_id, caller=AssemblyCaller.REQUEST
            )
            inputs = await assembler.assemble(WEEK, NOW)
        fresh = offered_tradeoffs(inputs, _an_unpackable_verdict(inputs))
        moved = next(one for one in fresh if one.tradeoff.kind.value == "drop_item")
        assert moved.recovers != GAP_MINUTES, (
            "the mutation left the figure where it was, so the assertion below proves nothing"
        )

        after = the_drop_offer(read_the_week(http, headers)["verdict"])

        assert after == before

    async def test_a_feasible_week_serves_no_tradeoffs(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owners: Callable[[], Awaitable[UserRecord]],
        clock: Ticking,
        http: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        owner = await owners()

        await run_the_commit_transaction(
            sessions, context, owner, clock, monkeypatch, second_solver=_moving_and_feasible
        )

        served = read_the_week(http, sign_in(http, owner.email))["verdict"]

        assert served["provenance"] == "solver"
        assert served["shortfalls"] == []
        assert served["tradeoffs"] == []
