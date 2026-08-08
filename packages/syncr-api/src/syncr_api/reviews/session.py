"""The weekly session's reading: last week's retrospective, next week's raises, and the verdict.

``US-REV-01``: planning and retrospective happen in one pass, so last week informs next week without
a second sitting. That is why one payload carries both halves, and why the week it is addressed by
is the week being PLANNED: the retrospective covers the week before it.

**Nothing here writes.** No revision, no operation, no version bump, and no ``VerdictEvent``. The
verdict on this payload is computed the same way the Week screen's is, through the same
collaborator, and ``VE6`` forbids a read from recording the transition it observes. That rule is
enforced by a guard stated over the response shapes that carry a verdict rather than over a list of
paths, so this payload came under it the moment it declared the field.

**Every figure is someone else's arithmetic.** The retrospective's actual-against-target is the pie
review's ``categories_of``; the verdict and the concessions are the week view's; an at-risk task is
``plans.at_risk``'s determination. A second arithmetic anywhere here would be the one that quietly
disagreed with the screen the user was looking at ten seconds earlier.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_api.offplan.reading import OffPlanReading
    from syncr_api.plans.records import WeekAdjustmentRecord
    from syncr_api.reviews.coverage import DayCounts
    from syncr_api.reviews.raised import RaisedItem
    from syncr_api.reviews.readings import CategoryReading
    from syncr_domain.feasibility import Verdict
    from syncr_domain.intervals import Interval
    from syncr_domain.promotion import PromotionCandidate
    from syncr_domain.weeks import IsoWeek


@dataclass(frozen=True, slots=True, kw_only=True)
class SessionRetro:
    """Last week, as the session reports it.

    ``discretionary_minutes`` is the reviewed week's own stored figure, or ``None`` when that week
    held no plan of record: a target divides a denominator such a week does not have.

    ``days`` is what ``US-REV-04`` asks for, and the three counts are three quantities. Off-plan
    days are reported separately from unconfirmed ones, because a day the user declared away is not
    a day they failed to answer for."""

    iso_week: IsoWeek
    span: Interval
    discretionary_minutes: int | None
    days: DayCounts
    off_plan: OffPlanReading
    categories: tuple[CategoryReading, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class WeeklySessionReading:
    """One weekly session: the week it plans, the week it reviews, and everything raised between.

    ``verdict`` and ``concessions`` are the week being planned, not the week under review. The
    session is a planning surface first: the retrospective is what informs it, and the verdict is
    what the one approve action is taken against.

    ``verdict`` is ``None`` exactly when the planned week holds no plan, which is the same
    biconditional the week's own read states: nothing has been computed about such a week, so a
    verdict beside it would be a claim about nothing.
    """

    iso_week: IsoWeek
    span: Interval
    retro: SessionRetro
    raised: tuple[RaisedItem, ...]
    verdict: Verdict | None
    concessions: Sequence[WeekAdjustmentRecord]
    promotions: tuple[PromotionCandidate, ...]
    input_version: int
