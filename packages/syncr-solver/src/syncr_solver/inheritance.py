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

**A block the derivation refused and the user pinned is not resurrected.** Derivation refuses a
buffer whose span was already spent, and nothing here has the buffer's Area to rebuild it from
without a second derivation path. The pin is then not honored, which is exactly what
``materialize`` already does with it, so this is a disclosed limit rather than a regression.

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
    """A block for content the user pinned that the live plan does not hold.

    Reachable from a first-ever pin on a task or an occurrence: the pin exists, no revision holds a
    block for it, and the property that every pin appears at exactly its interval still has to hold.
    The block is built from the same candidate the construction would have built, so its title and
    its ``bound`` clause are the ones the solve would have given it.

    A pin naming content this week holds nowhere is refused rather than dropped. The assembler drops
    a pin whose occurrence a reduced cadence no longer produces, so a pin arriving here that names
    nothing is a producer that answered wrongly, and silently ignoring it would leave a stored pin
    the plan never honors and nothing reporting why.
    """
    candidate = _content_named_by(pin.binding, inputs)
    if candidate is None:
        raise SolveError(
            f"the pin on {pin.binding.kind.value!r} {pin.binding.entity_id} occurrence "
            f"{pin.binding.occurrence_key!r} names content this week does not hold: the live plan "
            "has no block for it and it is neither an eligible task nor a due occurrence, so there "
            "is nothing to place at the interval the user chose"
        )
    return _placed(_block_for(candidate, pin.interval, inputs), pin)


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
