"""The five fitters. One module each, one pure function each, one parameter each.

Each takes a list of observations and returns a :class:`~syncr_learning.results.FitResult`. None of
them reads a gate: a fitter's job is to answer what the evidence says, and whether the answer is
applied is :mod:`syncr_learning.gates`'s decision. Keeping the two apart is what makes "a parameter
below its gate is not applied at all" one statement in one place.

| Module | Parameter | Consumed by |
|---|---|---|
| ``duration.py`` | ``duration_multiplier[area]`` | the week assembler, before a solve begins |
| ``time_of_day.py`` | ``time_of_day_fitness[area][hour]`` | the objective's misfit term |
| ``skipping.py`` | ``skip_probability[(area, bucket)]`` | the objective's misfit term |
| ``switching.py`` | ``context_switch_cost`` | the objective's context-switch term |
| ``churn.py`` | ``churn_tolerance`` | the objective's churn term |

Every one of the five has a named consumer and one application point. A fitted number with no
consumer would be a number nobody reads.
"""

from __future__ import annotations

from syncr_learning.fitters.churn import fit_churn_tolerance
from syncr_learning.fitters.duration import fit_duration_multiplier
from syncr_learning.fitters.skipping import fit_skip_probability
from syncr_learning.fitters.switching import fit_context_switch_cost
from syncr_learning.fitters.time_of_day import FittedCurve, fit_time_of_day_fitness

__all__ = [
    "FittedCurve",
    "fit_churn_tolerance",
    "fit_context_switch_cost",
    "fit_duration_multiplier",
    "fit_skip_probability",
    "fit_time_of_day_fitness",
]
