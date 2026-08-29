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

``elapsed`` when the week had already reached the slot, which is read from the clock before any
content is considered: see below. ``no_eligible_content`` when the Area's backlog is genuinely
empty, and ``no_fitting_content`` when it held content but none of it could take the slot's
duration: the two are distinguished in one pass so a second filter never runs. ``off_plan`` when
every candidate offered was refused by the span the
user declared off, because then it is the span rather than the content that emptied the slot.
``blocked_by_constraint`` otherwise, which is a candidate the rules refused for some other reason.
``not_solved`` is deliberately unreachable here: it means nobody looked at the backlog, and this
phase is the looking.

## A slot the week has already reached is left unbound, and the clock decides that first

The slot's span is not a choice, so a slot whose span has begun can only be filled by placing a
block in a part of the week that has gone. Nothing can be spent there, the packer's own gap set is
clipped to ``inputs.now`` for that reason, and a block the solve chose sitting in a past the plan
of record does not already hold is refused where the document becomes that record. So this phase
reads the same instant and hands out none of it.

The boundary is the slot's START rather than its end, and a slot straddling the instant is left
unbound whole. Shrinking it to the part still ahead is the refusal at the top of this file, so
there is no half of it to fill. It is also strict: a slot beginning exactly at ``inputs.now`` has
spent nothing and still binds, which is the boundary the packer's clip keeps as well. The instant
is read from the assembled inputs rather than from a clock here, so one assembly cannot answer
this two ways.

**The guard sits before the bind, and that is what keeps the week's content for the days it can
still be placed in.** Without it a task's remaining minutes go to a Monday nobody can reach, and a
later slot then reports that its Area had nothing.

**It also sits before the backlog is read, and that decides one thing on its own.** A slot that has
begun in an Area holding nothing eligible states the clock's reason rather than the backlog's:
answering ``no_eligible_content`` would claim the Area was searched and found empty for a span
nobody will search again. Reading the backlog first preserves the content either way, so the
position buys the reason and not the minutes.

## Eligible means "can take this slot's duration", in one expression for all three shapes

A candidate's ``min_minutes`` and ``max_minutes`` bound one placement of it, so the slot's own
duration falling inside that range is the whole test: an atomic task's range is a single length, a
divisible task's runs from its minimum chunk to what is left, and an occurrence's is its declared
elastic range. Content in the Area that cannot take the duration is not eligible FOR THIS SLOT,
which is why a slot it leaves empty says the Area had none that fit when the Area held any, and
says the backlog was empty when it held none at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from syncr_domain.gaps import EmptySlot, EmptySlotReason
from syncr_domain.intervals import has_elapsed
from syncr_domain.templates import TemplateEntryKind
from syncr_solver.candidates import candidates_for
from syncr_solver.constraints import ConstraintRule
from syncr_solver.offering import offer_at, refusal_of

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_domain.identifiers import AreaId, TemplateEntryId
    from syncr_domain.intervals import Instant
    from syncr_solver.attempt import Attempt
    from syncr_solver.candidates import Candidate
    from syncr_solver.constraints import BlockedCandidate
    from syncr_solver.inputs import MaterializedEntry


class Eligibility(NamedTuple):
    """What a slot's Area held, and what could take the slot's duration.

    ``candidates`` are the ones that passed the duration filter, in tie-break order. ``had_content``
    is whether the Area held any candidate at all, before the filter ran. The two together let the
    caller name the reason without a second pass: an empty Area and a full one with nothing that
    fits prompt opposite actions.
    """

    candidates: tuple[Candidate, ...]
    had_content: bool


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
    if has_elapsed(entry.interval, attempt.inputs.now):
        return attempt.with_slot(_slot(entry, EmptySlotReason.ELAPSED))
    eligibility = _eligible_for(entry, attempt)
    if not eligibility.candidates:
        reason = (
            EmptySlotReason.NO_FITTING_CONTENT
            if eligibility.had_content
            else EmptySlotReason.NO_ELIGIBLE_CONTENT
        )
        return attempt.with_slot(_slot(entry, reason))
    refusals: list[BlockedCandidate] = []
    for candidate in eligibility.candidates:
        offer = offer_at(candidate, entry.interval, attempt=attempt)
        refusal = refusal_of(offer, attempt)
        if refusal is None:
            return attempt.adding(offer.placed)
        refusals.append(refusal)
    return attempt.with_blocked(refusals).with_slot(_slot(entry, _reason_of(refusals)))


def _eligible_for(entry: MaterializedEntry, attempt: Attempt) -> Eligibility:
    """What this slot's Area held, and what could take the slot's duration.

    Both are read in one pass over the candidates, so the caller names the reason without a second
    filter: ``had_content`` is whether the Area held any candidate at all, and ``candidates`` is the
    subset that could take the slot's declared duration, in tie-break order.
    """
    minutes = entry.interval.total_minutes()
    area_candidates: list[Candidate] = []
    fitting: list[Candidate] = []
    for candidate in candidates_for(
        attempt.inputs,
        placed_minutes=attempt.placed_minutes(),
        held_demands=attempt.held_demands(),
        floor_shortfalls=attempt.floor_shortfalls(),
    ):
        if candidate.area_id != entry.area_id:
            continue
        area_candidates.append(candidate)
        if candidate.min_minutes <= minutes <= candidate.max_minutes:
            fitting.append(candidate)
    return Eligibility(candidates=tuple(fitting), had_content=bool(area_candidates))


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


def _entry_key(entry: MaterializedEntry) -> tuple[Instant, Instant, AreaId, TemplateEntryId, str]:
    """Span order, then the Area and the entry's own identity so no two slots tie."""
    return (
        entry.interval.start,
        entry.interval.end,
        entry.area_id,
        entry.entry_id,
        entry.occurrence_key,
    )
