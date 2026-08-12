"""The approve route through the real app: the demanded key, the replay, and the two refusals.

Four things only this tier can assert.

**The key is DEMANDED rather than offered**, which no other route in this api does. A request
without one is refused before anything is read, because approving twice would append two revisions
to a table with no update and no delete path.

**A retry with the same key replays the stored response** and appends nothing, which is what the
demand is for.

**The wire shape**, in camelCase, carrying both versions: what the week holds now and what the
approved plan was solved against.

**The 409 a client renders as "this proposal has been replaced"**, with the refresh action beside
it.

The last test in this module covers the collision this route's shape is exposed to: bodyless,
addressed by a path parameter, so the week it names reaches the guard through the request hash and
nothing else.
"""

from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.approvals.config import APPROVE_PATH
from syncr_api.concessions.config import ISO_WEEK_FIELD, WEEKS_PREFIX
from syncr_api.core.app_factory import create_app
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.errors import Conflict, MalformedRequest, ValidationFailed
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS
from syncr_api.idempotency.config import IDEMPOTENCY_KEY_HEADER
from syncr_api.plans.candidates import as_document
from syncr_api.plans.models import PlanRevision
from syncr_api.plans.proposals import PendingProposalRepository
from syncr_api.plans.stored_documents import stored_document
from syncr_domain.plan import AdjustmentKind
from syncr_domain.weeks import IsoWeek
from syncr_solver.inputs import WeekAdjustment
from tests.boundaries import api_routes, route_identity
from tests.live_tenants import PASSWORD, provision_owner, remove_tenant, run
from tests.plan_documents import a_document

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings
    from syncr_domain.identifiers import TenantId

pytestmark = pytest.mark.integration

# Far enough ahead that nothing in the week has been reached under the real clock, which is what the
# route reads: the past rules compare the document against the plan of record as of now.
WEEK = IsoWeek(2030, 7)
NEXT_WEEK = IsoWeek(2030, 8)
SEEDED_AT = datetime(2030, 2, 4, tzinfo=UTC)
BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]

BREAKDOWN: dict[str, Any] = {"deadline_risk": 0.0, "budget_deviation": 0.0}
A_VERDICT: dict[str, Any] = {"feasible": True, "shortfall_minutes": 0, "provenance": "solver"}
# What the breach the tradeoff slot carries concedes, so the history's figure is checked against the
# one the candidate stated rather than against a literal written twice.
BREACH_MINUTES = 80


def approve_url(week: IsoWeek) -> str:
    return f"{WEEKS_PREFIX}{APPROVE_PATH}".replace("{iso_week}", str(week))


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
def signed_in(http: TestClient, owner: UserRecord) -> dict[str, str]:
    answered = http.post(
        f"{AUTH_PREFIX}/login",
        json={"email": owner.email, "password": PASSWORD},
        headers={"Origin": BROWSER_ORIGIN},
    )
    assert answered.status_code == HTTPStatus.OK, answered.text
    cookie = answered.headers["set-cookie"]
    token = cookie.split(f"{SESSION_COOKIE_NAME}=", 1)[1].split(";", 1)[0]
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}", "Origin": BROWSER_ORIGIN}


def seed_slot(
    database_url: str,
    tenant_id: TenantId,
    week: IsoWeek = WEEK,
    *,
    conceded: UUID | None = None,
) -> None:
    """One proposal awaiting assent, on its own loop and engine as a sync test must.

    ``conceded`` makes it a tradeoff proposal: the candidate rides in the slot and the document
    names the identifier it was solved under, which is the pair the worker writes.
    """
    document = a_document(week=week, adjustments=() if conceded is None else (conceded,))
    candidate = (
        None
        if conceded is None
        else as_document(
            WeekAdjustment(
                adjustment_id=conceded,
                kind=AdjustmentKind.BREACH_FLOOR,
                target_id=uuid4(),
                reductions={},
                delta_minutes=BREACH_MINUTES,
            )
        )
    )

    async def seed() -> None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                await PendingProposalRepository(session, tenant_id).replace(
                    document=stored_document(document),
                    proposal_diff={"added": [], "removed": [], "moved": []},
                    objective_breakdown=BREAKDOWN,
                    verdict=A_VERDICT,
                    weight_set_version=1,
                    input_version=3,
                    operation_id=uuid4(),
                    created_at=SEEDED_AT,
                    candidate_adjustment=candidate,
                )
        finally:
            await database.engine.dispose()

    run(seed())


