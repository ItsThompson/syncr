"""The shapes the week service answers with, beside the service rather than inside it.

A composed read has a return type, and a wire schema has to name it. Keeping these in ``service.py``
would make ``schemas.py`` import a service module to describe a response, which is the dependency
running the wrong way: a schema describes a value, and the value is what the service produces.

None carries behaviour. They are what the routes map onto the wire, and every figure on them was
computed by the modules named beside their fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime

    from syncr_api.offplan.records import OffPlanPeriodRecord
    from syncr_api.plans.emptiness import EmptyWeek
    from syncr_api.plans.readings import WeekReadings
    from syncr_api.plans.records import (
        ConflictRecord,
        PinRecord,
        PlanRevisionRecord,
        WeekAdjustmentRecord,
    )
    from syncr_api.solving.records import OperationRecord
    from syncr_domain.feasibility import Verdict
    from syncr_domain.identifiers import OperationId
    from syncr_domain.intervals import Interval
    from syncr_domain.plan import PlanDocument
    from syncr_domain.proposals import ProposalDiff
    from syncr_domain.weeks import IsoWeek
    from syncr_domain.zones import Date, ZoneId


@dataclass(frozen=True, slots=True)
class WeekView:
    """One week, composed: the plan or the reason there is none, and the figures beside it.

    **``verdict`` is gated on the plan and ``proposal`` is not**, which is deliberate and not an
    oversight. A verdict is a claim ABOUT a plan, so a week holding none has none. A proposal is a
    difference the solver wants applied, and approval is never blocked, so a slot is rendered
    whenever it holds something. The pair a week holding a slot and no revision would produce is
    unreachable through the shipped routes -- a first solve of a planless week proposes nothing,
    because an addition into free time auto-applies -- so nothing gates the two together and no
    state exercises the asymmetry.
    """

    iso_week: IsoWeek
    span: Interval
    zone_by_date: Mapping[Date, ZoneId]
    live: PlanDocument | None
    empty: EmptyWeek | None
    proposal: ProposalDiff | None
    candidate_adjustment: WeekAdjustmentRecord | None
    adjustments: Sequence[WeekAdjustmentRecord]
    pins: Sequence[PinRecord]
    conflicts: Sequence[ConflictRecord]
    off_plan: Sequence[OffPlanPeriodRecord]
    verdict: Verdict | None
    operation: OperationRecord | None
    input_version: int
    readings: WeekReadings | None


@dataclass(frozen=True, slots=True)
class PendingProposal:
    """The proposal a week is holding, as its own route answers with it.

    **The candidate plan document is deliberately absent.** A proposal IS the difference between
    the live plan and a candidate, and the difference is what the grid renders proposal targets
    from: the live plan is already on the week view beside it, so carrying the whole candidate week
    would put a second document in a payload whose reader has one.

    Both versions travel, and that is ``PP5`` from the read side. ``input_version`` is the state the
    proposal was SOLVED against, so a client comparing it with the week's own can see that the week
    moved on while this proposal waited, which is permitted and is what makes approval never
    blocked.
    """

    iso_week: IsoWeek
    diff: ProposalDiff
    verdict: Verdict
    candidate_adjustment: WeekAdjustmentRecord | None
    input_version: int
    weight_set_version: int
    operation_id: OperationId
    created_at: datetime


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
