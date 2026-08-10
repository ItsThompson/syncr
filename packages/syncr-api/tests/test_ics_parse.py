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
from zoneinfo import ZoneInfo

import pytest

from syncr_api.calendars.config import (
    DETAIL_MAX_LENGTH,
    MALFORMED_VALUE,
    MAX_EVENT_DAYS,
    MAX_EVENTS_PER_FEED,
    MISSING_DURATION,
    READ_BUDGET_SPENT,
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
    CANCELLED_NEWER_REVISION,
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
    SHIFTED_BY_A_DUPLICATE_MASTER,
    SPRING_FORWARD_GAP,
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
        # A part that LIMITS at this frequency adds nothing to the set, so these select nothing
        # however many values they name.
        ("FREQ=MINUTELY;BYMINUTE=0,30;BYSETPOS=2", True),
        ("FREQ=SECONDLY;BYSECOND=0,30;BYSETPOS=2", True),
        ("FREQ=SECONDLY;BYMINUTE=0,30;BYSECOND=0,15;BYSETPOS=3", True),
        ("FREQ=MINUTELY;BYMINUTE=0,30;BYSECOND=0,30;BYSETPOS=-3", True),
        ("FREQ=HOURLY;BYMINUTE=0,30;BYSETPOS=2", False),
        ("FREQ=HOURLY;BYSETPOS=1", False),
        # BYSECOND expands a MINUTELY period, so this one has somewhere to land.
        ("FREQ=MINUTELY;BYSECOND=0,30;BYSETPOS=2", False),
    ],
)
def test_a_setpos_is_refused_only_when_its_period_cannot_hold_it(rule: str, refused: bool) -> None:
    # BYSETPOS picks the Nth member of each period's set. A position past it selects nothing, the
    # rule yields nothing, and dateutil walks to its own maximum year INSIDE ONE next() call:
    # measured at sixty seconds for one component, with the worker tick held open. Neither a step
    # bound nor an UNTIL can see that, because dateutil compares against UNTIL only when a period
    # yields.
    #
    # WHICH parts build that set is per-frequency: RFC 5545 has BYMINUTE expand an hour and merely
    # limit which minutes a MINUTELY rule looks at, and nothing expands a second. Counting a
    # limiting part as room passed three of these shapes through to dateutil, which walked anyway.
    #
    # Compared against the set SIZE rather than refused as a shape, so the last three still expand:
    # selecting the second of two is a rule dateutil answers in milliseconds.
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
        # Not "nothing was rejected": one of these expands past the per-feed event bound and is
        # refused BY that bound. What matters is that this guard did not fire.
        assert all("produces nothing" not in item.detail for item in outcome.rejected)


@pytest.mark.parametrize("interval", ["1", "2", "02", "0002", "+1"])
def test_a_positive_interval_is_expanded_however_it_is_written(interval: str) -> None:
    # The accepting side, including the padded forms RFC 5545's digit grammar permits and the signed
    # form it does not write but dateutil accepts, so the guard is shown to refuse a property rather
    # than a spelling.
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
    outcome = parse_feed(CANCELLED_NEWER_REVISION, horizon=HORIZON, profile=HOME)

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
    outcome = parse_feed(SHIFTED_BY_A_DUPLICATE_MASTER, horizon=HORIZON, profile=HOME)

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


@pytest.mark.parametrize(
    ("value", "property_named"),
    [
        ("INTERVAL=\u00b2", "INTERVAL"),
        ("INTERVAL=\u2461", "INTERVAL"),
        ("BYSETPOS=\u00b2", None),
    ],
)
def test_a_digit_int_refuses_is_answered_where_it_is_read(
    value: str, property_named: str | None
) -> None:
    # str.isdigit is true for a superscript two and for a circled two, and int() refuses both. A
    # publisher can carry either, so gating a conversion on isdigit leaves it able to raise while
    # reading as bounded. The package answers these where the value is read, so the detail can name
    # the property rather than quoting a converter's complaint about a literal.
    body = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:nd@example.org\r\n"
        "DTSTART:20260210T100000Z\r\nDTEND:20260210T110000Z\r\n"
        f"RRULE:FREQ=HOURLY;BYMINUTE=0;{value}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert outcome.events == ()
    assert [item.kind for item in outcome.rejected] == [UNPARSEABLE_RECURRENCE]
    detail = outcome.rejected[0].detail
    assert "invalid literal" not in detail
    if property_named is not None:
        assert property_named in detail


def test_a_refused_interval_is_named_by_size_rather_than_quoted_whole() -> None:
    # The message has to survive a value the feed chose the length of. Quoting it would put
    # thousands of characters on the panel and into the stored rejection, which is the reasoning
    # the duration bound already applies by reporting a digit count.
    body = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:big@example.org\r\n"
        "DTSTART:20260210T100000Z\r\nDTEND:20260210T110000Z\r\n"
        f"RRULE:FREQ=DAILY;INTERVAL={'9' * 5_000}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert [item.kind for item in outcome.rejected] == [UNPARSEABLE_RECURRENCE]
    detail = outcome.rejected[0].detail
    assert "5000-character" in detail
    assert "9999" not in detail
    assert len(detail) < 200


# One long all-day master and one short timed master in the same feed. Their expansion windows reach
# back by their OWN lengths, ten days against one hour, so a window taken from either one is wrong
# for the other.
_LONG_MASTER = (
    "BEGIN:VEVENT\r\nUID:halfterm@example.org\r\nSUMMARY:Half term\r\n"
    "DTSTART;VALUE=DATE:20260202\r\nDTEND;VALUE=DATE:20260212\r\nEND:VEVENT\r\n"
)
_SHORT_MASTER = (
    "BEGIN:VEVENT\r\nUID:weekly@example.org\r\nSUMMARY:Weekly\r\n"
    "DTSTART:20260209T100000Z\r\nDTEND:20260209T110000Z\r\n"
    "RRULE:FREQ=WEEKLY;COUNT=3\r\nEND:VEVENT\r\n"
)
# An override of the SHORT series naming an occurrence a week before the horizon: inside the long
# master's window, outside the short one's, which is the band where the two disagree.
_PULLED_FORWARD = (
    "BEGIN:VEVENT\r\nUID:weekly@example.org\r\nSUMMARY:Pulled forward\r\n"
    "RECURRENCE-ID:20260202T100000Z\r\n"
    "DTSTART:20260218T140000Z\r\nDTEND:20260218T150000Z\r\nEND:VEVENT\r\n"
)


