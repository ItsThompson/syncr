"""The lexer: unfolding, line attribution, escapes, quoted parameters, and grouping.

Asserted at this level rather than only through the adapter, because every one of these is
a property of the wire format a publisher gets wrong independently of what the event says.
The fixture corpus exercises the same code through :mod:`tests.test_ics_adapter`; these
tests are what say WHICH reading was wrong when that one goes red.
"""

from __future__ import annotations

from syncr_api.calendars.ics_lines import (
    VEVENT,
    Component,
    events_in,
    parse_components,
    parse_content_line,
    unescape,
    unfold,
)


def value_of(component: Component, name: str) -> str | None:
    """One property's value, so an assertion reads a value rather than an optional line."""
    found = component.first(name)
    return None if found is None else found.value


def test_a_folded_line_rejoins_and_keeps_the_line_it_started_on() -> None:
    feed = "BEGIN:VEVENT\r\nSUMMARY:Advanced Computer\r\n  Architecture\r\nEND:VEVENT\r\n"

    lines = list(unfold(feed))

    assert lines[1] == (2, "SUMMARY:Advanced Computer Architecture")
    # The END is the fourth physical line, not the third: the continuation is counted.
    assert lines[2] == (4, "END:VEVENT")


def test_a_tab_folded_line_rejoins_too() -> None:
    # RFC 5545 permits a tab as the fold prefix, and Outlook emits one. Unfolding removes
    # the break and exactly ONE whitespace character, so the space between the two words
    # is part of the continuation's content and the fixture carries both.
    assert list(unfold("SUMMARY:Team\r\n\t standup\r\n")) == [(1, "SUMMARY:Team standup")]


def test_all_three_line_breaks_read_as_one_break_each() -> None:
    lone_cr = "A:1\rB:2\nC:3\r\nD:4"

    assert [value for _line, value in unfold(lone_cr)] == ["A:1", "B:2", "C:3", "D:4"]


def test_a_blank_line_is_dropped_without_consuming_a_fold() -> None:
    feed = "SUMMARY:Lecture\r\n\r\nDTSTART:20260209T090000Z\r\n"

    assert list(unfold(feed)) == [(1, "SUMMARY:Lecture"), (3, "DTSTART:20260209T090000Z")]


def test_a_parameter_is_read_case_insensitively_and_unquoted() -> None:
    line = parse_content_line('DTSTART;tzid="Europe/London":20260209T090000', 7)

    assert line is not None
    assert line.name == "DTSTART"
    assert line.param("TZID") == "Europe/London"
    assert line.param("tzid") == "Europe/London"
    assert line.value == "20260209T090000"
    assert line.line == 7


def test_a_colon_inside_a_quoted_parameter_does_not_end_the_parameters() -> None:
    # The reading a naive split on the first colon gets wrong: the value would become
    # `//example.com/x"` and the property would lose its own.
    line = parse_content_line('SUMMARY;ALTREP="http://example.com/x":Kickoff', 1)

    assert line is not None
    assert line.param("ALTREP") == "http://example.com/x"
    assert line.value == "Kickoff"


def test_a_line_with_no_colon_is_not_a_content_line() -> None:
    assert parse_content_line("BEGINVEVENT", 1) is None
    assert parse_content_line(":no name", 1) is None


def test_every_defined_escape_resolves_and_an_undefined_one_survives() -> None:
    assert unescape(r"Exam\, room 3\; bring ID") == "Exam, room 3; bring ID"
    assert unescape(r"Line one\nLine two\NLine three") == "Line one\nLine two\nLine three"
    assert unescape(r"C:\\path") == "C:\\path"
    # Not an escape the standard defines: guessing would silently change a title.
    assert unescape(r"50\% off") == r"50\% off"
    assert unescape("trailing\\") == "trailing\\"


def test_a_vevent_inside_a_vcalendar_is_found_with_its_own_start_line() -> None:
    feed = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:one\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )

    found = list(events_in(parse_components(feed)))

    assert len(found) == 1
    assert found[0].line == 3
    assert value_of(found[0], "UID") == "one"


def test_an_alarm_start_does_not_become_the_events_start() -> None:
    # A VALARM carries a TRIGGER and can carry a DTSTART of its own. Flattening the two
    # would let the alarm decide when the event is.
    feed = (
        "BEGIN:VEVENT\r\n"
        "UID:one\r\n"
        "DTSTART:20260209T090000Z\r\n"
        "BEGIN:VALARM\r\n"
        "DTSTART:19700101T000000Z\r\n"
        "END:VALARM\r\n"
        "END:VEVENT\r\n"
    )

    event = next(events_in(parse_components(feed)))

    assert [line.value for line in event.all_values("DTSTART")] == ["20260209T090000Z"]
    assert event.children[0].name == "VALARM"


def test_a_component_whose_end_never_arrives_still_yields_its_events() -> None:
    # A truncated download is real, and the events before the cut are real occupancy.
    truncated = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:one\r\nEND:VEVENT\r\nBEGIN:VEVENT\r\nUID:two"
    )

    found = list(events_in(parse_components(truncated)))

    assert [value_of(event, "UID") for event in found] == ["one", "two"]


def test_a_missing_inner_end_closes_at_the_outer_one() -> None:
    feed = "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:one\r\nEND:VCALENDAR\r\n"

    components = parse_components(feed)

    assert [component.name for component in components] == ["VCALENDAR"]
    assert [value_of(event, "UID") for event in events_in(components)] == ["one"]


def test_an_end_naming_nothing_open_discards_no_component() -> None:
    feed = "END:VTIMEZONE\r\nBEGIN:VEVENT\r\nUID:one\r\nEND:VEVENT\r\n"

    assert [component.name for component in parse_components(feed)] == [VEVENT]