def approved_revisions(database_url: str, tenant_id: TenantId) -> list[str]:
    """Every revision this tenant holds, as ``week/status`` pairs, oldest first."""

    async def read() -> list[str]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                found = await session.scalars(
                    select(PlanRevision)
                    .where(PlanRevision.tenant_id == tenant_id)
                    .order_by(PlanRevision.created_at, PlanRevision.id)
                )
                return [f"{row.iso_week}/{row.status}" for row in found]
        finally:
            await database.engine.dispose()

    return run(read())


def post_approval(
    http: TestClient, headers: dict[str, str], week: IsoWeek = WEEK, *, key: str | None
) -> tuple[int, dict[str, Any]]:
    sent = dict(headers) if key is None else {**headers, IDEMPOTENCY_KEY_HEADER: key}
    answered = http.post(approve_url(week), headers=sent)
    return answered.status_code, answered.json()


class TestTheApproveRoute:
    def test_approving_answers_with_what_the_transaction_wrote(
        self, http: TestClient, owner: UserRecord, signed_in: dict[str, str], live_database_url: str
    ) -> None:
        seed_slot(live_database_url, owner.tenant_id)

        status, body = post_approval(http, signed_in, key=uuid4().hex)

        assert status == HTTPStatus.CREATED, body
        assert body["isoWeek"] == str(WEEK)
        assert body["reason"] == "user_approved"
        assert body["adjustment"] is None
        assert body["projection"]["kind"] == "projection"
        # Both versions on the wire: the version the week holds now, and the solved-against one.
        assert body["solvedAgainstVersion"] == 3
        assert body["inputVersion"] == 1
        assert body["approvedAt"]
        assert body["revisionId"]
        assert approved_revisions(live_database_url, owner.tenant_id) == [f"{WEEK}/approved"]

    def test_an_approval_without_a_key_is_refused_before_anything_is_read(
        self, http: TestClient, owner: UserRecord, signed_in: dict[str, str], live_database_url: str
    ) -> None:
        # The route that DEMANDS the header rather than offering it. Nothing is appended, so the
        # proposal is still there to approve with a key.
        seed_slot(live_database_url, owner.tenant_id)

        status, refused = post_approval(http, signed_in, key=None)

        assert status == MalformedRequest.status
        assert IDEMPOTENCY_KEY_HEADER in refused["detail"]
        assert approved_revisions(live_database_url, owner.tenant_id) == []

    def test_a_retry_with_the_same_key_replays_the_answer_and_appends_nothing(
        self, http: TestClient, owner: UserRecord, signed_in: dict[str, str], live_database_url: str
    ) -> None:
        # Why the key is demanded: the slot is cleared by the first approval, so a retry without the
        # guarantee would be answered 409 by a client that has no way to tell "already done" from
        # "someone replaced your proposal". With it, the retry is answered with the first response.
        seed_slot(live_database_url, owner.tenant_id)
        key = uuid4().hex

        first = post_approval(http, signed_in, key=key)
        second = post_approval(http, signed_in, key=key)

        assert first[0] == HTTPStatus.CREATED, first[1]
        assert second == first
        assert approved_revisions(live_database_url, owner.tenant_id) == [f"{WEEK}/approved"]

    def test_approving_a_slot_that_has_been_replaced_is_a_conflict_with_a_refresh_in_it(
        self, http: TestClient, owner: UserRecord, signed_in: dict[str, str], live_database_url: str
    ) -> None:
        # What the client renders as "this proposal has been replaced" with a refresh action: the
        # detail names re-reading the week as the thing that still works.
        seed_slot(live_database_url, owner.tenant_id)
        post_approval(http, signed_in, key=uuid4().hex)

        status, refused = post_approval(http, signed_in, key=uuid4().hex)

        assert status == Conflict.status
        assert "has been replaced" in refused["detail"]
        assert "reading the week again" in refused["detail"]

    def test_a_week_identifier_the_domain_does_not_parse_is_a_422_naming_the_field(
        self, http: TestClient, signed_in: dict[str, str]
    ) -> None:
        # The field is read from where the week routes settled its spelling rather than written out,
        # so seven routes that name one parameter cannot come to name it two ways.
        answered = http.post(
            f"{WEEKS_PREFIX}/2026-W99/approve",
            headers={**signed_in, IDEMPOTENCY_KEY_HEADER: uuid4().hex},
        )

        assert answered.status_code == ValidationFailed.status
        assert answered.json()["errors"][0]["field"] == ISO_WEEK_FIELD

    def test_the_app_answers_exactly_one_approve_route(self, settings: ServiceSettings) -> None:
        """The Week screen, the weekly session and the keyboard all approve through one endpoint.

        Three callers, one endpoint, and what this asserts is the half they depend on: there
        is one route, so three callers cannot come to mean three slightly different acts. Read off
        the app's own route table rather than from a list.
        """
        approving = sorted(
            f"{method} {path}"
            for route in api_routes(create_app(settings))
            for method, path in route_identity(route)
            if path.endswith("/approve")
        )

        assert approving == [f"POST {WEEKS_PREFIX}/{{iso_week}}/approve"]

    def test_the_history_names_the_concession_the_approved_plan_was_solved_under(
        self, http: TestClient, owner: UserRecord, signed_in: dict[str, str], live_database_url: str
    ) -> None:
        """The history names the concession, end to end over both routes.

        The document the worker produced records the concessions it was solved under by identifier,
        the approval persists the row under that identifier, and the history pairs the two. A week
        that absorbed a concession must not read as simply feasible, and this is where a reader sees
        which one it was and when they approved it.
        """
        conceded = uuid4()
        seed_slot(live_database_url, owner.tenant_id, conceded=conceded)

        approved = post_approval(http, signed_in, key=uuid4().hex)
        history = http.get(f"{WEEKS_PREFIX}/{WEEK}/revisions", headers=signed_in)

        assert approved[0] == HTTPStatus.CREATED, approved[1]
        assert history.status_code == HTTPStatus.OK, history.text
        listed = history.json()["revisions"]
        assert len(listed) == 1
        assert listed[0]["status"] == "approved"
        assert listed[0]["reason"] == "tradeoff_approved"
        assert listed[0]["approvedAt"] == approved[1]["approvedAt"]
        assert [one["id"] for one in listed[0]["adjustments"]] == [str(conceded)]
        assert listed[0]["adjustments"][0]["kind"] == "breach_floor"
        assert listed[0]["adjustments"][0]["deltaMinutes"] == BREACH_MINUTES
        assert listed[0]["revokedAdjustments"] == 0
        assert listed[0]["replacedAdjustments"] == 0
        assert listed[0]["autoApplied"] == []
        assert history.json()["truncated"] is False


def test_one_key_across_two_weeks_does_not_silently_skip_the_second(
    http: TestClient, owner: UserRecord, signed_in: dict[str, str], live_database_url: str
) -> None:
    # Approving is bodyless and names its week in the path, so the week is carried by the request
    # hash alone: a claim is keyed by the tenant, the handler and the key. Two weeks under one key
    # are one key used for two different requests, which is a 422, and the second week's proposal
    # stays pending for the caller to approve under a key of its own.
    seed_slot(live_database_url, owner.tenant_id, WEEK)
    seed_slot(live_database_url, owner.tenant_id, NEXT_WEEK)
    key = uuid4().hex

    first_status, first = post_approval(http, signed_in, WEEK, key=key)
    second_status, _ = post_approval(http, signed_in, NEXT_WEEK, key=key)

    assert first_status == HTTPStatus.CREATED, first
    assert first["isoWeek"] == str(WEEK)
    assert second_status == ValidationFailed.status
    assert approved_revisions(live_database_url, owner.tenant_id) == [f"{WEEK}/approved"]
