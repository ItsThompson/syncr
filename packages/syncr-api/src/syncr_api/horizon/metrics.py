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
"""

from __future__ import annotations

from prometheus_client import Gauge, Histogram

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
