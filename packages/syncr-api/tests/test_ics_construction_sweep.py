"""The construction sweep, executable: no site reads a feed's value without a declared guard.

A feed's values reach constructors that refuse some inputs by raising something no caller in this
package declares. :mod:`tests.ics_construction_sites` declares every such call with its guard, and
these tests compare that table against the package's own source.

Two directions, and both are needed. A site the source contains and the table does not is an
unguarded conversion nobody has answered. A site the table contains and the source does not is a
stale row, which is how a table stops describing the code while still looking authoritative.

The generated corpus is the other half. The table says where the values land; the axes in
:mod:`tests.hostile_ics` say which values to send, derived from the bounds rather than written out,
so the corpus follows a bound when it moves. What neither half can do is find an overflow in
arithmetic, which is not a call: that is what the unrepresentable net is for, and the corpus is what
exercises it.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from syncr_api.calendars.config import MAX_EVENT_DAYS
from syncr_api.calendars.ics_values import MAX_MAGNITUDE_DIGITS
from tests.hostile_ics import _EXTREMES, _STARTS, HOSTILE_MAGNITUDES
from tests.ics_construction_sites import (
    AT_INT_CONVERSION,
    EXPRESSED,
    GUARDS,
    PAST_INT_CONVERSION,
    REFUSED,
    SITES,
    UNSEEN,
    InexpressibleShape,
    construction_calls,
)

if TYPE_CHECKING:
    from pathlib import Path

    from tests.ics_construction_sites import Shape

PACKAGE = "calendars"


def declared() -> set[tuple[str, str, str]]:
    return {(site.module, site.function, site.constructor) for site in SITES}


# --------------------------------------------------------------------------------
# The table against the source, both ways
# --------------------------------------------------------------------------------


def test_every_construction_call_in_the_package_is_declared(source_root: Path) -> None:
    # A conversion with no row is a value a feed can reach with nothing stating how it is answered.
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
    # The interval the placement half builds, named here rather than only in the table, because this
    # assertion reads the SOURCE. A row moving module with its call is a table edit; a call moving
    # module is what the two directions above are for, and this is the site they are about.
    assert ("ics_series", "_window", "Interval") in found
    # And it is a filter rather than a firehose: most of the package's calls construct nothing, so
    # the walk finds far fewer sites than the package has modules times three. Asserting the found
    # NAMES are all in `CONSTRUCTORS` would be wrong: an attribute on a datetime type counts however
    # it is spelled, which is what keeps a new sibling of `strptime` from being invisible.
    assert 0 < len(found) < len(list((source_root / PACKAGE).rglob("*.py"))) * 3


def test_every_declared_site_states_a_guard() -> None:
    # A row whose guard is blank would satisfy both directions above while saying nothing, which is
    # the failure mode of a table that is only ever read by people.
    assert all(site.guard for site in SITES)
    assert all(site.reads for site in SITES)


def test_every_guard_is_one_of_the_named_mechanisms() -> None:
    # Non-blank is not enough: prose passes that. A guard has to name a mechanism from the closed
    # vocabulary, or a row can answer "looks fine" and read as though it answered something.
    stated = {site.guard for site in SITES}

    assert stated <= GUARDS, f"{sorted(stated - GUARDS)} are not terms this table defines."


# --------------------------------------------------------------------------------
# What the walk can express, what it refuses, and what it cannot see
# --------------------------------------------------------------------------------


def _walked(tmp_path: Path, source: str) -> set[tuple[str, str, str]]:
    """The census over a one-module package holding ``source``, as module ``probe``."""
    package = tmp_path / "probed"
    package.mkdir()
    (package / "probe.py").write_text(source, encoding="utf-8")
    return construction_calls(tmp_path, "probed")


@pytest.mark.parametrize("shape", EXPRESSED, ids=lambda shape: shape.what)
def test_every_expressed_shape_is_reported_with_its_triple(shape: Shape, tmp_path: Path) -> None:
    # The published bound, driven. A paragraph claiming the walk sees a shape is the walk's own
    # claim about itself; running the shape through it is the measurement.
    assert shape.triple is not None

    assert shape.triple in _walked(tmp_path, shape.source)


@pytest.mark.parametrize("shape", REFUSED, ids=lambda shape: shape.what)
def test_every_renamed_constructor_is_refused_by_name(shape: Shape, tmp_path: Path) -> None:
    # A census that answers "no calls here" for a module reaching a constructor under a second name
    # is indistinguishable from one answering for a module that constructs nothing. The refusal is
    # what tells those apart, and it has to name the binding or a reader cannot act on it.
    with pytest.raises(InexpressibleShape) as refused:
        _walked(tmp_path, shape.source)

    assert shape.names in str(refused.value)
    assert "probe" in str(refused.value)


@pytest.mark.parametrize("shape", UNSEEN, ids=lambda shape: shape.what)
def test_an_unseen_shape_is_reported_as_no_call_and_as_no_refusal(
    shape: Shape, tmp_path: Path
) -> None:
    # The claimed blind spot, measured. A limit an instrument asserts about itself is a claim like
    # any other, and this one is only worth stating if a container binding really does pass both
    # halves silently. If this test starts failing, the walk grew and the docstring owes an edit.
    assert _walked(tmp_path, shape.source) == set()


# --------------------------------------------------------------------------------
# The axes, and that they are derived rather than written
# --------------------------------------------------------------------------------


def test_the_magnitude_corpus_is_crossed_rather_than_listed() -> None:
    # A list holds the failures somebody found; a cross product holds combinations nobody would have
    # thought to write. The site that justified the unrepresentable net was found exactly that way,
    # so this is the property that earned its keep rather than a stylistic preference.
    assert len(HOSTILE_MAGNITUDES) == len(_STARTS) * len(_EXTREMES)
    # Every body is one event in one calendar, so a count is a count of combinations.
    assert all(body.count("BEGIN:VEVENT") == 1 for body in HOSTILE_MAGNITUDES.values())


def test_the_corpus_carries_both_sides_of_the_conversion_limit() -> None:
    # A corpus holding only the accepted side cannot fail when the conversion is left unguarded, so
    # both sides of the boundary have to be present.
    bodies = "".join(HOSTILE_MAGNITUDES.values())

    assert PAST_INT_CONVERSION in bodies
    assert AT_INT_CONVERSION in bodies


def test_the_conversion_axis_is_read_from_the_interpreter_rather_than_written_out() -> None:
    # A literal 4301 would stop testing the boundary the moment a deployment set
    # PYTHONINTMAXSTRDIGITS, so the axis reads the limit it is meant to straddle.
    assert len(PAST_INT_CONVERSION) == len(AT_INT_CONVERSION) + 1
    assert len(AT_INT_CONVERSION) >= sys.get_int_max_str_digits()


def test_the_magnitude_axis_is_read_from_the_bound_it_tests() -> None:
    # Same rule for the bound the code owns: the corpus follows MAX_EVENT_DAYS when it moves.
    bodies = "".join(HOSTILE_MAGNITUDES.values())

    assert f"P{MAX_EVENT_DAYS}D" in bodies
    assert f"P{MAX_EVENT_DAYS + 1}D" in bodies
    assert len(AT_INT_CONVERSION) > MAX_MAGNITUDE_DIGITS


@pytest.mark.parametrize("start", ["DTSTART:", "DTSTART;TZID=", "DTSTART;VALUE=DATE:"])
def test_every_start_form_is_crossed_with_the_extremes(start: str) -> None:
    # Three forms reach three different resolution paths: an instant, a named zone, and a whole
    # local day. An extreme value crossed with only one of them tests one path.
    assert any(start in body for body in HOSTILE_MAGNITUDES.values())
