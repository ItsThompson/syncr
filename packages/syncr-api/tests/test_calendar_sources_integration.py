"""Calendar sources against a real Postgres: the invariants the SCHEMA holds, not the code.

A fake repository would not catch any of what is asserted here. Every claim below is one the
database makes:

- exactly one write target per tenant, by a partial unique index whose existence is itself
  asserted, because the invariant depends on the index being there;
- the same feed cannot be added twice, by a unique index over the three columns that identify one;
- a horizon belongs to the write target and only to it, by a check constraint, so an anchor source
  with a projection bound is not a row that can exist;
- sync state is written on every attempt, which is what makes staleness computable;
- and every statement that reaches Postgres carries the tenant predicate.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from syncr_api.calendars.config import (
    ANCHOR_SOURCE,
    CALENDAR_SOURCES_TABLE,
    ERROR,
    EXCLUDED,
    GOOGLE,
    HORIZON_DAYS_DEFAULT,
    ICS,
    NEVER_SYNCED,
    OK,
    WRITE_TARGET,
)
from syncr_api.calendars.events import RejectedComponent
from syncr_api.calendars.records import SyncStateRecord
from syncr_api.calendars.repository import CalendarSourceRepository
from syncr_api.core.db import create_db_engine, create_sessionmaker
from tests.control_models import recording
from tests.live_tenants import delete_tenant, seed_owner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.calendars.records import CalendarSourceRecord
    from syncr_domain.identifiers import TenantId
    from tests.control_models import StatementRecorder

pytestmark = pytest.mark.integration

NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)
EARLIER = NOW - timedelta(hours=6)

WRITE_TARGET_INDEX = "uq_calendar_sources_tenant_id_write_target"
ONE_SOURCE_PER_FEED_INDEX = "uq_calendar_sources_tenant_id_provider_external_id"

TIMETABLE = "https://example.ac.uk/timetable.ics"
ASSESSMENTS = "https://example.ac.uk/assessments.ics"


@pytest.fixture
async def engine(live_database_url: str) -> AsyncIterator[AsyncEngine]:
    """An engine owned by this test's own event loop."""
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
def tenant_id(owner: UserRecord) -> TenantId:
    return owner.tenant_id


@pytest.fixture
def statements(engine: AsyncEngine) -> Iterator[StatementRecorder]:
    yield from recording(engine)


async def add(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    *,
    external_id: str = TIMETABLE,
    provider: str = ICS,
    role: str = ANCHOR_SOURCE,
    horizon_days: int | None = None,
    display_name: str = "University timetable",
) -> CalendarSourceRecord:
    async with sessions() as session, session.begin():
        return await CalendarSourceRepository(session, tenant_id).create(
            provider=provider,  # type: ignore[arg-type]  # the vocabulary is checked in SQL
            role=role,  # type: ignore[arg-type]
            display_name=display_name,
            external_id=external_id,
            included=True,
            horizon_days=horizon_days,
            created_at=NOW,
        )


# --------------------------------------------------------------------------------
# The write-target invariant
# --------------------------------------------------------------------------------


async def test_the_write_target_partial_unique_index_exists(engine: AsyncEngine) -> None:
    # The invariant is the index. Asserted directly, because a migration that created the table
    # without it would leave every other test in this file passing while two calendars could
    # both be designated the projection.
    async with engine.connect() as connection:
        found = await connection.execute(
            text("SELECT indexdef FROM pg_indexes WHERE tablename = :table AND indexname = :index"),
            {"table": CALENDAR_SOURCES_TABLE, "index": WRITE_TARGET_INDEX},
        )
        definition = found.scalar_one()

    assert "UNIQUE" in definition
    assert "tenant_id" in definition
    # Partial, so many anchor sources coexist and only the write-target role is constrained.
    assert "WHERE" in definition
    assert "write-target" in definition


