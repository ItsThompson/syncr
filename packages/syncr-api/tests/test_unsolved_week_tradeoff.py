"""What a candidate-carrying solve of a week with no solve behind it does, and what it leaves.

The tradeoff route refuses such a week, so this suite is about the arm that refusal exists to close,
and about how far the refusal reaches. Both are measured against a real Postgres, a real
materialization and the worker's own dispatch, because what decides them is the authority rule over
two stored documents.

**The two arms, and both are reachable.** A week whose plan of record holds nothing a solve placed
gives the classifier a candidate that displaces nothing, so what the classifier answers depends on
whether the solve placed anything at all:

| The week | The classification | What is written |
|---|---|---|
| holds content a solve can place | fills only, an empty diff | an ``auto_applied_fill`` revision |
| holds no content to place | empty | nothing at all |

Neither arm stores a concession, and neither raises anything, so under both a caller is told its
tradeoff succeeded and the shortfall it was offered for is still there. That is what the route's
refusal answers.

**How far the refusal reaches, stated because a guard credited with more reach than it has is this
epic's most repeated defect.** The refusal is at the request, so it stops such an operation being
CREATED. It does not stop one being adopted: an operation that already carries a candidate is folded
and adopted exactly as it is below, and the coordinator carries a candidate forward onto the
follow-up of a superseded solve. What makes that unreachable in practice is that the request is the
only place a candidate enters the product, which the suite below does not prove: it drives the
coordinator directly, in the worker's own words, to measure what the worker would do.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from syncr_api.concessions import service as concession_service
from syncr_api.core.app_factory import create_app
from syncr_api.core.clock import utc_now
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.settings import DEFAULT_SOLVE_DEBOUNCE_MS, DEV_ALLOWED_ORIGINS
from syncr_api.plans.adjustments import WeekAdjustmentRepository
from syncr_api.plans.assembler import AssemblyCaller
from syncr_api.plans.authority import classify
from syncr_api.plans.candidates import as_document
from syncr_api.plans.injection import build_week_assembler
from syncr_api.plans.proposals import PendingProposalRepository
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.solved import holds_a_solver_placed_block
from syncr_api.plans.stored_documents import plan_document
from syncr_api.solving.config import SUCCEEDED
from syncr_api.solving.dispatch import SolveDispatch
from syncr_api.solving.injection import build_solve_coordinator, debounce_window
from syncr_api.tasks.config import TASKS_PREFIX
from syncr_api.templates.config import DAY_TYPES_PREFIX, TEMPLATES_PREFIX, WEEK_PATTERN_PREFIX
from syncr_domain.plan import AdjustmentKind
from syncr_domain.weeks import IsoWeek, Weekday
from syncr_solver.inputs import WeekAdjustment
from tests.live_tenants import provision_owner, remove_tenant, run
from tests.live_weeks import declare_the_minimum as declare_a_planning_minimum
from tests.live_weeks import produce_a_plan, sign_in

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings
    from syncr_api.plans.records import PlanRevisionRecord
    from syncr_api.solving.records import OperationRecord
    from syncr_domain.identifiers import TenantId
    from syncr_domain.plan import PlanDocument
    from syncr_solver.inputs import SolveInputs

pytestmark = pytest.mark.integration

BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]

# Far enough ahead that the whole week is future capacity whenever this suite runs, for the reason
# the concession route suite states: capacity starts at ``now`` and these paths read a real clock.
WEEK = IsoWeek.containing(datetime.now(UTC).date() + timedelta(days=60))

# Mid-morning, so the slot the solver fills lands clear of the sleep routine the planning minimum
# declares. A slot the frame covers is refused at materialization and nothing would be placeable.
SLOT_AT = "10:00"
SLOT_MINUTES = 60

# What the concession lowers, in the shape the request would have built. The figure is not the
# enumeration's here: nothing in this suite reads it, because what is being measured is the
# authority rule over the two documents the solve produces rather than the concession's arithmetic.
BREACH_MINUTES = 60

# The two calls whose order in the request decides whether a refused request can leave an operation
# behind. Named rather than spelled twice, because the assertion below is about the pair.
REFUSAL = "_require_a_solve_to_concede_against"
ASKING_FOR_A_SOLVE = "request_solve"


@pytest.fixture
def owner(live_database_url: str) -> Iterator[UserRecord]:
    account = provision_owner(live_database_url)
    yield account
    remove_tenant(live_database_url, account.tenant_id)


@pytest.fixture
def http(live_database_url: str, settings: ServiceSettings) -> Iterator[TestClient]:
    database = create_database(live_database_url)
    app = create_app(settings, lifespan=create_db_lifespan(database.engine))
    app.state.db = database
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def a_planning_minimum(
    http: TestClient, owner: UserRecord, live_database_url: str
) -> tuple[dict[str, str], str]:
    """A signed-in tenant that can be planned at all, and the Area it declared.

    Every case materializes the week itself, because materializing is the act one of them is about.
    """
    headers = sign_in(http, owner.email)
    area_id = declare_a_planning_minimum(http, headers, live_database_url, owner.tenant_id)
    return headers, area_id


def declare_content_a_solve_can_place(
    http: TestClient, headers: dict[str, str], area_id: str
) -> None:
    """One Area slot on every weekday and one task that fits it.

    A slot is what a solve binds content into: a week declaring none has nothing to place, whatever
    its backlog holds, so this is the difference between the suite's two cases.
    """
    day_type = http.post(DAY_TYPES_PREFIX, json={"name": "Slotted"}, headers=headers)
    assert day_type.status_code == HTTPStatus.CREATED, day_type.text
    shape = http.post(
        TEMPLATES_PREFIX,
        json={"dayTypeId": day_type.json()["id"], "name": "Slotted"},
        headers=headers,
    )
    assert shape.status_code == HTTPStatus.CREATED, shape.text
    pattern = http.put(
        WEEK_PATTERN_PREFIX,
        json={weekday.value: day_type.json()["id"] for weekday in Weekday},
        headers=headers,
    )
    assert pattern.status_code == HTTPStatus.OK, pattern.text
    slot = http.post(
        f"{TEMPLATES_PREFIX}/{shape.json()['id']}/entries",
        json={
            "kind": "slot",
            "targetTime": SLOT_AT,
            "durationMinutes": SLOT_MINUTES,
            "areaId": area_id,
        },
        headers=headers,
    )
    assert slot.status_code == HTTPStatus.CREATED, slot.text
    task = http.post(
        TASKS_PREFIX,
        json={
            "areaId": area_id,
            "title": "Long run",
            "estimateMinutes": SLOT_MINUTES,
            "minChunkMinutes": SLOT_MINUTES,
        },
        headers=headers,
    )
    assert task.status_code == HTTPStatus.CREATED, task.text


def a_candidate_concession(area_id: str) -> dict[str, object]:
    """The candidate a tradeoff request would have put on the operation, in its own spelling."""
    return as_document(
        WeekAdjustment(
            adjustment_id=uuid4(),
            kind=AdjustmentKind.BREACH_FLOOR,
            target_id=UUID(area_id),
            delta_minutes=BREACH_MINUTES,
        )
    )


def a_candidate_carrying_solve(
    database_url: str, tenant_id: TenantId, candidate: dict[str, object]
) -> OperationRecord:
    """One solve of the week carrying a concession, created the way the request creates one."""

    async def request() -> OperationRecord:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                return await build_solve_coordinator(
                    session,
                    tenant_id,
                    clock=utc_now,
                    debounce=debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS),
                ).request_solve(
                    WEEK,
                    await _tracked_version(session, tenant_id),
                    immediate=True,
                    candidate=candidate,
                )
        finally:
            await database.engine.dispose()

    return run(request())


async def _tracked_version(session: Any, tenant_id: TenantId) -> int:
    from syncr_api.plans.versions import WeekInputVersionRepository

    return await WeekInputVersionRepository(session, tenant_id).tracked_version(WEEK)


def drain_one_solve(database_url: str, tenant_id: TenantId) -> OperationRecord:
    """Claim the due solve and dispatch it, which is what one tick of the worker's duty does."""

    async def drive() -> OperationRecord:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                claim = await build_solve_coordinator(
                    session,
                    tenant_id,
                    clock=utc_now,
                    debounce=debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS),
                ).claim_next()
            assert claim is not None, "the request created no solve for the worker to claim"
            return await SolveDispatch(
                database,
                tenant_id,
                clock=utc_now,
                debounce=debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS),
            ).run(claim, WEEK)
        finally:
            await database.engine.dispose()

    return run(drive())


