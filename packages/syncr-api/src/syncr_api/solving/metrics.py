"""What the orchestration publishes about itself: four families the debounce is tuned from.

The solver package already times the SOLVE. These measure the OPERATION around it, which is a
different subject: a solve that ran perfectly and was then discarded is a success to the solver and
a supersession to the product, and the whole debounce question is answered by how often that
happens.

| Family | Answers |
|---|---|
| ``syncr_solve_total`` | how many solves ended each way |
| ``syncr_solve_superseded_ratio`` | whether the debounce window fits how this user edits |
| ``syncr_operations_non_terminal`` | whether anything is stuck, by kind |
| ``syncr_operation_queue_delay_seconds`` | how long a claim waited past the instant it was due |

**The ratio is set from the same tally that increments the counter**, so the two cannot disagree
about how many solves there were. It is cumulative over the process's own lifetime, which is the
reading an operator gets from ``/metrics`` alone; the windowed reading, which is the one the 0.3
threshold is stated against, is a query over the counter and
``docs/runbooks/debounce-tuning.md`` states it.

**The queue delay is observed at the CLAIM, not at the finish.** What it measures is the worker
falling behind: a debounced solve is due 1500 ms after the mutation, and a delay far above the tick
interval means the tick is spending its time elsewhere. Measuring at the finish would fold the
solve's own duration into it, which the solver's histogram already reports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from prometheus_client import Counter, Gauge, Histogram

from syncr_api.solving.config import OPERATION_KINDS, SUPERSEDED, TERMINAL_STATUSES
from syncr_common.metrics import REGISTRY

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syncr_api.solving.config import OperationStatus

SOLVE_TOTAL = Counter(
    "syncr_solve_total",
    "Solve operations that reached a terminal status, by which one.",
    labelnames=("outcome",),
    registry=REGISTRY,
)

SUPERSEDED_RATIO = Gauge(
    "syncr_solve_superseded_ratio",
    "Share of this process's finished solves that were discarded as superseded.",
    registry=REGISTRY,
)

OPERATIONS_NON_TERMINAL = Gauge(
    "syncr_operations_non_terminal",
    "Operations that are pending or running, by kind.",
    labelnames=("kind",),
    registry=REGISTRY,
)

OPERATION_QUEUE_DELAY = Histogram(
    "syncr_operation_queue_delay_seconds",
    "How long a claimed operation waited past the instant it became due, by kind.",
    labelnames=("kind",),
    registry=REGISTRY,
)

# The three statuses a solve can end in, seeded at zero so a scraper sees the vocabulary before
# the first solve rather than a family that appears one label at a time. Read from the status set
# rather than listed, so a fourth terminal status is exported without being remembered.
_FINISHED: Final[tuple[OperationStatus, ...]] = TERMINAL_STATUSES


def seed_the_operation_families() -> None:
    """Export every label of the two kind-labeled families at zero, before anything observes one.

    A labeled family does not exist until a label is used, so a gauge nobody has set yet is absent
    from the exposition rather than zero. An alert stated over an absent series does not fire, which
    is the failure this epic has now shipped twice: the reading "nothing is stuck" and the reading
    "this process has not looked yet" have to be different, and they are only different if the
    vocabulary is exported up front.

    Called at import, because the module that defines the instrument is the one that knows its
    vocabulary. The queue delay is a histogram, so it is seeded by observing nothing rather than by
    setting a value: touching the child is what creates its series.
    """
    for kind in OPERATION_KINDS:
        OPERATIONS_NON_TERMINAL.labels(kind=kind).set(0)
        OPERATION_QUEUE_DELAY.labels(kind=kind)


class SolveTally:
    """The finished solves this process has seen, and the ratio derived from them.

    A counter cannot be read back portably, so the tally is held here and both instruments are
    written from it. That is what makes "the ratio is the share of the counter" true of the values
    rather than of a comment: one increment updates both.
    """

    def __init__(self) -> None:
        self._counts: dict[OperationStatus, int] = dict.fromkeys(_FINISHED, 0)
        for status in _FINISHED:
            SOLVE_TOTAL.labels(outcome=status)
        SUPERSEDED_RATIO.set(0.0)

    @property
    def counts(self) -> Mapping[OperationStatus, int]:
        """How many solves ended in each terminal status, for a test and for the ratio."""
        return dict(self._counts)

    def finished(self, status: OperationStatus) -> None:
        """Record one solve's ending, and re-derive the ratio from every ending so far."""
        if status not in self._counts:
            return
        self._counts[status] += 1
        SOLVE_TOTAL.labels(outcome=status).inc()
        SUPERSEDED_RATIO.set(self._ratio())

    def _ratio(self) -> float:
        finished = sum(self._counts.values())
        # Unreachable from `finished`, which has just incremented one count. Stated so the
        # expression is total: a process with no solves reports zero rather than dividing by it.
        if not finished:  # pragma: no cover
            return 0.0
        return self._counts[SUPERSEDED] / finished


SOLVE_TALLY = SolveTally()
"""One tally per process, because both instruments it writes are process-wide too."""

seed_the_operation_families()
