"""Where an interval's start is compared against a reference instant, derived from the tree.

One question is asked all over this product: has the week reached this span? It was answered in
several places, some of them across a package boundary from the others, and two of those answers
disagreed about the boundary instant on purpose while nothing said so. `syncr_domain.intervals`
now answers it once, for both readings, and this walk is what keeps that true: every comparison
of an interval's start against something that is not another bound, in every shipped source root,
is enumerated and held against the set of places allowed to hold one.

No count of sites appears here. Two were published in this module's first version and both were
wrong, because a count in a comment is a measurement that has stopped being taken. The census
belongs in the changeset, where it is dated.

The reading is symmetric: either side may carry the `.start`, and all four ordering operators
count. A rule stated over a pair of predicates has to be enforced over both, and a rule about a
comparison has to be enforced in both directions, or the direction left out is where the next copy
lands. It did: two copies lived in the uncovered directions for as long as this walk read only
forward.

An equality rather than an emptiness assertion, in both directions. A new copy anywhere fails it,
and so does a walk that has gone blind: an assertion that "no second definition exists" is
equally true when the reading matches nothing at all.

WHAT THIS WALK CANNOT SEE, stated so a green result is not read as more than it is:

* the comparison written through a local name. `start = interval.start` and then `start <= now`
  carries no attribute named `start` on either side, so it reads here as no comparison at all.
  Measured empty in every shipped root, and unenforced.
* a comparison passed directly to `.where`, `.filter` or `.having`. Those are excluded on purpose,
  because a stored column compared against a span's bound is the same shape as this predicate and
  no property of the syntax separates them. The exclusion is structural rather than a list of
  names, and it is what keeps the allowed set below to the module that owns the question plus two
  stated exceptions. A copy hidden inside a query call escapes.
* a reader that takes the predicate through a module import. The second reading below reads
  `from ... import` only, so `import syncr_api.plans.settled` followed by `settled.has_started(...)`
  is invisible to both readings.
* two qualifying comparisons inside one scope. Sites are keyed on `(module, scope)`, so a second
  one in a scope that already holds one changes nothing. Small in practice, because every allowed
  scope is named below, but real.
* a root outside `packages/*/src`. Measured rather than assumed: `cli/src` holds two containment
  comparisons and no copy of this predicate, and `tools/`, `e2e/`, `deployments/` and the
  migration chain hold none. The suites are outside deliberately, because a test comparing bounds
  enforces nothing.
* which reading a site takes. The walk sees that a comparison is there, not whether `<` or `<=` is
  the right one for that caller. `test_intervals.py` pins the difference between the two.

The second reading below covers the other half of one home: a module that imports the predicate
from somewhere other than the algebra. `plans/settled.py` imports both and uses both, so the names
stay bound there and `from syncr_api.plans.settled import has_started` keeps working; the
comparison walk cannot see that, because an import is not a comparison.
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
NETTING: Final = "packages/syncr-api/src/syncr_api/plans/netting.py"
ICS: Final = "packages/syncr-api/src/syncr_api/calendars/ics_recurrence.py"

# The predicates by name, and the one module a reader may take them from.
PREDICATES: Final = frozenset({"has_started", "has_elapsed"})
CANONICAL_MODULE: Final = "syncr_domain.intervals"

# Readers at the time this rule was written, asserted as a floor rather than an equality: a new
# reader taking the predicate from the algebra is ordinary and must not fail. What the floor buys
# is that a reading which resolved nothing cannot satisfy the rule by finding nothing.
KNOWN_READERS: Final = (
    "packages/syncr-api/src/syncr_api/plans/settled.py",
    "packages/syncr-api/src/syncr_api/plans/netting.py",
    "packages/syncr-api/src/syncr_api/plans/authority.py",
    "packages/syncr-api/src/syncr_api/plans/placements.py",
    "packages/syncr-api/src/syncr_api/plans/overlaps.py",
    "packages/syncr-api/src/syncr_api/plans/tradeoff_nights.py",
    "packages/syncr-solver/src/syncr_solver/binding.py",
    "packages/syncr-solver/src/syncr_solver/inheritance.py",
    "packages/syncr-solver/src/syncr_solver/state.py",
)

# The only places a comparison of an interval's start against something that is not a bound may
# live. Five are the algebra's own: the two predicates, which are this product's answer to the
# question, and three set operations that compare the same pair of values to a different end,
# cutting or walking a set at an instant rather than deciding anything about one member.
#
# Two sit outside it and each asks a different question, which is why each is named here rather
# than excluded by widening the reading:
#
#   _clipped_before  a local variant of `IntervalSet.before`, guarding the empty case before it
#                    builds a bound. The set-clip family, not a decision about a placement.
#   occurrences      an expansion filtered against the window it was expanded for. That bound is a
#                    sync window rather than a reference instant, and no placement is decided.
CANONICAL_SITES: Final = frozenset(
    {
        (ALGEBRA, "has_started"),
        (ALGEBRA, "has_elapsed"),
        (ALGEBRA, "IntervalSet.before"),
        (ALGEBRA, "IntervalSet.after"),
        (ALGEBRA, "_without"),
        (NETTING, "_clipped_before"),
        (ICS, "occurrences"),
    }
)

# An interval's own two bounds. A comparison whose other side is one of these is asking about two
# spans rather than about an instant: the overlap rule, the merge walk, and every containment test
# in the tree take that shape.
_BOUNDS: Final = frozenset({"start", "end"})

# Where a comparison is a stored-column predicate rather than a decision made in Python. A column
# compared against a span's bound is the same shape as this predicate and nothing in the syntax
# separates them, so the query call it is handed to is what separates them.
_QUERY_CALLS: Final = frozenset({"where", "filter", "having"})

FINDS_A_SITE: Final = (
    "interval.start <= now",
    "interval.start < now",
    "block.interval.start <= inputs.now",
    "entry.interval.start < attempt.inputs.now",
    "held = [one for one in rows if one.interval.start <= reference]",
    "def reached(span, stamp):\n    return span.start <= stamp\n",
    "entry.interval.start >= after",
    "now < block.interval.start",
    "now >= interval.start",
    "not interval.start > now",
)

FINDS_NO_SITE: Final = (
    "span.start <= moment < span.end",
    "self.start < other.end and other.start < self.end",
    "member.start < span.start",
    "OffPlanPeriodRow.start < span.end",
    "earliest_collision - block.interval.start < SNAP",
    "day.interval.end <= now",
    "one.interval.start >= accepted.end",
    "rows.where(BlockOutcome.occurred_at >= span.start)",
    "select(A).where(Anchor.starts_at < span.end, Anchor.ends_at > span.start)",
    "query.filter(EditEvent.created_at >= span.start)",
)

FINDS_AN_IMPORT: Final = (
    "from syncr_domain.intervals import has_started",
    "from syncr_domain.intervals import Interval, has_elapsed, has_started",
    "from syncr_api.plans.settled import has_started",
    "from .settled import has_elapsed",
)

FINDS_NO_IMPORT: Final = (
    "from syncr_domain.intervals import IntervalSet",
    "import syncr_domain.intervals",
    "from syncr_api.plans.settled import require_an_unchanged_past",
    "has_started = object()",
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

    One operator, so a chained containment test is a different question and reads as one.
    Symmetric in the two operands: either side may carry the start, because the direction a copy
    happens to be written in is not a property of the question it asks.
    """
    if len(node.ops) != 1 or not isinstance(node.ops[0], ast.Lt | ast.LtE | ast.Gt | ast.GtE):
        return False
    left, right = node.left, node.comparators[0]
    if _is_a_start(left):
        return not _is_a_bound(right)
    return _is_a_start(right) and not _is_a_bound(left)