@pytest.mark.parametrize(
    "order",
    [
        (_LONG_MASTER, _SHORT_MASTER, _PULLED_FORWARD),
        (_SHORT_MASTER, _LONG_MASTER, _PULLED_FORWARD),
        (_PULLED_FORWARD, _LONG_MASTER, _SHORT_MASTER),
    ],
)
def test_an_unclaimed_override_is_judged_against_its_own_master_s_window(
    order: tuple[str, ...],
) -> None:
    # Whether an override was ever OFFERED to its master depends on that master's own expansion
    # window, and each master's window reaches back by its own length. One window for the whole feed
    # is some other master's: a longer one swallows the override's original time and the moved hour
    # is counted as superseded instead of placed, a shorter one does the reverse and doubles an
    # occupied hour. Either way the same components answer differently depending on the order they
    # arrive in, which is what the duplicate-master tie-break exists to prevent.
    body = f"BEGIN:VCALENDAR\r\n{''.join(order)}END:VCALENDAR\r\n"

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    titles = sorted(event.title for event in outcome.events)
    assert titles == ["Half term", "Pulled forward", "Weekly", "Weekly"]
    assert outcome.events_read == 3


def test_a_magnitude_on_an_unclaimed_override_is_reported_rather_than_raised() -> None:
    # `stranded` runs outside the boundary that turns a component's values into a rejection, so any
    # arithmetic it performs on a publisher's magnitude escapes the whole package. It decides only
    # whether the master could have covered the hour; the placement path builds the span, under the
    # boundary, so an overflow arrives as a rejection naming the component and the line.
    body = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\nUID:series@example.org\r\nSUMMARY:Standup\r\n"
        "DTSTART:20260210T140000Z\r\nDTEND:20260210T150000Z\r\n"
        "RRULE:FREQ=WEEKLY;COUNT=3\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:series@example.org\r\nSUMMARY:Stale override\r\n"
        "RECURRENCE-ID:20250101T140000Z\r\n"
        "DTSTART:99991201T000000Z\r\nDURATION:P36600D\r\nEND:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert [event.title for event in outcome.events] == ["Standup", "Standup"]
    assert len(outcome.rejected) == 1
    assert outcome.rejected[0].line != 0


_MOVED_OVERRIDE = (
    "BEGIN:VEVENT\r\nUID:refused@example.org\r\nSUMMARY:Moved hour\r\n"
    "RECURRENCE-ID:20260210T100000Z\r\n"
    "DTSTART:20260217T140000Z\r\nDTEND:20260217T150000Z\r\nEND:VEVENT\r\n"
)


@pytest.mark.parametrize(
    "master",
    [
        # Refused while its VALUES are read, so it never reaches the partition at all.
        "BEGIN:VEVENT\r\nUID:refused@example.org\r\nSUMMARY:Series\r\n"
        "DTSTART;TZID=Nowhere/Land:20260210T100000\r\n"
        "DTEND;TZID=Nowhere/Land:20260210T110000\r\n"
        "RRULE:FREQ=WEEKLY;COUNT=3\r\nEND:VEVENT\r\n",
        # Refused while it EXPANDS, so it is present in the partition and places nothing.
        "BEGIN:VEVENT\r\nUID:refused@example.org\r\nSUMMARY:Series\r\n"
        "DTSTART:20260210T100000Z\r\nDTEND:20260210T110000Z\r\n"
        "RRULE:FREQ=DAILY;INTERVAL=0\r\nEND:VEVENT\r\n",
        # Refused while it expands, by a different property again.
        "BEGIN:VEVENT\r\nUID:refused@example.org\r\nSUMMARY:Series\r\n"
        "DTSTART:20260210T100000Z\r\nDTEND:20260210T110000Z\r\n"
        "RRULE:FREQ=MONTHLY;BYDAY=8MO\r\nEND:VEVENT\r\n",
    ],
)
def test_a_replacement_outlives_a_master_the_feed_got_wrong(master: str) -> None:
    # A master syncr refused places nothing, so nothing in the feed covers the hour its replacement
    # names: the orphan rule's premise exactly. Reading the master's PRESENCE instead of whether it
    # expanded made the answer depend on which layer refused it, so the same feed shape kept the
    # moved hour when the zone was wrong and lost it when the rule was.
    body = f"BEGIN:VCALENDAR\r\n{master}{_MOVED_OVERRIDE}END:VCALENDAR\r\n"

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert [event.title for event in outcome.events] == ["Moved hour"]
    assert len(outcome.rejected) == 1
    assert outcome.events_read == 2


# A rule that can never match: February has no thirtieth. RFC 5545 says an instance on an invalid
# date is ignored, and dateutil ignores it by scanning to the last year it can represent, at a cost
# of about two and a half seconds and one expansion step while placing nothing.
_NEVER_MATCHES = "RRULE:FREQ=MINUTELY;BYMONTH=2;BYMONTHDAY=30"


def _slow_feed(count: int) -> str:
    body = "".join(
        f"BEGIN:VEVENT\r\nUID:slow-{index}@example.org\r\nSUMMARY:S{index}\r\n"
        "DTSTART:20260210T090000Z\r\nDTEND:20260210T100000Z\r\n"
        f"{_NEVER_MATCHES}\r\nEND:VEVENT\r\n"
        for index in range(count)
    )
    return f"BEGIN:VCALENDAR\r\n{body}END:VCALENDAR\r\n"


def test_a_feed_cannot_spend_more_than_its_reading_budget() -> None:
    # Nothing bounds a feed's COMPONENT COUNT. The per-feed bound counts placed events, and these
    # place none; the per-series bound counts expansion steps, and these take one each. So the cost
    # multiplies by however many components the byte limit allows: measured at 2.5 seconds each and
    # linear, which is upwards of 36 hours of one worker tick with its transaction open for a feed
    # at MAX_FEED_BYTES, reporting no events and no rejections.
    #
    # A budget of zero states a spent budget rather than waiting for one, which is why it is a
    # parameter.
    outcome = parse_feed(_slow_feed(6), horizon=HORIZON, profile=HOME, budget=0.0)

    assert outcome.events == ()
    assert len(outcome.rejected) == 6
    # Its own class, because nothing is wrong with these components: they were not read. The panel
    # groups by class and states a reason per class, so a feed of ordinary meetings cut short must
    # not read as a recurrence problem it does not have.
    assert {item.kind for item in outcome.rejected} == {READ_BUDGET_SPENT}
    assert "seconds of reading" in outcome.rejected[0].detail
    # The bound in force, not the constant: a message that names the default while honoring the
    # parameter is a bound describing a figure it did not apply. Anchored on "its", because "0
    # seconds" is a substring of the default's own "30 seconds" and matched it either way.
    assert "its 0 seconds" in outcome.rejected[0].detail


def test_a_feed_that_spends_its_budget_still_accounts_for_every_component() -> None:
    # Refusing the remainder must not open the arithmetic. Every component past the deadline is
    # rejected individually, with a reason, rather than the parse returning early and leaving
    # components read but unaccounted for.
    outcome = parse_feed(_slow_feed(4), horizon=HORIZON, profile=HOME, budget=0.0)

    accounted = (
        outcome.placed
        + outcome.unplaced
        + len(outcome.rejected)
        + outcome.duplicates_discarded
        + outcome.cancelled_discarded
    )
    assert accounted == outcome.events_read == 4


