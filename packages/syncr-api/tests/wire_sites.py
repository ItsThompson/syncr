"""How a caller addresses an instant: a body key path, or a query parameter.

`wire_census.py` answers what the wire declares. This answers where a client puts a value and what
the api calls that place when it refuses one, which is the other half of driving a refusal through a
real route: the field path in a 422 has to be the path the request used, or an assertion about the
error naming a field is an assertion about the wrong string.

**A parameter's declared annotation is read from the endpoint rather than from the built field.**
FastAPI resolves an alias while it builds a parameter's field, so `field_info.annotation` on a
parameter declared with the shared type is the reading that type resolves to and the alias is gone.
It survives on the function itself: `get_type_hints(endpoint, include_extras=True)` answers with the
alias, by identity. Both are kept, because they answer two questions -- what the value must be, and
how the route spelled it -- and a parameter is held to the strict spelling claim a body field is.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, get_type_hints

from pydantic import TypeAdapter

from tests.boundaries import api_routes
from tests.wire_census import carries_an_instant, models_in

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import FastAPI
    from pydantic import BaseModel

# What a body param is called when a route declares one model for the whole body, which is the shape
# every route in this application uses. FastAPI reports a field's failure under this prefix, so a
# driver naming a field has to agree with it.
BODY = "body"


@dataclass(frozen=True, slots=True)
class InstantParameter:
    """One query, path, or header parameter whose value is an instant."""

    method: str
    path: str
    alias: str
    annotation: object
    # How the endpoint spelled it, which is where the alias survives.
    declared: object
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
        hints = get_type_hints(route.endpoint, include_extras=True)
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
                    declared=hints[parameter.name],
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


def _instant_keys(
    annotation: object, *, prefix: tuple[str, ...], seen: frozenset[type[BaseModel]]
) -> Iterator[tuple[str, ...]]:
    """Every path of wire keys under ``annotation`` that lands on an instant."""
    for model in models_in(annotation):
        if model in seen:
            continue
        for name, field in model.model_fields.items():
            here = (*prefix, field.alias or name)
            if carries_an_instant(field.rebuild_annotation()):
                yield here
            yield from _instant_keys(field.annotation, prefix=here, seen=seen | {model})
