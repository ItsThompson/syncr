"""The projection end to end: the worker duty, the real composition, and a calendar that remembers.

Everything between the worker's tick and the HTTP boundary is real here: the queue, the claim, the
plan documents read through the append-only repository, the zone profile, the token refresh, the
adapter, the diff, the sync-state write and the operation transitions. Only Google's HTTP boundary
is faked, and the fake KEEPS STATE: it applies the inserts, patches and deletes it is sent and
answers the next read from what it holds. That is what makes convergence assertable rather than
argued -- a second drain over an unchanged plan has to write nothing at all.

**Nothing here has run against the real Google API.** The live suite that would prove syncr's
reading of Google's write contract needs a standing authorization only a person at a consent screen
can obtain, so the deployment default is that writing is off. These tests arm it explicitly, which
is also the honest statement of what is unverified: the shape of the requests is proven and the
provider's answers to them are not.

Seven groups.

**The drain.** A queued projection reaches the calendar, records the attempt on the write target,
and closes its operation. A second drain writes nothing.

**Coalescing.** Twelve queued projections cost one destructive reconciliation, because a projection
is idempotent over the whole horizon.

**Nothing to write to.** A tenant with no write target drains its queue and writes nothing; a target
that is an ICS feed is a stated failure rather than a crash.

**Only when the live plan changed.** A burst of week-version bumps -- which is what a pin does --
enqueues no projection, so the drain writes to the provider zero times.

**Failure.** A refused write fails the operations, records the reason on the target, and raises the
banner through the read a Settings screen makes. A dead grant raises the loudest notice in the
product through the token layer the write path shares with the read path.

**The metrics**, read out of the Prometheus exposition as a scraper reads it, including that a
refusal counts as a FAILED outcome so the alert that watches failures cannot be silent for it.

**The structure.** The projection is composed by the worker and by nothing else, and the adapter a
request composes cannot write.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from syncr_api.areas.repository import AreaRepository
from syncr_api.calendars.config import GOOGLE, HORIZON_DAYS_DEFAULT, ICS
from syncr_api.calendars.google_events import DELETE, PATCH, POST, SYNCR_KEY_PROPERTY
from syncr_api.calendars.injection import build_adapters
from syncr_api.calendars.projection_errors import ProjectionRefused
from syncr_api.calendars.projection_metrics import FAILED, PROJECTION_OUTCOMES, SUCCEEDED
from syncr_api.calendars.projection_notices import (
    BANNER_NOTICE_ID,
    OPERATION,
    PANEL_NOTICE_ID,
    projection_failure_notices,
)
from syncr_api.calendars.projection_pass import UNWRITABLE_TARGET
from syncr_api.calendars.projection_runner import ProjectionRunner
from syncr_api.calendars.repository import CalendarSourceRepository
from syncr_api.core.clock import utc_now
from syncr_api.core.db import create_database, create_db_engine, create_sessionmaker
from syncr_api.core.settings import (
    WORKER_SERVICE,
    EnvSettings,
    build_service_settings,
)
from syncr_api.google_account.crypto import TokenCipher
from syncr_api.google_account.notices import (
    BANNER_NOTICE_ID as EXPIRY_BANNER_ID,
)
from syncr_api.google_account.notices import (
    write_target_expiry_notices,
)
from syncr_api.google_account.repository import GoogleCredentialRepository
from syncr_api.horizon.runner import PlanHorizonRunner
from syncr_api.learned.repository import WeightSetRepository
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.routines.repository import RoutineRepository
from syncr_api.solving.config import (
    MAX_ATTEMPTS,
    PENDING,
    PROJECTION,
)
from syncr_api.solving.config import (
    SUCCEEDED as OPERATION_SUCCEEDED,
)
from syncr_api.solving.lifecycle import OperationLifecycle
from syncr_api.solving.repository import OperationRepository
from syncr_api.templates.repository import DayTypeRepository, WeekPatternRepository
from syncr_api.user_settings.repository import SettingsRepository
from syncr_api.worker.main import RUNNERS, WorkerContext
from syncr_common.metrics import REGISTRY
from syncr_domain.intervals import Interval
from syncr_domain.templates import WeekPattern
from syncr_domain.weeks import Weekday
from syncr_domain.zones import ZoneProfile
from tests.fake_google import (
    ACCESS_TOKEN,
    CLIENT_ID,
    CLIENT_SECRET,
    REDIRECT_URI,
    REFRESH_TOKEN,
    TEST_ENCRYPTION_KEY,
    events_page,
)
from tests.live_tenants import delete_tenant, seed_owner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings
    from syncr_domain.identifiers import TenantId

pytestmark = pytest.mark.integration

LONDON = "Europe/London"
# A Monday mid-morning, so a fortnight's horizon covers two ISO weeks rather than three.
NOW = datetime(2026, 2, 9, 9, tzinfo=UTC)
# A second later, because the maintainer schedules the projections it enqueues at its own instant,
# and a queue is due at or before the instant it is read at.
DRAINED_AT = NOW + timedelta(seconds=1)

TOKEN_HOST = "oauth2.googleapis.com"
CALENDAR_ID = "syncr-dev@group.calendar.google.com"
TARGET_NAME = "syncr (dev)"


@dataclass
class FakeCalendar:
    """A Google calendar that remembers: it applies what it is sent and answers reads from that.

    Not a script of canned answers. The claims here are about CONVERGENCE -- a second reconciliation
    over an unchanged plan writes nothing, a partial failure is repaired by the next attempt -- and
    neither is expressible against a transport that answers the same page every time.

    ``refuse_after`` refuses every write past that many, which drives a partial application.
    """

    events: dict[str, dict[str, Any]] = field(default_factory=dict)
    requests: list[httpx.Request] = field(default_factory=list)
    refuse_after: int | None = None
    refusal: httpx.Response | None = None
    token_answer: httpx.Response | None = None
    next_id: int = 0

    @property
    def writes(self) -> list[httpx.Request]:
        """Every mutating request to the CALENDAR, which is what the counting claims are about.

        The token endpoint is a POST too, and counting it would make "this pass wrote nothing" false
        for a pass that only refreshed a token.
        """
        return [
            one
            for one in self.requests
            if one.method in {POST, PATCH, DELETE} and one.url.host != TOKEN_HOST
        ]

    def methods(self) -> list[str]:
        return [one.method for one in self.writes]

    def titles(self) -> set[str]:
        return {str(held.get("summary")) for held in self.events.values()}

    def syncr_keys(self) -> set[str]:
        return {
            str(held.get("extendedProperties", {}).get("private", {}).get(SYNCR_KEY_PROPERTY))
            for held in self.events.values()
        }

    def add_by_hand(self, identifier: str, *, summary: str, start: datetime) -> None:
        """One event the user created in a calendar client: it carries no syncr key."""
        self.events[identifier] = {
            "id": identifier,
            "summary": summary,
            "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": (start + timedelta(hours=1)).isoformat()},
        }

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == TOKEN_HOST:
            return self.token_answer or _token_response()
        if request.method == "GET":
            return httpx.Response(200, content=events_page(*self.events.values()))
        if self.refuse_after is not None and len(self.writes) > self.refuse_after:
            return self.refusal or httpx.Response(503)
        return self._applied(request)

    def _applied(self, request: httpx.Request) -> httpx.Response:
        if request.method == DELETE:
            self.events.pop(request.url.path.rsplit("/", 1)[-1], None)
            return httpx.Response(204)
        body = json.loads(request.content)
        if request.method == PATCH:
            identifier = request.url.path.rsplit("/", 1)[-1]
        else:
            self.next_id += 1
            identifier = f"evt-{self.next_id}"
        self.events[identifier] = {**body, "id": identifier}
        return httpx.Response(200, json={"id": identifier})


def _token_response(**overrides: Any) -> httpx.Response:
    body: dict[str, Any] = {
        "access_token": ACCESS_TOKEN,
        "expires_in": 3599,
        "refresh_token": REFRESH_TOKEN,
        "scope": "https://www.googleapis.com/auth/calendar.events",
        "token_type": "Bearer",
    }
    body.update(overrides)
    return httpx.Response(200, json=body)


# --------------------------------------------------------------------------------
# The deployment, the tenant, and one pass
# --------------------------------------------------------------------------------


def worker_settings(*, writes: bool = True, client_id: str = CLIENT_ID) -> ServiceSettings:
    """A worker that has a Google client and, unless a test says otherwise, may write."""
    return build_service_settings(
        service=WORKER_SERVICE,
        env=EnvSettings(
            _env_file=None,
            google_oauth_client_id=client_id,
            google_oauth_client_secret=CLIENT_SECRET,
            google_oauth_redirect_uri=REDIRECT_URI,
            google_token_encryption_key=TEST_ENCRYPTION_KEY,
            google_projection_writes=writes,
        ),
    )


@pytest.fixture
async def engine(live_database_url: str) -> AsyncIterator[AsyncEngine]:
    live = create_db_engine(live_database_url)
    yield live
    await live.dispose()


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_sessionmaker(engine)


@pytest.fixture
async def owner(sessions: async_sessionmaker[AsyncSession]) -> AsyncIterator[UserRecord]:
    account = await seed_owner(sessions)
    yield account
    await delete_tenant(sessions, account.tenant_id)


@pytest.fixture
async def context(live_database_url: str) -> AsyncIterator[WorkerContext]:
    database = create_database(live_database_url)
    yield WorkerContext(settings=worker_settings(), database=database)
    await database.engine.dispose()


@pytest.fixture
def calendar() -> FakeCalendar:
    return FakeCalendar()


def clock_at(at: datetime = NOW) -> Any:
    """A clock that advances a millisecond per read, so each row takes a distinct instant."""

    class Ticking:
        def __init__(self) -> None:
            self.at = at

        def __call__(self) -> datetime:
            read = self.at
            self.at += timedelta(milliseconds=1)
            return read

    return Ticking()


async def drain(
    context: WorkerContext, calendar: FakeCalendar, *, now: datetime = DRAINED_AT
) -> int:
    """One projection pass, with Google's HTTP boundary faked at both clients."""
    transport = httpx.MockTransport(calendar.handle)
    async with (
        httpx.AsyncClient(transport=transport) as reads,
        httpx.AsyncClient(transport=transport) as writes,
    ):
        return await ProjectionRunner(clock=clock_at(now)).drain(context, reads, writes, now=now)


