"""The two families the plan horizon maintainer publishes.

``syncr_horizon_weeks_without_plan`` should sit at zero. A sustained non-zero value means the
maintainer is not keeping up or is failing, and that failure would otherwise present to the user as
a calendar that goes blank at a week boundary: the projector reads revisions, so a horizon week with
no revision is a week with nothing to project. ``HorizonNotMaintained`` alerts on it above zero for
two hours, which is eight ticks.

**The gauge is SET at the end of a pass rather than incremented per week**, because it measures a
state rather than counting events: a gauge nudged per week would drift permanently the first time a
pass raised between two weeks. Setting it from the pass's own tally means a contained fault leaves
the number honest, and a pass that never completed leaves the previous value, which the alert reads
as unresolved.

**A week whose minimum inputs are missing counts as without a plan, deliberately**, and so does a
tenant whose horizon could not be read at all. The maintainer cannot plan either, and both are
genuinely weeks inside the horizon with nothing to project: the honest gauge reading is the one that
says so, and it is also the only reading under which ``HorizonNotMaintained`` can fire for a duty
that fails every pass. What tells an operator the cases apart is the log line naming what is
missing, and the user is told by the Week screen's own empty state.

``syncr_maintainer_tick_duration_seconds`` is labeled by duty because the second duty probes every
week WITH a plan while this one plans the weeks without: the two costs are unrelated, and a
histogram
that mixed them could not be read.

``syncr_maintainer_verdict_transitions_total`` is duty 2's, labeled by the direction the week moved
in, and both directions are exported at zero before the first tick. It counts a subset of what
``syncr_verdict_transitions_total{surface="maintainer"}`` counts and is kept separate because it is
the series an operator watches per direction: a rise in weeks becoming impossible with no user
action is a product signal, and a rise in weeks recovering is not the same event.
"""

from __future__ import annotations

from enum import StrEnum

from prometheus_client import Counter, Gauge, Histogram

from syncr_common.metrics import REGISTRY

HORIZON_WEEKS_WITHOUT_PLAN = Gauge(
    "syncr_horizon_weeks_without_plan",
    "ISO weeks inside the projection horizon that hold no live plan.",
    registry=REGISTRY,
)

MAINTAINER_TICK_DURATION = Histogram(
    "syncr_maintainer_tick_duration_seconds",
    "Time one plan horizon maintainer tick spent, by the duty it was spent on.",
    labelnames=("duty",),
    registry=REGISTRY,
)

MAINTAINER_VERDICT_TRANSITIONS = Counter(
    "syncr_maintainer_verdict_transitions_total",
    "Time-driven verdict transitions the maintainer recorded, by the direction the week moved.",
    labelnames=("direction",),
    registry=REGISTRY,
)


class TransitionDirection(StrEnum):
    """Which way a week moved. The one label on the maintainer's transition counter.

    Read from the row that was written rather than from the verdict that was probed, because the row
    carries the reading the corpus holds: a probe verdict's own ``feasible`` field is always false.
    """

    TO_INFEASIBLE = "to_infeasible"
    TO_FEASIBLE = "to_feasible"

    @classmethod
    def of(cls, *, feasible: bool) -> TransitionDirection:
        """The direction a recorded transition to ``feasible`` moved in."""
        return cls.TO_FEASIBLE if feasible else cls.TO_INFEASIBLE


def seed_the_transition_directions() -> None:
    """Export both directions at zero, before the first tick records one.

    A labeled family does not exist until a label is used, so a counter nobody has incremented is
    absent from the exposition rather than zero, and an alert or a rate stated over an absent series
    answers nothing. Called at import, because the module that defines the instrument knows its
    vocabulary.
    """
    for direction in TransitionDirection:
        MAINTAINER_VERDICT_TRANSITIONS.labels(direction=direction.value)


seed_the_transition_directions()
