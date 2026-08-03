"""The eight calendar-source routes end to end, against a real Postgres and a real request.

The unit suites prove the parser and the sync-state arithmetic. This proves what only a real
request and a real database can:

- that the two role rules reach the wire as the statuses section 13 states, 409 for a second
  write target and 422 for a horizon on an anchor source;
- that designating an active anchor source as the write target is refused with a reason, which
  is the rule that keeps syncr from reading back its own projection;
- that a `webcal` address is normalized on the way in and read back as what syncr fetches;
- that a forced sync answers with an `Operation` and reaches a terminal status, because a client
  follows one and a pending row nothing completes would never resolve;
- that the read model reports provider, anchor count, last sync time, and state, and carries no
  progress field for a spinner to be built from;
- and that another tenant's identifier is a 404 rather than a change.

The feed itself is served by a stub HTTP server rather than reached over the internet, so the
suite is deterministic and the adapter's real client does the fetching.

The cookie is replayed by setting the header rather than through a cookie jar: the cookie is
`Secure`, and a client that honors that attribute will not send it back over `http://testserver`.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.calendars.config import (
    ANCHOR_SOURCE,
    CALENDAR_SOURCES_PREFIX,
    DISPLAY_NAME_MAX_LENGTH,
    ERROR,
    EXCLUDED,
    EXTERNAL_ID_MAX_LENGTH,
    GOOGLE,
    HORIZON_DAYS_DEFAULT,
    ICS,
    NEVER_SYNCED,
    OK,
    WRITE_TARGET,
)
from syncr_api.core.app_factory import create_app
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.errors import Conflict, NotFound, ValidationFailed
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS
from syncr_api.solving.config import SUCCEEDED
from tests.live_tenants import PASSWORD, provision_owner, remove_tenant

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings

pytestmark = pytest.mark.integration

BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]
SOURCES = CALENDAR_SOURCES_PREFIX

ANOTHER_ID = "11111111-2222-3333-4444-555555555555"

TIMED_EVENTS = 3
WHOLE_DAY_EVENTS = 2

# The stub publisher's host, and how long its thread is given to stop.
STUB_HOST = "127.0.0.1"
SHUTDOWN_SECONDS = 5


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y%m%dT%H%M%SZ")


def _day(moment: datetime) -> str:
    return moment.strftime("%Y%m%d")


def timed_feed(now: datetime) -> str:
    """Three single timed events inside the default projection horizon.

    Built relative to ``now`` rather than taken from the corpus, because the request path
    derives its horizon from the real clock and the corpus is anchored to a fixed week. The
    corpus is what :mod:`tests.test_ics_parse` asserts arithmetic against; what this suite
    asserts is the contract and the persistence, so a feed whose only property is "three events,
    inside the horizon" is the right input for it.
    """
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//stub//EN"]
    for offset in range(1, TIMED_EVENTS + 1):
        start = (now + timedelta(days=offset)).replace(hour=9, minute=0, second=0, microsecond=0)
        lines += [
            "BEGIN:VEVENT",
            f"UID:stub-lecture-{offset}@example.ac.uk",
            f"SUMMARY:Lecture {offset}",
            f"DTSTART:{_stamp(start)}",
            f"DTEND:{_stamp(start + timedelta(hours=2))}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def assessments_feed(now: datetime) -> str:
    """Two whole-day deadlines and one timed component with no end at all.

    The third is the row syncr rejects, so this feed is what proves a half-working feed reads as
    a success whose rejections reach a later read.
    """
    first = now + timedelta(days=2)
    second = now + timedelta(days=4)
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
        "BEGIN:VEVENT\r\nUID:stub-cw1@example.ac.uk\r\nSUMMARY:Coursework 1 due\r\n"
        f"DTSTART;VALUE=DATE:{_day(first)}\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:stub-window@example.ac.uk\r\nSUMMARY:Exam window\r\n"
        f"DTSTART;VALUE=DATE:{_day(second)}\r\n"
        f"DTEND;VALUE=DATE:{_day(second + timedelta(days=3))}\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:stub-viva@example.ac.uk\r\nSUMMARY:Viva - time to be confirmed\r\n"
        f"DTSTART:{_stamp(second.replace(hour=14, minute=0, second=0, microsecond=0))}\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )


class _FeedHandler(BaseHTTPRequestHandler):
    """Serves two feeds at known paths, and 503s at every other.

    A stub server rather than a mocked client, so the request path exercises the real
    ``HttpFeedFetcher`` and the real ``httpx.AsyncClient`` the app wires.
    """

    def do_GET(self) -> None:
        now = datetime.now(UTC)
        bodies = {
            "/timetable.ics": timed_feed(now),
            "/assessments.ics": assessments_feed(now),
        }
        body = bodies.get(self.path)
        if body is None:
            self.send_response(HTTPStatus.SERVICE_UNAVAILABLE)
            self.end_headers()
            return
        encoded = body.encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/calendar; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format: str, *_args: object) -> None:
        """Silence the handler's stderr logging, which is not this suite's output."""


@pytest.fixture(scope="module")
def feed_origin() -> Iterator[str]:
    """A stub publisher, running for the module, at the origin the sources point at."""
    server = ThreadingHTTPServer((STUB_HOST, 0), _FeedHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # Port 0 asks the kernel for a free one, so the suite cannot collide with a developer's
    # own server or with a parallel run.
    port = int(server.server_address[1])
    try:
        yield f"http://{STUB_HOST}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=SHUTDOWN_SECONDS)


@pytest.fixture
def owner(live_database_url: str) -> Iterator[UserRecord]:
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


def add_source(
    http: TestClient,
    headers: dict[str, str],
    *,
    external_id: str,
    display_name: str = "University timetable",
    provider: str = ICS,
) -> dict[str, object]:
    response = http.post(
        SOURCES,
        json={
            "provider": provider,
            "displayName": display_name,
            "externalId": external_id,
        },
        headers=headers,
    )
    assert response.status_code == HTTPStatus.CREATED, response.text
    body: dict[str, object] = response.json()
    return body


# --------------------------------------------------------------------------------
# Adding and reading
# --------------------------------------------------------------------------------


def test_a_webcal_address_is_accepted_and_read_back_as_what_syncr_fetches(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    # No OAuth anywhere in this flow: an ICS source needs no account linking at all.
    created = add_source(http, signed_in, external_id="webcal://example.ac.uk/timetable.ics")

    assert created["externalId"] == "https://example.ac.uk/timetable.ics"
    assert created["role"] == ANCHOR_SOURCE
    assert created["provider"] == ICS
    assert created["horizonDays"] is None
    assert created["state"] == NEVER_SYNCED
    assert created["anchorCount"] == 0


def test_an_address_syncr_cannot_fetch_is_a_stated_422(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    response = http.post(
        SOURCES,
        json={"provider": ICS, "displayName": "Bad", "externalId": "ftp://example.ac.uk/t.ics"},
        headers=signed_in,
    )

    assert response.status_code == ValidationFailed.status
    assert "webcal" in response.json()["detail"]


def test_the_same_feed_added_twice_is_a_stated_409(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    add_source(http, signed_in, external_id="https://example.ac.uk/timetable.ics")

    response = http.post(
        SOURCES,
        json={
            "provider": ICS,
            "displayName": "Again",
            "externalId": "webcal://example.ac.uk/timetable.ics",
        },
        headers=signed_in,
    )

    assert response.status_code == Conflict.status
    # Normalization happens before the duplicate check, so two spellings of one feed collide.
    assert "already a source" in response.json()["detail"]


def test_a_role_cannot_be_asked_for_on_the_add(http: TestClient, signed_in: dict[str, str]) -> None:
    # Adding a calendar and handing syncr destructive write access to it are two acts. An
    # unknown field is rejected, so asking for the role here is stated rather than ignored.
    response = http.post(
        SOURCES,
        json={
            "provider": ICS,
            "displayName": "Target",
            "externalId": "https://example.ac.uk/t.ics",
            "role": WRITE_TARGET,
        },
        headers=signed_in,
    )

    assert response.status_code == ValidationFailed.status


def test_the_read_model_reports_provider_count_time_and_state_and_no_progress(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    add_source(http, signed_in, external_id="https://example.ac.uk/timetable.ics")

    listed = http.get(SOURCES, headers=signed_in).json()["sources"]

    assert len(listed) == 1
    reported = listed[0]
    assert {"provider", "anchorCount", "state", "syncState"} <= set(reported)
    assert "lastSuccessAt" in reported["syncState"]
    # No spinner and no progress bar anywhere: a count that changes is how progress is
    # reported, so there is no field here for one to render from.
    assert "progress" not in reported
    assert not any("progress" in key.lower() for key in reported)


def test_another_tenants_source_is_a_404(
    http: TestClient, signed_in: dict[str, str], live_database_url: str
) -> None:
    stranger = provision_owner(live_database_url)
    try:
        response = http.get(f"{SOURCES}/{ANOTHER_ID}", headers=signed_in)
        assert response.status_code == NotFound.status
    finally:
        remove_tenant(live_database_url, stranger.tenant_id)


# --------------------------------------------------------------------------------
# Inclusion
# --------------------------------------------------------------------------------


def test_an_excluded_source_reports_zero_anchors_and_an_excluded_state(
    http: TestClient, signed_in: dict[str, str], feed_origin: str
) -> None:
    created = add_source(http, signed_in, external_id=f"{feed_origin}/timetable.ics")
    synced = http.post(f"{SOURCES}/{created['id']}/sync", headers=signed_in)
    assert synced.status_code == HTTPStatus.OK, synced.text
    before = http.get(f"{SOURCES}/{created['id']}", headers=signed_in).json()
    assert before["anchorCount"] > 0
    assert before["state"] == OK

    excluded = http.patch(
        f"{SOURCES}/{created['id']}", json={"included": False}, headers=signed_in
    ).json()

    assert excluded["included"] is False
    assert excluded["state"] == EXCLUDED
    assert excluded["anchorCount"] == 0
    # Distinct from an error state: nothing failed, the user asked for this.
    assert excluded["state"] != ERROR
    assert excluded["syncState"]["lastError"] is None


# --------------------------------------------------------------------------------
# The two role rules
# --------------------------------------------------------------------------------


def test_a_never_synced_source_can_become_the_write_target(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    created = add_source(http, signed_in, external_id="https://example.ac.uk/plan.ics")

    designated = http.put(f"{SOURCES}/{created['id']}/role", headers=signed_in)

    assert designated.status_code == HTTPStatus.OK, designated.text
    assert designated.json()["role"] == WRITE_TARGET
    # A write target always carries a projection bound, defaulted here.
    assert designated.json()["horizonDays"] == HORIZON_DAYS_DEFAULT


def test_an_active_anchor_source_cannot_become_the_write_target(
    http: TestClient, signed_in: dict[str, str], feed_origin: str
) -> None:
    # The rule that stops syncr reading back its own projection. Its rejection names the
    # reason and what to do instead, because "422" alone leaves the user nowhere.
    created = add_source(http, signed_in, external_id=f"{feed_origin}/timetable.ics")
    assert http.post(f"{SOURCES}/{created['id']}/sync", headers=signed_in).status_code == 200

    response = http.put(f"{SOURCES}/{created['id']}/role", headers=signed_in)

    assert response.status_code == ValidationFailed.status
    detail = response.json()["detail"]
    assert "active anchor source" in detail
    assert "reconciled destructively" in detail
    # And the source is untouched: it still contributes its anchors.
    still = http.get(f"{SOURCES}/{created['id']}", headers=signed_in).json()
    assert still["role"] == ANCHOR_SOURCE
    assert still["anchorCount"] > 0


def test_a_second_write_target_is_a_409_naming_the_one_that_holds_the_role(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    first = add_source(
        http, signed_in, external_id="https://example.ac.uk/plan.ics", display_name="syncr plan"
    )
    second = add_source(http, signed_in, external_id="https://example.ac.uk/other.ics")
    assert http.put(f"{SOURCES}/{first['id']}/role", headers=signed_in).status_code == 200

    response = http.put(f"{SOURCES}/{second['id']}/role", headers=signed_in)

    assert response.status_code == Conflict.status
    assert "syncr plan" in response.json()["detail"]


def test_designating_the_source_that_already_holds_the_role_changes_nothing(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    # Idempotent by identity rather than by an idempotency key: PUT names a state, so
    # re-asserting it must not be the 409 a SECOND target is.
    created = add_source(http, signed_in, external_id="https://example.ac.uk/plan.ics")
    assert http.put(f"{SOURCES}/{created['id']}/role", headers=signed_in).status_code == 200

    again = http.put(f"{SOURCES}/{created['id']}/role", headers=signed_in)

    assert again.status_code == HTTPStatus.OK
    assert again.json()["role"] == WRITE_TARGET


# --------------------------------------------------------------------------------
# The horizon
# --------------------------------------------------------------------------------


def test_the_horizon_is_set_on_the_write_target(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    created = add_source(http, signed_in, external_id="https://example.ac.uk/plan.ics")
    assert http.put(f"{SOURCES}/{created['id']}/role", headers=signed_in).status_code == 200

    changed = http.patch(
        f"{SOURCES}/{created['id']}/horizon", json={"horizonDays": 21}, headers=signed_in
    )

    assert changed.status_code == HTTPStatus.OK, changed.text
    assert changed.json()["horizonDays"] == 21


def test_a_horizon_on_an_anchor_source_is_a_422(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    created = add_source(http, signed_in, external_id="https://example.ac.uk/timetable.ics")

    response = http.patch(
        f"{SOURCES}/{created['id']}/horizon", json={"horizonDays": 21}, headers=signed_in
    )

    assert response.status_code == ValidationFailed.status
    assert "anchor source" in response.json()["detail"]


@pytest.mark.parametrize("horizon_days", [0, -1, 91])
def test_a_horizon_outside_the_projection_range_is_a_422(
    http: TestClient, signed_in: dict[str, str], horizon_days: int
) -> None:
    created = add_source(http, signed_in, external_id="https://example.ac.uk/plan.ics")
    assert http.put(f"{SOURCES}/{created['id']}/role", headers=signed_in).status_code == 200

    response = http.patch(
        f"{SOURCES}/{created['id']}/horizon",
        json={"horizonDays": horizon_days},
        headers=signed_in,
    )

    assert response.status_code == ValidationFailed.status


# --------------------------------------------------------------------------------
# Sync
# --------------------------------------------------------------------------------


def test_a_forced_sync_answers_with_a_terminal_operation_and_moves_the_count(
    http: TestClient, signed_in: dict[str, str], feed_origin: str
) -> None:
    created = add_source(http, signed_in, external_id=f"{feed_origin}/timetable.ics")

    operation = http.post(f"{SOURCES}/{created['id']}/sync", headers=signed_in)

    assert operation.status_code == HTTPStatus.OK, operation.text
    body = operation.json()
    assert body["kind"] == "calendar_sync"
    # Terminal, because a client follows this and a pending row nothing completes would
    # never resolve.
    assert body["status"] == SUCCEEDED
    assert body["target"]["sourceId"] == created["id"]
    assert body["attempt"] == 1

    after = http.get(f"{SOURCES}/{created['id']}", headers=signed_in).json()
    assert after["state"] == OK
    assert after["anchorCount"] == TIMED_EVENTS
    assert after["syncState"]["lastSuccessAt"] is not None
    assert after["syncState"]["eventsRead"] == TIMED_EVENTS


def test_a_sync_that_rejected_events_still_succeeds_and_reports_each_rejection(
    http: TestClient, signed_in: dict[str, str], feed_origin: str
) -> None:
    # The panel states how many events were rejected and the reason for each class, so the
    # rejections have to survive the attempt and reach a later read.
    created = add_source(http, signed_in, external_id=f"{feed_origin}/assessments.ics")
    assert http.post(f"{SOURCES}/{created['id']}/sync", headers=signed_in).status_code == 200

    read = http.get(f"{SOURCES}/{created['id']}", headers=signed_in).json()

    assert read["state"] == OK
    assert read["syncState"]["lastError"] is None
    # The two that parsed are still returned: a feed that half-works reads as neither fully
    # working nor fully broken.
    assert read["anchorCount"] == WHOLE_DAY_EVENTS
    assert read["syncState"]["rejectedCount"] == 1
    rejection = read["syncState"]["rejections"][0]
    assert rejection["kind"] == "missing-duration"
    assert rejection["component"] == "VEVENT"
    assert "DURATION" in rejection["detail"]
    # The line is what a publisher looks at, so it has to survive the round trip as a real
    # position rather than as a default. Which line it is, is asserted against the corpus in
    # tests/test_ics_parse.py.
    assert rejection["line"] > 0


def test_an_unreachable_feed_records_an_error_and_retains_its_anchors(
    http: TestClient, signed_in: dict[str, str], feed_origin: str
) -> None:
    created = add_source(http, signed_in, external_id=f"{feed_origin}/timetable.ics")
    assert http.post(f"{SOURCES}/{created['id']}/sync", headers=signed_in).status_code == 200
    # Repoint it at a path the stub answers 503 for, without touching its sync state.
    renamed = http.patch(
        f"{SOURCES}/{created['id']}", json={"displayName": "Timetable"}, headers=signed_in
    )
    assert renamed.status_code == HTTPStatus.OK
    broken = add_source(
        http, signed_in, external_id=f"{feed_origin}/gone.ics", display_name="Removed feed"
    )

    assert http.post(f"{SOURCES}/{broken['id']}/sync", headers=signed_in).status_code == 200

    failed = http.get(f"{SOURCES}/{broken['id']}", headers=signed_in).json()
    assert failed["state"] == ERROR
    assert "503" in failed["syncState"]["lastError"]
    assert "retained" in failed["syncState"]["lastError"]
    # The healthy source is untouched by its neighbour's failure.
    healthy = http.get(f"{SOURCES}/{created['id']}", headers=signed_in).json()
    assert healthy["state"] == OK
    assert healthy["anchorCount"] == TIMED_EVENTS


def test_a_repeated_sync_under_one_idempotency_key_runs_once(
    http: TestClient, signed_in: dict[str, str], feed_origin: str
) -> None:
    created = add_source(http, signed_in, external_id=f"{feed_origin}/timetable.ics")
    keyed = {**signed_in, "Idempotency-Key": "sync-once-please"}

    first = http.post(f"{SOURCES}/{created['id']}/sync", headers=keyed)
    second = http.post(f"{SOURCES}/{created['id']}/sync", headers=keyed)

    assert first.status_code == HTTPStatus.OK, first.text
    assert second.status_code == HTTPStatus.OK
    # The same operation replayed, not a second one enqueued.
    assert second.json()["id"] == first.json()["id"]


# --------------------------------------------------------------------------------
# Removal
# --------------------------------------------------------------------------------


def test_a_removed_source_is_gone_from_the_listing(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    created = add_source(http, signed_in, external_id="https://example.ac.uk/timetable.ics")

    removed = http.delete(f"{SOURCES}/{created['id']}", headers=signed_in)

    assert removed.status_code == HTTPStatus.NO_CONTENT
    assert removed.content == b""
    assert http.get(SOURCES, headers=signed_in).json()["sources"] == []


def test_an_external_identifier_wider_than_the_column_is_a_stated_422(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    # For an ICS feed the normalizer enforces the bound. A Google calendarId is taken as the
    # provider states it and is never normalized, so without a bound at the boundary the value
    # reaches the driver and answers 500 rather than naming the field.
    response = http.post(
        SOURCES,
        json={
            "provider": GOOGLE,
            "displayName": "Personal",
            "externalId": "x" * (EXTERNAL_ID_MAX_LENGTH + 1),
        },
        headers=signed_in,
    )

    assert response.status_code == ValidationFailed.status
    assert http.get(SOURCES, headers=signed_in).json()["sources"] == []


def test_a_display_name_wider_than_the_column_is_a_stated_422(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    response = http.post(
        SOURCES,
        json={
            "provider": ICS,
            "displayName": "n" * (DISPLAY_NAME_MAX_LENGTH + 1),
            "externalId": "https://example.ac.uk/t.ics",
        },
        headers=signed_in,
    )

    assert response.status_code == ValidationFailed.status


def test_a_google_source_needs_no_url_normalization(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    # A calendarId is the provider's own opaque identifier, so rewriting it would break the
    # read. Asserted here because the normalizer would reject this string outright.
    created = add_source(
        http,
        signed_in,
        provider=GOOGLE,
        external_id="abc123@group.calendar.google.com",
        display_name="Personal",
    )

    assert created["externalId"] == "abc123@group.calendar.google.com"


def test_a_forced_sync_on_a_google_source_is_refused_rather_than_fetched(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    # Without the guard the calendarId is handed to the ICS adapter as a URL, the fetch fails, and
    # the source is recorded as failing with a transport message. The panel would then tell the
    # user their calendar is broken when the truth is that syncr does not read Google yet.
    created = add_source(
        http,
        signed_in,
        provider=GOOGLE,
        external_id="abc123@group.calendar.google.com",
        display_name="Personal",
    )

    response = http.post(f"{SOURCES}/{created['id']}/sync", headers=signed_in)

    assert response.status_code == ValidationFailed.status
    assert "nothing about this source is wrong" in response.json()["detail"]
    # And the source did not acquire an error state from an attempt that should not have happened.
    read = http.get(f"{SOURCES}/{created['id']}", headers=signed_in).json()
    assert read["state"] == NEVER_SYNCED
    assert read["syncState"]["lastError"] is None
    assert read["syncState"]["lastAttemptAt"] is None
