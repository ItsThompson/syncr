"""The three concession routes end to end, against a real Postgres and a real request.

The enumeration suite proves what is offered and the folding suite proves what an approval changes.
This proves what only a real request and a real database can:

*Requesting persists nothing.* WA2, asserted by reading the concession table after a request that
answered 202. The candidate rides on the operation instead, which is the only object that crosses
from the request to the worker.

*A concession the week does not offer is refused.* The figures come from the enumeration, so a
caller naming a target syncr offered nothing for gets a 422 rather than a concession nobody
computed.

*A week holding nothing a solve placed is refused before a solve is asked for.* A concession is an
agreement to give something up, and such a week holds nothing the product chose to give up, so the
candidate would fill empty space and be adopted as the plan of record with no row recording that
anything had been conceded. Every request case therefore drives a week whose plan of record holds
one block a solve placed: the state the route exists to serve.

*A request never joins a pending solve.* A pin made two seconds earlier would absorb it and the
proposal would look as though syncr ignored the user, so the pending operation is superseded and the
replacement carries the candidate. The single-flight invariant still holds afterwards: exactly one
non-terminal solve for the week.

*Revoking does all three things WA8 asks for.* The row goes, the week's input version moves, and a
plan without the concession is asked for.

The week is a FUTURE one, because capacity starts at ``now`` and a request path reads the real
clock: a past week has no capacity for a floor to be short of. The gap is built from a real off-plan
declaration and a real Area floor, so the offer this suite requests is one the product computed.

The cookie is replayed by setting the header rather than through a cookie jar: the cookie is
``Secure``, and an HTTP client that honors that attribute will not send it back over
``http://testserver``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.areas.config import AREAS_PREFIX
from syncr_api.concessions.config import WEEKS_PREFIX
from syncr_api.core.app_factory import create_app
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS
from syncr_api.offplan.config import OFF_PLAN_PREFIX
from syncr_api.plans.adjustments import WeekAdjustmentRepository
from syncr_api.plans.candidates import KIND, REDUCTIONS, TARGET_ID
from syncr_api.plans.proposals import PendingProposalRepository
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_documents import stored_document
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.config import PENDING, SOLVE, SUPERSEDED
from syncr_api.solving.lifecycle import OperationLifecycle
from syncr_api.solving.repository import OperationRepository
from syncr_domain.identity import Origin, is_placed_by_the_solver
from syncr_domain.intervals import Interval
from syncr_domain.plan import AdjustmentKind
from syncr_domain.weeks import IsoWeek
from tests.live_tenants import PASSWORD, provision_owner, remove_tenant, run
from tests.live_weeks import produce_a_plan, seed_a_weight_set
from tests.plan_documents import a_block, a_document

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings
    from syncr_api.plans.records import PlanRevisionRecord, WeekAdjustmentRecord
    from syncr_api.solving.records import OperationRecord
    from syncr_domain.identifiers import TenantId

pytestmark = pytest.mark.integration

BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]

# Far enough ahead that the whole week is future capacity whenever this suite runs, and near enough
# that it is a week the product would really plan.
WEEK = IsoWeek.containing(datetime.now(UTC).date() + timedelta(days=60))
MONDAY = WEEK.monday()

# Six hours of the week left on plan, from Monday midnight UTC, and everything after it declared
# off. A seven-hour floor against six hours of capacity is short by exactly an hour, which is the
# figure the offer this suite requests states.
ON_PLAN_HOURS = 6
FLOOR_HOURS = 7
GAP_MINUTES = 60

TRADEOFFS = f"{WEEKS_PREFIX}/{WEEK}/tradeoffs"
ADJUSTMENTS = f"{WEEKS_PREFIX}/{WEEK}/adjustments"

# Where the block a solve placed sits in the week the request cases drive. Thursday morning, which
# this fixture has declared off plan, so the block takes no capacity the Fitness floor competes for
# and the offer states the same figures with it as without it. Its Area is a second declared one
# with no floor of its own, for the same reason: attributing it to Fitness would net 60 minutes off
# that floor's reservation and close the very gap these cases request a concession for.
PLACED_DAY = 3
PLACED_FROM_HOUR = 10


def instant(*, days: int = 0, hours: int = 0) -> str:
    """A wall instant inside the week, as the wire spells one. The tenant's zone is UTC."""
    at = datetime(MONDAY.year, MONDAY.month, MONDAY.day, tzinfo=UTC) + timedelta(
        days=days, hours=hours
    )
    return at.isoformat().replace("+00:00", "Z")


