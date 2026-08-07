"""The one statement of each exclusion rule, so three readers cannot state it three ways.

Small on purpose. What lives here is the predicate the outcome-derived observations and the
edit-derived ones both apply, and it lives outside both so neither imports the other for it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_domain.intervals import Interval
    from syncr_learning.facts import OffPlanSpan


def is_off_plan(interval: Interval, off_plan: Sequence[OffPlanSpan]) -> bool:
    """Whether any declared span touches this interval at all.

    Overlap rather than containment, and that IS the wholesale rule: a block half inside a holiday
    was half lived under a different regime, and a rule that counted it would have to say which
    half.

    Applied whatever the confirmation state, which is the unconditional part. A split rule
    preserving duration signal from confirmed pinned blocks inside an off-plan span was considered
    and rejected: a holiday is a different regime for WHEN you do things but arguably not for HOW
    LONG a gym session takes, and the cost of the simple rule is a small amount of duration signal a
    few times a year.
    """
    return any(span.interval.overlaps(interval) for span in off_plan)
