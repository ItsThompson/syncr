"""Computing a live verdict on the request path, and the two metric families that watch it.

The arithmetic is pure and lives in the domain; what lives here is the one thing a pure function
cannot carry, which is who asked. The histogram is labeled by caller because the interactive one is
what the design rests on: every mutation that returns a live verdict probes first, and the
maintainer's hundreds of background probes a day must neither mask a regression there nor trigger
an alert about one.

**The assembly is the larger cost by an order of magnitude**, and it has its own histogram beside
this one. Watching only this figure would leave the dominant cost of every pin unmonitored, so the
two are read together: this one says the arithmetic is still interactive, and that one says the
request is.

The projection is inside the measurement, deliberately. From a caller's side the cost of a verdict
is the projection plus the arithmetic, and splitting them would report a figure no caller
experiences.

Its consumers are the pin and drag responses and the horizon maintainer's tick, neither of which
exists yet; until they do, this package's suite is what calls it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from prometheus_client import Histogram

from syncr_common.metrics import REGISTRY, measured
from syncr_domain.feasibility import probe

if TYPE_CHECKING:
    from syncr_domain.feasibility import Verdict
    from syncr_solver.inputs import SolveInputs

PROBE_DURATION = Histogram(
    "syncr_probe_duration_seconds",
    "Time to compute one week's feasibility verdict from capacity arithmetic, by caller.",
    labelnames=("caller",),
    registry=REGISTRY,
)


class ProbeCaller(StrEnum):
    """Who asked for a verdict. The one label on the probe histogram.

    Two members rather than the assembly's three: a solve does not probe. It produces a verdict of
    its own, from an attempted placement, which is a stronger finding than arithmetic can reach.
    """

    REQUEST = "request"
    MAINTAINER = "maintainer"


class WeekProbe:
    """The capacity arithmetic, bound to the caller that asks for it.

    A class rather than a function for the same reason the assembler is one: the caller label is
    bound at construction, so it stays out of the signature every consumer has to satisfy.
    """

    def __init__(self, *, caller: ProbeCaller) -> None:
        self._caller = caller

    # `measured` carries the per-method error counter every component in this application has; the
    # histogram beside it carries the caller label, which one component/method pair cannot express.
    @measured("feasibility")
    def verdict_for(self, inputs: SolveInputs) -> Verdict:
        """The verdict capacity arithmetic can prove about this assembly.

        Never a claim that the week works: the returned verdict carries ``probe`` provenance, and
        finding no gap means the week could not be proven impossible.
        """
        with PROBE_DURATION.labels(caller=self._caller.value).time():
            return probe(inputs.for_probe())