def test_a_budget_leaves_a_feed_the_product_exists_to_read_alone() -> None:
    # The bound has to clear the slowest LEGITIMATE feed with room, or it refuses what syncr is for.
    # Measured: 6.9 to 7.9 seconds for 9,800 events from 700 daily series running since 2010, across
    # runs and machines, against a budget of a minute.
    body = "".join(
        f"BEGIN:VEVENT\r\nUID:real-{index}@example.org\r\nSUMMARY:Lecture {index}\r\n"
        "DTSTART;TZID=Europe/London:20100901T090000\r\n"
        "DTEND;TZID=Europe/London:20100901T100000\r\n"
        "RRULE:FREQ=DAILY\r\nEND:VEVENT\r\n"
        for index in range(20)
    )

    outcome = parse_feed(
        f"BEGIN:VCALENDAR\r\n{body}END:VCALENDAR\r\n", horizon=HORIZON, profile=HOME
    )

    assert outcome.rejected == ()
    assert len(outcome.events) == 20 * 14


def test_a_rejection_detail_is_bounded_however_long_the_feed_makes_it() -> None:
    # The net. A detail is written to JSONB on the sync state and served whole by the read route,
    # and some messages quote a value the publisher supplied, so the length of a stored detail is
    # the feed's to choose unless something bounds it where the rejection is built.
    body = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:zone@example.org\r\n"
        f"DTSTART;TZID={'Nowhere/' * 900}:20260210T100000\r\n"
        "DTEND;TZID=UTC:20260210T110000\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert len(outcome.rejected) == 1
    detail = outcome.rejected[0].detail
    assert len(detail) <= DETAIL_MAX_LENGTH + 40
    assert "characters in all" in detail


def test_a_refused_rule_is_named_by_size_rather_than_quoted_whole() -> None:
    # The attribution half, for the one value a feed can make arbitrarily long and still have
    # refused by a library: the rule itself. Truncating it would fill the panel with the publisher's
    # padding, so past a readable width the rule is named by size and the library's reason is kept.
    #
    # BYDAY carries weekday codes rather than numbers, so it is the part syncr does not range-check
    # and dateutil does: exactly the shape where a library's own message reaches the panel.
    body = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:long@example.org\r\n"
        "DTSTART:20260210T100000Z\r\nDTEND:20260210T110000Z\r\n"
        f"RRULE:FREQ=DAILY;BYDAY={','.join(['XX'] * 2_000)}\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert [item.kind for item in outcome.rejected] == [UNPARSEABLE_RECURRENCE]
    detail = outcome.rejected[0].detail
    assert "6016 characters" in detail
    # syncr names the rule by size; dateutil's own reason still quotes part of the value, which is
    # why the stored detail is bounded as well as named.
    assert len(detail) <= DETAIL_MAX_LENGTH + 40
    assert "characters in all" in detail


def test_an_occurrence_ending_exactly_at_the_horizon_places_nothing() -> None:
    # The expansion window reaches back by the series' own length so an occurrence running INTO the
    # horizon is found. That also finds one ending exactly AT it, and the horizon is half-open, so
    # that event occupies none of it. Filtering only the replacements left the same position
    # answered two ways depending on whether a publisher had moved it.
    body = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:edge@example.org\r\nSUMMARY:Ends at midnight\r\n"
        "DTSTART:20260208T230000Z\r\nDTEND:20260209T000000Z\r\n"
        "RRULE:FREQ=DAILY;COUNT=1\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert outcome.events == ()
    assert outcome.unplaced == 1


def test_syncr_s_own_refusal_is_not_re_explained_as_a_library_fault() -> None:
    # IcsRejection is a ValueError by inheritance, so the catch written for a foreign expander's
    # lazily raised faults also catches this package's own refusals and re-wrapped them. The panel
    # then read "the recurrence rule cannot be expanded: the recurrence rule selects position 2 of a
    # HOURLY period holding 1", which explains syncr's own decision as something dateutil could not
    # do, and buries the property the publisher has to fix.
    body = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:own@example.org\r\n"
        "DTSTART:20260210T100000Z\r\nDTEND:20260210T110000Z\r\n"
        "RRULE:FREQ=HOURLY;BYMINUTE=0;BYSETPOS=2\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    detail = outcome.rejected[0].detail
    assert detail.startswith("the recurrence rule selects position 2")
    assert "cannot be expanded" not in detail


# July, when London runs an hour ahead of UTC, so the two RECURRENCE-ID forms differ in text while
# naming one instant. The corpus sits in February at an offset of zero, where they cannot differ.
_SUMMER = Interval(datetime(2026, 7, 6, 0, 0, tzinfo=UTC), datetime(2026, 7, 20, 0, 0, tzinfo=UTC))
_ZONED_SERIES = (
    "BEGIN:VEVENT\r\nUID:zoned@example.org\r\nSUMMARY:Weekly 09:00 London\r\n"
    "DTSTART;TZID=Europe/London:20260706T090000\r\n"
    "DTEND;TZID=Europe/London:20260706T100000\r\n"
    "RRULE:FREQ=WEEKLY;COUNT=3\r\nEND:VEVENT\r\n"
)


