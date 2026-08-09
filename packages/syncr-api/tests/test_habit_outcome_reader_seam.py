"""The seam the habit derivations read their log through, and the empty log kept beside it.

``NoRecordedOutcomes`` states in its own docstring that one suite is what keeps it. This measures
that claim: the suite is read out of the docstring, and the suites that CONSTRUCT the stub are read
out of every workspace member's tests. The two have to be the same one file.

**Construction rather than mention, and this census lives outside the suite it measures.** Both
choices exist for the same reason. A census that counted mentions, in the file it names, would
count itself: its own import line would guarantee the answer, and deleting the one test that
actually reads against the stub would leave it green. Keyed to a constructor call, from a module
that never makes one, the named suite's membership comes from the use rather than from the census's
existence. The failure direction is safe too: a construction added here would add a member and go
red, rather than silently standing in for the one that was removed.

What escapes it: a suite reaching the stub through an alias, a ``getattr``, or a subclass. What it
catches is the ordinary way the claim goes stale, which is a second suite instantiating it by name,
or the last one that did stopping.
"""

from __future__ import annotations

import ast
import inspect
import re
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

from syncr_api.habits.outcome_log import NoRecordedOutcomes

if TYPE_CHECKING:
    from collections.abc import Iterable

STUB = NoRecordedOutcomes.__name__

# `packages/syncr-api/src/syncr_api/habits/outcome_log.py` -> `packages/syncr-api`.
STUB_MEMBER = Path(inspect.getfile(NoRecordedOutcomes)).resolve().parents[3]
WORKSPACE_ROOT = STUB_MEMBER.parents[1]
A_SUITE_PATH = re.compile(r"tests/test_\w+\.py")


def member_suite_roots() -> tuple[Path, ...]:
    """Every workspace member's suite directory, read from the root's own member list.

    Read rather than listed, so a member added later comes under the census without this file
    being edited, and so the census covers the set it claims to.
    """
    declared = tomllib.loads((WORKSPACE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    members: list[str] = declared["tool"]["uv"]["workspace"]["members"]
    return tuple(WORKSPACE_ROOT / member / "tests" for member in members)


def suites_constructing(symbol: str, roots: Iterable[Path]) -> frozenset[Path]:
    """Every suite under ``roots`` that calls ``symbol`` as a constructor.

    Parsed rather than matched as text, so the name inside an import, an attribute read or a string
    literal is not a use. The text check ahead of the parse is a filter on the 270-odd suites this
    walks, and it changes no answer: a file that never spells the name cannot call it.

    Returns data rather than asserting, so the census and its controls drive one scan.
    """
    found = []
    for root in roots:
        for path in sorted(root.glob("test_*.py")):
            source = path.read_text(encoding="utf-8")
            if symbol not in source:
                continue
            if any(_is_a_call_of(node, symbol) for node in ast.walk(ast.parse(source))):
                found.append(path)
    return frozenset(found)


def _is_a_call_of(node: ast.AST, symbol: str) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == symbol


def test_the_suite_the_empty_log_is_kept_for_is_the_only_one_that_uses_it() -> None:
    stated = set(A_SUITE_PATH.findall(NoRecordedOutcomes.__doc__ or ""))

    using = suites_constructing(STUB, member_suite_roots())

    assert len(stated) == 1, f"the stub names {sorted(stated)} rather than one suite"
    assert using == {STUB_MEMBER / stated.pop()}, f"the suites constructing it are {sorted(using)}"


def test_the_census_sees_a_user_in_any_member(tmp_path: Path) -> None:
    """The control. A census blind to a second user would certify the claim above forever."""
    one, two = tmp_path / "one" / "tests", tmp_path / "two" / "tests"
    for root in (one, two):
        root.mkdir(parents=True)
        (root / "test_reads_nothing.py").write_text(f"log = {STUB}()\n", encoding="utf-8")
    (one / "test_reads_the_log.py").write_text("log = HabitOutcomeLog()\n", encoding="utf-8")

    found = suites_constructing(STUB, (one, two))

    assert found == {one / "test_reads_nothing.py", two / "test_reads_nothing.py"}


def test_a_suite_that_only_names_the_stub_is_not_counted_as_using_it(tmp_path: Path) -> None:
    """The other control, and the boundary the census is keyed to.

    An import, an attribute read and the name in a string are what this module itself holds. If any
    of them counted, this module would be a user of the stub and the census would be certifying its
    own existence.
    """
    root = tmp_path / "tests"
    root.mkdir(parents=True)
    (root / "test_only_names_it.py").write_text(
        f"from syncr_api.habits.outcome_log import {STUB}\n"
        f"doc = {STUB}.__doc__\n"
        f'named = "{STUB}"\n',
        encoding="utf-8",
    )

    assert suites_constructing(STUB, (root,)) == frozenset()
