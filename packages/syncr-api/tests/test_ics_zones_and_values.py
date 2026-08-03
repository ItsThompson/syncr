"""Zone aliasing, value parsing, and instant resolution: the three readings a feed forces.

Stated against real zones and real dates, never a mocked offset. The two daylight-saving
rules belong to the domain and are asserted there; what is asserted here is that this
package routes each of the three zone kinds to the right zone, which is the decision that
puts an event in the wrong hour when it is wrong.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from syncr_api.calendars.config import MAX_EVENT_DAYS
from syncr_api.calendars.ics_errors import MalformedValue, UnmappedZone
from syncr_api.calendars.ics_times import resolve, resolve_day_span, resolve_span, zone_for
from syncr_api.calendars.ics_values import (
    MAX_MAGNITUDE_DIGITS,
    IcsTime,
    ZoneKind,
    parse_duration,
    parse_sequence,
    parse_time,
)
from syncr_api.calendars.ics_zones import TZID_ALIASES, resolve_tzid
from syncr_domain.zones import TravelOverride, UnknownZoneError, ZoneProfile, resolve_zone
from tests.ics_construction_sites import PAST_INT_CONVERSION

LONDON = "Europe/London"
TOKYO = "Asia/Tokyo"

# Europe/London, 2026: 01:00 becomes 02:00 on 29 March, and 02:00 repeats on 25 October.
SPRING_FORWARD = datetime(2026, 3, 29)  # noqa: DTZ001 - a wall date, as a feed carries it
FALL_BACK = datetime(2026, 10, 25)  # noqa: DTZ001 - a wall date, as a feed carries it

HOME = ZoneProfile(home_zone=LONDON)
TRAVELLING = ZoneProfile(
    home_zone=LONDON,
    travel_overrides=(
        TravelOverride(start_date=FALL_BACK.date(), end_date=FALL_BACK.date(), zone=TOKYO),
    ),
)


def timed(text: str, **params: str) -> IcsTime:
    return parse_time(text, params=tuple((key.upper(), value) for key, value in params.items()))


# --------------------------------------------------------------------------------
# The alias table
# --------------------------------------------------------------------------------


def test_a_windows_zone_name_maps_through_the_table() -> None:
    assert resolve_tzid("GMT Standard Time") == LONDON
    assert resolve_tzid("  romance standard time  ") == "Europe/Paris"


def test_an_iana_key_needs_no_alias_entry() -> None:
    assert resolve_tzid(LONDON) == LONDON
    # A tz-database link resolves itself, which is why the table carries no legacy aliases.
    assert resolve_tzid("GB") == "GB"


def test_an_unmapped_zone_rejects_the_event_and_names_the_zone() -> None:
    with pytest.raises(UnmappedZone) as raised:
        resolve_tzid("Mars Standard Time")

    assert raised.value.tzid == "Mars Standard Time"
    assert "Mars Standard Time" in str(raised.value)


def test_an_unmapped_zone_is_the_domains_own_rejection() -> None:
    # A caller already handling an unknown zone handles this too, rather than needing to
    # know that ICS ingest invented a second error for the same condition.
    with pytest.raises(UnknownZoneError):
        resolve_tzid("Not A Zone")


def test_every_alias_value_is_a_real_zone() -> None:
    # A typo in the table would place events in a zone that does not exist, and the failure
    # would surface as a rejected event rather than as a bad table.
    for key, iana in TZID_ALIASES.items():
        assert resolve_zone(iana) is not None, key


def test_no_alias_key_is_one_the_tz_database_already_answers() -> None:
    # The table is consulted only after direct resolution fails, so such a row would be
    # dead. `GB`, `Eire`, `GMT` and `Europe/Belfast` are the tempting ones: all four are tz
    # links and all four resolve without the table.
    shadowed = [key for key in TZID_ALIASES if _resolves_directly(key)]

    assert shadowed == []


def _resolves_directly(key: str) -> bool:
    try:
        resolve_zone(key)
    except UnknownZoneError:
        return False
    return True


# --------------------------------------------------------------------------------
# Values
# --------------------------------------------------------------------------------


def test_a_z_suffix_is_an_instant_and_outranks_a_tzid() -> None:
    # RFC 5545 forbids both together. A publisher that sends both has stated the instant in
    # the value, so the value wins rather than the parameter.
    moment = timed("20260209T090000Z", tzid="Asia/Tokyo")

    assert moment.kind is ZoneKind.UTC
    assert moment.zone is None
    assert resolve(moment, HOME) == datetime(2026, 2, 9, 9, 0, tzinfo=UTC)


def test_a_named_tzid_resolves_in_the_zone_the_feed_named() -> None:
    moment = timed("20260709T090000", tzid="Europe/London")

    assert moment.kind is ZoneKind.NAMED
    # July: London is UTC+1, so 09:00 local is 08:00Z.
    assert resolve(moment, HOME) == datetime(2026, 7, 9, 8, 0, tzinfo=UTC)


def test_a_floating_time_resolves_in_the_zone_active_on_that_date() -> None:
    moment = timed("20261025T090000")

    assert moment.kind is ZoneKind.FLOATING
    assert zone_for(moment, moment.on, TRAVELLING) == TOKYO
    # Tokyo is UTC+9 and has no daylight saving, so 09:00 local is 00:00Z.
    assert resolve(moment, TRAVELLING) == datetime(2026, 10, 25, 0, 0, tzinfo=UTC)


def test_a_named_zone_ignores_the_travel_override() -> None:
    # A lecture published in London is at 09:00 London whichever zone the user is in.
    moment = timed("20261025T090000", tzid=LONDON)

    assert zone_for(moment, moment.on, TRAVELLING) == LONDON


def test_a_value_date_is_an_all_day_event_and_so_is_a_bare_date() -> None:
    declared = timed("20260209", value="DATE")
    bare = timed("20260209")

    assert declared.all_day is True
    # iCloud omits the VALUE parameter, so the value's own shape has to decide.
    assert bare.all_day is True
    assert declared.wall == bare.wall


def test_a_timed_event_at_midnight_is_not_an_all_day_event() -> None:
    assert timed("20260209T000000Z").all_day is False


@pytest.mark.parametrize(
    "value",
    ["20260231T090000Z", "20260209T250000", "2026-02-09T09:00:00Z", "20260209T0900", "", "TBC"],
    ids=["no such day", "hour 25", "extended form", "no seconds", "empty", "prose"],
)
def test_an_unreadable_value_is_rejected_rather_than_guessed(value: str) -> None:
    with pytest.raises(MalformedValue):
        timed(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("PT1H", timedelta(hours=1)),
        ("PT45M", timedelta(minutes=45)),
        ("P1D", timedelta(days=1)),
        ("P2W", timedelta(weeks=2)),
        ("PT1H30M", timedelta(hours=1, minutes=30)),
        ("P1DT2H3M4S", timedelta(days=1, hours=2, minutes=3, seconds=4)),
    ],
)
def test_a_duration_reads_every_form_the_standard_defines(value: str, expected: timedelta) -> None:
    assert parse_duration(value) == expected


@pytest.mark.parametrize("value", ["-PT1H", "PT0S", "P", "1H", "PT1X"])
def test_a_duration_that_is_not_positive_is_rejected(value: str) -> None:
    # An event that ends before it starts says nothing about occupancy, which is the same
    # failure a missing DTEND is.
    with pytest.raises(MalformedValue):
        parse_duration(value)


@pytest.mark.parametrize(
    "value",
    ["P9999999999D", "P999999999W", f"P{MAX_EVENT_DAYS + 1}D"],
    ids=["days past the constructor", "weeks", "one day past the bound"],
)
def test_a_duration_longer_than_syncr_will_place_is_rejected_by_name(value: str) -> None:
    # A magnitude is not a syntax error: each of these parses perfectly and then overflows the
    # arithmetic that would place it. Bounding it HERE rather than catching the overflow later is
    # what lets the rejection name the property and the bound, which is what the panel renders.
    with pytest.raises(MalformedValue) as raised:
        parse_duration(value)

    assert str(MAX_EVENT_DAYS) in str(raised.value)
    assert "syncr will place" in str(raised.value)


@pytest.mark.parametrize(
    "digits",
    [PAST_INT_CONVERSION, "9" * (MAX_MAGNITUDE_DIGITS + 1)],
    ids=["past the interpreter's conversion limit", "one digit past the bound's own width"],
)
def test_a_duration_component_is_bounded_by_its_length_before_it_is_converted(digits: str) -> None:
    # The step a bound on the total cannot see. `int()` on a string refuses more than
    # `sys.get_int_max_str_digits()` digits, and it raises BEFORE any sum exists, so the magnitude
    # bound never runs. `ValueError` is neither a rejection nor in the unrepresentable set, so
    # without a length bound here it escapes the adapter with no sync state to write.
    with pytest.raises(MalformedValue) as raised:
        parse_duration(f"PT{digits}S")

    # The same bound named the same way, whichever step refused the value.
    assert str(MAX_EVENT_DAYS) in str(raised.value)
    assert "syncr will place" in str(raised.value)


def test_the_length_bound_never_refuses_a_duration_the_magnitude_bound_would_allow() -> None:
    # The accepting side, and the reason the length bound is derived rather than chosen. The widest
    # group the magnitude bound can accept is MAX_EVENT_DAYS expressed in seconds, so that is the
    # value the length bound has to admit.
    widest = MAX_EVENT_DAYS * 24 * 60 * 60

    assert parse_duration(f"PT{widest}S").days == MAX_EVENT_DAYS
    assert len(str(widest)) <= MAX_MAGNITUDE_DIGITS


@pytest.mark.parametrize(
    "padded",
    ["PT00000000030S", "PT0000000000000000030S", f"P{'0' * 40}{MAX_EVENT_DAYS}D"],
    ids=["just inside the width", "far past it", "a padded value at the bound"],
)
def test_leading_zeros_do_not_count_toward_the_length_bound(padded: str) -> None:
    # RFC 5545's `\d+` permits leading zeros, so a padded group names a small number written wide.
    # Counting the characters rather than the significant digits refuses thirty seconds, and says so
    # in a message about a bound the value is nowhere near.
    assert parse_duration(padded).total_seconds() > 0


def test_a_padded_group_past_the_interpreters_limit_is_a_rejection_rather_than_a_fault() -> None:
    # The two counts a reader can confuse. The bound is on the SIGNIFICANT digits, so the padded
    # value below is well inside it, while the string `int()` would see is past what the interpreter
    # will convert. Bounding one and converting the other lets `ValueError` escape the adapter,
    # which is the whole defect this bound exists to answer.
    padded = "PT" + "0" * (sys.get_int_max_str_digits() + 1) + "1S"

    assert parse_duration(padded).total_seconds() == 1


def test_the_bound_refuses_before_the_interpreter_would() -> None:
    # Which is the point of owning it. `sys.get_int_max_str_digits()` is settable through
    # PYTHONINTMAXSTRDIGITS, so a boundary that relied on the interpreter's limit would move with
    # the deployment. Asserted by behaviour rather than by comparing two numbers: a group between
    # the two is refused by NAME, with the property and the bound stated.
    between = "9" * (MAX_MAGNITUDE_DIGITS + 1)
    assert len(between) < sys.get_int_max_str_digits()

    with pytest.raises(MalformedValue) as raised:
        parse_duration(f"PT{between}S")

    assert "syncr will place" in str(raised.value)


def test_a_duration_at_the_bound_is_accepted() -> None:
    # A multi-year all-day event is legitimate, which is why this bound is not the projection
    # horizon.
    assert parse_duration(f"P{MAX_EVENT_DAYS}D").days == MAX_EVENT_DAYS


def test_the_magnitude_bound_covers_every_unit_through_one_sum() -> None:
    # Once the groups are integers, one bound on their sum covers all five units: a mixed value
    # cannot slip past by splitting itself between them. This is a claim about the SUM only. The
    # conversion that produces those integers is bounded separately, by length, above.
    with pytest.raises(MalformedValue):
        parse_duration(f"P{MAX_EVENT_DAYS}DT24H")


def test_an_unreadable_sequence_is_rejected_rather_than_read_as_zero() -> None:
    # SEQUENCE decides which of two duplicate UIDs wins, so defaulting a bad one to zero
    # would let an older revision beat a newer one.
    assert parse_sequence(" 3 ") == 3
    with pytest.raises(MalformedValue):
        parse_sequence("three")


# --------------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------------


def test_a_recurrence_keeps_its_wall_time_across_a_spring_forward() -> None:
    # The reason expansion happens in wall time: a 09:00 lecture is at 09:00 local before
    # and after the transition, which is two different instants.
    series = timed("20260302T090000", tzid=LONDON)

    before = resolve(series, HOME, wall=datetime(2026, 3, 23, 9, 0))  # noqa: DTZ001
    after = resolve(series, HOME, wall=datetime(2026, 3, 30, 9, 0))  # noqa: DTZ001

    assert before == datetime(2026, 3, 23, 9, 0, tzinfo=UTC)
    assert after == datetime(2026, 3, 30, 8, 0, tzinfo=UTC)
    assert after.astimezone(ZoneInfo(LONDON)).hour == 9


def test_an_occurrence_spanning_a_gap_keeps_the_length_the_publisher_stated() -> None:
    # Resolving a wall-clock END independently inverts here: 01:30 shifts to 02:30 while
    # 02:00 does not move. The absolute span cannot invert.
    series = timed("20260329T013000", tzid=LONDON)

    span = resolve_span(
        series, HOME, wall=SPRING_FORWARD.replace(hour=1, minute=30), span=timedelta(minutes=30)
    )

    assert span.total_minutes() == 30
    assert span.start == datetime(2026, 3, 29, 1, 30, tzinfo=UTC)


def test_an_all_day_event_occupies_the_whole_local_day() -> None:
    day = timed("20260209", value="DATE")

    span = resolve_day_span(day, HOME, wall=day.wall, days=1)

    assert span.start == datetime(2026, 2, 9, 0, 0, tzinfo=UTC)
    assert span.total_minutes() == 24 * 60


def test_an_all_day_event_on_a_transition_day_is_as_long_as_that_day_was() -> None:
    # 23 hours in spring and 25 in autumn. A fixed 1440 would put the following day's
    # first hour inside the wrong day.
    spring = timed(SPRING_FORWARD.strftime("%Y%m%d"), value="DATE")
    autumn = timed(FALL_BACK.strftime("%Y%m%d"), value="DATE")

    assert resolve_day_span(spring, HOME, wall=spring.wall, days=1).total_minutes() == 23 * 60
    assert resolve_day_span(autumn, HOME, wall=autumn.wall, days=1).total_minutes() == 25 * 60


def test_a_multi_day_all_day_event_covers_every_day_it_names() -> None:
    day = timed("20260209", value="DATE")

    assert resolve_day_span(day, HOME, wall=day.wall, days=3).total_minutes() == 3 * 24 * 60


def test_an_all_day_event_of_no_days_is_rejected() -> None:
    day = timed("20260209", value="DATE")

    with pytest.raises(MalformedValue):
        resolve_day_span(day, HOME, wall=day.wall, days=0)


def test_a_wall_time_carrying_a_zone_is_not_an_ics_wall_time() -> None:
    # The invariant that keeps recurrence expansion from drifting: an aware datetime here
    # would already have resolved a zone, and expansion would then apply a second one.
    with pytest.raises(MalformedValue):
        IcsTime(
            wall=datetime(2026, 2, 9, 9, 0, tzinfo=UTC), kind=ZoneKind.UTC, zone=None, all_day=False
        )


def test_a_zone_kind_and_a_zone_that_disagree_are_rejected() -> None:
    naive = datetime(2026, 2, 9, 9, 0)  # noqa: DTZ001 - the shape a feed carries
    with pytest.raises(MalformedValue):
        IcsTime(wall=naive, kind=ZoneKind.NAMED, zone=None, all_day=False)
    with pytest.raises(MalformedValue):
        IcsTime(wall=naive, kind=ZoneKind.FLOATING, zone=LONDON, all_day=False)
