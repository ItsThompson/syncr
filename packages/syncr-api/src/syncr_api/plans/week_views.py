"""The two shapes the week service answers with, beside the service rather than inside it.

A composed read has a return type, and a wire schema has to name it. Keeping these in ``service.py``
would make ``schemas.py`` import a service module to describe a response, which is the dependency
running the wrong way: a schema describes a value, and the value is what the service produces.

Neither carries behaviour. They are what the routes map onto the wire, and every figure on them was
computed by the modules named beside their fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syncr_api.offplan.records import OffPlanPeriodRecord
    from syncr_api.plans.emptiness import EmptyWeek
    from syncr_api.plans.readings import WeekReadings
    from syncr_api.plans.records import PlanRevisionRecord, WeekAdjustmentRecord
    from syncr_api.solving.records import OperationRecord
    from syncr_domain.intervals import Interval
    from syncr_domain.plan import PlanDocument
    from syncr_domain.weeks import IsoWeek
    from syncr_domain.zones import Date, ZoneId


@dataclass(frozen=True, slots=True)
class WeekView:
    """One week, composed: the plan or the reason there is none, and the figures beside it."""

    iso_week: IsoWeek
    span: Interval
    zone_by_date: Mapping[Date, ZoneId]
    live: PlanDocument | None
    empty: EmptyWeek | None
    off_plan: Sequence[OffPlanPeriodRecord]
    operation: OperationRecord | None
    input_version: int
    readings: WeekReadings | None


@dataclass(frozen=True, slots=True)
class WeekRevision:
    """One revision as the history lists it, and the two things its own row cannot say.

    ``auto_applied`` names what this revision added without asking, which is a difference between
    two revisions rather than a column. ``adjustments`` names the concessions the plan was solved
    under, which the document holds by identifier, and ``unnamed_adjustments`` counts the ones the
    week no longer holds, so a plan is never reported as conceded less than it was.
    """

    record: PlanRevisionRecord
    auto_applied: tuple[str, ...]
    adjustments: tuple[WeekAdjustmentRecord, ...]
    unnamed_adjustments: int


@dataclass(frozen=True, slots=True)
class WeekRevisions:
    """One page of a week's history, and whether the week holds more than the page.

    The pair travels together because a bounded page that does not say it is bounded is a partial
    history a client cannot tell from a whole one.
    """

    revisions: Sequence[WeekRevision]
    truncated: bool
