"""The placements a solve inherits: what derivation determined, what has begun, and what is pinned.

Step 1 of the algorithm lists the frame, the anchors, the buffers, the concrete entries, the
forbidden windows, **the pins and the past blocks** as the space a solve places into rather than as
candidates inside it. ``materialize`` produces the first four; this produces the last two and
carries all of them into one set.

## Why the past blocks and the pins have to be here, in both directions

They are what the week already holds, so they belong in the document: a task with four hours
remaining and two of them pinned nets to two hours of work still to place, and if the pinned block
were not carried the document would hold two hours of a four-hour task. That is the shrinking a
re-solve must never do, arriving from the other side.

And they belong in the state, because three rules measure over what it holds. H4 reads the spans, so
a solve that seeded nothing would place work over time that has already gone; H8 and H9 read an
Area's minutes, so a day already full of pinned work would read as empty. The first of those is the
unsafe one and it is why this step exists rather than being left to a caller's contract.

## A pin outranks the span derivation chose

The user may pin a prep or transit block somewhere other than where its anchor cast it, which is how
a longer-than-usual commute is expressed. So a derived block whose binding is pinned is carried at
the pin's interval, which is the same precedence the checker's own immovable index takes. Composed
the other way the pin would be refused by H11 for not being where it was derived.

**A block the derivation refused and the user pinned is honored, by lookup.** Derivation refuses a
buffer or a concrete entry whose span was already spent, and such a binding is in none of the three
sources above. The week still holds its content: the frame entry, anchor, buffer or concrete entry
is in the inputs and only its span was refused. So the block is looked up across the four
collections that spell one -- ``frame``, ``anchors``, ``shadow_blocks`` and ``template_entries`` --
built by ``derivation``'s own builders, so its title and its ``bound`` clause are the ones
derivation would have given it, and placed at the pin's interval through the same precedence every
other pinned block takes. This is a lookup and not a second derivation path: nothing here re-checks
spans or decides a placement.

**A pin naming content the week holds nowhere at all is refused rather than dropped.** The
assembler drops a pin whose occurrence a reduced cadence no longer produces, so a pin arriving here
that names neither candidate content nor any of the four collections is a producer that answered
wrongly, and silently ignoring it would leave a stored pin the plan never honors and nothing
reporting why.

## A pinned block renders a pin glyph only when it can say what it replaced

``Block.pinned`` is true only for a block that states the placement it replaced and what replacing
it cost, because the reason panel renders both from the block rather than by walking the edit log. A
pin carrying neither is honored at its interval and carries no glyph: half a pair would render half
a sentence, and the domain refuses it.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from syncr_domain.identity import BindingKind
from syncr_domain.intervals import has_started
from syncr_domain.plan import Block
from syncr_domain.reasons import ReasonRecord
from syncr_solver.attempt import Placed
from syncr_solver.candidates import candidates_for
from syncr_solver.derivation import (
    anchor_blocks,
    entry_blocks,
    frame_blocks,
    shadow_blocks,
    zone_by_occurrence,
)
from syncr_solver.errors import SolveError
from syncr_solver.reading import demand_key
from syncr_solver.state import Sizing

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syncr_domain.identity import BindingRef
    from syncr_domain.intervals import Interval
    from syncr_solver.candidates import Candidate
    from syncr_solver.inputs import Pin, SolveInputs

# What a placement the solve did not choose carries when the rules want a sizing. Its length is a
# fact rather than a choice, so the demand it states is the length it holds: no rule reads it,
# because no rule judges a placement the solve may not move.
_A_FACT_RATHER_THAN_A_CHOICE = Sizing(whole_minutes=1, min_chunk_minutes=1, splittable=False)


def inherited(inputs: SolveInputs, derived: Sequence[Block]) -> tuple[Placed, ...]:
    """Every placement this solve may not move, in one set with one block per binding.

    Three sources in precedence order: what this week's derivation determined, what the live plan
    holds at a span that has begun or that the user pinned, and the pinned content the live plan
    does not hold at all. A binding found earlier is not taken again, so a frame occurrence the
    live plan also holds is carried once, at the span derivation determined for it.
    """
    pins = {pin.binding: pin for pin in inputs.pins}
    held: dict[BindingRef, Placed] = {}
    for block in derived:
        held[block.binding] = _placed(block, pins.get(block.binding))
    for block in _live(inputs):
        if block.binding in held or not _is_immovable(block, inputs, pins):
            continue
        held[block.binding] = _placed(block, pins.get(block.binding))
    for pin in inputs.pins:
        if pin.binding in held:
            continue
        held[pin.binding] = _from_content(pin, inputs)
    return tuple(held[binding] for binding in sorted(held, key=_binding_order))


def _placed(block: Block, pin: Pin | None) -> Placed:
    """This block where the week holds it, which is the pin's interval when one names it."""
    if pin is None:
        return Placed.of(block, sizing=_sizing_of(block), chosen=False)
    return Placed.of(_moved_to(block, pin), sizing=_sizing_of(block), chosen=False)