def revisions(database_url: str, tenant_id: TenantId) -> list[PlanRevisionRecord]:
    """The week's revisions, newest first."""

    async def read() -> list[PlanRevisionRecord]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                return await PlanRepository(session, tenant_id).history(WEEK)
        finally:
            await database.engine.dispose()

    return run(read())


def concessions(database_url: str, tenant_id: TenantId) -> list[object]:
    async def read() -> list[object]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                return list(await WeekAdjustmentRepository(session, tenant_id).for_week(WEEK))
        finally:
            await database.engine.dispose()

    return run(read())


def pending_proposal(database_url: str, tenant_id: TenantId) -> object | None:
    async def read() -> object | None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                return await PendingProposalRepository(session, tenant_id).find(WEEK)
        finally:
            await database.engine.dispose()

    return run(read())


def the_candidate_plan(
    database_url: str, tenant_id: TenantId, candidate: dict[str, object]
) -> tuple[SolveInputs, PlanDocument]:
    """The inputs a solve of this week against ``candidate`` reads, and the document it produces.

    The dispatch's own first two phases, composed from the same functions in the same order, because
    the classification the dispatch computes is not a value it answers with. The inputs come back
    with the document because the classification is decided against the instant they were stamped
    with.
    """
    from syncr_api.learned.repository import WeightSetRepository
    from syncr_api.learned.weight_reading import as_weight_set
    from syncr_api.plans.candidates import from_document
    from syncr_solver import solve

    async def read() -> Any:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                assembler = build_week_assembler(session, tenant_id, caller=AssemblyCaller.WORKER)
                inputs = await assembler.assemble(
                    WEEK, utc_now(), from_document(candidate, dates=WEEK.dates())
                )
                stored = await WeightSetRepository(session, tenant_id).active()
                assert stored is not None, "provisioning seeds one for every tenant it creates"
                return inputs, as_weight_set(stored)
        finally:
            await database.engine.dispose()

    inputs, weights = run(read())
    return inputs, solve(inputs, weights).document


