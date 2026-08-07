"""The wire shapes the week routes answer with.

``WeekViewResponse`` is section 13's ``WeekView``, field for field, so the generated TypeScript
needs no hand-written companion type. The document it carries is ``document_schemas.py``, the diff
is ``proposal_schemas.py``, and the verdict is ``verdict_schemas.py``.

**Six fields that shipped present-and-always-empty now carry what they name**: the verdict, the
pending proposal, the candidate concession, the approved concessions, the pins, and the conflicts.
The contract's SHAPE is what did not change, which is what the placeholders were for.

**Each of the six reuses the wire shape its owning module already declares.** A concession, a pin
and a conflict each cross the wire from a route of their own as well as from here, and a second
declaration of any of them is how two surfaces would come to render one value differently.

**``emptyReason`` is a word and ``emptyWeek`` is the facts.** The word is the closed vocabulary the
screen has an empty state for; the object beside it carries what the two actions need, which no
field of section 13's interface can hold: which input is missing, how long the horizon is, and
whether it reaches this week.

**Every duration is integer minutes**, which is this api's convention throughout: never a string and
never a float, so a client can add two of them without narrowing anything first.
"""

from __future__ import annotations

from datetime import date, datetime  # noqa: TC003 - pydantic resolves annotations at runtime
from typing import TYPE_CHECKING, Self
from uuid import UUID  # noqa: TC003 - as above

from pydantic import Field

# Runtime imports, every one of them: pydantic resolves a field's annotation while the app is being
# built, so a nested model or a closed vocabulary named in one has to be importable then. Ruff
# cannot see that ``WireModel`` extends ``BaseModel`` from another module, so each import says so.
from syncr_api.concessions.schemas import AdjustmentResponse
from syncr_api.conflicts.schemas import ConflictResponse
from syncr_api.core.schemas import WireModel, WireSpan
from syncr_api.offplan.schemas import OffPlanPeriodResponse
from syncr_api.pins.schemas import PinResponse
from syncr_api.plans.config import RevisionReason, RevisionStatus  # noqa: TC001
from syncr_api.plans.currency import PlanCurrency  # noqa: TC001
from syncr_api.plans.document_schemas import PlanDocumentResponse
from syncr_api.plans.emptiness import EmptyReason  # noqa: TC001
from syncr_api.plans.proposal_schemas import ProposalDiffResponse
from syncr_api.plans.verdict_schemas import VerdictResponse
from syncr_api.solving.schemas import OperationResponse

if TYPE_CHECKING:
    from syncr_api.plans.emptiness import EmptyWeek
    from syncr_api.plans.readings import WeekReadings
    from syncr_api.plans.week_views import WeekRevision, WeekRevisions, WeekView
    from syncr_domain.feasibility import Verdict


class WeekReadingsResponse(WireModel):
    """The three readings the summary strip shows, its sub-line, and the four beside them."""

    scheduled_minutes: int = Field(
        description="Minutes of the week that hold a block. Unioned, so a minute the user "
        "deliberately double-booked counts once, and clipped to the week, so a Sunday-night "
        "routine running into Monday is not charged here twice."
    )
    discretionary_minutes: int = Field(
        description="The denominator the STRIP renders. Today it is the week's span less the "
        "interval union of off-plan periods alone: the occupancy reader behind it does not yet "
        "subtract the circadian frame, external anchors or absolutely forbidden windows, so on a "
        "week with a frame it reads high by the whole of it. verdict.discretionaryMinutes is the "
        "same quantity with all four subtracted and is the authoritative one until this reader "
        "catches up. Never scheduled time."
    )
    unallocated_minutes: int = Field(
        description="Discretionary minutes covered by NO block carrying an Area. Never negative, "
        "and not zero merely because the declared shares sum to 100. The same figure the budget "
        "report carries, from the same arithmetic."
    )
    oversubscription_minutes: int = Field(
        description="How far the Area targets exceed discretionary time. Zero when they fit. A "
        "separate quantity from unallocatedMinutes, and never rendered as a negative one."
    )
    unconfirmed_days: int = Field(
        description="Days of this week that have ended, hold at least one block, and have not "
        "been confirmed. A day still ahead cannot be confirmed and is not counted."
    )
    off_plan_minutes: int = Field(
        description="How many of the week's minutes were declared off-plan. Already subtracted "
        "from discretionaryMinutes, so this explains the denominator rather than reducing it "
        "again."
    )
    block_count: int = Field(description="How many blocks the plan holds.")
    plan_currency: PlanCurrency = Field(
        description="Whether the block count is current, being recomputed, or the last one that "
        "worked. Derived from the week's own operation state, so this and the operation resource "
        "cannot disagree."
    )

    @classmethod
    def of(cls, readings: WeekReadings) -> Self:
        return cls(
            scheduled_minutes=readings.scheduled_minutes,
            discretionary_minutes=readings.discretionary_minutes,
            unallocated_minutes=readings.unallocated_minutes,
            oversubscription_minutes=readings.oversubscription_minutes,
            unconfirmed_days=readings.unconfirmed_days,
            off_plan_minutes=readings.off_plan_minutes,
            block_count=readings.block_count,
            plan_currency=readings.plan_currency,
        )