@pytest.fixture
def owner(live_database_url: str) -> Iterator[UserRecord]:
    account = provision_owner(live_database_url)
    yield account
    remove_tenant(live_database_url, account.tenant_id)


@pytest.fixture
def other_owner(live_database_url: str) -> Iterator[UserRecord]:
    account = provision_owner(live_database_url)
    yield account
    remove_tenant(live_database_url, account.tenant_id)


@pytest.fixture
def http(live_database_url: str, settings: ServiceSettings) -> Iterator[TestClient]:
    """A client against an app wired to the live database, as the process wires it."""
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


@pytest.fixture
def a_short_week(http: TestClient, owner: UserRecord) -> tuple[dict[str, str], str]:
    """A signed-in tenant whose week is an hour short of its own Fitness floor.

    Built through the routes rather than seeded, so the offer this suite requests is one the product
    computed from a declaration a user could have made.
    """
    headers = sign_in(http, owner.email)
    declared = http.post(
        OFF_PLAN_PREFIX,
        json={"start": instant(hours=ON_PLAN_HOURS), "end": instant(days=7), "keepFrame": False},
        headers=headers,
    )
    assert declared.status_code == HTTPStatus.CREATED, declared.text
    area = http.post(
        AREAS_PREFIX,
        json={"name": "Fitness", "floorHours": FLOOR_HOURS},
        headers=headers,
    )
    assert area.status_code == HTTPStatus.CREATED, area.text
    return headers, area.json()["area"]["id"]


@pytest.fixture
def a_short_solved_week(
    http: TestClient,
    owner: UserRecord,
    live_database_url: str,
    a_short_week: tuple[dict[str, str], str],
) -> tuple[dict[str, str], str]:
    """The same short week, with a plan of record holding one block a solve placed.

    Every request case needs one, because a week whose plan holds nothing a solve placed is refused
    before the offer is read: there is nothing the product chose that a concession could give up.
    The block is placed where it changes no figure the offer states, which the candidate's own
    ``deltaMinutes`` assertion below is the measurement of.
    """
    headers, area_id = a_short_week
    append_a_solved_revision(http, headers, live_database_url, owner.tenant_id)
    return headers, area_id


def append_a_solved_revision(
    http: TestClient, headers: dict[str, str], database_url: str, tenant_id: TenantId
) -> None:
    """One applied revision holding a single block a solve chose the placement of.

    Appended through the repository a solve appends through, because no route produces a plan: the
    horizon maintainer and the solve worker are the two writers and neither is reachable from a
    request.
    """
    elsewhere = http.post(AREAS_PREFIX, json={"name": "Career"}, headers=headers)
    assert elsewhere.status_code == HTTPStatus.CREATED, elsewhere.text
    placed = a_block(
        Origin.HABIT,
        week=WEEK,
        interval=Interval(
            datetime.fromisoformat(instant(days=PLACED_DAY, hours=PLACED_FROM_HOUR)),
            datetime.fromisoformat(instant(days=PLACED_DAY, hours=PLACED_FROM_HOUR + 1)),
        ),
        area_id=UUID(elsewhere.json()["area"]["id"]),
    )
    assert is_placed_by_the_solver(placed.origin), "the block has to be one a solve placed"

    async def append() -> None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                await PlanRepository(session, tenant_id).append(
                    document=stored_document(a_document(week=WEEK, blocks=(placed,))),
                    objective_breakdown={},
                    status="applied",
                    reason="auto_applied_fill",
                    weight_set_version=1,
                    input_version=1,
                    created_at=datetime.now(UTC),
                )
        finally:
            await database.engine.dispose()

    run(append())


