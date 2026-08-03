"""Absent and null, kept apart on a ``PATCH``.

A partial update over a nullable field has three cases, not two: leave it alone, set it, or
clear it. A schema field defaulting to ``None`` collapses the first and the third, so sending
``null`` to clear a floor and omitting the field entirely become the same request and one of
the two intentions is unreachable.

Pydantic already records which fields a request named, in ``model_fields_set``. What is
missing is a value a service can hold for "not named", so this is that value and the two
functions that put it in and take it out.

There is no ``ABSENT`` on the wire. It is never a schema default and never serialized: a
request states a field or it does not, and this type exists only between the route that reads
the request and the service that applies it.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pydantic import BaseModel


class Absent(Enum):
    """The type of :data:`ABSENT`, so a patched value is a closed union of two cases."""

    TOKEN = auto()


ABSENT: Final = Absent.TOKEN

type Patched[ValueT] = ValueT | Absent


def stated[ValueT](body: BaseModel, field: str, value: ValueT) -> Patched[ValueT]:
    """``value`` when the request named ``field``, else :data:`ABSENT`.

    For a NULLABLE field, where an explicit null is a legal value meaning "clear this". The
    value is passed in rather than read off the body, so the call is type-checked against the
    field it names instead of resolving an attribute by string at runtime.
    """
    return value if field in body.model_fields_set else ABSENT


def stated_unless_null[ValueT](value: ValueT | None) -> Patched[ValueT]:
    """``value`` unless it is ``None``, in which case :data:`ABSENT`.

    For a field that is NOT nullable. Its schema refuses an explicit null, so ``None`` can only
    mean the request left the field out, and the body does not have to be consulted at all.
    """
    return ABSENT if value is None else value


def resolved[ValueT](patched: Patched[ValueT], current: ValueT) -> ValueT:
    """``patched`` when the request stated it, else the value already stored."""
    return current if isinstance(patched, Absent) else patched
