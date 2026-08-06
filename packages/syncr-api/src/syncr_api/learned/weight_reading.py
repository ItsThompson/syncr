"""A stored weight set, as the value the objective reads. One direction: nothing writes back.

The solver takes plain floats and maps of them, and knows nothing about versions, origins,
maturity, or when a fit ran. Those are storage's concerns, so the projection happens here rather
than the solver growing a second constructor that takes a record.

**The two fitted maps have no producer, and this refuses rather than dropping them.** A stored
``time_of_day_fitness`` is a curve per Area and a stored ``skip_probability`` is a figure per Area
and time bucket, and no code in this deployment writes either: the offline fitters are what will,
and they own the stored spelling they choose. Reading a shape nobody has written would be inventing
the
contract; dropping a non-empty map would solve without curves the user's own history produced and
report nothing. So a set carrying either is refused, loudly, at the first solve that meets one.

``duration_multiplier`` is deliberately absent from this projection. It is read by the ASSEMBLER,
which applies it to estimates and elastic durations before a solve begins, so the solver never sees
it: applying it here as well would correct one estimate twice.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_solver.weights import WeightSet

if TYPE_CHECKING:
    from syncr_api.learned.records import WeightSetRecord


class FittedCurvesUnreadable(Exception):
    """A stored weight set carries fitted curves this deployment has no reader for."""


def as_weight_set(stored: WeightSetRecord) -> WeightSet:
    """The weights ``stored`` names, as the value one solve is produced under."""
    _require_no_curve_this_deployment_cannot_read(stored)
    return WeightSet(
        deadline_risk=stored.deadline_risk,
        budget_deviation=stored.budget_deviation,
        time_of_day_misfit=stored.time_of_day_misfit,
        fragmentation=stored.fragmentation,
        churn=stored.churn,
        context_switch=stored.context_switch,
        staleness=stored.staleness,
        context_switch_cost=stored.context_switch_cost,
        churn_tolerance=stored.churn_tolerance,
    )


def _require_no_curve_this_deployment_cannot_read(stored: WeightSetRecord) -> None:
    carried = [
        name
        for name, held in (
            ("time_of_day_fitness", stored.time_of_day_fitness),
            ("skip_probability", stored.skip_probability),
        )
        if held
    ]
    if not carried:
        return
    raise FittedCurvesUnreadable(
        f"weight set {stored.version} carries {' and '.join(carried)}, and nothing in this "
        "deployment reads either back: the offline fitters own the stored spelling, so solving "
        "against this set would silently ignore curves the user's own history produced"
    )
