"""The six reason clauses, one stored form each.

A clause's body only: which fields it holds, and how each is read back. The discriminator that
says which of the six a stored object is, the record that holds them, and the clause budget are
:mod:`syncr_api.plans.stored_reasons`, so the dispatch is stated once and this module is six
independent pairs a reader can check one at a time.

**A ``bound`` clause's source spans three vocabularies.** ``BoundSource`` is a habit's binding
source, a derivation source, or a placement the solver chose, and a stored clause holds one
string, so reading one has to decide which vocabulary the string belongs to. The three are
disjoint, which is what makes that decidable at all, and a test asserts the disjointness rather
than trusting it: a member added to any of them that collided with another would make one stored
clause name two sources.

Three of the six carry an arithmetic invariant of their own -- a share within the whole, a finite
objective delta, minute counts that are not negative -- and each is re-checked because each
constructor checks it. What restates such a refusal as the corruption of a stored row is the
dispatch, so it reads one way for all six.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from syncr_api.plans.errors import StoredDocumentCorrupt
from syncr_api.plans.stored_values import (
    read_date,
    read_id,
    read_interval,
    read_mapping,
    read_number,
    read_optional_id,
    read_optional_instant,
    read_optional_text,
    read_text,
    read_whole_number,
    stored_date,
    stored_id,
    stored_instant,
    stored_interval,
)
from syncr_domain.habits import BindingSource
from syncr_domain.reasons import (
    Blocked,
    Bound,
    ChurnBaseline,
    DerivationSource,
    Dominant,
    Floor,
    InsteadOf,
    Pinned,
    PlacedSource,
)

if TYPE_CHECKING:
    from syncr_api.core.columns import JsonDocument, JsonObject
    from syncr_domain.reasons import BoundSource

WINDOW = "window"
RULE = "rule"
DETAIL = "detail"

TERM = "term"
SHARE = "share"
BASELINE = "baseline"
REVISION_ID = "revision_id"
APPROVED_AT = "approved_at"

SOURCE = "source"
SELECTED = "selected"
CURSOR = "cursor"

AREA_ID = "area_id"
FLOOR_MINUTES = "floor_minutes"
PLACED = "placed"
OF = "of"

AT = "at"
PINNED_ON = "pinned_on"

PLACEMENT = "placement"
OBJECTIVE_DELTA = "objective_delta"

# The three vocabularies a `bound` clause's source spans, in the order a stored word is read
# against them. Disjoint, which is what makes one string decidable, and asserted to be.
BOUND_SOURCES: Final = (DerivationSource, BindingSource, PlacedSource)


def stored_blocked(clause: Blocked) -> JsonObject:
    """A candidate window and the hard constraint that rejected it."""
    return {WINDOW: stored_interval(clause.window), RULE: clause.rule, DETAIL: clause.detail}


def read_blocked(stored: JsonDocument, field: str) -> Blocked:
    return Blocked(
        window=read_interval(stored.get(WINDOW), field=f"{field}.{WINDOW}"),
        rule=read_text(stored.get(RULE), field=f"{field}.{RULE}"),
        detail=read_optional_text(stored.get(DETAIL), field=f"{field}.{DETAIL}"),
    )


def stored_dominant(clause: Dominant) -> JsonObject:
    """The objective term with the largest share of the plan's total cost."""
    return {
        TERM: clause.term,
        SHARE: clause.share,
        BASELINE: None if clause.baseline is None else _stored_baseline(clause.baseline),
    }


def read_dominant(stored: JsonDocument, field: str) -> Dominant:
    baseline = stored.get(BASELINE)
    return Dominant(
        term=read_text(stored.get(TERM), field=f"{field}.{TERM}"),
        share=read_number(stored.get(SHARE), field=f"{field}.{SHARE}"),
        baseline=(
            None if baseline is None else _read_baseline(baseline, field=f"{field}.{BASELINE}")
        ),
    )


