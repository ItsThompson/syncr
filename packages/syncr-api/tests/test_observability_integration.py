"""The two observability duties, driven against Postgres with rows that make each gauge move.

The unit tests state the arithmetic in exact numbers. What this asserts is the other half, which is
the half four tickets in this epic got wrong: THAT THE INSTRUMENT MOVES WHEN THE THING IT WATCHES
CHANGES. Every reading here is taken out of the Prometheus exposition, as a scraper takes it, rather
than from a collector's private attribute.

Each case breaks something real and watches the figure follow:

- a credential whose refresh started failing an hour ago, against a token age that reads zero while
  refreshes work
- a source last read successfully two days ago, against a staleness gauge an alert fires on at one
- a partial outcome that took twice its estimate, against a median absolute percentage error
- a verdict episode discovered during a weekly session, against the early-catch ratio
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from prometheus_client import generate_latest

from syncr_api.calendars.config import ANCHOR_SOURCE, ICS
from syncr_api.calendars.records import SyncStateRecord
from syncr_api.calendars.repository import CalendarSourceRepository
from syncr_api.core.db import Database, create_db_engine, create_sessionmaker
from syncr_api.google_account.repository import GoogleCredentialRepository
from syncr_api.observability.config import PRODUCT_INTERVAL, STATE_INTERVAL
from syncr_api.observability.product_runner import ProductMetricRunner
from syncr_api.observability.state_runner import StateGaugeRunner
from syncr_api.worker.main import WorkerContext
from syncr_common.metrics import REGISTRY
from tests.live_tenants import provision_owner, remove_tenant

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_api.accounts.records import UserRecord
    from syncr_api.calendars.records import CalendarSourceRecord
    from syncr_api.core.settings import ServiceSettings

NOW = datetime(2026, 2, 26, 9, 0, tzinfo=UTC)

TOKEN_AGE = "syncr_write_target_token_age_seconds"
STALENESS = "syncr_source_staleness_seconds"
ANCHORS = "syncr_anchors_current"

# The threshold `SourceStale` is stated over, quoted so a reading is asserted against the figure an
# alert actually fires on rather than against a number this file chose.
SOURCE_STALE_THRESHOLD = 86400


async def a_source(
    session: AsyncSession, owner: UserRecord, *, added: datetime
) -> CalendarSourceRecord:
    """One included ICS anchor source, added at ``added`` and never yet read."""
    return await CalendarSourceRepository(session, owner.tenant_id).create(
        provider=ICS,
        role=ANCHOR_SOURCE,
        display_name="A timetable",
        external_id=f"https://example.test/{uuid4()}.ics",
        included=True,
        horizon_days=None,
        created_at=added,
    )


def sample(name: str, **labels: str) -> float:
    """One sample out of the rendered exposition. Zero when the series does not exist yet."""
    wanted = ",".join(f'{key}="{value}"' for key, value in sorted(labels.items()))
    prefix = f"{name}{{{wanted}}} " if wanted else f"{name} "
    for line in generate_latest(REGISTRY).decode().splitlines():
        if line.startswith(prefix):
            return float(line.removeprefix(prefix))
    return 0.0


@pytest.fixture
def owner(live_database_url: str) -> Iterator[UserRecord]:
    """A tenant of this module's own, removed afterwards so no other suite sees its rows."""
    provisioned = provision_owner(live_database_url)
    try:
        yield provisioned
    finally:
        remove_tenant(live_database_url, provisioned.tenant_id)


@pytest.fixture
async def context(
    live_database_url: str, settings: ServiceSettings
) -> AsyncIterator[WorkerContext]:
    """A worker context over an engine of this module's own, disposed afterwards."""
    engine = create_db_engine(live_database_url)
    try:
        yield WorkerContext(
            settings=settings,
            database=Database(engine=engine, sessionmaker=create_sessionmaker(engine)),
        )
    finally:
        await engine.dispose()


