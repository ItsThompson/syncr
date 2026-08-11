"""Who reads the repeated-pin rule, derived from the source rather than from the prose.

Two modules of this package state that the api's weekly session is that rule's one reader, and this
package's own nightly run was the second reader until the figure it produced turned out to have no
consumer. A sentence saying "one reader" is exactly the kind of claim that goes false silently: the
second reader arrives in another package, and nothing here notices.

So the count is taken from the tree. Every first-party source root outside the rule's own package is
walked, each file is parsed, and a file counts as a reader when it imports or calls the rule by
name. The reading carries both controls: it must see a read it is shown, and it must not read an
ordinary call as one. Without them an equality against a single path passes whenever the walk has
gone blind.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import pytest

import syncr_learning
from syncr_learning import facts

RULE: Final = "detect_repeated_pins"

# Resolved from the imported package rather than from this file, in the shape
# `test_package_boundary.py` resolves its own tree: a walk over another checkout measures a claim
# about a tree nobody is running.
PACKAGE_FILE: Final = Path(syncr_learning.__file__).resolve()
ROOT: Final = PACKAGE_FILE.parents[4]

# The rule's home, excluded because it declares the rule and its suite drives it directly.
RULE_HOME: Final = ROOT / "packages" / "syncr-domain" / "src"

# Every tree a first-party module can live in. `cli` is not under `packages`, so it is named.
SOURCE_ROOTS: Final = (
    ROOT / "packages" / "syncr-api" / "src",
    ROOT / "packages" / "syncr-common" / "src",
    ROOT / "packages" / "syncr-learning" / "src",
    ROOT / "packages" / "syncr-solver" / "src",
    ROOT / "cli" / "src",
)

READ_SPELLINGS: Final = (
    f"from syncr_domain.promotion import {RULE}",
    f"{RULE}(corpus.pins)",
    f"promotion.{RULE}(facts.pins)",
    f"candidates = tuple({RULE}(pins))",
)

INNOCENT_SPELLINGS: Final = (
    "from syncr_domain.promotion import PinPlacement",
    "detect_repeated_pins_later(pins)",
    "promotion.declined(pins)",
    'DOCUMENTED = "detect_repeated_pins is one pass over pin rows"',
)


def first_party_sources() -> list[Path]:
    return [path for root in SOURCE_ROOTS for path in sorted(root.rglob("*.py"))]


def reads_the_rule(tree: ast.Module) -> bool:
    """Whether this module imports or calls the rule by name."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and any(one.name == RULE for one in node.names):
            return True
        called = node.func if isinstance(node, ast.Call) else None
        if isinstance(called, ast.Name) and called.id == RULE:
            return True
        if isinstance(called, ast.Attribute) and called.attr == RULE:
            return True
    return False


def readers() -> set[Path]:
    return {
        path
        for path in first_party_sources()
        if reads_the_rule(ast.parse(path.read_text(encoding="utf-8")))
    }


def test_the_walk_reaches_every_first_party_tree_and_the_one_this_suite_imported() -> None:
    # The instrument's precondition. A walk that resolved another checkout, or that lost a tree,
    # would satisfy the equality below by seeing nothing rather than by finding nothing.
    walked = first_party_sources()
    contributing = {
        root for root in SOURCE_ROOTS if any(one.is_relative_to(root) for one in walked)
    }

    assert PACKAGE_FILE in walked
    assert contributing == set(SOURCE_ROOTS)
    assert not any(one.is_relative_to(RULE_HOME) for one in walked), (
        "the rule's own package is excluded on purpose, so the census counts readers rather than "
        "the declaration"
    )


def test_one_first_party_source_outside_the_domain_reads_the_repeated_pin_rule() -> None:
    # What makes "one reader" a fact rather than a sentence. A second reader anywhere in the api,
    # the solver, the CLI or this package reddens here, which is the claim the two statements make.
    assert readers() == {
        ROOT / "packages" / "syncr-api" / "src" / "syncr_api" / "reviews" / "service.py"
    }


@pytest.mark.parametrize("spelling", READ_SPELLINGS)
def test_the_reading_finds_a_read_it_is_shown(spelling: str) -> None:
    assert reads_the_rule(ast.parse(spelling + "\n")), spelling


@pytest.mark.parametrize("spelling", INNOCENT_SPELLINGS)
def test_the_reading_does_not_read_an_ordinary_call_as_the_rule(spelling: str) -> None:
    # The half that catches a reading which widened to everything: an always-true reading satisfies
    # every case above and turns the census into a guard that cannot fail.
    assert not reads_the_rule(ast.parse(spelling + "\n")), spelling


@pytest.mark.parametrize(
    "stated", [syncr_learning.__doc__, facts.__doc__], ids=["package", "facts"]
)
def test_the_statement_names_the_reader_the_census_found(stated: str | None) -> None:
    normalized = " ".join((stated or "").split())

    assert "the api's weekly session is" in normalized
    assert "one reader" in normalized
