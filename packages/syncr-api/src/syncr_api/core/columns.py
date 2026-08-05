"""The column vocabulary the plan-side tables share, and the two SQL helpers.

Four things are stated here because four feature packages read them.

``JsonObject`` and ``JsonDocument`` are the two Python shapes of a ``JSONB`` column: what
the mapper round-trips, and what a caller hands a repository to store. A document's
interior is NOT validated at the database level. JSONB is schemaless there, and the
Pydantic model that writes a document is what enforces its shape, so what the column owes
its readers is a stable Python type rather than a schema.

``ISO_WEEK_LENGTH`` is the one definition of how wide a stored week is. A week is stored
as its identifier (``2026-W07``) rather than as a year and a week number, because sorting
the identifier and sorting the week agree, and every read is either for one exact week or
for an ordered range of them.

``values_in`` renders a column's closed set of legal values as a check constraint, and
``json_key`` renders one key of a JSONB column as the expression an index is built over. The
set and the key both live in the owning package, so neither statement of either can drift
alone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.sql.elements import TextClause

# The mutable mapping a JSONB column round-trips.
type JsonObject = dict[str, Any]

# What a caller hands a repository to store in one. Read-only, so a document cannot be
# mutated by its author after the write was composed from it.
type JsonDocument = Mapping[str, Any]

# The type a NULLABLE JSONB column is declared with. Without ``none_as_null`` a Python ``None``
# is stored as the JSON value ``null``, which is not SQL NULL: a check constraint reading
# ``IS NOT NULL`` would hold for a column nobody set, and so would a query looking for one. The
# instance is shared between columns, which SQLAlchemy supports, because a type carries no
# per-column state.
NULLABLE_JSONB = JSONB(none_as_null=True)

# `2026-W07`: four digits, `-W`, two digits.
ISO_WEEK_LENGTH = 8


def json_key(column: str, key: str) -> TextClause:
    """The SQL an index over one key of a ``JSONB`` column is built over.

    An expression index needs the extraction as SQL, and rendering it here means the index and
    the writer name the same key: a caller passes the constant its own serializer writes rather
    than a string spelled a second time. The rejection makes that a property of the call rather
    than a convention, exactly as :func:`values_in`'s does: a key carrying a quote would close
    the string and whatever followed would be read as SQL.
    """
    if "'" in column:
        raise ValueError(f"a column name carries a quote, which would end the string: {column!r}")
    if "'" in key:
        raise ValueError(f"{column}'s key carries a quote, which would end it: {key!r}")
    return text(f"({column} ->> '{key}')")


def values_in(column: str, values: Sequence[str]) -> str:
    """The SQL for ``column`` holding one of ``values``.

    A closed vocabulary is enforced by the database as well as by the type annotation,
    because the annotation is erased at runtime and a caller reaching this table from a
    later migration or a ``psql`` session is not type-checked at all.

    Every caller passes its own package's constants, so the members are rendered as literals
    rather than bound. The rejection makes that a property of the call rather than a
    convention: a member carrying a quote would close the string and whatever followed would
    be read as SQL.
    """
    quoted = [value for value in values if "'" in value]
    if quoted:
        raise ValueError(f"{column}'s vocabulary carries a quote, which would end it: {quoted}")
    rendered = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({rendered})"
