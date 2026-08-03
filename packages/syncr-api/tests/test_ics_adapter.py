"""The adapter's own contract: three answers, three sync states, and no raised exception.

The transport is faked and the parser is real. What is asserted here is the sync-state
arithmetic section 06 states, which is the part that decides whether a stale feed is visible:
which fields move on a success, which are retained on a failure, and that an unchanged feed is
a success that reparses nothing.

The fetcher is matched by URL rather than by call order, so adding a source to a test does not
break an unrelated one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syncr_api.calendars.config import ANCHOR_SOURCE, ICS, MISSING_DURATION
from syncr_api.calendars.feeds import FeedAnswer, FeedBody, FeedUnchanged, FeedUnreachable
from syncr_api.calendars.ics_adapter import IcsAdapter
from syncr_api.calendars.records import CalendarSourceRecord, SyncStateRecord
from syncr_api.calendars.sync_state import RETAINED_NOTICE
from syncr_domain.intervals import Interval
from syncr_domain.zones import ZoneProfile
from tests.hostile_ics import ASSESSMENTS_FEED, EMPTY_FEED, UNIVERSITY_TIMETABLE

if TYPE_CHECKING:
    from collections.abc import Mapping

FEED_URL = "https://example.ac.uk/timetable.ics"
HOME = ZoneProfile(home_zone="Europe/London")
NOW = datetime(2026, 2, 9, 7, 0, tzinfo=UTC)
EARLIER = NOW - timedelta(hours=6)
HORIZON = Interval(datetime(2026, 2, 9, 0, 0, tzinfo=UTC), datetime(2026, 2, 23, 0, 0, tzinfo=UTC))

ETAG = 'etag:"w/12345"'


@dataclass
class RecordedFetcher:
    """A :class:`~syncr_api.calendars.feeds.FeedFetcher` answering from a recorded map.

    Records the cursor each call sent, because "an unchanged ETag short-circuits" is a claim
    about what was SENT as much as about what came back.
    """

    answers: Mapping[str, FeedAnswer]
    sent: list[str | None] = field(default_factory=list)

    async def get(self, url: str, *, cursor: str | None) -> FeedAnswer:
        self.sent.append(cursor)
        return self.answers[url]


def source(**overrides: object) -> CalendarSourceRecord:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "provider": ICS,
        "role": ANCHOR_SOURCE,
        "display_name": "University timetable",
        "external_id": FEED_URL,
        "included": True,
        "horizon_days": None,
        "sync_state": SyncStateRecord(),
    }
    return CalendarSourceRecord(**{**defaults, **overrides})  # type: ignore[arg-type]


def adapter(answer: FeedAnswer) -> tuple[IcsAdapter, RecordedFetcher]:
    fetcher = RecordedFetcher(answers={FEED_URL: answer})
    return (
        IcsAdapter(fetcher=fetcher, profile=HOME, horizon=HORIZON, clock=lambda: NOW),
        fetcher,
    )


def synced(anchors: int = 12, **overrides: object) -> SyncStateRecord:
    """A source that last succeeded six hours ago, which is what a retention claim needs."""
    defaults: dict[str, object] = {
        "last_success_at": EARLIER,
        "last_attempt_at": EARLIER,
        "last_error": None,
        "cursor": ETAG,
        "events_read": 30,
        "anchors_current": anchors,
        "rejections": (),
    }
    return SyncStateRecord(**{**defaults, **overrides})  # type: ignore[arg-type]


async def test_a_read_feed_returns_events_and_a_successful_attempt() -> None:
    ics, _ = adapter(FeedBody(body=UNIVERSITY_TIMETABLE, cursor=ETAG))

    outcome, state = await ics.fetch(source())

    assert outcome.reparsed is True
    assert len(outcome.events) == 3
    assert state.last_success_at == NOW
    assert state.last_attempt_at == NOW
    assert state.last_error is None
    assert state.cursor == ETAG
    assert state.anchors_current == 3


async def test_a_parse_that_rejected_events_is_still_a_successful_fetch() -> None:
    # The row section 06 is most specific about: a feed that half-works must read as neither
    # fully working nor fully broken.
    ics, _ = adapter(FeedBody(body=ASSESSMENTS_FEED, cursor=ETAG))

    _outcome, state = await ics.fetch(source())

    assert state.last_error is None
    assert state.last_success_at == NOW
    assert [item.kind for item in state.rejections] == [MISSING_DURATION]
    assert state.rejected_count == 1
    assert state.events_read == 3
    assert state.anchors_current == 2


async def test_an_unchanged_feed_short_circuits_and_records_a_successful_attempt() -> None:
    held = synced()
    ics, fetcher = adapter(FeedUnchanged(cursor=held.cursor))

    outcome, state = await ics.fetch(source(sync_state=held))

    # The conditional validator was sent, which is what made the short-circuit possible.
    assert fetcher.sent == [ETAG]
    assert outcome.reparsed is False
    assert outcome.events == ()
    # A success: both instants move, and every count describing the still-current parse stays.
    assert state.last_success_at == NOW
    assert state.last_attempt_at == NOW
    assert state.last_error is None
    assert state.events_read == 30
    assert state.anchors_current == 12


async def test_an_unreachable_feed_retains_its_anchors_and_states_that_it_did() -> None:
    held = synced()
    ics, _ = adapter(FeedUnreachable(reason="the feed answered 503 Service Unavailable"))

    outcome, state = await ics.fetch(source(sync_state=held))

    assert outcome.reparsed is False
    assert state.last_error is not None
    assert "503" in state.last_error
    # A notice that says only what broke leaves the user unable to decide what to do next.
    assert RETAINED_NOTICE in state.last_error
    # The attempt moved; the success did not. The difference is what staleness is computed from.
    assert state.last_attempt_at == NOW
    assert state.last_success_at == EARLIER
    # Nothing the last success established became untrue because a poll failed.
    assert state.anchors_current == 12
    assert state.events_read == 30
    assert state.cursor == ETAG


@pytest.mark.parametrize(
    "answer",
    [
        FeedUnreachable(reason="the feed answered 404 Not Found"),
        FeedUnreachable(reason="the feed did not answer within 15s"),
        FeedUnchanged(cursor=ETAG),
        FeedBody(body="not an ics file at all", cursor=None),
        FeedBody(body="", cursor=None),
    ],
    ids=["4xx", "timeout", "unchanged", "not ics", "empty body"],
)
async def test_no_answer_raises_at_the_caller(answer: FeedAnswer) -> None:
    # A worker tick polling five feeds must not lose four of them because one publisher is
    # down or sent something that is not a calendar.
    ics, _ = adapter(answer)

    await ics.fetch(source(sync_state=synced()))


async def test_a_feed_that_genuinely_holds_no_events_is_told_apart_from_one_not_reparsed() -> None:
    # The distinction `reparsed` exists for. Both answers carry an empty event list, and only
    # one of them means the caller should remove the anchors it holds.
    read, _ = adapter(FeedBody(body=EMPTY_FEED, cursor=None))
    skipped, _ = adapter(FeedUnchanged(cursor=ETAG))

    empty, empty_state = await read.fetch(source(sync_state=synced()))
    unchanged, unchanged_state = await skipped.fetch(source(sync_state=synced()))

    assert empty.events == unchanged.events == ()
    assert empty.reparsed is True
    assert unchanged.reparsed is False
    # And the arithmetic follows: an empty feed contributes no anchors, an unchanged one keeps
    # the twelve it already had.
    assert empty_state.anchors_current == 0
    assert unchanged_state.anchors_current == 12


async def test_a_first_attempt_sends_no_conditional_validator() -> None:
    ics, fetcher = adapter(FeedBody(body=EMPTY_FEED, cursor=None))

    await ics.fetch(source())

    assert fetcher.sent == [None]
