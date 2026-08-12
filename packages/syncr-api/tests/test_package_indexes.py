"""The claims a package's ``__init__`` docstring makes about its own modules.

An index goes stale silently: a module lands and the docstring is not counted again, and the count
of how many modules do a particular thing is one short the moment a new one appears. Both are claims
about the source, so both are asserted against the source here rather than trusted.

**Only the packages that CLAIM a complete index are checked for one.** Several packages in this
member list a subset on purpose, leaving their wiring and injection modules out of the table, so
completeness is asserted exactly where completeness is stated. The claim itself is asserted too: a
package cannot quietly drop the sentence and stay in the inventory below.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Final

import pytest

# The packages whose docstring states that every module of theirs appears in its index.
PACKAGES_CLAIMING_A_COMPLETE_INDEX: Final = (
    "plans",
    "anchors",
    "reviews",
    "conflicts",
    "learned",
    "promotions",
)

COMPLETENESS_CLAIM: Final = "Every module in this package appears"

# What the anchor package says about itself: four modules compute a span nobody stored, and two
# more rebuild one they were handed. Every other module of that package names no interval at all.
COMPUTES_A_SPAN: Final = frozenset(
    {"shadows.py", "shadow_collisions.py", "shadow_products.py", "reach.py"}
)
REBUILDS_A_SPAN: Final = frozenset({"queries.py", "repository.py"})

# How a span is built, whatever it is built from. An annotation naming an interval is not building
# one, so the pattern is the CALL rather than the name.
_BUILDS_A_SPAN = re.compile(r"\b(Interval|IntervalSet|timedelta)\(")

_INDEXED_MODULE = re.compile(r"``([a-z_]+\.py)``")

# Spelled out because the docstring spells them out. Bounded by what a package of this size can
# reach rather than by a general number-to-word rule, which nothing here needs.
_NUMERALS: Final = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven"}


def package_directory(package: str) -> Path:
    return Path(importlib.import_module(f"syncr_api.{package}").__file__ or "").parent


def modules_on_disk(package: str) -> set[str]:
    """Every module of ``package``, which is every ``.py`` in it apart from the index itself."""
    return {
        path.name for path in package_directory(package).glob("*.py") if path.name != "__init__.py"
    }


def indexed_modules(package: str) -> set[str]:
    """Every module the package's own docstring names, read out of the index it states."""
    docstring = importlib.import_module(f"syncr_api.{package}").__doc__ or ""
    return set(_INDEXED_MODULE.findall(docstring))


@pytest.mark.parametrize("package", PACKAGES_CLAIMING_A_COMPLETE_INDEX)
def test_a_package_claiming_a_complete_index_says_so_where_a_reader_looks(package: str) -> None:
    # The inventory above is only meaningful while each member still makes the claim. Without this,
    # deleting the sentence would leave the check enforcing something the package no longer says.
    docstring = importlib.import_module(f"syncr_api.{package}").__doc__ or ""

    assert COMPLETENESS_CLAIM in docstring


@pytest.mark.parametrize("package", PACKAGES_CLAIMING_A_COMPLETE_INDEX)
def test_every_module_of_the_package_appears_in_its_index(package: str) -> None:
    # The drift this catches: a module lands and the index is not counted again.
    assert modules_on_disk(package) - indexed_modules(package) == set()


@pytest.mark.parametrize("package", PACKAGES_CLAIMING_A_COMPLETE_INDEX)
def test_the_index_names_no_module_the_package_does_not_hold(package: str) -> None:
    # The other direction, which a rename or a deletion produces: an index naming a module nobody
    # can open sends a reader looking for a file that is not there.
    assert indexed_modules(package) - modules_on_disk(package) == set()


def test_only_the_modules_the_anchor_package_names_build_a_span() -> None:
    # A claim about every OTHER module of a package cannot be checked by reading the ones it names,
    # so it is enumerated: which modules build a span is a property of the source. Stated as a
    # negative in prose and as an equality here.
    building = {
        path.name
        for path in package_directory("anchors").glob("*.py")
        if _BUILDS_A_SPAN.search(path.read_text(encoding="utf-8"))
    }

    assert building == set(COMPUTES_A_SPAN | REBUILDS_A_SPAN)


def test_the_anchor_package_states_the_count_it_claims() -> None:
    # The figure in the prose and the size of the set above are the same figure, and the prose is
    # what a reader believes.
    docstring = importlib.import_module("syncr_api.anchors").__doc__ or ""

    assert f"Those {_NUMERALS[len(COMPUTES_A_SPAN)]} are the only modules" in docstring
