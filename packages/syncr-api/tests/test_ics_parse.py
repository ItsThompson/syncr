"""Parsing the ``hostile_ics`` corpus: every row of section 06's ICS ingest table.

Fixture-driven rather than synthetic, per the testing strategy. Each body in
:mod:`tests.hostile_ics` carries one publisher's real defects, and every expected instant and
count here is written out by hand: reading them back off the fixture would assert the fixture
rather than the adapter.

The horizon is a fortnight from Monday 2026-02-09, which is the span the write target would
project, so what is asserted is what the solver would actually be handed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from syncr_api.calendars.config import (
    MALFORMED_VALUE,
    MISSING_DURATION,
    UNKNOWN_ZONE,
    UNPARSEABLE_RECURRENCE,
)
from syncr_api.calendars.ics_parse import parse_feed
from syncr_domain.intervals import Interval
from syncr_domain.zones import TravelOverride, ZoneProfile
from tests.hostile_ics import (
    ALL_FEEDS,
    ASSESSMENTS_FEED,
    EMPTY_FEED,
    HOLIDAY_FEED,
    PUBLISHED_OUTLOOK,
    RUNAWAY_RECURRENCE,
    UNIVERSITY_TIMETABLE,
)

if TYPE_CHECKING:
    from syncr_api.calendars.events import RawEvent

LONDON = "Europe/London"
TOKYO = "Asia/Tokyo"
HOME = ZoneProfile(home_zone=LONDON)

HORIZON = Interval(datetime(2026, 2, 9, 0, 0, tzinfo=UTC), datetime(2026, 2, 23, 0, 0, tzinfo=UTC))


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def parsed(body: str, *, profile: ZoneProfile = HOME) -> tuple[RawEvent, ...]:
    return parse_feed(body, horizon=HORIZON, profile=profile).events


def titled(events: tuple[RawEvent, ...], fragment: str) -> list[RawEvent]:
    return [event for event in events if fragment in event.title]


def spans(events: tuple[RawEvent, ...]) -> list[tuple[datetime, datetime]]:
    return sorted((event.interval.start, event.interval.end) for event in events)


# --------------------------------------------------------------------------------
# Recurrence, exclusions, and overrides
# --------------------------------------------------------------------------------


def test_a_weekly_rule_expands_across_the_horizon_honouring_its_exclusion() -> None:
    # Mondays 9 and 16 February fall in the horizon. The 16th is reading week and carries an
    # EXDATE, so one lecture survives, and the RECURRENCE-ID override below moved it.
    lectures = titled(parsed(UNIVERSITY_TIMETABLE), "Advanced Computer Architecture")

    assert spans(tuple(lectures)) == [(utc(2026, 2, 9, 10, 0), utc(2026, 2, 9, 12, 0))]


def test_a_recurrence_id_override_replaces_the_occurrence_rather_than_adding_one() -> None:
    # The override moves the 9 February lecture from 09:00 to 10:00 and changes its room. A
    # reading that treated the override as its own event would report the lecture twice.
    lectures = titled(parsed(UNIVERSITY_TIMETABLE), "Advanced Computer Architecture")

    assert len(lectures) == 1
    assert lectures[0].location == "Block BC, room BC-01-014"
    assert lectures[0].interval.start == utc(2026, 2, 9, 10, 0)
    # It keeps the identity of the occurrence it replaced, so reconciliation matches it to
    # the anchor the unmoved occurrence created on an earlier sync.
    assert lectures[0].uid.endswith("#20260209T090000")
    assert lectures[0].series_uid == "celcat-CS3009-LEC-01@example.ac.uk"


def test_a_folded_summary_arrives_whole_and_an_escaped_comma_is_a_comma() -> None:
    # Asserted on an occurrence the RECURRENCE-ID override does NOT replace, because the
    # override's own SUMMARY is unfolded: reading the overridden week would prove nothing
    # about unfolding at all.
    later = Interval(utc(2026, 2, 23, 0, 0), utc(2026, 3, 2, 0, 0))

    lectures = titled(
        parse_feed(UNIVERSITY_TIMETABLE, horizon=later, profile=HOME).events, "CS3009"
    )

    assert lectures[0].title == "CS3009 Advanced Computer Architecture - Lecture (Group A)"
    assert lectures[0].location == "Block MD, room MD108"


def test_a_count_bounded_rule_stops_at_its_count_within_the_horizon() -> None:
    # COUNT=6 from Tuesday 10 February: two of them (10 and 17 February) fall in a fortnight.
    labs = titled(parsed(UNIVERSITY_TIMETABLE), "Lab")

    assert spans(tuple(labs)) == [
        (utc(2026, 2, 10, 14, 0), utc(2026, 2, 10, 15, 30)),
        (utc(2026, 2, 17, 14, 0), utc(2026, 2, 17, 15, 30)),
    ]


def test_a_duration_property_sets_the_span_where_there_is_no_dtend() -> None:
    labs = titled(parsed(UNIVERSITY_TIMETABLE), "Lab")

    assert all(event.interval.total_minutes() == 90 for event in labs)


def test_an_rdate_adds_an_occurrence_the_rule_does_not_produce() -> None:
    # The half-term event has no RRULE at all: its only recurrence is one RDATE, outside the
    # horizon, so the horizon sees the series' own occurrence and nothing else.
    half_term = titled(parsed(HOLIDAY_FEED), "half term")

    assert spans(tuple(half_term)) == [(utc(2026, 2, 16, 0, 0), utc(2026, 2, 21, 0, 0))]


def test_a_yearly_rule_from_years_ago_reaches_the_horizon() -> None:
    # DTSTART is 2020. Nothing rebases the rule, so the expansion walks to the horizon and
    # the occurrence that lands in it is the 2026 one.
    valentines = titled(parsed(HOLIDAY_FEED), "Valentine")

    assert spans(tuple(valentines)) == [(utc(2026, 2, 14, 0, 0), utc(2026, 2, 15, 0, 0))]


def test_an_occurrence_that_began_before_the_horizon_and_runs_into_it_is_kept() -> None:
    # The half-term span starts on 16 February. Narrow the horizon to the 18th onwards and the
    # occurrence is still occupancy the solver has to respect.
    late = Interval(utc(2026, 2, 18, 0, 0), utc(2026, 2, 23, 0, 0))

    found = parse_feed(HOLIDAY_FEED, horizon=late, profile=HOME).events

    assert [event.interval.start for event in titled(found, "half term")] == [
        utc(2026, 2, 16, 0, 0)
    ]


# --------------------------------------------------------------------------------
# Whole days
# --------------------------------------------------------------------------------


def test_a_value_date_event_with_no_dtend_occupies_one_whole_local_day() -> None:
    coursework = titled(parsed(ASSESSMENTS_FEED), "Coursework 1")

    assert spans(tuple(coursework)) == [(utc(2026, 2, 13, 0, 0), utc(2026, 2, 14, 0, 0))]
    assert coursework[0].all_day is True


def test_a_value_date_range_covers_every_day_up_to_its_exclusive_end() -> None:
    # 17 to 20 February exclusive is three days, which is what the standard means and what a
    # reading that counted four would get wrong.
    window = titled(parsed(ASSESSMENTS_FEED), "exam window")

    assert spans(tuple(window)) == [(utc(2026, 2, 17, 0, 0), utc(2026, 2, 20, 0, 0))]


def test_a_whole_day_is_taken_in_the_zone_active_on_that_date() -> None:
    # A travel override for 13 February puts the user in Tokyo, so the coursework day is the
    # Tokyo day: nine hours earlier, and still 24 hours long.
    travelling = ZoneProfile(
        home_zone=LONDON,
        travel_overrides=(
            TravelOverride(
                start_date=utc(2026, 2, 13).date(), end_date=utc(2026, 2, 14).date(), zone=TOKYO
            ),
        ),
    )

    coursework = titled(parsed(ASSESSMENTS_FEED, profile=travelling), "Coursework 1")

    assert coursework[0].interval.start == utc(2026, 2, 12, 15, 0)
    assert coursework[0].interval.total_minutes() == 24 * 60


# --------------------------------------------------------------------------------
# Zones
# --------------------------------------------------------------------------------


def test_a_windows_zone_name_places_the_event_rather_than_rejecting_it() -> None:
    standups = titled(parsed(PUBLISHED_OUTLOOK), "standup")

    # February in London is UTC+0, so 08:15 local is 08:15Z.
    assert (utc(2026, 2, 9, 8, 15), utc(2026, 2, 9, 8, 30)) in spans(tuple(standups))


def test_an_unmapped_zone_rejects_the_event_and_reports_the_zone_and_the_line() -> None:
    outcome = parse_feed(PUBLISHED_OUTLOOK, horizon=HORIZON, profile=HOME)

    unknown = [rejected for rejected in outcome.rejected if rejected.kind == UNKNOWN_ZONE]
    assert len(unknown) == 1
    assert "Cheshire Standard Time" in unknown[0].detail
    assert unknown[0].component == "VEVENT"
    # The line the component began on in the feed as delivered, so a publisher can find it.
    assert unknown[0].line == 25
    assert titled(outcome.events, "offsite") == []


def test_a_floating_whole_day_needs_no_tzid_at_all() -> None:
    # The holiday feed carries no zone anywhere. Read in the active zone, it is a London day.
    assert titled(parsed(HOLIDAY_FEED), "Valentine")[0].interval.start == utc(2026, 2, 14, 0, 0)


# --------------------------------------------------------------------------------
# Rejections, duplicates, and cancellations
# --------------------------------------------------------------------------------


def test_an_event_with_neither_dtend_nor_duration_is_rejected_with_its_line() -> None:
    outcome = parse_feed(ASSESSMENTS_FEED, horizon=HORIZON, profile=HOME)

    rejected = [item for item in outcome.rejected if item.kind == MISSING_DURATION]
    assert len(rejected) == 1
    assert rejected[0].line == 15
    assert "DTEND" in rejected[0].detail
    assert "DURATION" in rejected[0].detail
    # And the two events that DID parse are still returned: a feed that half-works reads as
    # neither fully working nor fully broken.
    assert len(outcome.events) == 2
    assert outcome.events_read == 3


def test_a_duplicate_uid_resolves_to_the_later_sequence_and_counts_the_discard() -> None:
    outcome = parse_feed(PUBLISHED_OUTLOOK, horizon=HORIZON, profile=HOME)

    reviews = titled(outcome.events, "Sprint review")
    assert len(reviews) == 1
    assert reviews[0].sequence == 3
    # SEQUENCE 3 moved the meeting from 13:00 to 15:00. Keeping the first would have kept a
    # superseded revision and placed the block two hours early.
    assert reviews[0].interval.start == utc(2026, 2, 12, 15, 0)
    assert outcome.duplicates_discarded == 1


def test_a_cancelled_component_produces_no_event_and_is_counted() -> None:
    outcome = parse_feed(PUBLISHED_OUTLOOK, horizon=HORIZON, profile=HOME)

    assert titled(outcome.events, "budget sign-off") == []
    assert outcome.cancelled_discarded == 1


def test_a_runaway_recurrence_is_rejected_rather_than_expanded() -> None:
    outcome = parse_feed(RUNAWAY_RECURRENCE, horizon=HORIZON, profile=HOME)

    assert outcome.events == ()
    assert [item.kind for item in outcome.rejected] == [UNPARSEABLE_RECURRENCE]
    assert "will not read" in outcome.rejected[0].detail


def test_a_valid_feed_with_no_events_is_a_success_rather_than_a_failure() -> None:
    outcome = parse_feed(EMPTY_FEED, horizon=HORIZON, profile=HOME)

    assert outcome.events == ()
    assert outcome.rejected == ()
    assert outcome.events_read == 0


def test_every_component_of_every_feed_is_accounted_for() -> None:
    # The counts are what the panel reports, so they have to close: a component that appeared
    # in none of the four buckets would be occupancy that vanished with no explanation.
    for label, body in ALL_FEEDS.items():
        outcome = parse_feed(body, horizon=HORIZON, profile=HOME)
        masters = {event.series_uid or event.uid for event in outcome.events}
        accounted = (
            len(masters)
            + len(outcome.rejected)
            + outcome.duplicates_discarded
            + outcome.cancelled_discarded
        )
        assert accounted == outcome.events_read - _overrides_in(body), label


def _overrides_in(body: str) -> int:
    """How many components of ``body`` replace an occurrence rather than declaring a series.

    An override is read and applied, so it is neither kept as an event of its own nor rejected,
    nor discarded. Counting it here is what keeps the arithmetic above a real check rather than
    one loosened until it passed.
    """
    return body.count("RECURRENCE-ID")


@pytest.mark.parametrize("label", sorted(ALL_FEEDS))
def test_no_feed_in_the_corpus_raises(label: str) -> None:
    # The adapter's whole contract: hostility is absorbed and returned, never raised at a
    # caller. A body that raised would take a worker tick down with it.
    parse_feed(ALL_FEEDS[label], horizon=HORIZON, profile=HOME)


def test_a_component_with_no_uid_is_rejected_rather_than_placed() -> None:
    # A UID is the reconciliation key. Without one, the next sync could not match the anchor
    # it created, so every sync would delete and recreate it.
    body = "BEGIN:VEVENT\r\nDTSTART:20260209T090000Z\r\nDTEND:20260209T100000Z\r\nEND:VEVENT\r\n"

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert outcome.events == ()
    assert [item.kind for item in outcome.rejected] == [MALFORMED_VALUE]
    assert "UID" in outcome.rejected[0].detail


def test_an_event_ending_before_it_starts_is_rejected_rather_than_crashing() -> None:
    # A real export defect. Left to reach interval construction it would raise, taking the
    # rest of the feed with it.
    body = (
        "BEGIN:VEVENT\r\nUID:reversed@example.org\r\n"
        "DTSTART:20260209T100000Z\r\nDTEND:20260209T090000Z\r\nEND:VEVENT\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert outcome.events == ()
    assert [item.kind for item in outcome.rejected] == [MALFORMED_VALUE]
