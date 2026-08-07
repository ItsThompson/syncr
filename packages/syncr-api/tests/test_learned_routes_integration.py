"""The three learning routes end to end, against a real Postgres and a real request.

The service suite proves the rules. This proves what only a real request and the production wiring
can: that the three paths are the ones the acceptance criterion names, that the wire shape is
camelCase, that the two reads write nothing, that a retried activation reads the first attempt's
answer rather than queueing a second pass over every future week, that another account's version is
a 404, and that the origin check and the path validation are attached.

**It also closes the gap that let a stale frontend contract merge.** The generated document is
exported from the app the process builds, so a route registered at a path the contract does not
carry is now a red test here rather than a red `contract` job nobody ran locally.

The cookie is replayed by setting the header rather than through a cookie jar: the cookie is
``Secure``, and an HTTP client that honors that attribute will not send it back over
``http://testserver``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.core.app_factory import create_app
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS
from syncr_api.idempotency.config import IDEMPOTENCY_KEY_HEADER
from syncr_api.learned.config import (
    FITTED,
    HAND_TUNED,
    LEARNED_PREFIX,
    WEIGHT_SETS_PREFIX,
)
from syncr_api.learned.models import WeightSet
from syncr_api.learned.repository import WeightSetRepository
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_domain.weeks import IsoWeek
from tests.live_tenants import PASSWORD, provision_owner, remove_tenant, run

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings
    from syncr_domain.identifiers import TenantId

pytestmark = pytest.mark.integration

BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]
NOW = datetime(2026, 2, 16, 9, 0, tzinfo=UTC)

# The week the ACTIVATION will re-solve, resolved against the PRODUCTION clock rather than against
# `NOW`. The routes are wired with `utc_now`, and the re-solve floor is the week holding today's
# local date: a week seeded against a fixed instant would be in the past by the time the route ran,
# and the test would then assert that a future-weeks-only rule excluded a past week, which it does
# anyway.
TRACKED_WEEK = IsoWeek.containing(datetime.now(UTC).date())

ACTIVATE_PATH = f"{WEIGHT_SETS_PREFIX}/2/activate"

# The committed contract, resolved from this file rather than from the working directory, so the
# check finds it whichever directory pytest was started from.
CONTRACT = Path(__file__).resolve().parents[3] / "frontend" / "openapi.json"

A_READY_ROW = {
    "parameter": "duration_multiplier[11111111-1111-4111-8111-111111111111]",
    "samples": 14,
    "threshold": 12,
    "state": "ready",
    "value": 1.37,
    "shrinkage_weight": 0.42,
    "plain_language": "You estimate 60m for Fitness; your actual median is 82m.",
}


@pytest.fixture
def owner(live_database_url: str) -> Iterator[UserRecord]:
    account = provision_owner(live_database_url)
    _seed_versions(live_database_url, account.tenant_id)
    yield account
    remove_tenant(live_database_url, account.tenant_id)


@pytest.fixture
def other_owner(live_database_url: str) -> Iterator[UserRecord]:
    account = provision_owner(live_database_url)
    _seed_versions(live_database_url, account.tenant_id)
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


def _seed_versions(database_url: str, tenant_id: TenantId) -> None:
    """Version 1 hand-tuned and active, version 2 fitted and not, plus a tracked future week."""

    async def seed() -> None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                await WeightSetRepository(session, tenant_id).seed_hand_tuned(at=NOW)
                session.add(
                    WeightSet(
                        tenant_id=tenant_id,
                        version=2,
                        active=False,
                        origin=FITTED,
                        deadline_risk=9.0,
                        budget_deviation=3.0,
                        time_of_day_misfit=2.0,
                        fragmentation=1.5,
                        churn=4.0,
                        context_switch=1.0,
                        staleness=1.5,
                        duration_multiplier={},
                        time_of_day_fitness={},
                        skip_probability={},
                        context_switch_cost=2.5,
                        churn_tolerance=5.0,
                        fitted_at=NOW,
                        maturity=[A_READY_ROW],
                        created_at=NOW,
                    )
                )
                await WeekInputVersionRepository(session, tenant_id).bump(TRACKED_WEEK, at=NOW)
        finally:
            await database.engine.dispose()

    run(seed())


class TestTheThreePathsAreTheOnesTheCriterionNames:
    def test_the_app_registers_all_three(self, settings: ServiceSettings) -> None:
        document = create_app(settings).openapi()

        assert LEARNED_PREFIX in document["paths"]
        assert WEIGHT_SETS_PREFIX in document["paths"]
        assert f"{WEIGHT_SETS_PREFIX}/{{version}}/activate" in document["paths"]
        assert {
            "LearnedResponse",
            "WeightSetsResponse",
            "ActivatedResponse",
            "ParameterResponse",
            "WeightSetResponse",
        } <= set(document["components"]["schemas"])

    def test_the_committed_contract_carries_every_path_and_schema_the_app_declares(
        self, settings: ServiceSettings
    ) -> None:
        """The gap that let a stale frontend contract merge, closed where a developer will see it.

        The `contract` CI job regenerates `frontend/openapi.json` and fails on a diff, and it was
        the only thing that could see a route the contract does not carry. It is in no local gate
        list, so a backend change that adds a route goes red in CI and green everywhere a developer
        looks.

        **Paths AND schema names, because paths alone miss the likelier drift.** Once the three
        routes exist, the next staleness is a changed response model on an existing path rather than
        a new path, and a path-only comparison cannot see one: measured, dropping
        `ParameterResponse` from the committed document leaves a path-only check green.

        Compared as two SETS rather than byte for byte: byte equality is the `contract` job's own
        job, and doing it here would redden on a sibling's unrelated regeneration, which is a red
        test that teaches nothing. What matters is that nothing the app declares is absent.
        """
        declared = create_app(settings).openapi()
        committed = json.loads(CONTRACT.read_text(encoding="utf-8"))
        hint = (
            "the committed frontend contract is missing something the app declares. "
            "Run `just contract` and commit frontend/openapi.json with schema.d.ts."
        )

        assert set(declared["paths"]) - set(committed["paths"]) == set(), hint
        assert (
            set(declared["components"]["schemas"]) - set(committed["components"]["schemas"])
            == set()
        ), hint


class TestTheLearnedRead:
    def test_it_answers_the_screen_s_shape_in_camel_case(
        self, http: TestClient, signed_in: dict[str, str]
    ) -> None:
        answered = http.get(LEARNED_PREFIX, headers=signed_in)

        assert answered.status_code == HTTPStatus.OK, answered.text
        body = answered.json()
        assert body["version"] == 1
        assert body["origin"] == HAND_TUNED
        assert body["fittedAt"] is None
        assert body["parameters"] == []
        assert "estimates rather than measurements" in body["thresholdsAreEstimates"]
        assert "skipped everything and said so" in body["unlocksCountConfirmedVolume"]
        assert "still collecting is normal" in body["collectingIsNormal"].lower()

    def test_a_ready_row_carries_its_sentence_and_its_shrinkage_weight_in_camel_case(
        self, http: TestClient, signed_in: dict[str, str]
    ) -> None:
        assert http.post(ACTIVATE_PATH, headers=signed_in).status_code == HTTPStatus.OK

        body = http.get(LEARNED_PREFIX, headers=signed_in).json()

        assert body["version"] == 2
        assert body["ready"] == 1
        (row,) = body["parameters"]
        assert row["shrinkageWeight"] == 0.42
        assert "82m" in row["plainLanguage"]
        assert row["state"] == "ready"
        assert row["value"] == 1.37

    def test_the_read_is_refused_without_a_session(self, http: TestClient) -> None:
        answered = http.get(LEARNED_PREFIX, headers={"Origin": BROWSER_ORIGIN})

        assert answered.status_code == HTTPStatus.UNAUTHORIZED

    def test_a_read_from_another_origin_is_allowed_and_the_activation_is_not(
        self, http: TestClient, signed_in: dict[str, str]
    ) -> None:
        # The origin check guards the header only a MUTATION can use, so a read is not refused for
        # it. Both halves in one test, because the interesting claim is the difference between them.
        elsewhere = {**signed_in, "Origin": "https://not-syncr.example"}

        assert http.get(LEARNED_PREFIX, headers=elsewhere).status_code == HTTPStatus.OK
        assert http.post(ACTIVATE_PATH, headers=elsewhere).status_code == HTTPStatus.FORBIDDEN


class TestTheVersionList:
    def test_it_lists_both_versions_newest_first_with_origin_and_flag(
        self, http: TestClient, signed_in: dict[str, str]
    ) -> None:
        answered = http.get(WEIGHT_SETS_PREFIX, headers=signed_in)

        assert answered.status_code == HTTPStatus.OK, answered.text
        versions = answered.json()["versions"]
        assert [one["version"] for one in versions] == [2, 1]
        assert [one["origin"] for one in versions] == [FITTED, HAND_TUNED]
        assert [one["active"] for one in versions] == [False, True]
        assert versions[0]["fittedAt"] is not None
        assert versions[1]["fittedAt"] is None

    def test_another_account_sees_only_its_own_versions(
        self, http: TestClient, owner: UserRecord, other_owner: UserRecord
    ) -> None:
        # Two accounts, each with a version 1 and a version 2 of its own. The scope is what makes
        # the two lists identical in shape and disjoint in rows.
        mine = http.get(WEIGHT_SETS_PREFIX, headers=_sign_in(http, owner.email)).json()
        theirs = http.get(WEIGHT_SETS_PREFIX, headers=_sign_in(http, other_owner.email)).json()

        assert [one["version"] for one in mine["versions"]] == [2, 1]
        assert [one["version"] for one in theirs["versions"]] == [2, 1]


class TestTheActivation:
    def test_it_answers_the_version_and_the_future_weeks_it_re_solved(
        self, http: TestClient, signed_in: dict[str, str]
    ) -> None:
        answered = http.post(ACTIVATE_PATH, headers=signed_in)

        assert answered.status_code == HTTPStatus.OK, answered.text
        body = answered.json()
        assert body["version"] == 2
        assert body["resolvedWeeks"] == [str(TRACKED_WEEK)]

    def test_a_retry_with_one_key_reads_the_first_answer_rather_than_re_solving_again(
        self, http: TestClient, signed_in: dict[str, str]
    ) -> None:
        # The flip is idempotent by itself. What the guard adds is the stored RESPONSE, so a retry
        # after a timeout reads the operations the first attempt created rather than queueing a
        # second pass over every future week the account has planned.
        headers = {**signed_in, IDEMPOTENCY_KEY_HEADER: "one-activation"}

        first = http.post(ACTIVATE_PATH, headers=headers)
        second = http.post(ACTIVATE_PATH, headers=headers)

        assert first.status_code == HTTPStatus.OK, first.text
        assert second.status_code == HTTPStatus.OK, second.text
        assert first.json() == second.json()

    def test_a_version_this_account_does_not_hold_is_a_404(
        self, http: TestClient, signed_in: dict[str, str]
    ) -> None:
        answered = http.post(f"{WEIGHT_SETS_PREFIX}/99/activate", headers=signed_in)

        assert answered.status_code == HTTPStatus.NOT_FOUND

    def test_a_version_below_one_is_refused_by_the_path_itself(
        self, http: TestClient, signed_in: dict[str, str]
    ) -> None:
        # Versions start at one, which the row's own check constraint says too. Refused at the path
        # so a zero never reaches a statement that would match nothing.
        answered = http.post(f"{WEIGHT_SETS_PREFIX}/0/activate", headers=signed_in)

        assert answered.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_it_is_refused_without_a_session(self, http: TestClient) -> None:
        answered = http.post(ACTIVATE_PATH, headers={"Origin": BROWSER_ORIGIN})

        assert answered.status_code == HTTPStatus.UNAUTHORIZED

    def test_reverting_through_the_same_route_puts_version_one_back(
        self, http: TestClient, signed_in: dict[str, str]
    ) -> None:
        assert http.post(ACTIVATE_PATH, headers=signed_in).status_code == HTTPStatus.OK

        answered = http.post(f"{WEIGHT_SETS_PREFIX}/1/activate", headers=signed_in)

        assert answered.status_code == HTTPStatus.OK, answered.text
        assert answered.json()["version"] == 1
        listed = http.get(WEIGHT_SETS_PREFIX, headers=signed_in).json()["versions"]
        assert [one["active"] for one in listed] == [False, True]


class TestTheTwoReadsWriteNothing:
    def test_neither_read_changes_the_active_version_or_a_week_s_input_version(
        self, http: TestClient, signed_in: dict[str, str], live_database_url: str, owner: UserRecord
    ) -> None:
        # Reading what has been learned is a read. The Learned screen is one a user opens to check
        # syncr against their own experience, not to change anything.
        before = _state(live_database_url, owner.tenant_id)

        assert http.get(LEARNED_PREFIX, headers=signed_in).status_code == HTTPStatus.OK
        assert http.get(WEIGHT_SETS_PREFIX, headers=signed_in).status_code == HTTPStatus.OK

        assert _state(live_database_url, owner.tenant_id) == before


def _state(database_url: str, tenant_id: TenantId) -> tuple[int | None, int | None]:
    """The active version and this week's input version, as one comparable pair."""

    async def read() -> tuple[int | None, int | None]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                active = await WeightSetRepository(session, tenant_id).active()
                version = await WeekInputVersionRepository(session, tenant_id).current(TRACKED_WEEK)
            return (None if active is None else active.version, version)
        finally:
            await database.engine.dispose()

    return run(read())
