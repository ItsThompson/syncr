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
written, and it is the only source that would reach a shape the event stream serialises without a
route. A walk keyed on the module NAME ``schemas`` would miss ``core/notices.py`` and three of
the plan package's four schema modules, so this one is keyed on the base class instead.

``models_the_contract_is_generated_from`` asks the framework for the fields it renders the
OpenAPI document from, and follows each into its nested shapes. That reaches a shape that does
NOT extend the wire base -- the learning routes declare their own camel-casing base -- which the
first source cannot see. It is also, by construction, the population the committed document
describes, which is what lets a caller bound this walk from above by crossing the two sizes.

Every helper returns data rather than asserting, so a claim can be checked against the real
application AND against an input built to break it. A walk with no positive control passes
forever once it has gone blind, and the equality it certifies can hold with both sides empty.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeAliasType, get_args, get_origin

from fastapi.openapi.utils import get_fields_from_routes
from pydantic import BaseModel, TypeAdapter
from pydantic.errors import PydanticSchemaGenerationError

import syncr_api
from syncr_api.core.schemas import WireInstant, WireModel, WireText

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from types import ModuleType

    from fastapi import FastAPI

# What pydantic calls a moment in the schema it builds, whichever reading a field was declared with:
# the lax ``datetime``, the aware and naive markers, and the two that bound a moment against now all
# answer to this. Asking the framework rather than matching a list of names keeps a marker it adds
# later in scope.
_A_MOMENT = "datetime"


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


def instant_fields_rendered_by_a_serializer(
    fields: tuple[InstantField, ...],
) -> tuple[str, ...]:
    """Every instant field whose own model declares a serializer that renders it.

    A validator built from a field's annotation renders what the ANNOTATION says. A
    ``field_serializer`` or a ``model_serializer`` on the model renders what the MODEL says, and no
    reading of the annotation can see one, so a serializer that dropped an offset would leave the
    per-field instrument green while the socket carried an offset-less value. So this reads the
    DECLARATION rather than the rendering, and the rendering stays where the instrument can see it,
    in the shared type.

    ``__pydantic_decorators__`` is private and there is no public accessor for a model's declared
    serializers. The failure mode is loud rather than silent: a rename raises ``AttributeError`` and
    this reading errors instead of answering that nothing was found. It also carries a parent's
    decorators onto a subclass, which is what covers an inherited field.
    """
    found: list[str] = []
    for field in fields:
        decorators = field.model.__pydantic_decorators__
        covered = {
            name
            for name, decorator in decorators.field_serializers.items()
            if field.name in decorator.info.fields or "*" in decorator.info.fields
        }
        covered |= set(decorators.model_serializers)
        found.extend(f"{field.where} rendered by {name}" for name in sorted(covered))
    return tuple(sorted(found))


@dataclass(frozen=True, slots=True)
class TextField:
    """One field whose value is user-authored text under a length bound."""

    model: type[BaseModel]
    name: str
    annotation: object
    repeated: bool = False

    @property
    def where(self) -> str:
        return f"{qualified(self.model)}.{self.name}"

    @property
    def adapter(self) -> TypeAdapter[object]:
        """A validator over this field alone, so one field's reading is one assertion."""
        return TypeAdapter(self.annotation)

    def accept(self, value: str) -> object:
        """Validate one probe string the way the field would receive it."""
        probe: object = [value] if self.repeated else value
        return self.adapter.validate_python(probe)

    @property
    def bounds(self) -> tuple[int | None, int | None]:
        """The tightest (min, max) length bound any part of the value carries.

        A list field carries the item bounds and the list's own bound; the item is what a
        probe string is measured against, so the item's min is the larger min and the item's
        max is the smaller max.
        """
        minimums: list[int] = []
        maximums: list[int] = []
        for low, high in _length_bounds(self.annotation):
            if low is not None:
                minimums.append(low)
            if high is not None:
                maximums.append(high)
        return (
            max(minimums) if minimums else None,
            min(maximums) if maximums else None,
        )


