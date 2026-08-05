"""A stored proposal diff, written from and rebuilt through the domain constructors.

``pending_proposals.proposal_diff`` is what the grid renders proposal targets from and what the
approval path reads, so the pair of functions here is the whole boundary between the diff as a
value and the diff as a column, and both directions go through the same value type.

**The week is written once, by the row that holds the diff.** A change derives the block it names
from the week and the binding, exactly as a block does, so a week per change would be a second
statement of one fact and the only thing a second statement can do is disagree. The reader is
handed the week its row names and rebuilds every change against it.

**Which list a change is in is what kind of change it is**, so nothing here writes a kind. The
three keys are the three lists, and the value type refuses a change whose placements disagree with
the list it arrived in, which is what makes a corrupt row say so here rather than downstream.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.plans.stored_documents import read_binding, stored_binding
from syncr_api.plans.stored_reasons import read_reason, stored_reason
from syncr_api.plans.stored_values import (
    read_list,
    read_mapping,
    read_optional_id,
    read_optional_interval,
    read_text,
    rebuilt,
    stored_id,
    stored_interval,
)
from syncr_domain.proposals import BlockChange, ProposalDiff

if TYPE_CHECKING:
    from syncr_api.core.columns import JsonDocument, JsonObject
    from syncr_domain.weeks import IsoWeek

ADDED = "added"
REMOVED = "removed"
MOVED = "moved"

BINDING = "binding"
TITLE = "title"
AREA_ID = "area_id"
REASON = "reason"
BEFORE = "before"
AFTER = "after"


def stored_proposal_diff(diff: ProposalDiff) -> JsonObject:
    """The assent-requiring changes, as the object a ``proposal_diff`` column holds."""
    return {
        ADDED: [_stored_change(change) for change in diff.added],
        REMOVED: [_stored_change(change) for change in diff.removed],
        MOVED: [_stored_change(change) for change in diff.moved],
    }


def read_proposal_diff(stored: JsonDocument, iso_week: IsoWeek) -> ProposalDiff:
    """The diff a stored object describes, rebuilt against the week its row names.

    Every change is rebuilt through the value type, so a diff that reaches a caller has already
    satisfied what the domain states about a proposal: each change agrees with its list, no move
    leaves a block where it was, and one block is named once.
    """
    return rebuilt(
        lambda: ProposalDiff(
            added=_each(stored, ADDED, iso_week),
            removed=_each(stored, REMOVED, iso_week),
            moved=_each(stored, MOVED, iso_week),
        ),
        field="the proposal diff",
    )


def _each(stored: JsonDocument, key: str, iso_week: IsoWeek) -> tuple[BlockChange, ...]:
    """One list of changes, each read under a field naming its position.

    The position is in the field name for the reason a document's blocks carry theirs: a refusal
    has to say WHICH change could not be rebuilt, and changes are not named.
    """
    return tuple(
        _read_change(member, iso_week, field=f"{key}[{position}]")
        for position, member in enumerate(read_list(stored.get(key), field=key))
    )


def _stored_change(change: BlockChange) -> JsonObject:
    return {
        BINDING: stored_binding(change.binding),
        TITLE: change.title,
        AREA_ID: None if change.area_id is None else stored_id(change.area_id),
        REASON: stored_reason(change.reason),
        BEFORE: None if change.before is None else stored_interval(change.before),
        AFTER: None if change.after is None else stored_interval(change.after),
    }


def _read_change(value: object, iso_week: IsoWeek, *, field: str) -> BlockChange:
    stored = read_mapping(value, field=field)
    return rebuilt(
        lambda: BlockChange(
            iso_week=iso_week,
            binding=read_binding(stored.get(BINDING), field=f"{field}.{BINDING}"),
            title=read_text(stored.get(TITLE), field=f"{field}.{TITLE}"),
            area_id=read_optional_id(stored.get(AREA_ID), field=f"{field}.{AREA_ID}"),
            reason=read_reason(stored.get(REASON), field=f"{field}.{REASON}"),
            before=read_optional_interval(stored.get(BEFORE), field=f"{field}.{BEFORE}"),
            after=read_optional_interval(stored.get(AFTER), field=f"{field}.{AFTER}"),
        ),
        field=field,
    )
