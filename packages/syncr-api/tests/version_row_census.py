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
already carries: a constructor parameter annotated with the repository or with an adapter
composed around it, filed into an attribute by ``__init__`` or into a local by direct
assignment. A new caller arrives as a new entry in :func:`version_row_calls` without anyone
remembering to add it to a list, and the count the test asserts moves with it.

**What the reading accepts as a take.** ``hold`` spells the lock and ``bump`` takes the same
row to raise it, so both order whatever follows them; ``holds_version``, the solve's
conditional-write guard, locks the row before anything the adopted result writes, so it counts
too. A write may also sit above or below the function the call site lives in: those callers
are what the test's recorded resolutions account for, each with its reason.

**What this cannot see, stated because a census that hides its edge is worse than none.**
Receivers are typed through annotations and direct assignments, so a row or a table reached by
untyped inference, a factory call (``self._adoption(session).adopt(...)``), or a helper's
return is invisible to the ordering reading. A collaborator counts as a table only when its
type name ends in ``Repository``, and on such a collaborator everything but
:data:`READ_METHODS` counts as a write: an undeclared read method fails the walk loudly
instead of silently passing for one.

Every helper returns data rather than asserting, so the real tree, the test's recorded
resolutions, and a fixture planted to break the rule all drive one walk. A census with no
positive control passes forever once it has gone blind.
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

# The repository whose docstring states the rule. Receivers are resolved through annotations,
# and the annotation carries this name however the file imported it.
VERSION_ROW_REPOSITORY = "WeekInputVersionRepository"

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

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


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
    row_types = _row_types(trees)
    attributes = _attribute_annotations(trees)
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
                    locals_=_local_types(function, row_types),
                )
                taken_at = _first_take(function, scope, row_types)
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
                    kind, display = scope.receiver(statement.func.value, row_types)
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
                return _kind(annotation, row_types), f"self.{node.attr}"
            return None, ""
        if isinstance(node, ast.Name):
            return self._locals.get(node.id), node.id
        return None, ""


def _kind(annotation: str | None, row_types: frozenset[str]) -> str | None:
    """Whether an annotation names the version row, a table-holding repository, or neither."""
    names: set[str] = set(_IDENTIFIER.findall(annotation or ""))
    if names & row_types:
        return "version"
    repositories = {name for name in names if name.endswith("Repository")}
    if len(repositories) == 1:
        return repositories.pop()
    return None


def _annotation_of(arg: ast.arg) -> str | None:
    return ast.unparse(arg.annotation) if arg.annotation else None


def _init_parameters(cls: ast.ClassDef) -> dict[str, str]:
    """The initializer's parameter names, mapped to the annotation each carries."""
    found: dict[str, str] = {}
    for item in cls.body:
        if not (
            isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "__init__"
        ):
            continue
        found.update(
            {arg.arg: (_annotation_of(arg) or "") for arg in item.args.args + item.args.kwonlyargs}
        )
    return found


def _constructed_locals(tree: ast.Module, classes: frozenset[str]) -> dict[str, str]:
    """Every local a module binds to a constructor call, keyed for wiring reads."""
    found: dict[str, str] = {}
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id in classes
        ):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                found[target.id] = node.value.func.id
    return found


def _wired_type(value: ast.expr, constructed: Mapping[str, str]) -> str | None:
    """What an argument expression hands a constructor: a member, or nothing known."""
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
        return value.func.id
    if isinstance(value, ast.Name):
        return constructed.get(value.id)
    return None


