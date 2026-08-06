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
version claims about both.

## Why the per-term difference is measured a second time, at unit weights

A breakdown's seven costs are each a WEIGHTED measurement, so a difference of two of them already
contains the weights. Learning to rank fits the weights, so what it needs is the difference in the
objective's RAW measurements: seven numbers whose weighted sum, under the version the delta was
priced at, is the delta.

So both plans are evaluated a second time under a weight set whose seven term weights are one and
whose two shaping PARAMETERS are untouched. A weight scales a measurement and a parameter shapes
one, so unit weights leave every raw measurement as it was and make each cost equal to it. The
alternative, dividing each weighted difference by its own weight, has a hole at a weight of zero,
where the cost is zero whatever the measurement and the information is gone. Two more evaluations of
a pure function is the cheaper price: the pin path's cost is its two assemblies.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final

from syncr_solver.objective import evaluate
from syncr_solver.weights import OBJECTIVE_TERMS

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syncr_domain.intervals import Interval
    from syncr_domain.plan import Block, PlanDocument
    from syncr_solver.inputs import SolveInputs
    from syncr_solver.objective import ObjectiveBreakdown
    from syncr_solver.weights import WeightSet

# What a pin that moves nothing measured. Stated rather than left absent, so the corpus holds one
# shape and the fitter's rule about a pair comparing two identical plans is a rule about a value.
UNCHANGED: Final[Mapping[str, float]] = dict.fromkeys(OBJECTIVE_TERMS, 0.0)


@dataclass(frozen=True, slots=True, kw_only=True)
class PinPrice:
    """What one edit cost, and the reading of the plan it was measured against.

    Three values because two rows read them: the pin carries the delta, and the edit event carries
    the delta, the breakdown as the plan context a refit needs, and the per-term measurement
    difference a weight fit consumes.
    """

    objective_delta: float
    breakdown: ObjectiveBreakdown
    # Per term, the raw measurement of the plan the user chose minus that of the plan the solver
    # proposed. Signed: a term the user's choice improves reads negative. The weighted sum of these
    # under the pricing version's weights is `objective_delta`.
    measurement_delta: Mapping[str, float]


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
        return PinPrice(objective_delta=0.0, breakdown=before, measurement_delta=UNCHANGED)
    moved = _moved(document, block, accepted)
    after = evaluate(moved, inputs=inputs, weights=weights)
    return PinPrice(
        objective_delta=after.total() - before.total(),
        breakdown=before,
        measurement_delta=_measurement_delta(document, moved, inputs=inputs, weights=weights),
    )


def _measurement_delta(
    proposed: PlanDocument,
    accepted: PlanDocument,
    *,
    inputs: SolveInputs,
    weights: WeightSet,
) -> Mapping[str, float]:
    """Each term's raw measurement of ``accepted``, minus its raw measurement of ``proposed``."""
    unit = _at_unit_weights(weights)
    raw_proposed = evaluate(proposed, inputs=inputs, weights=unit).costs()
    raw_accepted = evaluate(accepted, inputs=inputs, weights=unit).costs()
    return {term: raw_accepted[term] - raw_proposed[term] for term in OBJECTIVE_TERMS}


def _at_unit_weights(weights: WeightSet) -> WeightSet:
    """``weights`` with every term weight at one, and every fitted parameter untouched.

    The seven are spelled out rather than taken from ``term_weights()``, so a term added to the
    objective is a name error here rather than a weight that quietly keeps its own scale and makes
    one of the seven measurements incomparable with the other six.
    """
    return replace(
        weights,
        deadline_risk=1.0,
        budget_deviation=1.0,
        time_of_day_misfit=1.0,
        fragmentation=1.0,
        churn=1.0,
        context_switch=1.0,
        staleness=1.0,
    )


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
