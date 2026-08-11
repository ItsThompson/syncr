"""The grid rule as `snap.py` records it, held against the tree that enforces it.

`syncr_domain.snap`'s module docstring is where this product states the fifteen-minute grid rule: a
declared duration and a wall time the user chose both owe the grid, an anchor and its derived
buffers are the only exemption, and the record enumerates the sites that read a declaration against
it. An enumeration in prose goes stale the moment a shape starts or stops reading one of those
predicates, and then the rule's own statement is evidence for a tree that no longer exists. So the
list is crossed against the tree here, in both directions: a module that reads a declaration
predicate and is not listed fails, and a listed module that reads neither fails.

Two predicates, because a DECLARATION can be read by exactly those two: a wall time carries no
instant and neither does a count of minutes, so the instant predicate can see neither. The
instant-facing pair is deliberately outside this crossing. `snap_to_grid` is applied by a producer
to its own output, and a producer's output is not a value a person authored.

WHAT THIS WALK CANNOT SEE, stated so a green result is not read as more than it is:

* a predicate reached through a value rather than through a name: `check = is_a_snap_multiple`
  followed by `check(minutes)`, or `getattr`. Every call in the tree takes the plain shape, so no
  test below is evidence about that form.
* the same arithmetic written out. `minutes % 15` enforces the rule and names no predicate, so a
  module that stops reading a predicate and starts computing reads here as a module that stopped
  enforcing.
* which FIELD a listed module reads. The crossing is at module granularity; the field clauses in the
  record are prose, and a reader checks those.

A call is resolved through the module's own imports where the receiver allows it, and matched on
the name alone where it does not, gated on the module importing the snap module at all. That gate
is what keeps a module's own function of the same name from reading as a call of the predicate, and
it is why a module that imports the snap module and shadows one of these names would read as a site.

The alias resolution is `test_package_boundary`'s `scan`, imported rather than repeated: resolving a
dotted call through a module's own imports is the same question there, over a narrower tree.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest

import syncr_domain
from syncr_domain import snap
from tests.test_package_boundary import scan

if TYPE_CHECKING:
    from collections.abc import Mapping

SNAP_MODULE: Final = "syncr_domain.snap"

# The two a declaration can be read by. `is_on_snap_grid` and `snap_to_grid` take an instant, which
# a wall time and a count of minutes both lack, so neither can read a declaration at all.
DECLARATION_PREDICATES: Final = ("is_wall_time_on_snap_grid", "is_a_snap_multiple")
ENFORCEMENTS: Final = frozenset(f"{SNAP_MODULE}.{name}" for name in DECLARATION_PREDICATES)

# Every root holding code this repository ships. The migration chain and the operational scripts are
# in because a stored declaration is refused from one of those or from nowhere; tests are out
# because the suites read the predicates constantly and none of them enforces anything.
SHIPPED_ROOTS: Final = (
    "packages/*/src",
    "cli/src",
    "packages/syncr-api/alembic",
    "deployments/ops",
)

# The trees the walk has to reach, spelled out rather than read back out of SHIPPED_ROOTS: a
# reach control derived from the globs it is checking cannot fail when one of them narrows.
COVERED_TREES: Final = (
    "packages/syncr-api/src/",
    "packages/syncr-common/src/",
    "packages/syncr-domain/src/",
    "packages/syncr-learning/src/",
    "packages/syncr-solver/src/",
    "cli/src/",
    "packages/syncr-api/alembic/",
    "deployments/ops/",
)

RECORD_SOURCE: Final = "packages/syncr-domain/src/syncr_domain/snap.py"

# One item of the record's enumerated list: the module in double backticks, then what it reads. The
# marker is anchored to the start of a line, so a module named inside a sentence is prose rather
# than a site, and the verb is part of the marker, so a list of anything else is not this list.
_SITE: Final = re.compile(r"^\* ``(?P<module>[\w./-]+)`` reads ", re.MULTILINE)

# What the record must go on saying to be the record. Nothing else in the repository states this
# rule, and the domain comment sweep runs over this file's neighbours, so its deletion has to be a
# red rather than a diff nobody reads. A reword updates both places and the red names the clause.
RECORDED_CLAUSES: Final = (
    ("the declared-duration half", "a declared duration owes the grid"),
    ("the chosen-wall-time half", "a wall time the user chose"),
    ("the exemption, and that it is the only one", "the only exemption"),
)

# A planning citation, which protocol forbids in source and which this file cannot be swept for by
# anything else: the domain sweep skips it so that a sweep cannot delete the record.
_CITATION: Final = re.compile(r"\btickets?\b|\bSP1-[A-Z]+-\d+", re.IGNORECASE)


def repository_root() -> Path:
    """The checkout the imported package came from, which is the tree the walk reads."""
    return Path(syncr_domain.__file__).resolve().parents[4]


def record() -> str:
    """The rule as stated, which is `snap`'s module docstring."""
    stated = snap.__doc__

    assert stated is not None, f"{SNAP_MODULE} carries no module docstring, so it records nothing"
    return stated


