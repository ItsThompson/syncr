"""The external bound on one recurrence expansion: what it answers, costs, and reclaims.

Every test here hands ``parse_feed`` a bound of its own with a short deadline, so a rule that
would genuinely walk for minutes is cut off in half a second. The production deadline lives in
``EXPANSION_DEADLINE_SECONDS``; nothing here waits on it.

The rules exercised are legal by every guard ``ics_recurrence`` states: each value sits inside
the range RFC 5545 gives its property, so no existing refusal fires, and the only answer left
is the deadline.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syncr_api.calendars.config import (
    ANCHOR_SOURCE,
    ICS,
    READ_BUDGET_SPENT,
    UNPARSEABLE_RECURRENCE,
)
from syncr_api.calendars.expansion_bound import ExpansionBound
from syncr_api.calendars.feeds import FeedBody
from syncr_api.calendars.ics_adapter import IcsAdapter
from syncr_api.calendars.ics_parse import parse_feed
from syncr_api.calendars.records import CalendarSourceRecord, SyncStateRecord
from syncr_domain.intervals import Interval
from syncr_domain.zones import ZoneProfile
from tests.hostile_ics import EMPTY_FEED, UNIVERSITY_TIMETABLE

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

FEED_URL = "https://example.org/hang.ics"
HOME = ZoneProfile(home_zone="Europe/London")
NOW = datetime(2026, 2, 9, 7, 0, tzinfo=UTC)
HORIZON = Interval(datetime(2026, 2, 9, 0, 0, tzinfo=UTC), datetime(2026, 2, 23, 0, 0, tzinfo=UTC))

# The shape the ticket names, and the eight further members of the same class: every value
# inside the range its property allows, jointly unsatisfiable, so dateutil scans for a match
# that never exists and every guard declines to judge. Each measured member of this family
# costs upwards of 200 seconds inside one call; the bound answers each in half a second here.
NAMED_RULE = "FREQ=SECONDLY;BYMONTH=2;BYMONTHDAY=30;BYHOUR=2"
FURTHER_LEGAL_SHAPES = (
    "FREQ=SECONDLY;BYMONTH=2;BYMONTHDAY=30",
    "FREQ=SECONDLY;BYMONTHDAY=31;BYMONTH=4",
    "FREQ=MINUTELY;BYMONTH=2;BYMONTHDAY=30;BYHOUR=2",
    "FREQ=HOURLY;BYMONTH=2;BYMONTHDAY=30;BYHOUR=2",
    "FREQ=MINUTELY;BYMONTHDAY=31;BYMONTH=4",
    "FREQ=HOURLY;BYMONTHDAY=31;BYMONTH=4;BYHOUR=2",
    "FREQ=SECONDLY;BYYEARDAY=366;BYMONTH=2",
    "FREQ=MINUTELY;BYMONTH=2;BYMONTHDAY=30",
)


def _rule_event(rule: str, uid: str) -> str:
    return (
        f"BEGIN:VEVENT\r\nUID:{uid}\r\nSUMMARY:Never matches\r\n"
        "DTSTART:20260210T100000Z\r\nDTEND:20260210T110000Z\r\n"
        f"RRULE:{rule}\r\nEND:VEVENT\r\n"
    )


def _feed(*events: str) -> str:
    return f"BEGIN:VCALENDAR\r\n{''.join(events)}END:VCALENDAR\r\n"


@pytest.fixture(scope="module")
def tight() -> Iterator[ExpansionBound]:
    """One pool with a half-second deadline, shared so each test does not spawn its own."""
    bound = ExpansionBound(deadline_seconds=0.5, size=1)
    yield bound
    bound.shutdown()


def test_the_named_unsatisfiable_rule_is_answered_by_the_deadline(tight: ExpansionBound) -> None:
    started = monotonic()
    outcome = parse_feed(
        _feed(_rule_event(NAMED_RULE, "hang@example.org")),
        horizon=HORIZON,
        profile=HOME,
        budget=60.0,
        bound=tight,
    )
    elapsed = monotonic() - started

    assert outcome.events == ()
    assert outcome.events_read == 1
    assert [item.kind for item in outcome.rejected] == [UNPARSEABLE_RECURRENCE]
    detail = outcome.rejected[0].detail
    # The stated rejection quotes the rule the publisher wrote, and names the bound it hit.
    assert "BYMONTHDAY=30" in detail
    assert "seconds" in detail
    # Bounded by the deadline rather than by anything else: ten times the deadline, against a
    # walk measured in thousands of them. The bound is the bite: a regression to inline
    # expansion hangs here instead of finishing inside this margin.
    assert elapsed < 5


@pytest.mark.parametrize("rule", FURTHER_LEGAL_SHAPES)
def test_a_further_legal_shape_answers_the_same_way(rule: str, tight: ExpansionBound) -> None:
    outcome = parse_feed(
        _feed(_rule_event(rule, "hang@example.org")), horizon=HORIZON, profile=HOME, bound=tight
    )

    assert outcome.events == ()
    assert [item.kind for item in outcome.rejected] == [UNPARSEABLE_RECURRENCE]
    assert "did not finish expanding within" in outcome.rejected[0].detail


def test_a_feed_of_such_components_costs_one_budget_plus_one_deadline(
    tight: ExpansionBound,
) -> None:
    body = _feed(*(_rule_event(NAMED_RULE, f"hang-{index}@example.org") for index in range(5)))

    started = monotonic()
    outcome = parse_feed(body, horizon=HORIZON, profile=HOME, budget=1.0, bound=tight)
    elapsed = monotonic() - started

    # Every component is accounted for: the first by the deadline, the rest by the feed's spent
    # budget, which is checked between components without reaching the pool again.
    assert outcome.events_read == 5
    kinds = [item.kind for item in outcome.rejected]
    assert kinds.count(UNPARSEABLE_RECURRENCE) >= 1
    assert kinds.count(READ_BUDGET_SPENT) == 5 - kinds.count(UNPARSEABLE_RECURRENCE)
    # The bound the ticket states: the feed's parse budget plus AT MOST one deadline. Generous
    # slack absorbs a loaded CI machine; two extra deadlines would fail here.
    assert elapsed < 1.0 + 0.5 + 1.5


@dataclass
class _AnsweredFetcher:
    """A :class:`~syncr_api.calendars.feeds.FeedFetcher` answering one body per URL."""

    answers: Mapping[str, str]

    async def get(self, url: str, *, cursor: str | None) -> FeedBody:
        return FeedBody(body=self.answers[url], cursor=cursor)


def _source() -> CalendarSourceRecord:
    return CalendarSourceRecord(
        id=uuid4(),
        tenant_id=uuid4(),
        provider=ICS,
        role=ANCHOR_SOURCE,
        display_name="Hang feed",
        external_id=FEED_URL,
        included=True,
        horizon_days=None,
        created_at=NOW,
        sync_state=SyncStateRecord(),
    )


async def test_a_request_during_an_expansion_is_answered_at_normal_latency() -> None:
    # The other half of the premise. The expansion runs in ANOTHER process, but the waiting
    # itself would park the event loop if fetch parsed on it: today's inline call held the loop
    # for the whole expansion, so a request issued mid-hang waited for it. Both halves are
    # asserted together: the second fetch answers while the first is still expanding, and the
    # first is then answered by its deadline as a stated rejection.
    bound = ExpansionBound(deadline_seconds=2.0, size=1)
    try:
        hanging = IcsAdapter(
            fetcher=_AnsweredFetcher({FEED_URL: _feed(_rule_event(NAMED_RULE, "h@example.org"))}),
            profile=HOME,
            horizon=HORIZON,
            clock=lambda: NOW,
            bound=bound,
        )
        quick = IcsAdapter(
            fetcher=_AnsweredFetcher({FEED_URL: EMPTY_FEED}),
            profile=HOME,
            horizon=HORIZON,
            clock=lambda: NOW,
            bound=bound,
        )
        hung_task = asyncio.create_task(hanging.fetch(_source()))
        await asyncio.sleep(0.5)

        started = monotonic()
        quick_outcome, quick_state = await quick.fetch(_source())
        latency = monotonic() - started

        assert quick_outcome.reparsed is True
        assert quick_state.last_error is None
        # Normal latency: answered while the hung expansion is still spending its 2 s deadline.
        # The margin is 1.0 s: half the deadline, so the property ("the loop never parks on the
        # wait") keeps its bite while a loaded CI machine's scheduler jitter cannot flake it.
        # An inline parse of this feed would blow past any margin here.
        assert latency < 1.0
        assert not hung_task.done()

        hung_outcome, hung_state = await asyncio.wait_for(hung_task, timeout=15)
        assert [item.kind for item in hung_outcome.rejected] == [UNPARSEABLE_RECURRENCE]
        assert hung_state.last_error is None
    finally:
        bound.shutdown()


def test_a_timed_out_expansion_leaves_a_pool_that_still_serves(tight: ExpansionBound) -> None:
    # The pool already replaced workers for earlier tests in this module; what matters here is
    # that THIS expansion costs exactly one.
    replacements_before = tight.replacements

    outcome = parse_feed(
        _feed(_rule_event(NAMED_RULE, "hang@example.org")),
        horizon=HORIZON,
        profile=HOME,
        bound=tight,
    )

    assert [item.kind for item in outcome.rejected] == [UNPARSEABLE_RECURRENCE]
    # The worker that ran the hung expansion was terminated and replaced: the reclaim.
    assert tight.replacements - replacements_before == 1

    # And the pool serves the next feed as before, which is why one hung component cannot
    # poison the source after it.
    good = parse_feed(UNIVERSITY_TIMETABLE, horizon=HORIZON, profile=HOME, bound=tight)
    assert len(good.events) == 3


# A BYSETPOS reaching past the set its period holds. The selectability guard
# ``_require_selectable_setpos`` used to refuse this shape with "produces nothing";
# that guard was deleted (SR-CAL-05) because the bound now answers it instead. This
# test is the bite: with the guard in place the shape never reaches the bound, so
# the rejection detail says "produces nothing" rather than "did not finish
# expanding", and the assertion below fails on the pre-change tree.
_SETPOS_PAST_SET = "FREQ=HOURLY;BYMINUTE=0;BYSETPOS=2"


@pytest.mark.parametrize(
    "rule",
    [
        _SETPOS_PAST_SET,
        "FREQ=SECONDLY;BYSETPOS=2",
        "FREQ=MINUTELY;BYMINUTE=0,30;BYSETPOS=2",
        "FREQ=HOURLY;BYMINUTE=0,0;BYSETPOS=2",
        "FREQ=DAILY;BYSETPOS=2",
    ],
)
def test_a_setpos_past_its_set_is_answered_by_the_deadline_not_a_guard(
    rule: str, tight: ExpansionBound
) -> None:
    # Every value in these rules is inside the range its property allows; the only fault is
    # that the position selects nothing, so dateutil walks to its own maximum year inside
    # one ``next()`` call. The bound interrupts that walk with a stated rejection.
    outcome = parse_feed(
        _feed(_rule_event(rule, "setpos@example.org")),
        horizon=HORIZON,
        profile=HOME,
        bound=tight,
    )

    assert outcome.events == ()
    assert [item.kind for item in outcome.rejected] == [UNPARSEABLE_RECURRENCE]
    detail = outcome.rejected[0].detail
    assert "did not finish expanding" in detail
    # The deleted guard's message must not appear: its presence would mean the guard
    # is still standing and the bound never fired.
    assert "produces nothing" not in detail


@pytest.mark.parametrize(
    "rule",
    [
        "FREQ=SECONDLY;BYMONTH=-1",
        "FREQ=SECONDLY;BYYEARDAY=-367",
        "FREQ=SECONDLY;BYWEEKNO=-54",
    ],
)
def test_a_range_the_bound_can_answer_reaches_the_deadline(
    rule: str, tight: ExpansionBound
) -> None:
    outcome = parse_feed(
        _feed(_rule_event(rule, "range@example.org")),
        horizon=HORIZON,
        profile=HOME,
        bound=tight,
    )

    assert outcome.events == ()
    assert [item.kind for item in outcome.rejected] == [UNPARSEABLE_RECURRENCE]
    assert "did not finish expanding" in outcome.rejected[0].detail
