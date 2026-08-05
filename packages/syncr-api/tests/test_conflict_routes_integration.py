"""The two conflict routes end to end, against a real Postgres and a real request.

The resolution suite proves the rules through the service. This proves what only a real request and
the production wiring can: that the wire shape is camelCase and half-open, that the answer is
recorded once however many times the request is retried, that another tenant's identifier is a 404
rather than an answer, and that a refusal leaves the conflict open and the plan alone.

The cookie is replayed by setting the header rather than through a cookie jar: the cookie is
``Secure``, and an HTTP client that honors that attribute will not send it back over
``http://testserver``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.conflicts.config import CONFLICTS_PREFIX, RESOLVED_PARAMETER
from syncr_api.core.app_factory import create_app
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.errors import PROBLEM_JSON_MEDIA_TYPE, Conflict, NotFound, ValidationFailed
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS
from syncr_api.idempotency.config import IDEMPOTENCY_KEY_HEADER
from syncr_api.plans.config import KEPT_BOTH_RESOLUTION, MOVED_RESOLUTION, RETYPED_RESOLUTION
from syncr_api.plans.conflicts import PlanConflictRepository
from syncr_api.plans.overlaps import DetectedConflict
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_documents import stored_document
from syncr_domain.identity import BindingRef
from tests.live_tenants import PASSWORD, provision_owner, remove_tenant, run
from tests.plan_documents import WEEK, a_block_holding, a_document, between

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings
    from syncr_domain.identifiers import TenantId
    from syncr_domain.plan import Block

pytestmark = pytest.mark.integration

BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]
NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)

GYM = BindingRef.for_habit(uuid4(), index=0)
SLEEP = BindingRef.for_routine(uuid4(), on=WEEK.monday())


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


@pytest.fixture
def signed_in(http: TestClient, owner: UserRecord) -> dict[str, str]:
    return _sign_in(http, owner.email)


def _sign_in(http: TestClient, email: str) -> dict[str, str]:
    answered = http.post(
        f"{AUTH_PREFIX}/login",
        json={"email": email, "password": PASSWORD},
        headers={"Origin": BROWSER_ORIGIN},
    )
    assert answered.status_code == HTTPStatus.OK, answered.text
    cookie = answered.headers["set-cookie"]
    token = cookie.split(f"{SESSION_COOKIE_NAME}=", 1)[1].split(";", 1)[0]
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}", "Origin": BROWSER_ORIGIN}


def seed_conflict(
    database_url: str, tenant_id: TenantId, *, binding: BindingRef = GYM, block: Block | None = None
) -> str:
    """A live plan holding ``block`` and one open conflict against ``binding``, on its own loop."""

    async def seed() -> str:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                held = block if block is not None else a_block_holding(binding, between(9, 10))
                await PlanRepository(session, tenant_id).append(
                    document=stored_document(a_document(blocks=(held,))),
                    objective_breakdown={"budget_deviation": 1.0},
                    status="applied",
                    reason="auto_applied_fill",
                    weight_set_version=1,
                    input_version=1,
                    created_at=NOW,
                )
                (raised,) = await PlanConflictRepository(session, tenant_id).raise_all(
                    (
                        DetectedConflict(
                            anchor_id=uuid4(),
                            iso_week=WEEK,
                            binding=binding,
                            overlap=between(9.5, 10),
                        ),
                    ),
                    at=NOW,
                )
            return str(raised.id)
        finally:
            await database.engine.dispose()

    return run(seed())


def stored_conflicts(database_url: str, tenant_id: TenantId) -> list[Any]:
    async def read() -> list[Any]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                held = await PlanConflictRepository(session, tenant_id).list_all()
            return list(held)
        finally:
            await database.engine.dispose()

    return run(read())


def resolve(
    http: TestClient, headers: dict[str, str], conflict_id: str, **body: Any
) -> tuple[int, dict[str, Any]]:
    answered = http.post(f"{CONFLICTS_PREFIX}/{conflict_id}/resolve", json=body, headers=headers)
    return answered.status_code, answered.json()


def test_the_open_list_carries_the_pair_a_notice_renders_from(
    http: TestClient, owner: UserRecord, signed_in: dict[str, str], live_database_url: str
) -> None:
    conflict_id = seed_conflict(live_database_url, owner.tenant_id)

    answered = http.get(CONFLICTS_PREFIX, params={RESOLVED_PARAMETER: "false"}, headers=signed_in)

    assert answered.status_code == HTTPStatus.OK, answered.text
    (conflict,) = answered.json()["conflicts"]
    assert conflict["id"] == conflict_id
    assert conflict["isoWeek"] == str(WEEK)
    assert conflict["blockId"] == a_block_holding(GYM, between(9, 10)).id
    assert conflict["binding"]["kind"] == GYM.kind.value
    assert conflict["overlap"]["start"].endswith("Z")
    assert conflict["resolvedAt"] is None
    assert conflict["resolution"] is None


def test_answering_kept_both_records_it_and_asks_for_no_solve(
    http: TestClient, owner: UserRecord, signed_in: dict[str, str], live_database_url: str
) -> None:
    conflict_id = seed_conflict(live_database_url, owner.tenant_id)

    status, body = resolve(http, signed_in, conflict_id, resolution=KEPT_BOTH_RESOLUTION)

    assert status == HTTPStatus.OK, body
    assert body["conflict"]["resolution"] == KEPT_BOTH_RESOLUTION
    assert body["conflict"]["resolvedAt"] is not None
    assert body["operation"] is None


def test_answering_moved_frees_the_block_and_answers_with_the_solve_to_follow(
    http: TestClient, owner: UserRecord, signed_in: dict[str, str], live_database_url: str
) -> None:
    conflict_id = seed_conflict(live_database_url, owner.tenant_id)

    status, body = resolve(http, signed_in, conflict_id, resolution=MOVED_RESOLUTION)

    assert status == HTTPStatus.OK, body
    assert body["conflict"]["resolution"] == MOVED_RESOLUTION
    assert body["operation"]["kind"] == "solve"
    assert body["operation"]["target"]["isoWeek"] == str(WEEK)


def test_a_retried_answer_records_one_resolution_and_reads_the_same_body(
    http: TestClient, owner: UserRecord, signed_in: dict[str, str], live_database_url: str
) -> None:
    conflict_id = seed_conflict(live_database_url, owner.tenant_id)
    headers = {**signed_in, IDEMPOTENCY_KEY_HEADER: uuid4().hex}

    first = http.post(
        f"{CONFLICTS_PREFIX}/{conflict_id}/resolve",
        json={"resolution": MOVED_RESOLUTION},
        headers=headers,
    )
    retried = http.post(
        f"{CONFLICTS_PREFIX}/{conflict_id}/resolve",
        json={"resolution": MOVED_RESOLUTION},
        headers=headers,
    )

    assert first.status_code == HTTPStatus.OK, first.text
    assert retried.status_code == HTTPStatus.OK, retried.text
    assert retried.json() == first.json()
    assert [
        conflict.resolution for conflict in stored_conflicts(live_database_url, owner.tenant_id)
    ] == [MOVED_RESOLUTION]


def test_answering_twice_without_a_key_is_refused_naming_the_answer(
    http: TestClient, owner: UserRecord, signed_in: dict[str, str], live_database_url: str
) -> None:
    conflict_id = seed_conflict(live_database_url, owner.tenant_id)
    resolve(http, signed_in, conflict_id, resolution=KEPT_BOTH_RESOLUTION)

    status, body = resolve(http, signed_in, conflict_id, resolution=MOVED_RESOLUTION)

    assert status == Conflict.status
    assert body["type"] == Conflict.type
    assert KEPT_BOTH_RESOLUTION in body["detail"]


def test_moving_a_block_a_declaration_fixes_is_refused_and_leaves_it_open(
    http: TestClient, owner: UserRecord, signed_in: dict[str, str], live_database_url: str
) -> None:
    conflict_id = seed_conflict(
        live_database_url,
        owner.tenant_id,
        binding=SLEEP,
        block=a_block_holding(SLEEP, between(0, 7)),
    )

    status, body = resolve(http, signed_in, conflict_id, resolution=MOVED_RESOLUTION)

    assert status == Conflict.status
    assert body["type"] == Conflict.type
    assert "pin this occurrence somewhere else" in body["detail"]
    (held,) = stored_conflicts(live_database_url, owner.tenant_id)
    assert held.resolution is None


def test_a_retype_that_states_no_type_is_a_422_naming_the_field(
    http: TestClient, owner: UserRecord, signed_in: dict[str, str], live_database_url: str
) -> None:
    conflict_id = seed_conflict(live_database_url, owner.tenant_id)

    status, body = resolve(http, signed_in, conflict_id, resolution=RETYPED_RESOLUTION)

    assert status == ValidationFailed.status
    assert body["errors"][0]["field"] == "anchorTypeId"


def test_an_answer_that_changes_no_type_may_not_name_one(
    http: TestClient, owner: UserRecord, signed_in: dict[str, str], live_database_url: str
) -> None:
    conflict_id = seed_conflict(live_database_url, owner.tenant_id)

    status, body = resolve(
        http, signed_in, conflict_id, resolution=MOVED_RESOLUTION, anchorTypeId=None
    )

    assert status == ValidationFailed.status
    assert body["errors"][0]["field"] == "anchorTypeId"


def test_an_unknown_answer_is_the_frameworks_own_422(
    http: TestClient, owner: UserRecord, signed_in: dict[str, str], live_database_url: str
) -> None:
    conflict_id = seed_conflict(live_database_url, owner.tenant_id)

    status, body = resolve(http, signed_in, conflict_id, resolution="ignored")

    assert status == ValidationFailed.status
    assert body["type"] == ValidationFailed.type


def test_a_field_the_body_does_not_declare_is_refused(
    http: TestClient, owner: UserRecord, signed_in: dict[str, str], live_database_url: str
) -> None:
    conflict_id = seed_conflict(live_database_url, owner.tenant_id)

    status, _ = resolve(
        http, signed_in, conflict_id, resolution=KEPT_BOTH_RESOLUTION, resolvedAt="now"
    )

    assert status == ValidationFailed.status


def test_another_tenants_conflict_is_a_404_and_is_not_answered(
    http: TestClient,
    owner: UserRecord,
    other_owner: UserRecord,
    signed_in: dict[str, str],
    live_database_url: str,
) -> None:
    theirs = seed_conflict(live_database_url, other_owner.tenant_id)

    status, body = resolve(http, signed_in, theirs, resolution=MOVED_RESOLUTION)

    assert status == NotFound.status
    assert body["type"] == NotFound.type
    (held,) = stored_conflicts(live_database_url, other_owner.tenant_id)
    assert held.resolution is None


def test_the_list_is_not_readable_without_a_session(http: TestClient) -> None:
    answered = http.get(CONFLICTS_PREFIX)

    assert answered.status_code == HTTPStatus.UNAUTHORIZED
    assert answered.headers["content-type"].startswith(PROBLEM_JSON_MEDIA_TYPE)


def test_answering_from_an_untrusted_origin_is_refused(
    http: TestClient, owner: UserRecord, signed_in: dict[str, str], live_database_url: str
) -> None:
    conflict_id = seed_conflict(live_database_url, owner.tenant_id)

    answered = http.post(
        f"{CONFLICTS_PREFIX}/{conflict_id}/resolve",
        json={"resolution": KEPT_BOTH_RESOLUTION},
        headers={**signed_in, "Origin": "https://evil.example"},
    )

    assert answered.status_code == HTTPStatus.FORBIDDEN
    (held,) = stored_conflicts(live_database_url, owner.tenant_id)
    assert held.resolution is None
