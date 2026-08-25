"""``materialize``: the plan derivation alone determines, with every Area slot left unfilled.

It places only what nothing had to choose. The frame at its effective duration, the imported
commitments, the buffers their types cast, the concrete entries of each day's shape, and the
windows that forbid work. Every Area slot becomes an empty slot stating that its content has not
been chosen, because nobody looked at the backlog.

**It takes no weight set**, and that is the whole reason it is usable before a solver exists:
there is nothing to weigh when nothing is being chosen. It reads no clock, performs no I/O and
draws on no randomness, so two materializations of one input are the same document.

## Two permanent jobs

Phase 1 of every solve, forever, and the plan of last resort when a solve fails terminally on a
week that has no plan at all. The second is why this is not scaffolding a later slice deletes: a
first-ever solve that failed would otherwise leave the week with nothing for the grid or the
projector to show, and a degraded plan that explains itself beats an absent one.

## What is placed unchecked, and what has to earn its span

The frame and the anchors are the space rather than candidates inside it. Both are immovable
facts, so two of them overlapping is a state of the week rather than a choice: a routine of more
than a local day overlaps its own next occurrence, and a double-booked calendar keeps both
commitments. They are placed as they arrive.

Everything else derivation determines is CHECKED, against that space and against what is already
placed. A buffer or a concrete entry that would overlap an anchor, an absolute forbidden window,
the frame, a span the week has already begun, or an earlier placement is refused, and the refusal
names the rule and the window. So materialization never creates an overlap of its own, which is
what H4 binds.

Buffers are checked before entries, because a buffer's geometry is cast by an immovable
commitment while an entry is the shape the user declared for the day, and an anchor colliding
with a materialized entry is a conflict the user resolves rather than one this function decides.

## What it deliberately does not do

No content is bound, so no habit occurrence and no task appears. No pin is honoured and no past
block is carried: a pin is the user's own choice about a placement, and reporting one needs the
two clauses a chosen placement carries. A span that has already begun is still refused to a
candidate, because carrying no block for it is not the same as placing an entry over time that has
gone. For the fallback job the omission costs nothing, because a week with no plan has no pins to
honour. Every block here carries exactly one clause, the ``bound`` clause naming its determinant,
so a derived plan satisfies the reason-record minimum with no exception carved out for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_domain.plan import PlanDocument
from syncr_solver.constraints import BlockedCandidate, ConstraintCheck
from syncr_solver.derivation import (
    anchor_blocks,
    empty_slots,
    entry_blocks,
    frame_blocks,
    shadow_blocks,
    zone_by_occurrence,
)
from syncr_solver.figures import week_figures
from syncr_solver.metrics import MATERIALIZE_TOTAL, MaterializeCause
from syncr_solver.occupancy import OCCUPANCY_RULES
from syncr_solver.ordering import block_key, slot_key
from syncr_solver.state import PartialPlan, Placement

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syncr_domain.gaps import EmptySlot
    from syncr_domain.plan import Block
    from syncr_domain.zones import Date, ZoneId
    from syncr_solver.inputs import MaterializedEntry, SolveInputs


@dataclass(frozen=True, slots=True)
class Materialization:
    """The derived plan, and the candidates the occupancy rules refused.

    A document has nowhere to record a refusal: it describes what the week holds, and a buffer
    that could not be placed holds nothing. The refusals are returned beside it, so a solve, whose
    first phase this is, carries them into the log its own rejections go to rather than re-running
    the checks that already knew.
    """

    document: PlanDocument
    blocked: tuple[BlockedCandidate, ...] = ()


def materialize(inputs: SolveInputs, *, cause: MaterializeCause) -> PlanDocument:
    """The plan derivation determines for ``inputs``. No content, no objective, no search.

    ``cause`` says which of the three callers asked, and it is the counter's only label. It is
    required rather than defaulted because no caller is inferable from the inputs: one week
    assembles the same way for phase 1 of a solve, for the horizon maintainer, and for the
    fallback after a terminal failure.
    """
    return derive(inputs, cause=cause).document


def derive(inputs: SolveInputs, *, cause: MaterializeCause) -> Materialization:
    """``materialize``, plus what the occupancy rules refused along the way.

    The counter is incremented once the document exists rather than on the way in, so a refusal is
    not counted as a materialization: a fallback that produced nothing is the outage the
    ``solve_failed`` count exists to distinguish a degraded plan from. It is incremented here rather
    than in ``materialize``, because both entry points materialize a week and a count only one of
    them reached would report a fraction of the weeks derived.
    """
    zones = zone_by_occurrence(inputs.iso_week, inputs.zone_by_date)
    space = PartialPlan.of(inputs)
    fixed = (
        *frame_blocks(inputs.frame, iso_week=inputs.iso_week, zones=zones),
        *anchor_blocks(inputs.anchors, iso_week=inputs.iso_week),
    )
    placed, blocked = _place(_candidates(inputs, zones), space)
    blocks = tuple(sorted((*fixed, *placed), key=block_key))
    figures = week_figures(inputs, blocks)
    document = PlanDocument(
        iso_week=inputs.iso_week,
        zone_by_date=_zones_of_this_week(inputs),
        discretionary_minutes=figures.discretionary_minutes,
        unallocated_minutes=figures.unallocated_minutes,
        oversubscription_minutes=figures.oversubscription_minutes,
        blocks=blocks,
        forbidden_windows=space.forbidden_windows,
        empty_slots=(*_slots(inputs.template_entries), *inputs.dropped_legs),
        adjustments=tuple(adjustment.adjustment_id for adjustment in inputs.adjustments),
    )
    MATERIALIZE_TOTAL.labels(cause=cause.value).inc()
    return Materialization(document=document, blocked=blocked)


def _candidates(inputs: SolveInputs, zones: Mapping[str, ZoneId]) -> tuple[Block, ...]:
    """Everything derivation determined that has to earn its span, in the order it is offered.

    Buffers first, then concrete entries, each kind in span order. The order is what makes a
    refusal reproducible: whether a candidate fits depends on what is already placed, so two
    permutations of one input list would otherwise refuse different members of an overlapping
    pair.
    """
    return (
        *sorted(shadow_blocks(inputs.shadow_blocks, iso_week=inputs.iso_week), key=block_key),
        *sorted(
            entry_blocks(inputs.template_entries, iso_week=inputs.iso_week, zones=zones),
            key=block_key,
        ),
    )


def _place(
    candidates: Sequence[Block], space: PartialPlan
) -> tuple[tuple[Block, ...], tuple[BlockedCandidate, ...]]:
    """Each candidate against the space and against what earlier candidates took.

    A refused candidate is not emitted at all. Shrinking it, moving it, or emitting it anyway
    would each be a placement decision, and derivation decides nothing: what it can say is that
    the span its determinant named was already spent, and by what.
    """
    check = ConstraintCheck(OCCUPANCY_RULES)
    state = space
    placed: list[Block] = []
    blocked: list[BlockedCandidate] = []
    for block in candidates:
        candidate = Placement.of(block)
        rejection = check.check(candidate, state)
        if rejection is not None:
            blocked.append(BlockedCandidate.of(block.binding, rejection))
            continue
        state = state.with_placed(candidate)
        placed.append(block)
    return tuple(placed), tuple(blocked)


def _slots(entries: Sequence[MaterializedEntry]) -> tuple[EmptySlot, ...]:
    """The week's unfilled Area slots, in span order."""
    return tuple(sorted(empty_slots(entries), key=slot_key))


def _zones_of_this_week(inputs: SolveInputs) -> Mapping[Date, ZoneId]:
    """The active zone per day, captured at materialize time, in the week's own date order.

    Rebuilt in date order rather than copied in the order it arrived, so a document is identical
    whichever order its inputs were assembled in, down to the order its keys are stored in. A
    travel override declared later cannot re-read a stored week either way: the mapping is a fact
    the document carries.
    """
    return {day: inputs.zone_by_date[day] for day in inputs.iso_week.dates()}
