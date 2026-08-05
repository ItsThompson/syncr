"""The solver's own metric families, on the registry the application exposes.

One counter today. It sits here rather than beside the code it measures so that the label
vocabulary and the family name have one home, and so a reader asking what the solver publishes
reads one file.

``syncr_materialize_total`` is read two ways. The ``solve_failed`` count should be zero in normal
operation, and a non-zero value is a solver fault surfacing as a degraded plan rather than as an
outage. The ``checkpoint`` count is the horizon maintainer bringing weeks into range. Neither is
derivable from the other, and neither is derivable from the solve counters, which is why the
cause is a label rather than an inference.

Incrementing a counter is the one effect materialization has besides its return value. It reads
no clock, touches no file, and does not change the document, so the purity the solver claims is
untouched: a caller can materialize twice and compare the two documents byte for byte.
"""

from __future__ import annotations

from enum import StrEnum

from prometheus_client import Counter

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
