"""The solver's own metric families, on the registry the application exposes.

Five families: one counter for the weeks derivation alone produced, and four histograms for what a
solve did. They sit here rather than beside the code they measure so that the label vocabulary and
the family names have one home, and so a reader asking what the solver publishes reads one file.

``syncr_materialize_total`` is read two ways. The ``solve_failed`` count should be zero in normal
operation, and a non-zero value is a solver fault surfacing as a degraded plan rather than as an
outage. The ``checkpoint`` count is the horizon maintainer bringing weeks into range. Neither is
derivable from the other, and neither is derivable from the solve counters, which is why the
cause is a label rather than an inference.

Observing a metric is the one effect these entry points have besides their return values. Both
touch no file, change no document, and draw on no randomness, and the monotonic clock a duration is
timed against cannot change what a call returns, so the purity the solver claims is untouched: a
caller can materialize or solve twice and compare the two documents byte for byte.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from prometheus_client import Counter, Histogram

from syncr_common.metrics import REGISTRY


class MaterializeCause(StrEnum):
    """Why a materialization ran. One member per caller, and there are exactly three.

    Required at every call site rather than defaulted, because a default would attribute one
    caller's materializations to another, and the whole value of the label is telling the
    fallback path apart from the two ordinary ones.
    """

    PHASE1 = "phase1"
    CHECKPOINT = "checkpoint"
    SOLVE_FAILED = "solve_failed"


MATERIALIZE_TOTAL = Counter(
    "syncr_materialize_total",
    "Weeks materialized from derivation alone, by what asked for it.",
    labelnames=("cause",),
    registry=REGISTRY,
)


class SolveOutcome(StrEnum):
    """How a solve ended, as the label its duration is recorded under.

    Three members and two producers. A solve that returns records ``succeeded``, because that is the
    only outcome the placement code can observe. ``superseded`` and ``failed`` belong to the solve
    coordinator, which is the one component that can see an input version move under a running solve
    or a solve raise. The vocabulary is declared here so both record ONE family rather than two.
    """

    SUCCEEDED = "succeeded"
    SUPERSEDED = "superseded"
    FAILED = "failed"


# How long a solve took, by how it ended. The one family a clock reaches: timing a call against a
# monotonic clock cannot change what the call returns.
SOLVE_DURATION = Histogram(
    "syncr_solve_duration_seconds",
    "Wall time one solve took, from its first phase to its verdict, by how it ended.",
    labelnames=("outcome",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0),
    registry=REGISTRY,
)

# The three below count things rather than seconds, so each states its own buckets: the client's
# defaults are latency-shaped and would put every solve in the last one.

SOLVE_ITERATIONS = Histogram(
    "syncr_solve_iterations",
    "Local-search moves one solve considered, against its configured budget.",
    buckets=(1.0, 10.0, 50.0, 100.0, 200.0, 400.0, 800.0),
    registry=REGISTRY,
)

# Sized against the 210 blocks a fully planned week is expected to reach rather than against the
# ~62 a hand-planned one measures at, which is the figure this product replaces.
SOLVE_BLOCKS_PLACED = Histogram(
    "syncr_solve_blocks_placed",
    "Blocks the document one solve produced holds.",
    buckets=(10.0, 50.0, 100.0, 150.0, 210.0, 300.0, 500.0),
    registry=REGISTRY,
)

# One observation per reason per solve INCLUDING zero, so a reason that stopped happening reads as a
# fall rather than as a series that went absent.
SOLVE_EMPTY_SLOTS = Histogram(
    "syncr_solve_empty_slots",
    "Template slots one solve left unfilled, by the reason it stated.",
    labelnames=("reason",),
    buckets=(0.0, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0),
    registry=REGISTRY,
)

# The four a solve publishes, named so a reader finds the inventory in one place and a test can
# cross it against what the registry carries.
SOLVE_FAMILIES: Final = (
    "syncr_solve_duration_seconds",
    "syncr_solve_iterations",
    "syncr_solve_blocks_placed",
    "syncr_solve_empty_slots",
)
