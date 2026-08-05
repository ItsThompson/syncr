"""How current a week's plan is, derived from the week's own operation state.

Three words, and the strip renders one of them in the sub-line beside the block count: ``91 ·
solving`` says the count is about to change, and ``91 blocks`` says it is not. Derived on the
server rather than inferred by a client from the operation resource, because two readings of one
state is how the strip and the resource would come to disagree about whether a week is settled.

| Word | When |
|---|---|
| ``solving`` | a solve or a materialize for the week is pending or running |
| ``stale`` | none is in flight and the last one FAILED terminally |
| ``current`` | neither: the plan on the grid is what the inputs produce |

**In flight is asked first, so a retry reads as ``solving`` rather than as ``stale``.** A failure
with an attempt left comes back to the queue in the same transaction that recorded it, so a row
observed as ``failed`` has no attempt left and the plan really is the last one that worked.

**Only a solve and a materialize count.** A projection writes an existing plan out to a calendar,
so a week whose projection is queued has a current plan and a strip that said otherwise would be
reporting the calendar's state as the plan's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Literal

from syncr_api.solving.config import FAILED

if TYPE_CHECKING:
    from syncr_api.solving.records import OperationRecord

type PlanCurrency = Literal["current", "solving", "stale"]
CURRENT: Final[PlanCurrency] = "current"
SOLVING: Final[PlanCurrency] = "solving"
STALE: Final[PlanCurrency] = "stale"
PLAN_CURRENCIES: Final = (CURRENT, SOLVING, STALE)


def plan_currency(
    *, in_flight: OperationRecord | None, latest: OperationRecord | None
) -> PlanCurrency:
    """How current the plan is, given the week's in-flight and most recent plan operations.

    Both arguments are read over the plan-producing kinds. ``latest`` may be the same row as
    ``in_flight``, which costs nothing: the in-flight branch answers first.
    """
    if in_flight is not None:
        return SOLVING
    if latest is not None and latest.status == FAILED:
        return STALE
    return CURRENT
