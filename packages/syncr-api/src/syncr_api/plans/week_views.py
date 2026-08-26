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
    from uuid import UUID

    from syncr_api.offplan.records import OffPlanPeriodRecord
    from syncr_api.plans.anchor_origins import AnchorOrigin
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
    from syncr_domain.identifiers import AreaId, OperationId
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
    whenever it holds something.

    The pair a week holding a slot and no revision would produce is unreachable **structurally**
    rather than by observation: ``PlanAdoption._replaced`` fills the slot only when the
    classification's diff is non-empty, and a diff against a week with no live plan holds nothing
    but additions, every one of which is a fill the authority rule applies without asking. So a
    first solve of a planless week appends a revision and leaves the slot alone, and nothing gates
    the two fields together because no state exercises the asymmetry.

    ``area_names`` names every Area this tenant holds. The plan charges its blocks and its gaps to
    Areas by identifier and a name is the user's own word for one, so the words travel beside the
    document rather than inside it: one read of the rows names every gap in the week.

    ``anchor_origins`` names, per imported commitment the week binds, the calendar feed it came
    from and whether that feed is failing now. It travels beside the document for the same reason:
    one read of each of the two tables answers every block, and the staleness threshold stays on
    this side of the wire.
    """

    iso_week: IsoWeek
    span: Interval
    zone_by_date: Mapping[Date, ZoneId]
    live: PlanDocument | None
    area_names: Mapping[AreaId, str]
    anchor_origins: Mapping[UUID, AnchorOrigin]
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

    Both versions travel, because a proposal may be approved while it is behind. ``input_version``
    is the state the proposal was SOLVED against, so a client comparing it with the week's own can
    see that the week moved on while this proposal waited, which is permitted and is what makes
    approval never blocked.
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
class UnnamedConcessions:
    """How many concessions a revision cannot name, split by what the week did to each.

    ``revoked`` is one whose row is gone. ``replaced`` is one a later approval for the same kind and
    target took over: that write keeps the replaced row's identifier, so the document beside it
    names an identifier no row carries, while the concession itself is still in force.

    Separate because the two are different facts about the week. A revoked concession no longer
    applies to anything; a replaced one applies under a name this revision does not use.

    The pair is built to sum to how many identifiers a document names that the week does not hold.
    That is established where the pair is computed, in :mod:`syncr_api.plans.history`, rather than
    here: this type holds two counts and enforces nothing about them.
    """

    revoked: int
    replaced: int


@dataclass(frozen=True, slots=True)
class WeekRevision:
    """One revision as the history lists it, and the two things its own row cannot say.

    ``auto_applied`` names what this revision added without asking, which is a difference between
    two revisions rather than a column. ``adjustments`` names the concessions the plan was solved
    under, which the document holds by identifier, and ``unnamed`` counts the ones the week no
    longer holds under that identifier, so a plan is never reported as conceded less than it was.
    """

    record: PlanRevisionRecord
    auto_applied: tuple[str, ...]
    adjustments: tuple[WeekAdjustmentRecord, ...]
    unnamed: UnnamedConcessions


@dataclass(frozen=True, slots=True)
class WeekRevisions:
    """One page of a week's history, and whether the week holds more than the page.

    The pair travels together because a bounded page that does not say it is bounded is a partial
    history a client cannot tell from a whole one.
    """

    revisions: Sequence[WeekRevision]
    truncated: bool