@pytest.mark.parametrize(
    "recurrence_id",
    ["RECURRENCE-ID:20260713T080000Z", "RECURRENCE-ID;TZID=Europe/London:20260713T090000"],
)
def test_a_recurrence_id_names_one_occurrence_in_either_form(recurrence_id: str) -> None:
    # RFC 5545 lets a publisher write a RECURRENCE-ID as UTC or with a TZID, and both name the same
    # occurrence. Matching on the wall TEXT made the UTC form match nothing wherever the zone's
    # offset is non-zero, so the moved hour was dropped and the original stood in the plan.
    body = (
        f"BEGIN:VCALENDAR\r\n{_ZONED_SERIES}"
        "BEGIN:VEVENT\r\nUID:zoned@example.org\r\nSUMMARY:Moved to 14:00\r\n"
        f"{recurrence_id}\r\n"
        "DTSTART;TZID=Europe/London:20260713T140000\r\n"
        "DTEND;TZID=Europe/London:20260713T150000\r\nEND:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=_SUMMER, profile=HOME)

    assert outcome.overrides_applied == 1
    on_the_13th = [event for event in outcome.events if event.interval.start.day == 13]
    assert [event.interval.start for event in on_the_13th] == [utc(2026, 7, 13, 13, 0)]


@pytest.mark.parametrize(
    "recurrence_id",
    ["RECURRENCE-ID:20260713T080000Z", "RECURRENCE-ID;TZID=Europe/London:20260713T090000"],
)
def test_a_cancelled_occurrence_is_suppressed_in_either_form(recurrence_id: str) -> None:
    # The same defect on the cancellation path, which is the one that costs the user an hour: the
    # feed says this occurrence does not happen, and a key that matched nothing left it standing as
    # hard occupancy while the arithmetic closed over a component counted as cancelled.
    body = (
        f"BEGIN:VCALENDAR\r\n{_ZONED_SERIES}"
        "BEGIN:VEVENT\r\nUID:zoned@example.org\r\nSTATUS:CANCELLED\r\n"
        "SUMMARY:Cancelled occurrence\r\n"
        f"{recurrence_id}\r\n"
        "DTSTART;TZID=Europe/London:20260713T090000\r\n"
        "DTEND;TZID=Europe/London:20260713T100000\r\nEND:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=_SUMMER, profile=HOME)

    assert [event.interval.start.day for event in outcome.events] == [6]
    assert outcome.overrides_applied == 1


@pytest.mark.parametrize("rule", ["", "RRULE:FREQ=WEEKLY;COUNT=1\r\n"])
def test_an_rdate_in_its_own_zone_is_resolved_in_that_zone(rule: str) -> None:
    # RFC 5545 lets an RDATE carry its own TZID, and a publisher that writes one means it: 09:00 in
    # New York is 14:00 UTC, whatever zone the series it is added to recurs in.
    #
    # Both parameters are here because an extra date reaches the expansion two ways. A series with
    # no rule is its own occurrence plus its extra dates; a series with one merges them into the
    # values the rule produces. The zone has to travel down both.
    body = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\nUID:rdate@example.org\r\nSUMMARY:Zoned addition\r\n"
        "DTSTART;TZID=Europe/London:20260210T090000\r\n"
        "DTEND;TZID=Europe/London:20260210T100000\r\n"
        f"{rule}"
        "RDATE;TZID=America/New_York:20260212T090000\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    added = [event for event in outcome.events if event.interval.start.day == 12]
    assert [event.interval.start for event in added] == [utc(2026, 2, 12, 14, 0)]
    # The series' own occurrence is unmoved: 09:00 London in February is 09:00 UTC.
    assert [event.interval.start for event in outcome.events if event.interval.start.day == 10] == [
        utc(2026, 2, 10, 9, 0)
    ]


@pytest.mark.parametrize(
    ("series_start", "rdate", "horizon", "starts"),
    [
        # February: New York is UTC-5 and London, the profile's zone, is UTC+0.
        (
            "20260210T090000",
            "RDATE:20260212T140000Z",
            HORIZON,
            [utc(2026, 2, 10, 14, 0), utc(2026, 2, 12, 14, 0)],
        ),
        # July: New York is UTC-4 and London is UTC+1, so the two wrong readings answer differently
        # from each other as well as from this one. Read as a New York wall time the addition is at
        # 18:00Z, read in the profile's zone it is at 13:00Z.
        (
            "20260706T090000",
            "RDATE:20260712T140000Z",
            _SUMMER,
            [utc(2026, 7, 6, 13, 0), utc(2026, 7, 12, 14, 0)],
        ),
    ],
)
def test_an_rdate_stating_an_instant_is_read_in_utc_and_in_no_other_zone(
    series_start: str, rdate: str, horizon: Interval, starts: list[datetime]
) -> None:
    # A Z suffix is already an instant, so a 14:00Z addition to a New York series is at 14:00Z. Read
    # as a New York wall time it lands five hours out, in the wrong hour of the user's evening.
    body = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\nUID:utc-rdate@example.org\r\nSUMMARY:Instant addition\r\n"
        f"DTSTART;TZID=America/New_York:{series_start}\r\n"
        "DURATION:PT1H\r\n"
        f"{rdate}\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=horizon, profile=HOME)

    assert sorted(event.interval.start for event in outcome.events) == starts


def test_a_floating_rdate_stays_on_the_clock_the_series_recurs_in() -> None:
    # An RDATE with no TZID and no Z suffix names no zone, so it means 09:00 on the series' own
    # clock. Read in the zone the USER is in instead, one feed would answer differently for two
    # readers, and a value the publisher wrote without a zone would move.
    body = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\nUID:floating-rdate@example.org\r\nSUMMARY:Floating addition\r\n"
        "DTSTART;TZID=Asia/Tokyo:20260210T090000\r\n"
        "DTEND;TZID=Asia/Tokyo:20260210T100000\r\n"
        "RDATE:20260212T090000\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    # Tokyo is UTC+9, so 09:00 there is 00:00Z. The profile's London would have made it 09:00Z.
    added = [event for event in outcome.events if event.interval.start.day == 12]
    assert [event.interval.start for event in added] == [utc(2026, 2, 12, 0, 0)]


def test_two_rdates_naming_two_zones_each_land_in_the_zone_they_name() -> None:
    # One series, two additions, two zones, neither of them the series'. A reading that resolved
    # every addition in ONE zone lands at least one of these in the wrong hour, whichever zone it
    # picked: the series', UTC, or the first value's.
    body = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\nUID:two-zones@example.org\r\nSUMMARY:Two zoned additions\r\n"
        "DTSTART;TZID=Europe/London:20260210T090000\r\n"
        "DTEND;TZID=Europe/London:20260210T100000\r\n"
        "RDATE;TZID=America/New_York:20260212T090000\r\n"
        "RDATE;TZID=Asia/Tokyo:20260213T090000\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    # New York is UTC-5 in February and Tokyo is UTC+9 all year.
    assert spans(outcome.events) == [
        (utc(2026, 2, 10, 9, 0), utc(2026, 2, 10, 10, 0)),
        (utc(2026, 2, 12, 14, 0), utc(2026, 2, 12, 15, 0)),
        (utc(2026, 2, 13, 0, 0), utc(2026, 2, 13, 1, 0)),
    ]


def test_a_rule_across_the_spring_forward_stays_at_nine_local_on_both_sides() -> None:
    # The rule recurs in wall time, so a 09:00 series is at 09:00 local on both sides of a
    # transition: 09:00Z while London is on GMT, 08:00Z once it is on BST. Expanding in absolute
    # time instead would hold the instant and move the local hour, which is a lecture at 10:00 for
    # half of a term.
    body = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\nUID:transition@example.org\r\nSUMMARY:Daily 09:00 London\r\n"
        "DTSTART;TZID=Europe/London:20260327T090000\r\n"
        "DTEND;TZID=Europe/London:20260327T100000\r\n"
        "RRULE:FREQ=DAILY;COUNT=4\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    across = Interval(utc(2026, 3, 27, 0, 0), utc(2026, 3, 31, 0, 0))

    events = parse_feed(body, horizon=across, profile=HOME).events

    # London springs forward on 29 March 2026: 01:00 GMT becomes 02:00 BST.
    assert spans(events) == [
        (utc(2026, 3, 27, 9, 0), utc(2026, 3, 27, 10, 0)),
        (utc(2026, 3, 28, 9, 0), utc(2026, 3, 28, 10, 0)),
        (utc(2026, 3, 29, 8, 0), utc(2026, 3, 29, 9, 0)),
        (utc(2026, 3, 30, 8, 0), utc(2026, 3, 30, 9, 0)),
    ]
    # The same claim in the words a publisher would use.
    assert {event.interval.start.astimezone(ZoneInfo(LONDON)).hour for event in events} == {9}


@pytest.mark.parametrize(
    ("rule", "events"),
    [
        # dateutil holds each BY list as a set of integers, so these name one member, not two or
        # three, and a position past one member selects nothing. `None` means refused.
        ("FREQ=HOURLY;BYMINUTE=0,0;BYSETPOS=2", None),
        ("FREQ=MINUTELY;BYSECOND=0,00;BYSETPOS=2", None),
        ("FREQ=HOURLY;BYMINUTE=30,030;BYSETPOS=2", None),
        ("FREQ=MINUTELY;BYSECOND=0,0,0;BYSETPOS=3", None),
        ("FREQ=HOURLY;BYMINUTE=0,0,30;BYSETPOS=3", None),
        # A list where SOME member lands is legitimate: dateutil skips the ones that do not and
        # yields for the rest, so refusing on the largest member lost a whole live series.
        ("FREQ=HOURLY;BYMINUTE=0,30;BYSETPOS=1,5", 302),
        ("FREQ=HOURLY;BYMINUTE=0,30;BYSETPOS=1,2,3,4", 604),
        ("FREQ=HOURLY;BYMINUTE=0,30;BYSETPOS=-1,-5", 302),
    ],
)
def test_a_setpos_is_read_against_the_values_dateutil_will_hold(
    rule: str, events: int | None
) -> None:
    # Two ways to get the room wrong, and each let a rule walk to year 9999 inside one call or lost
    # a rule that works. The room is the count of DISTINCT VALUES, because that is what dateutil
    # stores; the reach is the SMALLEST position, because one member landing makes the rule yield.
    body = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:sp2@example.org\r\n"
        "DTSTART:20260210T100000Z\r\nDTEND:20260210T103000Z\r\n"
        f"RRULE:{rule}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    if events is None:
        assert [item.kind for item in outcome.rejected] == [UNPARSEABLE_RECURRENCE]
        assert "produces nothing" in outcome.rejected[0].detail
    else:
        assert outcome.rejected == ()
        # The exact count, not "not empty": the guard's docstring used to quote a number for one of
        # these shapes, three drafts quoted three different ones, and none was asserted anywhere.
        assert len(outcome.events) == events


@pytest.mark.parametrize("padded", ["0" * 4302, "0" * 4301 + "1"])
def test_a_padded_rule_value_is_refused_without_the_conversion_complaining(padded: str) -> None:
    # The interpreter's conversion limit counts the CHARACTERS handed to int(), not the value, so a
    # bound on significant digits only holds if the significant digits are what gets converted. It
    # was not, so four thousand leading zeros passed the bound and the conversion raised, and the
    # panel told a publisher to change syncr's interpreter setting.
    #
    # The raw length is bounded too, because dateutil converts this string as well and whether THAT
    # succeeds depends on the interpreter's limit. Without it, one of these values meant 1 to syncr
    # and meant a refusal to dateutil, so the same feed answered two ways depending on how the
    # process was started. Which is why this module is also run at three settings of that limit.
    body = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:pad@example.org\r\n"
        "DTSTART:20260210T100000Z\r\nDTEND:20260210T110000Z\r\n"
        f"RRULE:FREQ=DAILY;INTERVAL={padded}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert [item.kind for item in outcome.rejected] == [UNPARSEABLE_RECURRENCE]
    detail = outcome.rejected[0].detail
    assert "set_int_max_str_digits" not in detail
    assert "INTERVAL" in detail


# The horizon around the spring-forward transition the gap body sits in.
_TRANSITION = Interval(
    datetime(2026, 3, 28, 0, 0, tzinfo=UTC), datetime(2026, 3, 31, 0, 0, tzinfo=UTC)
)


def test_two_occurrences_sharing_one_instant_keep_their_own_replacements() -> None:
    # A wall time inside a spring-forward gap resolves onto the same instant as the real wall time
    # an hour later, so an hourly series has two occurrences at one instant. Keyed on the instant,
    # one override was placed on BOTH of them, giving one component two events and two identities,
    # and a pair of overrides collapsed to one with the other counted as a duplicate revision of it.
    outcome = parse_feed(SPRING_FORWARD_GAP, horizon=_TRANSITION, profile=HOME)

    # A list of pairs rather than a mapping by title: keyed by title, a component placed TWICE
    # collapses into one entry and the assertion cannot see the defect it was written for.
    moved = sorted(
        (event.title, event.interval.start)
        for event in outcome.events
        if event.title.startswith("Moved")
    )
    assert moved == [
        ("Moved from the gap hour", utc(2026, 3, 29, 18, 0)),
        ("Moved from the hour after", utc(2026, 3, 29, 19, 0)),
    ]
    assert len(outcome.events) == 4
    assert len({event.uid for event in outcome.events}) == 4
    assert outcome.overrides_applied == 2
    assert outcome.duplicates_discarded == 0


def test_a_cancellation_in_the_gap_does_not_suppress_the_hour_after_it() -> None:
    # The same collision on the cancellation path. The tombstone names the gap wall; the occurrence
    # an hour later shares its instant and must keep its own event.
    body = SPRING_FORWARD_GAP.replace(
        "SUMMARY:Moved from the gap hour\r\n",
        "STATUS:CANCELLED\r\nSUMMARY:Cancelled in the gap\r\n",
    )

    outcome = parse_feed(body, horizon=_TRANSITION, profile=HOME)

    titles = sorted(event.title for event in outcome.events)
    assert titles == ["Hourly across the gap", "Hourly across the gap", "Moved from the hour after"]


def test_one_replacement_cannot_be_placed_on_both_occurrences_of_a_shared_instant() -> None:
    # The narrow shape the cross-form fallback opens: ONE override, and two occurrences sharing its
    # instant. The one whose own wall it names takes it; the other must not be offered it again, or
    # a single component becomes two hours of hard occupancy under two identities.
    body = SPRING_FORWARD_GAP.replace(
        "BEGIN:VEVENT\r\nUID:gap@example.org\r\nSUMMARY:Moved from the hour after\r\n"
        "RECURRENCE-ID;TZID=Europe/London:20260329T023000\r\n"
        "DTSTART;TZID=Europe/London:20260329T200000\r\n"
        "DTEND;TZID=Europe/London:20260329T205500\r\nEND:VEVENT\r\n",
        "",
    )

    outcome = parse_feed(body, horizon=_TRANSITION, profile=HOME)

    moved = [event for event in outcome.events if event.title.startswith("Moved")]
    assert len(moved) == 1
    assert moved[0].interval.start == utc(2026, 3, 29, 18, 0)
    # The occurrence that shares the instant keeps its own event rather than a copy of the override.
    assert sorted(event.title for event in outcome.events) == [
        "Hourly across the gap",
        "Hourly across the gap",
        "Hourly across the gap",
        "Moved from the gap hour",
    ]


def test_a_feed_cut_short_does_not_blame_a_recurrence_it_does_not_have() -> None:
    # Two ordinary meetings, no RRULE anywhere. Reported under the recurrence class, this reads to a
    # user as a rule problem in events that carry no rule, and the action is different: every other
    # class is the publisher's to fix, and this one is syncr declining to spend more time.
    body = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\nUID:plain-1@example.org\r\nSUMMARY:Standup\r\n"
        "DTSTART:20260210T090000Z\r\nDTEND:20260210T093000Z\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:plain-2@example.org\r\nSUMMARY:Review\r\n"
        "DTSTART:20260211T090000Z\r\nDTEND:20260211T100000Z\r\nEND:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME, budget=0.0)

    assert [item.kind for item in outcome.rejected] == [READ_BUDGET_SPENT, READ_BUDGET_SPENT]
    assert all("recurrence" not in item.detail for item in outcome.rejected)


@pytest.mark.parametrize(
    "rule",
    [
        # A position padded past what any guard's predicate would read. The predicate that judged
        # readability was consumed as a REFUSAL by one caller and as a FILTER by two others, so
        # tightening it made these skip the value they were meant to judge instead of refusing it.
        "FREQ=HOURLY;BYMINUTE=0;BYSETPOS=000000000002",
        "FREQ=HOURLY;BYMINUTE=0;BYSETPOS=+000000000002",
        "FREQ=HOURLY;BYMINUTE=0;BYSETPOS=-000000000002",
        "FREQ=MINUTELY;BYSECOND=0;BYSETPOS=000000000002",
        "FREQ=SECONDLY;BYSETPOS=000000000002",
        # And a padded SET MEMBER, which inflated the room the position is judged against.
        "FREQ=HOURLY;BYMINUTE=30,000000000030;BYSETPOS=2",
    ],
)
def test_a_padded_rule_member_cannot_walk_past_the_guard_that_reads_it(rule: str) -> None:
    # Each of these stalled for between a minute and days in one dateutil call, which is past what
    # MAX_PARSE_SECONDS can see: that bound is checked BETWEEN components, so one component overruns
    # it by however long the call takes.
    body = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:pad2@example.org\r\n"
        "DTSTART:20260210T100000Z\r\nDTEND:20260210T103000Z\r\n"
        f"RRULE:{rule}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert outcome.events == ()
    assert [item.kind for item in outcome.rejected] == [UNPARSEABLE_RECURRENCE]


@pytest.mark.parametrize(
    ("padded", "plain"),
    [
        # Padding is not an error. RFC 5545's digit grammar permits it, and a publisher who writes
        # it means the number, so a padded rule has to answer exactly as its plain spelling does
        # while the shapes above are refused.
        ("FREQ=DAILY;INTERVAL=000000000001", "FREQ=DAILY;INTERVAL=1"),
        ("FREQ=DAILY;COUNT=000000000003", "FREQ=DAILY;COUNT=3"),
        ("FREQ=HOURLY;BYMINUTE=00,030;BYSETPOS=2", "FREQ=HOURLY;BYMINUTE=0,30;BYSETPOS=2"),
    ],
)
def test_a_padded_value_a_publisher_means_is_still_read(padded: str, plain: str) -> None:
    def events_of(rule: str) -> list[datetime]:
        body = (
            "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:pad3@example.org\r\n"
            "DTSTART:20260210T100000Z\r\nDTEND:20260210T103000Z\r\n"
            f"RRULE:{rule}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        outcome = parse_feed(body, horizon=HORIZON, profile=HOME)
        assert outcome.rejected == ()
        return [event.interval.start for event in outcome.events]

    assert events_of(padded) == events_of(plain) != []


@pytest.mark.parametrize("part", ["INTERVAL", "COUNT", "BYSETPOS", "BYSECOND", "BYMONTHDAY"])
def test_every_rule_property_is_bounded_for_length_not_just_the_guarded_ones(part: str) -> None:
    # The bound is a pass over the rule rather than a predicate inside one guard, because dateutil
    # reads properties syncr has no opinion on: COUNT was unbounded while INTERVAL was refused, and
    # both are converted by the same library under the same interpreter limit.
    body = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:pad4@example.org\r\n"
        "DTSTART:20260210T100000Z\r\nDTEND:20260210T110000Z\r\n"
        f"RRULE:FREQ=DAILY;{part}={'0' * 4302}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert [item.kind for item in outcome.rejected] == [UNPARSEABLE_RECURRENCE]
    detail = outcome.rejected[0].detail
    assert f"{part}" in detail
    assert "4302-character" in detail
    assert "set_int_max_str_digits" not in detail


@pytest.mark.parametrize(
    ("kept", "expected"),
    [
        # The gap wall is expanded FIRST, so this is the direction a used-once check on "already
        # applied" happens to answer.
        ("20260329T013000", "Moved from the gap hour"),
        # And this is the direction it missed: the replacement belongs to an occurrence expanded
        # LATER, so the gap occurrence reached the index first and took it. One component was then
        # placed twice, on two identities, and the master's own occurrence was deleted.
        ("20260329T023000", "Moved from the hour after"),
    ],
)
def test_a_replacement_belongs_to_the_occurrence_naming_its_wall_whichever_expands_first(
    kept: str, expected: str
) -> None:
    dropped = "20260329T023000" if kept == "20260329T013000" else "20260329T013000"
    body = "\r\n".join(line for line in SPRING_FORWARD_GAP.split("\r\n") if dropped not in line)
    # Drop the whole component whose RECURRENCE-ID was removed, leaving one override.
    body = body.replace(
        "BEGIN:VEVENT\r\nUID:gap@example.org\r\nSUMMARY:Moved from the gap hour\r\n"
        "DTSTART;TZID=Europe/London:20260329T190000\r\n"
        "DTEND;TZID=Europe/London:20260329T195500\r\nEND:VEVENT\r\n",
        "",
    ).replace(
        "BEGIN:VEVENT\r\nUID:gap@example.org\r\nSUMMARY:Moved from the hour after\r\n"
        "DTSTART;TZID=Europe/London:20260329T200000\r\n"
        "DTEND;TZID=Europe/London:20260329T205500\r\nEND:VEVENT\r\n",
        "",
    )

    outcome = parse_feed(body, horizon=_TRANSITION, profile=HOME)

    moved = [event for event in outcome.events if event.title == expected]
    assert len(moved) == 1
    assert len(outcome.events) == 4
    assert len({event.uid for event in outcome.events}) == 4
    assert outcome.overrides_applied == 1


def test_a_cancellation_suppresses_one_occurrence_when_two_share_its_instant() -> None:
    # The same direction on the cancellation path: a tombstone naming the LATER of two occurrences
    # that share an instant suppressed both of them, so an hour the feed still asserts disappeared.
    body = SPRING_FORWARD_GAP.replace(
        "BEGIN:VEVENT\r\nUID:gap@example.org\r\nSUMMARY:Moved from the gap hour\r\n"
        "RECURRENCE-ID;TZID=Europe/London:20260329T013000\r\n"
        "DTSTART;TZID=Europe/London:20260329T190000\r\n"
        "DTEND;TZID=Europe/London:20260329T195500\r\nEND:VEVENT\r\n",
        "",
    ).replace(
        "SUMMARY:Moved from the hour after\r\n",
        "STATUS:CANCELLED\r\nSUMMARY:Cancelled the hour after\r\n",
    )

    outcome = parse_feed(body, horizon=_TRANSITION, profile=HOME)

    assert sorted(event.interval.start for event in outcome.events) == [
        utc(2026, 3, 29, 0, 30),
        utc(2026, 3, 29, 1, 30),
        utc(2026, 3, 29, 2, 30),
    ]


@pytest.mark.parametrize(
    "rule",
    [
        # int() accepts a PEP 515 underscore and str.isdecimal does not, so a readability predicate
        # that resembles int() rather than BEING int() dropped the position instead of judging it:
        # the guard concluded "no position" and dateutil, which converts with int(), walked.
        "FREQ=HOURLY;BYMINUTE=0;BYSETPOS=2_0",
        "FREQ=MINUTELY;BYSETPOS=1_0",
        "FREQ=SECONDLY;BYMINUTE=0;BYSETPOS=2_0",
    ],
)
def test_a_separator_a_publisher_can_write_cannot_walk_past_the_guard(rule: str) -> None:
    body = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:sep@example.org\r\n"
        "DTSTART:20260210T100000Z\r\nDTEND:20260210T103000Z\r\n"
        f"RRULE:{rule}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert outcome.events == ()
    assert [item.kind for item in outcome.rejected] == [UNPARSEABLE_RECURRENCE]


def test_a_separator_in_a_set_member_reads_as_the_number_dateutil_reads() -> None:
    # The paired direction of the same disagreement. Dropping an unreadable member SHRANK the room,
    # so this rule was refused while dateutil would have expanded it. One accept-set disagreement,
    # two opposite failures, which is why the predicate is now int() itself.
    def events_of(rule: str) -> list[datetime]:
        body = (
            "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:sep2@example.org\r\n"
            "DTSTART:20260210T100000Z\r\nDTEND:20260210T103000Z\r\n"
            f"RRULE:{rule}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        outcome = parse_feed(body, horizon=HORIZON, profile=HOME)
        assert outcome.rejected == ()
        return [event.interval.start for event in outcome.events]

    assert (
        events_of("FREQ=HOURLY;BYMINUTE=0,2_0;BYSETPOS=2")
        == events_of("FREQ=HOURLY;BYMINUTE=0,20;BYSETPOS=2")
        != []
    )


@pytest.mark.parametrize(
    "rule",
    [
        # A value outside the range RFC 5545 gives its property can never match, so the rule yields
        # nothing while the expander walks looking for it. One of these did not return in twenty
        # minutes.
        "FREQ=SECONDLY;BYMONTHDAY=53;BYHOUR=2",
        "FREQ=MINUTELY;BYMONTH=13",
        "FREQ=SECONDLY;BYHOUR=24",
        "FREQ=DAILY;BYYEARDAY=400",
        "FREQ=DAILY;BYWEEKNO=54",
        # RFC 5545 gives a signed form to four properties and not to these, so comparing a magnitude
        # admitted the negative of an unsigned one. BYMONTH=-1 is two characters, and -1 is the
        # CORRECT idiom on the four that do count backwards, so copying it across is one slip.
        "FREQ=SECONDLY;BYMONTH=-1;BYHOUR=2",
        "FREQ=SECONDLY;BYHOUR=-1",
        "FREQ=SECONDLY;BYMINUTE=-1",
        # Zero is outside every one of these ranges, and dateutil accepts BYMONTHDAY=0.
        "FREQ=MONTHLY;BYMONTHDAY=0",
        "FREQ=DAILY;BYWEEKNO=0",
        # A magnitude wider than the eleven significant digits syncr will ACT on. Routing the range
        # check through that predicate made it skip exactly the values most obviously out of range.
        "FREQ=SECONDLY;BYMONTHDAY=999999999999;BYHOUR=2",
        "FREQ=SECONDLY;BYYEARDAY=999999999999;BYHOUR=2",
        "FREQ=SECONDLY;BYWEEKNO=0000000000999999999999;BYHOUR=2",
        # And a position past every set a daily period can hold, stated 365 times: two seconds each,
        # measured at 160 seconds in one call, at the frequency the guard used to leave alone.
        "FREQ=DAILY;BYSETPOS=2",
        "FREQ=DAILY;BYHOUR=9,10;BYSETPOS=3",
    ],
)
def test_a_rule_that_can_never_match_is_refused_rather_than_walked(rule: str) -> None:
    body = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:never@example.org\r\n"
        "DTSTART:20260210T100000Z\r\nDTEND:20260210T110000Z\r\n"
        f"RRULE:{rule}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert outcome.events == ()
    assert [item.kind for item in outcome.rejected] == [UNPARSEABLE_RECURRENCE]


@pytest.mark.parametrize(
    ("rule", "events"),
    [
        # The accepting side of both bounds, so they are shown to refuse a property rather than a
        # shape. Every one of these is a rule a real publisher emits.
        ("FREQ=DAILY;BYHOUR=9,10;BYSETPOS=2", 13),
        ("FREQ=DAILY;BYSETPOS=1", 13),
        ("FREQ=DAILY;BYSETPOS=-1", 13),
        ("FREQ=MONTHLY;BYMONTHDAY=-31", 0),
        ("FREQ=MONTHLY;BYDAY=-1FR", 0),
        ("FREQ=DAILY;BYHOUR=0,23;BYMINUTE=0,59", 50),
    ],
)
def test_a_rule_inside_every_range_is_still_expanded(rule: str, events: int) -> None:
    body = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:ok@example.org\r\n"
        "DTSTART:20260210T100000Z\r\nDTEND:20260210T110000Z\r\n"
        f"RRULE:{rule}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert outcome.rejected == ()
    assert len(outcome.events) == events


@pytest.mark.parametrize(
    "rule",
    [
        # Every value inside the range its property allows, including the signed forms on the four
        # properties RFC 5545 gives one to. None of these may be refused.
        "FREQ=MONTHLY;BYMONTHDAY=-1",
        "FREQ=MONTHLY;BYMONTHDAY=-31",
        "FREQ=MONTHLY;BYMONTHDAY=1,-1",
        "FREQ=YEARLY;BYYEARDAY=-366",
        "FREQ=YEARLY;BYWEEKNO=-53",
        "FREQ=YEARLY;BYWEEKNO=1,53",
        "FREQ=MONTHLY;BYSETPOS=-1;BYDAY=MO,TU,WE,TH,FR",
        "FREQ=WEEKLY;BYSETPOS=-1;BYDAY=MO,FR",
        "FREQ=DAILY;BYHOUR=0,23",
        "FREQ=DAILY;BYMINUTE=0,59",
        "FREQ=YEARLY;BYMONTH=1,12",
        "FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=29",
        "FREQ=DAILY;BYHOUR=8,9,10,11,12,13,14,15,16,17;BYSETPOS=10",
    ],
)
def test_a_signed_form_the_standard_allows_is_not_refused(rule: str) -> None:
    # The accepting side of the range check, and the reason it is a table of intervals rather than a
    # magnitude: -1 means "the last one" on four properties and means nothing on the other four.
    body = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:signed@example.org\r\n"
        "DTSTART:20260210T100000Z\r\nDTEND:20260210T110000Z\r\n"
        f"RRULE:{rule}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert outcome.rejected == ()


@pytest.mark.parametrize(
    "rule",
    [
        # dateutil splits a rule value on ANY whitespace unless told to unfold, and treats each
        # token as its own content line, so one space smuggles a second RRULE past guards that split
        # on ";". The first of these provably never terminates: dateutil advances by INTERVAL, and
        # zero never reaches a new value.
        "FREQ=DAILY INTERVAL=0;FREQ=DAILY",
        "FREQ=WEEKLY RRULE:FREQ=SECONDLY;BYSETPOS=300",
        "FREQ=MONTHLY;COUNT=2 RRULE:FREQ=MINUTELY;BYSECOND=1;BYSETPOS=3",
        # A tab and a newline are whitespace to dateutil's split too.
        "FREQ=DAILY\tINTERVAL=0",
        # And the same seam in a property name rather than a value.
        "FREQ=DAILY;INT ERVAL=0",
    ],
)
def test_whitespace_cannot_smuggle_a_second_rule_past_the_guards(rule: str) -> None:
    # The guards read a ";"-separated property list; dateutil reads whitespace-separated content
    # lines. Where the two grammars disagreed, syncr validated one rule and dateutil expanded a
    # different one, and every guard was bypassed at once.
    body = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:ws@example.org\r\n"
        "DTSTART:20260210T100000Z\r\nDTEND:20260210T110000Z\r\n"
        f"RRULE:{rule}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert outcome.events == ()
    assert [item.kind for item in outcome.rejected] == [UNPARSEABLE_RECURRENCE]
    detail = outcome.rejected[0].detail
    assert "whitespace" in detail
    # The publisher is shown the offending text rather than a converter's complaint.
    assert "unpack" not in detail


@pytest.mark.parametrize(
    ("rule", "events"),
    [
        # Padding around a separator is a real publisher idiom and carries no second property, so it
        # is stripped and expanded rather than costing the series. This one used to reach the panel
        # as a Python tuple-unpacking error.
        ("FREQ=WEEKLY; BYDAY=MO", 1),
        ("FREQ=WEEKLY ; BYDAY=MO", 1),
        ("FREQ=DAILY ; COUNT=3", 3),
        ("  FREQ=DAILY;COUNT=3  ", 3),
        ("FREQ=DAILY;COUNT=3;", 3),
        ("FREQ = DAILY;COUNT = 3", 3),
    ],
)
def test_separator_padding_is_stripped_rather_than_costing_the_series(
    rule: str, events: int
) -> None:
    body = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:pad5@example.org\r\n"
        "DTSTART:20260210T100000Z\r\nDTEND:20260210T110000Z\r\n"
        f"RRULE:{rule}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert outcome.rejected == ()
    assert len(outcome.events) == events


def test_a_rule_part_with_no_value_is_named_rather_than_unpacked() -> None:
    # dateutil unpacks each part into a pair, so it answers this with "not enough values to unpack",
    # which tells a publisher nothing about which property is wrong.
    body = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:nopair@example.org\r\n"
        "DTSTART:20260210T100000Z\r\nDTEND:20260210T110000Z\r\n"
        "RRULE:FREQ=DAILY;COUNT\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert [item.kind for item in outcome.rejected] == [UNPARSEABLE_RECURRENCE]
    detail = outcome.rejected[0].detail
    assert "COUNT" in detail
    assert "unpack" not in detail


@pytest.mark.parametrize(
    ("rule", "phrase"),
    [
        # A property NAME carrying a colon is a second content line to dateutil, which splits
        # `name:value` before it looks at properties at all. So `RRULE:FREQ` is the name here,
        # `FREQ` is absent, and every guard that reads FREQ declines to judge while dateutil
        # expands.
        ("RRULE:FREQ=SECONDLY;BYSETPOS=300", "second content line"),
        ("EXRULE:FREQ=DAILY;COUNT=3", "second content line"),
        # These two carry no `=` at all, so they are refused one check earlier. Both are the same
        # smuggling attempt; each keeps the message for the malformation it actually has.
        ("RDATE:20260212T090000Z", "with no value"),
        ("DTSTART:20260101T000000Z;FREQ=DAILY", "with no value"),
    ],
)
def test_a_name_carrying_a_colon_cannot_smuggle_a_second_content_line(
    rule: str, phrase: str
) -> None:
    body = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:colon@example.org\r\n"
        "DTSTART:20260210T100000Z\r\nDTEND:20260210T110000Z\r\n"
        f"RRULE:{rule}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert outcome.events == ()
    assert [item.kind for item in outcome.rejected] == [UNPARSEABLE_RECURRENCE]
    assert phrase in outcome.rejected[0].detail


def test_an_exclusion_rule_smuggled_by_a_colon_cannot_delete_the_series_silently() -> None:
    # The worst of the four forms, because it is silent rather than slow: dateutil reads EXRULE as
    # an EXCLUSION rule, so the series is removed with no rejection and no events, and the panel
    # reports a healthy feed that produced nothing.
    body = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:exrule@example.org\r\nSUMMARY:Weekly\r\n"
        "DTSTART:20260210T100000Z\r\nDTEND:20260210T110000Z\r\n"
        "RRULE:EXRULE:FREQ=DAILY;COUNT=3\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert outcome.events == ()
    assert [item.kind for item in outcome.rejected] == [UNPARSEABLE_RECURRENCE]
    assert "second content line" in outcome.rejected[0].detail


@pytest.mark.parametrize(
    "rule",
    [
        # dateutil upper-cases every rule name and value, so comparing either case-sensitively is
        # the same divergence one letter wide. A lowercase z made UNTIL a floating time to syncr and
        # a UTC one to dateutil, which refused the pair and cost the whole series.
        "FREQ=DAILY;UNTIL=20260220T000000z",
        "freq=daily;until=20260220t000000z",
        "FREQ=DAILY;until=20260220T000000Z",
    ],
)
def test_a_rule_is_read_in_the_case_dateutil_reads_it(rule: str) -> None:
    body = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:case@example.org\r\nSUMMARY:Weekly\r\n"
        "DTSTART:20260210T100000Z\r\nDTEND:20260210T110000Z\r\n"
        f"RRULE:{rule}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )

    outcome = parse_feed(body, horizon=HORIZON, profile=HOME)

    assert outcome.rejected == ()
    assert len(outcome.events) == 10
