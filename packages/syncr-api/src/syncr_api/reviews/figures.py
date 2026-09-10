"""One reviewed week's figures, stated once so the trend, the pie and the proposal share them.

Three consumers ask the same four questions of a week: what did each Area get, what did each
Area's target work out to, what did no block cover, and how far past the denominator do the targets
reach. Answering them in the reading and again in the proposal is exactly how the trend's bar and
the proposal's observed column would come to disagree about one week.

Every answer is ``syncr_domain``'s arithmetic. What this module holds is the one place a week with
no plan of record is turned into ``None`` rather than into a figure: a target divides discretionary
time, and a week nobody planned has none to divide.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from syncr_api.reviews.coverage import claimed
from syncr_domain.budget_review import WHOLE_SHARE
from syncr_domain.budgets import (
    minutes_after_floors,
    oversubscription_minutes,
    target_minutes,
    unallocated_minutes,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syncr_api.reviews.history import ReviewedWeek
    from syncr_domain.budgets import AreaShare
    from syncr_domain.identifiers import AreaId


def actual_minutes(week: ReviewedWeek, area_id: AreaId) -> int:
    """The minutes this Area's blocks really occupied on the week's confirmed days."""
    found = week.covered.get(area_id)
    return 0 if found is None else found.total_minutes()


def vacancy_minutes(week: ReviewedWeek) -> int | None:
    """Discretionary minutes no confirmed block covered, or ``None`` with no plan of record."""
    if week.discretionary_minutes is None:
        return None
    return unallocated_minutes(week.discretionary, claimed(week.covered))


def targets(week: ReviewedWeek, shares: Sequence[AreaShare]) -> dict[AreaId, int]:
    """Each Area's target against this week's own denominator, or none at all without one."""
    if week.discretionary_minutes is None:
        return {}
    after_floors = minutes_after_floors(week.discretionary_minutes, shares)
    return {share.area_id: target_minutes(share, after_floors=after_floors) for share in shares}


def vacancy_target(week: ReviewedWeek, declared: Mapping[AreaId, int]) -> int | None:
    """The minutes the Areas' own targets leave, which is what the vacancy is measured against."""
    if week.discretionary_minutes is None:
        return None
    return max(0, week.discretionary_minutes - sum(declared.values()))


def oversubscription(week: ReviewedWeek, shares: Sequence[AreaShare]) -> int | None:
    """How far the Areas' targets exceed this week's discretionary time. Its own named quantity."""
    if week.discretionary_minutes is None:
        return None
    return oversubscription_minutes(targets(week, shares).values(), week.discretionary_minutes)


def vacancy_share(shares: Sequence[AreaShare]) -> Decimal:
    """The share of the whole the Areas have not claimed, which is the vacancy's target share.

    Zero rather than negative when the Areas claim more than the whole. An oversubscribed budget is
    accepted and reported as its own quantity, so the vacancy it leaves is none rather than a debt.
    """
    declared = sum((share.budget_percent for share in shares), Decimal(0))
    return max(Decimal(0), WHOLE_SHARE - declared)
