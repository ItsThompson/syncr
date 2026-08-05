"""The readers: what each one accepts, and what it says when the payload is not that.

A ``KeyError`` or a ``TypeError`` escaping from here would exit 1 with a traceback, which tells a
user nothing and tells an agent less. So every reader names the member and the kind it wanted, and
these are the assertions that the message is that rather than a stack trace.
"""

from __future__ import annotations

import pytest

from syncr_cli.errors import MalformedResponse
from syncr_cli.wire.reading import (
    boolean,
    instant,
    integer,
    mapping,
    mappings,
    nested,
    optional_nested,
    optional_text,
    sequence,
    text,
)
from syncr_cli.wire.verdict import Verdict


def test_a_payload_that_is_not_an_object_names_the_path() -> None:
    with pytest.raises(MalformedResponse, match="week is"):
        mapping(["not", "an", "object"], "week")


def test_an_absent_member_says_which_member_and_where() -> None:
    with pytest.raises(MalformedResponse, match=r"week\.readings"):
        text({}, "readings", "week")


def test_a_member_of_the_wrong_kind_says_what_was_wanted() -> None:
    with pytest.raises(MalformedResponse, match="a string"):
        text({"isoWeek": 7}, "isoWeek", "week")


def test_a_boolean_is_not_read_as_a_number() -> None:
    # `bool` is an `int` subclass in Python, so an unguarded reader would take `true` as one minute.
    with pytest.raises(MalformedResponse, match="a whole number"):
        integer({"minutes": True}, "minutes", "block")


def test_a_number_is_not_read_as_a_boolean() -> None:
    with pytest.raises(MalformedResponse, match="true or false"):
        boolean({"pinned": 1}, "pinned", "block")


def test_a_duration_that_arrives_as_text_is_refused_rather_than_coerced() -> None:
    # Durations are integer minutes on this wire. A string that happens to parse is a contract
    # violation, and reading it would hide the violation from both surfaces.
    with pytest.raises(MalformedResponse, match="a whole number"):
        integer({"minutes": "90"}, "minutes", "block")


def test_an_array_member_that_is_not_an_array_is_refused() -> None:
    with pytest.raises(MalformedResponse, match="an array"):
        sequence({"blocks": {}}, "blocks", "plan")


def test_an_array_entry_that_is_not_an_object_names_its_position() -> None:
    with pytest.raises(MalformedResponse, match=r"plan.blocks\[1\]"):
        mappings({"blocks": [{}, "not an object"]}, "blocks", "plan")


def test_a_nested_member_that_is_not_an_object_is_refused() -> None:
    with pytest.raises(MalformedResponse, match=r"week\.span"):
        nested({"span": 7}, "span", "week")


def test_an_optional_object_reads_absent_and_null_the_same_way() -> None:
    assert optional_nested({}, "live", "week") is None
    assert optional_nested({"live": None}, "live", "week") is None


def test_an_optional_string_of_the_wrong_kind_is_still_refused() -> None:
    assert optional_text({"supersededBy": None}, "supersededBy", "operation") is None
    with pytest.raises(MalformedResponse, match="a string or null"):
        optional_text({"supersededBy": 7}, "supersededBy", "operation")


def test_an_instant_with_no_offset_is_refused() -> None:
    # A local string a reader has to guess the zone of is exactly what this wire does not carry.
    with pytest.raises(MalformedResponse, match="states no UTC offset"):
        instant({"start": "2026-02-09T00:00:00"}, "start", "week.span")


def test_an_instant_that_is_not_an_instant_says_what_one_looks_like() -> None:
    with pytest.raises(MalformedResponse, match="RFC 3339"):
        instant({"start": "the ninth"}, "start", "week.span")


def test_an_instant_with_an_offset_is_read_as_one() -> None:
    read = instant({"start": "2026-02-09T00:00:00+01:00"}, "start", "week.span")

    assert read.utcoffset() is not None


def test_a_provenance_this_build_cannot_name_is_refused_with_the_ones_it_can() -> None:
    # The provenance is what the ledger prints as `[capacity check]` or `[after solving]`, so a word
    # it cannot map is not something to print blank.
    with pytest.raises(MalformedResponse, match="probe, solver"):
        Verdict.read({"feasible": False, "provenance": "guess"}, "verdict")


def test_a_verdict_with_no_shortfalls_member_reads_as_having_none() -> None:
    # The verdict's wire shape is not in the contract yet, so the reader requires only the two
    # members the headline is composed from.
    read = Verdict.read({"feasible": False, "provenance": "probe"}, "verdict")

    assert read.shortfalls == ()
    assert read.tradeoff_count == 0
    assert read.capacity_is_sufficient is True
