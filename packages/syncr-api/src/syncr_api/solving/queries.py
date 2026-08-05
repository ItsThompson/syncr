"""Reading the operation list's query: two optional filters, and an opaque page cursor.

Both filters are closed vocabularies, and a value outside either has to fail as a stated 422 rather
than as an empty page: `?status=done` is a client mistake, and answering it with no operations would
tell the user they have none.

**The cursor is keyset, not offset.** An operation created while a client is paging shifts every
offset after it, so an offset page silently skips a row; a key does not move. The key is
``(scheduled_for, id)``, which is the order the list is read in.

**The cursor is opaque because it is not a contract.** A client that parsed it would be coupled to
the ordering, and changing the ordering later would then be a breaking change rather than an
implementation detail. Base64url with no padding, so it survives a query string unescaped.

The shape is the anchor list's, deliberately: two list routes with two cursor spellings would be
two things for a client to learn about one idea.
"""

from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime
from typing import TYPE_CHECKING, Final
from uuid import UUID

from syncr_api.core.errors import FieldError, ValidationFailed
from syncr_api.solving.config import (
    OPERATION_KINDS,
    OPERATION_RESOURCE,
    OPERATION_STATUSES,
    OperationKind,
    OperationStatus,
)
from syncr_domain.intervals import as_instant

if TYPE_CHECKING:
    from syncr_domain.identifiers import OperationId

_SEPARATOR: Final = "|"
_PARTS: Final = 2
# What a base64 payload of an ISO instant plus a UUID needs, with room to spare. A longer value is
# rejected before it is decoded, so a megabyte-long query parameter costs one length check.
_MAX_ENCODED_LENGTH: Final = 256

# Everything decoding a client-supplied string can raise: a non-base64 token, a payload that is not
# UTF-8, a stamp that is not an instant, a naive stamp the interval algebra refuses (a
# `DomainError`, which is a `ValueError`), and an identifier that is not a UUID. Named rather than
# caught as `Exception`, so a genuine fault in this module still surfaces as a fault.
_MALFORMED = (UnicodeDecodeError, UnicodeEncodeError, ValueError)

_CURSOR_REJECTION = (
    "That page cursor could not be read, so no operations were returned. Nothing was changed. "
    "Drop the cursor to read the list from its start: a cursor is only meaningful as the value a "
    "previous page handed back."
)


def read_status(value: str | None) -> OperationStatus | None:
    """The status a query names, or ``None`` when it names none."""
    return _one_of(value, OPERATION_STATUSES, field="status", named="status")


def read_kind(value: str | None) -> OperationKind | None:
    """The kind a query names, or ``None`` when it names none."""
    return _one_of(value, OPERATION_KINDS, field="kind", named="kind")


def encode_cursor(after: tuple[datetime, OperationId]) -> str:
    """The keyset pair as the opaque token a client passes back."""
    scheduled_for, operation_id = after
    raw = f"{scheduled_for.isoformat()}{_SEPARATOR}{operation_id}"
    return urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str | None) -> tuple[datetime, OperationId] | None:
    """The keyset pair a cursor names, or ``None`` when there is no cursor.

    Raises a stated 422 for anything this module did not produce. The instant is normalized to UTC,
    so a cursor round-tripped through a client that rewrote the offset still names the same position
    in the ordering.
    """
    if cursor is None:
        return None
    if len(cursor) > _MAX_ENCODED_LENGTH:
        raise _malformed_cursor()
    try:
        parts = _decoded(cursor).split(_SEPARATOR)
    except _MALFORMED as exc:
        raise _malformed_cursor() from exc
    if len(parts) != _PARTS:
        raise _malformed_cursor()
    stamp, identifier = parts
    try:
        return as_instant(datetime.fromisoformat(stamp)), UUID(identifier)
    except _MALFORMED as exc:
        raise _malformed_cursor() from exc


def _one_of[MemberT: str](
    value: str | None, vocabulary: tuple[MemberT, ...], *, field: str, named: str
) -> MemberT | None:
    if value is None:
        return None
    if value not in vocabulary:
        raise _rejected(
            f"`{field}` names {value!r}, which is not an operation {named}, so no operations were "
            f"returned and nothing was changed. The {named}s are {', '.join(vocabulary)}. Leave "
            f"the parameter off to read every {named}.",
            field=field,
            message=f"must be one of {', '.join(vocabulary)}",
        )
    return value


def _decoded(cursor: str) -> str:
    padded = cursor + "=" * (-len(cursor) % 4)
    return urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")


def _malformed_cursor() -> ValidationFailed:
    return _rejected(
        _CURSOR_REJECTION, field="cursor", message=f"not an {OPERATION_RESOURCE} page cursor"
    )


def _rejected(detail: str, *, field: str, message: str) -> ValidationFailed:
    return ValidationFailed(detail, errors=[FieldError(field=field, message=message)])