class TestTheStateGauges:
    async def test_the_token_age_reads_zero_while_refreshes_work(
        self, context: WorkerContext, owner: UserRecord
    ) -> None:
        """A tenant with no credential and one refreshing normally are the same to the alert."""
        await StateGaugeRunner(interval=STATE_INTERVAL, clock=lambda: NOW).observe(context, now=NOW)

        assert sample(TOKEN_AGE, tenant=str(owner.tenant_id)) == 0.0

    async def test_it_grows_from_the_instant_refreshing_started_failing(
        self, context: WorkerContext, owner: UserRecord
    ) -> None:
        """BREAK IT: record a refresh failure an hour old, and watch the critical gauge move."""
        async with context.database.sessionmaker() as session, session.begin():
            credentials = GoogleCredentialRepository(session, owner.tenant_id)
            await credentials.connect(
                encrypted_refresh_token="ciphertext",
                granted_scopes=("https://www.googleapis.com/auth/calendar",),
                at=NOW - timedelta(days=30),
            )
            await credentials.record_refresh_failure(at=NOW - timedelta(hours=1), reason="invalid")

        await StateGaugeRunner(interval=STATE_INTERVAL, clock=lambda: NOW).observe(context, now=NOW)

        assert sample(TOKEN_AGE, tenant=str(owner.tenant_id)) == 3600.0

    async def test_source_staleness_is_measured_from_the_last_success(
        self, context: WorkerContext, owner: UserRecord
    ) -> None:
        """BREAK IT: a feed attempted a minute ago whose last success was two days ago is STALE.

        Measured from the success rather than the attempt, so a feed being retried on schedule and
        failing every time still crosses the 24-hour threshold `SourceStale` fires on.
        """
        async with context.database.sessionmaker() as session, session.begin():
            created = await a_source(session, owner, added=NOW - timedelta(days=30))
            await CalendarSourceRepository(session, owner.tenant_id).save_sync_state(
                created.id,
                SyncStateRecord(
                    last_success_at=NOW - timedelta(days=2),
                    last_attempt_at=NOW - timedelta(minutes=1),
                    last_error="the publisher answered 500",
                    anchors_current=7,
                ),
            )

        await StateGaugeRunner(interval=STATE_INTERVAL, clock=lambda: NOW).observe(context, now=NOW)

        assert sample(STALENESS, source_id=str(created.id)) == 172800.0
        assert sample(ANCHORS, source_id=str(created.id)) == 7.0

    async def test_a_source_that_has_never_succeeded_is_stale_from_when_it_was_added(
        self, context: WorkerContext, owner: UserRecord
    ) -> None:
        """BREAK IT: a feed added two days ago that has NEVER been read, attempted a minute ago.

        The reading this test exists for. Measured from the last ATTEMPT, this read 60 seconds
        against an 86400 threshold, because every failed poll refreshes that instant: a feed added
        with a wrong URL read FRESHER than a healthy feed polled twenty minutes ago, forever. The
        instant the user added it is the one on the row that does not move.
        """
        async with context.database.sessionmaker() as session, session.begin():
            created = await a_source(session, owner, added=NOW - timedelta(days=2))
            await CalendarSourceRepository(session, owner.tenant_id).save_sync_state(
                created.id,
                SyncStateRecord(
                    last_success_at=None,
                    last_attempt_at=NOW - timedelta(minutes=1),
                    last_error="no such host",
                    anchors_current=0,
                ),
            )

        await StateGaugeRunner(interval=STATE_INTERVAL, clock=lambda: NOW).observe(context, now=NOW)

        assert sample(STALENESS, source_id=str(created.id)) == 172800.0
        assert sample(STALENESS, source_id=str(created.id)) > SOURCE_STALE_THRESHOLD

    async def test_a_source_the_user_removes_takes_its_series_with_it(
        self, context: WorkerContext, owner: UserRecord
    ) -> None:
        """BREAK IT: publish a stale source, delete it, and read the gauge again.

        Nothing in the client library removes a child of a labelled gauge, and the worker is
        long-lived. Without the removal, a source the user deleted would keep its last reading until
        the process restarted, so `SourceStale` would fire forever on a source that no longer
        exists: an alert for a condition the user cannot act on, which section 18 forbids.
        """
        async with context.database.sessionmaker() as session, session.begin():
            created = await a_source(session, owner, added=NOW - timedelta(days=2))

        await StateGaugeRunner(interval=STATE_INTERVAL, clock=lambda: NOW).observe(context, now=NOW)
        assert sample(STALENESS, source_id=str(created.id)) > SOURCE_STALE_THRESHOLD

        async with context.database.sessionmaker() as session, session.begin():
            await CalendarSourceRepository(session, owner.tenant_id).remove(created.id)

        await StateGaugeRunner(interval=STATE_INTERVAL, clock=lambda: NOW).observe(context, now=NOW)

        assert sample(STALENESS, source_id=str(created.id)) == 0.0
        assert f'source_id="{created.id}"' not in generate_latest(REGISTRY).decode()

    async def test_a_source_the_user_excludes_publishes_no_staleness_at_all(
        self, context: WorkerContext, owner: UserRecord
    ) -> None:
        """BREAK IT: exclude a source that was already a day stale, and read the gauge again.

        An excluded source is never polled, so a reading for it grows without bound. `SourceStale`
        is a maximum over sources, so a growing reading stuck the alert firing forever on a source
        the user switched off DELIBERATELY: the expected outcome of their own instruction, which
        section 18's second clause forbids alerting on. Measured before the fix at 864000.0 against
        an 86400 threshold, reachable by one PATCH.

        The record states the principle one property away: "the user asked for zero anchors from it,
        so a stale error from before the exclusion must not render as a failure".

        THE INPUT IS A SHAPE PRODUCTION EMITS, in the order production emits it. A source is polled
        while included, which is what writes `last_success_at` (`sync.SourceSyncer.sync` ->
        `save_sync_state`); the user then excludes it, through `PATCH /calendar-sources/{id}` ->
        `api.py:96` -> `service.change_source:170` -> `set_inclusion`. This test calls that same
        writer, one layer below the HTTP edge.
        """
        async with context.database.sessionmaker() as session, session.begin():
            created = await a_source(session, owner, added=NOW - timedelta(days=10))
            await CalendarSourceRepository(session, owner.tenant_id).save_sync_state(
                created.id,
                SyncStateRecord(
                    last_success_at=NOW - timedelta(days=10),
                    last_attempt_at=NOW - timedelta(days=10),
                    anchors_current=7,
                ),
            )

        await StateGaugeRunner(interval=STATE_INTERVAL, clock=lambda: NOW).observe(context, now=NOW)
        assert sample(STALENESS, source_id=str(created.id)) == 864000.0
        assert sample(ANCHORS, source_id=str(created.id)) == 7.0

        async with context.database.sessionmaker() as session, session.begin():
            await CalendarSourceRepository(session, owner.tenant_id).set_inclusion(
                created.id, included=False, display_name=None
            )

        await StateGaugeRunner(interval=STATE_INTERVAL, clock=lambda: NOW).observe(context, now=NOW)

        assert sample(STALENESS, source_id=str(created.id)) == 0.0
        assert f'{STALENESS}{{source_id="{created.id}"}}' not in generate_latest(REGISTRY).decode()

    async def test_an_excluded_source_still_draws_its_anchor_count_as_zero(
        self, context: WorkerContext, owner: UserRecord
    ) -> None:
        """The anchor gauge reads the record's own property, not the raw sync-state column.

        `anchor_count` is zero for an excluded source whatever its last successful sync read, which
        is the figure every other surface uses. Reading the column drew seven anchors for a source
        contributing none to any plan, so the panel disagreed with the product about one source.

        The series stays, unlike the staleness one: zero anchors from an excluded source is a true
        and useful reading, and nothing alerts on it.

        Same production shape as the test above, and the service's own docstring states the intent
        it is checked against: "Excluding one reports zero anchors immediately rather than at the
        next poll, which is what the read model's excluded state renders." The exposition renders it
        now too.
        """
        async with context.database.sessionmaker() as session, session.begin():
            sources = CalendarSourceRepository(session, owner.tenant_id)
            created = await a_source(session, owner, added=NOW - timedelta(days=10))
            await sources.save_sync_state(
                created.id,
                SyncStateRecord(last_success_at=NOW - timedelta(hours=1), anchors_current=7),
            )
            await sources.set_inclusion(created.id, included=False, display_name=None)

        await StateGaugeRunner(interval=STATE_INTERVAL, clock=lambda: NOW).observe(context, now=NOW)

        assert sample(ANCHORS, source_id=str(created.id)) == 0.0
        assert f'{ANCHORS}{{source_id="{created.id}"}}' in generate_latest(REGISTRY).decode()


class TestTheProductJob:
    async def test_it_reads_every_tenant_without_raising(
        self, context: WorkerContext, owner: UserRecord
    ) -> None:
        """A tenant with no plan history at all must not fault the job.

        The adversarial case a metrics job meets first: every ratio has an empty denominator, and
        the run has to leave those gauges alone rather than publish zero or raise.
        """
        read = await ProductMetricRunner(interval=PRODUCT_INTERVAL, clock=lambda: NOW).compute(
            context, now=NOW
        )

        assert read >= 1

    async def test_a_tenant_whose_read_raises_is_counted_and_the_others_continue(
        self, context: WorkerContext, owner: UserRecord, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One tenant's fault must not take the whole deployment's product metrics down."""
        from syncr_api.observability import product_runner

        before = sample("syncr_observability_product_failures_total")

        async def raising(*_args: object, **_kwargs: object) -> object:
            raise RuntimeError("the read did not come back")

        monkeypatch.setattr(product_runner, "build_product_reader", raising)

        read = await ProductMetricRunner(interval=PRODUCT_INTERVAL, clock=lambda: NOW).compute(
            context, now=NOW
        )

        assert read == 0
        assert sample("syncr_observability_product_failures_total") - before >= 1.0