async def test_a_second_write_target_is_rejected_by_the_database(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    first = await add(sessions, tenant_id, external_id=TIMETABLE)
    second = await add(sessions, tenant_id, external_id=ASSESSMENTS)
    async with sessions() as session, session.begin():
        await CalendarSourceRepository(session, tenant_id).designate_write_target(
            first.id, horizon_days=HORIZON_DAYS_DEFAULT
        )

    with pytest.raises(IntegrityError):
        async with sessions() as session, session.begin():
            await CalendarSourceRepository(session, tenant_id).designate_write_target(
                second.id, horizon_days=HORIZON_DAYS_DEFAULT
            )


async def test_many_anchor_sources_coexist_because_the_index_is_partial(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    # The other half of the index's claim: constraining the write-target role must not constrain
    # the role every other source holds.
    await add(sessions, tenant_id, external_id=TIMETABLE)
    await add(sessions, tenant_id, external_id=ASSESSMENTS)
    await add(sessions, tenant_id, external_id="https://example.org/holidays.ics")

    async with sessions() as session:
        found = await CalendarSourceRepository(session, tenant_id).list_all()

    assert len(found) == 3
    assert {source.role for source in found} == {ANCHOR_SOURCE}


async def test_another_tenants_write_target_does_not_block_this_ones(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    # The index leads with tenant_id, so the invariant is per tenant. Without that leading
    # column the first deployment tenant to designate a target would lock out every other.
    other = await seed_owner(sessions)
    try:
        mine = await add(sessions, tenant_id, external_id=TIMETABLE)
        theirs = await add(sessions, other.tenant_id, external_id=TIMETABLE)
        async with sessions() as session, session.begin():
            await CalendarSourceRepository(session, tenant_id).designate_write_target(
                mine.id, horizon_days=HORIZON_DAYS_DEFAULT
            )
        async with sessions() as session, session.begin():
            await CalendarSourceRepository(session, other.tenant_id).designate_write_target(
                theirs.id, horizon_days=HORIZON_DAYS_DEFAULT
            )
        async with sessions() as session:
            read = await CalendarSourceRepository(session, tenant_id).write_target()
    finally:
        await delete_tenant(sessions, other.tenant_id)

    assert read is not None
    assert read.id == mine.id


# --------------------------------------------------------------------------------
# The other schema guards
# --------------------------------------------------------------------------------


async def test_the_same_feed_cannot_be_added_twice(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    await add(sessions, tenant_id, external_id=TIMETABLE)

    with pytest.raises(IntegrityError):
        await add(sessions, tenant_id, external_id=TIMETABLE)


async def test_one_address_can_be_a_source_under_two_providers(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    # The uniqueness is per provider, so a Google calendarId that happens to equal a feed
    # address is not the same source. Without the provider column this would be rejected.
    await add(sessions, tenant_id, external_id=TIMETABLE, provider=ICS)

    google = await add(sessions, tenant_id, external_id=TIMETABLE, provider=GOOGLE)

    assert google.provider == GOOGLE


async def test_an_anchor_source_cannot_carry_a_projection_horizon(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    with pytest.raises(IntegrityError):
        await add(sessions, tenant_id, role=ANCHOR_SOURCE, horizon_days=14)


async def test_a_write_target_cannot_be_created_without_one(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    # The biconditional's other direction: the two always travel together, so nothing reads a
    # write target and has to decide what a missing horizon would mean.
    with pytest.raises(IntegrityError):
        await add(sessions, tenant_id, role=WRITE_TARGET, horizon_days=None)


@pytest.mark.parametrize("horizon_days", [0, -1, 91, 3650])
async def test_a_horizon_outside_the_projection_range_is_rejected(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, horizon_days: int
) -> None:
    with pytest.raises(IntegrityError):
        await add(sessions, tenant_id, role=WRITE_TARGET, horizon_days=horizon_days)


@pytest.mark.parametrize(("provider", "role"), [("ical", ANCHOR_SOURCE), (ICS, "both")])
async def test_a_value_outside_a_closed_vocabulary_is_rejected(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    provider: str,
    role: str,
) -> None:
    # The annotation is erased at runtime, so the check constraint is what stops a caller reaching
    # this table from a later revision or a psql session.
    #
    # `IntegrityError` exactly, and both values are chosen to fit their column. A wildcard tuple
    # ending in `Exception` passes on any failure at all, and it was hiding one: the earlier
    # `"outlook"` is seven characters against a `varchar(6)`, so it never reached the constraint
    # this test is about. It failed on column WIDTH, as a `DBAPIError`, and the assertion was wide
    # enough to accept that.
    with pytest.raises(IntegrityError):
        await add(sessions, tenant_id, provider=provider, role=role)


# --------------------------------------------------------------------------------
# Sync state round trip
# --------------------------------------------------------------------------------


async def test_sync_state_round_trips_including_its_rejections(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    source = await add(sessions, tenant_id)
    rejected = RejectedComponent(
        kind="missing-duration",
        line=17,
        component="VEVENT",
        detail="the event has neither DTEND nor DURATION",
        uid="viva@example.ac.uk",
    )
    state = SyncStateRecord(
        last_success_at=NOW,
        last_attempt_at=NOW,
        last_error=None,
        cursor='etag:"abc"',
        events_read=30,
        anchors_current=27,
        rejections=(rejected,),
    )

    async with sessions() as session, session.begin():
        await CalendarSourceRepository(session, tenant_id).save_sync_state(source.id, state)
    async with sessions() as session:
        read = await CalendarSourceRepository(session, tenant_id).find(source.id)

    assert read is not None
    assert read.sync_state == state
    # The panel renders these, so the line and the reason have to survive the round trip.
    assert read.sync_state.rejections[0].line == 17
    assert read.sync_state.rejections[0].uid == "viva@example.ac.uk"


async def test_a_failed_attempt_is_stored_and_makes_the_source_read_as_failing(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    source = await add(sessions, tenant_id)

    async with sessions() as session, session.begin():
        await CalendarSourceRepository(session, tenant_id).save_sync_state(
            source.id,
            SyncStateRecord(
                last_success_at=EARLIER,
                last_attempt_at=NOW,
                last_error="the feed answered 503 Service Unavailable",
                cursor='etag:"abc"',
                events_read=30,
                anchors_current=27,
            ),
        )
    async with sessions() as session:
        read = await CalendarSourceRepository(session, tenant_id).find(source.id)

    assert read is not None
    assert read.state == ERROR
    # The anchors are retained: nothing the last success established became untrue.
    assert read.anchor_count == 27
    # And staleness is computable, which is the whole reason both instants are stored.
    assert read.sync_state.last_attempt_at == NOW
    assert read.sync_state.last_success_at == EARLIER


async def test_an_excluded_source_reads_as_excluded_rather_than_as_failing(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    source = await add(sessions, tenant_id)
    async with sessions() as session, session.begin():
        scoped = CalendarSourceRepository(session, tenant_id)
        await scoped.save_sync_state(
            source.id,
            SyncStateRecord(last_attempt_at=NOW, last_error="the feed answered 404", cursor=None),
        )
        await scoped.set_inclusion(source.id, included=False, display_name=None)

    async with sessions() as session:
        read = await CalendarSourceRepository(session, tenant_id).find(source.id)

    assert read is not None
    # A stale error from before the exclusion must not render as a failure the user resolved.
    assert read.state == EXCLUDED
    assert read.anchor_count == 0


async def test_a_source_nobody_has_polled_reads_as_never_synced(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    source = await add(sessions, tenant_id)

    assert source.state == NEVER_SYNCED
    assert source.anchor_count == 0


async def test_a_source_that_last_succeeded_reads_as_ok(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    source = await add(sessions, tenant_id)
    async with sessions() as session, session.begin():
        await CalendarSourceRepository(session, tenant_id).save_sync_state(
            source.id,
            SyncStateRecord(
                last_success_at=NOW, last_attempt_at=NOW, events_read=12, anchors_current=12
            ),
        )
    async with sessions() as session:
        read = await CalendarSourceRepository(session, tenant_id).find(source.id)

    assert read is not None
    assert read.state == OK
    assert read.anchor_count == 12


# --------------------------------------------------------------------------------
# Reads that must be scoped
# --------------------------------------------------------------------------------


async def test_another_tenants_source_reads_as_absent(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    other = await seed_owner(sessions)
    try:
        theirs = await add(sessions, other.tenant_id, external_id=TIMETABLE)
        async with sessions() as session:
            read = await CalendarSourceRepository(session, tenant_id).find(theirs.id)
    finally:
        await delete_tenant(sessions, other.tenant_id)

    # Absent rather than forbidden, which is what makes the service's 404 truthful.
    assert read is None


async def test_the_included_read_excludes_the_write_target_and_the_excluded(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    # Reading back the projection would make every solve treat the previous solve's output as
    # immovable commitments, so the poll's own read is where that is prevented.
    polled = await add(sessions, tenant_id, external_id=TIMETABLE)
    target = await add(sessions, tenant_id, external_id=ASSESSMENTS)
    dropped = await add(sessions, tenant_id, external_id="https://example.org/holidays.ics")
    async with sessions() as session, session.begin():
        scoped = CalendarSourceRepository(session, tenant_id)
        await scoped.designate_write_target(target.id, horizon_days=HORIZON_DAYS_DEFAULT)
        await scoped.set_inclusion(dropped.id, included=False, display_name=None)

    async with sessions() as session:
        due = await CalendarSourceRepository(session, tenant_id).included_for(ICS)

    assert [source.id for source in due] == [polled.id]


async def test_every_statement_this_repository_executes_carries_the_tenant_predicate(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, statements: StatementRecorder
) -> None:
    # Compiling a statement proves what the repository built. This proves what reached Postgres.
    #
    # The INSERT is excluded, and only the INSERT: a scope is a column VALUE on an insert rather
    # than a predicate, which is why there is no scoped_insert helper for one to be built from.
    # Every read, update, and delete is in scope for the rule.
    source = await add(sessions, tenant_id)
    async with sessions() as session, session.begin():
        scoped = CalendarSourceRepository(session, tenant_id)
        await scoped.list_all()
        await scoped.find(source.id)
        await scoped.write_target()
        await scoped.included_for(ICS)
        await scoped.find_by_external_id(ICS, TIMETABLE)
        # The horizon write is exercised on a source that may hold one, because the check
        # constraint refuses it on an anchor source: the ordering here is the schema's rule,
        # not an incidental sequence.
        await scoped.designate_write_target(source.id, horizon_days=HORIZON_DAYS_DEFAULT)
        await scoped.set_horizon(source.id, horizon_days=HORIZON_DAYS_DEFAULT + 1)
        await scoped.set_inclusion(source.id, included=False, display_name="Renamed")
        await scoped.save_sync_state(source.id, SyncStateRecord(last_attempt_at=NOW))
        await scoped.remove(source.id)

    predicated = [
        statement
        for statement in statements.against(CALENDAR_SOURCES_TABLE)
        if not statement.startswith("INSERT")
    ]
    unscoped = [
        statement
        for statement in statements.without_a_tenant_predicate(CALENDAR_SOURCES_TABLE)
        if not statement.startswith("INSERT")
    ]

    assert predicated, "no read or write of calendar_sources reached the database"
    assert unscoped == []


async def test_the_recorded_insert_is_the_only_statement_without_a_predicate(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, statements: StatementRecorder
) -> None:
    # The exclusion above is shown to be doing real work rather than hiding a hole: exactly one
    # statement is exempt, it is an INSERT, and it carries the tenant as a bound value.
    await add(sessions, tenant_id)

    exempt = statements.without_a_tenant_predicate(CALENDAR_SOURCES_TABLE)

    assert len(exempt) == 1
    assert exempt[0].startswith("INSERT")
    assert "tenant_id" in exempt[0]
