"""Which reader the assembler's placement seam is wired to, read out of the tree rather than stated.

The seam answers "what is already committed in this week", and the whole authority rule rests on the
answer: a candidate is classified against the live plan the assembly read, so a seam that answered
with nothing would classify every candidate as a first plan for its week and no moved block would
ever be held back. That makes the wiring a claim several docstrings state in prose, and prose is
what goes stale.

**The composition is read from the source, not imported.** What is under test is which class the
keyword is bound to at the one place a week assembler is composed, and the module that composes it
also has to have imported that class from the module that defines it: a local class of the same name
satisfies a name check while reading nothing, which is the shape a stub takes.

**The prose is crossed against that reading rather than asserted on its own.** The scan refuses the
statements a wired seam makes false, over this member's own sources and suites, and it runs only
after the wiring has been read: unwire the seam and the wiring guard fails first, which is the order
that keeps the two from disagreeing.

What escapes this: a reader reached through an alias, a ``getattr`` or a subclass; a second seam
wired inside a helper that returns the reader rather than constructing it at the keyword; and any
false sentence about the seam that is not one of the statements named below. What it catches is the
ordinary way this goes wrong, which is a stub wired back in and a docstring left describing it.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from syncr_api.plans import injection
from syncr_api.plans.assembler import WeekAssembler
from syncr_api.plans.placements import StoredPlacements
from syncr_api.solving import dispatch

if TYPE_CHECKING:
    from collections.abc import Iterable

ASSEMBLER = WeekAssembler.__name__
SEAM_KEYWORD = "placements"
PRODUCTION_READER = StoredPlacements.__name__
READER_MODULE = StoredPlacements.__module__

# `packages/syncr-api/src/syncr_api/plans/injection.py` -> `packages/syncr-api`.
MEMBER = Path(inspect.getfile(injection)).resolve().parents[3]
WIRING = "plans/injection.py"

# The statements a wired seam makes false. Each is a claim about what the seam answers or about what
# the answer costs, and the scan below refuses all four wherever a source or a suite writes one.
DENIALS_OF_THE_WIRING = (
    "placement seam answers with no live plan",
    "placement seam, which answers with nothing",
    "placement seam makes unreachable",
    "Whoever supplies the production reader",
)

# This module holds those statements as data, so it is the one file the scan may not read. Stated as
# a path rather than a name, and asserted to be a file the scan would otherwise have covered.
THE_SCANS_OWN_FILE = Path(__file__).resolve()


class Wiring(NamedTuple):
    """One composition of the week assembler: where it is, and what its placement seam reads."""

    module: str
    reader: str
    imported_from: str | None


def seam_wirings(source_root: Path) -> list[Wiring]:
    """Every composition of the week assembler under ``source_root``, with the seam it binds.

    The one reader of the tree. Returns data rather than asserting, so the census, its controls and
    the prose crossing all drive one walk.
    """
    found: list[Wiring] = []
    for module in sorted(source_root.rglob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        named = str(module.relative_to(source_root))
        found.extend(
            Wiring(named, reader, _imported_from(tree, reader))
            for node in ast.walk(tree)
            if (reader := _seam_of(node)) is not None
        )
    return found


def _seam_of(node: ast.AST) -> str | None:
    """The class this node's placement seam is constructed from, if it composes an assembler.

    A keyword bound to anything but a call has no class to name: a seam handed an already-built
    reader is invisible here, which is the residue the module docstring states.
    """
    if not isinstance(node, ast.Call) or getattr(node.func, "id", None) != ASSEMBLER:
        return None
    bound = {keyword.arg: keyword.value for keyword in node.keywords}
    seam = bound.get(SEAM_KEYWORD)
    if not isinstance(seam, ast.Call):
        return None
    return getattr(seam.func, "id", None) or getattr(seam.func, "attr", None)


def _imported_from(tree: ast.Module, name: str) -> str | None:
    """The module a source imported ``name`` from, or nothing when it defines or shadows it."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and any(
            (alias.asname or alias.name) == name for alias in node.names
        ):
            return node.module
    return None


def sources_and_suites() -> tuple[Path, ...]:
    """Every Python file of this member, which is where the seam is described.

    Both trees, because the sentences that go stale are written on the production path and in the
    suite that drives it, and a rule stated over one of them would leave the other free.
    """
    found = tuple(sorted((MEMBER / "src").rglob("*.py")) + sorted((MEMBER / "tests").rglob("*.py")))
    assert found, f"no Python file was found under {MEMBER}, so the scan below covers nothing"
    return found


def denying_the_wiring(files: Iterable[Path]) -> dict[Path, list[str]]:
    """Which files state one of the denials, and which ones each states."""
    found: dict[Path, list[str]] = {}
    for path in files:
        source = path.read_text(encoding="utf-8")
        stated = [one for one in DENIALS_OF_THE_WIRING if one in source]
        if stated:
            found[path] = stated
    return found


def classes_named(name: str, roots: Iterable[Path]) -> frozenset[Path]:
    """Every suite under ``roots`` that DEFINES a class of that name.

    A definition rather than a mention, so the import and the constructor call a suite driving the
    production reader makes are not counted: what this finds is a local class standing in front of
    the real one.
    """
    found = []
    for root in roots:
        for path in sorted(root.rglob("test_*.py")):
            source = path.read_text(encoding="utf-8")
            if name not in source:
                continue
            if any(
                isinstance(node, ast.ClassDef) and node.name == name
                for node in ast.walk(ast.parse(source))
            ):
                found.append(path)
    return frozenset(found)


