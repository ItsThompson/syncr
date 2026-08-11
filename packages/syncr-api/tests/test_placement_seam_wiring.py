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

What escapes this: an assembler bound by assignment rather than imported (``Composer =
WeekAssembler`` and then ``Composer(...)``), and a second composition whose ``placements`` keyword
is not a direct call, such as one handed an already-built reader or a helper's return. Both
spellings of a direct construction are covered for the assembler, the bare name and the
module-qualified one, plus any local name an ``import from`` binds it to. A reader under another
name does not hide, whether by alias, subclass or ``getattr``: the mapping asserts the reader's
exact name, so such a wiring fails loudly rather than passing quietly. What is left is a false
sentence about the seam that is not one of the statements named below.

**Two shapes a stub takes in a suite are refused as well**: a class defined in front of the reader's
own name, and a fixture whose body does nothing, which any number of signatures can declare while
nothing happens. Both are stated over every workspace member's suite directory and over every Python
file in it, because a rule over one member, or over the files named ``test_*.py`` alone, is
satisfied by writing the same thing next door. Neither shape is visible to the suite that holds it.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from syncr_api.plans import injection
from syncr_api.plans.assembler import WeekAssembler
from syncr_api.plans.placements import StoredPlacements
from tests.source_census import imported_as, named
from tests.test_habit_outcome_reader_seam import member_suite_roots

if TYPE_CHECKING:
    from collections.abc import Iterable

ASSEMBLER = WeekAssembler.__name__
ASSEMBLER_MODULE = WeekAssembler.__module__
SEAM_KEYWORD = "placements"
PRODUCTION_READER = StoredPlacements.__name__
READER_MODULE = StoredPlacements.__module__

# `packages/syncr-api/tests/test_placement_seam_wiring.py` -> `packages/syncr-api`. Taken from THIS
# FILE rather than from the imported package, so the precondition below crosses the tree this
# checkout holds against the tree the interpreter resolved: in a workspace whose editable installs
# point at another checkout those are two different questions.
MEMBER = Path(__file__).resolve().parents[1]
SOURCE = MEMBER / "src" / "syncr_api"
WIRING = "plans/injection.py"

# The two modules that describe the seam in prose: the path that classifies a candidate against the
# live plan, and the suite that drives it.
DESCRIBING_THE_SEAM = (
    SOURCE / "solving" / "dispatch.py",
    MEMBER / "tests" / "test_solve_runner_integration.py",
)

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
        relative = str(module.relative_to(source_root))
        composing = frozenset({ASSEMBLER}) | imported_as(
            tree, module=ASSEMBLER_MODULE, names=(ASSEMBLER,)
        )
        found.extend(
            Wiring(relative, reader, _imported_from(tree, reader))
            for node in ast.walk(tree)
            if (reader := _seam_of(node, composing)) is not None
        )
    return found


def _seam_of(node: ast.AST, composing: frozenset[str]) -> str | None:
    """The class this node's placement seam is constructed from, if it composes an assembler.

    ``composing`` holds every local name this source can reach the assembler by, so a
    module-qualified call and an ``as`` alias are read as compositions rather than passed over. A
    keyword bound to anything but a call has no class to name.
    """
    if not isinstance(node, ast.Call) or named(node.func) not in composing:
        return None
    bound = {keyword.arg: keyword.value for keyword in node.keywords}
    seam = bound.get(SEAM_KEYWORD)
    if not isinstance(seam, ast.Call):
        return None
    return named(seam.func)


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
        stated = [one for one in denials() if one in source]
        if stated:
            found[path] = stated
    return found


def describing_the_seam() -> tuple[Path, ...]:
    """The modules whose prose rests on the seam's answer, with their number asserted.

    A rule driven by a hand-written tuple is only as wide as the tuple, and its control iterates the
    same tuple, so dropping an entry narrows the rule and its control together and nothing reddens.
    """
    assert len(DESCRIBING_THE_SEAM) == 2, (
        "a module that describes the seam was dropped from the rule"
    )
    return DESCRIBING_THE_SEAM


def denials() -> tuple[str, ...]:
    """The statements a wired seam makes false, with their number asserted, for the same reason."""
    assert len(DENIALS_OF_THE_WIRING) == 4, "a denial was dropped from the scan"
    return DENIALS_OF_THE_WIRING


def suite_roots() -> tuple[Path, ...]:
    """Every workspace member's suite directory, read from the root manifest.

    One reading, shared by both rules stated over the suites, so the two cannot come to cover
    different trees while each looks like it covers the suites.
    """
    roots = tuple(member_suite_roots())
    assert len(roots) > 1, f"the member list resolved to {roots}, so these rules cover one member"
    missing = [str(root) for root in roots if not root.is_dir()]
    assert missing == [], (
        f"a member's suite directory is missing, so nothing was read there: {missing}"
    )
    return roots