def _is_a_start(node: ast.expr) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "start"


def _is_a_bound(node: ast.expr) -> bool:
    return isinstance(node, ast.Attribute) and node.attr in _BOUNDS


def query_predicates(tree: ast.Module) -> set[int]:
    """Every comparison handed straight to a query call, by node identity.

    Collected once per module and then excluded by identity rather than re-derived per comparison,
    so the walk stays one pass over the tree.
    """
    return {
        id(argument)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _QUERY_CALLS
        for argument in node.args
        if isinstance(argument, ast.Compare)
    }


def sites_in(tree: ast.Module) -> Iterator[str]:
    """The dotted name of every scope holding such a comparison, once per comparison."""
    yield from _scoped(tree, (), query_predicates(tree))


def _scoped(node: ast.AST, scope: tuple[str, ...], in_a_query: set[int]) -> Iterator[str]:
    """The scopes below ``node``, tracked on the way down rather than from a parent map.

    Tracking downward is what attributes a comparison inside a comprehension inside a method to the
    method that holds it.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            yield from _scoped(child, (*scope, child.name), in_a_query)
            continue
        if (
            isinstance(child, ast.Compare)
            and id(child) not in in_a_query
            and compares_a_start_against_an_instant(child)
        ):
            yield ".".join(scope) or "<module>"
        yield from _scoped(child, scope, in_a_query)


def found_sites(root: Path) -> set[tuple[str, str]]:
    """Every ``(module, scope)`` in the shipped tree that compares a start against an instant."""
    return {
        (relative, scope)
        for relative, path in shipped_modules(root).items()
        for scope in sites_in(ast.parse(path.read_text(encoding="utf-8")))
    }


def imports_in(tree: ast.Module) -> set[str]:
    """The module each ``from ... import`` naming a predicate takes it from.

    A relative import reads as the name it is written with rather than as what it resolves to,
    which is the direction that fails: the rule allows exactly one absolute module.
    """
    return {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and any(alias.name in PREDICATES for alias in node.names)
    }


def found_readers(root: Path) -> set[tuple[str, str]]:
    """Every ``(module, module it imports a predicate from)`` in the shipped tree."""
    return {
        (relative, source)
        for relative, path in shipped_modules(root).items()
        for source in imports_in(ast.parse(path.read_text(encoding="utf-8")))
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
    # would pass it. Each of these sits at least two directories inside a package and each held a
    # copy of the predicate before it was moved.
    found = shipped_modules(repository_root())

    assert ALGEBRA in found
    assert "packages/syncr-api/src/syncr_api/plans/settled.py" in found
    assert "packages/syncr-api/src/syncr_api/plans/netting.py" in found
    assert "packages/syncr-api/src/syncr_api/plans/overlaps.py" in found
    assert "packages/syncr-api/src/syncr_api/plans/tradeoff_nights.py" in found
    assert "packages/syncr-solver/src/syncr_solver/binding.py" in found


@pytest.mark.parametrize("spelling", FINDS_A_SITE)
def test_the_reading_finds_a_comparison_it_is_shown(spelling: str) -> None:
    assert list(sites_in(ast.parse(spelling))), spelling


@pytest.mark.parametrize("spelling", FINDS_NO_SITE)
def test_the_reading_does_not_read_an_ordinary_bound_comparison_as_one(spelling: str) -> None:
    # The half that catches a reading widened to everything. An always-true reading satisfies
    # every case above and turns the equality below into a guard that cannot fail.
    assert not list(sites_in(ast.parse(spelling))), spelling


@pytest.mark.parametrize(
    ("direction", "spelling"),
    [
        ("start first, strict", "interval.start < now"),
        ("start first, inclusive", "interval.start <= now"),
        ("start second, strict", "now < interval.start"),
        ("start second, inclusive", "now <= interval.start"),
        ("start first, reversed", "interval.start >= now"),
        ("start second, reversed", "now >= interval.start"),
    ],
)
def test_the_reading_covers_every_direction_the_question_can_be_written_in(
    direction: str, spelling: str
) -> None:
    # The control this module did not have when it read forward only, and the two copies that
    # survived that version were both written in a direction nothing here asserted. Enumerated by
    # direction rather than by example, so a reading narrowed to one side fails by name.
    assert list(sites_in(ast.parse(spelling))), direction


def test_the_reading_leaves_a_stored_column_predicate_to_the_database() -> None:
    # The exclusion that keeps the allowed set small. Same comparison, twice: handed to a query
    # call it is a stored-column predicate, and standing alone it is a decision in Python.
    handed_to_a_query = "rows.where(Anchor.ends_at > span.start)"
    standing_alone = "kept = Anchor.ends_at > span.start"

    assert not list(sites_in(ast.parse(handed_to_a_query)))
    assert list(sites_in(ast.parse(standing_alone)))


def test_the_reading_attributes_a_comparison_to_the_scope_that_holds_it() -> None:
    # What makes the equality below name a place rather than only a file, so two copies in one
    # module are two members and a copy that moves between functions is a changed member.
    nested = (
        "class Held:\n    def reached(self, span, stamp):\n        return span.start <= stamp\n"
    )

    assert list(sites_in(ast.parse(nested))) == ["Held.reached"]


@pytest.mark.parametrize("spelling", FINDS_AN_IMPORT)
def test_the_import_reading_finds_a_read_it_is_shown(spelling: str) -> None:
    assert imports_in(ast.parse(spelling)), spelling


@pytest.mark.parametrize("spelling", FINDS_NO_IMPORT)
def test_the_import_reading_does_not_read_an_ordinary_import_as_one(spelling: str) -> None:
    assert not imports_in(ast.parse(spelling)), spelling


def test_the_import_reading_reaches_the_readers_the_tree_holds() -> None:
    # The floor that stops the rule below being satisfied by a reading that resolves nothing.
    reading = {relative for relative, _ in found_readers(repository_root())}

    assert set(KNOWN_READERS) <= reading


# --------------------------------------------------------------------------------
# The rule
# --------------------------------------------------------------------------------


def test_the_interval_algebra_is_the_only_place_a_start_is_compared_to_an_instant() -> None:
    # Seven scopes: the algebra's five, and two elsewhere that ask a different question and are
    # named where the set is defined. An eighth anywhere fails, in either direction, and so does
    # any of the seven going missing.
    assert found_sites(repository_root()) == CANONICAL_SITES


def test_every_reader_takes_the_predicate_from_the_algebra_and_from_nowhere_else() -> None:
    # `plans/settled.py` still binds both names, because it imports and uses both, so the old
    # import path keeps resolving. This is what stops a new reader taking it from there.
    assert {source for _, source in found_readers(repository_root())} == {CANONICAL_MODULE}
