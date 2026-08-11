"""Every instant the wire carries, discovered rather than listed.

An instant is a moment, and a moment with no UTC offset is not one: ``"2026-03-08T09:00"`` and
``"2026-03-08"`` name a wall clock, and which moment that is depends on a zone neither states.
So the api accepts and renders offsets in both directions, which is what ``format: date-time``
already promises a caller.

That claim is over the WHOLE surface rather than over the fields someone remembered, so the
fields are found by walking. A list would be right on the day it was written: the surface here
grew from one feature module to twenty-five.

**TWO SOURCES, because neither alone is the wire.**

``models_extending_the_wire_base`` walks every module of the package for subclasses of the base
every wire shape extends. It reaches a shape no route mounts yet, which is where a new field is
written. A walk keyed on the module NAME ``schemas`` would miss ``core/notices.py`` and three of
the plan package's four schema modules, so this one is keyed on the base class instead.

``models_the_contract_is_generated_from`` asks the framework for the fields it renders the
OpenAPI document from, and follows each into its nested shapes. That reaches a shape that does
NOT extend the wire base -- the learning routes declare their own camel-casing base -- which the
first source cannot see. It is also, by construction, the set the committed contract describes.

Every helper returns data rather than asserting, so a claim can be checked against the real
application AND against an input built to break it. A walk with no positive control passes
forever once it has gone blind, and the equality it certifies can hold with both sides empty.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, TypeAliasType, get_args

from fastapi.openapi.utils import get_fields_from_routes
from pydantic import AwareDatetime, BaseModel, TypeAdapter

import syncr_api
from syncr_api.core.schemas import WireInstant, WireModel
from tests.boundaries import api_routes

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from types import ModuleType

    from fastapi import FastAPI

# What a body param is called when a route declares one model for the whole body, which is the
# shape every route in this application uses. FastAPI reports a field's failure under this
# prefix, so a driver naming a field has to agree with it.
BODY = "body"

# The two readings of a moment a field can be built on. ``datetime`` is the lax one, which takes a
# wall clock and calls it a moment; ``AwareDatetime`` is pydantic's aware one, and at runtime it is
# a marker class rather than an annotated ``datetime``, so a structural walk has to know both names
# or it finds only half of the surface it is meant to bound.
_INSTANT_READINGS = (datetime, AwareDatetime)


def api_modules() -> Iterator[ModuleType]:
    """Every module of the api package, imported.

    Importing is what makes a class visible: a subclass exists once its module body has run, so a
    reading taken without these imports describes whichever packages the caller happened to touch.
    """
    yield syncr_api
    for found in pkgutil.walk_packages(syncr_api.__path__, prefix=f"{syncr_api.__name__}."):
        yield importlib.import_module(found.name)


def models_extending_the_wire_base() -> tuple[type[BaseModel], ...]:
    """Every subclass of the wire base declared anywhere in the api package."""
    found = {
        value
        for module in api_modules()
        for value in vars(module).values()
        if isinstance(value, type) and issubclass(value, WireModel) and value is not WireModel
    }
    return _ordered(found)


def models_the_contract_is_generated_from(app: FastAPI) -> tuple[type[BaseModel], ...]:
    """Every model the OpenAPI document describes, asked of the framework that renders it.

    ``get_fields_from_routes`` is what the document generator itself reads: request bodies,
    response models, and every declared parameter. Following each field into its nested models is
    what makes the answer the whole document rather than its top-level shapes.
    """
    found: set[type[BaseModel]] = set()
    for field in get_fields_from_routes(app.routes):
        _collect_models(field.field_info.annotation, found)
    return _ordered(found)


def wire_models(app: FastAPI) -> tuple[type[BaseModel], ...]:
    """Every model this application exposes, from both sources."""
    both = set(models_extending_the_wire_base()) | set(models_the_contract_is_generated_from(app))
    return _ordered(both)


@dataclass(frozen=True, slots=True)
class InstantField:
    """One field whose value is an instant, wherever it was declared."""

    model: type[BaseModel]
    name: str
    annotation: object

    @property
    def where(self) -> str:
        return f"{qualified(self.model)}.{self.name}"

    @property
    def adapter(self) -> TypeAdapter[object]:
        """A validator over this field alone, so one field's reading is one assertion."""
        return TypeAdapter(self.annotation)


def instant_fields(models: tuple[type[BaseModel], ...]) -> tuple[InstantField, ...]:
    """Every field of ``models`` whose annotation carries an instant, in a stable order."""
    return tuple(
        InstantField(model=model, name=name, annotation=field.rebuild_annotation())
        for model in models
        for name, field in model.model_fields.items()
        if carries_an_instant(field.rebuild_annotation())
    )


@dataclass(frozen=True, slots=True)
class InstantParameter:
    """One query, path, or header parameter whose value is an instant."""

    method: str
    path: str
    alias: str
    annotation: object
    # Which of its route's instant parameters this is, in the order the route declares them. A
    # driver needs it: the two bounds of a span are declared in order and a request carrying one
    # value twice is refused for the ordering rather than for the reading under test.
    position: int

    @property
    def where(self) -> str:
        return f"{self.method} {self.path} ?{self.alias}"

    @property
    def adapter(self) -> TypeAdapter[object]:
        return TypeAdapter(self.annotation)


