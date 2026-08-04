"""Anchors against a real Postgres: the invariants the SCHEMA holds, and what reconciliation does.

A fake repository would catch none of what is asserted here. Every claim below is one the database
or a real statement makes:

- the reconciliation key is a unique index over ``(tenant_id, source_id, external_uid)``, whose
  existence is itself asserted because the invariant depends on the index being there;
- the three boundary rules are check constraints, so a writer that skipped the service cannot store
  a shadow that cannot be laid out;
- removing a calendar source removes the occupancy it contributed, by cascade;
- removing an anchor type leaves its commitments as opaque busy time rather than removing them;
- a successful read removes what the feed stopped publishing, and a failed one does not;
- a retype reaches every occurrence of a series, including ones a later sync creates;
- reordering rules re-evaluates the anchors a rule may still type, and only those;
- and the assembly's unpaged span read and the interface's paged one answer with the same
  commitments, asserted over the pairs at each edge of the span.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from syncr_api.anchors.config import (
    ANCHOR_PAGE_LIMIT_MAX,
    ANCHORS_TABLE,
    FORBIDS_AREAS,
    FORBIDS_EVERYTHING,
    FORBIDS_NOTHING,
)
from syncr_api.anchors.evaluation import RuleEvaluator
from syncr_api.anchors.identity import reconciliation_key
from syncr_api.anchors.reconcile import AnchorReconciler
from syncr_api.anchors.records import AnchorTypeSpecification
from syncr_api.anchors.repository import AnchorRepository
from syncr_api.anchors.type_repository import AnchorTypeRepository
from syncr_api.areas.repository import AreaRepository
from syncr_api.calendars.config import ANCHOR_SOURCE, ICS
from syncr_api.calendars.events import FetchOutcome, RawEvent
from syncr_api.calendars.repository import CalendarSourceRepository
from syncr_api.core.db import create_db_engine, create_sessionmaker
from syncr_domain.intervals import Interval
from tests.anchor_specifications import EXAM, INTERVIEW, LECTURE, NOTHING, STANDUP, with_areas
from tests.live_tenants import delete_tenant, seed_owner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.anchors.records import AnchorRecord, AnchorTypeRecord
    from syncr_api.calendars.anchor_writing import AnchorDelta
    from syncr_api.calendars.records import CalendarSourceId, CalendarSourceRecord
    from syncr_domain.identifiers import AreaId, TenantId

pytestmark = pytest.mark.integration

NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)
MONDAY_0900 = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)

RECONCILIATION_KEY_INDEX = "uq_anchors_tenant_id_source_id_external_uid"
HOUR = timedelta(hours=1)

TIMETABLE = "https://example.ac.uk/timetable.ics"
ASSESSMENTS = "https://example.ac.uk/assessments.ics"


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
    return await add_source(sessions, tenant_id)


async def add_source(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    *,
    external_id: str = TIMETABLE,
    display_name: str = "University timetable",
) -> CalendarSourceRecord:
    async with sessions() as session, session.begin():
        return await CalendarSourceRepository(session, tenant_id).create(
            provider=ICS,
            role=ANCHOR_SOURCE,
            display_name=display_name,
            external_id=external_id,
            included=True,
            horizon_days=None,
            created_at=NOW,
        )


async def add_area(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, *, name: str
) -> AreaId:
    async with sessions() as session, session.begin():
        created = await AreaRepository(session, tenant_id).create(
            parent_id=None,
            name=name,
            pigment_index=0,
            budget_percent=None,
            floor_hours=None,
            created_at=NOW,
        )
    return created.id


async def declare(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    specification: AnchorTypeSpecification,
    *,
    order: int,
) -> AnchorTypeRecord:
    async with sessions() as session, session.begin():
        return await AnchorTypeRepository(session, tenant_id).create(
            rule_order=order, specification=specification, created_at=NOW
        )


def an_event(
    uid: str,
    *,
    title: str = "Computer Science Lecture",
    series_uid: str | None = None,
    start: datetime = MONDAY_0900,
    minutes: int = 120,
    location: str | None = "Lecture Theatre 3",
) -> RawEvent:
    return RawEvent(
        uid=uid,
        series_uid=series_uid,
        title=title,
        interval=Interval(start, start + timedelta(minutes=minutes)),
        location=location,
        sequence=0,
        all_day=False,
    )


def a_read(*events: RawEvent) -> FetchOutcome:
    """A fetch that actually read the feed. ``reparsed`` is what permits a removal."""
    return FetchOutcome(events=events, events_read=len(events), placed=len(events), reparsed=True)


async def reconcile(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
    outcome: FetchOutcome,
) -> AnchorDelta:
    async with sessions() as session, session.begin():
        reconciler = AnchorReconciler(
            AnchorRepository(session, tenant_id), AnchorTypeRepository(session, tenant_id)
        )
        return await reconciler.reconcile(source, outcome)


async def held(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, source_id: CalendarSourceId
) -> tuple[AnchorRecord, ...]:
    async with sessions() as session:
        return await AnchorRepository(session, tenant_id).list_for_source(source_id)


# --------------------------------------------------------------------------------
# Invariant A2: the reconciliation key is the database's statement, not the code's.
# --------------------------------------------------------------------------------


async def test_the_reconciliation_key_is_a_unique_index(engine: AsyncEngine) -> None:
    # The invariant is the index. Asserted directly, because a migration that created the table
    # without it would leave every reconciliation test passing while one commitment could be stored
    # twice and displace two blocks.
    async with engine.connect() as connection:
        found = await connection.execute(
            text("SELECT indexdef FROM pg_indexes WHERE tablename = :table AND indexname = :index"),
            {"table": ANCHORS_TABLE, "index": RECONCILIATION_KEY_INDEX},
        )
        definition = found.scalar_one()

    assert "UNIQUE" in definition
    for column in ("tenant_id", "source_id", "external_uid"):
        assert column in definition


async def test_one_uid_cannot_be_stored_twice_for_one_source(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    async with sessions() as session, session.begin():
        anchors = AnchorRepository(session, tenant_id)
        await anchors.create(
            source_id=source.id,
            external_uid="lecture@example.ac.uk",
            series_uid=None,
            title="Lecture",
            interval=Interval(MONDAY_0900, MONDAY_0900 + timedelta(hours=2)),
            location=None,
            anchor_type_id=None,
            type_overridden=False,
        )
        with pytest.raises(IntegrityError):
            await anchors.create(
                source_id=source.id,
                external_uid="lecture@example.ac.uk",
                series_uid=None,
                title="Lecture, moved",
                interval=Interval(MONDAY_0900, MONDAY_0900 + timedelta(hours=3)),
                location=None,
                anchor_type_id=None,
                type_overridden=False,
            )


async def test_two_sources_publishing_one_uid_are_two_commitments(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    # The source is half of the key because two calendars can each carry the same meeting.
    # Excluding one must not remove the other's occupancy.
    timetable = await add_source(sessions, tenant_id)
    assessments = await add_source(sessions, tenant_id, external_id=ASSESSMENTS, display_name="B")
    shared = an_event("shared@example.ac.uk")

    await reconcile(sessions, tenant_id, timetable, a_read(shared))
    await reconcile(sessions, tenant_id, assessments, a_read(shared))

    assert len(await held(sessions, tenant_id, timetable.id)) == 1
    assert len(await held(sessions, tenant_id, assessments.id)) == 1


async def test_a_commitment_that_moved_is_updated_rather_than_replaced(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # Keyed on the UID and nothing else, so a lecture moved by an hour is one anchor at a new time.
    # Diffing on the title and the time would free every block it displaced and displace them again.
    await reconcile(sessions, tenant_id, source, a_read(an_event("lecture@example.ac.uk")))
    original = (await held(sessions, tenant_id, source.id))[0]

    moved = an_event(
        "lecture@example.ac.uk",
        title="Lecture, room changed",
        start=MONDAY_0900 + timedelta(hours=1),
    )
    delta = await reconcile(sessions, tenant_id, source, a_read(moved))

    after = (await held(sessions, tenant_id, source.id))[0]
    assert after.id == original.id
    assert after.interval == moved.interval
    assert after.title == "Lecture, room changed"
    assert (delta.created, delta.updated, delta.removed) == (0, 1, 0)


# --------------------------------------------------------------------------------
# Invariants A3 and A4: what a successful read removes, and what a failure does not.
# --------------------------------------------------------------------------------


async def test_a_successful_read_removes_what_the_feed_stopped_publishing(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    await reconcile(
        sessions,
        tenant_id,
        source,
        a_read(an_event("kept@example.ac.uk"), an_event("cancelled@example.ac.uk")),
    )

    delta = await reconcile(sessions, tenant_id, source, a_read(an_event("kept@example.ac.uk")))

    assert [anchor.external_uid for anchor in await held(sessions, tenant_id, source.id)] == [
        "kept@example.ac.uk"
    ]
    assert delta.removed == 1


async def test_a_feed_that_now_publishes_nothing_removes_everything_it_had(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # `keeping` empty is legal and means the feed published nothing. Only reachable from a read
    # that actually parsed, which is what the sync pass guarantees.
    await reconcile(sessions, tenant_id, source, a_read(an_event("gone@example.ac.uk")))

    await reconcile(sessions, tenant_id, source, a_read())

    assert await held(sessions, tenant_id, source.id) == ()


async def test_a_failed_attempt_retains_every_anchor_and_marks_it_possibly_stale(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    await reconcile(sessions, tenant_id, source, a_read(an_event("lecture@example.ac.uk")))

    async with sessions() as session, session.begin():
        reconciler = AnchorReconciler(
            AnchorRepository(session, tenant_id), AnchorTypeRepository(session, tenant_id)
        )
        delta = await reconciler.mark_possibly_stale(source)

    anchors = await held(sessions, tenant_id, source.id)
    assert len(anchors) == 1
    assert anchors[0].possibly_stale is True
    assert (delta.marked_stale, delta.removed, delta.current) == (1, 0, 1)


async def test_the_next_successful_read_clears_possibly_stale(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    await reconcile(sessions, tenant_id, source, a_read(an_event("lecture@example.ac.uk")))
    async with sessions() as session, session.begin():
        await AnchorRepository(session, tenant_id).set_possibly_stale(source.id, stale=True)

    await reconcile(sessions, tenant_id, source, a_read(an_event("lecture@example.ac.uk")))

    assert (await held(sessions, tenant_id, source.id))[0].possibly_stale is False


async def test_an_unchanged_feed_confirms_its_anchors_without_removing_one(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # A 304 means the last parse still stands. Nothing is created, nothing is removed, and a
    # commitment a previous failure marked possibly stale stops being stale.
    await reconcile(sessions, tenant_id, source, a_read(an_event("lecture@example.ac.uk")))
    async with sessions() as session, session.begin():
        await AnchorRepository(session, tenant_id).set_possibly_stale(source.id, stale=True)

    async with sessions() as session, session.begin():
        reconciler = AnchorReconciler(
            AnchorRepository(session, tenant_id), AnchorTypeRepository(session, tenant_id)
        )
        delta = await reconciler.confirm(source)

    anchors = await held(sessions, tenant_id, source.id)
    assert len(anchors) == 1
    assert anchors[0].possibly_stale is False
    assert delta.current == 1
    assert delta.removed == 0


async def test_removing_a_source_removes_the_occupancy_it_contributed(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    timetable = await add_source(sessions, tenant_id)
    assessments = await add_source(sessions, tenant_id, external_id=ASSESSMENTS, display_name="B")
    await reconcile(sessions, tenant_id, timetable, a_read(an_event("a@example.ac.uk")))
    await reconcile(sessions, tenant_id, assessments, a_read(an_event("b@example.ac.uk")))

    async with sessions() as session, session.begin():
        await CalendarSourceRepository(session, tenant_id).remove(timetable.id)

    assert await held(sessions, tenant_id, timetable.id) == ()
    assert len(await held(sessions, tenant_id, assessments.id)) == 1


async def test_a_steady_feed_reports_nothing_updated(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # `updated` has to mean CHANGED, not republished. A steady feed sends the same events every
    # fifteen minutes, so counting each one would report a number equal to the whole set forever and
    # say nothing at all about what moved.
    outcome = a_read(an_event("a@example"), an_event("b@example", start=MONDAY_0900 + HOUR))
    await reconcile(sessions, tenant_id, source, outcome)

    second = await reconcile(sessions, tenant_id, source, outcome)

    assert (second.created, second.updated, second.removed) == (0, 0, 0)
    assert second.current == 2


async def test_clearing_possibly_stale_counts_as_an_update(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # The other side of the count. An anchor a failed sync marked stale becomes unstale on the next
    # successful read, and that IS a change even though the published fact is identical.
    outcome = a_read(an_event("a@example"))
    await reconcile(sessions, tenant_id, source, outcome)
    async with sessions() as session, session.begin():
        await AnchorRepository(session, tenant_id).set_possibly_stale(source.id, stale=True)

    after = await reconcile(sessions, tenant_id, source, outcome)

    assert after.updated == 1
    assert (await held(sessions, tenant_id, source.id))[0].possibly_stale is False


async def test_a_moved_commitment_counts_as_one_update(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    outcome = a_read(an_event("a@example"), an_event("b@example", start=MONDAY_0900 + HOUR))
    await reconcile(sessions, tenant_id, source, outcome)

    moved = await reconcile(
        sessions,
        tenant_id,
        source,
        a_read(
            an_event("a@example", start=MONDAY_0900 + timedelta(hours=3)),
            an_event("b@example", start=MONDAY_0900 + HOUR),
        ),
    )

    assert moved.updated == 1


# --------------------------------------------------------------------------------
# The facts an anchor keeps: its real time, and a whole all-day span.
# --------------------------------------------------------------------------------


async def test_an_anchor_keeps_its_real_time_even_at_seven_minutes_past(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # Anchors are exempt from the fifteen-minute snap. A snapped anchor would be syncr asserting
    # the university's timetable is wrong.
    odd = datetime(2026, 2, 10, 16, 7, tzinfo=UTC)

    await reconcile(
        sessions, tenant_id, source, a_read(an_event("odd@example.ac.uk", start=odd, minutes=38))
    )

    stored = (await held(sessions, tenant_id, source.id))[0]
    assert stored.interval.start == odd
    assert stored.interval.end == odd + timedelta(minutes=38)


async def test_a_whole_day_span_is_stored_as_the_span_the_adapter_resolved(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # The zone question is the adapter's: it turns `VALUE=DATE` into the local day's instants in
    # the zone active on that date. What is asserted here is that reconciliation stores that span
    # whole rather than re-deriving it.
    midnight = datetime(2026, 6, 15, 23, 0, tzinfo=UTC)
    whole_day = an_event("holiday@example.org", start=midnight, minutes=24 * 60)

    await reconcile(sessions, tenant_id, source, a_read(whole_day))

    assert (await held(sessions, tenant_id, source.id))[0].interval == whole_day.interval


async def test_a_zero_length_anchor_cannot_be_stored(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # The adapter rejects an event with no end before this is reached, and `Interval` refuses to
    # build one, so the row is written in raw SQL: what is asserted is that the DATABASE refuses it
    # too, which is what makes "syncr cannot reason about occupancy without a duration"
    # unbypassable rather than a property of two layers above it.
    async with sessions() as session, session.begin():
        with pytest.raises(DBAPIError, match="occupies_time"):
            await session.execute(
                text(
                    f"INSERT INTO {ANCHORS_TABLE} "  # noqa: S608 - a constant table name
                    "(id, source_id, external_uid, title, starts_at, ends_at, type_overridden, "
                    "possibly_stale, tenant_id) VALUES "
                    "(:id, :source_id, :uid, :title, :at, :at, false, false, :tenant_id)"
                ),
                {
                    "id": str(uuid4()),
                    "source_id": str(source.id),
                    "uid": "instant@example.ac.uk",
                    "title": "A commitment with no duration",
                    "at": MONDAY_0900,
                    "tenant_id": str(tenant_id),
                },
            )
        await session.rollback()


async def test_an_oversized_published_uid_still_reconciles_to_one_anchor(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # A UID longer than the column is digested rather than cut, and the digest is stable, so the
    # second read matches the row the first created instead of failing on the unique index.
    huge = "u" * 5_000
    outcome = a_read(an_event(huge))

    await reconcile(sessions, tenant_id, source, outcome)
    await reconcile(sessions, tenant_id, source, outcome)

    anchors = await held(sessions, tenant_id, source.id)
    assert len(anchors) == 1
    assert anchors[0].external_uid == reconciliation_key(huge)


async def test_a_control_character_from_a_publisher_reconciles_rather_than_raising(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # THE must-fix, end to end against real Postgres. `str.split()` does not remove a NUL, so before
    # the scrub this reached the VARCHAR column and asyncpg raised CharacterNotInRepertoireError out
    # of the flush. In a sync pass that raise happened BEFORE the sync state was written, so a third
    # party who can put an event on a subscribed calendar could stop the user's sync with one byte
    # and leave nothing on the panel built to report it.
    hostile = an_event(
        "lecture\x00@example.ac.uk",
        title="Computer Science\x00Lecture",
        series_uid="series\x00@example.ac.uk",
        location="Lecture\x00Theatre 3",
    )

    delta = await reconcile(sessions, tenant_id, source, a_read(hostile))

    anchors = await held(sessions, tenant_id, source.id)
    assert delta.created == 1
    assert len(anchors) == 1
    stored = anchors[0]
    for value in (stored.external_uid, stored.series_uid, stored.title, stored.location):
        assert value is not None
        assert "\x00" not in value
    assert "Computer Science" in stored.title


async def test_a_control_character_bearing_feed_still_reconciles_on_the_second_pass(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # The scrub has to be stable, or the second sync creates a second anchor for one commitment and
    # the unique index refuses it. Asserted separately, because a scrub using a random or positional
    # fallback would pass the test above and fail here.
    outcome = a_read(an_event("l\x00@example", title="Systems\x00Lecture"))

    await reconcile(sessions, tenant_id, source, outcome)
    second = await reconcile(sessions, tenant_id, source, outcome)

    assert (second.created, second.removed) == (0, 0)
    assert len(await held(sessions, tenant_id, source.id)) == 1


async def test_a_scrubbed_commitment_is_counted_so_the_drop_is_not_silent(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # Dropping a byte silently alters a publisher's data. A user looking at `SystemsLecture` on the
    # grid, or at a match rule that stopped matching, needs something to go on, and so does whoever
    # answers the support question. Counted per commitment rather than per value, so a feed whose
    # every field carries a bad byte reports the number of commitments rather than four times it.
    delta = await reconcile(
        sessions,
        tenant_id,
        source,
        a_read(
            an_event("clean@example", title="Systems Lecture"),
            an_event(
                "dirty\x00@example",
                title="Maths\x00Lecture",
                location="Room\x00 3",
                start=MONDAY_0900 + HOUR,
            ),
        ),
    )

    assert delta.scrubbed == 1
    assert delta.created == 2
    assert "anchors_scrubbed" in delta.as_log_fields()


async def test_a_clean_feed_counts_nothing_scrubbed(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # The control. Without it, the count could report every commitment and still look right in the
    # test above.
    delta = await reconcile(sessions, tenant_id, source, a_read(an_event("clean@example")))

    assert delta.scrubbed == 0


async def test_a_folded_summary_is_not_counted_as_scrubbed(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # A whitespace control is folded, not dropped, so it changes no word and must not be reported as
    # data loss. Counting it would make the number useless on any feed that folds a long SUMMARY.
    delta = await reconcile(
        sessions, tenant_id, source, a_read(an_event("f@example", title="Computer\r\n\tScience"))
    )

    assert delta.scrubbed == 0
    assert (await held(sessions, tenant_id, source.id))[0].title == "Computer Science"


# --------------------------------------------------------------------------------
# Typing: first match wins, and the override that persists on the series.
# --------------------------------------------------------------------------------


async def test_a_created_anchor_is_typed_by_the_first_matching_rule(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    lecture = await declare(sessions, tenant_id, LECTURE, order=0)
    await declare(sessions, tenant_id, INTERVIEW, order=1)

    await reconcile(
        sessions, tenant_id, source, a_read(an_event("l@example", title="Systems Lecture"))
    )

    stored = (await held(sessions, tenant_id, source.id))[0]
    assert stored.anchor_type_id == lecture.id
    assert stored.type_overridden is False


async def test_an_anchor_no_rule_matches_is_opaque_busy_time_with_no_type(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    await declare(sessions, tenant_id, LECTURE, order=0)

    await reconcile(sessions, tenant_id, source, a_read(an_event("d@example", title="Dentist")))

    stored = (await held(sessions, tenant_id, source.id))[0]
    assert stored.anchor_type_id is None
    assert stored.type_overridden is False


async def test_a_retype_reaches_every_occurrence_of_the_series(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    standup = await declare(sessions, tenant_id, STANDUP, order=0)
    occurrences = [
        an_event(
            f"standup@example#{day}",
            title="Daily standup",
            series_uid="standup@example",
            start=MONDAY_0900 + timedelta(days=day),
        )
        for day in range(5)
    ]
    await reconcile(sessions, tenant_id, source, a_read(*occurrences))

    async with sessions() as session, session.begin():
        moved = await AnchorRepository(session, tenant_id).retype_series(
            source_id=source.id, series_uid="standup@example", anchor_type_id=standup.id
        )

    anchors = await held(sessions, tenant_id, source.id)
    assert moved == len(occurrences)
    assert {anchor.anchor_type_id for anchor in anchors} == {standup.id}
    assert all(anchor.type_overridden for anchor in anchors)


async def test_a_later_occurrence_arriving_from_the_source_inherits_the_override(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # The reason a daily standup is typed once rather than 250 times. The override is read off the
    # occurrences already held, BEFORE anything is written, so it survives the horizon rolling on.
    interview = await declare(sessions, tenant_id, INTERVIEW, order=0)
    monday = an_event("standup@example#1", title="Daily standup", series_uid="standup@example")
    await reconcile(sessions, tenant_id, source, a_read(monday))
    async with sessions() as session, session.begin():
        await AnchorRepository(session, tenant_id).retype_series(
            source_id=source.id, series_uid="standup@example", anchor_type_id=interview.id
        )

    tuesday = an_event(
        "standup@example#2",
        title="Daily standup",
        series_uid="standup@example",
        start=MONDAY_0900 + timedelta(days=1),
    )
    await reconcile(sessions, tenant_id, source, a_read(monday, tuesday))

    inherited = next(
        anchor
        for anchor in await held(sessions, tenant_id, source.id)
        if anchor.external_uid == "standup@example#2"
    )
    assert inherited.anchor_type_id == interview.id
    assert inherited.type_overridden is True


async def test_a_series_whose_occurrences_all_turn_over_still_inherits_the_override(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # The case the read-before-write ordering exists for: every occurrence the tenant holds drops
    # out of the feed in the same pass that brings new ones in.
    interview = await declare(sessions, tenant_id, INTERVIEW, order=0)
    week_one = an_event("standup@example#1", title="Daily standup", series_uid="standup@example")
    await reconcile(sessions, tenant_id, source, a_read(week_one))
    async with sessions() as session, session.begin():
        await AnchorRepository(session, tenant_id).retype_series(
            source_id=source.id, series_uid="standup@example", anchor_type_id=interview.id
        )

    week_two = an_event(
        "standup@example#8",
        title="Daily standup",
        series_uid="standup@example",
        start=MONDAY_0900 + timedelta(days=7),
    )
    await reconcile(sessions, tenant_id, source, a_read(week_two))

    anchors = await held(sessions, tenant_id, source.id)
    assert [anchor.external_uid for anchor in anchors] == ["standup@example#8"]
    assert anchors[0].anchor_type_id == interview.id
    assert anchors[0].type_overridden is True


async def test_an_override_survives_a_retitle_that_another_rule_would_match(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # The override is on the anchor, so it outranks both the rules and the series lookup. A
    # publisher renaming an event must not undo a decision the user made.
    lecture = await declare(sessions, tenant_id, LECTURE, order=0)
    interview = await declare(sessions, tenant_id, INTERVIEW, order=1)
    await reconcile(sessions, tenant_id, source, a_read(an_event("x@example", title="Dentist")))
    async with sessions() as session, session.begin():
        anchor = (await AnchorRepository(session, tenant_id).list_for_source(source.id))[0]
        await AnchorRepository(session, tenant_id).retype_one(
            anchor.id, anchor_type_id=interview.id
        )

    await reconcile(
        sessions, tenant_id, source, a_read(an_event("x@example", title="Systems Lecture"))
    )

    stored = (await held(sessions, tenant_id, source.id))[0]
    assert stored.title == "Systems Lecture"
    assert stored.anchor_type_id == interview.id
    assert stored.anchor_type_id != lecture.id


async def test_a_rule_match_is_recomputed_when_the_title_changes(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # The other side of the rule above. A match was derived from the title, so a retitle has to
    # re-derive it; only an OVERRIDE is preserved.
    lecture = await declare(sessions, tenant_id, LECTURE, order=0)
    await reconcile(
        sessions, tenant_id, source, a_read(an_event("x@example", title="Systems Lecture"))
    )
    assert (await held(sessions, tenant_id, source.id))[0].anchor_type_id == lecture.id

    await reconcile(sessions, tenant_id, source, a_read(an_event("x@example", title="Dentist")))

    assert (await held(sessions, tenant_id, source.id))[0].anchor_type_id is None


# --------------------------------------------------------------------------------
# Re-evaluation: reordering rules re-types existing anchors, and only the right ones.
# --------------------------------------------------------------------------------


async def test_reordering_rules_re_evaluates_existing_anchors(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    broad = await declare(
        sessions, tenant_id, replace(NOTHING, name="Anything at uni", match_source_id=None), order=0
    )
    narrow = await declare(sessions, tenant_id, LECTURE, order=1)
    await reconcile(
        sessions, tenant_id, source, a_read(an_event("l@example", title="Systems Lecture"))
    )
    assert (await held(sessions, tenant_id, source.id))[0].anchor_type_id == broad.id

    async with sessions() as session, session.begin():
        types = AnchorTypeRepository(session, tenant_id)
        await types.set_rule_order(narrow.id, rule_order=0)
        await types.set_rule_order(broad.id, rule_order=1)
        retyped = await RuleEvaluator(AnchorRepository(session, tenant_id), types).re_evaluate()

    assert retyped == 1
    assert (await held(sessions, tenant_id, source.id))[0].anchor_type_id == narrow.id


async def test_re_evaluation_leaves_an_overridden_anchor_alone(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    lecture = await declare(sessions, tenant_id, LECTURE, order=0)
    interview = await declare(sessions, tenant_id, INTERVIEW, order=1)
    await reconcile(
        sessions, tenant_id, source, a_read(an_event("l@example", title="Systems Lecture"))
    )
    async with sessions() as session, session.begin():
        anchor = (await AnchorRepository(session, tenant_id).list_for_source(source.id))[0]
        await AnchorRepository(session, tenant_id).retype_one(
            anchor.id, anchor_type_id=interview.id
        )

    async with sessions() as session, session.begin():
        types = AnchorTypeRepository(session, tenant_id)
        retyped = await RuleEvaluator(AnchorRepository(session, tenant_id), types).re_evaluate()

    assert retyped == 0
    stored = (await held(sessions, tenant_id, source.id))[0]
    assert stored.anchor_type_id == interview.id
    assert stored.anchor_type_id != lecture.id


async def test_re_evaluation_writes_nothing_when_no_answer_moved(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    await declare(sessions, tenant_id, LECTURE, order=0)
    await reconcile(
        sessions, tenant_id, source, a_read(an_event("l@example", title="Systems Lecture"))
    )

    async with sessions() as session, session.begin():
        types = AnchorTypeRepository(session, tenant_id)
        retyped = await RuleEvaluator(AnchorRepository(session, tenant_id), types).re_evaluate()

    assert retyped == 0


async def test_releasing_a_type_returns_its_anchors_to_rule_matching(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # An override naming a type nobody can name any more is a state no route could leave, so
    # removing the type clears the flag as well as the identifier.
    interview = await declare(sessions, tenant_id, INTERVIEW, order=0)
    lecture = await declare(sessions, tenant_id, LECTURE, order=1)
    await reconcile(
        sessions, tenant_id, source, a_read(an_event("l@example", title="Systems Lecture"))
    )
    async with sessions() as session, session.begin():
        anchor = (await AnchorRepository(session, tenant_id).list_for_source(source.id))[0]
        await AnchorRepository(session, tenant_id).retype_one(
            anchor.id, anchor_type_id=interview.id
        )

    async with sessions() as session, session.begin():
        anchors = AnchorRepository(session, tenant_id)
        types = AnchorTypeRepository(session, tenant_id)
        released = await anchors.release_type(interview.id)
        await types.remove(interview.id)
        await RuleEvaluator(anchors, types).re_evaluate()

    stored = (await held(sessions, tenant_id, source.id))[0]
    assert released == 1
    assert stored.anchor_type_id == lecture.id
    assert stored.type_overridden is False


async def test_removing_a_type_leaves_its_commitments_as_busy_time(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # The foreign key is SET NULL rather than CASCADE: a commitment is a fact, and removing a
    # declaration about it must not remove the commitment.
    lecture = await declare(sessions, tenant_id, LECTURE, order=0)
    await reconcile(
        sessions, tenant_id, source, a_read(an_event("l@example", title="Systems Lecture"))
    )

    async with sessions() as session, session.begin():
        await AnchorTypeRepository(session, tenant_id).remove(lecture.id)

    anchors = await held(sessions, tenant_id, source.id)
    assert len(anchors) == 1
    assert anchors[0].anchor_type_id is None


# --------------------------------------------------------------------------------
# The boundary rules as check constraints: the guarantee behind the stated 422.
# --------------------------------------------------------------------------------


async def test_the_transit_rule_is_a_check_constraint(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    late = replace(NOTHING, name="Late", transit_lead_minutes=20, transit_duration_minutes=30)

    with pytest.raises(DBAPIError, match="arrives_before_the_anchor"):
        await declare(sessions, tenant_id, late, order=0)


async def test_the_prep_collision_rule_is_a_check_constraint(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    colliding = replace(
        NOTHING,
        name="Colliding",
        prep_lead_minutes=60,
        prep_duration_minutes=30,
        transit_lead_minutes=60,
        transit_duration_minutes=30,
    )

    with pytest.raises(DBAPIError, match="prep_finishes_before"):
        await declare(sessions, tenant_id, colliding, order=0)


async def test_the_database_accepts_a_transit_only_type_with_no_prep(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    # The constraint's guard on a non-zero prep duration, in SQL. Without `prep_duration_minutes =
    # 0 OR ...` the rendered `Lecture` is a row the database refuses.
    stored = await declare(sessions, tenant_id, LECTURE, order=0)

    assert stored.specification.prep_duration_minutes == 0
    assert stored.specification.transit_duration_minutes == 30


@pytest.mark.parametrize(
    ("scope", "areas"),
    [(FORBIDS_AREAS, 0), (FORBIDS_EVERYTHING, 1), (FORBIDS_NOTHING, 1)],
    ids=["areas-with-none", "everything-with-some", "nothing-with-some"],
)
async def test_a_scope_disagreeing_with_its_areas_is_a_check_constraint(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, scope: str, areas: int
) -> None:
    disagreeing = replace(
        NOTHING,
        name=f"Disagreeing {scope} {areas}",
        post_buffer_minutes=75,
        post_scope=scope,  # type: ignore[arg-type]  # parametrized over the literal's members
        forbidden_area_ids=tuple(uuid4() for _ in range(areas)),
    )

    with pytest.raises(DBAPIError, match="only_the_areas_scope_names_areas"):
        await declare(sessions, tenant_id, disagreeing, order=0)


async def test_two_types_cannot_share_a_name(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    await declare(sessions, tenant_id, LECTURE, order=0)

    with pytest.raises(IntegrityError):
        await declare(sessions, tenant_id, replace(EXAM, name="Lecture"), order=1)


async def test_a_forbidden_area_list_round_trips_through_jsonb(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    career = await add_area(sessions, tenant_id, name="Career")
    study = await add_area(sessions, tenant_id, name="Study")
    transit = await add_area(sessions, tenant_id, name="Transit")
    interview = with_areas(INTERVIEW, prep=career, transit=transit, forbidden=[career, study])

    stored = await declare(sessions, tenant_id, interview, order=0)

    assert stored.specification.forbidden_area_ids == (career, study)
    assert stored.specification.prep_area_id == career
    assert stored.specification.transit_area_id == transit


async def test_an_areas_removal_leaves_the_type_and_its_own_areas_alone(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    # Areas are permanent in P0, so this is not a route anyone can take. What it proves is that the
    # `SET NULL` on the Area foreign keys is what a future removal would do: it does not take a
    # hand-authored shadow declaration with it.
    career = await add_area(sessions, tenant_id, name="Career")
    stored = await declare(
        sessions, tenant_id, with_areas(INTERVIEW, prep=career, forbidden=[career]), order=0
    )
    assert stored.specification.post_scope == FORBIDS_AREAS

    async with sessions() as session, session.begin():
        await session.execute(
            text("DELETE FROM areas WHERE id = :area_id"), {"area_id": str(career)}
        )

    async with sessions() as session:
        after = await AnchorTypeRepository(session, tenant_id).find(stored.id)

    assert after is not None
    assert after.specification.prep_area_id is None
    assert after.specification.prep_lead_minutes == INTERVIEW.prep_lead_minutes


# --------------------------------------------------------------------------------
# Reading a span, and the page cursor.
# --------------------------------------------------------------------------------


async def test_a_span_read_includes_a_commitment_that_began_before_it(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # Overlapping rather than contained. A lecture that started before the span and runs into it
    # occupies time inside it, and missing it would report a free hour the user is in a lecture for.
    straddling = an_event("s@example", start=MONDAY_0900 - timedelta(hours=1), minutes=180)
    await reconcile(sessions, tenant_id, source, a_read(straddling))

    async with sessions() as session:
        found = await AnchorRepository(session, tenant_id).in_span(
            Interval(MONDAY_0900, MONDAY_0900 + timedelta(hours=1)), limit=10
        )

    assert [anchor.external_uid for anchor in found] == ["s@example"]


async def test_a_span_read_excludes_a_commitment_that_ended_before_it(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # Half-open, so a commitment ending exactly at the span's start is outside it.
    earlier = an_event("e@example", start=MONDAY_0900 - timedelta(hours=2), minutes=120)
    await reconcile(sessions, tenant_id, source, a_read(earlier))

    async with sessions() as session:
        found = await AnchorRepository(session, tenant_id).in_span(
            Interval(MONDAY_0900, MONDAY_0900 + timedelta(hours=1)), limit=10
        )

    assert found == ()


async def test_the_page_cursor_walks_the_whole_span_once(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # Keyset paging over `(starts_at, id)`. Two commitments share a start, so the identifier is
    # what breaks the tie and what stops one page repeating a row the previous page returned.
    events = [
        an_event(f"a{index}@example", start=MONDAY_0900 + timedelta(hours=index // 2), minutes=30)
        for index in range(6)
    ]
    await reconcile(sessions, tenant_id, source, a_read(*events))
    span = Interval(MONDAY_0900, MONDAY_0900 + timedelta(days=1))

    walked: list[str] = []
    after: tuple[datetime, object] | None = None
    async with sessions() as session:
        anchors = AnchorRepository(session, tenant_id)
        for _page in range(4):
            page = await anchors.in_span(span, limit=2, after=after)  # type: ignore[arg-type]
            if not page:
                break
            walked.extend(anchor.external_uid for anchor in page)
            after = (page[-1].interval.start, page[-1].id)

    assert sorted(walked) == sorted(event.uid for event in events)
    assert len(walked) == len(set(walked))


async def test_an_unpaged_span_read_answers_with_every_commitment_inside_it(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # The assembly's read. More commitments than the interface's largest page, because what this
    # asserts is that no page boundary decides what a week believes is occupied.
    events = [
        an_event(f"p{index}@example", start=MONDAY_0900 + timedelta(minutes=index), minutes=5)
        for index in range(ANCHOR_PAGE_LIMIT_MAX + 3)
    ]
    await reconcile(sessions, tenant_id, source, a_read(*events))

    async with sessions() as session:
        found = await AnchorRepository(session, tenant_id).overlapping(
            Interval(MONDAY_0900, MONDAY_0900 + timedelta(days=1))
        )

    assert len(found) == len(events)
    assert [anchor.external_uid for anchor in found] == [event.uid for event in events]


async def test_the_unpaged_read_and_the_paged_one_agree_at_every_boundary(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # Two statements of one predicate, crossed against each other over the pairs that decide it:
    # a commitment that abuts each edge, straddles each edge, is contained, and contains the span.
    # The two reads serve different callers and must not disagree about what a span holds.
    span = Interval(MONDAY_0900, MONDAY_0900 + timedelta(hours=2))
    placements = {
        "ends-at-start": (MONDAY_0900 - timedelta(hours=1), 60),
        "ends-one-minute-in": (MONDAY_0900 - timedelta(hours=1), 61),
        "starts-at-start": (MONDAY_0900, 30),
        "contained": (MONDAY_0900 + timedelta(minutes=30), 30),
        "straddles-the-end": (MONDAY_0900 + timedelta(minutes=90), 60),
        "starts-at-end": (MONDAY_0900 + timedelta(hours=2), 60),
        "starts-one-minute-before-the-end": (MONDAY_0900 + timedelta(minutes=119), 60),
        "covers-the-whole-span": (MONDAY_0900 - timedelta(hours=1), 240),
        "wholly-before": (MONDAY_0900 - timedelta(days=1), 60),
        "wholly-after": (MONDAY_0900 + timedelta(days=1), 60),
        "one-minute-long-at-the-start": (MONDAY_0900, 1),
    }
    await reconcile(
        sessions,
        tenant_id,
        source,
        a_read(
            *(
                an_event(f"{name}@example", start=start, minutes=minutes)
                for name, (start, minutes) in placements.items()
            )
        ),
    )

    async with sessions() as session:
        anchors = AnchorRepository(session, tenant_id)
        unpaged = await anchors.overlapping(span)
        paged = await anchors.in_span(span, limit=len(placements))

    inside = {anchor.external_uid for anchor in unpaged}
    assert inside == {anchor.external_uid for anchor in paged}
    assert inside == {
        "ends-one-minute-in@example",
        "starts-at-start@example",
        "contained@example",
        "straddles-the-end@example",
        "starts-one-minute-before-the-end@example",
        "covers-the-whole-span@example",
        "one-minute-long-at-the-start@example",
    }


def test_the_anchor_type_specification_names_every_column_the_ticket_requires() -> None:
    # A migration test would prove the columns exist; this proves the SHAPE the code is stated over
    # holds them, so a column added to the table without a field is a failure here rather than a
    # value nothing reads.
    required = {
        "name",
        "match_title_contains",
        "match_source_id",
        "prep_lead_minutes",
        "prep_duration_minutes",
        "prep_area_id",
        "transit_lead_minutes",
        "transit_duration_minutes",
        "return_transit_minutes",
        "transit_area_id",
        "post_buffer_minutes",
        "post_scope",
        "forbidden_area_ids",
    }

    assert set(AnchorTypeSpecification.__dataclass_fields__) == required