def _row_types(trees: Mapping[Path, ast.Module]) -> frozenset[str]:
    """The row's own type plus every adapter composed around it, derived transitively.

    Two edges grow the set to a fixed point. A class whose ``__init__`` takes a parameter
    annotated with a member composes it, so :class:`TrackedWeekInputVersions` joins the
    repository itself. And a constructor wired at composition time (``SomeService(versions=
    TrackedWeekInputVersions(...))``) proves the annotated name the keyword files into -- here
    the :class:`WeekInputVersions` protocol -- resolves to a member, so services depending on
    the operation rather than on plan storage's repository are reached without naming them.
    Keyword wiring only: a positional hand-off is this reading's stated blind edge.
    """
    classes = {
        node.name: node
        for tree in trees.values()
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    }
    constructed = {
        path: _constructed_locals(tree, frozenset(classes)) for path, tree in trees.items()
    }
    types = {VERSION_ROW_REPOSITORY}
    growing = True
    while growing:
        growing = False
        for name in sorted(classes):
            if name not in types and _composed_class(classes[name], frozenset(types)):
                types.add(name)
                growing = True
        for path, tree in trees.items():
            wired = constructed[path]
            for node in ast.walk(tree):
                if (
                    not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name))
                    or node.func.id not in classes
                ):
                    continue
                parameters = _init_parameters(classes[node.func.id])
                for keyword in node.keywords:
                    if keyword.arg is None:  # the ``**`` marker carries no name to file under
                        continue
                    annotation = parameters.get(keyword.arg)
                    if not annotation or annotation in types:
                        continue
                    if _wired_type(keyword.value, wired) in types:
                        types.add(annotation)
                        growing = True
    return frozenset(types)


def _composed_class(node: ast.ClassDef, types: frozenset[str]) -> bool:
    """Whether a class composes a member of ``types`` through an annotated parameter."""
    return any(
        _kind(_annotation_of(arg), types) == "version"
        for item in node.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "__init__"
        for arg in item.args.args + item.args.kwonlyargs
    )


def _attribute_annotations(trees: Mapping[Path, ast.Module]) -> dict[str, dict[str, str]]:
    """Every class's ``self.X`` filings, mapped to the annotation the filed parameter carries."""
    filings: dict[str, dict[str, str]] = {}
    for tree in trees.values():
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            annotations = filings.setdefault(node.name, {})
            for item in node.body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                parameters = {
                    arg.arg: (_annotation_of(arg) or "")
                    for arg in item.args.args + item.args.kwonlyargs
                }
                for statement in ast.walk(item):
                    if not isinstance(statement, ast.Assign):
                        continue
                    for target in statement.targets:
                        if not (
                            isinstance(target, ast.Attribute)
                            and isinstance(target.value, ast.Name)
                            and target.value.id == "self"
                            and isinstance(statement.value, ast.Name)
                        ):
                            continue
                        if target.attr not in annotations:
                            annotations[target.attr] = parameters.get(statement.value.id, "")
    return filings


def _local_types(
    function: ast.FunctionDef | ast.AsyncFunctionDef, row_types: frozenset[str]
) -> dict[str, str]:
    """The method's own typed names: annotated parameters and constructed locals."""
    found: dict[str, str] = {}
    for arg in function.args.args + function.args.kwonlyargs:
        kind = _kind(_annotation_of(arg), row_types)
        if kind is not None:
            found[arg.arg] = kind
    for statement in ast.walk(function):
        if not (
            isinstance(statement, ast.Assign)
            and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Name)
        ):
            continue
        kind = _kind(statement.value.func.id, row_types)
        if kind is None:
            continue
        for target in statement.targets:
            if isinstance(target, ast.Name):
                found[target.id] = kind
    return found


def _first_take(
    function: ast.FunctionDef | ast.AsyncFunctionDef, scope: _MethodScope, row_types: frozenset[str]
) -> int | None:
    """The earliest line the row is taken at, or ``None`` while the function takes nothing."""
    taken: list[int] = []
    for statement in ast.walk(function):
        if not (isinstance(statement, ast.Call) and isinstance(statement.func, ast.Attribute)):
            continue
        if statement.func.attr not in TAKE_METHODS:
            continue
        kind, _ = scope.receiver(statement.func.value, row_types)
        if kind == "version":
            taken.append(statement.lineno)
    return min(taken, default=None)