def classes_named(name: str, roots: Iterable[Path]) -> frozenset[Path]:
    """Every file under ``roots`` that DEFINES a class of that name.

    A definition rather than a mention, so the import and the constructor call a suite driving the
    production reader makes are not counted: what this finds is a local class standing in front of
    the real one.

    Every Python file rather than the ones named ``test_*.py``: a suite's doubles live beside it in
    modules pytest never collects directly, and that is where a placement double would go.
    """
    found = []
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            if name not in source:
                continue
            if any(
                isinstance(node, ast.ClassDef) and node.name == name
                for node in ast.walk(ast.parse(source))
            ):
                found.append(path)
    return frozenset(found)


def no_op_fixtures(roots: Iterable[Path]) -> frozenset[tuple[Path, str]]:
    """Every fixture under ``roots`` whose body does nothing at all.

    A docstring, a ``pass`` or an ellipsis is a body that runs and changes nothing, so the
    parameters such a fixture declares are the whole of it and a case declaring the fixture gets no
    behaviour.
    """
    found: list[tuple[Path, str]] = []
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            found.extend(
                (path, node.name)
                for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                and _is_a_fixture(node)
                and _does_nothing(node)
            )
    return frozenset(found)


def _is_a_fixture(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Whether pytest will treat this function as a fixture, under either decorator spelling."""
    for one in node.decorator_list:
        named = one.func if isinstance(one, ast.Call) else one
        if isinstance(named, ast.Attribute) and named.attr == "fixture":
            return True
        if isinstance(named, ast.Name) and named.id == "fixture":
            return True
    return False


def _does_nothing(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Whether every statement of this body is a bare constant or a ``pass``."""
    return all(
        isinstance(one, ast.Pass)
        or (isinstance(one, ast.Expr) and isinstance(one.value, ast.Constant))
        for one in node.body
    )


def test_the_one_composition_of_the_assembler_wires_the_stored_reader(source_root: Path) -> None:
    """The wiring, as an exact mapping, so a second composition is a diff a reviewer reads.

    The import is asserted beside the name because the name alone is satisfied by a class defined in
    the composing module, and that is what a stub wired back in would look like.
    """
    wired = seam_wirings(source_root)

    assert wired, "no week assembler is composed in this package, so this asserted nothing"
    assert [(one.module, one.reader) for one in wired] == [(WIRING, PRODUCTION_READER)]
    assert wired[0].imported_from == READER_MODULE


def test_the_tree_walked_is_the_one_this_checkout_holds(source_root: Path) -> None:
    """The precondition, and its two sides are resolved from different places.

    ``source_root`` comes from the imported package and ``MEMBER`` from this file's own path, so a
    run whose interpreter answers with another checkout's ``syncr_api`` fails here instead of
    certifying that checkout's wiring against this checkout's statements.
    """
    assert Path(injection.__file__).resolve() == (SOURCE / WIRING).resolve()
    assert source_root.resolve() == SOURCE.resolve()
    assert PRODUCTION_READER in (SOURCE / WIRING).read_text(encoding="utf-8")


def test_the_walk_reports_a_seam_wired_to_something_else(tmp_path: Path) -> None:
    """The control on the reading: it names what the keyword is bound to, not what it expects.

    Three spellings of the composition, because a reading that saw only the bare name would report
    one wiring out of three and its exact-mapping case would still pass.
    """
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
    (tmp_path / "qualified.py").write_text(
        f"from elsewhere import NoPlacements\n"
        f"import {ASSEMBLER_MODULE} as composer\n"
        f"def build() -> object:\n"
        f"    return composer.{ASSEMBLER}({SEAM_KEYWORD}=NoPlacements())\n",
        encoding="utf-8",
    )
    (tmp_path / "aliased.py").write_text(
        f"from elsewhere import NoPlacements\n"
        f"from {ASSEMBLER_MODULE} import {ASSEMBLER} as Composer\n"
        f"def build() -> object:\n"
        f"    return Composer({SEAM_KEYWORD}=NoPlacements())\n",
        encoding="utf-8",
    )

    found = seam_wirings(tmp_path)

    assert found == [
        Wiring("aliased.py", "NoPlacements", "elsewhere"),
        Wiring("local_stub.py", "NoPlacements", None),
        Wiring("qualified.py", "NoPlacements", "elsewhere"),
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


def test_every_module_that_describes_the_seam_names_the_reader() -> None:
    """Each module whose prose rests on the seam's answer says which reader answers.

    Keyed on the reader's own name rather than on a sentence, so rewording a paragraph is free and
    dropping the seam out of one is not. Read from the tree rather than through ``__doc__``, for the
    reason the scan below reads the tree: what is under test is what this checkout says.
    """
    silent = [
        str(path.relative_to(MEMBER))
        for path in describing_the_seam()
        if PRODUCTION_READER
        not in (ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or "")
    ]

    assert silent == [], f"{silent} rest on the seam's answer and do not say which reader answers"


def test_the_scan_finds_every_denial_it_names(tmp_path: Path) -> None:
    """The control on the crossing. A scan blind to the sentences it lists refuses nothing."""
    written = {}
    for index, denial in enumerate(denials()):
        path = tmp_path / f"stated_{index}.py"
        path.write_text(f'"""A docstring that says the {denial} today."""\n', encoding="utf-8")
        written[path] = [denial]
    (tmp_path / "silent.py").write_text('"""Says nothing about the seam."""\n', encoding="utf-8")

    assert denying_the_wiring(sorted(tmp_path.rglob("*.py"))) == written


def test_no_suite_defines_a_class_named_after_the_production_reader() -> None:
    """A local class of that name shadows the seam it looks like it drives, and reads nothing."""
    defining = classes_named(PRODUCTION_READER, suite_roots())

    assert defining == frozenset(), (
        f"{sorted(str(one) for one in defining)} define a class named after the production reader, "
        "which stands in front of it while reading nothing"
    )


def test_the_class_scan_sees_a_definition_in_any_member_and_ignores_a_use(tmp_path: Path) -> None:
    """Its control, three ways: a second member, a file pytest does not collect, and a mere use.

    The file not named ``test_*.py`` is the case that matters, because the doubles of this member's
    suites live in exactly such a file and that is where a placement double would be written.
    """
    one, two = tmp_path / "one" / "tests", tmp_path / "two" / "tests"
    for root in (one, two):
        root.mkdir(parents=True)
    (one / "suite_fakes.py").write_text(f"class {PRODUCTION_READER}:\n    pass\n", encoding="utf-8")
    (two / "test_defines_one.py").write_text(
        f"class {PRODUCTION_READER}:\n    pass\n", encoding="utf-8"
    )
    (one / "test_drives_the_real_one.py").write_text(
        f"from {READER_MODULE} import {PRODUCTION_READER}\n"
        f"seam = {PRODUCTION_READER}(1, 2, 3, 4)\n",
        encoding="utf-8",
    )

    assert classes_named(PRODUCTION_READER, (one, two)) == {
        one / "suite_fakes.py",
        two / "test_defines_one.py",
    }


def test_no_fixture_of_any_member_has_a_body_that_does_nothing() -> None:
    """The other shape: a fixture a signature declares and that substitutes nothing when it runs."""
    idle = no_op_fixtures(suite_roots())

    assert idle == frozenset(), (
        f"{sorted((str(path), name) for path, name in idle)} run and change nothing, so a case can "
        "declare one and get no behaviour. A fixture that only composes others returns or yields "
        "what it composed."
    )


def test_the_fixture_reading_sees_an_empty_body_and_leaves_a_working_one(tmp_path: Path) -> None:
    """Its control, over a second member, both decorator spellings, and a conftest."""
    one, two = tmp_path / "one" / "tests", tmp_path / "two" / "tests"
    for root in (one, two):
        root.mkdir(parents=True)
    (one / "test_idle.py").write_text(
        "import pytest\nfrom pytest import fixture\n\n\n"
        '@pytest.fixture\ndef says_only_this() -> None:\n    """A docstring and no body."""\n\n\n'
        "@fixture()\ndef passes() -> None:\n    pass\n\n\n"
        "@pytest.fixture\ndef reads_something() -> int:\n    return 1\n\n\n"
        "def not_a_fixture() -> None:\n    pass\n",
        encoding="utf-8",
    )
    (two / "conftest.py").write_text(
        "import pytest\n\n\n@pytest.fixture\ndef also_idle() -> None:\n    ...\n",
        encoding="utf-8",
    )

    assert no_op_fixtures((one, two)) == {
        (one / "test_idle.py", "says_only_this"),
        (one / "test_idle.py", "passes"),
        (two / "conftest.py", "also_idle"),
    }


def test_both_rules_over_the_suites_take_the_same_roots() -> None:
    """One input set for both rules, read out of this module's own source.

    Two scans over two different sets is how a name reaches the one file only one of them reads, so
    the roots come from a single function and each rule is checked to take them from it.
    """
    tree = ast.parse(THE_SCANS_OWN_FILE.read_text(encoding="utf-8"))
    taking = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and any(
            isinstance(call, ast.Call) and named(call.func) == suite_roots.__name__
            for call in ast.walk(node)
        )
    }
    roots = suite_roots()

    assert {
        test_no_suite_defines_a_class_named_after_the_production_reader.__name__,
        test_no_fixture_of_any_member_has_a_body_that_does_nothing.__name__,
    } <= taking
    assert MEMBER / "tests" in roots, "this member's own suites are outside the scanned roots"
    assert all(root.name == "tests" for root in roots)