def revisions(database_url: str, tenant_id: TenantId) -> list[PlanRevisionRecord]:
    """Every revision the tenant holds for the week, newest first."""

    async def read() -> list[PlanRevisionRecord]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                return await PlanRepository(session, tenant_id).history(WEEK)
        finally:
            await database.engine.dispose()

    return run(read())


def pending_proposal(database_url: str, tenant_id: TenantId) -> object | None:
    """What the week's pending slot holds, which a refused request must leave empty."""

    async def read() -> object | None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                return await PendingProposalRepository(session, tenant_id).find(WEEK)
        finally:
            await database.engine.dispose()

    return run(read())


def request_tradeoff(
    http: TestClient, headers: dict[str, str], *, kind: str, target_id: str
) -> tuple[int, dict[str, Any]]:
    answered = http.post(TRADEOFFS, json={"kind": kind, "targetId": target_id}, headers=headers)
    return answered.status_code, answered.json()


def stored_concessions(
    database_url: str, tenant_id: TenantId, *, iso_week: IsoWeek = WEEK
) -> list[WeekAdjustmentRecord]:
    """The tenant's concessions for one week, read on a connection of this test's own.

    The week is a parameter because a test about revoking through the WRONG week has to read the
    other one: asserting the addressed week is empty would hold whether or not the row survived.
    """

    async def read() -> list[WeekAdjustmentRecord]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                return await WeekAdjustmentRepository(session, tenant_id).for_week(iso_week)
        finally:
            await database.engine.dispose()

    return run(read())


def operations(database_url: str, tenant_id: TenantId) -> list[OperationRecord]:
    """Every operation the tenant holds, newest first."""

    async def read() -> list[OperationRecord]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                return await OperationRepository(session, tenant_id).page(limit=50)
        finally:
            await database.engine.dispose()

    return run(read())


def seeded_solve(database_url: str, tenant_id: TenantId, *, running: bool) -> OperationRecord:
    """One solve of the week, pending or already claimed, as an earlier edit would have left it."""

    async def write() -> OperationRecord:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                lifecycle = OperationLifecycle(
                    OperationRepository(session, tenant_id), lambda: datetime.now(UTC)
                )
                created = await lifecycle.enqueue(kind=SOLVE, iso_week=WEEK)
                return await lifecycle.claim(created.id) if running else created
        finally:
            await database.engine.dispose()

    return run(write())


def seeded_concession(
    database_url: str, tenant_id: TenantId, *, iso_week: IsoWeek = WEEK
) -> WeekAdjustmentRecord:
    """One approved concession and a version row, as an approval would have left them."""

    async def write() -> WeekAdjustmentRecord:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                at = datetime.now(UTC)
                await WeekInputVersionRepository(session, tenant_id).bump(iso_week, at=at)
                return await WeekAdjustmentRepository(session, tenant_id).upsert(
                    iso_week=iso_week,
                    kind=AdjustmentKind.REDUCE_ROUTINE.value,
                    target_id=uuid4(),
                    reductions={iso_week.dates()[2].isoformat(): 20},
                    created_at=at,
                    created_by_operation_id=uuid4(),
                )
        finally:
            await database.engine.dispose()

    return run(write())


def current_version(database_url: str, tenant_id: TenantId) -> int | None:
    async def read() -> int | None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                return await WeekInputVersionRepository(session, tenant_id).current(WEEK)
        finally:
            await database.engine.dispose()

    return run(read())


# --------------------------------------------------------------------------------
# Requesting a tradeoff
# --------------------------------------------------------------------------------


def test_requesting_a_tradeoff_writes_no_concession_and_answers_with_an_operation(
    http: TestClient,
    owner: UserRecord,
    live_database_url: str,
    a_short_solved_week: tuple[dict[str, str], str],
) -> None:
    # WA2, read from the table rather than described: an adjustment is created only by APPROVING a
    # tradeoff. Requesting one asks for a proposal, and the plan is untouched until assent.
    headers, area_id = a_short_solved_week

    status, body = request_tradeoff(
        http, headers, kind=AdjustmentKind.BREACH_FLOOR.value, target_id=area_id
    )

    assert status == HTTPStatus.ACCEPTED, body
    assert body["kind"] == SOLVE
    assert body["status"] == PENDING
    assert body["target"]["isoWeek"] == str(WEEK)
    assert stored_concessions(live_database_url, owner.tenant_id) == []


