"""Which weeks a zone change invalidates, as literal dates and literal ISO weeks.

Every case here is a real date with a real weekday, because the two rules being tested
are both about weekday boundaries: a week's span ends at the FOLLOWING Monday's local
midnight, and a past week keeps the span it was computed with.

``2026-08-02`` is a Sunday and the last day of ``2026-W31``; ``2026-08-03`` is the Monday
that opens ``2026-W32``. That pair is what makes the "one day before" rule visible, so it
recurs below.
"""

from __future__ import annotations

import io
import json
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, cast

import pytest

from syncr_api.user_settings.solve_inputs import (
    TrackedWeekInputVersions,
    WeekRange,
    weeks_covering,
    weeks_from,
)
from syncr_common.logging import configure_logging
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syncr_api.plans.versions import WeekInputVersionRepository

SUNDAY = date(2026, 8, 2)  # the last day of 2026-W31
MONDAY = date(2026, 8, 3)  # the first day of 2026-W32
# The instant every bump below is written with. Aware, because the counter stores it.
NOW = datetime(2026, 8, 2, 9, 0, tzinfo=UTC)
WEEK_31 = IsoWeek.parse("2026-W31")
WEEK_32 = IsoWeek.parse("2026-W32")
WEEK_33 = IsoWeek.parse("2026-W33")


def test_a_home_zone_change_invalidates_the_current_week_and_every_week_after_it() -> None:
    affected = weeks_from(SUNDAY)

    assert affected == WeekRange(first=WEEK_31, last=None)
    assert affected.covers(WEEK_31)
    assert affected.covers(IsoWeek.parse("2030-W01"))


def test_a_home_zone_change_never_reaches_a_past_week() -> None:
    # The whole reason the floor exists. A past week's span is stored on an approved
    # revision, which is immutable, so re-deriving it would rewrite history.
    affected = weeks_from(SUNDAY)

    assert not affected.covers(IsoWeek.parse("2026-W30"))
    assert not affected.covers(IsoWeek.parse("2025-W31"))


@pytest.mark.parametrize(
    ("start_date", "end_date", "expected"),
    [
        # Wholly inside one week.
        (date(2026, 8, 4), date(2026, 8, 6), WeekRange(WEEK_32, WEEK_32)),
        # Spanning a week boundary.
        (date(2026, 8, 6), date(2026, 8, 12), WeekRange(WEEK_32, WEEK_33)),
        # Beginning on a MONDAY: the week before it is affected too, because that week's
        # span ends at this Monday's local midnight, which the new zone now names.
        (MONDAY, date(2026, 8, 5), WeekRange(WEEK_31, WEEK_32)),
        # Ending on a Sunday: the week after is NOT affected. Its own Monday and every day
        # in it fall outside the range.
        (date(2026, 8, 4), date(2026, 8, 9), WeekRange(WEEK_32, WEEK_32)),
        # One day long, on a Monday.
        (date(2026, 8, 10), date(2026, 8, 10), WeekRange(WEEK_32, WEEK_33)),
    ],
)
def test_a_travel_override_invalidates_the_weeks_its_range_can_reach(
    start_date: date, end_date: date, expected: WeekRange
) -> None:
    assert weeks_covering(start_date, end_date, today=SUNDAY) == expected


def test_a_range_wholly_in_the_past_invalidates_nothing() -> None:
    # Not an empty range: nothing at all, so the caller does not tell the counter to bump
    # a range it would have to interpret as empty.
    assert weeks_covering(date(2026, 7, 20), date(2026, 7, 24), today=SUNDAY) is None


def test_a_range_reaching_into_the_current_week_starts_at_the_current_week() -> None:
    # A trip that began last week and is still running: the days already spent keep the
    # span they were computed with, and this week onwards re-derives.
    affected = weeks_covering(date(2026, 7, 29), date(2026, 8, 5), today=SUNDAY)

    assert affected == WeekRange(first=WEEK_31, last=WEEK_32)


def test_a_range_ending_in_the_current_week_still_invalidates_it() -> None:
    # The current week is partly in the past, and its span reads the zone active on its
    # own Monday, so an override covering that Monday changes it.
    affected = weeks_covering(date(2026, 7, 28), date(2026, 7, 30), today=SUNDAY)

    assert affected == WeekRange(first=WEEK_31, last=WEEK_31)