class EmptyWeekResponse(WireModel):
    """Why a week holds no plan, and what the screen's two actions need to be offered."""

    statement: str = Field(
        description="One sentence naming why this week holds no plan and what still works, "
        "composed here so two surfaces cannot word it differently."
    )
    missing_inputs: list[str] = Field(
        description="Which minimum inputs the tenant has not declared, in setup order. Empty "
        "unless emptyReason is setup_incomplete."
    )
    horizon_days: int = Field(description="How many days ahead the projection horizon reaches.")
    horizon_through: date = Field(
        description="The last local date the horizon covers, which is the date the statement names."
    )
    covers_this_week: bool = Field(
        description="Whether the horizon reaches this week. False means extending it brings the "
        "week in; true means the week is inside it and its plan has not been produced yet."
    )

    @classmethod
    def of(cls, empty: EmptyWeek) -> Self:
        return cls(
            statement=empty.statement,
            missing_inputs=[missing.value for missing in empty.missing],
            horizon_days=empty.horizon.days,
            horizon_through=empty.horizon.through,
            covers_this_week=empty.covers_this_week,
        )


class WeekViewResponse(WireModel):
    """The Week screen's whole read, in one request.

    **Every field is required and the nullable ones are nullable**, which is section 13's own shape
    and the one thirty-six other response fields in this api already take. A field with a default is
    OPTIONAL in the generated document, so a client would have to narrow ``undefined`` as well as
    ``null`` and ``if (view.emptyReason === null)`` would not be sound against its own types. The
    server populates all sixteen on every answer, so the contract says so.
    """

    iso_week: str
    span: WireSpan = Field(
        description="The week's real span. 167 or 169 hours across a daylight-saving transition, "
        "and something else again across a travel boundary."
    )
    zone_by_date: dict[str, str] = Field(
        description="The zone active on each of the week's dates NOW, keyed by ISO date. The "
        "mapping inside live is the one captured when the plan was produced, and the two differ "
        "wherever a travel override was declared afterwards."
    )
    live: PlanDocumentResponse | None = Field(
        description="The plan of record for this week, or null when none exists. A read never "
        "produces one: navigating between weeks is not a mutation.",
    )
    empty_reason: EmptyReason | None = Field(
        description="Why live is null. Null exactly when live is populated."
    )
    empty_week: EmptyWeekResponse | None = Field(
        description="The facts behind emptyReason. Null exactly when live is populated.",
    )
    proposal: ProposalDiffResponse | None = Field(
        description="The changes this week is proposing and waiting for assent to, or null when "
        "its slot is empty. What the grid renders proposal targets from. Rendered whether or not "
        "the slot is current, because approval is never blocked; the version it was solved "
        "against is not on this response, so a client that needs to know whether these targets "
        "were computed against the state it is looking at reads the proposal route."
    )
    candidate_adjustment: AdjustmentResponse | None = Field(
        description="The concession the pending proposal was solved under, awaiting approval, or "
        "null. Not persisted until the proposal is approved, and it carries the identifier the "
        "approval will persist it under.",
    )
    adjustments: list[AdjustmentResponse] = Field(
        description="The approved concessions this week holds, in the order the assembler folds "
        "them. Listed above the verdict's shortfalls, so a week that has absorbed a concession "
        "does not read as simply feasible.",
    )
    pins: list[PinResponse] = Field(
        description="The user's own placements for this week, each with what the solver had chosen "
        "instead and what overriding it cost. Pins do not carry forward to the next week."
    )
    conflicts: list[ConflictResponse] = Field(
        description="Every overlap raised in this week, answered ones included: the open ones hold "
        "a banner and the answered ones are what a repeated collision is computed over.",
    )
    verdict: VerdictResponse | None = Field(
        description="Whether this week can hold its commitments, and by how much it cannot. Null "
        "exactly when live is null. Its provenance is solver while the week holds a current "
        "proposal, because that is the only place an attempted placement's finding is kept."
    )
    off_plan: list[OffPlanPeriodResponse] = Field(
        description="Every declared off-plan span reaching into this week, unclipped, so a "
        "Friday-to-Monday span reads the same in both weeks it touches.",
    )
    operation: OperationResponse | None = Field(
        description="The non-terminal solve or materialize for this week, if one is in flight. "
        "Either changes what the grid holds, and the field exists so a client knows what to follow."
    )
    input_version: int = Field(
        description="The week's input counter, for optimistic client reasoning. Zero when nothing "
        "has referenced the week yet: versions start at one."
    )
    readings: WeekReadingsResponse | None = Field(
        description="The strip's figures. Null exactly when live is null."
    )

    @classmethod
    def of(cls, view: WeekView) -> Self:
        """The wire shape of one composed week.

        The zone mapping is emitted in date order, so two reads of one week are byte-identical.

        Every field is passed explicitly rather than defaulted, so what a payload carries is a
        statement at the one place the response is built rather than a property of the schema.
        """
        return cls(
            iso_week=str(view.iso_week),
            span=WireSpan.of(view.span),
            zone_by_date={day.isoformat(): zone for day, zone in sorted(view.zone_by_date.items())},
            live=None if view.live is None else PlanDocumentResponse.of(view.live),
            empty_reason=None if view.empty is None else view.empty.reason,
            empty_week=None if view.empty is None else EmptyWeekResponse.of(view.empty),
            proposal=(None if view.proposal is None else ProposalDiffResponse.of(view.proposal)),
            candidate_adjustment=(
                None
                if view.candidate_adjustment is None
                else AdjustmentResponse.of(view.candidate_adjustment)
            ),
            adjustments=[AdjustmentResponse.of(one) for one in view.adjustments],
            pins=[PinResponse.of(one) for one in view.pins],
            conflicts=[ConflictResponse.of(one) for one in view.conflicts],
            verdict=None if view.verdict is None else VerdictResponse.of(view.verdict),
            off_plan=[OffPlanPeriodResponse.of(period) for period in view.off_plan],
            operation=None if view.operation is None else OperationResponse.of(view.operation),
            input_version=view.input_version,
            readings=None if view.readings is None else WeekReadingsResponse.of(view.readings),
        )


