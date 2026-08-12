"""The stale-feed panel end to end, against a real Postgres and a real request.

The unit suite proves what the composer decides. This proves the two things only a real database and
a real request can:

- that the days the panel names come back from the anchor table, resolved to local dates, through a
  read that keeps repeats and leaves the composer to collapse them, rather than through a fake that
  already answered in dates;
- and that the notice reaches the wire on the source list, under the names the frontend reads, with
  no staleness threshold anywhere on the document.

The feed is never fetched. A source is added through its route, its commitments are seeded through
the reconciler exactly as ``test_anchor_routes_integration`` seeds them, and the failure is written
to the sync state through the repository. Making a real fetch fail needs a stub publisher on
loopback, and the address rules refuse a loopback feed, so a test built that way would assert this
notice through a refusal that has nothing to do with it.

The cookie is replayed by setting the header rather than through a cookie jar: the cookie is
``Secure``, and a client that honors that attribute will not send it back over ``http://testserver``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.anchors.reconcile import AnchorReconciler
from syncr_api.anchors.repository import AnchorRepository
from syncr_api.anchors.type_repository import AnchorTypeRepository
from syncr_api.calendars.config import (
    ANCHOR_SOURCE,
    CALENDAR_SOURCES_PREFIX,
    HORIZON_DAYS_DEFAULT,
    ICS,
    STALE_AFTER,
)
from syncr_api.calendars.day_spans import local_day_start
from syncr_api.calendars.events import FetchOutcome, RawEvent
from syncr_api.calendars.feed_notices import FEED_STALE, FEED_STILL_WORKS
from syncr_api.calendars.records import CalendarSourceRecord, SyncStateRecord
from syncr_api.calendars.repository import CalendarSourceRepository
from syncr_api.calendars.sync_state import recorded_failure
from syncr_api.core.app_factory import create_app
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.notices import AMBER, PANEL
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.user_settings.config import HOME_ZONE_DEFAULT
from syncr_api.user_settings.solve_inputs import TrackedWeekInputVersions
from syncr_api.user_settings.zone_reading import local_date
from syncr_domain.intervals import Interval
from syncr_domain.zones import ZoneProfile
from tests.live_tenants import PASSWORD, provision_owner, remove_tenant, run

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings
    from syncr_domain.identifiers import TenantId

pytestmark = pytest.mark.integration

BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]
SOURCES = CALENDAR_SOURCES_PREFIX
TIMETABLE = "https://example.ac.uk/timetable.ics"
OTHER_FEED = "https://example.ac.uk/society.ics"

# Real wall-clock time, because the composer decides against the process clock and the horizon is
# read from now. Every seeded instant is placed at local MIDDAY on a date derived from it, rather
# than by adding hours to `now`: a run late in the evening turns `now + 26 hours` into the day after
# the one the test means, which is a failure that appears for a few hours a day and no others.
NOW = datetime.now(UTC)
HOME = ZoneProfile(home_zone=HOME_ZONE_DEFAULT)
TODAY_LOCAL = local_date(NOW, HOME_ZONE_DEFAULT)

MIDDAY = timedelta(hours=12)


def midday_in(days_ahead: int) -> datetime:
    """Local midday on the date ``days_ahead`` from today, as an instant.

    Midday rather than an offset from ``now``, so which local date an instant falls on is fixed by
    the date arithmetic instead of by the hour the suite happens to run at.
    """
    return local_day_start(TODAY_LOCAL + timedelta(days=days_ahead), HOME) + MIDDAY


def day_of(days_ahead: int) -> str:
    return (TODAY_LOCAL + timedelta(days=days_ahead)).isoformat()


# Far enough past the default horizon that no time of day can pull it back inside.
BEYOND_THE_HORIZON = HORIZON_DAYS_DEFAULT + 6

# How long a seeded commitment lasts. Named because one case places it deliberately so that the hour
# it ends in falls on the day after the one it began in.
EVENT_MINUTES = timedelta(minutes=60)


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
    external_id: str = TIMETABLE,
    display_name: str = "University timetable",
) -> dict[str, Any]:
    response = http.post(
        SOURCES,
        json={"provider": ICS, "displayName": display_name, "externalId": external_id},
        headers=headers,
    )
    assert response.status_code == HTTPStatus.CREATED, response.text
    created: dict[str, Any] = response.json()
    return created


def a_source(
    source_id: Any, tenant_id: TenantId, *, external_id: str = TIMETABLE
) -> CalendarSourceRecord:
    return CalendarSourceRecord(
        id=source_id,
        tenant_id=tenant_id,
        provider=ICS,
        role=ANCHOR_SOURCE,
        display_name="University timetable",
        external_id=external_id,
        included=True,
        horizon_days=None,
        created_at=NOW,
    )


def an_event(uid: str, *, start: datetime) -> RawEvent:
    return RawEvent(
        uid=uid,
        series_uid=None,
        title="Compilers lecture",
        interval=Interval(start, start + EVENT_MINUTES),
        location="Lecture Theatre 3",
        sequence=0,
        all_day=False,
    )


def seed_anchors(
    database_url: str,
    tenant_id: TenantId,
    source_id: Any,
    events: Sequence[RawEvent],
    *,
    external_id: str = TIMETABLE,
) -> None:
    """Put commitments in the table the way a sync would. There is no route that creates one."""

    async def seed() -> None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                reconciler = AnchorReconciler(
                    AnchorRepository(session, tenant_id),
                    AnchorTypeRepository(session, tenant_id),
                    versions=TrackedWeekInputVersions(
                        WeekInputVersionRepository(session, tenant_id), clock=lambda: NOW
                    ),
                    home_zone=HOME_ZONE_DEFAULT,
                )
                await reconciler.reconcile(
                    a_source(source_id, tenant_id, external_id=external_id),
                    FetchOutcome(events=tuple(events), events_read=len(events), reparsed=True),
                )
        finally:
            await database.engine.dispose()

    run(seed())


def stop_answering(
    database_url: str, tenant_id: TenantId, source_id: Any, *, succeeded: datetime | None
) -> None:
    """Record a failed read on the source, through the writer that owns the sentence it states."""

    async def write() -> None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                await CalendarSourceRepository(session, tenant_id).save_sync_state(
                    source_id,
                    recorded_failure(
                        SyncStateRecord(last_success_at=succeeded, last_attempt_at=succeeded),
                        at=NOW,
                        reason="The feed answered 503.",
                    ),
                )
        finally:
            await database.engine.dispose()

    run(write())


def notices_of(http: TestClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    response = http.get(SOURCES, headers=headers)
    assert response.status_code == HTTPStatus.OK, response.text
    body: dict[str, Any] = response.json()
    listed: list[dict[str, Any]] = body["notices"]
    return listed


def test_every_seeded_day_falls_on_the_date_it_is_named_for() -> None:
    # The control on this module's own clock arithmetic, and it exists because the first version of
    # it was wrong: instants built by adding hours to `now` crossed local midnight when the suite
    # ran late in the evening, so three cases passed for twenty hours a day and failed for four.
    # Every offset the module uses is checked, at whatever time of day this run happens to be.
    for days_ahead in (-2, 0, 1, 3, BEYOND_THE_HORIZON):
        assert local_date(midday_in(days_ahead), HOME_ZONE_DEFAULT) == TODAY_LOCAL + timedelta(
            days=days_ahead
        ), f"midday_in({days_ahead}) does not fall on the date it names"


def test_a_commitment_that_runs_past_midnight_is_named_on_the_day_it_began(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # The one case that can tell the read's two instant columns apart. Every other seeded commitment
    # begins and ends inside one local day, so reading `ends_at` instead of `starts_at` would answer
    # identically and the column choice would be untested.
    began = midday_in(1) + timedelta(hours=11, minutes=30)
    ends = began + EVENT_MINUTES
    # The premise, checked rather than assumed: this commitment really does cross local midnight.
    assert local_date(began, HOME_ZONE_DEFAULT) == TODAY_LOCAL + timedelta(days=1)
    assert local_date(ends, HOME_ZONE_DEFAULT) == TODAY_LOCAL + timedelta(days=2)

    created = add_source(http, signed_in)
    seed_anchors(live_database_url, owner.tenant_id, created["id"], [an_event("late", start=began)])
    stop_answering(live_database_url, owner.tenant_id, created["id"], succeeded=None)

    raised = notices_of(http, signed_in)

    assert len(raised) == 1
    assert raised[0]["scope"]["dates"] == [day_of(1)]


def test_a_healthy_source_list_carries_an_empty_notice_array(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # The control for every assertion below: the field is on the document and the condition is what
    # fills it, so an empty array here is what makes a populated one downstream mean something.
    created = add_source(http, signed_in)
    seed_anchors(
        live_database_url, owner.tenant_id, created["id"], [an_event("a", start=midday_in(1))]
    )

    assert notices_of(http, signed_in) == []


def test_a_stale_feed_raises_one_amber_panel_naming_its_source_and_its_days(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    created = add_source(http, signed_in)
    seed_anchors(
        live_database_url,
        owner.tenant_id,
        created["id"],
        [
            an_event("tomorrow", start=midday_in(1)),
            # A second commitment on the same day, so the composer's own dedupe is exercised by two
            # rows arriving from the read rather than asserted about one.
            an_event("tomorrow-again", start=midday_in(1) + timedelta(hours=2)),
            an_event("later", start=midday_in(3)),
        ],
    )
    stop_answering(
        live_database_url,
        owner.tenant_id,
        created["id"],
        succeeded=NOW - STALE_AFTER - timedelta(hours=1),
    )

    raised = notices_of(http, signed_in)

    assert len(raised) == 1
    panel = raised[0]
    assert panel["id"] == f"{FEED_STALE}.{created['id']}"
    assert (panel["volume"], panel["pigment"]) == (PANEL, AMBER)
    # The frontend reads camelCase, and the field the surfaces mark a day from is `dates`.
    assert panel["scope"]["sourceId"] == created["id"]
    assert panel["scope"]["dates"] == [
        day_of(1),
        day_of(3),
    ]
    assert panel["stillWorks"] == list(FEED_STILL_WORKS)


def test_a_feed_that_has_never_answered_raises_on_its_first_failure_over_the_wire(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # Added seconds ago, failing on its first poll, and well inside the threshold. It raises anyway,
    # because there is no last success for it to be inside the threshold of.
    created = add_source(http, signed_in)
    stop_answering(live_database_url, owner.tenant_id, created["id"], succeeded=None)

    raised = notices_of(http, signed_in)

    assert [panel["id"] for panel in raised] == [f"{FEED_STALE}.{created['id']}"]
    # It fed no day, so it claims none. The feed is still reported, which is the point.
    assert raised[0]["scope"]["dates"] == []


def test_a_day_already_gone_is_not_named_over_the_wire(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # The lower end of the read, armed against a real row rather than against a double that already
    # applied the span. Without it the panel claims a day the reader cannot act on.
    created = add_source(http, signed_in)
    seed_anchors(
        live_database_url,
        owner.tenant_id,
        created["id"],
        [
            an_event("last-week", start=midday_in(-2)),
            an_event("tomorrow", start=midday_in(1)),
        ],
    )
    stop_answering(live_database_url, owner.tenant_id, created["id"], succeeded=None)

    raised = notices_of(http, signed_in)

    assert len(raised) == 1
    assert raised[0]["scope"]["dates"] == [day_of(1)]


def test_a_day_past_the_horizon_is_not_named_over_the_wire(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # The upper end, separately, so removing either bound is its own red rather than the two sharing
    # one assertion that cannot say which end moved.
    created = add_source(http, signed_in)
    seed_anchors(
        live_database_url,
        owner.tenant_id,
        created["id"],
        [
            an_event("tomorrow", start=midday_in(1)),
            an_event("beyond", start=midday_in(BEYOND_THE_HORIZON)),
        ],
    )
    stop_answering(live_database_url, owner.tenant_id, created["id"], succeeded=None)

    raised = notices_of(http, signed_in)

    assert len(raised) == 1
    assert raised[0]["scope"]["dates"] == [day_of(1)]


def test_a_stale_feed_names_its_own_days_and_not_another_sources(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # Two sources feeding two different days, one of them failing. Without the source predicate on
    # the read, the failing feed's panel claims a day it never fed, and a reader marks a day for an
    # outage that cannot have touched it.
    failing = add_source(http, signed_in)
    healthy = add_source(http, signed_in, external_id=OTHER_FEED, display_name="Society calendar")
    seed_anchors(
        live_database_url, owner.tenant_id, failing["id"], [an_event("mine", start=midday_in(1))]
    )
    seed_anchors(
        live_database_url,
        owner.tenant_id,
        healthy["id"],
        [an_event("theirs", start=midday_in(3))],
        external_id=OTHER_FEED,
    )
    stop_answering(live_database_url, owner.tenant_id, failing["id"], succeeded=None)

    raised = notices_of(http, signed_in)

    assert [panel["scope"]["sourceId"] for panel in raised] == [failing["id"]]
    assert raised[0]["scope"]["dates"] == [day_of(1)]


def test_a_feed_failing_inside_the_threshold_raises_nothing_over_the_wire(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    created = add_source(http, signed_in)
    stop_answering(
        live_database_url,
        owner.tenant_id,
        created["id"],
        succeeded=NOW - STALE_AFTER + timedelta(hours=1),
    )

    assert notices_of(http, signed_in) == []


def test_the_document_states_no_staleness_threshold_a_client_could_apply(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # The whole payload, read as a tree, because the defect is a figure a
    # client can read and apply from anywhere on the document rather than from one named field.
    created = add_source(http, signed_in)
    stop_answering(live_database_url, owner.tenant_id, created["id"], succeeded=None)
    body = http.get(SOURCES, headers=signed_in).json()

    assert _threshold_shaped_keys(body) == []


def _threshold_shaped_keys(node: object, path: str = "") -> list[str]:
    """Every key anywhere in the payload whose name reads as a staleness threshold."""
    if isinstance(node, dict):
        found: list[str] = []
        for key, value in node.items():
            here = f"{path}.{key}"
            if any(word in str(key).lower() for word in ("stale", "threshold")):
                found.append(here)
            found += _threshold_shaped_keys(value, here)
        return found
    if isinstance(node, list):
        found = []
        for index, item in enumerate(node):
            found += _threshold_shaped_keys(item, f"{path}[{index}]")
        return found
    return []


def test_the_payload_reading_reports_a_threshold_key_that_is_planted() -> None:
    # The positive control. Without it the assertion above passes on a reading that walks nothing.
    planted = {"sources": [{"syncState": {"staleAfterHours": 12}}], "notices": []}

    assert _threshold_shaped_keys(planted) == [".sources[0].syncState.staleAfterHours"]
