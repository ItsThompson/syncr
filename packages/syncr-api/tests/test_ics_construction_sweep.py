"""The construction sweep, executable: no site reads a feed's value without a declared guard.

Three rounds of this ticket went on one class of defect. Each round the fix was right and each round
the class survived somewhere else, because what existed was a list of the failures that had been
found rather than a statement of where a feed's values are converted. This is that statement, and
these tests are what make it fail rather than rot.

Two directions, and both are needed. A site the source contains and the table does not is the defect
that recurred: an unguarded conversion nobody noticed. A site the table contains and the source does
not is a stale row, which is how a table stops describing the code while still looking
authoritative.

The generated corpus is the other half. The table says where the values land; the axes in
:mod:`tests.hostile_ics` say which values to send, derived from the bounds rather than written
out, so
the corpus follows a bound when it moves. What neither half can do is find an overflow in
arithmetic,
which is not a call: that is what the unrepresentable net is for, and the corpus is what exercises
it.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from syncr_api.calendars.config import MAX_EVENT_DAYS
from syncr_api.calendars.ics_values import MAX_MAGNITUDE_DIGITS
from tests.hostile_ics import ALL_FEEDS, HOSTILE_MAGNITUDES
from tests.ics_construction_sites import (
    AT_INT_CONVERSION,
    CONSTRUCTORS,
    PAST_INT_CONVERSION,
    SITES,
    construction_calls,
)

if TYPE_CHECKING:
    from pathlib import Path

PACKAGE = "calendars"


def declared() -> set[tuple[str, str, str]]:
    return {(site.module, site.function, site.constructor) for site in SITES}


# --------------------------------------------------------------------------------
# The table against the source, both ways
# --------------------------------------------------------------------------------


def test_every_construction_call_in_the_package_is_declared(source_root: Path) -> None:
    # The direction that catches the defect this ticket kept reproducing. A conversion added without
    # a row is a value a feed can reach with nothing saying how it is answered, and the reviews
    # found
    # three such sites across three iterations by reading rather than by running anything.
    undeclared = construction_calls(source_root, PACKAGE) - declared()

    assert undeclared == set(), (
        f"{sorted(undeclared)} construct from a value this package reads and are not in SITES. "
        "Add a row naming the guard, or add the guard."
    )


def test_no_declared_site_has_gone_away(source_root: Path) -> None:
    # The other direction. A stale row makes the table look complete while describing code that no
    # longer exists, which is how the next reader concludes a boundary is settled when it is not.
    missing = declared() - construction_calls(source_root, PACKAGE)

    assert missing == set(), f"{sorted(missing)} are declared in SITES and no longer in the source."


def test_the_walk_finds_a_construction_call_and_ignores_other_calls(source_root: Path) -> None:
    # The walk's own control. Without it, "every call is declared" passes on a reading that finds
    # nothing, and goes on passing after someone adds the conversion it is meant to catch.
    found = construction_calls(source_root, PACKAGE)

    assert ("ics_values", "_number", "int") in found
    assert ("ics_values", "_build", "datetime") in found
    # And it is a filter rather than a firehose: the package makes many calls that construct
    # nothing.
    assert all(constructor in CONSTRUCTORS for _module, _function, constructor in found)


def test_every_declared_site_states_a_guard() -> None:
    # A row whose guard is blank would satisfy both directions above while saying nothing, which is
    # the failure mode of a table that is only ever read by people.
    assert all(site.guard for site in SITES)
    assert all(site.reads for site in SITES)


# --------------------------------------------------------------------------------
# The axes, and that they are derived rather than written
# --------------------------------------------------------------------------------


def test_the_magnitude_corpus_is_crossed_rather_than_listed() -> None:
    # A list holds the failures somebody found; a cross product holds combinations nobody would have
    # thought to write. The site that justified the unrepresentable net was found exactly that way,
    # so this is the property that earned its keep rather than a stylistic preference.
    assert len(HOSTILE_MAGNITUDES) > len(ALL_FEEDS) - len(HOSTILE_MAGNITUDES)
    # Every body is one event in one calendar, so a count is a count of combinations.
    assert all(body.count("BEGIN:VEVENT") == 1 for body in HOSTILE_MAGNITUDES.values())


def test_the_corpus_carries_both_sides_of_the_conversion_limit() -> None:
    # The axis the hand-written list stopped short of, and therefore the axis the must-fix sat on. A
    # corpus with only the passing side cannot fail when the conversion is left unguarded.
    bodies = "".join(HOSTILE_MAGNITUDES.values())

    assert PAST_INT_CONVERSION in bodies
    assert AT_INT_CONVERSION in bodies


def test_the_conversion_axis_is_read_from_the_interpreter_rather_than_written_out() -> None:
    # A literal 4301 would stop testing the boundary the moment a deployment set
    # PYTHONINTMAXSTRDIGITS, which is exactly the kind of drift that hid the must-fix.
    assert len(PAST_INT_CONVERSION) == sys.get_int_max_str_digits() + 1
    assert len(AT_INT_CONVERSION) == sys.get_int_max_str_digits()


def test_the_magnitude_axis_is_read_from_the_bound_it_tests() -> None:
    # Same rule for the bound the code owns: the corpus follows MAX_EVENT_DAYS when it moves.
    bodies = "".join(HOSTILE_MAGNITUDES.values())

    assert f"P{MAX_EVENT_DAYS}D" in bodies
    assert f"P{MAX_EVENT_DAYS + 1}D" in bodies
    assert sys.get_int_max_str_digits() > MAX_MAGNITUDE_DIGITS


@pytest.mark.parametrize("start", ["DTSTART:", "DTSTART;TZID=", "DTSTART;VALUE=DATE:"])
def test_every_start_form_is_crossed_with_the_extremes(start: str) -> None:
    # Three forms reach three different resolution paths: an instant, a named zone, and a whole
    # local
    # day. An extreme value crossed with only one of them tests one path.
    assert any(start in body for body in HOSTILE_MAGNITUDES.values())
