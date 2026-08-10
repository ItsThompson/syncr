"""Accumulating the components a read refused: a bounded sample of them, and a count of all of them.

Every rejection any adapter produces goes through one of these, because the two figures a source's
panel needs are different figures and only one of them can be stored.

**The sample is what a reader renders.** The first few instances of each class, which is what names
a cause a publisher can act on. It is bounded because a publisher decides how many components a
feed holds: the sample is written to JSONB on the sync state and served whole on every panel render,
so an unbounded one is an unbounded write and an unbounded response on page load.

**The count is what the accounting closes over.** Every component a feed offered is kept, rejected,
discarded, applied or read and found to place nothing, and a term that stopped at the sample would
report a feed that refused fifty thousand components as having refused fifteen. Counted per kind
rather than as one number, because the rejection metric is labelled by kind and a count summed
before it reached the labels could not be spent there.

**The FIRST entries of each kind are kept rather than the last.** A feed whose reading budget runs
out part way through appends one rejection per remaining component, so keeping the last would push
out the ordinary rejections the feed began with, which are the ones the publisher can fix.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from syncr_api.calendars.config import REJECTIONS_KEPT_PER_KIND
from syncr_api.calendars.events import RejectionTally

if TYPE_CHECKING:
    from syncr_api.calendars.config import RejectionKind
    from syncr_api.calendars.events import RejectedComponent


@dataclass(slots=True)
class RejectionAccumulator:
    """The rejections one read produced, sampled for a panel and counted in full.

    ``kept_per_kind`` is a parameter rather than only a constant so a test can plant a feed over a
    small bound instead of over the shipped one. It is the only parameter: the sample and the counts
    are built here and never handed in, because an accumulator constructed around a caller's own
    list would alias the mutable state the copies in :meth:`tally` exist to protect.
    """

    kept_per_kind: int = REJECTIONS_KEPT_PER_KIND
    _kept: list[RejectedComponent] = field(default_factory=list, init=False)
    _counted: Counter[RejectionKind] = field(default_factory=Counter, init=False)

    def add(self, rejected: RejectedComponent) -> None:
        """Count one rejection, and keep it when its kind still has room in the sample."""
        if self._counted[rejected.kind] < self.kept_per_kind:
            self._kept.append(rejected)
        self._counted[rejected.kind] += 1

    def tally(self) -> RejectionTally:
        """The sample and the counts, as an outcome carries them."""
        return RejectionTally(sample=tuple(self._kept), counted=dict(self._counted))


def one_rejection(rejected: RejectedComponent) -> RejectionTally:
    """The tally of a read that refused exactly one thing, which is a whole feed's worth.

    A body the lexer refused produces one rejection naming the calendar rather than a component.
    It goes through the accumulator like every other rejection, so nothing composes a tally by hand.
    """
    accumulated = RejectionAccumulator()
    accumulated.add(rejected)
    return accumulated.tally()
