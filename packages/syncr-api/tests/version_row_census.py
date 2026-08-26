"""Every version-row caller, walked against the rule the row states on ``hold``.

The rule: whoever takes the week's input-version row takes it FIRST. The row is the one lock
this api holds across several writes, so the order two transactions take their rows in is
decided entirely by where this one sits; a caller that writes another table before taking it
inverts the order against every caller that does not, and two such transactions deadlock. The
rule is stated on :meth:`~syncr_api.plans.versions.WeekInputVersionRepository.hold`, and a
rule a reader can only obey by remembering it degrades silently as callers arrive. This
census is the reading that examines whatever callers exist whenever it runs.

**The population is discovered, not listed.** Every module under the source root is parsed,
and each ``bump``/``hold`` receiver is resolved to a type through the annotations the file
already carries (the receiver typing lives in
:mod:`tests.version_row_receiver_types`): a constructor parameter annotated with the
repository or with an adapter composed around it, filed into an attribute by ``__init__`` or
into a local by direct assignment. A new caller arrives as a new entry in
:func:`version_row_calls` without anyone remembering to add it to a list, and the count the
test asserts moves with it.

**What the reading accepts as a take.** ``hold`` spells the lock and ``bump`` takes the same
row to raise it, so both order whatever follows them; ``holds_version``, the solve's
conditional-write guard, locks the row before anything the adopted result writes, so it counts
too. A write may also sit above or below the function the call site lives in: those callers
are what the test's recorded resolutions account for, each with its reason.

**What this cannot see, stated because a census that hides its edge is worse than none.**
The walk reads method bodies of classes only, so a caller at module level -- a free function
taking a row or a session -- produces no call site, moves no count, and is never checked for
order; today every caller is a class method, which is what keeps the measured figure honest.
Receivers are typed through annotations and direct assignments, so a row or a table reached by
untyped inference, a factory call (``self._adoption(session).adopt(...)``), or a helper's
return is invisible to the ordering reading too. A collaborator counts as a table only when
its type name ends in ``Repository``, and on such a collaborator everything but
:data:`READ_METHODS` counts as a write: an undeclared read method fails the walk loudly
instead of silently passing for one.

Every helper returns data rather than asserting, so the real tree, the test's recorded
resolutions, and a fixture planted to break the rule all drive one walk. A census with no
positive control passes forever once it has gone blind.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, NamedTuple

from tests.version_row_receiver_types import (
    VERSION_ROW_REPOSITORY,
    annotation_kind,
    annotation_of,
    attribute_annotations,
    row_types,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

# The methods a take of the row arrives as. ``bump`` and ``hold`` spell the lock directly;
# ``holds_version`` is the solve's conditional-write guard, which takes the row FOR UPDATE
# before anything the adopted result writes.
TAKE_METHODS = frozenset({"bump", "hold", "holds_version"})

# The two methods the walk counts callers of, which is the population the rule speaks to.
CALLED_METHODS = frozenset({"bump", "hold"})

# Collaborator calls that touch no row another transaction could be waiting under. Everything
# else on a Repository-typed collaborator counts as a write, so an undeclared read method
# fails the walk instead of silently reading as harmless.
READ_METHODS = frozenset(
    {
        "find",
        "for_week",
        "for_weeks",
        "list_all",
        "latest",
        "active",
        "read",
        "current",
        "holds_a_plan",
        "tracked_weeks",
        "tracked_version",
        "lock",
    }
)


class VersionRowCall(NamedTuple):
    """One call site of ``bump`` or ``hold`` on the week's version row."""

    module: str
    owner: str
    function: str
    line: int
    method: str

    @property
    def site(self) -> tuple[str, str, str]:
        """Where the call sits, without the line a formatting change moves."""
        return (self.module, f"{self.owner}.{self.function}", self.method)


class PrecedingWrite(NamedTuple):
    """One write to another table sitting before the caller's first take of the row."""

    module: str
    owner: str
    function: str
    collaborator: str
    called: str
    line: int
    taken_at: int

    @property
    def site(self) -> tuple[str, str]:
        """The caller the write sits in, keyed the way a resolution records it."""
        return (self.module, f"{self.owner}.{self.function}")


def version_row_calls(source_root: Path) -> tuple[VersionRowCall, ...]:
    """Every ``bump``/``hold`` call site on the version row, in a stable order."""
    calls, _ = _walk(source_root)
    return tuple(sorted(calls))