def test_a_range_wholly_in_the_future_keeps_both_of_its_own_bounds() -> None:
    affected = weeks_covering(date(2027, 1, 4), date(2027, 1, 8), today=SUNDAY)

    assert affected == WeekRange(first=IsoWeek.parse("2026-W53"), last=IsoWeek.parse("2027-W01"))


def test_a_week_range_refuses_to_end_before_it_begins() -> None:
    # The type is what a bump reads, so an inverted range would be a silent no-op UPDATE
    # rather than an error.
    with pytest.raises(ValueError, match="first <= last"):
        WeekRange(first=WEEK_33, last=WEEK_31)


def test_an_unbounded_range_covers_a_week_a_bounded_one_does_not() -> None:
    # The control for `covers`: without it, a rule that always answered True would pass
    # every assertion above.
    bounded = WeekRange(first=WEEK_31, last=WEEK_32)

    assert not bounded.covers(WEEK_33)
    assert WeekRange(first=WEEK_31, last=None).covers(WEEK_33)


@pytest.fixture
def log_stream() -> Iterator[io.StringIO]:
    """Render log lines to a captured stream, then hand the configuration back.

    Stays in ``test``, so the strict dotted-event-name check is on and the event name
    below is validated rather than merely recorded.
    """
    stream = io.StringIO()
    configure_logging(environment="test", log_level="info", stream=stream)
    yield stream
    configure_logging(environment="test", log_level="info")


class FakeVersionRows:
    """Plan storage's counter over a dict: which weeks have rows, and their versions."""

    def __init__(self, versions: dict[IsoWeek, int]) -> None:
        self.versions = dict(versions)
        self.bumped: list[IsoWeek] = []

    async def tracked_weeks(
        self, first: IsoWeek, last: IsoWeek | None = None
    ) -> tuple[IsoWeek, ...]:
        return tuple(
            week
            for week in sorted(self.versions)
            if first <= week and (last is None or week <= last)
        )

    async def bump(self, iso_week: IsoWeek, *, at: datetime) -> int:
        assert at.tzinfo is not None, "the counter is written with an aware instant"
        self.bumped.append(iso_week)
        self.versions[iso_week] = self.versions.get(iso_week, 0) + 1
        return self.versions[iso_week]


def tracked(versions: dict[IsoWeek, int]) -> TrackedWeekInputVersions:
    return TrackedWeekInputVersions(
        cast("WeekInputVersionRepository", FakeVersionRows(versions)), clock=lambda: NOW
    )


async def test_only_the_weeks_that_have_a_version_row_are_bumped() -> None:
    # A week with no row has no plan and no running solve, and the write guard already
    # treats a missing row as a mismatch, so creating one here would buy nothing.
    rows = FakeVersionRows({WEEK_31: 4, WEEK_33: 2})
    counter = TrackedWeekInputVersions(cast("WeekInputVersionRepository", rows), clock=lambda: NOW)

    await counter.bump(WeekRange(first=WEEK_31, last=None))

    assert rows.bumped == [WEEK_31, WEEK_33]
    assert rows.versions == {WEEK_31: 5, WEEK_33: 3}


async def test_a_bounded_range_leaves_a_later_tracked_week_alone() -> None:
    rows = FakeVersionRows({WEEK_31: 1, WEEK_32: 1, WEEK_33: 1})
    counter = TrackedWeekInputVersions(cast("WeekInputVersionRepository", rows), clock=lambda: NOW)

    await counter.bump(WeekRange(first=WEEK_31, last=WEEK_32))

    assert rows.bumped == [WEEK_31, WEEK_32]
    assert rows.versions[WEEK_33] == 1


async def test_the_bump_reports_the_range_and_how_many_weeks_it_reached(
    log_stream: io.StringIO,
) -> None:
    await tracked({WEEK_31: 1}).bump(WeekRange(first=WEEK_31, last=WEEK_33))

    lines = [json.loads(line) for line in log_stream.getvalue().splitlines() if line]
    assert [line["event"] for line in lines] == ["user_settings.input_version.bumped"]
    assert lines[0]["first_week"] == "2026-W31"
    assert lines[0]["last_week"] == "2026-W33"
    assert lines[0]["weeks_bumped"] == 1


async def test_an_unbounded_bump_reports_no_last_week_rather_than_a_week(
    log_stream: io.StringIO,
) -> None:
    await tracked({}).bump(WeekRange(first=WEEK_31, last=None))

    line = json.loads(log_stream.getvalue().splitlines()[0])
    assert line["last_week"] is None
    assert line["weeks_bumped"] == 0
