"""The seam between a delta's silence about an anchor and a full read's absence of one.

An incremental poll that lists changes mentions almost nothing. A read of the calendar mentions
everything present and removes the rest by absence. Those two silences mean opposite things, and
the property here is what holds them apart: **a small change must leave the anchors it did not
mention alone.**

The test drives one poll end to end -- the adapter over a scripted transport, the syncer, and the
real reconciler over real Postgres -- against a calendar of sixty commitments whose delta reports
exactly two changes. Fifty-eight rows must survive with their identity intact: asserted row by row,
on the primary key and the fact each row stores, never on a count. A count of fifty-eight would
also be answered by a pass that deleted fifty-eight rows and re-created them, which is precisely
the failure this property exists to catch.

Written against the full-read path first, so the day the shape changes -- a raw delta handed to a
reconciler that removes what it was not told about, most of all -- this goes red rather than quiet.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from syncr_api.anchors.reconcile import AnchorReconciler
from syncr_api.anchors.repository import AnchorRepository
from syncr_api.anchors.type_repository import AnchorTypeRepository
from syncr_api.calendars.config import ANCHOR_SOURCE, GOOGLE
from syncr_api.calendars.google_adapter import GoogleAdapter
from syncr_api.calendars.google_backoff import BackoffPolicy
from syncr_api.calendars.google_client import GoogleCalendarClient
from syncr_api.calendars.google_cursors import CURSOR_PREFIX
from syncr_api.calendars.injection import READS_ONLY
from syncr_api.calendars.records import CalendarSourceRecord, SyncStateRecord
from syncr_api.calendars.repository import CalendarSourceRepository
from syncr_api.calendars.sync import SourceSyncer
from syncr_api.core.db import create_db_engine, create_sessionmaker
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.user_settings.solve_inputs import TrackedWeekInputVersions
from syncr_domain.intervals import Interval
from syncr_domain.weeks import IsoWeek
from syncr_domain.zones import ZoneProfile
from tests.fake_google import (
    SYNC_TOKEN,
    FixedTokens,
    RecordedGoogle,
    event,
    events_page,
    ok,
)
from tests.live_tenants import delete_tenant, seed_owner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.anchors.records import AnchorRecord
    from syncr_api.calendars.google_transport import GoogleResponse
    from syncr_api.calendars.records import CalendarSourceRecord, SyncStateRecord

pytestmark = pytest.mark.integration

NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)
HORIZON = Interval(NOW, NOW + timedelta(days=14))
HOME_ZONE = "UTC"
NEXT_TOKEN = "CNEXT-token"  # pragma: allowlist secret

# 2026-02-09 opens 2026-W07.
WEEK = IsoWeek(2026, 7)
MOVED_UID = "evt-07@provider.test"
CANCELLED_UID = "evt-11@provider.test"


def sixty_commitments() -> tuple[dict[str], ...]:
    """Sixty single-instance events spread across the horizon, one per identifier."""
    return tuple(
        {
            "id": f"evt-{index:02d}@provider.test",
            "summary": f"Commitment {index}",
            "start": {
                "dateTime": (NOW + timedelta(days=index // 6, hours=index % 6)).isoformat(),
                "timeZone": "UTC",
            },
            "end": {
                "dateTime": (
                    NOW + timedelta(days=index // 6, hours=index % 6, minutes=45)
                ).isoformat(),
                "timeZone": "UTC",
            },
        }
        for index in range(60)
    )


def an_adapter(answers: list[GoogleResponse]) -> GoogleAdapter:
    transport = RecordedGoogle(answers=answers)

    async def sleep(_seconds: float) -> None:
        return None

    return GoogleAdapter(
        client=GoogleCalendarClient(
            transport=transport, tokens=FixedTokens(), backoff=BackoffPolicy(), sleep=sleep
        ),
        profile=ZoneProfile(home_zone=HOME_ZONE),
        horizon=HORIZON,
        clock=lambda: NOW,
        # The read side holds the refusing arm of the write seam, which is what the request
        # composition passes; the projection is not this suite's subject.
        writes=READS_ONLY,
    )


@dataclass
class RecordingSources:
    """The sync states each pass wrote, so the next pass reads the cursor the last one stored."""

    saved: list[SyncStateRecord] = field(default_factory=list)

    async def save_sync_state(self, source_id: object, state: SyncStateRecord) -> None:
        del source_id
        self.saved.append(state)


@dataclass
class SilentCollisions:
    """Satisfies the ``CollisionDetection`` protocol without reading a plan."""

    async def detect(self, *, now: datetime) -> object:
        del now
        return ()


@dataclass
class SilentSolves:
    asked: list[frozenset] = field(default_factory=list)

    async def request(self, weeks: frozenset) -> tuple[()]:
        self.asked.append(weeks)
        return ()


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
def tenant_id(owner: UserRecord) -> UUID:
    return owner.tenant_id


@pytest.fixture
async def source(
    sessions: async_sessionmaker[AsyncSession], tenant_id: UUID
) -> CalendarSourceRecord:
    async with sessions() as session, session.begin():
        return await CalendarSourceRepository(session, tenant_id).create(
            provider=GOOGLE,
            role=ANCHOR_SOURCE,
            display_name="Personal",
            external_id="primary",
            included=True,
            horizon_days=None,
            created_at=NOW - timedelta(days=30),
        )


async def run_a_poll(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
    source: CalendarSourceRecord,
    answers: list[GoogleResponse],
) -> tuple[list[AnchorRecord], SyncStateRecord]:
    """One sync pass, whole: adapter, syncer, and the real reconciler, in one transaction.

    Answers with the rows as the pass left them and the state the pass WROTE, which carries the
    reconciler's own count of the rows rather than the count of events the read produced.
    """
    sources = RecordingSources()
    async with sessions() as session, session.begin():
        versions = TrackedWeekInputVersions(
            WeekInputVersionRepository(session, tenant_id), clock=lambda: NOW
        )
        syncer = SourceSyncer(
            sources=sources,
            # A scheduled pass enqueues no operation; the lifecycle's other callers are the routes.
            operations=None,  # type: ignore[arg-type]
            adapters={GOOGLE: an_adapter(answers)},
            anchors=AnchorReconciler(
                AnchorRepository(session, tenant_id),
                AnchorTypeRepository(session, tenant_id),
                versions=versions,
                home_zone=HOME_ZONE,
            ),
            collisions=SilentCollisions(),
            # A concrete collaborator rather than a protocol, so a structural fake cannot satisfy
            # it; the routing suite carries the same ignore for the same reason.
            solves=SilentSolves(),  # type: ignore[arg-type]
            clock=lambda: NOW,
        )
        _outcome, _returned = await syncer.sync(source)
        rows = await AnchorRepository(session, tenant_id).list_for_source(source.id)
    return list(rows), sources.saved[0]


async def test_two_reported_changes_leave_the_fifty_eight_unmentioned_rows_alone(
    sessions: async_sessionmaker[AsyncSession], tenant_id: UUID, source: CalendarSourceRecord
) -> None:
    commitments = sixty_commitments()

    # The first poll reads the calendar in full and plants one anchor per commitment.
    first_rows, first_state = await run_a_poll(
        sessions,
        tenant_id,
        source,
        [ok(events_page(*commitments))],
    )
    assert len(first_rows) == 60
    assert f"{CURSOR_PREFIX}{SYNC_TOKEN}" == first_state.cursor

    # The second poll holds a cursor and reports two changes: one commitment moved, one cancelled.
    # A second answer is scripted because the shape that follows a change-bearing delta with a full
    # read consumes it; it states the calendar AS THE DELTA LEAVES IT, so whichever shape runs, the
    # poll answers the same calendar.
    moved_at = NOW + timedelta(days=3, hours=10)
    moved = {
        "id": MOVED_UID,
        "summary": "Commitment 7",
        "start": {"dateTime": moved_at.isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": (moved_at + timedelta(minutes=45)).isoformat(), "timeZone": "UTC"},
    }
    settled = [moved if one["id"] == MOVED_UID else one for one in commitments]
    second_rows, second_state = await run_a_poll(
        sessions,
        tenant_id,
        replace(source, sync_state=first_state),
        [
            ok(
                events_page(
                    event(
                        MOVED_UID,
                        start=moved_at.isoformat(),
                        end=(moved_at + timedelta(minutes=45)).isoformat(),
                    ),
                    event(CANCELLED_UID, status="cancelled", start=None, end=None),
                    sync_token=NEXT_TOKEN,
                )
            ),
            ok(events_page(*[one for one in settled if one["id"] != CANCELLED_UID])),
        ],
    )

    before = {row.external_uid: row for row in first_rows}
    after = {row.external_uid: row for row in second_rows}

    # Row identity, not counts: every unmentioned commitment is THE SAME ROW holding THE SAME FACT.
    unmentioned = set(before) - {MOVED_UID, CANCELLED_UID}
    assert set(after) == unmentioned | {MOVED_UID}
    assert {uid: after[uid].id for uid in unmentioned} == {
        uid: before[uid].id for uid in unmentioned
    }
    assert {
        uid: (
            after[uid].title,
            after[uid].interval,
            after[uid].location,
            after[uid].series_uid,
            after[uid].possibly_stale,
        )
        for uid in unmentioned
    } == {
        uid: (
            before[uid].title,
            before[uid].interval,
            before[uid].location,
            before[uid].series_uid,
            before[uid].possibly_stale,
        )
        for uid in unmentioned
    }

    # The two the delta named are the two that moved, and no others.
    assert after[MOVED_UID].id == before[MOVED_UID].id
    assert after[MOVED_UID].interval.start == moved_at
    # And the count the panel reports is the number of rows the table holds.
    assert second_state.anchors_current == len(second_rows) == 59


async def test_a_quiet_delta_confirms_rather_than_reconciles(
    sessions: async_sessionmaker[AsyncSession], tenant_id: UUID, source: CalendarSourceRecord
) -> None:
    """A poll reporting nothing changed answers exactly as an ICS 304 does: nothing is touched."""
    commitments = sixty_commitments()

    first_rows, first_state = await run_a_poll(
        sessions,
        tenant_id,
        source,
        [ok(events_page(*commitments))],
    )

    quiet_rows, quiet_state = await run_a_poll(
        sessions,
        tenant_id,
        replace(source, sync_state=replace(first_state, cursor=f"{CURSOR_PREFIX}{SYNC_TOKEN}")),
        [ok(events_page(sync_token=NEXT_TOKEN))],
    )

    before = {row.external_uid: row for row in first_rows}
    after = {row.external_uid: row for row in quiet_rows}
    assert set(after) == set(before)
    assert {
        uid: (row.id, row.title, row.interval, row.possibly_stale) for uid, row in after.items()
    } == {uid: (row.id, row.title, row.interval, row.possibly_stale) for uid, row in before.items()}
    assert quiet_state.last_error is None
    assert quiet_state.anchors_current == 60


# --------------------------------------------------------------------------------------
# The delta branch of the reconcile itself, against the rows rather than a fake.
# --------------------------------------------------------------------------------------


async def track(
    sessions: async_sessionmaker[AsyncSession], tenant_id: UUID, *weeks: IsoWeek
) -> None:
    """Give each week a version row, which is what makes it a week the counter bumps."""
    async with sessions() as session, session.begin():
        versions = WeekInputVersionRepository(session, tenant_id)
        for week in weeks:
            await versions.bump(week, at=NOW)


async def version_of(
    sessions: async_sessionmaker[AsyncSession], tenant_id: UUID, week: IsoWeek
) -> int | None:
    async with sessions() as session:
        return await WeekInputVersionRepository(session, tenant_id).current(week)


async def test_a_cancelled_occurrence_the_delta_reports_is_removed(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
    source: CalendarSourceRecord,
) -> None:
    commitments = sixty_commitments()

    _first_rows, first_state = await run_a_poll(
        sessions,
        tenant_id,
        source,
        [ok(events_page(*commitments))],
    )
    await track(sessions, tenant_id, WEEK)

    second_rows, second_state = await run_a_poll(
        sessions,
        tenant_id,
        replace(source, sync_state=first_state),
        [
            ok(
                events_page(
                    event(CANCELLED_UID, status="cancelled", start=None, end=None),
                    sync_token=NEXT_TOKEN,
                )
            )
        ],
    )

    assert {row.external_uid for row in second_rows} == {
        one["id"] for one in commitments if one["id"] != CANCELLED_UID
    }
    assert second_state.anchors_current == 59
    # And the week the removed commitment occupied was invalidated: its plan still describes an
    # hour of occupancy the source says is gone.
    assert await version_of(sessions, tenant_id, WEEK) == 2


async def test_a_reported_removal_matches_the_stored_key_through_the_same_scrub(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
    source: CalendarSourceRecord,
) -> None:
    """The stored half of every reconciliation key went through the scrub, so a removal must go
    through it too: a provider echoing a UID with whitespace in it names an anchor the table no
    longer addresses under any other reading."""
    spaced = "evt-03@provider.test "
    commitments = (
        {
            "id": spaced,
            "summary": "Commitment 3",
            "start": {"dateTime": (NOW + timedelta(hours=4)).isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": (NOW + timedelta(hours=5)).isoformat(), "timeZone": "UTC"},
        },
        {
            "id": CANCELLED_UID,
            "summary": "Commitment 11",
            "start": {"dateTime": (NOW + timedelta(days=1)).isoformat(), "timeZone": "UTC"},
            "end": {
                "dateTime": (NOW + timedelta(days=1, minutes=30)).isoformat(),
                "timeZone": "UTC",
            },
        },
    )

    _first_rows, first_state = await run_a_poll(
        sessions,
        tenant_id,
        source,
        [ok(events_page(*commitments))],
    )

    second_rows, _second_state = await run_a_poll(
        sessions,
        tenant_id,
        replace(source, sync_state=first_state),
        [
            ok(
                events_page(
                    event(spaced, status="cancelled", start=None, end=None),
                    sync_token=NEXT_TOKEN,
                )
            )
        ],
    )

    assert [row.external_uid for row in second_rows] == [CANCELLED_UID]