def test_the_operation_carries_the_candidate_the_worker_folds(
    http: TestClient,
    owner: UserRecord,
    live_database_url: str,
    a_short_solved_week: tuple[dict[str, str], str],
) -> None:
    # The candidate's whole path: the assembler takes it as an argument, so it needs a channel from
    # the request to the worker and the operation is the only object that already crosses.
    headers, area_id = a_short_solved_week

    status, _ = request_tradeoff(
        http, headers, kind=AdjustmentKind.BREACH_FLOOR.value, target_id=area_id
    )

    assert status == HTTPStatus.ACCEPTED
    carried = [
        operation.candidate_adjustment
        for operation in operations(live_database_url, owner.tenant_id)
        if operation.candidate_adjustment is not None
    ]
    assert len(carried) == 1
    assert carried[0][KIND] == AdjustmentKind.BREACH_FLOOR.value
    assert carried[0][TARGET_ID] == area_id
    assert carried[0][REDUCTIONS] == {}
    assert carried[0]["deltaMinutes"] == GAP_MINUTES


def test_a_concession_the_week_does_not_offer_is_refused_and_writes_nothing(
    http: TestClient,
    owner: UserRecord,
    live_database_url: str,
    a_short_solved_week: tuple[dict[str, str], str],
) -> None:
    # The figures are the enumeration's, so a target syncr offered nothing for cannot be conceded:
    # a caller could otherwise reduce a routine below the minimum the user set.
    headers, _ = a_short_solved_week

    status, body = request_tradeoff(
        http, headers, kind=AdjustmentKind.REDUCE_ROUTINE.value, target_id=str(uuid4())
    )

    assert status == HTTPStatus.UNPROCESSABLE_ENTITY, body
    assert body["errors"][0]["field"] == "targetId"
    assert stored_concessions(live_database_url, owner.tenant_id) == []
    assert operations(live_database_url, owner.tenant_id) == []


def test_a_week_identifier_that_will_not_parse_names_the_field_it_came_from(
    http: TestClient, a_short_week: tuple[dict[str, str], str]
) -> None:
    headers, area_id = a_short_week

    answered = http.post(
        f"{WEEKS_PREFIX}/2026-W99/tradeoffs",
        json={"kind": AdjustmentKind.BREACH_FLOOR.value, "targetId": area_id},
        headers=headers,
    )

    assert answered.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, answered.text
    assert answered.json()["errors"][0]["field"] == "iso_week"


def test_a_request_supersedes_a_pending_solve_rather_than_joining_it(
    http: TestClient,
    owner: UserRecord,
    live_database_url: str,
    a_short_solved_week: tuple[dict[str, str], str],
) -> None:
    # A pin made two seconds earlier would otherwise absorb the concession, and the user would be
    # shown a proposal that does not contain it. Superseded is not a failure: it is the expected
    # outcome of editing quickly.
    headers, area_id = a_short_solved_week
    pending = seeded_solve(live_database_url, owner.tenant_id, running=False)

    status, body = request_tradeoff(
        http, headers, kind=AdjustmentKind.BREACH_FLOOR.value, target_id=area_id
    )

    assert status == HTTPStatus.ACCEPTED, body
    held = {operation.id: operation for operation in operations(live_database_url, owner.tenant_id)}
    assert held[pending.id].status == SUPERSEDED
    assert held[pending.id].candidate_adjustment is None
    replacement = held[UUID(body["id"])]
    assert replacement.status == PENDING
    assert replacement.candidate_adjustment is not None
    # The single-flight invariant, after the exchange: one non-terminal solve for the week.
    assert [one.id for one in held.values() if one.status == PENDING] == [replacement.id]