class WeekRevisionResponse(WireModel):
    """One appended revision of a week's plan, as the history lists it."""

    id: UUID
    created_at: datetime = Field(description="When the revision was appended.")
    status: RevisionStatus = Field(
        description="Whether the authority rule applied it or the user assented to it."
    )
    reason: RevisionReason = Field(description="What caused this revision to exist.")
    approved_at: datetime | None = Field(
        description="When the user assented. Null for an applied revision."
    )
    input_version: int = Field(description="The input snapshot the revision was produced from.")
    auto_applied: list[str] = Field(
        description="What this revision added without asking, by block title. Empty for an "
        "approved revision, whose changes the user assented to, and empty for the first plan a "
        "week ever had, which added everything."
    )
    adjustments: list[AdjustmentResponse] = Field(
        description="The approved concessions this plan was solved under, so a week never reads as "
        "feasible for a reason the user cannot see."
    )
    unnamed_adjustments: int = Field(
        description="How many concessions this plan was solved under the week no longer holds "
        "under that identifier, and so cannot be named: revoked, or replaced by a later "
        "concession of the same kind and target. Zero when the week still holds all of them."
    )

    @classmethod
    def of(cls, revision: WeekRevision) -> Self:
        record = revision.record
        return cls(
            id=record.id,
            created_at=record.created_at,
            status=record.status,
            reason=record.reason,
            approved_at=record.approved_at,
            input_version=record.input_version,
            auto_applied=list(revision.auto_applied),
            adjustments=[AdjustmentResponse.of(one) for one in revision.adjustments],
            unnamed_adjustments=revision.unnamed_adjustments,
        )


class WeekRevisionsResponse(WireModel):
    """One week's revision history, newest first. Read-only: no route mutates a revision.

    ``truncated`` exists because the page is bounded and a bounded page that says nothing about its
    bound is a partial history a client cannot tell from a whole one. There is no cursor: what this
    answers is the recent history of one week, and paging back through a year of it is the weekly
    review's question rather than this route's.
    """

    revisions: list[WeekRevisionResponse]
    truncated: bool = Field(
        description="Whether the week has more revisions than this page holds. True means the "
        "oldest are not here."
    )

    @classmethod
    def of(cls, page: WeekRevisions) -> Self:
        return cls(
            revisions=[WeekRevisionResponse.of(one) for one in page.revisions],
            truncated=page.truncated,
        )


class WeekVerdictResponse(WireModel):
    """The week's verdict alone, for a cheap refresh.

    The same rule the composed read serves, so the two cannot report different provenance for one
    week: the pending slot's verdict while its input version is current, and a live probe otherwise.

    Null exactly when the week holds no plan, which is the biconditional the composed read states.

    This read writes nothing at all: no ``VerdictEvent`` is appended by any read path.
    """

    verdict: VerdictResponse | None = Field(
        description="The week's verdict, or null when the week holds no plan. Reading it appends "
        "no transition: a read computes a verdict for display and records nothing."
    )

    @classmethod
    def of(cls, verdict: Verdict | None) -> Self:
        return cls(verdict=None if verdict is None else VerdictResponse.of(verdict))
