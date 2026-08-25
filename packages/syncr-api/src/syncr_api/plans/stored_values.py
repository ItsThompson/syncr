"""The leaf forms a stored plan document is built from, read and written in one place.

An instant, a span, a local date, an identifier, a whole number, and a member of a closed
vocabulary are the values every part of a document is ultimately made of, and each has exactly
one stored spelling here. A second spelling of any of them is how a block's interval would come
to round-trip while a pin clause's does not.

**Reading is where text becomes a value, and it is the only place that parses.** The domain
value types refuse anything malformed -- an interval refuses a naive datetime, a binding refuses
an identifier that is not a ``UUID`` -- so JSON, which carries only text, numbers and booleans,
has to be turned into those values somewhere. Doing it here means every rejection names the
field it came from instead of surfacing as a driver error or, worse, as a value that pairs with
nothing.

**An instant is written in UTC and read back as one.** ``as_instant`` normalizes an aware
datetime and refuses a naive one, so a span written from a stored week and read back is the same
value down to its offset.

**A boolean is not a number and a number is not a whole one.** ``bool`` is an ``int`` in
Python, so ``True`` would otherwise read as a count of one, and a fractional value would read as
a count the arithmetic cannot hold. Both are refused explicitly.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from syncr_api.plans.errors import StoredDocumentCorrupt
from syncr_domain.errors import DomainError
from syncr_domain.intervals import Interval, as_instant

if TYPE_CHECKING:
    from collections.abc import Callable
    from enum import StrEnum

    from syncr_api.core.columns import JsonDocument, JsonObject
    from syncr_domain.intervals import Instant
    from syncr_domain.zones import Date

# Everything parsing stored text can raise. `datetime.fromisoformat` and `UUID` both raise
# `ValueError`, and a domain refusal is a `DomainError`, which is one too. Named rather than
# caught as `Exception`, so a genuine fault in this module still surfaces as a fault.
_MALFORMED = (TypeError, ValueError)

START = "start"
END = "end"


def stored_instant(instant: Instant) -> str:
    """One moment, as the offset-carrying text a stored document holds."""
    return instant.isoformat()


def read_instant(value: object, *, field: str) -> Instant:
    """The moment a stored value names, or a stated refusal.

    The offset is not optional: a wall time with none names a different moment in every zone,
    so a week's blocks would silently shift by the reader's own offset.
    """
    text = read_text(value, field=field)
    try:
        return as_instant(datetime.fromisoformat(text))
    except _MALFORMED as error:
        raise _corrupt(field, text, "an instant carrying a UTC offset") from error


def read_optional_instant(value: object, *, field: str) -> Instant | None:
    """The moment a stored value names, or nothing when the document states none."""
    return None if value is None else read_instant(value, field=field)


def stored_interval(interval: Interval) -> JsonObject:
    """One span, as the pair of instants a stored document holds."""
    return {START: stored_instant(interval.start), END: stored_instant(interval.end)}


def read_interval(value: object, *, field: str) -> Interval:
    """The span a stored pair names, or a stated refusal.

    The bounds are read first and the span is built from them, so a reversed or zero-length
    pair is refused by the interval algebra rather than by a second statement of that rule.
    """
    stored = read_mapping(value, field=field)
    start = read_instant(stored.get(START), field=f"{field}.{START}")
    end = read_instant(stored.get(END), field=f"{field}.{END}")
    return rebuilt(lambda: Interval(start, end), field=field)


def read_optional_interval(value: object, *, field: str) -> Interval | None:
    """The span a stored pair names, or nothing when the document states none."""
    return None if value is None else read_interval(value, field=field)


def stored_date(on: Date) -> str:
    """One local date, as the text a stored document holds."""
    return on.isoformat()


def read_date(value: object, *, field: str) -> Date:
    """The local date a stored value names, or a stated refusal."""
    text = read_text(value, field=field)
    try:
        return date.fromisoformat(text)
    except _MALFORMED as error:
        raise _corrupt(field, text, "a local date in ISO 8601 form") from error


def stored_id(identifier: UUID) -> str:
    """One identifier, as the text a stored document holds."""
    return str(identifier)


def read_id(value: object, *, field: str) -> UUID:
    """The identifier a stored value names, or a stated refusal.

    The parse cannot be skipped: every identity in the domain is a ``UUID`` and the value types
    refuse text that merely looks like one, because one entity spelled two ways would take two
    identities.
    """
    text = read_text(value, field=field)
    try:
        return UUID(text)
    except _MALFORMED as error:
        raise _corrupt(field, text, "an identifier") from error


def read_optional_id(value: object, *, field: str) -> UUID | None:
    """The identifier a stored value names, or nothing when the document states none."""
    return None if value is None else read_id(value, field=field)


def read_whole_number(value: object, *, field: str) -> int:
    """The whole number a stored value names, or a stated refusal.

    Named for what it reads rather than for what its first caller counted: a minute figure, a chunk
    count and a chunk index are all this, and a name claiming minutes would be wrong at two of the
    three call sites.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise _corrupt(field, value, "a whole number")
    return value


