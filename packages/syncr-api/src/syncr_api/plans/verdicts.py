"""Computing a live verdict on the request path, and the two metric families that watch it.

The arithmetic is pure and lives in the domain; what lives here is the one thing a pure function
cannot carry, which is who asked. The histogram is labeled by caller because the interactive one is
what the design rests on: every mutation that returns a live verdict probes first, and the
maintainer's hundreds of background probes a day must neither mask a regression there nor trigger
an alert about one.

**A verdict a panel renders carries its tradeoffs, and a verdict a recorder reads does not.** Two
methods for that reason rather than one: the panel needs the concessions each gap could be closed
with, and the transition recorder needs the shortfall kinds and the version. Enumerating for the
recorder would compute a list nothing reads.

**The assembly is the larger cost by an order of magnitude**, and it has its own histogram beside
this one. Watching only this figure would leave the dominant cost of every pin unmonitored, so the
two are read together: this one says the arithmetic is still interactive, and that one says the
request is.

The projection is inside the measurement, deliberately. From a caller's side the cost of a verdict
is the projection plus the arithmetic, and splitting them would report a figure no caller
experiences.

Its consumers are the pin and drag responses, the tradeoff request path, and the horizon
maintainer's tick.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING

from prometheus_client import Histogram

from syncr_api.plans.tradeoffs import offered_tradeoffs
from syncr_common.metrics import REGISTRY, measured
from syncr_domain.feasibility import probe

if TYPE_CHECKING:
    from syncr_api.plans.tradeoffs import Offer, OfferedConcession
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


@dataclass(frozen=True, slots=True, kw_only=True)
class OfferedVerdict:
    """A week's verdict, and the concession each tradeoff on it would apply.

    Two readings of one enumeration, held together so they cannot diverge. ``verdict`` is what a
    panel renders and what crosses the wire; ``offers`` carry the reductions and the target a
    request needs to build the candidate, which a rendered label cannot.
    """

    verdict: Verdict
    offers: tuple[Offer, ...]

    def offered(self, concession: OfferedConcession) -> Offer | None:
        """The offer a request names by kind and target, or ``None`` if syncr offered no such thing.

        The check that keeps a request from asking for a concession the enumerator would not make: a
        reduction below a routine's own floor, a breach larger than the floor reserves, or a
        concession on a week that is not short at all.
        """
        return next((offer for offer in self.offers if offer.concession == concession), None)


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

    @measured("feasibility")
    def offered_verdict_for(self, inputs: SolveInputs) -> OfferedVerdict:
        """The verdict, with a tradeoff per gap, and the concession each one would apply.

        What a panel needs in one call: a gap the user can do nothing about is a refusal without a
        remedy. The enumeration is pure and cheap beside the assembly that produced ``inputs``, and
        it is deterministic, so two calls over one assembly are equal.
        """
        verdict = self.verdict_for(inputs)
        offers = offered_tradeoffs(inputs, verdict)
        return OfferedVerdict(
            verdict=replace(verdict, tradeoffs=tuple(offer.tradeoff for offer in offers)),
            offers=offers,
        )
