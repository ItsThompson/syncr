"""The grammar seam: where syncr's reading of a timestamp and Python's disagree.

The ICS reader's most expensive lesson was that when syncr and a library both parse the same
string, the
divergence is one defect per rule they disagree on, not one defect. Google hands syncr its own
datetime representation and Python's ``fromisoformat`` does the arithmetic, so the axes below are
enumerated from what the two accept rather than sampled from values that looked plausible.

Each row of the table in :mod:`syncr_api.calendars.google_values` has a case here, in both
directions: what RFC 3339 permits and Python refuses, and what Python accepts and RFC 3339 forbids.
The measurements those rows record were taken against Python 3.12, which is this workspace's floor;
a test here fails rather than a docstring rotting if a future version changes one.

The dangerous divergence is the naive datetime. Python accepts one and reads it as having no zone
at all, so silently treating it as UTC would place an event up to thirteen hours from where the
provider put it, and nothing downstream could tell that from a correct answer.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from syncr_api.calendars.config import MALFORMED_VALUE, MAX_EVENT_DAYS, MISSING_DURATION
from syncr_api.calendars.google_payloads import GoogleTimePayload
from syncr_api.calendars.google_values import (
    MAX_TIMESTAMP_LENGTH,
    ReadSpan,
    UnreadableSpan,
    read_date,
    read_instant,
    read_span,
)
from syncr_domain.zones import ZoneProfile

LONDON = ZoneProfile(home_zone="Europe/London")

HOURS_IN_A_DAY = 24


def timed(value: str) -> GoogleTimePayload:
    return GoogleTimePayload(dateTime=value, timeZone="Europe/London")


def all_day(value: str) -> GoogleTimePayload:
    return GoogleTimePayload(date=value)


# --------------------------------------------------------------------------------------
# What both readers agree on
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-02-09T09:00:00Z", "2026-02-09T09:00:00+00:00"),
        ("2026-02-09T09:00:00+00:00", "2026-02-09T09:00:00+00:00"),
        ("2026-02-09T09:00:00-07:00", "2026-02-09T16:00:00+00:00"),
        ("2026-02-09T09:00:00+05:30", "2026-02-09T03:30:00+00:00"),
        # Legal, and the fraction is below the resolution an anchor is placed at.
        ("2026-02-09T09:00:00.500Z", "2026-02-09T09:00:00.500000+00:00"),
    ],
)
def test_an_rfc_3339_date_time_reads_as_the_instant_it_names(value: str, expected: str) -> None:
    read = read_instant(value)

    assert isinstance(read, datetime)
    assert read.isoformat() == expected


def test_a_lower_case_separator_and_suffix_are_accepted() -> None:
    # RFC 3339 permits both in lower case and `fromisoformat` refuses them. Refusing an event over a
    # letter is what the ICS reader's `UNTIL` defect cost, and this is the same seam one provider
    # over.
    read = read_instant("2026-02-09t09:00:00z")

    assert isinstance(read, datetime)
    assert read.isoformat() == "2026-02-09T09:00:00+00:00"


def test_more_fractional_digits_than_python_holds_are_accepted() -> None:
    # Legal, and Python truncates to microseconds. Measured rather than assumed: on 3.11 this
    # raised, so a workspace floor below 3.12 would fail here rather than in a worker tick.
    read = read_instant("2026-02-09T09:00:00.123456789Z")

    assert isinstance(read, datetime)
    assert read.isoformat() == "2026-02-09T09:00:00.123456+00:00"


# --------------------------------------------------------------------------------------
# What Python accepts and the contract does not
# --------------------------------------------------------------------------------------


def test_a_datetime_with_no_offset_is_refused_rather_than_read_as_utc() -> None:
    # THE dangerous one. `fromisoformat` accepts it and returns a naive value; reading that as UTC
    # would place an event up to thirteen hours from where the provider put it.
    read = read_instant("2026-02-09T09:00:00")

    assert isinstance(read, UnreadableSpan)
    assert read.kind == MALFORMED_VALUE
    assert "with an offset" in read.detail


@pytest.mark.parametrize(
    "value",
    [
        "20260209T090000Z",
        "2026-02-09T09:00:00+0000",
        "2026-W07-1T09:00:00Z",
        "2026-02-09 09:00:00+00:00",
        "2026-02-09T09:00Z",
        "+2026-02-09T09:00:00Z",
    ],
    ids=[
        "basic form",
        "offset without a colon",
        "week form",
        "space separator",
        "no seconds",
        "signed year",
    ],
)
def test_a_form_the_contract_does_not_state_is_refused(value: str) -> None:
    # Google documents RFC 3339 with a mandatory offset. Every value here is one Python's parser
    # accepts and the contract forbids, so accepting them would make a provider contract change
    # invisible until something downstream misplaced an event.
    read = read_instant(value)

    assert isinstance(read, UnreadableSpan)


@pytest.mark.parametrize(
    "value",
    ["20260209", "2026-W07-1", "2026-2-9", "09/02/2026"],
    ids=["basic form", "week form", "unpadded", "not iso at all"],
)
def test_a_date_form_the_contract_does_not_state_is_refused(value: str) -> None:
    read = read_date(value)

    assert isinstance(read, UnreadableSpan)


# --------------------------------------------------------------------------------------
# What the contract permits and Python refuses
# --------------------------------------------------------------------------------------


def test_a_leap_second_is_refused_and_the_reason_says_what_happened() -> None:
    # RFC 3339 permits `:60` and Python raises on it. This is the divergence in the other
    # direction: the pattern accepts the value and the arithmetic does not, so the answer is a
    # stated rejection rather than an exception out of a fetch.
    read = read_instant("2026-12-31T23:59:60Z")

    assert isinstance(read, UnreadableSpan)
    assert "not a real instant" in read.detail


@pytest.mark.parametrize(
    "value",
    ["2026-02-30T09:00:00Z", "2026-13-01T09:00:00Z", "2026-02-09T25:00:00Z"],
    ids=["a day February does not have", "a thirteenth month", "a twenty-fifth hour"],
)
def test_a_well_formed_value_that_is_not_a_real_instant_is_refused(value: str) -> None:
    read = read_instant(value)

    assert isinstance(read, UnreadableSpan)
    assert "not a real instant" in read.detail


def test_a_well_formed_date_that_is_not_a_real_day_is_refused() -> None:
    read = read_date("2026-02-30")

    assert isinstance(read, UnreadableSpan)
    assert "not a real day" in read.detail


# --------------------------------------------------------------------------------------
# Magnitudes, which are the provider's to choose
# --------------------------------------------------------------------------------------


def test_a_timestamp_wider_than_any_timestamp_is_refused_by_its_length() -> None:
    # The fraction is the only unbounded field in the grammar, so it is where a provider or a
    # hostile intermediary can spend megabytes. Bounded before the pattern runs.
    oversize = f"2026-02-09T09:00:00.{'1' * (MAX_TIMESTAMP_LENGTH * 2)}Z"

    read = read_instant(oversize)

    assert isinstance(read, UnreadableSpan)
    assert str(len(oversize)) in read.detail


def test_the_length_bound_reports_the_size_rather_than_quoting_the_value() -> None:
    oversize = f"2026-02-09T09:00:00.{'1' * 5000}Z"

    read = read_instant(oversize)

    assert isinstance(read, UnreadableSpan)
    assert oversize not in read.detail


# --------------------------------------------------------------------------------------
# The span an event occupies
# --------------------------------------------------------------------------------------


def test_a_timed_event_occupies_the_instants_the_provider_stated() -> None:
    read = read_span(timed("2026-02-09T09:00:00Z"), timed("2026-02-09T10:30:00Z"), profile=LONDON)

    assert isinstance(read, ReadSpan)
    assert read.all_day is False
    assert read.interval.total_minutes() == 90


def test_the_offset_decides_the_instant_rather_than_the_named_zone() -> None:
    # Google sends both, and only the offset is authoritative: the zone names where the event was
    # authored, which matters to recurrence expansion, and Google expands recurrence itself.
    read = read_span(
        GoogleTimePayload(dateTime="2026-02-09T09:00:00-05:00", timeZone="Asia/Tokyo"),
        GoogleTimePayload(dateTime="2026-02-09T10:00:00-05:00", timeZone="Asia/Tokyo"),
        profile=LONDON,
    )

    assert isinstance(read, ReadSpan)
    assert read.interval.start.isoformat() == "2026-02-09T14:00:00+00:00"


def test_an_all_day_event_occupies_whole_local_days() -> None:
    # `end.date` is exclusive, exactly as an ICS DTEND is, so one day is stated as two dates.
    read = read_span(all_day("2026-02-09"), all_day("2026-02-10"), profile=LONDON)

    assert isinstance(read, ReadSpan)
    assert read.all_day is True
    assert read.interval.duration.total_seconds() / 3600 == HOURS_IN_A_DAY


def test_an_all_day_event_over_a_transition_is_as_long_as_those_days_were() -> None:
    read = read_span(all_day("2026-03-29"), all_day("2026-03-30"), profile=LONDON)

    assert isinstance(read, ReadSpan)
    assert read.interval.duration.total_seconds() / 3600 == HOURS_IN_A_DAY - 1


def test_an_all_day_event_whose_end_does_not_outlast_its_start_is_rejected() -> None:
    # Google states a one-day event as start + 1, so an equal pair is a provider or a proxy having
    # rewritten it, and syncr cannot reason about occupancy that occupies nothing.
    read = read_span(all_day("2026-02-09"), all_day("2026-02-09"), profile=LONDON)

    assert isinstance(read, UnreadableSpan)
    assert read.kind == MISSING_DURATION


def test_a_zero_length_timed_event_is_rejected_for_the_same_reason() -> None:
    read = read_span(timed("2026-02-09T09:00:00Z"), timed("2026-02-09T09:00:00Z"), profile=LONDON)

    assert isinstance(read, UnreadableSpan)
    assert read.kind == MISSING_DURATION


def test_an_inverted_timed_event_is_rejected() -> None:
    read = read_span(timed("2026-02-09T10:00:00Z"), timed("2026-02-09T09:00:00Z"), profile=LONDON)

    assert isinstance(read, UnreadableSpan)
    assert read.kind == MISSING_DURATION


def test_an_event_with_no_start_or_no_end_is_rejected_for_having_no_duration() -> None:
    read = read_span(None, timed("2026-02-09T10:00:00Z"), profile=LONDON)

    assert isinstance(read, UnreadableSpan)
    assert read.kind == MISSING_DURATION


def test_an_event_stated_in_two_different_forms_is_refused_as_ambiguous() -> None:
    read = read_span(all_day("2026-02-09"), timed("2026-02-09T10:00:00Z"), profile=LONDON)

    assert isinstance(read, UnreadableSpan)
    assert read.kind == MALFORMED_VALUE
    assert "different forms" in read.detail


@pytest.mark.parametrize("days", [MAX_EVENT_DAYS + 1, MAX_EVENT_DAYS * 3])
def test_an_all_day_span_longer_than_syncr_can_place_is_refused(days: int) -> None:
    # A magnitude is not a syntax error: these dates parse perfectly and then overflow the
    # arithmetic that would place them, so they are refused where the magnitude is read.
    end = date(1, 1, 1) + __import__("datetime").timedelta(days=days)

    read = read_span(all_day("0001-01-01"), all_day(end.isoformat()), profile=LONDON)

    assert isinstance(read, UnreadableSpan)
    assert read.kind == MALFORMED_VALUE


def test_a_timed_span_longer_than_syncr_can_place_is_refused() -> None:
    read = read_span(timed("0001-01-01T00:00:00Z"), timed("9999-12-31T23:00:00Z"), profile=LONDON)

    assert isinstance(read, UnreadableSpan)
    assert read.kind == MALFORMED_VALUE


def test_a_span_at_the_far_end_of_the_representable_range_does_not_raise() -> None:
    # The no-raise contract has to hold for a value the pattern accepts, whatever the arithmetic
    # underneath it thinks: an escape here is a lost worker tick rather than one lost event.
    read = read_span(all_day("9999-12-30"), all_day("9999-12-31"), profile=LONDON)

    assert isinstance(read, ReadSpan | UnreadableSpan)
