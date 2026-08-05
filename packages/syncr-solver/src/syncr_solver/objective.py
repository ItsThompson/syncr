"""``evaluate``: one plan's cost, as a breakdown per term rather than as a scalar.

The solver minimizes a weighted sum of costs and returns the **breakdown**, because a scalar
cannot be explained: the ``dominant`` reason clause renders which term carried the cost, and the
learning layer refits the weights from the same seven numbers.

Pure. No clock, no I/O, no randomness. Two evaluations of one plan against one week are equal,
which is what lets the local search accept only strict improvements without a tolerance.

## What the breakdown holds

Seven costs, each a weight times the raw measurement its term returned. The costs are what
``total()`` sums and what a share is taken of, because a raw measurement is only comparable with
another term's after its weight is applied.

Two further fields carry what two terms would otherwise lose, and neither is a cost:

- ``staleness_split`` names which of the staleness term's two inputs dominated, which is what
  keeps one term with two inputs from costing anything in explainability;
- ``churn_baseline`` names the plan churn was measured against, or states that there is none,
  which is what stops a churn of zero reading as a plan that never moved.

## Where the fitted parameters are applied, and where one is not

Four are applied inside the terms: the time-of-day fitness and the skip probability as two of the
misfit term's four components, the price of an Area change against the gap the schedule leaves,
and the churn tolerance as the point the churn cost begins to rise steeply.

The fifth, ``duration_multiplier``, is applied by the week assembler and is not reachable from a
:class:`~syncr_solver.weights.WeightSet`. So a plan is always evaluated against already-corrected
durations, and the objective cannot multiply a duration because it holds no multiplier to
multiply by.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import TYPE_CHECKING

from syncr_domain.plan import PlanError
from syncr_solver.inputs import ChurnBaseline
from syncr_solver.reading import PlanReading
from syncr_solver.terms import (
    StalenessSplit,
    budget_deviation,
    churn,
    context_switch,
    deadline_risk,
    fragmentation,
    staleness,
    time_of_day_misfit,
)
from syncr_solver.weights import OBJECTIVE_TERMS

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syncr_domain.plan import PlanDocument
    from syncr_solver.inputs import SolveInputs
    from syncr_solver.weights import WeightSet


@dataclass(frozen=True, slots=True, kw_only=True)
class ObjectiveBreakdown:
    """What one plan costs, per term, under one weight set.

    Seven costs and nothing else that is a number. Every one is a weight times a dimensionless
    measurement, so the seven are comparable with each other and a share of the total is the
    percentage the ``dominant`` clause renders.
    """

    deadline_risk: float
    budget_deviation: float
    time_of_day_misfit: float
    fragmentation: float
    churn: float
    context_switch: float
    staleness: float

    # Which of the staleness term's two inputs dominated, and both figures. Not a cost: the term
    # above is the cost, and this is what the reason record names.
    staleness_split: StalenessSplit = field(default_factory=StalenessSplit)
    # What churn was measured against, or the statement that there is nothing to measure against.
    # A breakdown built for its arithmetic alone states the truthful zero, which is a week no
    # revision of has been approved.
    churn_baseline: ChurnBaseline = field(default_factory=ChurnBaseline.never_approved)

    def __post_init__(self) -> None:
        for term, cost in self.costs().items():
            _require_a_cost(term, cost)
        _require_a_baseline_for_a_charged_churn(self.churn, self.churn_baseline)
        _require_a_split_for_a_charged_staleness(self.staleness, self.staleness_split)

    def costs(self) -> Mapping[str, float]:
        """Each term's cost by its name: the shape a revision stores and an edit event carries.

        Spelled out rather than read off the fields, for the reason
        :meth:`~syncr_solver.weights.WeightSet.term_weights` is, and crossed against the
        vocabulary at construction so the two mappings cannot name different terms.
        """
        return {
            "deadline_risk": self.deadline_risk,
            "budget_deviation": self.budget_deviation,
            "time_of_day_misfit": self.time_of_day_misfit,
            "fragmentation": self.fragmentation,
            "churn": self.churn,
            "context_switch": self.context_switch,
            "staleness": self.staleness,
        }

    def total(self) -> float:
        """What this plan costs in all. What the local search compares."""
        return sum(self.costs().values())

    def dominant_term(self) -> str | None:
        """The term carrying the largest share of the total, or nothing because there is none.

        ``None`` for a plan that costs nothing, which an empty week really is. A name at a share
        of zero would state a dominant cost no arithmetic here found, and the ``dominant`` clause
        is optional, so a plan with nothing to report reports nothing.

        A tie goes to the earlier term in the vocabulary, so the same plan always names the same
        term: without that the answer would depend on a mapping's iteration order.
        """
        costs = self.costs()
        ranked = max(OBJECTIVE_TERMS, key=lambda term: (costs[term], -OBJECTIVE_TERMS.index(term)))
        return None if costs[ranked] <= 0 else ranked

    def share_of(self, term: str) -> float:
        """This term's fraction of the total, from 0 to 1. Zero when nothing costs anything."""
        costs = self.costs()
        if term not in costs:
            raise PlanError(
                f"{term!r} is not one of the objective's seven terms: they are "
                f"{', '.join(OBJECTIVE_TERMS)}"
            )
        total = self.total()
        return 0.0 if total <= 0 else costs[term] / total


