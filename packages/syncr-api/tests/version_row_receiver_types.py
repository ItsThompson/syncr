"""Which names in a source tree resolve to the week's input-version row, or to a table.

The half of the version-row walk that types receivers, split along its seam from the
ordering reading in :mod:`tests.version_row_census`: this module answers "is this receiver
the row, or a repository over another table", and nothing about statement order. Everything
here is derived rather than listed, so a new adapter or collaborator naming convention is
covered without anyone remembering.

**How a name joins the version-row set.** Two edges grow it to a fixed point. A class whose
``__init__`` takes a parameter annotated with a member composes it, so
:class:`TrackedWeekInputVersions` joins the repository itself. And a constructor wired at
composition time (``SomeService(versions=TrackedWeekInputVersions(...))``) proves the
annotated name the keyword files into -- here the :class:`WeekInputVersions` protocol --
resolves to a member, so services depending on the operation rather than on plan storage's
repository are reached without naming them. Keyword wiring only: a positional hand-off is
this reading's stated blind edge.
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

# The repository whose docstring states the lock-order rule. Receivers are resolved through
# annotations, and the annotation carries this name however the file imported it.
VERSION_ROW_REPOSITORY = "WeekInputVersionRepository"

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def annotation_kind(annotation: str | None, row_types: frozenset[str]) -> str | None:
    """Whether an annotation names the version row, a table-holding repository, or neither."""
    names: set[str] = set(_IDENTIFIER.findall(annotation or ""))
    if names & row_types:
        return "version"
    repositories = {name for name in names if name.endswith("Repository")}
    if len(repositories) == 1:
        return repositories.pop()
    return None


def annotation_of(arg: ast.arg) -> str | None:
    """The annotation as the file spells it, or ``None`` when it carries none."""
    return ast.unparse(arg.annotation) if arg.annotation else None


def init_parameters(cls: ast.ClassDef) -> dict[str, str]:
    """The initializer's parameter names, mapped to the annotation each carries."""
    found: dict[str, str] = {}
    for item in cls.body:
        if not (
            isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "__init__"
        ):
            continue
        found.update(
            {arg.arg: (annotation_of(arg) or "") for arg in item.args.args + item.args.kwonlyargs}
        )
    return found


def composed_class(node: ast.ClassDef, types: frozenset[str]) -> bool:
    """Whether a class composes a member of ``types`` through an annotated parameter."""
    return any(
        annotation_kind(annotation_of(arg), types) == "version"
        for item in node.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "__init__"
        for arg in item.args.args + item.args.kwonlyargs
    )


def constructed_locals(tree: ast.Module, classes: frozenset[str]) -> dict[str, str]:
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


def wired_type(value: ast.expr, constructed: Mapping[str, str]) -> str | None:
    """What an argument expression hands a constructor: a member, or nothing known."""
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
        return value.func.id
    if isinstance(value, ast.Name):
        return constructed.get(value.id)
    return None


def row_types(trees: Mapping[Path, ast.Module]) -> frozenset[str]:
    """The row's own type plus every adapter composed around it, derived transitively."""
    classes = {
        node.name: node
        for tree in trees.values()
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    }
    constructed = {
        path: constructed_locals(tree, frozenset(classes)) for path, tree in trees.items()
    }
    types = {VERSION_ROW_REPOSITORY}
    growing = True
    while growing:
        growing = False
        for name in sorted(classes):
            if name not in types and composed_class(classes[name], frozenset(types)):
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
                parameters = init_parameters(classes[node.func.id])
                for keyword in node.keywords:
                    if keyword.arg is None:  # the ``**`` marker carries no name to file under
                        continue
                    annotation = parameters.get(keyword.arg)
                    if not annotation or annotation in types:
                        continue
                    if wired_type(keyword.value, wired) in types:
                        types.add(annotation)
                        growing = True
    return frozenset(types)


def attribute_annotations(trees: Mapping[Path, ast.Module]) -> dict[str, dict[str, str]]:
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
                    arg.arg: (annotation_of(arg) or "")
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
