"""The reason record every block carries, assembled from what the solve already decided.

``assemble`` is a projection. Every clause it emits is a value some other part of the solve
computed and kept: the refusals the checker recorded, the breakdown the objective returned, the
figures the assembler resolved for each Area, the pin rows, and the ``bound`` clause the block
has carried since the moment it was built. Nothing here re-runs a check, re-derives a figure or
looks anything up, so explainability costs no subsystem of its own.

## What each clause is drawn from, and there is nothing else

```
bound        ◀── the block's own record, built by derivation or by the candidate
pinned       ◀── the pin row
instead of   ◀── the superseded placement and delta stored with the same pin row
blocked      ◀── the bounded log of what the thirteen rules refused
dominant     ◀── the objective breakdown's largest term and its share
floor        ◀── the Area figures the assembler resolved
```

The parameter list IS the traceability boundary: a clause naming something outside it could not
be built, because nothing here can reach anything else.

## A derived block reports its determinant and stops

A placement derivation fixed was not chosen, so nothing was weighed and nothing was refused for
it: the frame, an imported commitment, a buffer an anchor's type cast and a concrete template
entry each carry the one ``bound`` clause that names their determinant. The user's own edit is
the exception the design states, so a derived block the user pinned elsewhere also carries
``pinned`` and ``instead of``.

Content the solver binds late -- a habit occurrence and a task -- is what the other three
clauses describe, because a choice was made about it.

## The share a ``dominant`` clause renders is the PLAN's

Three of the seven objective terms have no per-block reading: an Area's budget deviation is a
week's gap, churn counts moves across the whole document, and staleness is measured over
occurrences the plan does not hold at all. A per-block share would need an attribution rule for
each, invented to satisfy a sentence rather than to answer a question the objective asks. The
breakdown already answers "which term carried this week, and by how much", so that is what the
clause names, and every block of one plan carries the same one.

## The two floor figures a clause renders are over two different sets, deliberately

``AreaBudget`` holds the floor twice, and the pair is not redundant. ``floor_minutes`` nets the
immovable placements only, which is the number H9 read when it forced or forbade a placement.
``floor_reservation_minutes`` nets EVERY placement, which is the number the probe compares
against free capacity. A clause rendering one figure from each set would let a reader compute a
third quantity that is neither.

So the clause states the rule's own figure as ``floor_minutes``, and states ``placed`` and ``of``
over one set, the reservation's:

```
placed = AreaBudget.placed_minutes                 every placement, pinned or not
of     = placed_minutes + floor_reservation_minutes the floor that reservation is against
```

``of - placed`` is then the probe's reservation exactly, for every Area and every week, so the
clause cannot disagree with the figure a reader compares it against. The Area's DECLARED floor is
not on ``AreaBudget`` at all, and an Area with more placed than its floor asks therefore reads
``of == placed`` with a reservation of zero, which is what the probe reports for it: see ticket
1380, which carries the producer field that would let the clause name the declared figure too.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Final

from syncr_domain.reasons import (
    CLAUSE_BUDGET,
    Blocked,
    Bound,
    ChurnBaseline,
    DerivationSource,
    Dominant,
    Floor,
    InsteadOf,
    Pinned,
    ReasonRecord,
)
from syncr_solver.reading import demand_key

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syncr_domain.identifiers import AreaId
    from syncr_domain.identity import BindingRef
    from syncr_domain.plan import Block, PlanDocument
    from syncr_domain.reasons import Clause
    from syncr_solver.constraints import BlockedCandidate
    from syncr_solver.inputs import AreaBudget, Pin
    from syncr_solver.objective import ObjectiveBreakdown
    from syncr_solver.reading import DemandKey

# The objective term whose clause names the plan it was measured against. The only term of the
# seven that is a difference from another document rather than a fact about this one.
CHURN: Final = "churn"

# How many refused windows one block reports, read from the budget rather than restated: the log
# is bounded per binding by the same figure, and a third row could never be rendered.
BLOCKED_PER_BLOCK: Final = CLAUSE_BUDGET[Blocked]


def assemble(
    plan: PlanDocument,
    *,
    blocked_log: Sequence[BlockedCandidate],
    breakdown: ObjectiveBreakdown | None,
    pins: Sequence[Pin],
    areas: Sequence[AreaBudget],
) -> tuple[ReasonRecord, ...]:
    """One record per block of ``plan``, in the plan's own block order.

    ``breakdown`` is ``None`` for a plan nothing weighed, which is a materialized week: it runs
    no search and evaluates no objective, so there is no dominant term to name. That is the same
    absence a plan costing nothing has, and both report no ``dominant`` clause rather than one at
    a share of zero.

    Pure, and it performs no lookup. The refusals are indexed by demand once for the whole plan
    rather than scanned per block, so the cost is the assembly itself.
    """
    refusals = _by_demand(blocked_log)
    pinned = {pin.binding: pin for pin in pins}
    floors = {area.area_id: area for area in areas}
    return tuple(
        ReasonRecord(_clauses_for(block, refusals, pinned, floors, breakdown))
        for block in plan.blocks
    )


def explained(
    plan: PlanDocument,
    *,
    blocked_log: Sequence[BlockedCandidate],
    breakdown: ObjectiveBreakdown | None,
    pins: Sequence[Pin],
    areas: Sequence[AreaBudget],
) -> PlanDocument:
    """``plan`` with every block carrying its assembled record. What a caller stores.

    The records are paired with the blocks by position rather than by id, because they were built
    from that same sequence one call earlier: an id lookup here would be a second pairing rule for
    something that cannot be out of step.
    """
    records = assemble(plan, blocked_log=blocked_log, breakdown=breakdown, pins=pins, areas=areas)
    return replace(
        plan,
        blocks=tuple(
            replace(block, reason=record)
            for block, record in zip(plan.blocks, records, strict=True)
        ),
    )


def _clauses_for(
    block: Block,
    refusals: Mapping[DemandKey, tuple[BlockedCandidate, ...]],
    pinned: Mapping[BindingRef, Pin],
    floors: Mapping[AreaId, AreaBudget],
    breakdown: ObjectiveBreakdown | None,
) -> tuple[Clause, ...]:
    """Every clause this block's record holds: its own determinant, the user's, and the solve's.

    The block's own ``bound`` clause is carried forward, because a block has held the clause naming
    its determinant since it was built and rebuilding it here would be a second spelling of what
    the candidate or the derivation resolved.

    **The other five kinds are this function's, not the block's**, and any it already carried are
    replaced rather than added to. So assembling a record twice produces the record once: a caller
    that re-explains a plan after a pin gets one ``pinned`` clause rather than a refusal for
    exceeding the budget.
    """
    pin = pinned.get(block.binding)
    return (
        *_bound_clauses(block),
        *_pin_clauses(pin),
        *(() if _was_determined(block) else _weighed_clauses(block, refusals, floors, breakdown)),
    )


def _bound_clauses(block: Block) -> tuple[Clause, ...]:
    """The clauses naming what determined this block, which are the ones it brought with it."""
    return tuple(clause for clause in block.reason.clauses if isinstance(clause, Bound))


def _pin_clauses(pin: Pin | None) -> tuple[Clause, ...]:
    """What the user's own edit says: where they put it, and what it replaced where it can.

    Both halves of ``instead of`` or neither, which is the same pairing ``Block.pinned`` is set
    from: a pin on content the solve had nothing to move states no superseded placement, so the
    record says the user placed it and claims no trade.
    """
    if pin is None:
        return ()
    at = Pinned(pin.interval, pin.pinned_on)
    if pin.superseded_placement is None or pin.objective_delta is None:
        return (at,)
    return (at, InsteadOf(pin.superseded_placement, pin.objective_delta))


def _weighed_clauses(
    block: Block,
    refusals: Mapping[DemandKey, tuple[BlockedCandidate, ...]],
    floors: Mapping[AreaId, AreaBudget],
    breakdown: ObjectiveBreakdown | None,
) -> tuple[Clause, ...]:
    """The three clauses that describe a choice, for the content the solver chose to place."""
    return (
        *_blocked_clauses(block, refusals),
        *_dominant_clause(breakdown),
        *_floor_clause(block, floors),
    )


def _blocked_clauses(
    block: Block, refusals: Mapping[DemandKey, tuple[BlockedCandidate, ...]]
) -> tuple[Clause, ...]:
    """The windows the rules refused for this block's demand, in the order they were refused.

    Keyed by DEMAND rather than by binding, so every chunk of a divided task reports the rejected
    windows recorded while that task was being packed. The refusals were recorded against the
    demand's own binding, so paired by binding they would reach the first chunk and no other.
    """
    return tuple(
        Blocked(row.window, row.rule, row.detail)
        for row in refusals.get(demand_key(block.binding), ())
    )


def _dominant_clause(breakdown: ObjectiveBreakdown | None) -> tuple[Clause, ...]:
    """Which objective term carried the plan's cost, and what share of it that was.

    Nothing for a plan nothing weighed and nothing for a plan that costs nothing, because a term
    named at a share of zero would state a dominant cost no arithmetic found.
    """
    if breakdown is None:
        return ()
    term = breakdown.dominant_term()
    if term is None:
        return ()
    return (Dominant(term, breakdown.share_of(term), _baseline_of(term, breakdown)),)


def _baseline_of(term: str, breakdown: ObjectiveBreakdown) -> ChurnBaseline | None:
    """The plan churn was measured against, for the one term that is measured against a plan.

    Named for churn and for nothing else. A charged churn always names an approved revision and
    the instant of assent -- the breakdown refuses one that does not -- so the clause cannot claim
    a comparison that never happened, and a week nobody approved has zero churn and no clause.
    """
    if term != CHURN:
        return None
    baseline = breakdown.churn_baseline
    return ChurnBaseline(revision_id=baseline.revision_id, approved_at=baseline.approved_at)


def _floor_clause(block: Block, floors: Mapping[AreaId, AreaBudget]) -> tuple[Clause, ...]:
    """The Area floor that forced or forbade this placement, or nothing because none did.

    A floor of no minutes reserves nothing: it neither promoted this Area's content in the
    ordering nor gave H9 anything to refuse a candidate with, so there is no floor to report.
    """
    area = None if block.area_id is None else floors.get(block.area_id)
    if area is None or area.floor_minutes <= 0:
        return ()
    return (
        Floor(
            area.area_id,
            area.floor_minutes,
            area.placed_minutes,
            area.placed_minutes + area.floor_reservation_minutes,
        ),
    )


def _was_determined(block: Block) -> bool:
    """Whether derivation fixed this block rather than the solver choosing to place it.

    Read from the ``bound`` clause the block already carries, which names one of two vocabularies:
    a derivation source for a placement nobody chose, and a habit binding source for content the
    solver bound into a window. So the partition is the block's own statement about itself rather
    than a second list of the kinds that are derived.
    """
    return any(
        isinstance(clause.source, DerivationSource)
        for clause in _bound_clauses(block)
        if isinstance(clause, Bound)
    )


def _by_demand(
    blocked_log: Sequence[BlockedCandidate],
) -> Mapping[DemandKey, tuple[BlockedCandidate, ...]]:
    """The log's rows by the demand they were refused for, bounded at what a block may report.

    The log is already bounded at two rows per binding, and this bounds what one block renders
    over the demand those bindings share, so a demand spelled by two bindings cannot put a third
    row in front of a reader.
    """
    found: dict[DemandKey, tuple[BlockedCandidate, ...]] = {}
    for row in blocked_log:
        key = demand_key(row.binding)
        kept = found.get(key, ())
        if len(kept) < BLOCKED_PER_BLOCK:
            found[key] = (*kept, row)
    return found