class TestHowFarTheRefusalReaches:
    """Where the refusal sits, and why a behavioural case cannot say.

    A refused request rolls its own transaction back, so the operation the coordinator would have
    created is discarded whether the refusal is raised before that call or after it. Both orders
    therefore answer 409 and leave no row, and every behavioural assertion in this suite and in the
    route suite passes under either: moving the refusal past the coordinator was measured to redden
    nothing at all.

    The order still decides a reachable outcome, which is why it is asserted here rather than left
    to prose. An operation committed before its response is produced would survive the rollback, and
    a refusal raised after the coordinator would then leave a committed solve carrying a concession
    for a week that cannot be conceded against, with a caller holding its identifier.
    """

    def test_the_refusal_is_raised_before_the_coordinator_is_asked_for_a_solve(self) -> None:
        source = Path(concession_service.__file__).read_text(encoding="utf-8")
        requesting = _the_request_method(ast.parse(source))
        at = _where_each_call_is(requesting)

        assert REFUSAL in at, "the refusal is not reached from the request at all"
        assert ASKING_FOR_A_SOLVE in at
        assert at[REFUSAL] < at[ASKING_FOR_A_SOLVE], (
            "the refusal has to be raised before the solve is asked for, and no behavioural case "
            "in this suite can say so: a refused request rolls back the operation either way"
        )


def _where_each_call_is(method: ast.AsyncFunctionDef) -> dict[str, int]:
    """The first line each name is called on, by line rather than by walk order.

    ``ast.walk`` is breadth-first, so a list built from it is in no source order at all and a
    comparison over its positions cannot see one call move past another.
    """
    lines: dict[str, int] = {}
    for node in ast.walk(method):
        if not isinstance(node, ast.Call):
            continue
        name = _called_name(node.func)
        if name:
            lines[name] = min(lines.get(name, node.lineno), node.lineno)
    return lines


