"""Reading the anchor list's query: a bounded span, and an opaque page cursor.

Both are client-supplied and both have to fail as a stated 422 rather than as a fault. The
interval algebra refuses a reversed or zero-length span by raising a domain error, and nothing
maps a domain error to a status, so a route that built an ``Interval`` straight from two query
parameters would answer 500 to `?from=X&to=X`.

**A span bound states its offset.** `13-http-api.md` requires an instant to carry one always, and
the interval algebra refuses a naive datetime by raising a domain error nothing maps, so a route
that built an ``Interval`` straight from two query parameters would answer 500 to a bound written
without one. Refused here instead, naming the parameter. This covers this route's own PARAMETERS
only: an instant inside a request body is the shared wire boundary's concern, and folding both into
one place belongs with the ticket that adds a shared instant type.

**The span is bounded.** A read of "every commitment ever" is not a question the interface asks:
the week view reads a week and the Settings panel reads a projection horizon. Bounding it is what
keeps one request's row count a function of a bound syncr owns rather than of how many years of
timetable a publisher chose to feed.

**The cursor is keyset, not offset.** A sync that inserts a commitment earlier than the page a
client is reading shifts every offset after it, so an offset page silently skips a row; a key does
not move. The key is ``(starts_at, id)``, which is the order the list is read in and the leading
columns of the span index.

**The cursor is opaque because it is not a contract.** A client that parsed it would be coupled
to the ordering, and changing the ordering later would then be a breaking change rather than an
implementation detail. Base64url with no padding, so it survives a query string unescaped.
"""

from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final
from uuid import UUID

from syncr_api.anchors.config import ANCHOR_RESOURCE, ANCHOR_SPAN_DAYS_MAX
from syncr_api.core.errors import FieldError, ValidationFailed
from syncr_domain.intervals import Interval, as_instant

if TYPE_CHECKING:
    from syncr_api.anchors.records import AnchorId

_SEPARATOR: Final = "|"
_PARTS: Final = 2
# What a base64 payload of an ISO instant plus a UUID needs, with room to spare. A longer value is
# rejected before it is decoded, so a megabyte-long query parameter costs one length check.
_MAX_ENCODED_LENGTH: Final = 256

_MAX_SPAN: Final = timedelta(days=ANCHOR_SPAN_DAYS_MAX)

# Everything decoding a client-supplied string can raise: a non-base64 token, a payload that is
# not UTF-8, a stamp that is not an instant, a naive stamp the interval algebra refuses (a
# `DomainError`, which is a `ValueError`), and an identifier that is not a UUID. Named rather than
# caught as `Exception`, so a genuine fault in this module still surfaces as a fault.
_MALFORMED = (UnicodeDecodeError, UnicodeEncodeError, ValueError)

_CURSOR_REJECTION = (
    "That page cursor could not be read, so no commitments were returned. Nothing was changed. "
    "Drop the cursor to read the span from its start: a cursor is only meaningful as the value a "
    "previous page handed back."
)


def read_span(start: datetime, end: datetime) -> Interval:
    """The span two query parameters name, or a stated rejection.

    Half-open, so `from` equal to `to` covers nothing and is refused rather than answered with an
    empty page: a caller asking for a zero-width window has made a mistake, and an empty list
    would read as "you have nothing on".
    """
    for field, bound in (("from", start), ("to", end)):
        if bound.tzinfo is None or bound.tzinfo.utcoffset(bound) is None:
            raise _rejected(
                f"`{field}` carries no UTC offset, so it names no instant and no commitments were "
                "returned. Nothing was changed. Send an offset: `2026-02-09T09:00:00Z` or "
                "`2026-02-09T09:00:00+00:00`. A wall time without one means a different moment in "
                "every zone, and the span decides which commitments a week holds.",
                field=field,
                message="must carry a UTC offset",
            )
    if end <= start:
        raise _rejected(
            "A commitment span needs `to` after `from`, and this one ended at or before it. "
            "Nothing was returned and nothing was changed. Ask for a span that covers time: "
            "`from` is included and `to` is not.",
            field="to",
            message="must be after `from`",
        )
    if end - start > _MAX_SPAN:
        raise _rejected(
            f"A commitment span may cover at most {ANCHOR_SPAN_DAYS_MAX} days and this one "
            f"covered {(end - start).days}. Nothing was returned and nothing was changed. Read it "
            "in shorter spans: every commitment inside each of them is still reported.",
            field="to",
            message=f"must be at most {ANCHOR_SPAN_DAYS_MAX} days after `from`",
        )
    return Interval(start, end)


def encode_cursor(after: tuple[datetime, AnchorId]) -> str:
    """The keyset pair as the opaque token a client passes back."""
    starts_at, anchor_id = after
    raw = f"{starts_at.isoformat()}{_SEPARATOR}{anchor_id}"
    return urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str | None) -> tuple[datetime, AnchorId] | None:
    """The keyset pair a cursor names, or ``None`` when there is no cursor.

    Raises a stated 422 for anything this module did not produce. The instant is normalized to
    UTC, so a cursor round-tripped through a client that rewrote the offset still names the same
    position in the ordering.
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


def _decoded(cursor: str) -> str:
    padded = cursor + "=" * (-len(cursor) % 4)
    return urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")


def _malformed_cursor() -> ValidationFailed:
    return _rejected(
        _CURSOR_REJECTION, field="cursor", message=f"not a {ANCHOR_RESOURCE} page cursor"
    )


def _rejected(detail: str, *, field: str, message: str) -> ValidationFailed:
    return ValidationFailed(detail, errors=[FieldError(field=field, message=message)])