def _moved_to(block: Block, pin: Pin) -> Block:
    """The block at the interval the user put it at, stating what it replaced where it can.

    The interval is set whether or not it already matches, because a pin on a block that is already
    where the user wants it is still the user's own placement: it renders a pin glyph, it is a
    training label, and H4 excepts it. Read only as a move, a pin on content the solve had nothing
    to move would silently lose all three.
    """
    if pin.superseded_placement is None or pin.objective_delta is None:
        return replace(block, interval=pin.interval)
    return replace(
        block,
        interval=pin.interval,
        pinned=True,
        superseded_placement=pin.superseded_placement,
        objective_delta=pin.objective_delta,
    )


def _sizing_of(block: Block) -> Sizing | None:
    """The sizing a placement of this block carries, for exactly the two kinds that need one."""
    if block.binding.kind not in {BindingKind.TASK, BindingKind.HABIT}:
        return None
    return replace(
        _A_FACT_RATHER_THAN_A_CHOICE,
        whole_minutes=block.interval.total_minutes(),
        min_chunk_minutes=block.interval.total_minutes(),
    )


def _is_immovable(block: Block, inputs: SolveInputs, pins: Mapping[BindingRef, Pin]) -> bool:
    """Whether the solve may not move this live-plan block: it has begun, or the user placed it.

    Decided against the instant the assembly was stamped with rather than against a clock, which is
    the same reading H10 takes: without that instant "has started or is in the past" is not
    decidable at all.
    """
    return has_started(block.interval, inputs.now) or block.binding in pins


def _from_content(pin: Pin, inputs: SolveInputs) -> Placed:
    """A block for content the user pinned that no earlier source seeded.

    Reachable two ways: a first-ever pin on a task or an occurrence, where no revision holds a
    block for it and the block is built from the same candidate the construction would have built;
    and a pin on content derivation REFUSED, where the block is looked up across the four
    collections that spell one. Both carry the title and the ``bound`` clause the construction or
    derivation would have given them, and both land at the pin's interval.

    A pin naming content this week holds nowhere at all is refused rather than dropped. The
    assembler drops a pin whose occurrence a reduced cadence no longer produces, so a pin arriving
    here that names nothing is a producer that answered wrongly, and silently ignoring it would
    leave a stored pin the plan never honors and nothing reporting why.
    """
    candidate = _content_named_by(pin.binding, inputs)
    if candidate is not None:
        return _placed(_block_for(candidate, pin.interval, inputs), pin)
    block = _derived_block_named_by(pin.binding, inputs)
    if block is not None:
        return _placed(block, pin)
    raise SolveError(
        f"the pin on {pin.binding.kind.value!r} {pin.binding.entity_id} occurrence "
        f"{pin.binding.occurrence_key!r} names content this week does not hold: the live plan "
        "has no block for it, it is neither an eligible task nor a due occurrence, and no routine "
        "occurrence, anchor, buffer or concrete template entry names it, so there is nothing to "
        "place at the interval the user chose"
    )


def _derived_block_named_by(binding: BindingRef, inputs: SolveInputs) -> Block | None:
    """The block derivation spells for this binding, or nothing because none of them names it.

    The four collections that spell a derived block -- the frame, the anchors, the buffers and the
    concrete entries -- are rebuilt through ``derivation``'s own builders, so the block a pin here
    resolves to carries the one ``bound`` clause derivation would have given it rather than a
    second spelling of it. A slot is deliberately absent: it binds late and names no content, so a
    pin on one falls through to the refusal in ``_from_content``. Nothing here checks spans either:
    whether the refused span may now be occupied is the pin's own answer, which H4 already exempts.
    """
    zones = zone_by_occurrence(inputs.iso_week, inputs.zone_by_date)
    spelled = (
        *frame_blocks(inputs.frame, iso_week=inputs.iso_week, zones=zones),
        *anchor_blocks(inputs.anchors, iso_week=inputs.iso_week),
        *shadow_blocks(inputs.shadow_blocks, iso_week=inputs.iso_week),
        *entry_blocks(inputs.template_entries, iso_week=inputs.iso_week, zones=zones),
    )
    wanted = demand_key(binding)
    return next((block for block in spelled if demand_key(block.binding) == wanted), None)


def _content_named_by(binding: BindingRef, inputs: SolveInputs) -> Candidate | None:
    """The candidate this binding names, or nothing because the week holds no such content.

    Every candidate is built rather than the collections searched by hand, so the title and the
    clause a pinned block carries are the construction's own and not a second spelling of them. The
    shortfalls are empty because nothing here is ordered: this is a lookup by identity.
    """
    wanted = demand_key(binding)
    return next(
        (
            candidate
            for candidate in candidates_for(inputs, placed_minutes={}, floor_shortfalls={})
            if demand_key(candidate.binding) == wanted
        ),
        None,
    )


def _block_for(candidate: Candidate, interval: Interval, inputs: SolveInputs) -> Block:
    return Block(
        iso_week=inputs.iso_week,
        interval=interval,
        binding=candidate.binding,
        title=candidate.title,
        reason=ReasonRecord((candidate.bound,)),
        area_id=candidate.area_id,
        make_up=candidate.make_up,
    )


def _live(inputs: SolveInputs) -> tuple[Block, ...]:
    return () if inputs.live_plan is None else inputs.live_plan.blocks


def _binding_order(binding: BindingRef) -> tuple[str, str, str, int]:
    """A total order over bindings, so the inherited set is held in one order on every run."""
    return (
        binding.kind.value,
        str(binding.entity_id),
        binding.occurrence_key,
        -1 if binding.split_index is None else binding.split_index,
    )
