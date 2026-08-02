"""Helpers for the boundary tests: route walking, dependency walking, AST reading.

These exist because three rules in this application are enforceable only by a test that
inspects the code itself. Each rule degrades silently as new code arrives, so what is
needed is not a test of today's routes but a mechanism that examines whatever routes
exist whenever it runs.

Every helper here returns data rather than asserting, so each rule can be checked
against the real app AND against a deliberately broken synthetic input. A boundary test
with no positive control passes forever once the thing it guards has been removed, which
is worse than having no test at all.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from dataclasses import dataclass, is_dataclass
from importlib import import_module
from typing import (
    TYPE_CHECKING,
    Annotated,
    TypeAliasType,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

from syncr_api.core.principal import Principal
from syncr_api.core.tenancy import IDENTITY_TABLES

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Sequence
    from pathlib import Path

    from fastapi import FastAPI
    from fastapi.dependencies.models import Dependant
    from starlette.routing import BaseRoute

# The parameter name and annotation every service method's first argument carries.
PRINCIPAL_PARAMETER = "principal"
PRINCIPAL_ANNOTATION = Principal.__name__

# A module holding service classes. The authorization rule is stated over these, so
# what counts as a service is a naming convention the whole package follows rather
# than a registry someone has to remember to add to.
SERVICE_MODULE_SUFFIX = ".service"
SERVICE_MODULE_NAME = "service.py"
REPOSITORY_MODULE_NAME = "repository.py"
MODELS_MODULE_NAME = "models.py"
PACKAGE_NAME = "syncr_api"

# The statement constructors a scoped repository must not call directly. `insert` is
# absent on purpose: a scope is a column value on an insert rather than a predicate, so
# there is nothing a scoped helper would add.
STATEMENT_CONSTRUCTORS = frozenset({"select", "update", "delete"})

# `syncr_api.<package>.models` is three parts, and the package is the second from last.
MODELS_MODULE_DEPTH = 3
SERVICE_MODULE_NAME = "service.py"
PACKAGE_NAME = "syncr_api"

METHODS_WITHOUT_A_BODY = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True, slots=True)
class RouteView:
    """One route, reduced to what a boundary rule is stated over.

    The framework's own route objects come in more than one shape: a router included
    into the application is resolved lazily, so what ``app.routes`` holds is a mixture
    of routes and includes-to-be-expanded, and only the expanded form knows its final
    path or its inherited dependencies. Collapsing both into this one shape keeps that
    detail in :func:`api_routes` instead of in every rule.
    """

    path: str
    methods: frozenset[str]
    endpoint: Callable[..., object]
    dependant: Dependant


def api_routes(app: FastAPI) -> list[RouteView]:
    """Every route the application declares, with its inherited dependencies applied.

    Excludes the documentation and schema endpoints the framework mounts: they carry no
    handler of ours and no dependency tree, which is exactly the shape this filter
    tests for rather than a class name to keep matching.
    """
    return [_view(candidate) for candidate in _expand(app.routes) if _is_api_route(candidate)]


def route_identity(route: RouteView) -> set[tuple[str, str]]:
    """The ``(method, path)`` pairs this route answers."""
    return {(method.upper(), route.path) for method in route.methods}


def resolved_dependencies(route: RouteView) -> set[Callable[..., object]]:
    """Every callable the framework resolves for this route, at any depth.

    Router-level dependencies and nested sub-dependencies are both included, so a check
    for one function finds it whether a route declared it directly or inherited it.
    """
    return {dependant.call for dependant in _walk(route.dependant) if dependant.call is not None}


def _expand(routes: Sequence[BaseRoute]) -> Iterator[object]:
    """Flatten included routers into the routes they contribute."""
    for route in routes:
        expand = getattr(route, "effective_route_contexts", None)
        if callable(expand):
            # Recurses through nested includes on its own, so one level here is enough.
            yield from cast("Iterator[object]", expand())
        else:
            yield route


def _is_api_route(candidate: object) -> bool:
    return all(hasattr(candidate, name) for name in ("path", "methods", "endpoint", "dependant"))


def _view(candidate: object) -> RouteView:
    return RouteView(
        path=cast("str", getattr(candidate, "path")),  # noqa: B009 - duck-typed shape
        methods=frozenset(cast("set[str]", getattr(candidate, "methods")) or set()),  # noqa: B009
        endpoint=cast("Callable[..., object]", getattr(candidate, "endpoint")),  # noqa: B009
        dependant=cast("Dependant", getattr(candidate, "dependant")),  # noqa: B009
    )


def _walk(dependant: Dependant) -> Iterator[Dependant]:
    yield dependant
    for nested in dependant.dependencies:
        yield from _walk(nested)


def service_calls(endpoint: Callable[..., object]) -> set[tuple[type, str]]:
    """The ``(service class, method name)`` pairs this handler calls.

    Found by pairing two readings of the handler. Its resolved annotations say which
    parameters are service classes, which is reliable because a route obtains a service
    only by declaring one. Its syntax tree says which methods are called on those
    parameters, which is what makes the answer specific to the method rather than to the
    class.
    """
    parameters = _service_parameters(endpoint)
    if not parameters:
        return set()
    tree = ast.parse(textwrap.dedent(inspect.getsource(endpoint)))
    return {
        (parameters[node.func.value.id], node.func.attr)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in parameters
    }


def principal_position(service_class: type, method_name: str) -> str | None:
    """``None`` when the method takes a principal first, or why it does not.

    The annotation is compared as written rather than resolved. A service module keeps
    its type-only imports under ``TYPE_CHECKING``, so resolving them here would need
    this test to reconstruct that module's namespace, which would make the test fail for
    a reason that has nothing to do with authorization.
    """
    method = getattr(service_class, method_name, None)
    if method is None:
        return f"{service_class.__name__} has no method {method_name}"
    parameters = [
        parameter
        for name, parameter in inspect.signature(method).parameters.items()
        if name != "self"
    ]
    if not parameters:
        return f"{service_class.__name__}.{method_name} takes no principal at all"
    first = parameters[0]
    if first.name != PRINCIPAL_PARAMETER:
        return (
            f"{service_class.__name__}.{method_name} takes {first.name!r} first, "
            f"not {PRINCIPAL_PARAMETER!r}"
        )
    if PRINCIPAL_ANNOTATION not in str(first.annotation):
        return (
            f"{service_class.__name__}.{method_name}'s first parameter is annotated "
            f"{first.annotation!r} rather than {PRINCIPAL_ANNOTATION}"
        )
    return None


def public_methods(service_class: type) -> list[str]:
    """Every method of a service class that is part of its interface."""
    return sorted(
        name
        for name, member in inspect.getmembers(service_class, inspect.isfunction)
        if not name.startswith("_")
    )


def service_classes(source_root: Path) -> list[type]:
    """Every service class the package defines, discovered rather than listed.

    Found by walking ``*/service.py``, the same way the route rule walks ``*/api.py``, so
    a service class added by a later feature module is covered without that ticket
    remembering to extend an import here. Value types are excluded: a frozen dataclass in
    the same module is a return shape, not a service, and has no authorization to do.
    """
    discovered: list[type] = []
    for path in sorted(source_root.glob(f"*/{SERVICE_MODULE_NAME}")):
        module = import_module(f"{PACKAGE_NAME}.{path.parent.name}.service")
        discovered.extend(
            member
            for name, member in inspect.getmembers(module, inspect.isclass)
            if not name.startswith("_")
            and member.__module__ == module.__name__
            and not is_dataclass(member)
        )
    return discovered


def imported_modules(source: str) -> set[str]:
    """Every module name this source imports, as written."""
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
    return names


def bare_statement_calls(source: str) -> list[str]:
    """Every statement built without the scope: ``select(...)``, not ``self.scoped_*``.

    A repository over a table that holds a plan must build its statements through the
    scoped base, or the tenant predicate is something each method remembers rather than
    something the base applies. A call on an attribute (``self.scoped_select(Model)``) is
    not a bare call and is not reported.
    """
    return sorted(
        node.func.id
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in STATEMENT_CONSTRUCTORS
    )


def packages_with_scoped_tables(models: Iterable[type]) -> set[str]:
    """The feature packages owning at least one table the tenancy rules apply to.

    Derived from the mapped classes rather than from a list, so a package added by a
    later feature module comes under the rule without that ticket registering it. A
    package whose tables are all identity tables is exempt, and that exemption is
    ``IDENTITY_TABLES``, which is itself asserted.
    """
    packages = set()
    for model in models:
        tablename = getattr(model, "__tablename__", None)
        if tablename is None or tablename in IDENTITY_TABLES:
            continue
        parts = model.__module__.split(".")
        if len(parts) >= MODELS_MODULE_DEPTH:
            packages.add(parts[-2])
    return packages


def mapped_classes(source_root: Path) -> list[type]:
    """Every model class the package declares, importing each models module first.

    Filesystem-driven rather than read from the mapper registry. A registry only knows
    the modules something has already imported, so a feature module whose models nothing
    in the suite happens to import would fall outside every schema rule silently. This
    also populates ``Base.metadata``, which the metadata rules read.
    """
    discovered: list[type] = []
    for path in sorted(source_root.glob(f"*/{MODELS_MODULE_NAME}")):
        module = import_module(f"{PACKAGE_NAME}.{path.parent.name}.models")
        discovered.extend(
            member
            for _name, member in inspect.getmembers(module, inspect.isclass)
            if member.__module__ == module.__name__ and hasattr(member, "__tablename__")
        )
    return discovered


def _service_parameters(endpoint: Callable[..., object]) -> dict[str, type]:
    """The handler's parameters whose annotation is a service class."""
    resolved: dict[str, type] = {}
    for name, hint in get_type_hints(endpoint, include_extras=True).items():
        if name == "return":
            continue
        candidate = _underlying_type(hint)
        if isinstance(candidate, type) and _is_service_class(candidate):
            resolved[name] = candidate
    return resolved


def _underlying_type(hint: object) -> object:
    """The class an annotation ultimately names.

    A route's dependency annotations are ``type`` aliases wrapping ``Annotated``, and a
    resolved hint hands back the alias rather than its value, so both layers are peeled
    here. Without this the check finds no service parameters at all and every route
    passes for the wrong reason.
    """
    seen = hint
    while True:
        if isinstance(seen, TypeAliasType):
            seen = seen.__value__
        elif get_origin(seen) is Annotated:
            seen = get_args(seen)[0]
        else:
            return seen


def _is_service_class(candidate: type) -> bool:
    module = getattr(candidate, "__module__", "")
    return module.startswith("syncr_api.") and module.endswith(SERVICE_MODULE_SUFFIX)