def instant_parameters(app: FastAPI) -> tuple[InstantParameter, ...]:
    """Every parameter of every route whose value is an instant."""
    found: list[InstantParameter] = []
    for route in api_routes(app):
        for method in sorted(route.methods):
            declared = [
                parameter
                for parameter in (
                    *route.dependant.query_params,
                    *route.dependant.path_params,
                    *route.dependant.header_params,
                )
                if carries_an_instant(parameter.field_info.annotation)
            ]
            found.extend(
                InstantParameter(
                    method=method,
                    path=route.path,
                    alias=parameter.alias,
                    annotation=parameter.field_info.annotation,
                    position=position,
                )
                for position, parameter in enumerate(declared)
            )
    return tuple(sorted(found, key=lambda one: one.where))


@dataclass(frozen=True, slots=True)
class InstantBodySite:
    """One request body field whose value is an instant, addressed as a caller sends it."""

    method: str
    path: str
    keys: tuple[str, ...]

    @property
    def field(self) -> str:
        """The field path a failure is reported under, which is what a 422 names."""
        return ".".join((BODY, *self.keys))

    @property
    def where(self) -> str:
        return f"{self.method} {self.path} {self.field}"

    def body(self, value: object) -> dict[str, object]:
        """A request body carrying ``value`` at this site and nothing else.

        Nothing else, deliberately: a body missing a required field is refused for that too, and
        an assertion about THIS field's failure is one the other failures cannot satisfy.
        """
        nested: dict[str, object] = {}
        holder = nested
        for key in self.keys[:-1]:
            branch: dict[str, object] = {}
            holder[key] = branch
            holder = branch
        holder[self.keys[-1]] = value
        return nested


def instant_body_sites(app: FastAPI) -> tuple[InstantBodySite, ...]:
    """Every request body field, on every route, whose value is an instant."""
    found = [
        InstantBodySite(method=method, path=route.path, keys=keys)
        for route in api_routes(app)
        for method in sorted(route.methods)
        for parameter in route.dependant.body_params
        for keys in _instant_keys(parameter.field_info.annotation, prefix=(), seen=frozenset())
    ]
    return tuple(sorted(found, key=lambda one: one.where))


def carries_an_instant(annotation: object) -> bool:
    """Whether ``annotation`` holds an instant, however it is spelled.

    Aliases are resolved, so a field spelled with the shared type and a field spelled with a bare
    ``datetime`` both answer true. That is what lets one walk find the fields to enforce over AND
    the fields that have not adopted the shared spelling.
    """
    return any(part in _INSTANT_READINGS for part in _parts(annotation))


def names_the_shared_instant(annotation: object) -> bool:
    """Whether ``annotation`` reaches its instant through the shared type, by name."""
    return any(part is WireInstant for part in _parts(annotation, resolve_aliases=False))


def takes_the_shared_reading(annotation: object) -> bool:
    """Whether ``annotation``'s instant is the reading the shared type resolves to.

    A weaker claim than :func:`names_the_shared_instant`, and it exists for parameters. The
    framework resolves an alias while it builds a parameter's field, so the alias is not there to
    be found afterwards and only the reading it resolved to is. A field spelled with an alias of
    its own would satisfy this and not the stricter claim, which is why bodies are held to that
    one.
    """
    resolved = set(_parts(WireInstant))
    return any(part in resolved for part in _parts(annotation) if part in _INSTANT_READINGS)


def _parts(annotation: object, *, resolve_aliases: bool = True) -> Iterator[object]:
    """``annotation`` and everything inside it: union members, aliases, annotated metadata."""
    yield annotation
    if isinstance(annotation, TypeAliasType):
        if resolve_aliases:
            yield from _parts(annotation.__value__, resolve_aliases=resolve_aliases)
        return
    for argument in get_args(annotation):
        yield from _parts(argument, resolve_aliases=resolve_aliases)


def _instant_keys(
    annotation: object, *, prefix: tuple[str, ...], seen: frozenset[type[BaseModel]]
) -> Iterator[tuple[str, ...]]:
    """Every path of wire keys under ``annotation`` that lands on an instant."""
    for model in _models_in(annotation):
        if model in seen:
            continue
        for name, field in model.model_fields.items():
            here = (*prefix, field.alias or name)
            if carries_an_instant(field.rebuild_annotation()):
                yield here
            yield from _instant_keys(field.annotation, prefix=here, seen=seen | {model})


def _models_in(annotation: object) -> tuple[type[BaseModel], ...]:
    return tuple(
        part
        for part in _parts(annotation)
        if isinstance(part, type) and issubclass(part, BaseModel)
    )


def _collect_models(annotation: object, found: set[type[BaseModel]]) -> None:
    for model in _models_in(annotation):
        if model in found:
            continue
        found.add(model)
        for field in model.model_fields.values():
            _collect_models(field.annotation, found)


def qualified(model: type[BaseModel]) -> str:
    """How a model is named wherever a claim here is about one."""
    return f"{model.__module__}.{model.__qualname__}"


def _ordered(models: Iterable[type[BaseModel]]) -> tuple[type[BaseModel], ...]:
    """A stable order, so a parametrized identifier names the same field on every run."""
    return tuple(sorted(models, key=qualified))
