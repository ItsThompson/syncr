"""What the user's choice cost, in objective units, and the breakdown it was measured against.

Pure. Two evaluations of one objective over one week's resolved inputs: the plan as the solver left
it, and the same plan with the one block where the user put it. The difference is the price.

**Both sides are evaluated against ONE assembly, and that is what makes the difference a
comparison.** The objective's terms read facts about the week -- a deadline, an Area's target, a
preferred window, the approved baseline -- so evaluating the two documents against different
assemblies would produce a difference between two different questions. Which assembly it is matters
far less: the pair is what the fitter consumes, and both sides have to be priced in the same frame.

**``PN4`` and ``E2``: the figure is stored, never recomputed.** The weight set that produced it is
versioned and will have moved on, so a later recomputation would answer a different question. That
is why the delta is written onto the pin and onto the edit event rather than derived on read, and
why both rows also carry the weight-set version it was priced under.

**The breakdown is the plan's own, computed here rather than read off the stored revision.** The
revision's column holds the breakdown the solve that produced it computed, under whichever weight
set was active then. Computing it beside the delta means the seven terms and the difference cannot
be priced under different weights, which is exactly what an edit event carrying one weight-set
version claims about both."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from syncr_solver.objective import evaluate

if TYPE_CHECKING:
    from syncr_domain.intervals import Interval
    from syncr_domain.plan import Block, PlanDocument
    from syncr_solver.inputs import SolveInputs
    from syncr_solver.objective import ObjectiveBreakdown
    from syncr_solver.weights import WeightSet


@dataclass(frozen=True, slots=True, kw_only=True)
class PinPrice:
    """What one edit cost, and the reading of the plan it was measured against.

    Two values because two rows read them: the pin and the edit event each carry the delta, and the
    event also carries the breakdown as the plan context a refit needs.
    """

    objective_delta: float
    breakdown: ObjectiveBreakdown


def pin_price(
    document: PlanDocument,
    block: Block,
    accepted: Interval,
    *,
    inputs: SolveInputs,
    weights: WeightSet,
) -> PinPrice:
    """What moving ``block`` to ``accepted`` costs, and what the plan cost before it.

    Positive when the user's placement is worse under the current weights, which is the ordinary
    case and is what "a pin is a visible trade" means. Zero for a pin that keeps a block where it
    already is, which is what the ``p`` toggle and a partial rejection both are: the two documents
    are then equal, so the difference is exactly nothing rather than nearly nothing.
    """
    before = evaluate(document, inputs=inputs, weights=weights)
    if block.interval == accepted:
        return PinPrice(objective_delta=0.0, breakdown=before)
    after = evaluate(_moved(document, block, accepted), inputs=inputs, weights=weights)
    return PinPrice(objective_delta=after.total() - before.total(), breakdown=before)


def _moved(document: PlanDocument, block: Block, accepted: Interval) -> PlanDocument:
    """``document`` with one block where the user put it, and nothing else changed.

    ``pinned`` stays false here, deliberately: the flag names a block the domain can render a pin
    glyph and an ``instead of`` clause for, which needs the very delta this document is being built
    to compute. No objective term reads it, so setting it would change no figure and would make the
    document refuse itself.

    The three stored figures are carried unchanged. A move takes no time out of the week and adds
    none, so the denominator and the two residuals are the same figures they were.
    """
    return replace(
        document,
        blocks=tuple(
            replace(one, interval=accepted) if one.binding == block.binding else one
            for one in document.blocks
        ),
    )
