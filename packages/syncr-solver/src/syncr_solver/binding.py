"""Phase 2: binding content into the slots whose time the template already fixed.

A slot says "one hour of Learning" and carries no content, so at solve time it resolves to a
specific task or habit occurrence in its Area. Its span is not a choice, which is what makes this
phase a choice of CONTENT and nothing else: the candidates are ordered by
:func:`~syncr_solver.tiebreak.compare`, constraint-checked in that order, and the first one the
rules accept is placed.

## A slot nothing fills stays exactly where it is

Three refusals, and each is a decision the design settled rather than an omission:

| Refused | Why |
|---|---|
| shrink the slot | it needs a minimum-slot rule, and it reads as the solver editing the template |
| fill it from another Area | it needs an Area adjacency graph, a concept nobody asked for |
| leave it empty silently | a forbidden gap and an ordinary one would be pixel-identical |

So the slot is emitted at its declared time and duration with a stated reason, its span counts as
unallocated rather than as scheduled, and the label the gutter renders comes from the one place that
owns a reason's wording.

## Which reason a slot states, and how it is decided rather than chosen

``no_eligible_content`` when the Area had nothing that could take the slot's duration.
``off_plan`` when every candidate offered was refused by the span the user declared off, because
then it is the span rather than the content that emptied the slot. ``blocked_by_constraint``
otherwise, which is a candidate the rules refused for some other reason. ``not_solved`` is
deliberately unreachable here: it means nobody looked at the backlog, and this phase is the looking.

## Eligible means "can take this slot's duration", in one expression for all three shapes

A candidate's ``min_minutes`` and ``max_minutes`` bound one placement of it, so the slot's own
duration falling inside that range is the whole test: an atomic task's range is a single length, a
divisible task's runs from its minimum chunk to what is left, and an occurrence's is its declared
elastic range. Content in the Area that cannot take the duration is not eligible FOR THIS SLOT,
which is why a slot it leaves empty says the Area had none.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_domain.gaps import EmptySlot, EmptySlotReason
from syncr_domain.templates import TemplateEntryKind
from syncr_solver.candidates import candidates_for
from syncr_solver.constraints import ConstraintRule
from syncr_solver.offering import offer_at, refusal_of

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_solver.attempt import Attempt
    from syncr_solver.candidates import Candidate
    from syncr_solver.constraints import BlockedCandidate
    from syncr_solver.inputs import MaterializedEntry


def bind_slots(attempt: Attempt) -> Attempt:
    """Every slot of the week, in span order, with content bound into it or a reason stated.

    Span order, so a slot's candidates are the ones still unplaced when the day reaches it: two
    slots of one Area on one day are filled by two different things, and which of them gets the
    higher-ordered content is decided by the clock rather than by an input's arrival.
    """
    for entry in sorted(_slots(attempt.inputs.template_entries), key=_entry_key):
        attempt = _bind_one(entry, attempt)
    return attempt


def _bind_one(entry: MaterializedEntry, attempt: Attempt) -> Attempt:
    """One slot: the first eligible candidate the rules accept, or the slot with its reason."""
    eligible = _eligible_for(entry, attempt)
    if not eligible:
        return attempt.with_slot(_slot(entry, EmptySlotReason.NO_ELIGIBLE_CONTENT))
    refusals: list[BlockedCandidate] = []
    for candidate in eligible:
        offer = offer_at(candidate, entry.interval, attempt=attempt)
        refusal = refusal_of(offer, attempt)
        if refusal is None:
            return attempt.adding(offer.placed)
        refusals.append(refusal)
    return attempt.with_blocked(refusals).with_slot(_slot(entry, _reason_of(refusals)))


def _eligible_for(entry: MaterializedEntry, attempt: Attempt) -> tuple[Candidate, ...]:
    """The content of this slot's Area that could take its duration, in tie-break order."""
    minutes = entry.interval.total_minutes()
    return tuple(
        candidate
        for candidate in candidates_for(
            attempt.inputs,
            placed_minutes=attempt.placed_minutes(),
            held_demands=attempt.held_demands(),
            floor_shortfalls=attempt.floor_shortfalls(),
        )
        if candidate.area_id == entry.area_id
        and candidate.min_minutes <= minutes <= candidate.max_minutes
    )


def _reason_of(refusals: Sequence[BlockedCandidate]) -> EmptySlotReason:
    """Which reason the refusals name: the declared-off span, or a constraint.

    ``off_plan`` only when it refused EVERY candidate. A span the user declared off empties a slot
    whatever was offered into it, and one candidate refused by it while another was refused by a
    daily cap is a slot the rules emptied rather than the span.
    """
    if all(refusal.rule is ConstraintRule.OFF_PLAN for refusal in refusals):
        return EmptySlotReason.OFF_PLAN
    return EmptySlotReason.BLOCKED_BY_CONSTRAINT


def _slot(entry: MaterializedEntry, reason: EmptySlotReason) -> EmptySlot:
    """The slot as the document holds it: its declared time and duration, and why it is empty."""
    return EmptySlot(interval=entry.interval, area_id=entry.area_id, reason=reason)


def _slots(entries: Sequence[MaterializedEntry]) -> tuple[MaterializedEntry, ...]:
    return tuple(entry for entry in entries if entry.kind is TemplateEntryKind.SLOT)


def _entry_key(entry: MaterializedEntry) -> tuple[object, ...]:
    """Span order, then the Area and the entry's own identity so no two slots tie."""
    return (
        entry.interval.start,
        entry.interval.end,
        entry.area_id,
        entry.entry_id,
        entry.occurrence_key,
    )
