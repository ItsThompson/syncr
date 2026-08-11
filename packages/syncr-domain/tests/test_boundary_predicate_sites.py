"""Where an interval's start is compared against a reference instant, derived from the tree.

One question is asked all over this product: has the week reached this span? It was answered in
five places, two of them across a package boundary from the other three, and two of those five
disagreed about the boundary instant on purpose while nothing said so. `syncr_domain.intervals`
now answers it once, for both readings, and this walk is what keeps that true: every comparison
of an interval's start against an instant in every shipped source root is enumerated and held
against the set of places allowed to hold one.

An equality rather than an emptiness assertion, in both directions. A new copy anywhere fails it,
and so does a walk that has gone blind: an assertion that "no second definition exists" is
equally true when the reading matches nothing at all.

WHAT THIS WALK CANNOT SEE, stated so a green result is not read as more than it is:

* a reversed spelling, `now >= interval.start`. Adding that direction to the reading was tried and
  reverted: a stored column compared against a span's start is the same shape, so six SQLAlchemy
  `where` clauses matched, in files this rule has nothing to do with. Forward-only is what keeps
  the allowed set below down to the module that owns the question.
* the comparison written through a local name. `start = interval.start` and then `start <= now`
  carries no attribute named `start` on the left, so it reads here as no comparison at all.
* the negated form, `not interval.start > now`, for the same reason as the reversed one.
* a root outside `packages/*/src`. Measured rather than assumed: `cli/src` holds two containment
  comparisons and no copy of this predicate, and `tools/`, `e2e/`, `deployments/` and the
  migration chain hold none. The suites are outside deliberately, because a test comparing bounds
  enforces nothing.
* which reading a site takes. The walk sees that a comparison is there, not whether `<` or `<=` is
  the right one for that caller. `test_intervals.py` pins the difference between the two.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest

import syncr_domain

if TYPE_CHECKING:
    from collections.abc import Iterator

# Every tree a shipped first-party module lives in, which is the scope this rule is stated over.
SOURCE_ROOTS: Final = ("packages/*/src",)

# The trees the walk has to reach, spelled out rather than read back out of the glob above: a
# reach control derived from the pattern it is checking cannot fail when that pattern narrows.
COVERED_TREES: Final = (
    "packages/syncr-api/src/",
    "packages/syncr-common/src/",
    "packages/syncr-domain/src/",
    "packages/syncr-learning/src/",
    "packages/syncr-solver/src/",
)

ALGEBRA: Final = "packages/syncr-domain/src/syncr_domain/intervals.py"

# The only places a comparison of an interval's start against an instant may live. The two
# predicates are the answer this product gives to the question; `IntervalSet.before` compares the
# same pair of values to a different end, cutting a set at an instant rather than deciding
# anything about one member, and it is listed because it sits in the module that owns the shape.
CANONICAL_SITES: Final = frozenset(
    {
        (ALGEBRA, "has_started"),
        (ALGEBRA, "has_elapsed"),
        (ALGEBRA, "IntervalSet.before"),
    }
)

# An interval's own two bounds. A comparison whose other side is one of these is asking about two
# spans rather than about an instant: the overlap rule, the merge walk, and every containment test
# in the tree take that shape.
_BOUNDS: Final = frozenset({"start", "end"})

FINDS_A_SITE: Final = (
    "interval.start <= now",
    "interval.start < now",
    "block.interval.start <= inputs.now",
    "entry.interval.start < attempt.inputs.now",
    "held = [one for one in rows if one.interval.start <= reference]",
    "def reached(span, stamp):\n    return span.start <= stamp\n",
)

FINDS_NO_SITE: Final = (
    "span.start <= moment < span.end",
    "self.start < other.end and other.start < self.end",
    "member.start < span.start",
    "OffPlanPeriodRow.start < span.end",
    "earliest_collision - block.interval.start < SNAP",
    "day.interval.end <= now",
)


def repository_root() -> Path:
    """The checkout the imported package came from, which is the tree the walk reads."""
    return Path(syncr_domain.__file__).resolve().parents[4]


def shipped_modules(root: Path) -> dict[str, Path]:
    """Every shipped Python file, by path relative to the root."""
    found: dict[str, Path] = {}
    for pattern in SOURCE_ROOTS:
        for source_root in sorted(root.glob(pattern)):
            for path in sorted(source_root.rglob("*.py")):
                found[str(path.relative_to(root))] = path
    return found


def compares_a_start_against_an_instant(node: ast.Compare) -> bool:
    """Whether this comparison asks where an interval's start falls relative to one instant.

    One operator, so a chained containment test is a different question and reads as one. The
    left side names an interval's start, and the right side names something that is not another
    interval's bound.
    """
    if len(node.ops) != 1 or not isinstance(node.ops[0], ast.Lt | ast.LtE):
        return False
    if not (isinstance(node.left, ast.Attribute) and node.left.attr == "start"):
        return False
    upper = node.comparators[0]
    return not (isinstance(upper, ast.Attribute) and upper.attr in _BOUNDS)


def sites_in(node: ast.AST, scope: tuple[str, ...] = ()) -> Iterator[str]:
    """The dotted name of every scope holding such a comparison, once per comparison.

    The scope is tracked on the way down rather than recovered from a parent map, so a comparison
    inside a comprehension inside a method is attributed to the method that holds it.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            yield from sites_in(child, (*scope, child.name))
            continue
        if isinstance(child, ast.Compare) and compares_a_start_against_an_instant(child):
            yield ".".join(scope) or "<module>"
        yield from sites_in(child, scope)


