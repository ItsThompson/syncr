"""Builders for the weeks ``solve`` is driven against, on top of the two fixture modules.

``solve`` takes a whole week and a whole weight set, so a test asserting one behaviour would
otherwise spell a week's worth of values it does not care about. These produce a week whose span is
entirely ahead of ``now`` -- so nothing is clipped to the past unless a test asks for it -- and take
overrides for the members under test.

Every value is real: the interval algebra, the identity derivation, the domain value types, and the
shipped hand-tuned weights. Nothing here builds a block or a binding by hand; the blocks a test
compares against come out of the solver, and the ones a live plan holds come out of the domain
constructors.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from syncr_domain.templates import TemplateEntryKind
from syncr_solver.budget import SolveBudget
from syncr_solver.solve import solve
from tests.materialized_weeks import MONDAY_MIDNIGHT, inputs
from tests.objective_weeks import hand_tuned_weights

if TYPE_CHECKING:
    from syncr_domain.identifiers import AreaId
    from syncr_domain.intervals import Interval
    from syncr_domain.plan import Block, PlanDocument
    from syncr_solver.inputs import SolveInputs
    from syncr_solver.solve import SolveResult
    from syncr_solver.weights import WeightSet

# A budget small enough to keep a suite fast and large enough for the search to reach a plan a
# handful of moves away. A test about the bound itself states its own.
QUICK = SolveBudget(scored_windows=2, move_evaluations=40, checkpoint_every=10)


def a_week(**overrides: Any) -> SolveInputs:
    """One week whose whole span is still to come, so every gap is placeable.

    ``now`` is the week's own first instant rather than the mid-week stamp the materialization
    fixture uses: a solve places nothing before ``now``, so a test about placement would otherwise
    be a test about the clip.
    """
    stated: dict[str, Any] = {"now": MONDAY_MIDNIGHT}
    stated.update(overrides)
    return inputs(**stated)


def solved(week: SolveInputs, *, weights: WeightSet | None = None, **kwargs: Any) -> SolveResult:
    """This week solved against the shipped hand-tuned weights and the quick budget."""
    stated: dict[str, Any] = {"budget": QUICK}
    stated.update(kwargs)
    return solve(week, weights or hand_tuned_weights(), **stated)


def titles_of(document: PlanDocument) -> tuple[str, ...]:
    """Every block's title, in the order the document holds them."""
    return tuple(block.title for block in document.blocks)


def blocks_titled(document: PlanDocument, title: str) -> tuple[Block, ...]:
    """The blocks whose title starts with this one, which is how a bound occurrence reads."""
    return tuple(block for block in document.blocks if block.title.startswith(title))


def minutes_in(document: PlanDocument, area_id: AreaId) -> int:
    """Minutes this document places in one Area, summed over its blocks."""
    return sum(
        block.interval.total_minutes() for block in document.blocks if block.area_id == area_id
    )


def minutes_toward(document: PlanDocument, entity_id: Any) -> int:
    """Minutes this document places toward one entity, however many pieces it holds."""
    return sum(
        block.interval.total_minutes()
        for block in document.blocks
        if block.binding.entity_id == entity_id
    )


def slot_reasons(document: PlanDocument) -> tuple[str, ...]:
    """The reason each unfilled slot states, in the order the document holds them."""
    return tuple(slot.reason.value for slot in document.empty_slots)


def slot_spans(week: SolveInputs) -> tuple[Interval, ...]:
    """The declared spans of this week's template slots, for a test comparing against them."""
    return tuple(
        entry.interval for entry in week.template_entries if entry.kind is TemplateEntryKind.SLOT
    )
