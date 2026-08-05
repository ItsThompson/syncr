"""The wire shapes the week routes answer with.

``WeekViewResponse`` is section 13's ``WeekView``, field for field, so the generated TypeScript
needs no hand-written companion type. The document it carries is ``document_schemas.py``.

**Five fields are present and always empty**, because the components that populate them do not
exist yet: the verdict, the pending proposal, the candidate concession, the approved concessions,
the pins, and the conflicts. Present rather than omitted, so the contract the frontend generates
is the contract the screen will read, and a client written against it needs no change when each is
filled. Each says so on itself.

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
from syncr_api.concessions.schemas import AdjustmentResponse  # noqa: TC001
from syncr_api.core.schemas import WireModel, WireSpan
from syncr_api.offplan.schemas import OffPlanPeriodResponse  # noqa: TC001
from syncr_api.plans.config import RevisionReason, RevisionStatus  # noqa: TC001
from syncr_api.plans.currency import PlanCurrency  # noqa: TC001
from syncr_api.plans.document_schemas import PlanDocumentResponse  # noqa: TC001
from syncr_api.plans.emptiness import EmptyReason  # noqa: TC001
from syncr_api.solving.schemas import OperationResponse  # noqa: TC001

if TYPE_CHECKING:
    from syncr_api.plans.emptiness import EmptyWeek
    from syncr_api.plans.readings import WeekReadings
    from syncr_api.plans.records import PlanRevisionRecord


class WeekReadingsResponse(WireModel):
    """The three readings the summary strip shows, its sub-line, and the four beside them."""

    scheduled_minutes: int = Field(
        description="Minutes of the week that hold a block. Unioned, so a minute the user "
        "deliberately double-booked counts once, and clipped to the week, so a Sunday-night "
        "routine running into Monday is not charged here twice."
    )
    discretionary_minutes: int = Field(
        description="The denominator every percentage is measured against: the week's span less "
        "the interval union of the circadian frame, external anchors, absolutely forbidden "
        "windows, and off-plan periods. Never scheduled time."
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
    """The Week screen's whole read, in one request."""

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
        default=None,
        description="The plan of record for this week, or null when none exists. A read never "
        "produces one: navigating between weeks is not a mutation.",
    )
    empty_reason: EmptyReason | None = Field(
        default=None, description="Why live is null. Null exactly when live is populated."
    )
    empty_week: EmptyWeekResponse | None = Field(
        default=None,
        description="The facts behind emptyReason. Null exactly when live is populated.",
    )
    # Ticket 44 wires the verdict, the proposal, the candidate concession, the approved
    # concessions, the pins, and the conflicts into this response. Each field ships now, always
    # null or empty, so the generated contract does not change shape when they are filled.
    proposal: None = Field(
        default=None, description="Always null: nothing produces a proposal in this deployment."
    )
    candidate_adjustment: AdjustmentResponse | None = Field(
        default=None,
        description="Always null: a candidate concession rides on an operation and is not read "
        "back into this view yet.",
    )
    adjustments: list[AdjustmentResponse] = Field(
        default_factory=list,
        description="Always empty: the concessions a week holds are read through the adjustments "
        "route in this deployment.",
    )
    pins: list[None] = Field(
        default_factory=list, description="Always empty: nothing records a pin in this deployment."
    )
    conflicts: list[None] = Field(
        default_factory=list,
        description="Always empty: nothing records a conflict in this deployment.",
    )
    verdict: None = Field(
        default=None, description="Always null: no read computes a verdict in this deployment."
    )
    off_plan: list[OffPlanPeriodResponse] = Field(
        default_factory=list,
        description="Every declared off-plan span reaching into this week, unclipped, so a "
        "Friday-to-Monday span reads the same in both weeks it touches.",
    )
    operation: OperationResponse | None = Field(
        default=None, description="The non-terminal solve for this week, if one is in flight."
    )
    input_version: int = Field(
        description="The week's input counter, for optimistic client reasoning. Zero when nothing "
        "has referenced the week yet: versions start at one."
    )
    readings: WeekReadingsResponse | None = Field(
        default=None, description="The strip's figures. Null exactly when live is null."
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
        default=None, description="When the user assented. Null for an applied revision."
    )
    input_version: int = Field(description="The input snapshot the revision was produced from.")

    @classmethod
    def of(cls, record: PlanRevisionRecord) -> Self:
        return cls(
            id=record.id,
            created_at=record.created_at,
            status=record.status,
            reason=record.reason,
            approved_at=record.approved_at,
            input_version=record.input_version,
        )


class WeekRevisionsResponse(WireModel):
    """One week's revision history, newest first. Read-only: no route mutates a revision."""

    revisions: list[WeekRevisionResponse]


class WeekVerdictResponse(WireModel):
    """The week's verdict alone, for a cheap refresh.

    Always null, and this read writes nothing at all: no ``VerdictEvent`` is appended by any read
    path. Ticket 44 supplies the verdict, and ticket 43 owns the only writer of a transition.
    """

    verdict: None = Field(
        default=None, description="Always null: no read computes a verdict in this deployment."
    )
