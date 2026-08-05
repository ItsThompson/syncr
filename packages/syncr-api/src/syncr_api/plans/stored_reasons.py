"""A block's reason record, as the object a stored document holds, and the six kinds' dispatch.

A clause is a Python type in the domain and a JSON object here, so the two need a discriminator
the domain does not carry: ``ReasonRecord`` distinguishes its members by their class, and JSON has
no class. :data:`CLAUSE_KIND` is that discriminator. It is keyed on the types themselves, so the
inventory it is crossed against is :data:`~syncr_domain.reasons.CLAUSE_BUDGET`, the domain's own
table of what a record may hold: a seventh clause kind reaching the domain fails here until it has
a stored word and a reader.

**Writing dispatches statically and reading dispatches on text.** A value's kind is its type, so
the writer is a ``match`` whose totality ``assert_never`` holds at type-check time. A stored
object's kind is a word, so the reader is a table lookup and an unknown word is refused with the
six named. The bodies themselves are :mod:`syncr_api.plans.stored_clauses`.

**A domain refusal is restated once, here.** Three of the six clauses carry an arithmetic
invariant a stored row can break, and the record carries the clause budget, so both raise a
``ReasonError``. Restating it at the dispatch rather than in each reader is what makes one category
of failure read one way wherever a document is read.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, assert_never

from syncr_api.plans.errors import StoredDocumentCorrupt
from syncr_api.plans.stored_clauses import (
    read_blocked,
    read_bound,
    read_dominant,
    read_floor,
    read_instead_of,
    read_pinned,
    stored_blocked,
    stored_bound,
    stored_dominant,
    stored_floor,
    stored_instead_of,
    stored_pinned,
)
from syncr_api.plans.stored_values import read_list, read_mapping, read_text
from syncr_domain.reasons import (
    Blocked,
    Bound,
    Clause,
    Dominant,
    Floor,
    InsteadOf,
    Pinned,
    ReasonError,
    ReasonRecord,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from syncr_api.core.columns import JsonDocument, JsonObject

KIND = "kind"
CLAUSES = "clauses"

# One stored word per clause type, keyed on the types themselves rather than on a parallel list of
# names, so the inventory this is crossed against is the domain's own budget table.
CLAUSE_KIND: Final[Mapping[type[Clause], str]] = {
    Blocked: "blocked",
    Dominant: "dominant",
    Bound: "bound",
    Floor: "floor",
    Pinned: "pinned",
    InsteadOf: "instead_of",
}

# One reader per stored word, because reading dispatches on text. The writers dispatch on the
# type instead, so what a new kind needs is an entry here plus a branch `assert_never` will not
# let anyone forget.
READERS: Final[Mapping[str, Callable[[JsonDocument, str], Clause]]] = {
    CLAUSE_KIND[Blocked]: read_blocked,
    CLAUSE_KIND[Dominant]: read_dominant,
    CLAUSE_KIND[Bound]: read_bound,
    CLAUSE_KIND[Floor]: read_floor,
    CLAUSE_KIND[Pinned]: read_pinned,
    CLAUSE_KIND[InsteadOf]: read_instead_of,
}


def stored_reason(reason: ReasonRecord) -> JsonObject:
    """One block's reason record, as the object a stored document holds."""
    return {CLAUSES: [_stored_clause(clause) for clause in reason.clauses]}


def read_reason(value: object, *, field: str) -> ReasonRecord:
    """The reason record a stored object names, or a stated refusal.

    The record's own constructor applies the clause budget, so a document holding three
    ``blocked`` clauses is refused here rather than growing a revision nobody bounded.
    """
    stored = read_mapping(value, field=field)
    clauses = read_list(stored.get(CLAUSES), field=f"{field}.{CLAUSES}")
    read = tuple(
        _read_clause(clause, field=f"{field}.{CLAUSES}[{position}]")
        for position, clause in enumerate(clauses)
    )
    try:
        return ReasonRecord(read)
    except ReasonError as error:
        raise _not_a_reason(field, error) from error


def _stored_clause(clause: Clause) -> JsonObject:
    """One clause and its kind. Total over the six, which ``assert_never`` is what holds."""
    match clause:
        case Blocked():
            body = stored_blocked(clause)
        case Dominant():
            body = stored_dominant(clause)
        case Bound():
            body = stored_bound(clause)
        case Floor():
            body = stored_floor(clause)
        case Pinned():
            body = stored_pinned(clause)
        case InsteadOf():
            body = stored_instead_of(clause)
        case _:  # pragma: no cover - unreachable while the union holds six members
            assert_never(clause)
    return {KIND: CLAUSE_KIND[type(clause)], **body}


def _read_clause(value: object, *, field: str) -> Clause:
    """The clause a stored object names, or a stated refusal."""
    stored = read_mapping(value, field=field)
    kind = read_text(stored.get(KIND), field=f"{field}.{KIND}")
    reader = READERS.get(kind)
    if reader is None:
        named = ", ".join(sorted(CLAUSE_KIND.values()))
        raise StoredDocumentCorrupt(
            f"{field} is a {kind!r} clause, and the reason panel renders one template per kind, "
            f"so a kind with no template renders nothing at all. The kinds are {named}"
        )
    try:
        return reader(stored, field)
    except ReasonError as error:
        raise _not_a_reason(field, error) from error


def _not_a_reason(field: str, error: ReasonError) -> StoredDocumentCorrupt:
    return StoredDocumentCorrupt(f"{field} is not a reason a block can carry: {error}")
