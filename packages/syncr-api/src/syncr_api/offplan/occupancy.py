"""What a week holds once off-plan periods are stored: the fourth subtrahend, and nothing else.

This is the occupancy reader the budget report asks, replacing
:class:`~syncr_api.budgets.occupancy.UnplannedWeek`. It fills exactly one of the five sets,
and the four it leaves empty are each empty for a reason that has not changed:

| Set | Awaits |
|---|---|
| ``frame`` | routines, which no table holds yet |
| ``anchors`` | anchors, which no table holds yet |
| ``absolute_forbidden`` | recovery windows, which shadow generation casts |
| ``by_area`` | the plan document's interior, which is not defined yet |

**The members are unclipped, and that is correct rather than sloppy.** A period running from
Friday to Monday is returned whole, and the denominator subtracts it from the week's own span,
so the part outside the week removes nothing:
``IntervalSet([span]).subtract(occupied)`` cannot reach past ``span``. Clipping here would be
a second place the week's bounds were applied, and the figure would be identical.

**Nothing here re-checks that the stored periods do not overlap.** The invariant holds because
the write path enforces it, and the union is what makes it moot here: ``IntervalSet``
normalizes, so two rows covering one instant subtract exactly what one row covering it would.
A read that raised over an invariant only a write can break would take the whole budget report
down to report a figure it can compute correctly anyway.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.budgets.occupancy import WeekOccupancy
from syncr_domain.intervals import IntervalSet

if TYPE_CHECKING:
    from syncr_api.offplan.repository import OffPlanPeriodRepository
    from syncr_domain.intervals import Interval
    from syncr_domain.weeks import IsoWeek


class OffPlanOccupancy:
    """The off-plan spans overlapping one week, as the denominator's fourth subtrahend."""

    def __init__(self, periods: OffPlanPeriodRepository) -> None:
        self._periods = periods

    async def read(self, iso_week: IsoWeek, span: Interval) -> WeekOccupancy:
        """Every off-plan span reaching into ``span``, unioned. Writes nothing.

        ``iso_week`` is the identifier the caller resolved ``span`` from, and this reader has
        no use for it: a period is stored as instants, so the span is the whole question.
        """
        found = await self._periods.for_span(span)
        return WeekOccupancy(off_plan=IntervalSet(record.interval for record in found))