def text_fields(models: tuple[type[BaseModel], ...]) -> tuple[TextField, ...]:
    """Every field of ``models`` whose value is a length-bounded string, in a stable order.

    The seam is a string that satisfies a length bound: a bare ``str`` anywhere in the
    annotation and a length constraint on some part of it. That reaches both spellings -- a
    field already on the shared user-text type AND a field still declared with its own
    ``Field(min_length=...)`` -- which is what lets an adoption test cover the whole surface
    rather than the fields someone remembered.
    """
    found: list[TextField] = []
    for model in models:
        for name, field in model.model_fields.items():
            annotation = field.rebuild_annotation()
            if _carries_a_bare_str(annotation) and _carries_a_length_bound(annotation):
                found.append(
                    TextField(
                        model=model,
                        name=name,
                        annotation=annotation,
                        repeated=_is_a_list_of_strings(annotation),
                    )
                )
    return tuple(found)


def names_the_shared_text(annotation: object) -> bool:
    """Whether ``annotation`` reaches its string through the shared user-text type.

    Aliases are followed one level at a time rather than resolved wholesale, so a field
    declared through a module-local alias of the shared type counts while a second spelling
    of the same reading does not: one name is the claim.
    """
    if annotation is WireText:
        return True
    if isinstance(annotation, TypeAliasType):
        return names_the_shared_text(annotation.__value__)
    return any(names_the_shared_text(argument) for argument in get_args(annotation))


def _carries_a_bare_str(annotation: object) -> bool:
    return any(part is str for part in _parts(annotation))


def _carries_a_length_bound(annotation: object) -> bool:
    return any(bound != (None, None) for bound in _length_bounds(annotation))


def _length_bounds(annotation: object) -> Iterator[tuple[int | None, int | None]]:
    """Every (min, max) length pair declared on any part of ``annotation``.

    A bound declared through ``Field(...)`` sits on the field info; one declared through a
    module-local alias is normalized by pydantic into ``MinLen``/``MaxLen`` markers one level
    down, so the metadata is descended into rather than read off one object.
    """
    for part in _parts(annotation):
        if isinstance(part, type | TypeAliasType):
            continue
        low = getattr(part, "min_length", None)
        high = getattr(part, "max_length", None)
        if low is not None or high is not None:
            yield (low, high)
        for marker in getattr(part, "metadata", ()) or ():
            yield from _length_bounds(marker)


def _is_a_list_of_strings(annotation: object) -> bool:
    """Whether the field's own value is a list of such strings, rather than one."""
    return any(
        get_origin(part) is list and _carries_a_bare_str(part) for part in _parts(annotation)
    )


def carries_an_instant(annotation: object) -> bool:
    """Whether ``annotation`` holds a moment, however it was spelled.

    Aliases are resolved and every reading pydantic has counts, so a field spelled with the shared
    type, one spelled with a bare ``datetime``, and one spelled with the naive marker all answer
    true. That is what lets one walk find the fields to enforce over AND the fields that have not
    adopted the shared spelling, including the laxer spellings that would reintroduce what this
    surface exists to refuse.
    """
    return any(_is_a_moment(part) for part in _parts(annotation))


def _is_a_moment(part: object) -> bool:
    """Whether ``part`` is one of pydantic's readings of a moment, asked of pydantic.

    A leaf, never a model: a shape that HOLDS an instant is not one, and descending into its fields
    here would make every response carrying a span an instant field of its own.
    """
    if not isinstance(part, type) or issubclass(part, BaseModel):
        return False
    try:
        schema = TypeAdapter(part).core_schema
    except PydanticSchemaGenerationError:
        return False
    return schema.get("type") == _A_MOMENT


def names_the_shared_instant(annotation: object) -> bool:
    """Whether ``annotation`` reaches its instant through the shared type, by name.

    By name rather than by reading, so a field that reached the same aware reading through a second
    alias of its own does NOT satisfy it: one spelling is the claim.
    """
    return any(part is WireInstant for part in _parts(annotation, resolve_aliases=False))


def _parts(annotation: object, *, resolve_aliases: bool = True) -> Iterator[object]:
    """``annotation`` and everything inside it: union members, aliases, annotated metadata."""
    yield annotation
    if isinstance(annotation, TypeAliasType):
        if resolve_aliases:
            yield from _parts(annotation.__value__, resolve_aliases=resolve_aliases)
        return
    for argument in get_args(annotation):
        yield from _parts(argument, resolve_aliases=resolve_aliases)


def models_in(annotation: object) -> tuple[type[BaseModel], ...]:
    """Every model ``annotation`` names, without descending into their fields."""
    return tuple(
        part
        for part in _parts(annotation)
        if isinstance(part, type) and issubclass(part, BaseModel)
    )


def _collect_models(annotation: object, found: set[type[BaseModel]]) -> None:
    for model in models_in(annotation):
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