def test_a_request_while_a_solve_is_running_is_refused_rather_than_absorbed(
    http: TestClient,
    owner: UserRecord,
    live_database_url: str,
    a_short_solved_week: tuple[dict[str, str], str],
) -> None:
    # There is no second non-terminal solve to create while one runs, and joining the one that runs
    # is the one thing this route may not do. So it refuses, names what still works, and leaves the
    # running solve alone: the coordinator owns the queued alternative.
    headers, area_id = a_short_solved_week
    running = seeded_solve(live_database_url, owner.tenant_id, running=True)

    status, body = request_tradeoff(
        http, headers, kind=AdjustmentKind.BREACH_FLOOR.value, target_id=area_id
    )

    assert status == HTTPStatus.CONFLICT, body
    assert "already running" in body["detail"]
    held = operations(live_database_url, owner.tenant_id)
    assert [one.id for one in held] == [running.id]
    assert held[0].candidate_adjustment is None
    assert stored_concessions(live_database_url, owner.tenant_id) == []


def test_a_signed_out_caller_cannot_request_a_tradeoff(http: TestClient) -> None:
    answered = http.post(
        TRADEOFFS,
        json={"kind": AdjustmentKind.BREACH_FLOOR.value, "targetId": str(uuid4())},
        headers={"Origin": BROWSER_ORIGIN},
    )

    assert answered.status_code == HTTPStatus.UNAUTHORIZED, answered.text


# --------------------------------------------------------------------------------
# A week with no solve to concede against
# --------------------------------------------------------------------------------


def test_a_tradeoff_on_a_week_with_no_plan_at_all_is_refused_and_creates_no_operation(
    http: TestClient,
    owner: UserRecord,
    live_database_url: str,
    a_short_week: tuple[dict[str, str], str],
) -> None:
    # The week this fixture builds holds a real gap and offers two real concessions, so what is
    # refused here is a request the enumeration would have honoured. The refusal is about the state
    # of the week: there is no plan, so nothing was chosen that conceding could give up.
    headers, area_id = a_short_week

    status, body = request_tradeoff(
        http, headers, kind=AdjustmentKind.BREACH_FLOOR.value, target_id=area_id
    )

    assert status == HTTPStatus.CONFLICT, body
    assert "no solve to concede against" in body["detail"]
    assert "Nothing was changed" in body["detail"]
    assert "solve the week first" in body["detail"]
    assert operations(live_database_url, owner.tenant_id) == []


def test_a_tradeoff_on_a_materialized_week_is_refused_because_a_solve_chose_none_of_it(
    http: TestClient,
    owner: UserRecord,
    live_database_url: str,
    a_short_week: tuple[dict[str, str], str],
) -> None:
    # The state the refusal is really about, and the one a reader of the week screen is in: the
    # horizon maintainer has produced a plan, so the week HOLDS one, and every block in it restates
    # something its own source fixed. A guard keyed to the absence of a revision would permit here.
    headers, area_id = a_short_week
    seed_a_weight_set(live_database_url, owner.tenant_id)
    produce_a_plan(live_database_url, owner.tenant_id, WEEK)
    materialized = revisions(live_database_url, owner.tenant_id)
    assert [one.reason for one in materialized] == ["horizon_advanced"]

    status, body = request_tradeoff(
        http, headers, kind=AdjustmentKind.BREACH_FLOOR.value, target_id=area_id
    )

    assert status == HTTPStatus.CONFLICT, body
    assert "no solve to concede against" in body["detail"]
    # The wire vocabulary a caller that has to exit with a number keys on. `syncr:conflict` is the
    # type `cli/src/syncr_cli/problems.py` maps to `ExitCode.CONFLICT`, code 6, and it maps by TYPE
    # before it falls back to the status, so a refusal minting a type of its own would reach an
    # agent as whatever 409 alone justifies.
    assert body["type"] == "syncr:conflict"
    assert body["status"] == HTTPStatus.CONFLICT
    assert [one.id for one in revisions(live_database_url, owner.tenant_id)] == [materialized[0].id]
    assert stored_concessions(live_database_url, owner.tenant_id) == []
    assert pending_proposal(live_database_url, owner.tenant_id) is None
    # No solve, which is what makes this a refusal rather than a solve nobody asked for: the guard
    # is raised before the coordinator is reached, so there is no row for a caller to follow and
    # none for the worker to claim and adopt. The two rows the materialization left are its own.
    created = operations(live_database_url, owner.tenant_id)
    assert [one.id for one in created if one.kind == SOLVE] == []
    assert [one.id for one in created if one.candidate_adjustment is not None] == []