def lock_order_violations(source_root: Path) -> tuple[PrecedingWrite, ...]:
    """Every caller reaching a write to another table before its first take of the row."""
    _, violations = _walk(source_root)
    return tuple(sorted(violations))


def _walk(source_root: Path) -> tuple[list[VersionRowCall], list[PrecedingWrite]]:
    """The one pass both readings are taken over, so they cannot disagree about the tree."""
    trees = {
        path: ast.parse(path.read_text(encoding="utf-8"))
        for path in sorted(source_root.rglob("*.py"))
    }
    types = row_types(trees)
    attributes = attribute_annotations(trees)
    calls: list[VersionRowCall] = []
    violations: list[PrecedingWrite] = []
    for path, tree in trees.items():
        module = path.relative_to(source_root).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for function in node.body:
                if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                scope = _MethodScope(
                    attributes=attributes.get(node.name, {}),
                    locals_=_local_types(function, types),
                )
                taken_at = _first_take(function, scope, types)
                if taken_at is None:
                    # No take here orders nothing: this function never acquires the row, so
                    # its writes are ordered by whoever called it, above or below.
                    continue
                for statement in ast.walk(function):
                    if not (
                        isinstance(statement, ast.Call)
                        and isinstance(statement.func, ast.Attribute)
                    ):
                        continue
                    kind, display = scope.receiver(statement.func.value, types)
                    if kind == "version":
                        if (
                            statement.func.attr in CALLED_METHODS
                            and node.name != VERSION_ROW_REPOSITORY
                        ):
                            # The declaring repository's own internal bump is the rule's
                            # subject, not a caller under it.
                            calls.append(
                                VersionRowCall(
                                    module=module,
                                    owner=node.name,
                                    function=function.name,
                                    line=statement.lineno,
                                    method=statement.func.attr,
                                )
                            )
                    elif (
                        kind is not None
                        and statement.func.attr not in READ_METHODS
                        and statement.lineno < taken_at
                    ):
                        violations.append(
                            PrecedingWrite(
                                module=module,
                                owner=node.name,
                                function=function.name,
                                collaborator=kind,
                                called=f"{display}.{statement.func.attr}",
                                line=statement.lineno,
                                taken_at=taken_at,
                            )
                        )
    return calls, violations


class _MethodScope:
    """The names one method's body resolves receivers through.

    Attributes come from the class's ``__init__`` filings; locals come from annotated
    parameters and direct constructor assignments. Anything else reads as untyped and stays
    outside the walk, which the module docstring states rather than hides.
    """

    def __init__(self, *, attributes: Mapping[str, str], locals_: Mapping[str, str]) -> None:
        self._attributes = attributes
        self._locals = locals_

    def receiver(self, node: ast.expr, row_types: frozenset[str]) -> tuple[str | None, str]:
        """What a receiver expression resolves to, and how to name it in a report.

        ``"version"`` is the row itself; anything else returned is a collaborator type name.
        """
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "self":
                annotation = self._attributes.get(node.attr)
                return annotation_kind(annotation, row_types), f"self.{node.attr}"
            return None, ""
        if isinstance(node, ast.Name):
            return self._locals.get(node.id), node.id
        return None, ""


def _local_types(
    function: ast.FunctionDef | ast.AsyncFunctionDef, types: frozenset[str]
) -> dict[str, str]:
    """The method's own typed names: annotated parameters and constructed locals."""
    found: dict[str, str] = {}
    for arg in function.args.args + function.args.kwonlyargs:
        kind = annotation_kind(annotation_of(arg), types)
        if kind is not None:
            found[arg.arg] = kind
    for statement in ast.walk(function):
        if not (
            isinstance(statement, ast.Assign)
            and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Name)
        ):
            continue
        kind = annotation_kind(statement.value.func.id, types)
        if kind is None:
            continue
        for target in statement.targets:
            if isinstance(target, ast.Name):
                found[target.id] = kind
    return found


def _first_take(
    function: ast.FunctionDef | ast.AsyncFunctionDef, scope: _MethodScope, types: frozenset[str]
) -> int | None:
    """The earliest line the row is taken at, or ``None`` while the function takes nothing."""
    taken: list[int] = []
    for statement in ast.walk(function):
        if not (isinstance(statement, ast.Call) and isinstance(statement.func, ast.Attribute)):
            continue
        if statement.func.attr not in TAKE_METHODS:
            continue
        kind, _ = scope.receiver(statement.func.value, types)
        if kind == "version":
            taken.append(statement.lineno)
    return min(taken, default=None)
