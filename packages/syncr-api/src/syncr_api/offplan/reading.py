"""What an off-plan span means to a report: how many minutes, and whether to say why.

A budget report over a week that was entirely off-plan is a row of zeros, and a row of zeros
has two readings: nothing was planned, or nothing was meant to be. The first is a failure and
the second is a holiday, so the report states which. That is the whole reason this module
exists: without it the honest answer and the alarming one render identically.

``statement`` is non-null exactly when the week is covered end to end, which is the same
convention ``RampReading.statement`` follows. A partially off-plan week needs no statement:
its denominator is smaller and its deviations are still meaningful, so the minute count alone
says what happened.

The coverage test is ``the span minus the off-plan spans is empty``, not ``off-plan minutes equal
the span's minutes``. Both counts truncate a sub-minute remainder, and they truncate
independently: a span whose own length carries seconds reads as the same number of minutes as the
off-plan time inside it while a fraction of it is still on plan. Emptiness of the residual cannot
be reached that way, and it is no more code than the comparison.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_domain.intervals import IntervalSet

if TYPE_CHECKING:
    from syncr_domain.intervals import Interval

WHOLE_WEEK_STATEMENT = (
    "This week was declared off-plan from end to end, so it holds no discretionary time and "
    "every Area target is zero. Nothing is missing from the plan."
)


@dataclass(frozen=True, slots=True)
class OffPlanReading:
    """How much of one week was off-plan, and what the report says about it."""

    minutes: int
    statement: str | None


def off_plan_reading(span: Interval, off_plan: IntervalSet) -> OffPlanReading:
    """The off-plan reading for ``span``, given the spans overlapping it.

    ``off_plan`` arrives unclipped, so it is clipped here: a Friday-to-Monday span contributes
    its Friday-to-Sunday part to one week's reading and its Monday part to the next week's.
    """
    inside = off_plan.clip(span)
    uncovered = IntervalSet([span]).subtract(inside)
    return OffPlanReading(
        minutes=inside.total_minutes(),
        statement=None if uncovered else WHOLE_WEEK_STATEMENT,
    )
