"""The three metric families the projection exports, and why a refusal counts as a failure.

``syncr_projection_duration_seconds`` is labeled by outcome, and the outcome vocabulary has exactly
two members. A reconciliation refused before it started is recorded as **failed**, not as a member
of its own, because the consequence is identical: the plan is not reaching the phone.
``ProjectionFailing`` alerts on failures over fifteen minutes, so a third value would make that
alert silent for a deployment whose writes are switched off -- the same alert inversion ticket 27
shipped and ticket 28's closing pass fixed one layer down. Which KIND of stoppage it was lives
where the repair differs: the operation's error code, and the sentence in the banner.

**Two outcome values alone would trade a silent alert for an always-firing one**, because writes
are off in every deployment today, so every plan change produces a failure. That is what the third
family is for: with the arming state exported, the alert is stated as "failures over fifteen minutes
AND writes enabled", which inhibits a deliberately-off deployment without the outcome label having
to lie about what happened. Ticket 1302 carries the rule.

``syncr_projection_events`` is a histogram labeled by action, observed once per action per
reconciliation, including the zeroes and including the partial counts of one that failed part way
through. The zeroes matter: an action observed only when it was non-zero makes a rate unreadable.

``foreign_deleted`` is the one to watch. It counts events the user created by hand on the write
target that syncr removed. Destructive reconciliation is the documented behaviour, so a non-zero
count is not a fault; a SUSTAINED one is a product signal that the user is still editing in their
calendar client.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from prometheus_client import Gauge, Histogram

from syncr_common.metrics import REGISTRY

if TYPE_CHECKING:
    from syncr_api.calendars.projection import ReconcileResult

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

# Whether this deployment may write to the calendar it owns: 1 or 0. Not in `18-observability.md`'s
# table, and named here because the alert that table defines cannot be stated correctly without it.
#
# A property of the DEPLOYMENT rather than of a tenant, and set on every pass rather than where a
# write is composed: a gauge that appeared only when a write was attempted would be absent from the
# exposition exactly when the alert needed to read it, and an alert whose inhibiting term is absent
# either never fires or always does, depending on which way it was written.
PROJECTION_WRITES_ENABLED = Gauge(
    "syncr_projection_writes_enabled",
    "Whether this deployment is permitted to write the plan to its calendar. 1 or 0.",
    registry=REGISTRY,
)


def observed(result: ReconcileResult, *, outcome: str) -> None:
    """Report one reconciliation to both families, including the zeroes.

    Here rather than at the duty that calls it, because what it does is decide what these two
    families are told: every action on every reconciliation, so a rate over the histogram is
    readable, and the duration under the outcome the pass reached. A caller that observed only the
    non-zero actions would make a rate unreadable, and one that skipped a failure's partial counts
    would lose the writes that did land.
    """
    PROJECTION_DURATION.labels(outcome=outcome).observe(result.duration_ms / 1000)
    for action, count in result.by_action().items():
        PROJECTION_EVENTS.labels(action=action.value).observe(count)
