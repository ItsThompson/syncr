"""Parsing the ``hostile_ics`` corpus: every row of the ICS ingest table.

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
    MAX_EVENT_DAYS,
    MAX_EVENTS_PER_FEED,
    MISSING_DURATION,
    UNKNOWN_ZONE,
    UNPARSEABLE_RECURRENCE,
)
from syncr_api.calendars.ics_lines import MAX_COMPONENT_DEPTH, VEVENT
from syncr_api.calendars.ics_parse import parse_feed
from syncr_domain.intervals import Interval
from syncr_domain.zones import TravelOverride, ZoneProfile
from tests.hostile_ics import (
    ALL_FEEDS,
    ASSESSMENTS_FEED,
    CANCELLED_DUPLICATE_MASTER,
    CANCELLED_DUPLICATE_MASTER_REVERSED,
    CANCELLED_ORPHAN,
    DUPLICATE_ORPHANS,
    DUPLICATE_REPLACEMENTS,
    DUPLICATE_REPLACEMENTS_REVERSED,
    DUPLICATE_TOMBSTONES,
    EMPTY_FEED,
    HOLIDAY_FEED,
    MOVED_AND_CANCELLED,
    OVERRUNNING_RECURRENCE,
    PUBLISHED_OUTLOOK,
    RUNAWAY_RECURRENCE,
    UNIVERSITY_TIMETABLE,
    nested_feed,
)

if TYPE_CHECKING:
    from syncr_api.calendars.events import FetchOutcome, RawEvent, RejectedComponent

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
    # Three cancellations in this body, each a different form: the cancelled master above, the
    # cancelled series further down, and that series' surviving override, which the cancellation
    # takes with it. The cancelled OCCURRENCE of the live standup is an applied override rather
    # than a discard, so it is not counted here.
    assert outcome.cancelled_discarded == 3


def test_a_cancelled_occurrence_is_removed_from_its_live_series() -> None:
    # How Exchange and most CalDAV servers express a deleted occurrence: a RECURRENCE-ID naming it,
    # on a component whose STATUS is CANCELLED, while the master stays live. Read as the absence of
    # an override, the master's rule places it anyway and blanks an hour the user actually has.
    standups = titled(parsed(PUBLISHED_OUTLOOK), "standup")

    cancelled = utc(2026, 2, 16).date()
    assert [event for event in standups if event.interval.start.date() == cancelled] == []
    # The rest of the series is untouched: a tombstone removes one occurrence, not the rule.
    assert utc(2026, 2, 9).date() in {event.interval.start.date() for event in standups}


def test_a_cancelled_occurrence_is_not_also_counted_as_a_discard() -> None:
    # The counting rule the arithmetic depends on. A tombstone is an override, and an override is
    # already accounted for by its role, so counting it as a cancellation too leaves the totals
    # short and the panel reporting a component that went nowhere.
    outcome = parse_feed(PUBLISHED_OUTLOOK, horizon=HORIZON, profile=HOME)

    assert outcome.cancelled_discarded == 3
    assert outcome.events_read == 8


def test_a_runaway_recurrence_is_rejected_rather_than_expanded() -> None:
    outcome = parse_feed(RUNAWAY_RECURRENCE, horizon=HORIZON, profile=HOME)

    assert outcome.events == ()
    assert [item.kind for item in outcome.rejected] == [UNPARSEABLE_RECURRENCE]
    assert "will not read" in outcome.rejected[0].detail


@pytest.mark.parametrize(
    "interval",
    ["0", "00", "-1", "-999999999", "1.5", ""],
    ids=["zero", "padded zero", "negative", "a large negative", "fractional", "empty"],
)
def test_an_interval_that_is_not_a_positive_number_is_refused_by_name(interval: str) -> None:
    # An exporter's sign slip, not a hostile body. Two different faults sit behind this one guard,
    # and neither is answered by anything downstream:
    #
    # A NEGATIVE interval is accepted when the rule is built and raises during ITERATION, inside
    # dateutil, where `ValueError` is neither a rejection nor unrepresentable, so it escaped the
    # adapter with no sync state written.
    #
    # A ZERO interval never terminates. dateutil advances by the interval, so the rule never reaches
    # a new value, and a bound counting the occurrences a rule YIELDS can never fire. That holds a
    # worker tick and its transaction open rather than aborting them, which is worse than a raise.
    body = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:iv@example.org\r\n"
        "DTSTART:20260210T100000Z\r\nDTEND:20260210T110000Z\r\n"
        f"RRULE:FREQ=DAILY;INTERVAL={interval}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert outcome.events == ()
    assert [item.kind for item in outcome.rejected] == [UNPARSEABLE_RECURRENCE]
    assert "positive number of periods" in outcome.rejected[0].detail


@pytest.mark.parametrize(
    "rule",
    ["FREQ=MONTHLY;BYDAY=8MO", "FREQ=MONTHLY;BYDAY=99MO", "FREQ=YEARLY;BYDAY=99MO"],
)
def test_a_byday_ordinal_past_its_period_is_a_rejection_rather_than_a_fault(rule: str) -> None:
    # dateutil indexes its own weekday mask with the publisher's ordinal, so one past the weeks a
    # period holds walks off the end and raises IndexError. That is not a value error, so a caught
    # set of dateutil's VALUE faults did not cover it and it escaped the adapter with no state.
    # RFC 5545 allows +1..+5 there, so 8MO is one index slip in an exporter.
    body = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:bd@example.org\r\n"
        "DTSTART:20260210T100000Z\r\nDTEND:20260210T110000Z\r\n"
        f"RRULE:{rule}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert outcome.events == ()
    assert [item.kind for item in outcome.rejected] == [UNPARSEABLE_RECURRENCE]


@pytest.mark.parametrize(
    ("rule", "refused"),
    [
        ("FREQ=HOURLY;BYMINUTE=0;BYSETPOS=2", True),
        ("FREQ=HOURLY;BYSETPOS=2", True),
        ("FREQ=SECONDLY;BYSETPOS=2", True),
        ("FREQ=HOURLY;BYMINUTE=0,30;BYSETPOS=3", True),
        ("FREQ=HOURLY;BYMINUTE=0,30;BYSETPOS=2", False),
        ("FREQ=HOURLY;BYSETPOS=1", False),
    ],
)
def test_a_setpos_is_refused_only_when_its_period_cannot_hold_it(rule: str, refused: bool) -> None:
    # BYSETPOS picks the Nth member of each period's set. On a sub-daily frequency that set is built
    # only from BYMINUTE and BYSECOND, so a position past it selects nothing, the rule yields
    # nothing, and dateutil walks to its own maximum year INSIDE ONE next() call: measured at sixty
    # seconds for one component, with the worker tick held open. Neither a step bound nor an UNTIL
    # can see that, because dateutil compares against UNTIL only when a period yields.
    #
    # Compared against the set SIZE rather than refused as a shape, so the fourth case below still
    # expands: selecting the second of two is a rule dateutil answers in milliseconds.
    body = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:sp@example.org\r\n"
        "DTSTART:20260210T100000Z\r\nDTEND:20260210T103000Z\r\n"
        f"RRULE:{rule}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    if refused:
        assert [item.kind for item in outcome.rejected] == [UNPARSEABLE_RECURRENCE]
        assert "produces nothing" in outcome.rejected[0].detail
    else:
        assert outcome.rejected == ()
        assert outcome.events != ()


@pytest.mark.parametrize("interval", ["1", "2", "02", "0002"])
def test_a_positive_interval_is_expanded_however_it_is_written(interval: str) -> None:
    # The accepting side, including the padded forms RFC 5545's digit grammar permits, so the guard
    # is shown to refuse a property rather than a spelling.
    body = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:iv@example.org\r\n"
        "DTSTART:20260210T100000Z\r\nDTEND:20260210T110000Z\r\n"
        f"RRULE:FREQ=DAILY;INTERVAL={interval}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert outcome.rejected == ()
    assert len(outcome.events) > 1


def test_a_component_overrunning_the_per_feed_bound_is_refused_whole_and_says_so() -> None:
    # A FREQ=MINUTELY rule stays inside the per-series step bound while producing more events than
    # syncr reads from one feed. Truncating the total would bound neither the memory nor the time it
    # took to build, and would discard occupancy with nothing counting the loss: the panel would
    # report the source healthy while some of the user's commitments had silently vanished.
    outcome = parse_feed(OVERRUNNING_RECURRENCE, horizon=HORIZON, profile=HOME)

    assert outcome.events == ()
    assert [item.kind for item in outcome.rejected] == [UNPARSEABLE_RECURRENCE]
    assert str(MAX_EVENTS_PER_FEED) in outcome.rejected[0].detail
    assert "none of it was read" in outcome.rejected[0].detail


def test_no_feed_returns_more_events_than_the_per_feed_bound() -> None:
    # The bound's own control: whatever a body asks for, the returned list is within it.
    for label, body in ALL_FEEDS.items():
        outcome = parse_feed(body, horizon=HORIZON, profile=HOME)
        assert len(outcome.events) <= MAX_EVENTS_PER_FEED, label


def test_a_valid_feed_with_no_events_is_a_success_rather_than_a_failure() -> None:
    outcome = parse_feed(EMPTY_FEED, horizon=HORIZON, profile=HOME)

    assert outcome.events == ()
    assert outcome.rejected == ()
    assert outcome.events_read == 0


def test_a_whole_day_range_longer_than_syncr_will_place_is_rejected_by_name() -> None:
    # `DTEND;VALUE=DATE:99991231` is how some publishers express an open-ended all-day event. It
    # parses, and then the day count it yields overflows the arithmetic that would place the
    # occurrence. Bounded where the count is READ, so the rejection names the property.
    body = (
        "BEGIN:VEVENT\r\nUID:forever@example.org\r\nSUMMARY:Forever\r\n"
        "DTSTART;VALUE=DATE:20260209\r\nDTEND;VALUE=DATE:99991231\r\nEND:VEVENT\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert outcome.events == ()
    assert [item.kind for item in outcome.rejected] == [MALFORMED_VALUE]
    assert str(MAX_EVENT_DAYS) in outcome.rejected[0].detail
    # The component and the line, which is what AC 8's reporting depends on and what a generic
    # catch at the boundary would have lost.
    assert outcome.rejected[0].component == VEVENT
    assert outcome.rejected[0].line == 1


def test_an_orphaned_override_is_placed_rather_than_dropped() -> None:
    # An export window beginning after a series did emits the moved occurrence and not the master.
    # The feed asserts the commitment, so dropping it loses an hour the user is actually busy.
    body = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\nUID:normal@example.org\r\nSUMMARY:A normal meeting\r\n"
        "DTSTART:20260210T090000Z\r\nDTEND:20260210T100000Z\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:orphan@example.org\r\nSUMMARY:A moved occurrence\r\n"
        "RECURRENCE-ID:20260211T090000Z\r\n"
        "DTSTART:20260211T140000Z\r\nDTEND:20260211T150000Z\r\nEND:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    moved = titled(outcome.events, "moved occurrence")
    assert len(moved) == 1
    # Placed where the override says, not where the RECURRENCE-ID says.
    assert moved[0].interval.start == utc(2026, 2, 11, 14, 0)
    # And it keeps the occurrence identity the series would have given it, so a later sync that
    # does carry the master reconciles to the same anchor rather than creating a second one.
    assert moved[0].uid == "orphan@example.org#20260211T090000"
    assert moved[0].series_uid == "orphan@example.org"
    # It is not an applied override: there was no master for it to apply to.
    assert outcome.overrides_applied == 0


def test_an_orphaned_cancellation_places_nothing_and_is_counted() -> None:
    # A cancellation of an occurrence of a series nobody sent has nothing to suppress. Counted, so
    # the component does not vanish from the arithmetic.
    body = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\nUID:orphan@example.org\r\nSUMMARY:A cancelled occurrence\r\n"
        "RECURRENCE-ID:20260211T090000Z\r\nSTATUS:CANCELLED\r\n"
        "DTSTART:20260211T090000Z\r\nDTEND:20260211T100000Z\r\nEND:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert outcome.events == ()
    assert outcome.rejected == ()
    assert outcome.cancelled_discarded == 1
    assert outcome.overrides_applied == 0


def test_a_cancelled_master_cancels_its_overrides_too() -> None:
    # A replacement whose series the feed cancelled has nothing live to attach to and is not an
    # occurrence OF anything. Deciding that by dictionary membership instead places it as a
    # standalone event: a component the feed said does not happen becoming hard occupancy, which is
    # the inverse of the harm the cancellation rules exist to prevent.
    body = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\nUID:s@example.org\r\nSUMMARY:Cancelled series\r\n"
        "STATUS:CANCELLED\r\nDTSTART:20260209T090000Z\r\nDTEND:20260209T100000Z\r\n"
        "RRULE:FREQ=WEEKLY\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:s@example.org\r\nSUMMARY:Moved occurrence of a cancelled series\r\n"
        "RECURRENCE-ID:20260216T090000Z\r\n"
        "DTSTART:20260216T140000Z\r\nDTEND:20260216T150000Z\r\nEND:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert outcome.events == ()
    assert outcome.rejected == ()
    # Both components, counted: the master and the replacement it took with it.
    assert outcome.cancelled_discarded == 2
    assert outcome.overrides_applied == 0


def test_a_cancelled_duplicate_master_does_not_cancel_the_live_series_overrides() -> None:
    # The counterpart to the test above, and the edge its fix can overreach on. A feed holding BOTH
    # a live master and a cancelled one under one UID has a live series, so its override belongs to
    # that series. Deciding by "is this UID cancelled anywhere" discards the moved hour and the
    # accounting still closes, so nothing would report the loss.
    #
    # Both masters carry SEQUENCE 0, so the tie keeps the one declared first, which is the live one.
    # The cancelled duplicate therefore LOST a SEQUENCE comparison and is counted as a duplicate:
    # what discarded it is the other revision, not its own cancellation.
    outcome = parse_feed(CANCELLED_DUPLICATE_MASTER, horizon=HORIZON, profile=HOME)

    assert "Moved hour" in {event.title for event in outcome.events}
    assert outcome.overrides_applied == 1
    assert outcome.duplicates_discarded == 1
    assert outcome.cancelled_discarded == 0


def test_a_cancelled_duplicate_does_not_win_a_tie_and_delete_a_live_series() -> None:
    # Most publishers emit no SEQUENCE at all, so a tie is the COMMON case, not an edge. Letting
    # document order settle it made the same three components answer two ways: with the cancelled
    # duplicate declared first, a whole live series and its moved hour vanished, and the accounting
    # closed over the loss because one component simply moved from `placed` into `cancelled`.
    forward = parse_feed(CANCELLED_DUPLICATE_MASTER, horizon=HORIZON, profile=HOME)
    reversed_order = parse_feed(CANCELLED_DUPLICATE_MASTER_REVERSED, horizon=HORIZON, profile=HOME)

    assert {event.title for event in forward.events} == {
        event.title for event in reversed_order.events
    }
    assert "Moved hour" in {event.title for event in reversed_order.events}
    assert reversed_order.duplicates_discarded == 1


def test_a_cancelled_revision_with_the_higher_sequence_beats_a_live_older_one() -> None:
    # The duplicate rule has to run WHETHER OR NOT one of the two is cancelled. Reading the
    # cancellation first lets an older live revision win by default, and places a whole series the
    # feed's latest word says does not happen: four hours of hard occupancy from a superseded
    # revision. Exchange bumps SEQUENCE and sets STATUS:CANCELLED together, so an overlapping export
    # window carries both.
    body = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\nUID:rev@example.org\r\nSEQUENCE:1\r\nSUMMARY:Live older revision\r\n"
        "DTSTART:20260210T100000Z\r\nDTEND:20260210T110000Z\r\n"
        "RRULE:FREQ=WEEKLY;COUNT=3\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:rev@example.org\r\nSEQUENCE:7\r\nSTATUS:CANCELLED\r\n"
        "SUMMARY:Cancelled newer revision\r\n"
        "DTSTART:20260210T100000Z\r\nDTEND:20260210T110000Z\r\n"
        "RRULE:FREQ=WEEKLY;COUNT=3\r\nEND:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert outcome.events == ()
    assert outcome.cancelled_discarded == 1
    assert outcome.duplicates_discarded == 1


def test_two_orphaned_replacements_of_one_occurrence_resolve_by_sequence() -> None:
    # The orphan branch needs every rule the master-present branch has, because the shapes reaching
    # it are the same shapes. Two survivors would give ONE commitment two hard-occupancy events, and
    # they would carry the SAME uid, so the reconciler would see two rows for one occurrence.
    outcome = parse_feed(DUPLICATE_ORPHANS, horizon=HORIZON, profile=HOME)

    assert [event.title for event in outcome.events] == ["Orphan moved to 16:00"]
    assert len({event.uid for event in outcome.events}) == 1
    assert outcome.duplicates_discarded == 1


def test_an_orphaned_cancellation_suppresses_an_orphaned_override_of_that_occurrence() -> None:
    # Cancellation wins whether or not the master is present. Reading it only against a live series
    # leaves the moved hour standing as occupancy for an occurrence the feed cancelled, which is the
    # harm the cancellation rules exist to prevent.
    outcome = parse_feed(CANCELLED_ORPHAN, horizon=HORIZON, profile=HOME)

    assert outcome.events == ()
    assert outcome.cancelled_discarded == 2


def test_two_replacements_of_one_occurrence_resolve_by_sequence_and_count_the_discard() -> None:
    # An export overlapping two edits repeats an override as readily as it repeats a master, so the
    # rule that settles duplicate masters has to settle these too. Overwriting by document order
    # loses a component silently AND makes the answer depend on declaration order.
    outcome = parse_feed(DUPLICATE_REPLACEMENTS, horizon=HORIZON, profile=HOME)

    titles = {event.title for event in outcome.events}
    assert "Moved to 16:00" in titles
    assert "Moved to 14:00" not in titles
    assert outcome.duplicates_discarded == 1
    assert outcome.overrides_applied == 1


def test_the_surviving_replacement_does_not_depend_on_declaration_order() -> None:
    # The same two components with the higher SEQUENCE first. A rule that kept whichever arrived
    # last would answer the two bodies differently, which is the defect the master rule already
    # avoids by comparing SEQUENCE rather than position.
    first = parse_feed(DUPLICATE_REPLACEMENTS, horizon=HORIZON, profile=HOME)
    reversed_order = parse_feed(DUPLICATE_REPLACEMENTS_REVERSED, horizon=HORIZON, profile=HOME)

    assert {event.title for event in first.events} == {
        event.title for event in reversed_order.events
    }
    assert reversed_order.duplicates_discarded == 1


def test_a_repeated_cancellation_of_one_occurrence_is_counted() -> None:
    # The sibling of the duplicate-override rule, three lines away in the same loop. A repeated
    # tombstone has no SEQUENCE question to settle, so the risk is not a wrong answer but a
    # component absorbed by a set and dropped out of the arithmetic.
    outcome = parse_feed(DUPLICATE_TOMBSTONES, horizon=HORIZON, profile=HOME)

    assert outcome.duplicates_discarded == 1
    # The surviving tombstone claimed a real occurrence, so it is an override that was applied.
    assert outcome.overrides_applied == 1
    on_the_17th = [event for event in outcome.events if event.interval.start.day == 17]
    assert on_the_17th == []


def test_an_occurrence_both_moved_and_cancelled_is_cancelled_and_the_override_counted() -> None:
    # Cancellation is read before the replacement, as everywhere else here: the feed said the hour
    # does not happen. The override it displaces is still a component, so it is counted rather than
    # dropped where no term would report it.
    outcome = parse_feed(MOVED_AND_CANCELLED, horizon=HORIZON, profile=HOME)

    assert "Moved" not in {event.title for event in outcome.events}
    assert outcome.cancelled_discarded == 1
    assert outcome.overrides_applied == 1


def test_an_override_matching_no_occurrence_is_counted_rather_than_lost() -> None:
    # A publisher that edits a series' rule and keeps a previously emitted override produces one,
    # and Google and Exchange exports both do. A replacement is registered by UID and read by
    # occurrence, so one naming a time the rule never produces is only visible by comparing what
    # expansion consumed against what was registered.
    #
    # Counted, NOT placed. Every replacement that reaches this point has a master in the same body,
    # so the series did expand and its current rule is what the feed asserts. Placing the stale
    # override as well puts two events on one occupied hour, which is what a duplicate master that
    # shifts the series' times produces.
    body = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\nUID:m@example.org\r\nSUMMARY:Weekly Monday\r\n"
        "DTSTART:20260209T090000Z\r\nDTEND:20260209T100000Z\r\n"
        "RRULE:FREQ=WEEKLY;BYDAY=MO\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:m@example.org\r\nSUMMARY:Moved to Tuesday\r\n"
        "RECURRENCE-ID:20260210T090000Z\r\n"
        "DTSTART:20260210T140000Z\r\nDTEND:20260210T150000Z\r\nEND:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert titled(outcome.events, "Moved to Tuesday") == []
    # Counted as read-and-placed-nothing rather than as a duplicate: the rule was edited, so nothing
    # superseded this override and calling it a duplicate would put a claim on the panel that the
    # parser cannot support.
    assert outcome.unplaced == 1
    assert outcome.duplicates_discarded == 0
    # And it is NOT counted as applied: the term means "replaced an occurrence", so its name and the
    # arithmetic agree.
    assert outcome.overrides_applied == 0
    # The Mondays the rule does produce are untouched.
    assert len(titled(outcome.events, "Weekly Monday")) == 2


def test_a_duplicate_master_that_shifts_a_series_does_not_double_the_moved_hour() -> None:
    # The shape that makes the rule above load-bearing, and the one an export covering two
    # overlapping windows produces: the same meeting at two SEQUENCE values, the later of which
    # moved it, plus the override the earlier window emitted. Placing that override alongside
    # the winning master's occurrence puts two hours of hard occupancy on one commitment.
    body = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\nUID:shift@example.org\r\nSEQUENCE:1\r\nSUMMARY:Weekly at 10\r\n"
        "DTSTART:20260210T100000Z\r\nDTEND:20260210T110000Z\r\n"
        "RRULE:FREQ=WEEKLY;COUNT=3\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:shift@example.org\r\nSEQUENCE:2\r\nSUMMARY:Weekly at 12\r\n"
        "DTSTART:20260210T120000Z\r\nDTEND:20260210T130000Z\r\n"
        "RRULE:FREQ=WEEKLY;COUNT=3\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:shift@example.org\r\nSUMMARY:Moved to 14:00\r\n"
        "RECURRENCE-ID:20260217T100000Z\r\n"
        "DTSTART:20260217T140000Z\r\nDTEND:20260217T150000Z\r\nEND:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert titled(outcome.events, "Moved to 14:00") == []
    on_the_17th = [event for event in outcome.events if event.interval.start.day == 17]
    assert len(on_the_17th) == 1
    # The losing revision's master is a duplicate; the override that belonged to it placed nothing.
    assert outcome.duplicates_discarded == 1
    assert outcome.unplaced == 1


def test_an_override_that_matches_an_occurrence_is_counted_as_applied() -> None:
    # The other side of that term, so it is shown to distinguish rather than to count nothing.
    outcome = parse_feed(UNIVERSITY_TIMETABLE, horizon=HORIZON, profile=HOME)

    assert outcome.overrides_applied == 1


def test_a_tombstone_matching_no_occurrence_is_counted_rather_than_dropped() -> None:
    # It cancels an occurrence the rule never produces, so there is nothing to suppress. Counted,
    # because a component that placed nothing and explained nothing reads as a loss.
    body = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\nUID:m@example.org\r\nSUMMARY:Weekly Monday\r\n"
        "DTSTART:20260209T090000Z\r\nDTEND:20260209T100000Z\r\n"
        "RRULE:FREQ=WEEKLY;BYDAY=MO\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:m@example.org\r\nSUMMARY:Weekly Monday\r\n"
        "RECURRENCE-ID:20260210T090000Z\r\nSTATUS:CANCELLED\r\n"
        "DTSTART:20260210T090000Z\r\nDTEND:20260210T100000Z\r\nEND:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert outcome.cancelled_discarded == 1
    assert outcome.overrides_applied == 0
    assert len(titled(outcome.events, "Weekly Monday")) == 2


def test_an_applied_override_is_counted_as_applied() -> None:
    # The term the accounting depends on. An override is neither kept as an event of its own nor
    # discarded, so without its own count it reads as a component that vanished.
    outcome = parse_feed(UNIVERSITY_TIMETABLE, horizon=HORIZON, profile=HOME)

    assert outcome.overrides_applied == 1


def test_a_component_placing_nothing_inside_the_horizon_is_counted() -> None:
    # Not a loss and not an error: the event is real, it is simply elsewhere in time. Counted
    # anyway, because otherwise it is indistinguishable from occupancy that vanished.
    body = (
        "BEGIN:VEVENT\r\nUID:distant@example.org\r\nSUMMARY:Long ago\r\n"
        "DTSTART;VALUE=DATE:00010101\r\nDTEND;VALUE=DATE:00010102\r\nEND:VEVENT\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert outcome.events == ()
    assert outcome.rejected == ()
    assert outcome.events_read == 1
    assert outcome.unplaced == 1


def test_every_component_of_every_feed_is_accounted_for() -> None:
    # The counts are what the panel reports, so they have to close: a component that appeared in
    # none of the buckets would be occupancy that vanished with no explanation.
    #
    # Every term is read off the OUTCOME, including how many components placed something. A term
    # recomputed from the events cannot tell two components apart when both contribute events under
    # one identity, and a term counted from the body's text excuses a component whatever the parser
    # did with it.
    for label, body in ALL_FEEDS.items():
        outcome = parse_feed(body, horizon=HORIZON, profile=HOME)
        accounted = (
            outcome.placed
            + len(_component_rejections(outcome))
            + outcome.duplicates_discarded
            + outcome.cancelled_discarded
            + outcome.overrides_applied
            + outcome.unplaced
        )
        assert accounted == outcome.events_read, label


def test_the_accounting_sees_two_orphans_of_one_series() -> None:
    # The case that shows why `placed` is reported rather than derived. Two orphaned replacements of
    # one absent master are both placed and both name that series, so counting the events' series
    # reads two components as one and the arithmetic closes one short while a commitment is
    # unaccounted for.
    body = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\nUID:gone@example.org\r\nSUMMARY:First orphan\r\n"
        "RECURRENCE-ID:20260210T090000Z\r\n"
        "DTSTART:20260210T140000Z\r\nDTEND:20260210T150000Z\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:gone@example.org\r\nSUMMARY:Second orphan\r\n"
        "RECURRENCE-ID:20260217T090000Z\r\n"
        "DTSTART:20260217T140000Z\r\nDTEND:20260217T150000Z\r\nEND:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert outcome.placed == 2
    assert {event.series_uid for event in outcome.events} == {"gone@example.org"}
    assert outcome.placed + outcome.overrides_applied + outcome.unplaced == outcome.events_read


def _component_rejections(outcome: FetchOutcome) -> list[RejectedComponent]:
    """The rejections that describe a component the parser read.

    A feed-level rejection names the calendar rather than an event, because the lexer refused the
    body before any component was read. It is excluded here rather than skipped, so the arithmetic
    stays a real check on every body including that one, whose ``events_read`` is zero.
    """
    return [rejected for rejected in outcome.rejected if rejected.component == VEVENT]


@pytest.mark.parametrize("label", sorted(ALL_FEEDS))
def test_no_feed_in_the_corpus_raises(label: str) -> None:
    # The adapter's whole contract: hostility is absorbed and returned, never raised at a
    # caller. A body that raised would take a worker tick down with it.
    parse_feed(ALL_FEEDS[label], horizon=HORIZON, profile=HOME)


def test_a_deeply_nested_feed_is_a_stated_rejection_rather_than_a_recursion_error() -> None:
    # Nesting depth is a property of a body a third-party publisher controls, and a recursive walk
    # turns 21 KB of it into a RecursionError. That is not an IcsRejection, so it would escape the
    # adapter, abort the whole tenant's sync pass, and roll back the sync state of every feed read
    # before it.
    outcome = parse_feed(nested_feed(MAX_COMPONENT_DEPTH + 1), horizon=HORIZON, profile=HOME)

    assert outcome.events == ()
    assert [item.kind for item in outcome.rejected] == [MALFORMED_VALUE]
    assert outcome.rejected[0].component == "VCALENDAR"
    # The line the lexer gave up on, so a publisher has somewhere to look.
    assert outcome.rejected[0].line > 0
    assert str(MAX_COMPONENT_DEPTH) in outcome.rejected[0].detail


def test_a_feed_nesting_up_to_the_bound_is_read() -> None:
    # The accepting side of the bound, so the comparison is shown not to be off by one. The event is
    # buried under the deepest nesting syncr accepts and still comes back.
    outcome = parse_feed(nested_feed(MAX_COMPONENT_DEPTH), horizon=HORIZON, profile=HOME)

    assert outcome.rejected == ()
    assert [event.uid for event in outcome.events] == ["buried@example.org"]


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


def test_an_override_moving_an_occurrence_into_the_horizon_is_placed() -> None:
    # The occurrence the feed moved is INSIDE the horizon; the one it moved FROM is not, so
    # expansion never offered that key and the override went unclaimed. Counting it loses an hour
    # the user is busy, and nothing else reports it: the panel shows a component read and no
    # occupancy, while the solver books over a meeting the publisher pulled forward.
    body = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\nUID:fwd@example.org\r\nSUMMARY:Weekly\r\n"
        "DTSTART:20260303T100000Z\r\nDTEND:20260303T110000Z\r\n"
        "RRULE:FREQ=WEEKLY;COUNT=3\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:fwd@example.org\r\nSUMMARY:Pulled forward\r\n"
        "RECURRENCE-ID:20260310T100000Z\r\n"
        "DTSTART:20260216T140000Z\r\nDTEND:20260216T150000Z\r\nEND:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert [event.title for event in outcome.events] == ["Pulled forward"]
    assert outcome.events[0].interval.start == utc(2026, 2, 16, 14, 0)


def test_an_override_moving_an_occurrence_out_of_the_horizon_places_nothing() -> None:
    # The mirror. The occurrence generated the event, but a replacement is placed at the time the
    # REPLACEMENT states, so an override moving one to August must not leave an anchor in a plan for
    # February. It is still counted as applied, because it did replace the occurrence.
    body = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\nUID:out@example.org\r\nSUMMARY:Weekly\r\n"
        "DTSTART:20260210T100000Z\r\nDTEND:20260210T110000Z\r\n"
        "RRULE:FREQ=WEEKLY;COUNT=3\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:out@example.org\r\nSUMMARY:Pushed to August\r\n"
        "RECURRENCE-ID:20260217T100000Z\r\n"
        "DTSTART:20260817T140000Z\r\nDTEND:20260817T150000Z\r\nEND:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert "Pushed to August" not in {event.title for event in outcome.events}
    assert all(event.interval.start < utc(2026, 3, 1, 0, 0) for event in outcome.events)
    assert outcome.overrides_applied == 1