def found_sites(root: Path) -> set[tuple[str, str]]:
    """Every ``(module, scope)`` in the shipped tree that compares a start against an instant."""
    return {
        (relative, scope)
        for relative, path in shipped_modules(root).items()
        for scope in sites_in(ast.parse(path.read_text(encoding="utf-8")))
    }


# --------------------------------------------------------------------------------
# The controls: which tree the walk read, how far it reached, and what the reading reads
# --------------------------------------------------------------------------------


def test_the_walk_reads_the_checkout_whose_code_this_suite_imports() -> None:
    # Two derivations of one root, crossed. A run against a scratch copy would otherwise hold one
    # checkout's allowed set against another checkout's sources and pass on both being wrong.
    assert repository_root() == Path(__file__).resolve().parents[3]


def test_the_walk_reaches_every_shipped_package_tree() -> None:
    found = shipped_modules(repository_root())

    reached = {tree: any(one.startswith(tree) for one in found) for tree in COVERED_TREES}

    assert reached == dict.fromkeys(COVERED_TREES, True)


def test_the_walk_recurses_and_reaches_the_modules_this_rule_is_about() -> None:
    # The reach control above is satisfied by one file per tree, so a walk that stopped recursing
    # would pass it. All four of these sit at least two directories inside a package and all four
    # held a copy of the predicate before it was moved.
    found = shipped_modules(repository_root())

    assert ALGEBRA in found
    assert "packages/syncr-api/src/syncr_api/plans/settled.py" in found
    assert "packages/syncr-api/src/syncr_api/plans/netting.py" in found
    assert "packages/syncr-solver/src/syncr_solver/binding.py" in found


@pytest.mark.parametrize("spelling", FINDS_A_SITE)
def test_the_reading_finds_a_comparison_it_is_shown(spelling: str) -> None:
    assert list(sites_in(ast.parse(spelling))), spelling


@pytest.mark.parametrize("spelling", FINDS_NO_SITE)
def test_the_reading_does_not_read_an_ordinary_bound_comparison_as_one(spelling: str) -> None:
    # The half that catches a reading widened to everything. An always-true reading satisfies
    # every case above and turns the equality below into a guard that cannot fail.
    assert not list(sites_in(ast.parse(spelling))), spelling


def test_the_reading_attributes_a_comparison_to_the_scope_that_holds_it() -> None:
    # What makes the equality below name a place rather than only a file, so two copies in one
    # module are two members and a copy that moves between functions is a changed member.
    nested = (
        "class Held:\n    def reached(self, span, stamp):\n        return span.start <= stamp\n"
    )

    assert list(sites_in(ast.parse(nested))) == ["Held.reached"]


# --------------------------------------------------------------------------------
# The rule
# --------------------------------------------------------------------------------


def test_the_interval_algebra_is_the_only_place_a_start_is_compared_to_an_instant() -> None:
    assert found_sites(repository_root()) == CANONICAL_SITES