def evaluate(plan: PlanDocument, *, inputs: SolveInputs, weights: WeightSet) -> ObjectiveBreakdown:
    """What ``plan`` costs, term by term, for the week ``inputs`` describes under ``weights``.

    The plan alone cannot be evaluated: a deadline, an Area's target, a preferred window and the
    approved baseline are all facts about the week rather than about the document, and the weights
    are the tenant's. So the three arrive together, and the function reads nothing else at all.
    """
    _require_one_week(plan, inputs)
    reading = PlanReading.of(plan, inputs=inputs)
    split = staleness(reading)
    return ObjectiveBreakdown(
        deadline_risk=weights.deadline_risk * deadline_risk(reading),
        budget_deviation=weights.budget_deviation * budget_deviation(reading),
        time_of_day_misfit=weights.time_of_day_misfit * time_of_day_misfit(reading, weights),
        fragmentation=weights.fragmentation * fragmentation(reading),
        churn=weights.churn * churn(reading, weights),
        context_switch=weights.context_switch * context_switch(reading, weights),
        staleness=weights.staleness * split.share(),
        staleness_split=split,
        churn_baseline=inputs.churn_baseline,
    )


def _require_one_week(plan: PlanDocument, inputs: SolveInputs) -> None:
    """A document and the inputs it is scored against describe one week.

    Every figure the terms compare is for a specific week: an Area's target, a task's remaining
    minutes, the discretionary denominator. Scored against another week's inputs the answer would
    be arithmetic on unrelated quantities rather than an error, which is the failure this product
    cannot detect any other way.
    """
    if plan.iso_week != inputs.iso_week:
        raise PlanError(
            f"a plan for {plan.iso_week} cannot be scored against inputs for {inputs.iso_week}: "
            "every figure the terms compare is resolved for one specific week"
        )


def _require_a_cost(term: str, cost: float) -> None:
    """A cost is finite and never negative, because a share of the total has to be readable.

    A negative cost would make the solver seek the thing the term measures and could make a total
    of zero out of two non-zero terms; a non-finite one would make every share undefined. Both
    are faults in a weight or in a term rather than states a plan can be in.
    """
    if not isfinite(cost) or cost < 0:
        raise PlanError(
            f"the {term!r} cost is {cost}, and a cost is a finite number at or above zero: a "
            "negative one would pay the plan for what the term measures"
        )


def _require_a_baseline_for_a_charged_churn(cost: float, baseline: ChurnBaseline) -> None:
    """Churn above zero names the plan it is the difference from.

    The two are one statement seen twice, so a charged churn with no baseline would be a cost the
    reason record cannot explain, and a composition that read the term but dropped the baseline
    would ship exactly that.
    """
    if cost > 0 and not baseline.is_measured:
        raise PlanError(
            f"churn costs {cost} against a baseline of {baseline.reason!r}: churn is the "
            "difference from the plan the user approved, so a charge with no such plan is a "
            "cost nothing can be the difference from"
        )


def _require_a_split_for_a_charged_staleness(cost: float, split: StalenessSplit) -> None:
    """Staleness above zero names which of its two inputs it came from.

    The same shape as the churn guard: the term is one number over two inputs, and the split is
    what keeps the single weight from costing anything in explainability. A charge whose split is
    empty is a composition that read one and dropped the other.
    """
    if cost > 0 and split.dominant() is None:
        raise PlanError(
            f"staleness costs {cost} and its split names neither input: the term is one weight "
            "over an overdue cadence item and a rotation that has not advanced, and the "
            "breakdown names which of them dominated"
        )
