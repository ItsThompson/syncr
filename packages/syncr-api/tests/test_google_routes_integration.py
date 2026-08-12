"""The Google routes end to end: a real request, a real database, and a faked Google.

The unit suites prove the client, the adapter and the service. This proves what only a real request
and a real Postgres can:

- that a connect states the scopes and what will be read, and that the callback stores a grant whose
  refresh token is CIPHERTEXT in the column;
- that a refresh Google refuses turns into the loudest notice in the product, at two volumes, with
  the duration in it, reached by the read a Settings screen actually makes;
- that a Google source syncs through the same forced-sync route an ICS source does, and that its
  attempt count and resync reason reach the wire;
- that an excluded Google calendar reports zero anchors and an excluded state rather than an error;
- that the calendars of an account are listed for selection, and that asking an ICS source is a
  stated 422 rather than an empty list;
- and that the write-target read model states the destructive behaviour wherever the role is shown.

Only the HTTP boundary to Google is faked, at the httpx client the two dependencies build, so the
service, the adapter, the client, the cipher, the repositories and the migration-backed schema all
run for real. The transport is chosen per test by a mutable handler on the module's own state, which
is what lets one signed-in client walk a whole flow.

The cookie is replayed by setting the header rather than through a cookie jar: the cookie is
``Secure``, and a client that honours that attribute will not send it back over ``http://testserver``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from fastapi.testclient import TestClient

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.calendars.config import (
    CALENDAR_SOURCES_PREFIX,
    EXCLUDED,
    GOOGLE,
    HORIZON_DAYS_DEFAULT,
    ICS,
    OK,
)
from syncr_api.calendars.google_adapter import CHANGES_DETECTED
from syncr_api.calendars.injection import get_feed_client, get_google_read_client
from syncr_api.calendars.schemas import DESTRUCTIVE_RECONCILIATION, RECONCILIATION_KIND
from syncr_api.core.app_factory import create_app
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.settings import (
    API_SERVICE,
    DEV_ALLOWED_ORIGINS,
    DEV_PUBLIC_BASE_URL,
    EnvSettings,
    build_service_settings,
)
from syncr_api.google_account.config import CALLBACK_PATH, CONNECT_PATH, CONNECTION_PATH
from syncr_api.google_account.injection import get_google_client
from syncr_api.google_account.notices import BANNER_NOTICE_ID, PANEL_NOTICE_ID
from syncr_api.google_account.outcomes import CONNECTED, DENIED, EXPIRED, OUTCOME_QUERY_KEY
from syncr_api.google_account.state import issue_state
from tests.fake_google import (
    ACCESS_TOKEN,
    CLIENT_ID,
    CLIENT_SECRET,
    REDIRECT_URI,
    REFRESH_TOKEN,
    SYNC_TOKEN,
    TEST_ENCRYPTION_KEY,
    calendar,
    calendar_list_page,
    event,
    events_page,
)
from tests.live_tenants import PASSWORD, provision_owner, remove_tenant

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings

pytestmark = pytest.mark.integration

BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]
SOURCES = CALENDAR_SOURCES_PREFIX
SIGNING_SECRET = "a-signing-secret-for-this-suite"  # pragma: allowlist secret

TOKEN_HOST = "oauth2.googleapis.com"
CALENDAR_LIST_PATH = "/calendar/v3/users/me/calendarList"


@dataclass
class FakeGoogle:
    """What Google answers, per test, and every request it received.

    One object rather than a fixture per case: a connect, a sync and a read of the connection are
    three requests in one flow, and the flow is what these tests are about.
    """

    token_answer: httpx.Response = field(default_factory=lambda: _token_response())
    events_answers: list[httpx.Response] = field(default_factory=list)
    calendar_list: httpx.Response | None = None
    requests: list[httpx.Request] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == TOKEN_HOST:
            return self.token_answer
        if request.url.path == CALENDAR_LIST_PATH:
            return self.calendar_list or httpx.Response(200, content=calendar_list_page())
        if self.events_answers:
            return self.events_answers.pop(0)
        return httpx.Response(200, content=events_page())

    def asked_google_for(self, path_fragment: str) -> list[httpx.Request]:
        return [one for one in self.requests if path_fragment in str(one.url)]


def inside_the_horizon(identifier: str, *, days: int = 1) -> dict[str, Any]:
    """One timed event inside the default projection horizon, relative to the real clock.

    Built from ``now`` rather than taken from a fixture, because the request path derives its
    horizon from the real clock: a fixed stamp would be read, counted as outside the window, and
    the source would report zero anchors for a reason that has nothing to do with the contract.
    """
    start = (datetime.now(UTC) + timedelta(days=days)).replace(
        hour=9, minute=0, second=0, microsecond=0
    )
    return event(
        identifier,
        start=start.isoformat().replace("+00:00", "Z"),
        end=(start + timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
    )


def _token_response(**overrides: Any) -> httpx.Response:
    body: dict[str, Any] = {
        "access_token": ACCESS_TOKEN,
        "expires_in": 3599,
        "refresh_token": REFRESH_TOKEN,
        "scope": "https://www.googleapis.com/auth/calendar.events.readonly",
        "token_type": "Bearer",
    }
    body.update(overrides)
    return httpx.Response(200, json=body)


@pytest.fixture
def google() -> FakeGoogle:
    return FakeGoogle()


@pytest.fixture
def settings() -> ServiceSettings:
    """Settings for a deployment that HAS a Google client, which is what these routes need."""
    return build_service_settings(
        service=API_SERVICE,
        env=EnvSettings(
            _env_file=None,
            session_signing_secret=SIGNING_SECRET,
            google_oauth_client_id=CLIENT_ID,
            google_oauth_client_secret=CLIENT_SECRET,
            google_oauth_redirect_uri=REDIRECT_URI,
            google_token_encryption_key=TEST_ENCRYPTION_KEY,
        ),
    )


@pytest.fixture
def owner(live_database_url: str) -> Iterator[UserRecord]:
    account = provision_owner(live_database_url)
    yield account
    remove_tenant(live_database_url, account.tenant_id)


@pytest.fixture
def http(
    live_database_url: str, settings: ServiceSettings, google: FakeGoogle
) -> Iterator[TestClient]:
    """A client against an app wired to the live database, with Google's HTTP boundary faked.

    The override is on the two HTTP CLIENTS rather than on a service, so every layer between the
    route and the transport is the real one.
    """
    database = create_database(live_database_url)
    app = create_app(settings, lifespan=create_db_lifespan(database.engine))
    app.state.db = database

    async def faked() -> AsyncIterator[httpx.AsyncClient]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(google.handle)) as client:
            yield client

    app.dependency_overrides[get_google_client] = faked
    app.dependency_overrides[get_google_read_client] = faked
    app.dependency_overrides[get_feed_client] = faked
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def signed_in(http: TestClient, owner: UserRecord) -> dict[str, str]:
    """The headers a signed-in browser sends: the session cookie and its origin."""
    response = http.post(
        f"{AUTH_PREFIX}/login",
        json={"email": owner.email, "password": PASSWORD},
        headers={"Origin": BROWSER_ORIGIN},
    )
    assert response.status_code == HTTPStatus.OK, response.text
    cookie = response.headers["set-cookie"]
    token = cookie.split(f"{SESSION_COOKIE_NAME}=", 1)[1].split(";", 1)[0]
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}", "Origin": BROWSER_ORIGIN}


def add_google_source(
    http: TestClient,
    headers: dict[str, str],
    *,
    calendar_id: str = "primary",
    display_name: str = "Personal",
) -> dict[str, Any]:
    response = http.post(
        SOURCES,
        json={"provider": GOOGLE, "displayName": display_name, "externalId": calendar_id},
        headers=headers,
    )
    assert response.status_code == HTTPStatus.CREATED, response.text
    return dict(response.json())


def connect(http: TestClient, headers: dict[str, str], owner: UserRecord) -> httpx.Response:
    """Walk the callback with a state this deployment would have issued."""
    state = issue_state(tenant_id=owner.tenant_id, secret=SIGNING_SECRET, at=datetime.now(UTC))
    answered: httpx.Response = http.get(
        f"{SOURCES}{CALLBACK_PATH}",
        params={"code": "4/code", "state": state},
        headers=headers,
        follow_redirects=False,
    )
    return answered


def returned_to_settings(outcome: str) -> str:
    """The target the callback answers with on this deployment, as the browser receives it.

    The fixture names no application origin, so it is the api's own: the single-origin shape the
    deployed stack serves. `tests/test_google_callback_target.py` drives the split-origin one.
    """
    return f"{DEV_PUBLIC_BASE_URL}/settings?{OUTCOME_QUERY_KEY}={outcome}"


# --------------------------------------------------------------------------------
# The connect flow
# --------------------------------------------------------------------------------


def test_a_connect_states_the_scopes_and_which_calendars_will_be_read(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    response = http.post(f"{SOURCES}{CONNECT_PATH}", headers=signed_in)

    assert response.status_code == HTTPStatus.OK, response.text
    body = response.json()
    assert body["authorizationUrl"].startswith("https://accounts.google.com/")
    assert len(body["scopes"]) == 3
    assert all(scope["statement"] for scope in body["scopes"])
    assert "No calendar is read until you include it" in body["statement"]
    assert body["calendarsRead"] == []


def test_a_connect_names_the_google_sources_already_configured(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    add_google_source(http, signed_in, display_name="Personal")

    body = http.post(f"{SOURCES}{CONNECT_PATH}", headers=signed_in).json()

    assert [one["displayName"] for one in body["calendarsRead"]] == ["Personal"]


def test_the_callback_stores_a_grant_and_returns_the_browser_to_settings(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord
) -> None:
    response = connect(http, signed_in, owner)

    assert response.status_code == HTTPStatus.SEE_OTHER
    assert response.headers["location"] == returned_to_settings(CONNECTED)

    connection = http.get(f"{SOURCES}{CONNECTION_PATH}", headers=signed_in).json()
    assert connection["connected"] is True
    assert connection["configured"] is True
    assert connection["notices"] == []


def test_the_stored_refresh_token_is_ciphertext_in_the_column(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # Read out of the database rather than through the api, because the claim is about the COLUMN:
    # a dump, a backup and a replica all carry what this row holds.
    import asyncio

    from sqlalchemy import text

    connect(http, signed_in, owner)

    async def stored() -> str:
        database = create_database(live_database_url)
        try:
            async with database.engine.connect() as connection:
                found = await connection.execute(
                    text(
                        "SELECT encrypted_refresh_token FROM google_credentials "
                        "WHERE tenant_id = :tenant"
                    ),
                    {"tenant": owner.tenant_id},
                )
                return str(found.scalar_one())
        finally:
            await database.engine.dispose()

    ciphertext = asyncio.run(stored())

    assert REFRESH_TOKEN not in ciphertext
    assert ciphertext.startswith("gAAAAA")


def test_a_user_who_declined_is_returned_to_settings_without_a_grant(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    response = http.get(
        f"{SOURCES}{CALLBACK_PATH}",
        params={"error": "access_denied", "state": "whatever"},
        headers=signed_in,
        follow_redirects=False,
    )

    assert response.headers["location"] == returned_to_settings(DENIED)
    assert http.get(f"{SOURCES}{CONNECTION_PATH}", headers=signed_in).json()["connected"] is False


def test_a_callback_whose_state_does_not_verify_stores_nothing(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    response = http.get(
        f"{SOURCES}{CALLBACK_PATH}",
        params={"code": "4/code", "state": "forged"},
        headers=signed_in,
        follow_redirects=False,
    )

    assert response.headers["location"] == returned_to_settings(EXPIRED)
    assert http.get(f"{SOURCES}{CONNECTION_PATH}", headers=signed_in).json()["connected"] is False


def test_the_callback_needs_a_session_like_every_other_route(http: TestClient) -> None:
    # Google's redirect is a top-level GET navigation, so a browser sends the SameSite=Lax cookie
    # with it. Completing a connect without one would accept a grant nobody is signed in to own.
    response = http.get(
        f"{SOURCES}{CALLBACK_PATH}", params={"code": "4/code"}, follow_redirects=False
    )

    assert response.status_code == HTTPStatus.UNAUTHORIZED


# --------------------------------------------------------------------------------
# Reading a Google calendar
# --------------------------------------------------------------------------------


def test_a_google_source_syncs_through_the_same_route_an_ics_source_does(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, google: FakeGoogle
) -> None:
    connect(http, signed_in, owner)
    source = add_google_source(http, signed_in)
    google.events_answers = [
        httpx.Response(
            200,
            content=events_page(
                inside_the_horizon("one"), inside_the_horizon("two", days=2), sync_token=SYNC_TOKEN
            ),
        )
    ]

    synced = http.post(f"{SOURCES}/{source['id']}/sync", headers=signed_in)

    assert synced.status_code == HTTPStatus.OK, synced.text
    read = http.get(f"{SOURCES}/{source['id']}", headers=signed_in).json()
    assert read["state"] == OK
    assert read["anchorCount"] == 2
    assert read["syncState"]["lastError"] is None
    assert read["syncState"]["attempts"] == 1
    assert read["syncState"]["resyncReason"] is None


def test_a_second_sync_asks_what_changed_and_reads_fully_when_something_did(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, google: FakeGoogle
) -> None:
    connect(http, signed_in, owner)
    source = add_google_source(http, signed_in)
    google.events_answers = [
        httpx.Response(200, content=events_page(inside_the_horizon("one"), sync_token=SYNC_TOKEN))
    ]
    http.post(f"{SOURCES}/{source['id']}/sync", headers=signed_in)

    # The second poll: the detector reports a change, so the calendar is read in full.
    google.events_answers = [
        httpx.Response(
            200, content=events_page(inside_the_horizon("moved", days=3), sync_token="CNEXT")
        ),
        httpx.Response(
            200,
            content=events_page(
                inside_the_horizon("one"), inside_the_horizon("moved", days=3), sync_token="CNEXT"
            ),
        ),
    ]
    http.post(f"{SOURCES}/{source['id']}/sync", headers=signed_in)

    read = http.get(f"{SOURCES}/{source['id']}", headers=signed_in).json()
    assert read["anchorCount"] == 2
    assert read["syncState"]["resyncReason"] == CHANGES_DETECTED
    assert read["syncState"]["attempts"] == 2
    sent = [one for one in google.asked_google_for("/events") if "syncToken" in str(one.url)]
    assert sent, "the second poll sent the token the first stored"


def test_an_excluded_google_calendar_reports_zero_anchors_and_an_excluded_state(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, google: FakeGoogle
) -> None:
    connect(http, signed_in, owner)
    source = add_google_source(http, signed_in)
    google.events_answers = [
        httpx.Response(200, content=events_page(inside_the_horizon("one"), sync_token=SYNC_TOKEN))
    ]
    http.post(f"{SOURCES}/{source['id']}/sync", headers=signed_in)

    excluded = http.patch(
        f"{SOURCES}/{source['id']}", json={"included": False}, headers=signed_in
    ).json()

    assert excluded["state"] == EXCLUDED
    assert excluded["anchorCount"] == 0
    # An exclusion is not an error: the user asked for zero anchors from it.
    assert excluded["syncState"]["lastError"] is None


def test_including_a_calendar_again_restores_its_count_on_the_next_sync(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, google: FakeGoogle
) -> None:
    # Exclusions persist and are reversible, which is what per-calendar choice means.
    connect(http, signed_in, owner)
    source = add_google_source(http, signed_in)
    http.patch(f"{SOURCES}/{source['id']}", json={"included": False}, headers=signed_in)

    restored = http.patch(
        f"{SOURCES}/{source['id']}", json={"included": True}, headers=signed_in
    ).json()
    google.events_answers = [
        httpx.Response(200, content=events_page(inside_the_horizon("one"), sync_token=SYNC_TOKEN))
    ]
    http.post(f"{SOURCES}/{restored['id']}/sync", headers=signed_in)

    read = http.get(f"{SOURCES}/{source['id']}", headers=signed_in).json()
    assert read["state"] == OK
    assert read["anchorCount"] == 1


# --------------------------------------------------------------------------------
# The account's calendars
# --------------------------------------------------------------------------------


def test_the_accounts_calendars_are_listed_for_selection(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, google: FakeGoogle
) -> None:
    connect(http, signed_in, owner)
    source = add_google_source(http, signed_in)
    google.calendar_list = httpx.Response(
        200,
        content=calendar_list_page(
            calendar("primary", summary="Personal", primary=True),
            calendar("holidays@group.calendar", summary="Holidays", access_role="reader"),
        ),
    )

    response = http.get(f"{SOURCES}/{source['id']}/remote-calendars", headers=signed_in)

    assert response.status_code == HTTPStatus.OK, response.text
    listed = response.json()["calendars"]
    assert [one["displayName"] for one in listed] == ["Personal", "Holidays"]
    # Only a writable calendar can be the write target, because syncr reconciles that one
    # destructively.
    assert [one["writable"] for one in listed] == [True, False]


def test_asking_an_ics_source_for_its_accounts_calendars_is_refused(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    feed = http.post(
        SOURCES,
        json={
            "provider": ICS,
            "displayName": "University timetable",
            "externalId": "https://example.ac.uk/timetable.ics",
        },
        headers=signed_in,
    ).json()

    response = http.get(f"{SOURCES}/{feed['id']}/remote-calendars", headers=signed_in)

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert "list of calendars" in response.json()["detail"]


def test_another_tenants_source_discloses_nothing(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    response = http.get(
        f"{SOURCES}/11111111-2222-3333-4444-555555555555/remote-calendars", headers=signed_in
    )

    assert response.status_code == HTTPStatus.NOT_FOUND


# --------------------------------------------------------------------------------
# Write-target expiry, the loudest notice in the product
# --------------------------------------------------------------------------------


def test_a_refresh_google_refuses_raises_a_banner_and_a_settings_panel(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, google: FakeGoogle
) -> None:
    connect(http, signed_in, owner)
    source = add_google_source(http, signed_in)
    # The grant dies between the connect and the next read, which is what revocation looks like.
    google.token_answer = httpx.Response(400, json={"error": "invalid_grant"})

    http.post(f"{SOURCES}/{source['id']}/sync", headers=signed_in)
    connection = http.get(f"{SOURCES}{CONNECTION_PATH}", headers=signed_in).json()

    raised = {notice["id"]: notice for notice in connection["notices"]}
    assert set(raised) == {BANNER_NOTICE_ID, PANEL_NOTICE_ID}
    banner = raised[BANNER_NOTICE_ID]
    assert banner["volume"] == "banner"
    assert banner["pigment"] == "oxide"
    assert raised[PANEL_NOTICE_ID]["volume"] == "panel"
    assert raised[PANEL_NOTICE_ID]["scope"]["screen"] == "settings"
    # Every degradation notice names what survives, and this one offers one repair.
    assert banner["stillWorks"]
    assert banner["action"]["label"] == "Reconnect Google"
    assert banner["since"] is not None
    assert "for less than a minute" in banner["detail"]


def test_a_dead_grant_makes_the_source_say_so_without_losing_what_it_read(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, google: FakeGoogle
) -> None:
    connect(http, signed_in, owner)
    source = add_google_source(http, signed_in)
    google.events_answers = [
        httpx.Response(200, content=events_page(inside_the_horizon("one"), sync_token=SYNC_TOKEN))
    ]
    http.post(f"{SOURCES}/{source['id']}/sync", headers=signed_in)
    google.token_answer = httpx.Response(400, json={"error": "invalid_grant"})

    http.post(f"{SOURCES}/{source['id']}/sync", headers=signed_in)

    read = http.get(f"{SOURCES}/{source['id']}", headers=signed_in).json()
    assert read["syncState"]["lastError"] is not None
    assert "retained" in read["syncState"]["lastError"]
    # The anchors read on the last success are still the best occupancy syncr has.
    assert read["anchorCount"] == 1


def test_a_reconnect_clears_the_notice_it_repaired(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, google: FakeGoogle
) -> None:
    connect(http, signed_in, owner)
    source = add_google_source(http, signed_in)
    google.token_answer = httpx.Response(400, json={"error": "invalid_grant"})
    http.post(f"{SOURCES}/{source['id']}/sync", headers=signed_in)
    assert http.get(f"{SOURCES}{CONNECTION_PATH}", headers=signed_in).json()["notices"]

    google.token_answer = _token_response()
    connect(http, signed_in, owner)

    assert http.get(f"{SOURCES}{CONNECTION_PATH}", headers=signed_in).json()["notices"] == []


# --------------------------------------------------------------------------------
# The write target
# --------------------------------------------------------------------------------


def test_the_write_target_read_model_states_the_destructive_behaviour(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    source = add_google_source(http, signed_in, calendar_id="syncr-dev", display_name="syncr (dev)")

    designated = http.put(f"{SOURCES}/{source['id']}/role", headers=signed_in)

    assert designated.status_code == HTTPStatus.OK, designated.text
    body = designated.json()
    target = body["writeTarget"]
    assert target["calendarName"] == "syncr (dev)"
    assert target["horizonDays"] == HORIZON_DAYS_DEFAULT
    assert target["reconciliation"] == RECONCILIATION_KIND
    assert target["statement"] == DESTRUCTIVE_RECONCILIATION
    assert "overwritten" in target["statement"]


def test_an_anchor_source_carries_no_write_target_reading(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    source = add_google_source(http, signed_in)

    assert http.get(f"{SOURCES}/{source['id']}", headers=signed_in).json()["writeTarget"] is None


def test_the_horizon_is_read_back_on_the_write_target_reading(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    source = add_google_source(http, signed_in, calendar_id="syncr-dev", display_name="syncr (dev)")
    http.put(f"{SOURCES}/{source['id']}/role", headers=signed_in)

    changed = http.patch(
        f"{SOURCES}/{source['id']}/horizon", json={"horizonDays": 21}, headers=signed_in
    )

    assert changed.status_code == HTTPStatus.OK, changed.text
    assert changed.json()["writeTarget"]["horizonDays"] == 21


# --------------------------------------------------------------------------------
# A deployment with no Google client
# --------------------------------------------------------------------------------


def test_a_deployment_with_no_google_client_says_so_rather_than_failing_obscurely(
    live_database_url: str, owner: UserRecord
) -> None:
    stock = build_service_settings(
        service=API_SERVICE,
        env=EnvSettings(_env_file=None, session_signing_secret=SIGNING_SECRET),
    )
    database = create_database(live_database_url)
    app = create_app(stock, lifespan=create_db_lifespan(database.engine))
    app.state.db = database

    with TestClient(app, raise_server_exceptions=False) as http:
        login = http.post(
            f"{AUTH_PREFIX}/login",
            json={"email": owner.email, "password": PASSWORD},
            headers={"Origin": BROWSER_ORIGIN},
        )
        token = login.headers["set-cookie"].split(f"{SESSION_COOKIE_NAME}=", 1)[1].split(";", 1)[0]
        headers = {"Cookie": f"{SESSION_COOKIE_NAME}={token}", "Origin": BROWSER_ORIGIN}

        refused = http.post(f"{SOURCES}{CONNECT_PATH}", headers=headers)
        connection = http.get(f"{SOURCES}{CONNECTION_PATH}", headers=headers)

    assert refused.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    detail = refused.json()["detail"]
    assert "GOOGLE_OAUTH_CLIENT_ID" in detail
    assert "ICS feed still syncs" in detail
    # The read still answers, because it is how Settings decides what to render.
    assert connection.status_code == HTTPStatus.OK
    assert connection.json()["configured"] is False


def test_provider_text_carrying_a_nul_byte_does_not_disable_the_sync(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, google: FakeGoogle
) -> None:
    """The NUL-byte class the ICS path was fixed for, measured over the Google path's own text.

    A NUL in publisher-authored text reaches a Postgres text column as
    ``CharacterNotInRepertoireError``, which rolls back the transaction BEFORE `last_error` is
    written: a third party could then durably disable a user's sync with nothing on the panel.
    Google hands syncr the same shape of text in `summary` and `location`, and the identifier it
    keys an anchor by, so all three carry one here.

    What answers it is the anchor boundary rather than this adapter: the scrubbing in
    `anchors.identity` drops control characters from a title, a location and a reconciliation key
    before any of them reaches a column. This asserts the OUTCOME for this provider rather than the
    mechanism, so it keeps holding if that scrubbing moves.
    """
    connect(http, signed_in, owner)
    source = add_google_source(http, signed_in)
    hostile = inside_the_horizon("evt-\x00-one")
    hostile["summary"] = "Kontron\x00 Placement Interview"
    hostile["location"] = "Reading\x00, Berkshire"
    google.events_answers = [
        httpx.Response(200, content=events_page(hostile, sync_token=SYNC_TOKEN))
    ]

    synced = http.post(f"{SOURCES}/{source['id']}/sync", headers=signed_in)

    assert synced.status_code == HTTPStatus.OK, synced.text
    read = http.get(f"{SOURCES}/{source['id']}", headers=signed_in).json()
    # The sync ran, the state was written, and the occupancy the feed asserts is kept.
    assert read["state"] == OK
    assert read["syncState"]["lastError"] is None
    assert read["anchorCount"] == 1


def test_the_published_key_refuses_only_the_connect_and_leaves_every_read_working(
    live_database_url: str, owner: UserRecord, google: FakeGoogle
) -> None:
    """The blast radius of the published-key refusal, at the routes rather than at a unit.

    An operator lands in this state by copying `.env.example`, which ships the published key, and
    setting a client id from the runbook. The earlier shape refused to build a cipher at all, so
    every calendar-source route answered 503 and the worker's whole poll died each tick, while the
    message said feeds still synced. What must be refused is connecting, and nothing else.
    """
    published = build_service_settings(
        service=API_SERVICE,
        env=EnvSettings(
            _env_file=None,
            environment="production",
            session_signing_secret=SIGNING_SECRET,
            google_oauth_client_id=CLIENT_ID,
            google_oauth_client_secret=CLIENT_SECRET,
            google_oauth_redirect_uri=REDIRECT_URI,
        ),
    )
    database = create_database(live_database_url)
    app = create_app(published, lifespan=create_db_lifespan(database.engine))
    app.state.db = database

    async def faked() -> AsyncIterator[httpx.AsyncClient]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(google.handle)) as client:
            yield client

    app.dependency_overrides[get_google_client] = faked
    app.dependency_overrides[get_google_read_client] = faked
    app.dependency_overrides[get_feed_client] = faked

    with TestClient(app, raise_server_exceptions=False) as http:
        login = http.post(
            f"{AUTH_PREFIX}/login",
            json={"email": owner.email, "password": PASSWORD},
            headers={"Origin": BROWSER_ORIGIN},
        )
        token = login.headers["set-cookie"].split(f"{SESSION_COOKIE_NAME}=", 1)[1].split(";", 1)[0]
        headers = {"Cookie": f"{SESSION_COOKIE_NAME}={token}", "Origin": BROWSER_ORIGIN}

        listed = http.get(SOURCES, headers=headers)
        added = http.post(
            SOURCES,
            json={
                "provider": ICS,
                "displayName": "University timetable",
                "externalId": "https://example.ac.uk/timetable.ics",
            },
            headers=headers,
        )
        connection = http.get(f"{SOURCES}{CONNECTION_PATH}", headers=headers)
        refused = http.get(
            f"{SOURCES}{CALLBACK_PATH}",
            params={
                "code": "4/code",
                "state": issue_state(
                    tenant_id=owner.tenant_id, secret=SIGNING_SECRET, at=datetime.now(UTC)
                ),
            },
            headers=headers,
            follow_redirects=False,
        )

    # Every read and every ICS write the message promises still work.
    assert listed.status_code == HTTPStatus.OK, listed.text
    assert added.status_code == HTTPStatus.CREATED, added.text
    assert connection.status_code == HTTPStatus.OK
    # And the one act that would store an authorization under the published key is refused by name.
    assert refused.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert "GOOGLE_TOKEN_ENCRYPTION_KEY" in refused.json()["detail"]
    assert "Every ICS feed still syncs" in refused.json()["detail"]


def test_no_response_carries_a_token_or_a_ciphertext(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord
) -> None:
    # The wire is the other place a credential could leak: the connection read model states what
    # was granted and when, and never the values behind it.
    connect(http, signed_in, owner)

    rendered = json.dumps(http.get(f"{SOURCES}{CONNECTION_PATH}", headers=signed_in).json())

    assert REFRESH_TOKEN not in rendered
    assert ACCESS_TOKEN not in rendered
    assert "gAAAAA" not in rendered
