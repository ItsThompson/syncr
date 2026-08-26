"""``syncr_verdict_transitions_total``, and the label set a writer can actually produce.

One family, three labels, and every series it can hold is exported at zero before the first
transition. A labeled family does not exist until a label is used, so a counter nobody has
incremented is ABSENT from the exposition rather than zero, and a rate stated over an absent series
answers nothing: the reading "no week has changed verdict" and the reading "this process has not
recorded one yet" have to be different, and they are only different if the vocabulary is exported up
front.

**What this family is not.** It is the operational read, not the product metric. The early-catch
ratio's numerator is the EPISODE count -- episodes begun in the period, each counted once however
many rows it holds -- and the ``largest_gap_minutes`` column on those rows is read by no metric:
a gap's size says how large a shortage was, never whether anyone was told in time.

**Seeded over the reachable pairs rather than over every combination.** A surface reaches a verdict
one way, which :data:`~syncr_api.plans.surfaces.REACHABLE_PAIRS` states, so twelve series exist
rather than twenty-four. A series for ``surface="solve", provenance="probe"`` would be one an
operator reads as "a solve has never disagreed with the arithmetic", when what it means is that no
writer can produce it at all.
"""

from __future__ import annotations

from prometheus_client import Counter

from syncr_api.plans.surfaces import REACHABLE_PAIRS
from syncr_common.metrics import REGISTRY

VERDICT_TRANSITIONS = Counter(
    "syncr_verdict_transitions_total",
    "Verdict transitions recorded, by what proved it, which way it went, and where it was found.",
    labelnames=("provenance", "feasible", "surface"),
    registry=REGISTRY,
)

# Both readings of the `feasible` label, as the strings a scrape carries.
_FEASIBILITY = ("true", "false")


def as_label(feasible: bool) -> str:
    """The one spelling of the ``feasible`` label, so a counter and its seed cannot disagree."""
    return "true" if feasible else "false"


def seed_the_transition_family() -> None:
    """Export every series a writer can produce at zero, before anything records one.

    Called at import, because the module that defines the instrument is the one that knows its
    vocabulary.
    """
    for surface, provenance in REACHABLE_PAIRS:
        for feasible in _FEASIBILITY:
            VERDICT_TRANSITIONS.labels(
                provenance=provenance.value, feasible=feasible, surface=surface.value
            )


seed_the_transition_family()