def _stored_baseline(baseline: ChurnBaseline) -> JsonObject:
    """Which plan churn was measured against. Both halves, or neither, as the record states."""
    return {
        REVISION_ID: None if baseline.revision_id is None else stored_id(baseline.revision_id),
        APPROVED_AT: None if baseline.approved_at is None else stored_instant(baseline.approved_at),
    }


def _read_baseline(value: object, *, field: str) -> ChurnBaseline:
    stored = read_mapping(value, field=field)
    return ChurnBaseline(
        revision_id=read_optional_id(stored.get(REVISION_ID), field=f"{field}.{REVISION_ID}"),
        approved_at=read_optional_instant(stored.get(APPROVED_AT), field=f"{field}.{APPROVED_AT}"),
    )


def stored_bound(clause: Bound) -> JsonObject:
    """What determined this block's content, or its whole placement."""
    return {SOURCE: clause.source.value, SELECTED: clause.selected, CURSOR: clause.cursor}


def read_bound(stored: JsonDocument, field: str) -> Bound:
    return Bound(
        source=_read_bound_source(stored.get(SOURCE), field=f"{field}.{SOURCE}"),
        selected=read_text(stored.get(SELECTED), field=f"{field}.{SELECTED}"),
        cursor=read_optional_text(stored.get(CURSOR), field=f"{field}.{CURSOR}"),
    )


def _read_bound_source(value: object, *, field: str) -> BoundSource:
    word = read_text(value, field=field)
    for vocabulary in BOUND_SOURCES:
        if word in {member.value for member in vocabulary}:
            return vocabulary(word)
    named = ", ".join(sorted(member.value for source in BOUND_SOURCES for member in source))
    raise StoredDocumentCorrupt(
        f"{field} names {word!r}, which determines nothing: a bound clause names how a habit's "
        f"content was chosen, what fixed a derived block, or a placement the solver chose, and "
        f"those are {named}"
    )


def stored_floor(clause: Floor) -> JsonObject:
    """An Area floor that forced or forbade this placement."""
    return {
        AREA_ID: stored_id(clause.area_id),
        FLOOR_MINUTES: clause.floor_minutes,
        PLACED: clause.placed,
        OF: clause.of,
    }


def read_floor(stored: JsonDocument, field: str) -> Floor:
    return Floor(
        area_id=read_id(stored.get(AREA_ID), field=f"{field}.{AREA_ID}"),
        floor_minutes=read_whole_number(
            stored.get(FLOOR_MINUTES), field=f"{field}.{FLOOR_MINUTES}"
        ),
        placed=read_whole_number(stored.get(PLACED), field=f"{field}.{PLACED}"),
        of=read_whole_number(stored.get(OF), field=f"{field}.{OF}"),
    )


def stored_pinned(clause: Pinned) -> JsonObject:
    """The user's own edit, and the date they made it."""
    return {AT: stored_interval(clause.at), PINNED_ON: stored_date(clause.pinned_on)}


def read_pinned(stored: JsonDocument, field: str) -> Pinned:
    return Pinned(
        at=read_interval(stored.get(AT), field=f"{field}.{AT}"),
        pinned_on=read_date(stored.get(PINNED_ON), field=f"{field}.{PINNED_ON}"),
    )


def stored_instead_of(clause: InsteadOf) -> JsonObject:
    """The placement a pin overrode, and what overriding it cost."""
    return {PLACEMENT: stored_interval(clause.placement), OBJECTIVE_DELTA: clause.objective_delta}


def read_instead_of(stored: JsonDocument, field: str) -> InsteadOf:
    return InsteadOf(
        placement=read_interval(stored.get(PLACEMENT), field=f"{field}.{PLACEMENT}"),
        objective_delta=read_number(
            stored.get(OBJECTIVE_DELTA), field=f"{field}.{OBJECTIVE_DELTA}"
        ),
    )
