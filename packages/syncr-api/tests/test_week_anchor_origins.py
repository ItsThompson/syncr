"""The week payload's anchor-origin block: the feed behind each imported commitment.

The pure half proves what the composition decides over values, and what the wire renders for it.
The integration half proves the composed read against a real Postgres: a week whose plan binds
commitments from two feeds, one of them failing, answers ``possiblyStale`` on the failing feed's
blocks and ``false`` on the healthy one's, and answers nothing on a block the solver placed.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.anchors.reconcile import AnchorReconciler
from syncr_api.anchors.repository import AnchorRepository
from syncr_api.anchors.type_repository import AnchorTypeRepository
from syncr_api.calendars.config import ANCHOR_SOURCE, CALENDAR_SOURCES_PREFIX, ICS, STALE_AFTER
from syncr_api.calendars.events import FetchOutcome, RawEvent
from syncr_api.calendars.records import CalendarSourceRecord, SyncStateRecord
from syncr_api.calendars.repository import CalendarSourceRepository
from syncr_api.calendars.sync_state import recorded_failure
from syncr_api.concessions.config import WEEKS_PREFIX
from syncr_api.core.app_factory import create_app
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS
from syncr_api.plans.anchor_origins import (
    ANCHOR_BOUND_KINDS,
    AnchorOrigin,
    anchor_origins,
    bound_anchor_ids,
)
from syncr_api.plans.document_schemas import BlockResponse, PlanDocumentResponse
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_documents import stored_document
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.user_settings.solve_inputs import TrackedWeekInputVersions
from syncr_domain.identity import BindingKind, BindingRef, Origin, TransitLeg
from syncr_domain.intervals import Interval
from tests.live_tenants import PASSWORD, provision_owner, remove_tenant, run
from tests.plan_documents import (
    AREA_NAMES,
    WEEK,
    a_block,
    a_block_holding,
    a_document,
    between,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syncr_api.accounts.records import UserRecord
    from syncr_api.anchors.records import AnchorRecord
    from syncr_api.calendars.records import CalendarSourceId
    from syncr_api.core.settings import ServiceSettings
    from syncr_domain.identifiers import TenantId
    from syncr_domain.plan import Block

NOW = datetime(2026, 2, 12, 9, tzinfo=UTC)
HOME_ZONE = "Europe/London"
TENANT: TenantId = uuid4()
TIMETABLE = "https://example.ac.uk/timetable.ics"
SOCIETY = "https://example.ac.uk/society.ics"


# --------------------------------------------------------------------------------
# The sources the composition decides about
# --------------------------------------------------------------------------------


def a_source(
    source_id: CalendarSourceId,
    tenant_id: TenantId,
    *,
    last_success_at: datetime | None = NOW - timedelta(hours=1),
    last_error: str | None = None,
) -> CalendarSourceRecord:
    """One anchor feed, healthy. Failing is one override away."""
    return CalendarSourceRecord(
        id=source_id,
        tenant_id=tenant_id,
        provider=ICS,
        role=ANCHOR_SOURCE,
        display_name="University timetable",
        external_id="https://example.ac.uk/timetable.ics",
        included=True,
        horizon_days=None,
        created_at=NOW - timedelta(days=30),
        sync_state=SyncStateRecord(
            last_success_at=last_success_at,
            last_attempt_at=NOW - timedelta(minutes=5),
            last_error=last_error,
        ),
    )


def a_stale_source(source_id: CalendarSourceId, tenant_id: TenantId) -> CalendarSourceRecord:
    """One that has been failing longer than the threshold, with no success to fall back on."""
    return a_source(
        source_id,
        tenant_id,
        last_success_at=NOW - STALE_AFTER - timedelta(hours=1),
        last_error="The feed answered 503.",
    )


# --------------------------------------------------------------------------------
# Which commitments a week binds
# --------------------------------------------------------------------------------


def test_only_the_anchor_bound_kinds_are_collected() -> None:
    # All three anchor-bound members are stated against a literal, so a kind added to the binding
    # vocabulary reddens here rather than silently joining or silently staying out of the set this
    # module claims.
    assert (
        frozenset({BindingKind.ANCHOR, BindingKind.ANCHOR_PREP, BindingKind.ANCHOR_TRANSIT})
        == ANCHOR_BOUND_KINDS
    )


def test_a_weeks_imports_are_collected_distinctly_in_the_order_first_seen() -> None:
    # An anchor, its prep and one transit leg bind to ONE row, so three blocks are one import.
    anchor = a_block(origin=Origin.ANCHOR)
    prep = a_block(
        origin=Origin.PREP,
        binding=BindingRef.for_anchor_prep(anchor.binding.entity_id),
    )
    transit = a_block(
        origin=Origin.TRANSIT,
        binding=BindingRef.for_anchor_transit(anchor.binding.entity_id, leg=TransitLeg.BACK),
    )

    assert bound_anchor_ids((prep, transit, anchor)) == (anchor.binding.entity_id,)


def test_blocks_bound_to_no_import_collect_no_rows_at_all() -> None:
    assert bound_anchor_ids(a_document().blocks) == ()


# --------------------------------------------------------------------------------
# What the composition decides, per feed
# --------------------------------------------------------------------------------


def test_a_commitment_of_a_failing_feed_answers_true_and_a_healthy_one_false() -> None:
    stale_feed, healthy_feed = uuid4(), uuid4()
    stale_anchor, healthy_anchor = uuid4(), uuid4()

    decided = anchor_origins(
        {stale_anchor: stale_feed, healthy_anchor: healthy_feed},
        {
            stale_feed: a_stale_source(stale_feed, TENANT),
            healthy_feed: a_source(healthy_feed, TENANT),
        },
        now=NOW,
    )

    assert decided[stale_anchor] == AnchorOrigin(source_id=stale_feed, possibly_stale=True)
    assert decided[healthy_anchor] == AnchorOrigin(source_id=healthy_feed, possibly_stale=False)


def test_a_feed_failing_inside_the_threshold_is_not_stale() -> None:
    # The boundary's inside half. The composer's own suite owns the exclusive instant itself; this
    # pins only that the week payload reads the same decision and not a second threshold.
    failing_soon = uuid4()

    decided = anchor_origins(
        {uuid4(): failing_soon},
        {
            failing_soon: a_source(
                failing_soon,
                TENANT,
                last_success_at=NOW - STALE_AFTER + timedelta(hours=1),
                last_error="The feed answered 503.",
            )
        },
        now=NOW,
    )

    assert next(iter(decided.values())).possibly_stale is False


def test_an_excluded_source_is_never_stale_whatever_its_error_says() -> None:
    # The user asked for zero anchors from it, so an old error must not read as a failure.
    excluded_feed = uuid4()
    anchor = uuid4()
    excluded = dataclasses.replace(
        a_source(excluded_feed, TENANT, last_success_at=None, last_error="refused"),
        included=False,
    )

    decided = anchor_origins({anchor: excluded_feed}, {excluded_feed: excluded}, now=NOW)

    assert decided[anchor].possibly_stale is False


def test_a_commitment_whose_feed_is_gone_answers_nothing() -> None:
    # Removing a source cascades to its commitments while stored weeks naming them stay, so the
    # honest answer for one of those is absence rather than a claim about a feed never read.
    removed_feed, orphaned_anchor = uuid4(), uuid4()

    assert anchor_origins({orphaned_anchor: removed_feed}, {}, now=NOW) == {}


# --------------------------------------------------------------------------------
# What the wire renders
# --------------------------------------------------------------------------------


def a_document_rendering(block: Block, origin: AnchorOrigin | None) -> BlockResponse:
    """The wire block, rendered with ``origin`` as everything known about its feed."""
    origins = {} if origin is None else {block.binding.entity_id: origin}
    document = PlanDocumentResponse.of(
        a_document(week=WEEK, blocks=(block,)), area_names=AREA_NAMES, anchor_origins=origins
    )
    return document.blocks[0]


def test_an_anchor_block_renders_its_feed_and_the_decision_about_it() -> None:
    feed, anchor = uuid4(), uuid4()

    rendered = a_document_rendering(
        a_block(origin=Origin.ANCHOR, binding=BindingRef.for_anchor(anchor)),
        AnchorOrigin(source_id=feed, possibly_stale=True),
    )

    assert rendered.anchor_origin is not None
    assert rendered.anchor_origin.source_id == feed
    assert rendered.anchor_origin.possibly_stale is True


def test_a_solver_placed_block_answers_neither_feed_nor_verdict() -> None:
    assert BlockResponse.of(a_block(), None, None).anchor_origin is None


def test_an_import_without_a_known_feed_renders_null_rather_than_a_guess() -> None:
    rendered = a_document_rendering(
        a_block(origin=Origin.ANCHOR, binding=BindingRef.for_anchor(uuid4())), None
    )

    assert rendered.anchor_origin is None


# --------------------------------------------------------------------------------
# The composed week read, against a real Postgres
# --------------------------------------------------------------------------------

BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]


def an_event(uid: str, *, start: datetime) -> RawEvent:
    """One commitment inside ``WEEK``, so a block can bind to whatever row it becomes."""
    return RawEvent(
        uid=uid,
        series_uid=None,
        title="Compilers lecture",
        interval=Interval(start, start + timedelta(hours=1)),
        location=None,
        sequence=0,
        all_day=False,
    )


def seed_anchors(
    database_url: str,
    tenant_id: TenantId,
    source_id: CalendarSourceId,
    events: tuple[RawEvent, ...],
) -> None:
    """Put commitments in the table the way a sync would. There is no route that creates one."""

    async def seed() -> None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                await AnchorReconciler(
                    AnchorRepository(session, tenant_id),
                    AnchorTypeRepository(session, tenant_id),
                    versions=TrackedWeekInputVersions(
                        WeekInputVersionRepository(session, tenant_id), clock=lambda: NOW
                    ),
                    home_zone=HOME_ZONE,
                ).reconcile(
                    _a_source_row(source_id, tenant_id),
                    FetchOutcome(events=events, events_read=len(events), reparsed=True),
                )
        finally:
            await database.engine.dispose()

    run(seed())


def _a_source_row(source_id: UUID, tenant_id: TenantId) -> CalendarSourceRecord:
    return CalendarSourceRecord(
        id=source_id,
        tenant_id=tenant_id,
        provider=ICS,
        role=ANCHOR_SOURCE,
        display_name="University timetable",
        external_id="https://example.ac.uk/timetable.ics",
        included=True,
        horizon_days=None,
        created_at=NOW,
    )


def stop_answering(database_url: str, tenant_id: TenantId, source_id: CalendarSourceId) -> None:
    """Record a failed read on the source, through the writer that owns the sentence."""

    async def write() -> None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                await CalendarSourceRepository(session, tenant_id).save_sync_state(
                    source_id,
                    recorded_failure(
                        SyncStateRecord(last_success_at=None, last_attempt_at=None),
                        at=datetime.now(UTC),
                        reason="The feed answered 503.",
                    ),
                )
        finally:
            await database.engine.dispose()

    run(write())


def append_a_week_binding(
    database_url: str,
    tenant_id: TenantId,
    bindings: tuple[tuple[BindingRef, tuple[int, float, float]], ...],
) -> None:
    """A revision holding one block per binding, each at the hours of the week it names."""

    async def append() -> None:
        document = a_document(
            week=WEEK,
            blocks=tuple(
                a_block_holding(binding, between(start, end, day=day), week=WEEK)
                for binding, (day, start, end) in bindings
            ),
        )
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                await PlanRepository(session, tenant_id).append(
                    document=stored_document(document),
                    objective_breakdown={},
                    status="applied",
                    reason="horizon_advanced",
                    weight_set_version=1,
                    input_version=1,
                    created_at=datetime.now(UTC),
                )
        finally:
            await database.engine.dispose()

    run(append())


def anchors_of(
    database_url: str, tenant_id: TenantId, source_id: CalendarSourceId
) -> tuple[AnchorRecord, ...]:
    """The commitments a seeded feed contributed, so a block can bind to one by identity."""

    async def read() -> tuple[AnchorRecord, ...]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                return await AnchorRepository(session, tenant_id).list_for_source(source_id)
        finally:
            await database.engine.dispose()

    return run(read())


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


def add_source(http: TestClient, headers: dict[str, str], *, external_id: str) -> dict[str, Any]:
    response = http.post(
        CALENDAR_SOURCES_PREFIX,
        json={"provider": ICS, "displayName": "Timetable", "externalId": external_id},
        headers=headers,
    )
    assert response.status_code == HTTPStatus.CREATED, response.text
    created: dict[str, Any] = response.json()
    return created


def week_blocks(http: TestClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    response = http.get(f"{WEEKS_PREFIX}/{WEEK}", headers=headers)
    assert response.status_code == HTTPStatus.OK, response.text
    body: dict[str, Any] = response.json()
    live = body["live"]
    assert live is not None
    blocks: list[dict[str, Any]] = live["blocks"]
    return blocks


# Monday and Tuesday of the static week, at hours nothing else in the fixture claims.
DAY_OF = {"failing": (0, 9, 10), "healthy": (1, 9, 10), "solver": (2, 9, 10)}


@pytest.mark.integration
def test_the_composed_week_answers_stale_healthy_and_neither_on_one_payload(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
) -> None:
    failing = add_source(http, signed_in, external_id=TIMETABLE)
    healthy = add_source(http, signed_in, external_id=SOCIETY)
    seed_anchors(
        live_database_url,
        owner.tenant_id,
        failing["id"],
        (an_event("one", start=between(9, 10).start),),
    )
    seed_anchors(
        live_database_url,
        owner.tenant_id,
        healthy["id"],
        (an_event("two", start=between(9, 10, day=1).start),),
    )
    stop_answering(live_database_url, owner.tenant_id, failing["id"])

    failing_anchor = anchors_of(live_database_url, owner.tenant_id, failing["id"])[0].id
    healthy_anchor = anchors_of(live_database_url, owner.tenant_id, healthy["id"])[0].id
    append_a_week_binding(
        live_database_url,
        owner.tenant_id,
        (
            (BindingRef.for_anchor(failing_anchor), DAY_OF["failing"]),
            (BindingRef.for_anchor(healthy_anchor), DAY_OF["healthy"]),
            (BindingRef.for_task(uuid4()), DAY_OF["solver"]),
        ),
    )

    rendered = {
        (block["origin"], block["binding"]["entityId"]): block
        for block in week_blocks(http, signed_in)
    }

    failing_block = rendered[("anchor", str(failing_anchor))]
    assert failing_block["anchorOrigin"]["sourceId"] == failing["id"]
    assert failing_block["anchorOrigin"]["possiblyStale"] is True

    healthy_block = rendered[("anchor", str(healthy_anchor))]
    assert healthy_block["anchorOrigin"]["sourceId"] == healthy["id"]
    # False, not null: a healthy feed is an answer, which lets the screen tell the two apart.
    assert healthy_block["anchorOrigin"]["possiblyStale"] is False

    solver_placed = next(
        block for block in rendered.values() if block["binding"]["kind"] == BindingKind.TASK.value
    )
    assert solver_placed["anchorOrigin"] is None