def listed_sites(stated: str) -> tuple[str, ...]:
    """Every module the record's enumerated list names, in the order it names them."""
    return tuple(match.group("module") for match in _SITE.finditer(stated))


def shipped_modules(root: Path) -> Mapping[str, Path]:
    """Every Python file this repository ships, by path relative to the root.

    Keyed on the relative path rather than on an import path, because the migration chain and the
    operational scripts are importable as no package's member and would collide.
    """
    found: dict[str, Path] = {}
    for shipped in SHIPPED_ROOTS:
        for source_root in sorted(root.glob(shipped)):
            for path in sorted(source_root.rglob("*.py")):
                found[str(path.relative_to(root))] = path
    return found


def module_of(relative: str) -> str:
    """The dotted module a shipped path imports as, or the path itself when it imports as none."""
    _, marker, tail = relative.partition("/src/")
    if not marker:
        return relative
    return tail.removesuffix(".py").removesuffix("/__init__").replace("/", ".")


def predicates_read(path: Path, *, package: str) -> tuple[str, ...]:
    """Which declaration predicates this module calls, by name.

    Two readings, because one receiver cannot be resolved from imports. A dotted call is qualified
    through the module's own aliases; a call this module could only have reached through the snap
    module is matched on the name alone, which is what makes ``from . import snap`` and a relative
    import of a predicate visible. ``package`` is what such an import resolves against.
    """
    scanned = scan(path, package)
    read = {name.rpartition(".")[2] for name in ENFORCEMENTS & scanned.calls}
    if SNAP_MODULE in scanned.imports:
        read |= set(DECLARATION_PREDICATES) & scanned.attributes
    return tuple(sorted(read))


def enforcing_modules(root: Path) -> Mapping[str, tuple[str, ...]]:
    """Every shipped module that reads a declaration predicate, with the predicates it reads."""
    found: dict[str, tuple[str, ...]] = {}
    for relative, path in shipped_modules(root).items():
        named = module_of(relative)
        read = predicates_read(path, package=named.rpartition(".")[0] or named)
        if read:
            found[named] = read
    return found


def reads_a_declaration_predicate(source: str, path: Path) -> tuple[str, ...]:
    """The same reading, over source that is not in the tree yet."""
    path.write_text(source, encoding="utf-8")
    return predicates_read(path, package="syncr_domain")


# --------------------------------------------------------------------------------
# The controls: which tree the walk read, and how far into it the walk reached
# --------------------------------------------------------------------------------


def test_the_walk_reads_the_checkout_whose_code_this_suite_imports() -> None:
    # The record is read out of the imported module and the sites out of a tree resolved from a
    # path, so a run against a scratch copy could otherwise cross one checkout's list against
    # another checkout's callers and pass on both being wrong.
    assert repository_root() == Path(__file__).resolve().parents[3]


