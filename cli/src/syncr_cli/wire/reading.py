"""Reading a value out of a payload the api sent, and saying where it was wrong.

Every reader takes the mapping and the member's name and raises
:class:`~syncr_cli.errors.MalformedResponse` naming the path when the member is absent or of
the wrong kind. A ``KeyError`` or a ``TypeError`` escaping to the top would exit 1 with a
traceback, which tells a user nothing and tells an agent less.

**Camel case, because that is what the api answers.** Every response body in the product is
camelCase so the generated TypeScript reads ``lastSeenAt``, and this package reads the same
document rather than a translation of it.

The one thing a reader will not do is coerce. A duration is an integer minute count on this
wire and a string that happens to parse is a contract violation, so it is reported as one.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from syncr_cli.errors import MalformedResponse

# The shape of any parsed JSON. Named so a payload carried for re-emission is typed as data
# rather than as `Any`, which would silently accept an object no renderer can serialize.
type JsonValue = bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"] | None
type JsonMapping = dict[str, JsonValue]


def mapping(payload: Any, path: str) -> JsonMapping:
    """``payload`` as an object, or a refusal naming ``path``."""
    if not isinstance(payload, dict):
        raise MalformedResponse(_wrong(path, "an object", payload))
    return payload


def member(payload: JsonMapping, name: str, path: str) -> JsonValue:
    """One member of ``payload``, or a refusal naming the member that is missing."""
    if name not in payload:
        raise MalformedResponse(
            f"the API's response has no {_named(path, name)}, which this command reads. Nothing "
            "was changed. Check that the API and this CLI are the same version."
        )
    return payload[name]


def nested(payload: JsonMapping, name: str, path: str) -> JsonMapping:
    """A member that is itself an object."""
    return mapping(member(payload, name, path), _named(path, name))


def optional_nested(payload: JsonMapping, name: str, path: str) -> JsonMapping | None:
    """A member that is an object or explicitly null. Absent reads as null."""
    value = payload.get(name)
    if value is None:
        return None
    return mapping(value, _named(path, name))


def sequence(payload: JsonMapping, name: str, path: str) -> list[JsonValue]:
    """A member that is an array."""
    value = member(payload, name, path)
    if not isinstance(value, list):
        raise MalformedResponse(_wrong(_named(path, name), "an array", value))
    return value


def mappings(payload: JsonMapping, name: str, path: str) -> list[JsonMapping]:
    """A member that is an array of objects."""
    where = _named(path, name)
    return [
        mapping(entry, f"{where}[{index}]")
        for index, entry in enumerate(sequence(payload, name, path))
    ]


def text(payload: JsonMapping, name: str, path: str) -> str:
    """A member that is a string."""
    value = member(payload, name, path)
    if not isinstance(value, str):
        raise MalformedResponse(_wrong(_named(path, name), "a string", value))
    return value


def optional_text(payload: JsonMapping, name: str, path: str) -> str | None:
    """A member that is a string or explicitly null. Absent reads as null."""
    value = payload.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise MalformedResponse(_wrong(_named(path, name), "a string or null", value))
    return value


def integer(payload: JsonMapping, name: str, path: str) -> int:
    """A member that is a whole number, which is how every duration crosses this wire.

    ``bool`` is refused explicitly: it is an ``int`` subclass in Python, so a ``true`` would
    otherwise read as one minute.
    """
    value = member(payload, name, path)
    if isinstance(value, bool) or not isinstance(value, int):
        raise MalformedResponse(_wrong(_named(path, name), "a whole number", value))
    return value


def boolean(payload: JsonMapping, name: str, path: str) -> bool:
    """A member that is a boolean."""
    value = member(payload, name, path)
    if not isinstance(value, bool):
        raise MalformedResponse(_wrong(_named(path, name), "true or false", value))
    return value


def instant(payload: JsonMapping, name: str, path: str) -> datetime:
    """A member that is an RFC 3339 instant with an explicit offset.

    An offset is required rather than assumed. A local string a reader has to guess the zone
    of is exactly what this wire does not carry, so one arriving is a contract violation
    rather than something to interpret with the machine's own zone.
    """
    raw = text(payload, name, path)
    where = _named(path, name)
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError as error:
        raise MalformedResponse(
            f"{where} is {raw!r}, which is not an RFC 3339 instant such as "
            "'2026-02-10T09:00:00+00:00'."
        ) from error
    if moment.tzinfo is None:
        raise MalformedResponse(
            f"{where} is {raw!r}, which states no UTC offset. Every instant on this wire "
            "carries one, so this CLI will not guess a zone for it."
        )
    return moment


def _named(path: str, name: str) -> str:
    return f"{path}.{name}" if path else name


def _wrong(path: str, expected: str, found: Any) -> str:
    return (
        f"{path} is {found!r}, and this command reads {expected} there. Nothing was changed. "
        "Check that the API and this CLI are the same version."
    )
