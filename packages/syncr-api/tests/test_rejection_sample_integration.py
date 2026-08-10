"""The rejection sample and its count against a real Postgres, plus the revision that added it.

Three claims, none of which a fake repository could make:

- a feed planted over the sample size stores a bounded sample and the number of refusals it made,
  driven through the adapter and read back out of the column rather than off the outcome;
- the stored count is not the stored list's length, so the column carries its own figure;
- a row written before the column existed takes the length of its own list, which is what makes the
  revision non-lossy, driven with the statement the revision itself runs.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from syncr_api.calendars.config import (
    ANCHOR_SOURCE,
    ICS,
    MISSING_DURATION,
    UNKNOWN_ZONE,
)
from syncr_api.calendars.feeds import FeedBody
from syncr_api.calendars.ics_adapter import IcsAdapter
from syncr_api.calendars.records import SyncStateRecord
from syncr_api.calendars.repository import CalendarSourceRepository
from syncr_api.core.db import create_db_engine, create_sessionmaker
from syncr_api.core.migrations import ALEMBIC_DIR
from syncr_domain.intervals import Interval
from syncr_domain.zones import ZoneProfile
from tests.live_tenants import delete_tenant, seed_owner
from tests.rejection_feeds import NOW, refused_feed, rejection

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.calendars.feeds import FeedAnswer
    from syncr_api.calendars.records import CalendarSourceId, CalendarSourceRecord
    from syncr_domain.identifiers import TenantId

pytestmark = pytest.mark.integration

FEED_URL = "https://example.ac.uk/refusals.ics"
HOME = ZoneProfile(home_zone="Europe/London")
# The fortnight the write target would project, starting the Monday the shared instant falls on.
HORIZON = Interval(NOW.replace(hour=0), NOW.replace(hour=0) + timedelta(days=14))

REVISION = "0061_rejection_total"


class OneFeed:
    """A fetcher that answers one URL with one body, so the parse under test is the real one."""

    def __init__(self, body: str) -> None:
        self._body = body

    async def get(self, url: str, *, cursor: str | None) -> FeedAnswer:
        assert url == FEED_URL
        assert cursor is None
        return FeedBody(body=self._body, cursor='etag:"planted"')


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
def tenant_id(owner: UserRecord) -> TenantId:
    return owner.tenant_id


async def add(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> CalendarSourceRecord:
    async with sessions() as session, session.begin():
        return await CalendarSourceRepository(session, tenant_id).create(
            provider=ICS,
            role=ANCHOR_SOURCE,
            display_name="A feed of refusals",
            external_id=FEED_URL,
            included=True,
            horizon_days=None,
            created_at=NOW,
        )


async def stored(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, source_id: CalendarSourceId
) -> SyncStateRecord:
    async with sessions() as session:
        read = await CalendarSourceRepository(session, tenant_id).find(source_id)
    assert read is not None
    return read.sync_state


def clock() -> datetime:
    return NOW


async def test_a_planted_feed_over_the_sample_size_stores_a_sample_and_the_whole_count(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    # The bound driven end to end: a feed of 50,000 refusals reaches the column through the adapter
    # and the repository, and what comes back out is nine entries and a count of all of them.
    source = await add(sessions, tenant_id)
    adapter = IcsAdapter(
        fetcher=OneFeed(refused_feed(50_000)), profile=HOME, horizon=HORIZON, clock=clock
    )

    _outcome, state = await adapter.fetch(source)
    async with sessions() as session, session.begin():
        await CalendarSourceRepository(session, tenant_id).save_sync_state(source.id, state)

    read = await stored(sessions, tenant_id, source.id)
    assert read.rejected_count == 50_000
    # Three kinds at three kept each, written out rather than read off the bound.
    assert len(read.rejections) == 9
    assert read.events_read == 50_000


async def test_the_stored_count_is_not_the_length_of_the_stored_sample(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    # The column's own claim, away from any parse: two entries kept and nine refusals counted. Two
    # rather than one, because a count asserted against a single-member list cannot be told from the
    # length of that list.
    source = await add(sessions, tenant_id)
    state = SyncStateRecord(
        last_success_at=NOW,
        last_attempt_at=NOW,
        events_read=30,
        anchors_current=21,
        rejections=(rejection(MISSING_DURATION, line=17), rejection(UNKNOWN_ZONE, line=42)),
        rejected_total=9,
    )

    async with sessions() as session, session.begin():
        await CalendarSourceRepository(session, tenant_id).save_sync_state(source.id, state)

    read = await stored(sessions, tenant_id, source.id)
    assert read == state
    assert len(read.rejections) == 2
    assert read.rejected_count == 9


async def test_a_row_written_before_the_column_existed_takes_the_length_of_its_own_list(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    # What every stored row looked like the instant the column was added: a rejection list written
    # when nothing bounded it, and a count of zero from the column's default. The revision derives
    # the count from the list, so no stored panel loses its rejections.
    #
    # The statement executed here is the revision's own, loaded through Alembic's loader, so a copy
    # of it cannot drift from what a database is actually migrated with.
    source = await add(sessions, tenant_id)
    before_the_column = SyncStateRecord(
        last_success_at=NOW,
        last_attempt_at=NOW,
        events_read=30,
        anchors_current=21,
        rejections=(rejection(MISSING_DURATION, line=17), rejection(UNKNOWN_ZONE, line=42)),
        rejected_total=0,
    )

    async with sessions() as session, session.begin():
        await CalendarSourceRepository(session, tenant_id).save_sync_state(
            source.id, before_the_column
        )
    read = await _derived(sessions, tenant_id, source.id)

    assert read.rejected_count == 2
    assert len(read.rejections) == 2


async def test_a_row_that_never_rejected_anything_is_left_at_zero_by_the_derivation(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    # The other side of the derivation's condition. A source nobody has polled holds SQL NULL rather
    # than an empty array, and `jsonb_array_length(NULL)` is NULL: without the condition the
    # derivation would violate the column's own NOT NULL rather than leave the row alone.
    source = await add(sessions, tenant_id)

    read = await _derived(sessions, tenant_id, source.id)

    assert read.rejections == ()
    assert read.rejected_count == 0


async def test_a_negative_count_is_refused_by_the_schema(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    # The check constraint the revision restated. A count below zero is a count nothing produced,
    # and the column is written by one repository method whose input is an int.
    source = await add(sessions, tenant_id)

    with pytest.raises(IntegrityError):
        async with sessions() as session, session.begin():
            await CalendarSourceRepository(session, tenant_id).save_sync_state(
                source.id, SyncStateRecord(last_attempt_at=NOW, rejected_total=-1)
            )


async def _derived(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, source_id: CalendarSourceId
) -> SyncStateRecord:
    """One source as the revision's derivation leaves it, without leaving it that way.

    The statement is the revision's own, loaded through Alembic's loader, so a copy of it here
    cannot drift from what a database is actually migrated with. It is a migration, so it names no
    tenant and no source: it is read back inside its own transaction and rolled back, which is what
    keeps a suite run against a shared Postgres from rewriting every other row's count.
    """
    module = ScriptDirectory(str(ALEMBIC_DIR)).get_revision(REVISION).module
    derivation: str = module.DERIVED_FROM_THE_SAMPLE
    async with sessions() as session:
        await session.execute(text(derivation))
        read = await CalendarSourceRepository(session, tenant_id).find(source_id)
        await session.rollback()
    assert read is not None
    return read.sync_state
