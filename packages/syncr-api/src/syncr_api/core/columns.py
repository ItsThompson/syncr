"""The column vocabulary the plan-side tables share, and the check-constraint helper.

Three things are stated here because four feature packages read them.

``JsonObject`` and ``JsonDocument`` are the two Python shapes of a ``JSONB`` column: what
the mapper round-trips, and what a caller hands a repository to store. A document's
interior is NOT validated at the database level. JSONB is schemaless there, and the
Pydantic model that writes a document is what enforces its shape, so what the column owes
its readers is a stable Python type rather than a schema.

``ISO_WEEK_LENGTH`` is the one definition of how wide a stored week is. A week is stored
as its identifier (``2026-W07``) rather than as a year and a week number, because sorting
the identifier and sorting the week agree, and every read is either for one exact week or
for an ordered range of them.

``values_in`` renders a column's closed set of legal values as a check constraint. The set
itself lives in the owning package's ``config.py``, so the database rejects a value the
application does not name and neither statement of the set can drift alone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.dialects.postgresql import JSONB

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

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