def test_the_same_request_is_honoured_once_the_week_holds_a_block_a_solve_placed(
    http: TestClient,
    owner: UserRecord,
    live_database_url: str,
    a_short_solved_week: tuple[dict[str, str], str],
) -> None:
    # The other side of the guard, on one week and one request: what decides the answer is whether
    # the plan of record holds a placement the product chose, and nothing else about the week moved
    # between this case and the two above.
    headers, area_id = a_short_solved_week

    status, body = request_tradeoff(
        http, headers, kind=AdjustmentKind.BREACH_FLOOR.value, target_id=area_id
    )

    assert status == HTTPStatus.ACCEPTED, body
    assert body["kind"] == SOLVE
    carried = [
        one.candidate_adjustment
        for one in operations(live_database_url, owner.tenant_id)
        if one.candidate_adjustment is not None
    ]
    assert len(carried) == 1


def test_a_plan_holding_only_blocks_their_own_sources_placed_is_refused(
    http: TestClient,
    owner: UserRecord,
    live_database_url: str,
    a_short_week: tuple[dict[str, str], str],
) -> None:
    # The permit above is not simply always-on once a revision exists. This week holds an applied
    # revision of its own, and every block in it is a restatement of a fact outside the solve, which
    # is what a materialization produces. Parametrized over the whole half of the origin vocabulary
    # the domain marks that way, so an origin moving between the halves is caught here.
    headers, area_id = a_short_week
    restated = tuple(
        a_block(
            origin,
            week=WEEK,
            interval=Interval(
                datetime.fromisoformat(instant(days=PLACED_DAY, hours=PLACED_FROM_HOUR + offset)),
                datetime.fromisoformat(
                    instant(days=PLACED_DAY, hours=PLACED_FROM_HOUR + offset + 1)
                ),
            ),
        )
        for offset, origin in enumerate(sorted(Origin, key=str))
        if not is_placed_by_the_solver(origin)
    )
    assert len(restated) == 5, "every origin a source places, so the permit cannot be assumed"

    async def append() -> None:
        database = create_database(live_database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                await PlanRepository(session, owner.tenant_id).append(
                    document=stored_document(a_document(week=WEEK, blocks=restated)),
                    objective_breakdown={},
                    status="applied",
                    reason="materialized",
                    weight_set_version=1,
                    input_version=1,
                    created_at=datetime.now(UTC),
                )
        finally:
            await database.engine.dispose()

    run(append())

    status, body = request_tradeoff(
        http, headers, kind=AdjustmentKind.BREACH_FLOOR.value, target_id=area_id
    )

    assert status == HTTPStatus.CONFLICT, body
    assert "no solve to concede against" in body["detail"]
    assert operations(live_database_url, owner.tenant_id) == []


# --------------------------------------------------------------------------------
# Reading and revoking
# --------------------------------------------------------------------------------


def test_the_concessions_a_week_holds_are_listed_with_the_nights_they_touched(
    http: TestClient, owner: UserRecord, live_database_url: str
) -> None:
    # WA6 on the wire: a week that absorbed a concession must not read as simply feasible, so the
    # panel lists what it absorbed, and a reduction names the nights because the row stores them.
    headers = sign_in(http, owner.email)
    stored = seeded_concession(live_database_url, owner.tenant_id)

    answered = http.get(ADJUSTMENTS, headers=headers)

    assert answered.status_code == HTTPStatus.OK, answered.text
    listed = answered.json()["adjustments"]
    assert [one["id"] for one in listed] == [str(stored.id)]
    assert listed[0]["kind"] == AdjustmentKind.REDUCE_ROUTINE.value
    assert listed[0]["isoWeek"] == str(WEEK)
    assert listed[0]["reductions"] == {WEEK.dates()[2].isoformat(): 20}
    assert listed[0]["deltaMinutes"] is None


def test_revoking_a_concession_removes_it_bumps_the_version_and_asks_for_a_plan(
    http: TestClient, owner: UserRecord, live_database_url: str
) -> None:
    # WA8's three effects in one act. The bump is what makes a solve already running fail its
    # conditional write, so the plan that lands is one the week was not conceded anything for.
    headers = sign_in(http, owner.email)
    stored = seeded_concession(live_database_url, owner.tenant_id)
    before = current_version(live_database_url, owner.tenant_id)

    answered = http.delete(f"{ADJUSTMENTS}/{stored.id}", headers=headers)

    assert answered.status_code == HTTPStatus.NO_CONTENT, answered.text
    assert answered.content == b""
    assert stored_concessions(live_database_url, owner.tenant_id) == []
    assert current_version(live_database_url, owner.tenant_id) == (before or 0) + 1
    asked = operations(live_database_url, owner.tenant_id)
    assert [(one.kind, one.status) for one in asked] == [(SOLVE, PENDING)]
    assert asked[0].candidate_adjustment is None


def test_revoking_while_a_solve_runs_bumps_the_version_and_creates_no_second_solve(
    http: TestClient, owner: UserRecord, live_database_url: str
) -> None:
    # The version row is the only serialization point, and it already carries the signal: the
    # running solve's conditional append fails and its own follow-up reads the week without this
    # concession. A second solve here would race the first.
    headers = sign_in(http, owner.email)
    stored = seeded_concession(live_database_url, owner.tenant_id)
    running = seeded_solve(live_database_url, owner.tenant_id, running=True)
    before = current_version(live_database_url, owner.tenant_id)

    answered = http.delete(f"{ADJUSTMENTS}/{stored.id}", headers=headers)

    assert answered.status_code == HTTPStatus.NO_CONTENT, answered.text
    assert current_version(live_database_url, owner.tenant_id) == (before or 0) + 1
    assert [one.id for one in operations(live_database_url, owner.tenant_id)] == [running.id]


def test_a_concession_of_another_week_is_not_revocable_through_this_week(
    http: TestClient, owner: UserRecord, live_database_url: str
) -> None:
    # The path names a week and the row carries one, so the two have to agree: otherwise revoking
    # through the wrong week would remove a concession the user was not looking at.
    headers = sign_in(http, owner.email)
    elsewhere = seeded_concession(live_database_url, owner.tenant_id, iso_week=WEEK.following())

    answered = http.delete(f"{ADJUSTMENTS}/{elsewhere.id}", headers=headers)

    assert answered.status_code == HTTPStatus.NOT_FOUND, answered.text
    # Read the week the row is actually on: the addressed week holds none either way, so asserting
    # THAT would pass whether or not the revoke had deleted the other week's concession.
    surviving = stored_concessions(live_database_url, owner.tenant_id, iso_week=WEEK.following())
    assert [one.id for one in surviving] == [elsewhere.id]
    assert current_version(live_database_url, owner.tenant_id) is None


def test_another_tenants_concession_reads_as_absent_rather_than_forbidden(
    http: TestClient, owner: UserRecord, other_owner: UserRecord, live_database_url: str
) -> None:
    # Scoped reads are what make the 404 truthful: one tenant learns nothing about another's rows,
    # not even that an identifier exists.
    headers = sign_in(http, other_owner.email)
    stored = seeded_concession(live_database_url, owner.tenant_id)

    answered = http.delete(f"{ADJUSTMENTS}/{stored.id}", headers=headers)

    assert answered.status_code == HTTPStatus.NOT_FOUND, answered.text
    assert [one.id for one in stored_concessions(live_database_url, owner.tenant_id)] == [stored.id]