def _the_request_method(tree: ast.Module) -> ast.AsyncFunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "request":
            return node
    message = "the service defines no `request` method, so what this asserts has moved"
    raise AssertionError(message)


def _called_name(func: ast.expr) -> str:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


class TestAWeekWhoseContentASolveCanPlace:
    """The arm that adopts. A fill-only candidate advances the plan of record on its own."""

    def test_the_classification_is_fills_only_so_the_concession_becomes_the_plan_of_record(
        self,
        http: TestClient,
        owner: UserRecord,
        live_database_url: str,
        a_planning_minimum: tuple[dict[str, str], str],
    ) -> None:
        headers, area_id = a_planning_minimum
        declare_content_a_solve_can_place(http, headers, area_id)
        produce_a_plan(live_database_url, owner.tenant_id, WEEK)
        (materialized,) = revisions(live_database_url, owner.tenant_id)
        live = plan_document(materialized.document)
        assert not holds_a_solver_placed_block(live), "the premise: no solve has placed anything"
        candidate = a_candidate_concession(area_id)

        inputs, produced = the_candidate_plan(live_database_url, owner.tenant_id, candidate)
        classification = classify(live, produced, now=inputs.now)

        assert holds_a_solver_placed_block(produced), "the solve placed content into the slot"
        assert len(classification.auto_applicable) == 1
        assert classification.proposal_diff.is_empty()
        assert classification.applies_immediately()
        assert not classification.is_empty()

    def test_the_worker_appends_a_fill_revision_and_stores_no_concession(
        self,
        http: TestClient,
        owner: UserRecord,
        live_database_url: str,
        a_planning_minimum: tuple[dict[str, str], str],
    ) -> None:
        # The revision count is the whole point: the concession reaches the plan of record and no
        # row anywhere says the week was conceded anything, so the panel it was offered from still
        # shows the shortfall and nothing to revoke.
        headers, area_id = a_planning_minimum
        declare_content_a_solve_can_place(http, headers, area_id)
        produce_a_plan(live_database_url, owner.tenant_id, WEEK)
        before = revisions(live_database_url, owner.tenant_id)
        a_candidate_carrying_solve(
            live_database_url, owner.tenant_id, a_candidate_concession(area_id)
        )

        finished = drain_one_solve(live_database_url, owner.tenant_id)

        assert finished.status == SUCCEEDED, finished.error_message
        appended = revisions(live_database_url, owner.tenant_id)
        assert len(before) == 1
        assert len(appended) == 2
        assert appended[0].reason == "auto_applied_fill"
        assert holds_a_solver_placed_block(plan_document(appended[0].document))
        assert concessions(live_database_url, owner.tenant_id) == []
        assert pending_proposal(live_database_url, owner.tenant_id) is None


class TestAWeekWithNothingToPlace:
    """The other arm. The same request, the same refusal, and nothing written at all."""

    def test_the_classification_is_empty_and_the_worker_writes_nothing(
        self,
        owner: UserRecord,
        live_database_url: str,
        a_planning_minimum: tuple[dict[str, str], str],
    ) -> None:
        # No slot is declared, so the solve binds nothing and the candidate changes no placement.
        # The operation still reports success, which is the shape of "a mutation that succeeds and
        # changes nothing".
        _, area_id = a_planning_minimum
        produce_a_plan(live_database_url, owner.tenant_id, WEEK)
        (materialized,) = revisions(live_database_url, owner.tenant_id)
        candidate = a_candidate_concession(area_id)
        inputs, produced = the_candidate_plan(live_database_url, owner.tenant_id, candidate)
        classification = classify(plan_document(materialized.document), produced, now=inputs.now)
        assert classification.is_empty()
        a_candidate_carrying_solve(live_database_url, owner.tenant_id, candidate)

        finished = drain_one_solve(live_database_url, owner.tenant_id)

        assert finished.status == SUCCEEDED, finished.error_message
        assert [one.id for one in revisions(live_database_url, owner.tenant_id)] == [
            materialized.id
        ]
        assert concessions(live_database_url, owner.tenant_id) == []
        assert pending_proposal(live_database_url, owner.tenant_id) is None