def test_the_walk_reaches_every_tree_a_declaration_could_be_refused_from() -> None:
    # No count is asserted anywhere in this file, deliberately: a floor on the number of modules
    # ranks the walk against whatever the tree holds this week, and the collapse it would catch is
    # the collapse this reach control catches without publishing a figure.
    found = shipped_modules(repository_root())

    reached = {
        tree: [module for module in found if module.startswith(tree)] for tree in COVERED_TREES
    }

    assert {tree: bool(modules) for tree, modules in reached.items()} == dict.fromkeys(
        COVERED_TREES, True
    )


def test_the_walk_reaches_a_nested_module_and_leaves_the_suites_out() -> None:
    # The reach control above is satisfied by one file per tree, so a walk that stopped recursing
    # would pass it. Both named files are load-bearing for the rule: one holds the record and the
    # other sits two directories down inside a package.
    found = shipped_modules(repository_root())

    assert RECORD_SOURCE in found
    assert "packages/syncr-api/src/syncr_api/promotions/service.py" in found
    assert [module for module in found if "/tests/" in module] == []


@pytest.mark.parametrize(
    ("relative", "expected"),
    [
        ("packages/syncr-domain/src/syncr_domain/snap.py", "syncr_domain.snap"),
        ("packages/syncr-api/src/syncr_api/promotions/service.py", "syncr_api.promotions.service"),
        ("packages/syncr-api/src/syncr_api/promotions/__init__.py", "syncr_api.promotions"),
        ("cli/src/syncr_cli/main.py", "syncr_cli.main"),
        ("deployments/ops/dump.py", "deployments/ops/dump.py"),
    ],
    ids=["a module", "a nested module", "a package", "another member", "importable as none"],
)
def test_a_shipped_path_names_the_module_it_imports_as(relative: str, expected: str) -> None:
    assert module_of(relative) == expected


# --------------------------------------------------------------------------------
# The controls on the reading: the shapes a call of a predicate takes, and the shapes
# that name a predicate without being one
# --------------------------------------------------------------------------------

CALL_SHAPES = [
    (
        "an imported predicate",
        "from syncr_domain.snap import is_a_snap_multiple\n"
        "def check(minutes):\n    return is_a_snap_multiple(minutes)\n",
    ),
    (
        "an aliased predicate",
        "from syncr_domain.snap import is_a_snap_multiple as multiple\n"
        "def check(minutes):\n    return multiple(minutes)\n",
    ),
    (
        "the module imported from its package",
        "from syncr_domain import snap\n"
        "def check(minutes):\n    return snap.is_a_snap_multiple(minutes)\n",
    ),
    (
        "the module imported by its full name",
        "import syncr_domain.snap\n"
        "def check(minutes):\n    return syncr_domain.snap.is_a_snap_multiple(minutes)\n",
    ),
    (
        "an aliased module",
        "import syncr_domain.snap as grid\n"
        "def check(minutes):\n    return grid.is_a_snap_multiple(minutes)\n",
    ),
    (
        "a predicate imported relatively",
        "from .snap import is_a_snap_multiple\n"
        "def check(minutes):\n    return is_a_snap_multiple(minutes)\n",
    ),
    (
        "the module imported relatively from its package",
        "from . import snap\ndef check(minutes):\n    return snap.is_a_snap_multiple(minutes)\n",
    ),
]


@pytest.mark.parametrize(("shape", "source"), CALL_SHAPES, ids=[shape for shape, _ in CALL_SHAPES])
def test_the_reading_finds_a_predicate_call_however_it_is_spelled(
    shape: str, source: str, tmp_path: Path
) -> None:
    read = reads_a_declaration_predicate(source, tmp_path / "enforces.py")

    assert read == ("is_a_snap_multiple",), f"the reading missed {shape}"


