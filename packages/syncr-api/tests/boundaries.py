"""Helpers for the boundary tests: route walking, dependency walking, AST reading.

These exist because several rules in this application are enforceable only by a test that
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
import re
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

from pydantic import BaseModel

from syncr_api.concessions.config import WEEKS_PREFIX
from syncr_api.core.principal import Principal
from syncr_api.core.settings import API_PREFIX
from syncr_api.core.tenancy import IDENTITY_TABLES

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
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
# What a mapped class assigns to name its table. Read from a module's SOURCE to decide whether
# importing it can contribute a table, so the models walk finds a table wherever a package
# declares one without importing the package's routes, wiring, or entrypoints on the way.
TABLENAME_ATTRIBUTE = "__tablename__"
PACKAGE_NAME = "syncr_api"

# The statement constructors a scoped repository must not call directly. `insert` is
# absent on purpose: a scope is a column value on an insert rather than a predicate, so
# there is nothing a scoped helper would add.
STATEMENT_CONSTRUCTORS = frozenset({"select", "update", "delete"})

# `syncr_api.<package>.models` is three parts, and the package is the second from last.
MODELS_MODULE_DEPTH = 3

METHODS_WITHOUT_A_BODY = frozenset({"GET", "HEAD", "OPTIONS"})

# One path parameter, as a route template spells it. An exemption's reason below names the value a
# driver would have to invent in the same spelling, so the two are compared as tokens rather than
# as prose.
PATH_PARAMETER = re.compile(r"\{([^}]+)\}")

# The field a response shape declares when it carries a verdict to a client. The contribution below
# is stated over it, so a read added later comes under the rule without any file naming its path.
VERDICT_FIELD = "verdict"


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


@dataclass(frozen=True, slots=True)
class SerializationView:
    """One route, reduced to what it drops from a body it renders.

    A key the model calls required is still absent from what a client reads if the route renders
    the body with nulls or unset members excluded, and neither the model nor the generated
    document can see that.
    """

    path: str
    excludes_none: bool
    excludes_unset: bool


@dataclass(frozen=True, slots=True)
class ReadCensus:
    """Every parameterized read the application declares, crossed against the sets that name one.

    A filter local to one guard covers what it matches and reports nothing about what it does not,
    so a read arriving under a prefix no guard reaches is inherited undriven and invisible. The
    first two members are the two ways a read is accounted for; the rest are the ways the
    accounting itself goes quiet, and each has to be empty for the census to mean anything.
    """

    # Reads a published contribution derives, so a guard drives them by consuming that contribution.
    driven: frozenset[str]
    # Reads the exemption table names, each with the value a driver would have to invent.
    exempt: frozenset[str]
    # Declared by the application and named by neither set: the case the census exists for.
    covered_by_neither: frozenset[str]
    # Derived by a contribution and not declared by the application, so the contribution names a
    # read nothing serves. It reddens the equality either way; naming it is what tells the operator
    # which side of the equality moved.
    driven_but_undeclared: frozenset[str]
    # Exempted and no longer declared, so the exemption covers a route that does not exist.
    exempt_but_undeclared: frozenset[str]
    # Exempted and driven, so the table states a gap that has since been closed.
    exempt_but_driven: frozenset[str]
    # Exempted with a reason that does not name the route's own parameter, which is what a reason
    # copied from another route looks like.
    exempt_without_naming_its_parameter: frozenset[str]
    # Contributions that derived nothing, by name. A contribution matching no route has gone blind,
    # and the equality above cannot see the difference.
    contributions_deriving_nothing: tuple[str, ...]


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


def serialization_views(app: FastAPI) -> list[SerializationView]:
    """Every route that renders a response model, with the settings that decide what it renders.

    Separate from :func:`api_routes` because these settings live on the framework's route object
    rather than on the handler or its dependency tree, and :class:`RouteView` is stated over the
    latter. Both read the same expansion, so a route contributed by an included router is seen by
    each.
    """
    return [
        SerializationView(
            path=cast("str", getattr(candidate, "path")),  # noqa: B009 - duck-typed shape
            excludes_none=bool(getattr(candidate, "response_model_exclude_none", False)),
            excludes_unset=bool(getattr(candidate, "response_model_exclude_unset", False)),
        )
        for candidate in _expand(app.routes)
        if hasattr(candidate, "response_model_exclude_none")
    ]


def read_paths(app: FastAPI, *, parameterized: bool) -> list[str]:
    """Every GET path under the api prefix, split by whether it carries a path parameter.

    Bounded by the app's own route table rather than by a list, so a read route added by a
    later feature module is driven by whichever caller wants its half without that ticket
    remembering to extend one.

    The split exists because driving a parameterized read needs a value invented for the
    parameter, and which value is meaningful is the addressed resource's own business: a week
    identifier, an anchor id, a period. So the two halves are driven separately, and the
    parameterized half is censused against the drivers it has by :func:`census_of_reads`. The rule
    they serve is the same one, that a read is not a mutation, and stating the predicate once is
    what keeps the halves from overlapping or leaving a route in neither.
    """
    return sorted(
        {
            path
            for route in api_routes(app)
            for method, path in route_identity(route)
            if method == "GET" and path.startswith(API_PREFIX) and ("{" in path) == parameterized
        }
    )


def path_parameters(path: str) -> set[str]:
    """Every path parameter a route template declares, by the name the template spells."""
    return set(PATH_PARAMETER.findall(path))


def week_addressed_reads(app: FastAPI) -> list[str]:
    """Every parameterized read under the week prefix, which one week identifier addresses.

    Published here rather than filtered beside the guards that drive it, because a filter is not a
    contribution: it answers what it matches and leaves the reads it does not match unaccounted
    for. Derived from the route table, so a week read a later feature module adds is driven by
    whoever consumes this with no list to extend.
    """
    return [path for path in read_paths(app, parameterized=True) if path.startswith(WEEKS_PREFIX)]


def verdict_bearing_reads(app: FastAPI) -> list[str]:
    """Every GET path whose response shape carries a verdict to a client.

    Derived from the response models, so a read that starts answering a verdict comes under the rule
    that a read records no transition when it ships rather than when someone remembers it.

    Published beside :func:`week_addressed_reads` because it is the second derivation over this
    route table, and one of the reads it derives sits under the review prefix rather than the week
    one: a census that read only the first would call that read a gap while a guard was driving it.
    """
    paths = []
    for route in api_routes(app):
        if "GET" not in route.methods:
            continue
        answered = get_type_hints(route.endpoint).get("return")
        if (
            isinstance(answered, type)
            and issubclass(answered, BaseModel)
            and VERDICT_FIELD in answered.model_fields
        ):
            paths.append(route.path)
    return sorted(paths)


type DrivenReads = Callable[[FastAPI], list[str]]

# Every published contribution of driven parameterized reads. Each is a derivation over the
# application's own route table rather than a list of paths, so a read arriving under a prefix a
# driver already covers is driven with no edit here, and nothing enters the driven set by being
# named.
#
# A DERIVATION THE SUITE ALREADY HAS AND THIS TUPLE DOES NOT HOLD IS THE ONE FAILURE THIS CENSUS
# CANNOT SEE: the reads it derives are then declared gaps while a guard drives them. Both of these
# were written before the census and were found by sweeping the suite for readers of the route
# table, which is the sweep to repeat rather than a list to trust.
DRIVEN_READ_CONTRIBUTIONS: tuple[DrivenReads, ...] = (week_addressed_reads, verdict_bearing_reads)

# The parameterized reads no contribution drives, each naming the value a driver would have to
# invent to address it. Written out and crossed against the route table in BOTH directions, so a
# route the application stops declaring is reported here rather than sitting in the table forever,
# and a route it starts declaring is reported rather than inherited unguarded.
#
# What a route here is exempt from is the drivers of this census: guards that take their paths FROM
# the route table, which is what lets one cover a route nobody wrote it for. A feature's own
# integration test addressing one of these with a record it created is not a contribution, because
# a test that spells its own path cannot cover a route it has never heard of.
EXEMPT_PARAMETERIZED_READS: Mapping[str, str] = {
    f"{API_PREFIX}/anchor-types/{{anchor_type_id}}": (
        "{anchor_type_id} names a declared anchor type"
    ),
    f"{API_PREFIX}/anchors/{{anchor_id}}": "{anchor_id} names a stored anchor",
    f"{API_PREFIX}/areas/{{area_id}}": "{area_id} names a declared area",
    f"{API_PREFIX}/areas/{{area_id}}/preference": (
        "{area_id} names a declared area, and the preference is the one stored against it"
    ),
    f"{API_PREFIX}/calendar-sources/{{source_id}}": "{source_id} names a declared feed",
    f"{API_PREFIX}/calendar-sources/{{source_id}}/remote-calendars": (
        "{source_id} names a declared feed, and this read reaches the provider behind it"
    ),
    f"{API_PREFIX}/days/{{date}}": "{date} is a date the tenant's plan has blocks on",
    f"{API_PREFIX}/habits/{{habit_id}}": "{habit_id} names a declared habit",
    f"{API_PREFIX}/habits/{{habit_id}}/preference": (
        "{habit_id} names a declared habit, and the preference is the one stored against it"
    ),
    f"{API_PREFIX}/off-plan/{{period_id}}": "{period_id} names a declared off-plan period",
    f"{API_PREFIX}/operations/{{operation_id}}": "{operation_id} names an enqueued operation",
    f"{API_PREFIX}/projects/{{project_id}}": "{project_id} names a declared project",
    f"{API_PREFIX}/routines/{{routine_id}}": "{routine_id} names a declared routine",
    f"{API_PREFIX}/tasks/{{task_id}}": "{task_id} names a declared task",
    f"{API_PREFIX}/tasks/{{task_id}}/preference": (
        "{task_id} names a declared task, and the preference is the one stored against it"
    ),
    f"{API_PREFIX}/templates/{{template_id}}": "{template_id} names a declared week template",
}


def census_of_reads(
    app: FastAPI,
    *,
    contributions: Sequence[DrivenReads] = DRIVEN_READ_CONTRIBUTIONS,
    exemptions: Mapping[str, str] = EXEMPT_PARAMETERIZED_READS,
) -> ReadCensus:
    """Cross every parameterized read the application declares against the two sets that name one.

    Returns data rather than asserting, and takes both sets as arguments, so the same reading runs
    against the real application and against one carrying a route neither set names.
    """
    declared = frozenset(read_paths(app, parameterized=True))
    derived = tuple(
        (contribution.__name__, frozenset(contribution(app))) for contribution in contributions
    )
    driven: frozenset[str] = frozenset().union(*(paths for _, paths in derived))
    exempt = frozenset(exemptions)
    return ReadCensus(
        driven=driven,
        exempt=exempt,
        covered_by_neither=declared - driven - exempt,
        driven_but_undeclared=driven - declared,
        exempt_but_undeclared=exempt - declared,
        exempt_but_driven=exempt & driven,
        exempt_without_naming_its_parameter=frozenset(
            path
            for path, reason in exemptions.items()
            if not path_parameters(path) <= path_parameters(reason)
        ),
        contributions_deriving_nothing=tuple(name for name, paths in derived if not paths),
    )


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
    remembering to extend an import here.

    Two kinds of class in the same module are excluded, and neither has authorization to do. A
    frozen dataclass is a return shape. A ``Protocol`` is the interface of a collaborator the
    service reads THROUGH, declared beside the reader so the service depends on the question it asks
    rather than on another package's implementation: whoever implements one is a class elsewhere,
    and it is that class's own module the rule applies to.
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
            and not _is_protocol(member)
        )
    return discovered


def _is_protocol(candidate: type) -> bool:
    """Whether this class is a ``Protocol`` declaration rather than an implementation.

    Read off the attribute ``typing`` sets on the class itself, so a protocol is recognized by what
    it IS rather than by a naming convention a new one could miss.
    """
    return getattr(candidate, "_is_protocol", False) is True


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

    Applied to EVERY module of a scoped package rather than only to ``repository.py``: a
    package whose repositories are split by concern would otherwise have all but one of them
    outside the rule.
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


def table_names(models: Iterable[type]) -> set[str]:
    """The table each of these mapped classes declares."""
    return {name for model in models if (name := getattr(model, "__tablename__", None))}


def package_modules(source_root: Path, package: str) -> list[Path]:
    """Every module of one feature package, in a stable order.

    The bare-statement rule is stated over all of them rather than over ``repository.py``
    alone. A package that splits its repositories by concern (the plan of record, the pending
    slot, the version counter) keeps them in modules of their own, and a rule that read one
    file would cover one of them.
    """
    return sorted((source_root / package).glob("*.py"))


def declares_a_table(source: str) -> bool:
    """Whether this module's source names a table inside a class body."""
    for statement in ast.walk(ast.parse(source)):
        if not isinstance(statement, ast.ClassDef):
            continue
        for assignment in statement.body:
            targets: list[ast.expr] = []
            if isinstance(assignment, ast.Assign):
                targets = list(assignment.targets)
            elif isinstance(assignment, ast.AnnAssign):
                targets = [assignment.target]
            if any(getattr(target, "id", None) == TABLENAME_ATTRIBUTE for target in targets):
                return True
    return False