async def declare_a_planned_week(
    sessions: async_sessionmaker[AsyncSession],
    context: WorkerContext,
    tenant_id: TenantId,
    *,
    horizon_days: int = HORIZON_DAYS_DEFAULT,
    provider: str = GOOGLE,
) -> None:
    """The least a projection needs: a plan for the horizon's weeks, and a calendar to write to.

    The plan is produced by the horizon maintainer rather than inserted, so what is projected is a
    document production code wrote, and the projections in the queue are the ones it enqueued.
    """
    await declare_the_minimum(sessions, tenant_id)
    await declare_a_write_target(sessions, tenant_id, horizon_days=horizon_days, provider=provider)
    await store_a_grant(sessions, tenant_id)
    await PlanHorizonRunner(clock=clock_at()).plan(context, now=NOW)


async def declare_the_minimum(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    """Areas, a day shape, a weight set and a home zone: the least a plan can exist from."""
    async with sessions() as session, session.begin():
        settings = SettingsRepository(session, tenant_id)
        locked = await settings.lock(created_at=NOW)
        await settings.write(
            visible_hours=locked.visible_hours,
            day_start=locked.day_start,
            day_end=locked.day_end,
            review_cadence=locked.review_cadence,
            home_zone=LONDON,
        )
        await AreaRepository(session, tenant_id).create(
            parent_id=None,
            name="Career",
            pigment_index=1,
            budget_percent=Decimal(30),
            floor_hours=Decimal(3),
            created_at=NOW,
        )
        day_type = await DayTypeRepository(session, tenant_id).create(
            name="Weekday", created_at=NOW
        )
        await WeekPatternRepository(session, tenant_id).replace(
            WeekPattern(dict.fromkeys(Weekday, day_type.id))
        )
        await WeightSetRepository(session, tenant_id).seed_hand_tuned(at=NOW)
        # One routine, so the materialized week holds blocks at all: a frame block projects, and its
        # Sunday-night occurrence is the span that crosses the ISO week boundary in real life.
        await RoutineRepository(session, tenant_id).create(
            title="Sleep",
            target_time=time(23, 0),
            duration_minutes=8 * 60,
            min_duration_minutes=6 * 60,
            flex_band_minutes=60,
            created_at=NOW,
        )


async def declare_a_write_target(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    *,
    horizon_days: int = HORIZON_DAYS_DEFAULT,
    provider: str = GOOGLE,
) -> None:
    async with sessions() as session, session.begin():
        sources = CalendarSourceRepository(session, tenant_id)
        target = await sources.create(
            provider=provider,  # type: ignore[arg-type]
            role="anchor-source",
            display_name=TARGET_NAME,
            external_id=CALENDAR_ID if provider == GOOGLE else "https://example.test/plan.ics",
            included=True,
            horizon_days=None,
            created_at=NOW,
        )
        await sources.designate_write_target(target.id, horizon_days=horizon_days)


async def store_a_grant(sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId) -> None:
    """A connected Google account, as the callback would have stored one."""
    async with sessions() as session, session.begin():
        await GoogleCredentialRepository(session, tenant_id).connect(
            encrypted_refresh_token=TokenCipher(TEST_ENCRYPTION_KEY).encrypt(REFRESH_TOKEN),
            granted_scopes=("https://www.googleapis.com/auth/calendar.events",),
            at=NOW,
        )


async def projections_of(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> list[Any]:
    async with sessions() as session:
        return await OperationRepository(session, tenant_id).page(limit=50, kind=PROJECTION)


async def write_target_of(sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId) -> Any:
    async with sessions() as session:
        return await CalendarSourceRepository(session, tenant_id).write_target()


def sample(family: str, **labels: str) -> float:
    """One metric sample, read as a scraper reads it rather than through a private attribute."""
    value = REGISTRY.get_sample_value(family, labels or None)
    assert value is not None, f"{family}{labels} is not in the registry"
    return value


# --------------------------------------------------------------------------------
# The drain
# --------------------------------------------------------------------------------


async def test_a_queued_projection_writes_the_plan_to_the_write_target(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    calendar: FakeCalendar,
) -> None:
    await declare_a_planned_week(sessions, context, owner.tenant_id)

    performed = await drain(context, calendar)

    assert performed == 1
    assert calendar.methods() == [POST] * len(calendar.events)
    assert calendar.events, "the plan reached no event onto the target"
    # Every event syncr wrote carries the diff key, which is what the next reconciliation pairs on.
    assert None not in calendar.syncr_keys()


async def test_every_queued_projection_is_closed_as_succeeded(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    calendar: FakeCalendar,
) -> None:
    await declare_a_planned_week(sessions, context, owner.tenant_id)

    await drain(context, calendar)

    statuses = {row.status for row in await projections_of(sessions, owner.tenant_id)}
    assert statuses == {OPERATION_SUCCEEDED}


async def test_the_write_target_records_when_the_plan_last_reached_the_phone(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    calendar: FakeCalendar,
) -> None:
    """Staleness is the difference between the last attempt and the last success, on the source."""
    await declare_a_planned_week(sessions, context, owner.tenant_id)

    await drain(context, calendar)

    target = await write_target_of(sessions, owner.tenant_id)
    assert target.sync_state.last_success_at is not None
    assert target.sync_state.last_attempt_at == target.sync_state.last_success_at
    assert target.sync_state.last_error is None


async def test_a_second_drain_over_an_unchanged_plan_writes_nothing(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    calendar: FakeCalendar,
) -> None:
    """The convergence claim, and the reason a destructive path is safe to run often."""
    await declare_a_planned_week(sessions, context, owner.tenant_id)
    await drain(context, calendar)
    written = len(calendar.writes)
    async with sessions() as session, session.begin():
        await OperationLifecycle(OperationRepository(session, owner.tenant_id), utc_now).enqueue(
            kind=PROJECTION,
            iso_week=(await projections_of(sessions, owner.tenant_id))[0].iso_week,
            due_at=NOW,
        )

    await drain(context, calendar)

    assert len(calendar.writes) == written


async def test_an_event_the_user_created_by_hand_is_removed_and_counted(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    calendar: FakeCalendar,
) -> None:
    await declare_a_planned_week(sessions, context, owner.tenant_id)
    calendar.add_by_hand("evt-dentist", summary="Dentist", start=NOW + timedelta(days=1))
    # The SUM rather than the count: a histogram's `_count` is the number of observations, and every
    # reconciliation observes every action including the zeroes, so `_count` moves whether or not
    # anything was deleted. Read as a delta, because other tests in this file observe it too.
    before = sample("syncr_projection_events_sum", action="foreign_deleted")

    await drain(context, calendar)

    assert "evt-dentist" not in calendar.events
    assert sample("syncr_projection_events_sum", action="foreign_deleted") == before + 1


# --------------------------------------------------------------------------------
# Coalescing
# --------------------------------------------------------------------------------


async def test_a_span_reaching_into_the_horizon_from_the_previous_week_is_kept(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    calendar: FakeCalendar,
) -> None:
    """The sleep in progress at local midnight belongs to the week that is ending.

    Its interval overlaps the horizon and Google's own window-bounded read returns it, so read over
    the horizon's own weeks alone the diff would find it under syncr's key, not desired, and delete
    it: every Monday morning the in-progress sleep event would leave the phone while the live plan
    still held it. The week list therefore reaches one week back.
    """
    await declare_the_minimum(sessions, owner.tenant_id)
    await declare_a_write_target(sessions, owner.tenant_id)
    await store_a_grant(sessions, owner.tenant_id)
    # Plan last week as well as this one, by running the maintainer a week earlier: only a week that
    # HAS a plan can contribute a block, and last week's is the one under test.
    await PlanHorizonRunner(clock=clock_at(NOW - timedelta(days=7))).plan(
        context, now=NOW - timedelta(days=7)
    )
    await PlanHorizonRunner(clock=clock_at()).plan(context, now=NOW)

    await drain(context, calendar)

    # Sunday 23:00 London to Monday 07:00, which is 2026-W06's last frame occurrence and covers the
    # instant the horizon begins at.
    starts = {str(held["start"]["dateTime"]) for held in calendar.events.values()}
    assert "2026-02-08T23:00:00+00:00" in starts, sorted(starts)[:4]


async def test_twelve_queued_projections_cost_one_reconciliation(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    calendar: FakeCalendar,
) -> None:
    """Twelve destructive reconciliations in one weekly session would be slow and visible."""
    await declare_a_planned_week(sessions, context, owner.tenant_id)
    week = (await projections_of(sessions, owner.tenant_id))[0].iso_week
    async with sessions() as session, session.begin():
        lifecycle = OperationLifecycle(OperationRepository(session, owner.tenant_id), utc_now)
        for _ in range(10):
            await lifecycle.enqueue(kind=PROJECTION, iso_week=week, due_at=NOW)

    performed = await drain(context, calendar)

    assert performed == 1
    reads = [one for one in calendar.requests if one.method == "GET"]
    assert len(reads) == 1
    statuses = {row.status for row in await projections_of(sessions, owner.tenant_id)}
    assert statuses == {OPERATION_SUCCEEDED}


async def test_an_empty_queue_writes_nothing_and_reads_nothing(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    calendar: FakeCalendar,
) -> None:
    await declare_the_minimum(sessions, owner.tenant_id)
    await declare_a_write_target(sessions, owner.tenant_id)

    performed = await drain(context, calendar)

    assert performed == 0
    assert calendar.requests == []


# --------------------------------------------------------------------------------
# Nothing to write to
# --------------------------------------------------------------------------------


async def test_a_tenant_with_no_write_target_drains_its_queue_without_writing(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    calendar: FakeCalendar,
) -> None:
    """Nothing happened, by the user's own instruction: the answer an excluded source gets."""
    await declare_the_minimum(sessions, owner.tenant_id)
    await PlanHorizonRunner(clock=clock_at()).plan(context, now=NOW)

    performed = await drain(context, calendar)

    assert performed == 0
    assert calendar.requests == []
    statuses = {row.status for row in await projections_of(sessions, owner.tenant_id)}
    assert statuses == {OPERATION_SUCCEEDED}
    # And no attempt is recorded against any source, because none was made: there is nothing to
    # record one on.
    assert await write_target_of(sessions, owner.tenant_id) is None


async def test_an_ics_write_target_is_a_stated_refusal_rather_than_a_crash(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    calendar: FakeCalendar,
) -> None:
    """A feed is published by somebody else, so a source syncr cannot write can hold the role."""
    await declare_a_planned_week(sessions, context, owner.tenant_id, provider=ICS)

    performed = await drain(context, calendar)

    assert performed == 0
    assert calendar.requests == []
    target = await write_target_of(sessions, owner.tenant_id)
    assert target.sync_state.last_error is not None
    assert UNWRITABLE_TARGET.format(provider=ICS)[:40] in target.sync_state.last_error


async def test_an_unwritable_target_is_not_retried_because_retrying_cannot_clear_it(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    calendar: FakeCalendar,
) -> None:
    """A source's provider is immutable, so every attempt reaches the first one's conclusion.

    Classified as a failure it would spend three attempts and two backoffs per plan change to say
    what it already knew, and the runbook's own table says the repair is to designate a different
    calendar rather than to wait.
    """
    await declare_a_planned_week(sessions, context, owner.tenant_id, provider=ICS)

    await drain(context, calendar)

    rows = await projections_of(sessions, owner.tenant_id)
    assert {row.error_code for row in rows} == {ProjectionRefused.code}


# --------------------------------------------------------------------------------
# Only when the live plan changed
# --------------------------------------------------------------------------------


async def test_a_burst_of_version_bumps_writes_to_the_provider_zero_times(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    calendar: FakeCalendar,
) -> None:
    """A pin bumps the week's input version and changes no live plan, so it enqueues no projection.

    Driven over the bump itself rather than over the pin route, which is a later ticket's: what the
    rule is about is that a mutation which appends no revision reaches the provider zero times.
    """
    await declare_a_planned_week(sessions, context, owner.tenant_id)
    await drain(context, calendar)
    written = len(calendar.writes)
    week = (await projections_of(sessions, owner.tenant_id))[0].iso_week

    async with sessions() as session, session.begin():
        versions = WeekInputVersionRepository(session, owner.tenant_id)
        for _ in range(12):
            await versions.bump(week, at=NOW)

    performed = await drain(context, calendar)

    assert performed == 0
    assert len(calendar.writes) == written
    pending = [
        row for row in await projections_of(sessions, owner.tenant_id) if row.status == PENDING
    ]
    assert pending == []


def test_a_projection_is_enqueued_only_beside_an_appended_revision(source_root: Any) -> None:
    """The structural half: one enqueue site in the tree, and it follows a revision append.

    A burst of pins writing zero times is a property of WHERE a projection is enqueued, so a second
    enqueue site added later would break the rule without breaking the test above.
    """
    sites = [
        path
        for path in source_root.rglob("*.py")
        if f"enqueue(kind={PROJECTION.upper()}" in path.read_text()
    ]

    assert [path.name for path in sites] == ["production.py"]
    body = sites[0].read_text()
    assert body.index("revisions.append") < body.index(f"enqueue(kind={PROJECTION.upper()}")


# --------------------------------------------------------------------------------
# Failure
# --------------------------------------------------------------------------------


async def test_a_refused_write_fails_every_claimed_operation(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    calendar: FakeCalendar,
) -> None:
    await declare_a_planned_week(sessions, context, owner.tenant_id)
    calendar.refuse_after = 0

    performed = await drain(context, calendar)

    assert performed == 0
    rows = await projections_of(sessions, owner.tenant_id)
    # Failed with an attempt left comes back as pending, which is what a retrying job looks like.
    assert {row.status for row in rows} == {PENDING}
    assert all(row.error_code == "projection_failed" for row in rows)


async def test_a_retry_behind_its_backoff_is_not_claimed_before_it_is_due(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    calendar: FakeCalendar,
) -> None:
    """A failure that will run again is scheduled, and the queue reads only what is due.

    The bite check found this: dropping the schedule from the queue's own predicate passed every
    test, so nothing held the one property a backoff exists for. A drain that ignored it would spend
    a destructive reconciliation per tick against a provider that has just refused one.
    """
    await declare_a_planned_week(sessions, context, owner.tenant_id)
    calendar.refuse_after = 0
    await drain(context, calendar)
    refused = len(calendar.requests)
    rows = await projections_of(sessions, owner.tenant_id)
    assert {row.status for row in rows} == {PENDING}, "the failures have to be retrying"
    assert all(row.scheduled_for > DRAINED_AT for row in rows), "pushed out by the backoff"

    performed = await drain(context, calendar)

    assert performed == 0
    assert len(calendar.requests) == refused


async def test_a_partially_applied_write_leaves_what_landed_and_records_the_failure(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    calendar: FakeCalendar,
) -> None:
    """A partial write must not read as a success: the target holds part of the plan and says so."""
    await declare_a_planned_week(sessions, context, owner.tenant_id)
    calendar.refuse_after = 1

    await drain(context, calendar)

    assert len(calendar.events) == 1
    target = await write_target_of(sessions, owner.tenant_id)
    assert target.sync_state.last_error is not None
    assert target.sync_state.last_success_at is None


async def test_the_next_attempt_converges_after_a_partial_write(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    calendar: FakeCalendar,
) -> None:
    """The whole reason an ambiguous write is not retried in place: the next pass repairs it."""
    await declare_a_planned_week(sessions, context, owner.tenant_id)
    calendar.refuse_after = 1
    await drain(context, calendar)
    partial = len(calendar.events)

    calendar.refuse_after = None
    async with sessions() as session, session.begin():
        await OperationLifecycle(OperationRepository(session, owner.tenant_id), utc_now).enqueue(
            kind=PROJECTION,
            iso_week=(await projections_of(sessions, owner.tenant_id))[0].iso_week,
            due_at=NOW,
        )
    await drain(context, calendar)

    assert len(calendar.events) > partial
    target = await write_target_of(sessions, owner.tenant_id)
    assert target.sync_state.last_error is None


async def test_a_failure_raises_the_banner_a_settings_screen_reads(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    calendar: FakeCalendar,
) -> None:
    """Which operation failed, the retry count, and that the previous projection still stands."""
    await declare_a_planned_week(sessions, context, owner.tenant_id)
    calendar.refuse_after = 0
    await drain(context, calendar)

    target = await write_target_of(sessions, owner.tenant_id)
    async with sessions() as session:
        last = (await OperationRepository(session, owner.tenant_id).page(limit=1, kind=PROJECTION))[
            0
        ]
    raised = projection_failure_notices(target, last, now=NOW + timedelta(hours=2))

    assert [notice.id for notice in raised] == [BANNER_NOTICE_ID, PANEL_NOTICE_ID]
    banner = raised[0]
    assert banner.volume == "banner"
    assert banner.pigment == "oxide"
    assert OPERATION in banner.detail
    assert TARGET_NAME in banner.detail
    assert f"attempt {last.attempt} of {MAX_ATTEMPTS}" in banner.detail
    assert "untouched" in banner.detail
    assert banner.still_works


async def test_a_healthy_projection_raises_no_notice(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    calendar: FakeCalendar,
) -> None:
    await declare_a_planned_week(sessions, context, owner.tenant_id)
    await drain(context, calendar)

    target = await write_target_of(sessions, owner.tenant_id)

    assert projection_failure_notices(target, None, now=NOW) == ()


async def test_a_dead_grant_raises_the_loudest_notice_through_the_token_layer(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    calendar: FakeCalendar,
) -> None:
    """The write path shares the token source with the read path, which is what records an expiry.

    Asserted through the credential and the notice rather than through the writer, because the claim
    is that the expiry is RECORDED where the loudest notice in the product reads it from.
    """
    await declare_a_planned_week(sessions, context, owner.tenant_id)
    calendar.token_answer = httpx.Response(400, json={"error": "invalid_grant"})

    await drain(context, calendar)

    async with sessions() as session:
        credential = await GoogleCredentialRepository(session, owner.tenant_id).read()
    assert credential is not None
    assert credential.refresh_failing_since is not None
    raised = write_target_expiry_notices(credential, now=NOW + timedelta(days=1))
    assert next(notice.id for notice in raised) == EXPIRY_BANNER_ID
    assert calendar.writes == []


# --------------------------------------------------------------------------------
# The metrics
# --------------------------------------------------------------------------------


async def test_a_reconciliation_reports_its_duration_and_every_action(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    calendar: FakeCalendar,
) -> None:
    await declare_a_planned_week(sessions, context, owner.tenant_id)
    before = sample("syncr_projection_duration_seconds_count", outcome=SUCCEEDED)

    await drain(context, calendar)

    assert sample("syncr_projection_duration_seconds_count", outcome=SUCCEEDED) == before + 1
    for action in ("inserted", "patched", "deleted", "foreign_deleted"):
        assert sample("syncr_projection_events_count", action=action) > 0


async def test_a_refusal_is_reported_as_a_failed_outcome(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    calendar: FakeCalendar,
) -> None:
    """A third outcome would make ``ProjectionFailing`` silent for a deployment that will not write.

    The consequence of a refusal is the consequence of a failure: the plan is not reaching the
    phone.
    """
    await declare_a_planned_week(sessions, context, owner.tenant_id)
    context = WorkerContext(settings=worker_settings(writes=False), database=context.database)
    before = sample("syncr_projection_duration_seconds_count", outcome=FAILED)

    await drain(context, calendar)

    assert sample("syncr_projection_duration_seconds_count", outcome=FAILED) == before + 1
    assert calendar.writes == []
    rows = await projections_of(sessions, owner.tenant_id)
    assert all(row.error_code == ProjectionRefused.code for row in rows)


async def test_the_outcome_label_set_stays_the_two_the_vocabulary_names(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    calendar: FakeCalendar,
) -> None:
    """A third value would make ``ProjectionFailing`` silent for a deployment that will not write.

    Read off the exposition rather than trusted, so a member added later has to move this line.
    """
    await declare_a_planned_week(sessions, context, owner.tenant_id)
    await drain(context, calendar)
    await drain(
        WorkerContext(settings=worker_settings(writes=False), database=context.database), calendar
    )

    observed = {
        one.labels["outcome"]
        for family in REGISTRY.collect()
        if family.name == "syncr_projection_duration_seconds"
        for one in family.samples
    }

    assert observed == set(PROJECTION_OUTCOMES)


async def test_the_arming_state_is_exported_whether_or_not_anything_is_due(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    calendar: FakeCalendar,
) -> None:
    """The term an alert inhibits on has to be present, or the alert is silent or always firing.

    Set on every pass rather than where a write is composed, so an idle deployment still exports it:
    a deployment with writes off produces a failure per plan change, and this is what lets ticket 54
    state ``ProjectionFailing`` as "failures AND writes enabled" instead of choosing between an
    alert that never fires and one that always does.
    """
    await declare_the_minimum(sessions, owner.tenant_id)

    await drain(
        WorkerContext(settings=worker_settings(writes=False), database=context.database), calendar
    )
    assert sample("syncr_projection_writes_enabled") == 0

    await drain(context, calendar)
    assert sample("syncr_projection_writes_enabled") == 1
    assert calendar.requests == [], "nothing was due, and the gauge is set regardless"


async def test_a_deployment_that_will_not_write_says_so_in_the_banner(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    calendar: FakeCalendar,
) -> None:
    await declare_a_planned_week(sessions, context, owner.tenant_id)
    await drain(
        WorkerContext(settings=worker_settings(writes=False), database=context.database), calendar
    )

    target = await write_target_of(sessions, owner.tenant_id)
    (banner, _panel) = projection_failure_notices(target, None, now=NOW)

    assert "switched off" in banner.detail
    assert "GOOGLE_PROJECTION_WRITES" in banner.detail


# --------------------------------------------------------------------------------
# The structure
# --------------------------------------------------------------------------------


def test_the_runner_is_on_the_worker_loop() -> None:
    """Nothing else drains the queue, so an unregistered runner is a calendar that never updates."""
    assert any(isinstance(runner, ProjectionRunner) for runner in RUNNERS)


def test_the_projection_is_composed_by_the_worker_and_by_nothing_else(source_root: Any) -> None:
    """The projection never sits on a request, and this is what makes that structural.

    Three constructions carry the ability to write a calendar: the writer, the adapter that holds
    it, and the component that reads the plan for it. Each appears in exactly one module.
    """
    built: dict[str, set[str]] = {
        "GoogleEventWriter(": set(),
        "build_write_target_adapter(": set(),
        "ProjectionWriter(": set(),
    }
    for path in source_root.rglob("*.py"):
        body = path.read_text()
        for construction in built:
            if construction in body and not body.count(f"def {construction}"):
                built[construction].add(path.name)

    assert built["GoogleEventWriter("] == {"injection.py"}
    # The duty claims and contains a fault; the pass performs the write. Both are the worker's, and
    # nothing on a request path is in either set.
    assert built["build_write_target_adapter("] == {"projection_pass.py"}
    assert built["ProjectionWriter("] == {"projection_pass.py"}


async def test_the_adapter_a_request_composes_cannot_write(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    """Every route's Google adapter holds the refusing arm, whatever the deployment allows.

    Driven through the adapter's own contract rather than by reading the arm off it: what matters is
    that a caller reaching ``reconcile`` from a request is refused, and refused before it reads.
    """
    await declare_a_write_target(sessions, owner.tenant_id)
    async with sessions() as session, httpx.AsyncClient() as client:
        adapters, _reader = build_adapters(
            worker_settings(),
            session,
            owner.tenant_id,
            feeds=client,
            google=client,
            profile=ZoneProfile(home_zone=LONDON),
            horizon=Interval(NOW, NOW + timedelta(days=14)),
        )
        target = await CalendarSourceRepository(session, owner.tenant_id).write_target()
        assert target is not None

        # A deployment that is fully armed for the worker, and this adapter still will not write.
        with pytest.raises(ProjectionRefused, match="background worker"):
            await adapters[GOOGLE].reconcile(target, [])  # type: ignore[attr-defined]