NOT_CALLS = [
    (
        "an import with no call",
        "from syncr_domain.snap import is_a_snap_multiple\nCHECK = None\n",
    ),
    (
        "the predicate named in prose",
        '"""A duration owes the grid, which is is_a_snap_multiple."""\n',
    ),
    (
        "the instant predicate, which no declaration can be read by",
        "from syncr_domain.snap import is_on_snap_grid\n"
        "def check(moment):\n    return is_on_snap_grid(moment)\n",
    ),
    (
        "a function of the same name that came from somewhere else",
        "from syncr_domain.durations import is_a_snap_multiple\n"
        "def check(minutes):\n    return is_a_snap_multiple(minutes)\n",
    ),
]


@pytest.mark.parametrize(("shape", "source"), NOT_CALLS, ids=[shape for shape, _ in NOT_CALLS])
def test_the_reading_reports_no_enforcement_for(shape: str, source: str, tmp_path: Path) -> None:
    read = reads_a_declaration_predicate(source, tmp_path / "quiet.py")

    assert read == (), f"the reading counted {shape} as an enforcement of the rule"


# --------------------------------------------------------------------------------
# The controls on the record's own reading: which lines are a site and which are prose
# --------------------------------------------------------------------------------


def test_the_record_s_list_is_read_in_order_and_only_from_its_own_marker() -> None:
    stated = (
        "A declaration off the grid names a length no block can hold, and\n"
        "``syncr_domain.routines`` reads neither predicate.\n"
        "\n"
        "* ``syncr_domain.habits`` reads both bounds of a habit's duration.\n"
        "* ``syncr_api.promotions.service`` reads the wall time a promoted pattern names,\n"
        "  and refuses it as a conflict.\n"
        "* ``syncr_domain.templates`` describes something other than a reading.\n"
    )

    assert listed_sites(stated) == ("syncr_domain.habits", "syncr_api.promotions.service")


def test_a_record_that_lists_nothing_reads_as_listing_nothing() -> None:
    # The crossing below compares two sets, so a list that stopped parsing has to come back empty
    # rather than as whatever the last shape happened to match.
    assert listed_sites("A declared duration owes the grid.\n") == ()


# --------------------------------------------------------------------------------
# The rule: the record states it, cites nothing, and lists the sites the tree enforces it at
# --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("clause", "stated"), RECORDED_CLAUSES, ids=[clause for clause, _ in RECORDED_CLAUSES]
)
def test_the_record_still_states(clause: str, stated: str) -> None:
    assert stated in record().lower(), (
        f"{SNAP_MODULE}'s docstring no longer states {clause}, and nothing else in the repository "
        f"states the rule at all"
    )


def test_the_record_cites_no_ticket() -> None:
    # Every other tree's citations are swept by a scan that skips this file, because a sweep that
    # took the record with it would delete the only statement of the rule. So this file's own
    # prose is held here instead.
    source = (repository_root() / RECORD_SOURCE).read_text(encoding="utf-8")

    assert _CITATION.findall(source) == [], (
        f"{RECORD_SOURCE} cites a planning artifact a reader cannot resolve: state what it "
        f"requires instead"
    )


def test_the_citation_reading_would_catch_one() -> None:
    # The control on the reading above, which is a negative assertion over prose that is clean
    # today and so passes whether or not the pattern works.
    assert _CITATION.findall("Tickets 1142, 1151, and 1161 carry the question.") == ["Tickets"]
    assert _CITATION.findall("SP1-INTENT-07 records it.") == ["SP1-INTENT-07"]


def test_the_record_lists_every_module_that_enforces_the_grid_and_no_others() -> None:
    listed = listed_sites(record())
    enforcing = enforcing_modules(repository_root())

    assert set(listed) == set(enforcing), (
        f"{SNAP_MODULE}'s docstring lists {sorted(listed)} and the tree reads a declaration "
        f"predicate in {dict(sorted(enforcing.items()))}. The record is what states the rule, so "
        f"a site the tree gained or lost is an edit to that docstring rather than to this list"
    )


def test_the_record_lists_each_site_once() -> None:
    listed = listed_sites(record())

    assert sorted(listed) == sorted(set(listed))