def test_the_one_composition_of_the_assembler_wires_the_stored_reader(source_root: Path) -> None:
    """The wiring, as an exact mapping, so a second composition is a diff a reviewer reads.

    The import is asserted beside the name because the name alone is satisfied by a class defined in
    the composing module, and that is what a stub wired back in would look like.
    """
    wired = seam_wirings(source_root)

    assert wired, "no week assembler is composed in this package, so this asserted nothing"
    assert [(one.module, one.reader) for one in wired] == [(WIRING, PRODUCTION_READER)]
    assert wired[0].imported_from == READER_MODULE


def test_the_tree_walked_is_the_one_this_suite_imported(source_root: Path) -> None:
    """The precondition. A walk over a tree nobody runs would certify the claim above forever."""
    assert Path(injection.__file__).resolve() == (source_root / WIRING).resolve()
    assert PRODUCTION_READER in (source_root / WIRING).read_text(encoding="utf-8")


def test_the_walk_reports_a_seam_wired_to_something_else(tmp_path: Path) -> None:
    """The control on the reading: it names what the keyword is bound to, not what it expects."""
    (tmp_path / "wiring.py").write_text(
        "from elsewhere import NoPlacements\n"
        f"def build() -> object:\n"
        f"    return {ASSEMBLER}(settings=None, {SEAM_KEYWORD}=NoPlacements())\n",
        encoding="utf-8",
    )
    (tmp_path / "local_stub.py").write_text(
        f"class NoPlacements:\n    pass\n\n\n"
        f"def build() -> object:\n"
        f"    return {ASSEMBLER}({SEAM_KEYWORD}=NoPlacements())\n",
        encoding="utf-8",
    )

    found = seam_wirings(tmp_path)

    assert found == [
        Wiring("local_stub.py", "NoPlacements", None),
        Wiring("wiring.py", "NoPlacements", "elsewhere"),
    ]


def test_a_tree_that_only_names_the_seam_reports_no_wiring(tmp_path: Path) -> None:
    """The other control, and the boundary the reading is keyed to.

    An import, an attribute read, the name in a string, and a call that is not an assembler's are
    what this module and the suites around it hold. If any of them counted, the mapping above would
    be certifying a composition nobody wrote.
    """
    (tmp_path / "mentions.py").write_text(
        f"from {READER_MODULE} import {PRODUCTION_READER}\n"
        f"doc = {PRODUCTION_READER}.__doc__\n"
        f'named = "{SEAM_KEYWORD}={PRODUCTION_READER}()"\n'
        f"seam = {PRODUCTION_READER}()\n"
        f"other = SomethingElse({SEAM_KEYWORD}={PRODUCTION_READER}())\n",
        encoding="utf-8",
    )

    assert seam_wirings(tmp_path) == []


def test_no_source_or_suite_of_this_member_denies_the_wiring(source_root: Path) -> None:
    """The prose crossing, in the order that keeps it honest: read the wiring, then refuse a denial.

    A statement that the seam answers with nothing is false while the composition above binds the
    stored reader, and a false statement about this seam is what let the authority rule read as
    unreachable in three places while it was being driven end to end.
    """
    wired = seam_wirings(source_root)
    assert [one.reader for one in wired] == [PRODUCTION_READER]

    scanned = [path for path in sources_and_suites() if path != THE_SCANS_OWN_FILE]
    denying = denying_the_wiring(scanned)

    assert len(scanned) == len(sources_and_suites()) - 1, "the scan read its own statements"
    assert denying == {}, f"these deny a seam that is wired: { {str(one) for one in denying} }"


def test_the_dispatch_names_the_reader_its_classification_rests_on() -> None:
    """The path that classifies a candidate says which reader the plan it compares against comes
    from.

    Keyed on the reader's own name rather than on a sentence, so rewording the paragraph is free and
    dropping the seam out of it is not.
    """
    assert PRODUCTION_READER in (dispatch.__doc__ or "")


def test_the_scan_finds_every_denial_it_names(tmp_path: Path) -> None:
    """The control on the crossing. A scan blind to the sentences it lists refuses nothing."""
    written = {}
    for index, denial in enumerate(DENIALS_OF_THE_WIRING):
        path = tmp_path / f"stated_{index}.py"
        path.write_text(f'"""A docstring that says the {denial} today."""\n', encoding="utf-8")
        written[path] = [denial]
    (tmp_path / "silent.py").write_text('"""Says nothing about the seam."""\n', encoding="utf-8")

    assert denying_the_wiring(sorted(tmp_path.rglob("*.py"))) == written


def test_no_suite_defines_a_class_named_after_the_production_reader() -> None:
    """A local class of that name shadows the seam it looks like it drives, and reads nothing."""
    assert classes_named(PRODUCTION_READER, (MEMBER / "tests",)) == frozenset()


def test_the_class_scan_sees_a_definition_and_ignores_a_use(tmp_path: Path) -> None:
    """Its control, both ways: the definition is found, and importing or calling it is not one."""
    root = tmp_path / "tests"
    root.mkdir(parents=True)
    (root / "test_defines_one.py").write_text(
        f"class {PRODUCTION_READER}:\n    pass\n", encoding="utf-8"
    )
    (root / "test_drives_the_real_one.py").write_text(
        f"from {READER_MODULE} import {PRODUCTION_READER}\n"
        f"seam = {PRODUCTION_READER}(1, 2, 3, 4)\n",
        encoding="utf-8",
    )

    assert classes_named(PRODUCTION_READER, (root,)) == {root / "test_defines_one.py"}
