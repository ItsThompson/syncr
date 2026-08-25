"""The nine figures the summary strip and the review both read, computed once on the server.

The strip shows three of them plus the verdict, and the pie review divides the same denominator.
Computing them in a client from the document would risk a figure on the strip disagreeing with the
same figure in a review, so they are computed here and only here.

## Where each figure comes from, and why the four budget ones are not the document's

``discretionary``, ``unallocated``, ``oversubscription`` and ``off_plan`` are taken from the BUDGET
REPORT, which is the one implementation of that arithmetic and the one the pie review divides. The
document carries three of them too, computed when the plan was produced, and those are as of that
instant: a period declared off-plan an hour later moves the real denominator and not the stored one.
Reading the report is therefore what makes the strip and the review agree by construction rather
than by a test, and it is why the wire document does not carry the stored three at all.

``scheduled``, ``block_count`` and ``unconfirmed_days`` are the document's, because no other shape
can answer them: they are facts about what the week holds. ``dropped_legs`` is the document's
for the same reason, and a figure rather than something a client counts out of the payload:
an absence explained on the grid is still one fact about the week.

## Three of the nine are worth stating exactly

``scheduled_minutes`` is a COVERAGE figure, unioned and clipped to the week. Unioned because a
minute the user deliberately double-booked is one scheduled minute rather than two, and clipped
because a Sunday-night routine running into Monday is scheduled time that belongs to next week.

``unconfirmed_days`` counts only the week's days that have ENDED, and only those holding a block. A
day the user cannot confirm yet is not outstanding, and a day with nothing on it has nothing to
confirm: counting either would make the figure nag about work nobody owes.

``plan_currency`` is derived from the week's operation state, in ``currency.py``, so the strip's
sub-line and the operation resource cannot disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_domain.gaps import EmptySlotReason
from syncr_domain.intervals import IntervalSet
from syncr_domain.weeks import local_days

if TYPE_CHECKING:
    from collections.abc import Collection
    from datetime import datetime

    from syncr_api.offplan.reading import OffPlanReading
    from syncr_api.plans.currency import PlanCurrency
    from syncr_domain.budgets import BudgetReport
    from syncr_domain.intervals import Interval
    from syncr_domain.plan import PlanDocument
    from syncr_domain.zones import Date


@dataclass(frozen=True, slots=True)
class WeekReadings:
    """The strip's three readings, its sub-line, and the four figures beside them."""

    scheduled_minutes: int
    discretionary_minutes: int
    unallocated_minutes: int
    oversubscription_minutes: int
    unconfirmed_days: int
    off_plan_minutes: int
    block_count: int
    dropped_legs: int
    plan_currency: PlanCurrency


def week_readings(
    document: PlanDocument,
    *,
    span: Interval,
    report: BudgetReport,
    off_plan: OffPlanReading,
    confirmed: Collection[Date],
    now: datetime,
    currency: PlanCurrency,
) -> WeekReadings:
    """Every reading for one week that holds a plan."""
    return WeekReadings(
        scheduled_minutes=scheduled_minutes(document, span),
        discretionary_minutes=report.discretionary_minutes,
        unallocated_minutes=report.unallocated_minutes,
        oversubscription_minutes=report.oversubscription_minutes,
        unconfirmed_days=unconfirmed_days(document, span=span, confirmed=confirmed, now=now),
        off_plan_minutes=off_plan.minutes,
        block_count=len(document.blocks),
        dropped_legs=sum(
            1 for slot in document.empty_slots if slot.reason is EmptySlotReason.DROPPED_LEG
        ),
        plan_currency=currency,
    )


def scheduled_minutes(document: PlanDocument, span: Interval) -> int:
    """Minutes of the week that hold a block, counting a double-booked minute once."""
    return IntervalSet(block.interval for block in document.blocks).clip(span).total_minutes()


def unconfirmed_days(
    document: PlanDocument, *, span: Interval, confirmed: Collection[Date], now: datetime
) -> int:
    """The week's ended days that hold a block and that the user has not confirmed.

    The days are bounded by the document's own zone mapping, so a date is as long as it really was:
    a spring-forward date is 23 hours and a travel boundary makes one 14. That mapping was captured
    when the plan was produced, which is also what the grid draws the day columns from, so the day a
    figure is charged to is the day the reader sees.

    **The span is live and the mapping is stored, and they can disagree.** A travel override
    declared after the plan was produced moves the week's real bounds relative to the dates the
    document captured. ``local_days`` clips every day to the span and drops one whose bounds do not
    run forward, so the disagreement costs a day rather than a fault, and charging the figure to the
    day the grid draws is the reading a person can check.
    """
    return sum(
        1
        for day in local_days(document.iso_week, document.zone_by_date, span)
        if day.interval.end <= now
        and day.on not in confirmed
        and any(block.interval.overlaps(day.interval) for block in document.blocks)
    )
