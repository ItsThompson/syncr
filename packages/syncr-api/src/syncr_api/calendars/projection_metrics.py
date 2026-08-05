"""The two metric families the projection exports, and why a refusal counts as a failure.

``syncr_projection_duration_seconds`` is labeled by outcome, and the outcome vocabulary has exactly
two members. A reconciliation refused before it started is recorded as **failed**, not as a member
of its own, because the consequence is identical: the plan is not reaching the phone.
``ProjectionFailing`` alerts on failures over fifteen minutes, so a third value would make that
alert silent for a deployment whose writes are switched off -- the same alert inversion ticket 27
shipped and ticket 28's closing pass fixed one layer down. Which KIND of stoppage it was lives
where the repair differs: the operation's error code, and the sentence in the banner.

``syncr_projection_events`` is a histogram labeled by action, observed once per action per
reconciliation, including the zeroes and including the partial counts of one that failed part way
through. The zeroes matter: an action observed only when it was non-zero makes a rate unreadable.

``foreign_deleted`` is the one to watch. It counts events the user created by hand on the write
target that syncr removed. Destructive reconciliation is the documented behaviour, so a non-zero
count is not a fault; a SUSTAINED one is a product signal that the user is still editing in their
calendar client.
"""

from __future__ import annotations

from typing import Final

from prometheus_client import Histogram

from syncr_common.metrics import REGISTRY

SUCCEEDED: Final = "succeeded"
FAILED: Final = "failed"
PROJECTION_OUTCOMES: Final = (SUCCEEDED, FAILED)

PROJECTION_DURATION = Histogram(
    "syncr_projection_duration_seconds",
    "How long one destructive reconciliation of the write target took, by outcome.",
    labelnames=("outcome",),
    registry=REGISTRY,
)

PROJECTION_EVENTS = Histogram(
    "syncr_projection_events",
    "Events one reconciliation changed on the write target, by action.",
    labelnames=("action",),
    # A reconciliation in the steady state changes a handful of events and a first one over a
    # fortnight changes a couple of hundred, so the buckets straddle both rather than defaulting to
    # a latency ladder measured in seconds.
    buckets=(0, 1, 2, 5, 10, 25, 50, 100, 250, 500),
    registry=REGISTRY,
)
