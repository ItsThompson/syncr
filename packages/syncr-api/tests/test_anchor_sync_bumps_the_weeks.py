"""Which weeks a sync invalidates, against a real Postgres and the real counter.

A commitment arriving, moving, or disappearing changes what a solve of its week read, and the week
input version is the counter a running solve is guarded on. So a pass that moved occupancy has to
bump the weeks it moved it in, in the same transaction as the rows it wrote.

The removal is why this is an integration suite rather than a unit one. ``remove_absent`` answers
with a COUNT, so a removed commitment's occupancy exists only in the state the pass read before the
delete; a fake repository would let a test pass while reading rows that a real statement had already
destroyed.

Four groups.

**Each of the three changes bumps, and the two non-changes bump nothing.** Create, move and remove,
against a read that changed nothing, a feed that answered 304, and a feed that could not be read.
The negative cases are what make this about a change rather than about an attempt: a poll runs every
fifteen minutes and most of them change nothing.

**A move names both weeks.** The week a commitment left has an hour free that its solve read as
occupied, so it is invalidated as well as the week the commitment arrived in.

**The expansion comes from the tenant's own declarations.** A 14-hour prep lead lands an exam's prep
the evening before, which is the previous ISO week, so that week is an input of the exam and is
invalidated by it. The discriminating pair is the same commitment under two different sets of
declared types: with a lead, and with types that cast nothing. A constant would answer both alike.

**Every range is closed at both ends.** The bound is not tidiness. An open-ended bump on a
fifteen-minute poll would invalidate every week the user has not yet lived on every pass that moved
one commitment, so no week would ever reach a write.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from syncr_api.anchors.reconcile import AnchorReconciler
from syncr_api.anchors.repository import AnchorRepository
from syncr_api.anchors.type_repository import AnchorTypeRepository
from syncr_api.calendars.config import ANCHOR_SOURCE, ICS
from syncr_api.calendars.events import FetchOutcome, RawEvent
from syncr_api.calendars.repository import CalendarSourceRepository
from syncr_api.core.db import create_db_engine, create_sessionmaker
from syncr_api.plans.config import FIRST_INPUT_VERSION
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.user_settings.solve_inputs import TrackedWeekInputVersions, WeekRange
from syncr_domain.intervals import Interval
from syncr_domain.weeks import IsoWeek
from tests.anchor_specifications import EXAM, STANDUP
from tests.live_tenants import delete_tenant, seed_owner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.anchors.records import AnchorTypeSpecification
    from syncr_api.calendars.anchor_writing import AnchorDelta
    from syncr_api.calendars.records import CalendarSourceRecord
    from syncr_domain.identifiers import TenantId

pytestmark = pytest.mark.integration

# The tenant's home zone here, which is also what a tenant that has never opened Settings holds.
# Every instant below is therefore a wall time as well as an instant, which is what makes the
# weekday claims in the test names readable.
HOME_ZONE = "UTC"

# 2026-02-09 is the Monday that opens 2026-W07.
WEEK = IsoWeek(2026, 7)
PREVIOUS_WEEK = IsoWeek(2026, 6)
NEXT_WEEK = IsoWeek(2026, 8)
MONDAY_0000 = datetime(2026, 2, 9, 0, 0, tzinfo=UTC)
MONDAY_0930 = datetime(2026, 2, 9, 9, 30, tzinfo=UTC)
WEDNESDAY_1000 = MONDAY_0000 + timedelta(days=2, hours=10)
NEXT_WEDNESDAY_1000 = WEDNESDAY_1000 + timedelta(days=7)
NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)

TIMETABLE = "https://example.ac.uk/timetable.ics"
LECTURE_UID = "lecture@example.ac.uk"


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


@pytest.fixture
async def source(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> CalendarSourceRecord:
    async with sessions() as session, session.begin():
        return await CalendarSourceRepository(session, tenant_id).create(
            provider=ICS,
            role=ANCHOR_SOURCE,
            display_name="University timetable",
            external_id=TIMETABLE,
            included=True,
            horizon_days=None,
            created_at=NOW,
        )


@dataclass
class RecordingVersions:
    """The real counter, with every range it was asked for kept.

    A wrapper rather than a substitute, so both halves of a bump are readable from one pass: the
    ranges the reconciler ASKED for, which is where the shape of the invalidation lives, and the
    rows that really moved, which is what a running solve is guarded against. A substitute would
    show the first and prove nothing about the second.
    """

    inner: TrackedWeekInputVersions
    asked: list[WeekRange] = field(default_factory=list)

    async def bump(self, weeks: WeekRange) -> None:
        self.asked.append(weeks)
        await self.inner.bump(weeks)

    @property
    def weeks(self) -> list[IsoWeek]:
        """The first week of every range asked for, in the order they were asked."""
        return [one.first for one in self.asked]


def an_event(
    uid: str = LECTURE_UID,
    *,
    title: str = "Computer Science Lecture",
    start: datetime = WEDNESDAY_1000,
    minutes: int = 120,
) -> RawEvent:
    return RawEvent(
        uid=uid,
        series_uid=None,
        title=title,
        interval=Interval(start, start + timedelta(minutes=minutes)),
        location="Lecture Theatre 3",
        sequence=0,
        all_day=False,
    )


def a_read(*events: RawEvent) -> FetchOutcome:
    """A fetch that actually read the feed, which is the only attempt that may remove."""
    return FetchOutcome(events=events, events_read=len(events), placed=len(events), reparsed=True)


async def track(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, *weeks: IsoWeek
) -> None:
    """Give each week a version row, which is what makes it a week the counter bumps.

    A week nobody has planned has no row and is deliberately left alone, so a suite that seeded
    none would read every assertion below as green while nothing was invalidated at all.
    """
    async with sessions() as session, session.begin():
        versions = WeekInputVersionRepository(session, tenant_id)
        for week in weeks:
            await versions.bump(week, at=NOW)


async def declare(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    specification: AnchorTypeSpecification,
) -> None:
    async with sessions() as session, session.begin():
        await AnchorTypeRepository(session, tenant_id).create(
            rule_order=0, specification=specification, created_at=NOW
        )


@asynccontextmanager
async def a_pass(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> AsyncIterator[tuple[AnchorReconciler, RecordingVersions]]:
    """The reconciler as both compositions build it, in one transaction, with its counter.

    One transaction per pass, because that is what a pass is: the rows a sync writes and the
    versions its changes invalidate either both land or neither does.
    """
    async with sessions() as session, session.begin():
        versions = RecordingVersions(
            TrackedWeekInputVersions(
                WeekInputVersionRepository(session, tenant_id), clock=lambda: NOW
            )
        )
        yield (
            AnchorReconciler(
                AnchorRepository(session, tenant_id),
                AnchorTypeRepository(session, tenant_id),
                versions=versions,
                home_zone=HOME_ZONE,
            ),
            versions,
        )


async def synced(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
    outcome: FetchOutcome,
) -> tuple[AnchorDelta, RecordingVersions]:
    """An attempt that actually read the feed, which is the only one that may remove."""
    async with a_pass(sessions, tenant_id) as (reconciler, versions):
        delta = await reconciler.reconcile(source, outcome)
    return delta, versions


async def confirmed(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> tuple[AnchorDelta, RecordingVersions]:
    """The 304 path: the feed answered "unchanged" and nothing was reparsed."""
    async with a_pass(sessions, tenant_id) as (reconciler, versions):
        delta = await reconciler.confirm(source)
    return delta, versions


async def marked_stale(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> tuple[AnchorDelta, RecordingVersions]:
    """The failure path: the feed could not be read, so nothing is known about its occupancy."""
    async with a_pass(sessions, tenant_id) as (reconciler, versions):
        delta = await reconciler.mark_possibly_stale(source)
    return delta, versions


async def version_of(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, week: IsoWeek
) -> int | None:
    async with sessions() as session:
        return await WeekInputVersionRepository(session, tenant_id).current(week)


def one_week(week: IsoWeek) -> list[WeekRange]:
    """The one range a pass that touched exactly ``week`` must ask for."""
    return [WeekRange(first=week, last=week)]


# --------------------------------------------------------------------------------
# The three changes each invalidate, and the two non-changes invalidate nothing.
# --------------------------------------------------------------------------------


async def test_a_created_commitment_invalidates_the_week_it_occupies(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    await track(sessions, tenant_id, WEEK)

    delta, versions = await synced(sessions, tenant_id, source, a_read(an_event()))

    assert delta.created == 1
    assert delta.occupied_weeks == frozenset({WEEK})
    assert versions.asked == one_week(WEEK)
    assert await version_of(sessions, tenant_id, WEEK) == FIRST_INPUT_VERSION + 1


async def test_a_commitment_moved_inside_its_week_invalidates_that_week(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # The lecture theatre changed the hour, not the day. The week's occupancy moved, so a solve
    # that placed work around the old hour read a week that no longer exists.
    await synced(sessions, tenant_id, source, a_read(an_event()))
    await track(sessions, tenant_id, WEEK)

    delta, versions = await synced(
        sessions,
        tenant_id,
        source,
        a_read(an_event(start=WEDNESDAY_1000 + timedelta(hours=3))),
    )

    assert delta.updated == 1
    assert versions.asked == one_week(WEEK)
    assert await version_of(sessions, tenant_id, WEEK) == FIRST_INPUT_VERSION + 1


async def test_a_removed_commitment_invalidates_the_week_it_occupied(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # The week the cancelled lecture occupied now has two free hours, which is the case a stale
    # plan is most visible in: the user is shown occupancy that the source says is gone.
    #
    # The capture has to happen before the delete. `remove_absent` answers with a count, so a pass
    # that read its prior state after the statement would have nothing left to derive this from.
    await synced(sessions, tenant_id, source, a_read(an_event()))
    await track(sessions, tenant_id, WEEK)

    delta, versions = await synced(sessions, tenant_id, source, a_read())

    assert (delta.removed, delta.current) == (1, 0)
    assert delta.occupied_weeks == frozenset({WEEK})
    assert versions.asked == one_week(WEEK)
    assert await version_of(sessions, tenant_id, WEEK) == FIRST_INPUT_VERSION + 1


async def test_a_read_that_changed_nothing_invalidates_nothing(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # THE ordinary case, and the one the bound exists for. A steady feed republishes every
    # component on every poll, so a pass that invalidated on every attempt would supersede a solve
    # of this week every fifteen minutes forever.
    await synced(sessions, tenant_id, source, a_read(an_event()))
    await track(sessions, tenant_id, WEEK)

    delta, versions = await synced(sessions, tenant_id, source, a_read(an_event()))

    assert (delta.created, delta.updated, delta.removed) == (0, 0, 0)
    assert delta.occupied_weeks == frozenset()
    assert versions.asked == []
    assert await version_of(sessions, tenant_id, WEEK) == FIRST_INPUT_VERSION


async def test_two_consecutive_polls_that_changed_nothing_invalidate_nothing_twice(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # The loop this closes is not one pass but the sequence: a poll that invalidated because the
    # previous poll had invalidated would hold a week superseded for as long as the feed exists.
    await synced(sessions, tenant_id, source, a_read(an_event()))
    await track(sessions, tenant_id, WEEK)

    _first, first_versions = await synced(sessions, tenant_id, source, a_read(an_event()))
    _second, second_versions = await synced(sessions, tenant_id, source, a_read(an_event()))

    assert first_versions.asked == []
    assert second_versions.asked == []
    assert await version_of(sessions, tenant_id, WEEK) == FIRST_INPUT_VERSION


async def test_a_feed_that_answered_unchanged_invalidates_nothing(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # A 304 means the last parse still stands, so no occupancy moved and there is nothing for a
    # running solve to have read wrongly.
    await synced(sessions, tenant_id, source, a_read(an_event()))
    await track(sessions, tenant_id, WEEK)

    delta, versions = await confirmed(sessions, tenant_id, source)

    assert delta.occupied_weeks == frozenset()
    assert versions.asked == []
    assert await version_of(sessions, tenant_id, WEEK) == FIRST_INPUT_VERSION


async def test_a_failed_sync_invalidates_nothing(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # A feed being down is not evidence that a lecture was cancelled. The anchors are retained and
    # marked possibly stale, the occupancy read on the last success still stands, and invalidating
    # here would make an unreachable publisher supersede a solve every fifteen minutes.
    await synced(sessions, tenant_id, source, a_read(an_event()))
    await track(sessions, tenant_id, WEEK)

    delta, versions = await marked_stale(sessions, tenant_id, source)

    assert delta.marked_stale == 1
    assert delta.occupied_weeks == frozenset()
    assert versions.asked == []
    assert await version_of(sessions, tenant_id, WEEK) == FIRST_INPUT_VERSION


# --------------------------------------------------------------------------------
# A move across a week boundary names both weeks.
# --------------------------------------------------------------------------------


async def test_a_commitment_moved_across_a_week_boundary_invalidates_the_week_it_left(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # The week it LEFT is the one a reading of the published event alone would miss: the feed's new
    # word says nothing about the hours it has just freed, and the solve of that week placed work
    # around occupancy that is no longer there.
    await synced(sessions, tenant_id, source, a_read(an_event()))
    await track(sessions, tenant_id, WEEK, NEXT_WEEK)

    delta, _versions = await synced(
        sessions, tenant_id, source, a_read(an_event(start=NEXT_WEDNESDAY_1000))
    )

    assert WEEK in delta.occupied_weeks
    assert await version_of(sessions, tenant_id, WEEK) == FIRST_INPUT_VERSION + 1


async def test_a_commitment_moved_across_a_week_boundary_invalidates_the_week_it_arrived_in(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # The arrival week, which now holds two hours of hard occupancy its own solve read as free.
    await synced(sessions, tenant_id, source, a_read(an_event()))
    await track(sessions, tenant_id, WEEK, NEXT_WEEK)

    delta, _versions = await synced(
        sessions, tenant_id, source, a_read(an_event(start=NEXT_WEDNESDAY_1000))
    )

    assert NEXT_WEEK in delta.occupied_weeks
    assert await version_of(sessions, tenant_id, NEXT_WEEK) == FIRST_INPUT_VERSION + 1


async def test_a_commitment_moved_across_a_week_boundary_invalidates_both_weeks(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # The pair as one set, and one range per week. Stated beside the two halves above rather than
    # instead of them: this assertion holds for a pass that named a THIRD week as well, and each
    # half names which side of the move it is about.
    await synced(sessions, tenant_id, source, a_read(an_event()))
    await track(sessions, tenant_id, WEEK, NEXT_WEEK)

    delta, versions = await synced(
        sessions, tenant_id, source, a_read(an_event(start=NEXT_WEDNESDAY_1000))
    )

    assert delta.updated == 1
    assert delta.occupied_weeks == frozenset({WEEK, NEXT_WEEK})
    assert versions.asked == [
        WeekRange(first=WEEK, last=WEEK),
        WeekRange(first=NEXT_WEEK, last=NEXT_WEEK),
    ]


async def test_a_commitment_spanning_a_week_boundary_invalidates_both_weeks(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # A residential week, one component: it occupies part of two ISO weeks and changes the
    # discretionary time of both.
    await track(sessions, tenant_id, WEEK, NEXT_WEEK)

    delta, _versions = await synced(
        sessions,
        tenant_id,
        source,
        a_read(an_event(start=WEDNESDAY_1000, minutes=6 * 24 * 60)),
    )

    assert delta.occupied_weeks == frozenset({WEEK, NEXT_WEEK})


# --------------------------------------------------------------------------------
# The expansion is read from the tenant's own declarations.
# --------------------------------------------------------------------------------


async def test_a_monday_morning_exam_invalidates_the_previous_week_through_its_prep_lead(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # `Exam` declares a 14-hour prep lead, so a 09:30 exam on a Monday casts prep at 19:30 the
    # evening before, which is the last evening of the PREVIOUS ISO week. That week's assembly
    # reads this commitment, so that week's inputs moved when it arrived.
    await declare(sessions, tenant_id, EXAM)
    await track(sessions, tenant_id, PREVIOUS_WEEK, WEEK)

    delta, versions = await synced(
        sessions,
        tenant_id,
        source,
        a_read(an_event(title="Databases Exam", start=MONDAY_0930, minutes=120)),
    )

    assert delta.created == 1
    assert delta.occupied_weeks == frozenset({PREVIOUS_WEEK, WEEK})
    assert versions.weeks == [PREVIOUS_WEEK, WEEK]


async def test_the_expansion_comes_from_the_tenants_types_rather_than_from_a_constant(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    """The discriminating pair: one commitment, two sets of declarations, two answers.

    A tenant whose types cast nothing gets the commitment's own week and no other. The same
    commitment for a tenant declaring a 14-hour lead gets the week before it as well. A hardcoded
    expansion would answer both the same way, whichever number it held.
    """
    await declare(sessions, tenant_id, STANDUP)
    await track(sessions, tenant_id, PREVIOUS_WEEK, WEEK)

    casting_nothing, _ = await synced(
        sessions,
        tenant_id,
        source,
        a_read(an_event(title="Databases Exam", start=MONDAY_0930, minutes=120)),
    )

    assert casting_nothing.occupied_weeks == frozenset({WEEK})

    await declare(sessions, tenant_id, EXAM)
    with_a_lead, _ = await synced(
        sessions,
        tenant_id,
        source,
        a_read(an_event(title="Databases Exam", start=MONDAY_0930 + timedelta(hours=1))),
    )

    assert with_a_lead.occupied_weeks == frozenset({PREVIOUS_WEEK, WEEK})


# --------------------------------------------------------------------------------
# Every range is closed at both ends.
# --------------------------------------------------------------------------------


async def test_every_range_a_sync_asks_for_is_closed_at_both_ends(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    """One range per week, each ending where it begins, over a pass that touched three weeks.

    The open-ended shape exists in the same module and is reserved for a mutation with no end date.
    Reached from here it would invalidate every week from the earliest one this feed touches
    onwards, on every pass that moved one commitment: each supersession enqueues a follow-up, the
    next poll fifteen minutes later supersedes that, and no week ever reaches a write. A range
    SPANNING these three would be the same failure in miniature, invalidating a week between two
    commitments that nothing changed.
    """
    await declare(sessions, tenant_id, EXAM)
    await track(sessions, tenant_id, PREVIOUS_WEEK, WEEK, NEXT_WEEK)

    _delta, versions = await synced(
        sessions,
        tenant_id,
        source,
        a_read(
            an_event("exam@example.ac.uk", title="Databases Exam", start=MONDAY_0930),
            an_event("away@example.ac.uk", start=NEXT_WEDNESDAY_1000),
        ),
    )

    assert versions.weeks == [PREVIOUS_WEEK, WEEK, NEXT_WEEK]
    for asked in versions.asked:
        assert asked.last == asked.first, asked


async def test_a_week_between_two_commitments_a_term_apart_is_not_invalidated(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # The control for the shape above. A range spanning what one pass touched would invalidate
    # every tracked week between two commitments, and this is the week that would notice.
    between = NEXT_WEEK
    await track(sessions, tenant_id, WEEK, between, IsoWeek(2026, 9))

    _delta, versions = await synced(
        sessions,
        tenant_id,
        source,
        a_read(
            an_event("near@example.ac.uk", start=WEDNESDAY_1000),
            an_event("far@example.ac.uk", start=WEDNESDAY_1000 + timedelta(days=14)),
        ),
    )

    assert versions.weeks == [WEEK, IsoWeek(2026, 9)]
    assert await version_of(sessions, tenant_id, between) == FIRST_INPUT_VERSION


async def test_a_week_nobody_has_planned_is_not_given_a_version_row_by_a_sync(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # A week with no row has no plan and no running solve to invalidate, and the write guard
    # already treats a missing row as a mismatch, so creating one here would buy nothing.
    delta, versions = await synced(sessions, tenant_id, source, a_read(an_event()))

    assert delta.occupied_weeks == frozenset({WEEK})
    assert versions.asked == one_week(WEEK)
    assert await version_of(sessions, tenant_id, WEEK) is None


async def test_the_pass_reports_how_many_weeks_it_invalidated(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # A count rather than the weeks themselves, for the same reason every other field of the tally
    # is a count: a log line carries what a support question needs and no commitment's own words.
    await declare(sessions, tenant_id, EXAM)

    delta, _versions = await synced(
        sessions,
        tenant_id,
        source,
        a_read(an_event(title="Databases Exam", start=MONDAY_0930)),
    )

    assert delta.as_log_fields()["anchors_weeks_occupied"] == 2