def mapped_classes(source_root: Path) -> list[type]:
    """Every model class the package declares, importing the modules that declare one first.

    Filesystem-driven rather than read from the mapper registry. A registry only knows
    the modules something has already imported, so a feature module whose models nothing
    in the suite happens to import would fall outside every schema rule silently. This
    also populates ``Base.metadata``, which the metadata rules read.

    Not restricted to ``models.py``: a package may split its tables by concern, and one that
    kept them all outside a ``models.py`` would otherwise fall outside every rule stated over
    this walk. Which modules to import is decided by reading each one for a class that names a
    table, so a package's routes and wiring are never imported and no module is skipped by name.
    """
    discovered: list[type] = []
    for path in sorted(source_root.glob("*/*.py")):
        if path.name.startswith("_") or not declares_a_table(path.read_text(encoding="utf-8")):
            continue
        module = import_module(f"{PACKAGE_NAME}.{path.parent.name}.{path.stem}")
        discovered.extend(
            member
            for _name, member in inspect.getmembers(module, inspect.isclass)
            if member.__module__ == module.__name__ and hasattr(member, TABLENAME_ATTRIBUTE)
        )
    return discovered


def package_mapped_classes(source_root: Path, package: str) -> list[type]:
    """Every model class one feature package declares, in whichever module declares it.

    Wider than :func:`mapped_classes`, which reads ``models.py`` alone. A package that
    splits its tables by concern keeps some of them elsewhere, so a rule stated over "the
    tables this package owns" has to read the whole package or it silently covers a subset.
    """
    discovered: list[type] = []
    for path in package_modules(source_root, package):
        if path.stem.startswith("_"):
            continue
        module = import_module(f"{PACKAGE_NAME}.{package}.{path.stem}")
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
