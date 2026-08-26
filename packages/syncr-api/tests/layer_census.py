"""Reading the api's package layers off its own imports: who may reach whom, walked as text.

Two layering intentions here have no type check and no runtime guard, so what enforces them is
a reading of the source that examines whatever modules exist whenever it runs. The composition
root in :mod:`syncr_api.core.app_factory` may import feature packages, because assembling their
routers is its one job; no other file under ``core`` may, or ``core`` stops being the layer
everything else stands on (R1). And ``accounts`` reaches into exactly one feature module besides
``oauth``: ``learned.repository``, because provisioning seeds weight-set version 1 in the same
transaction that creates the tenant, so the weight sets exist before the first request can ask
for them (R3).

The walk reads imports through ``ast`` rather than by importing, so a function-local import (the
kind provisioning makes) counts exactly like a module-top one: these rules are about which way
the dependency points, not about the line it was written on. Relative imports do not resolve
here because this source tree states every intra-api import absolutely; a relative import would
be invisible to this walk, which is a stated edge, not a silent one.

The graph readings also record how big the dependency graph is: package count, edge count, how
many feature-to-feature pairs import each other, and how many of those pairs involve ``plans``.
A figure that moves means an import changed direction somewhere on purpose, so the recorded
figure is updated in the same change rather than silently absorbed. No claim is made that the
graph is acyclic: many of these pairs cycle, and blessing them is worse than not counting them.

Every helper returns data rather than asserting, so each rule is checked against the real tree
AND against a deliberately planted violation. A rule with no control passes forever once it has
gone blind, which is worse than having no rule at all.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

# The prefix every intra-api import carries, and the one package that is composition rather
# than feature.
API_PACKAGE_ROOT = "syncr_api"
CORE_PACKAGE = "core"

# The tuple in core/app_factory.py that names one router factory per feature module. Read by
# name from the parsed source, so renaming the registry fails loudly instead of quietly
# detaching R1's justification from what app_factory actually imports.
ROUTER_REGISTRY_NAME = "FEATURE_ROUTERS"


@dataclass(frozen=True, slots=True)
class CrossImport:
    """One import that leaves its own package: which file, which package, reaching where."""

    importer: str
    source_package: str
    target: str


def declared_packages(source_root: Path) -> frozenset[str]:
    """Every top-level package directory under the api's source root."""
    found = frozenset(
        path.name for path in source_root.iterdir() if path.is_dir() and path.name != "__pycache__"
    )
    if not found:
        raise AssertionError(f"no packages found under {source_root}")
    return found


def cross_imports(source_root: Path) -> frozenset[CrossImport]:
    """Every import from one package of the api into a different package, over the whole root.

    Only absolute ``syncr_api.<package>.<module>`` targets count, which is the only spelling
    this tree uses for intra-api imports.
    """
    found: set[CrossImport] = set()
    for path in sorted(source_root.rglob("*.py")):
        source_package = path.relative_to(source_root).parts[0]
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            targets = _import_targets(node)
            for dotted in targets:
                parts = dotted.split(".")
                if (
                    len(parts) > 1
                    and parts[0] == API_PACKAGE_ROOT
                    and parts[1] in _package_names(source_root)
                    and parts[1] != source_package
                ):
                    found.add(
                        CrossImport(
                            importer=path.relative_to(source_root).as_posix(),
                            source_package=source_package,
                            target=dotted,
                        )
                    )
    return frozenset(found)


def core_feature_importers(imports: frozenset[CrossImport]) -> frozenset[str]:
    """The files under ``core`` that import any feature package."""
    return frozenset(
        crossed.importer for crossed in imports if crossed.source_package == CORE_PACKAGE
    )


def registry_factory_origins(app_factory_source: Path) -> dict[str, str]:
    """The module each factory named in the router registry was imported from.

    The registry is a tuple of bare names, so what feature each entry serves is visible only
    through the import that binds the name in the same file. A name with no such binding means
    the registry references something this file does not import, and an empty mapping means the
    registry itself was not found: both fail here rather than letting a rule read nothing.
    """
    tree = ast.parse(app_factory_source.read_text(encoding="utf-8"))
    bound_to = {
        alias.name: node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    }
    registry = _registry_names(tree)
    origins = {name: bound_to[name] for name in registry if name in bound_to}
    if len(origins) != len(registry):
        missing = sorted(registry - origins.keys())
        raise AssertionError(f"registry factories with no import origin: {missing}")
    return origins


def package_edges(imports: frozenset[CrossImport]) -> frozenset[tuple[str, str]]:
    """The unique directed edges of the package dependency graph, self-edges excluded."""
    return frozenset((crossed.source_package, crossed.target.split(".")[1]) for crossed in imports)


def mutual_import_pairs(edges: frozenset[tuple[str, str]]) -> frozenset[tuple[str, str]]:
    """The feature-to-feature pairs that import each other: one cycle apiece.

    Each unordered pair is returned once, so a pair importing in both directions counts as the
    single cycle it is, whatever the two directions cost. Edges touching ``core`` are outside
    this reading: core is meant to sit beneath every feature, so a pair carrying core is either
    the composition root reaching up (allowed to exactly one file, per R1) or a violation that
    rule already names.
    """
    return frozenset(
        (min(a, b), max(a, b)) for a, b in edges if (b, a) in edges and CORE_PACKAGE not in (a, b)
    )


def _import_targets(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
        return [node.module]
    return []


def _package_names(source_root: Path) -> frozenset[str]:
    return frozenset(path.name for path in source_root.iterdir() if path.is_dir())


def _registry_names(tree: ast.Module) -> set[str]:
    for node in ast.walk(tree):
        value = None
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == ROUTER_REGISTRY_NAME
            for target in node.targets
        ):
            value = node.value
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == ROUTER_REGISTRY_NAME
        ):
            value = node.value
        if isinstance(value, ast.Tuple):
            return {element.id for element in value.elts if isinstance(element, ast.Name)}
    raise AssertionError(f"no {ROUTER_REGISTRY_NAME} tuple found in the app factory")