def read_optional_whole_number(value: object, *, field: str) -> int | None:
    """The whole number a stored value names, or nothing when the document states none."""
    return None if value is None else read_whole_number(value, field=field)


def read_number(value: object, *, field: str) -> float:
    """The real number a stored value names, or a stated refusal."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _corrupt(field, value, "a number")
    return float(value)


def read_optional_number(value: object, *, field: str) -> float | None:
    """The real number a stored value names, or nothing when the document states none."""
    return None if value is None else read_number(value, field=field)


def read_flag(value: object, *, field: str) -> bool:
    """The boolean a stored value names, or a stated refusal."""
    if not isinstance(value, bool):
        raise _corrupt(field, value, "true or false")
    return value


def read_optional_flag(value: object, *, field: str) -> bool:
    """The boolean a stored value names, or false when the document states none.

    For a flag added to documents that already exist: a row written before the flag did
    reads as its default rather than as a corrupt row, which is what ``read_flag`` would
    call it.
    """
    return False if value is None else read_flag(value, field=field)


def read_text(value: object, *, field: str) -> str:
    """The string a stored value names, or a stated refusal."""
    if not isinstance(value, str):
        raise _corrupt(field, value, "text")
    return value


def read_optional_text(value: object, *, field: str) -> str | None:
    """The string a stored value names, or nothing when the document states none."""
    return None if value is None else read_text(value, field=field)


def read_member[MemberT: StrEnum](
    vocabulary: type[MemberT], value: object, *, field: str
) -> MemberT:
    """The member of a closed vocabulary a stored word names, or a stated refusal."""
    word = read_text(value, field=field)
    try:
        return vocabulary(word)
    except ValueError as error:
        named = ", ".join(sorted(member.value for member in vocabulary))
        raise StoredDocumentCorrupt(
            f"{field} names {word!r}, which is not one of {named}: a stored document holds a "
            "closed vocabulary, and a value outside it names a state no reader knows"
        ) from error


def read_mapping(value: object, *, field: str) -> JsonDocument:
    """The object a stored value names, or a stated refusal."""
    if not isinstance(value, dict):
        raise _corrupt(field, value, "an object")
    return value


def read_list(value: object, *, field: str) -> list[Any]:
    """The array a stored value names, or a stated refusal.

    An absent key is an empty array rather than a refusal, because every collection a document
    holds defaults to empty: a week with no forbidden windows holds none.
    """
    if value is None:
        return []
    if not isinstance(value, list):
        raise _corrupt(field, value, "an array")
    return value


def rebuilt[ValueT](build: Callable[[], ValueT], *, field: str) -> ValueT:
    """``build()``, with a domain refusal restated as the corruption of a stored row.

    Every value type a document holds states invariants of its own, and a stored row can break
    any of them: a block with no title, a window whose scope and Areas disagree, a binding whose
    occurrence key does not match its kind. Restated once so one category of failure reads one
    way wherever a document is read, and the domain's own message is carried through rather than
    replaced: it already says which invariant fell and why it exists.
    """
    try:
        return build()
    except DomainError as error:
        raise StoredDocumentCorrupt(f"{field} could not be rebuilt: {error}") from error


def _corrupt(field: str, value: object, expected: str) -> StoredDocumentCorrupt:
    return StoredDocumentCorrupt(
        f"{field} holds {value!r}, and a stored plan document states {expected} there: a row "
        "that cannot be rebuilt describes no week, so it is refused where it is read rather "
        "than resolved to a value that pairs with nothing"
    )
