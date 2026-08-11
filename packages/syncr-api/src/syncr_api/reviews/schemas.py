"""The wire shapes the two pie-review routes exchange.

Every duration is integer minutes, which is section 13's convention throughout, so a client can add
two of them without narrowing anything first. Every share is a percentage of discretionary time,
never of scheduled time: measuring against scheduled time would inflate every Area's share by
excluding exactly the hours nobody planned.

Four properties are stated in the field descriptions rather than only here, because the descriptions
reach the OpenAPI document and therefore the caller.

**A null ``areaId`` is the vacancy, not a missing Area.** Discretionary time no confirmed block
covered is a first-class category: a wedge on the pie, a row in the deviation bars, and a row of the
proposal. It is never rendered as a negative Area figure, and ``oversubscriptionMinutes`` is the
other quantity, reported separately.

**``discretionaryMinutes`` and the two residuals are null together.** They are null exactly when the
named week holds no plan of record: there is no denominator, so nothing derived from one exists
either. ``statement`` says which, so a row of nulls has one reading rather than two.

**No Area name appears here.** This is arithmetic over identifiers, and the names live on
``/api/v1/areas``, so a rename cannot make a cached review read as another Area's.

**Only confirmed days are in ``actualMinutes``, and off-plan spans are excluded entirely.** A day
nobody answered for contributes nothing, which is why the day counts travel beside every figure:
they are what tell the reader how much of the period the figures rest on.
"""

from __future__ import annotations

from uuid import UUID  # noqa: TC003 - pydantic resolves annotations at runtime

from pydantic import ConfigDict, Field

# `PeriodSpan` and `ProposalBasis` are referenced from field annotations, which pydantic resolves at
# RUNTIME to build the model, so under TYPE_CHECKING they would resolve to a NameError while the app
# is being constructed.
from syncr_api.areas.config import BUDGET_PERCENT_MAX, BUDGET_PERCENT_MIN
from syncr_api.budgets.schemas import PeriodSpan  # noqa: TC001
from syncr_api.core.schemas import WireDecimal, WireInstant, WireModel
from syncr_domain.budget_review import ProposalBasis  # noqa: TC001

_AREA_DESCRIPTION = (
    "The Area this row is about, or NULL for the vacancy: discretionary time covered by no block "
    "carrying an Area. The vacancy is a category rather than an absence, and it is never a "
    "negative Area figure."
)
_TARGET_DESCRIPTION = (
    "The Area's floor plus its share of the discretionary time its floors leave, for this week. "
    "Null when the week holds no plan of record, because a target divides a denominator that week "
    "does not have. For the vacancy it is what the Areas' own targets leave."
)
_ACTUAL_DESCRIPTION = (
    "Minutes this category really held, over the CONFIRMED days of the period only, with off-plan "
    "spans excluded entirely. A skipped block contributes nothing, a partial contributes the "
    "minutes it reported, and a moved block contributes the interval it happened in."
)


class ReviewDayCounts(WireModel):
    """How many of a period's days were answered for, left unanswered, and declared away.

    The three are separate quantities. Off-plan days are reported SEPARATELY from unconfirmed days
    because an off-plan day is one the user declared away rather than one they failed to answer for,
    and counting a holiday as a lapse is what US-REV-04 exists to prevent.

    They need not sum to the period's length: a day holding no block is none of the three, since
    there is nothing to answer for and counting it would report a backlog of days on which nothing
    was planned.
    """

    confirmed: int = Field(description="Days every block of which carries a confirmation.")
    unconfirmed: int = Field(
        description="Days holding blocks that have not been answered for. These contribute nothing "
        "to any figure in this payload."
    )
    off_plan: int = Field(
        description="Days covered end to end by a declared off-plan period. Not unconfirmed: there "
        "was nothing to answer for."
    )
    statement: str | None = Field(
        default=None,
        description="Why the charts for this period hold nothing, stated when no day of it was "
        "confirmed. Null otherwise.",
    )


class CategoryReadingResponse(WireModel):
    """One category's row: what it was allotted, and what it actually held."""

    area_id: UUID | None = Field(description=_AREA_DESCRIPTION)
    target_minutes: int | None = Field(description=_TARGET_DESCRIPTION)
    actual_minutes: int = Field(description=_ACTUAL_DESCRIPTION)


class TrendWeekResponse(WireModel):
    """One week of the trend, which renders as one stacked bar.

    Never a line: the Area ramp is sealed to a wedge fill and a bar fill, so a time series drawn as
    a line has no legal ink at all.
    """

    period: str = Field(description="The ISO week this bar covers, such as '2026-W07'.")
    slices: list[CategoryReadingResponse]
    days: ReviewDayCounts


class ProposedShareResponse(WireModel):
    """One row of the proposed revision: what is declared, what happened, and what to declare."""

    area_id: UUID | None = Field(description=_AREA_DESCRIPTION)
    declared_percent: WireDecimal = Field(
        description="The share this category declares now, which is what behaviour is compared "
        "against. For the vacancy it is the share the Areas have not claimed."
    )
    observed_percent: WireDecimal = Field(
        description="What this category actually held across the fully confirmed weeks, as a share "
        "of their discretionary time, to a tenth of a point."
    )
    proposed_percent: WireDecimal = Field(
        description="The share to declare: the declared one moved HALF the distance to the "
        "observed one, truncated, and bounded to 0..100. Half rather than the whole, because a "
        "budget that ratifies whatever happened cannot starve an Area, which is what it exists to "
        "prevent."
    )
    basis: ProposalBasis = Field(description="Why this row's proposal is what it is.")
    statement: str = Field(description="The same reason as a sentence, for a caller that renders.")


class BudgetProposalResponse(WireModel):
    """The proposed revision, or the count that says why there is not one yet.

    ``shares`` is empty exactly when ``confirmedWeeks`` is below ``requiredWeeks``. Both counts are
    present either way, because the count is the answer to "why is this empty" and a caller that had
    to infer it from an empty list would be inferring it.
    """

    confirmed_weeks: int = Field(
        description="How many weeks of the quarter were FULLY confirmed. A partly confirmed week "
        "is reported in the day counts but is not evidence: its actuals cover some days and its "
        "denominator covers all seven."
    )
    required_weeks: int = Field(
        description="How many fully confirmed weeks a proposal needs. A quarter, which is 13."
    )
    shares: list[ProposedShareResponse] = Field(
        description="One row per Area, then the vacancy. Empty until the quarter's worth of "
        "confirmed weeks exists."
    )
    statement: str = Field(
        description="What the proposal rests on, or how much evidence is missing. Always present: "
        "both readings are something the reader needs."
    )


class BudgetReviewResponse(WireModel):
    """One period's pie review: the figures, the categories, the trend, and the proposal."""

    period: str = Field(description="The ISO week the review is anchored at, such as '2026-W07'.")
    span: PeriodSpan
    discretionary_minutes: int | None = Field(
        description="The denominator every share here is measured against, taken from the week's "
        "own plan of record, which is the figure the week was solved against. Null when the week "
        "holds no plan."
    )
    unallocated_minutes: int | None = Field(
        description="Discretionary minutes covered by NO confirmed block carrying an Area. Never "
        "negative, and not zero merely because the shares sum to 100. Null with no plan of record."
    )
    oversubscription_minutes: int | None = Field(
        description="How far the Area targets exceed discretionary time. Zero when they fit. A "
        "SEPARATE quantity from unallocatedMinutes, and never rendered as a negative one. Null "
        "with no plan of record."
    )
    off_plan_minutes: int = Field(
        description="How many of the period's minutes were declared off-plan, clipped to the "
        "period."
    )
    off_plan_statement: str | None = Field(
        default=None,
        description="Why every figure above is zero, stated when the period was off-plan from end "
        "to end. Null otherwise.",
    )
    statement: str | None = Field(
        default=None,
        description="Why the figures above are null, stated when the week holds no plan of record. "
        "Null otherwise.",
    )
    days: ReviewDayCounts = Field(description="The named week's own day counts.")
    quarter_days: ReviewDayCounts = Field(
        description="The whole reviewed quarter's day counts, summed from the trend's weeks."
    )
    categories: list[CategoryReadingResponse] = Field(
        description="One row per declared Area, then the vacancy, in the order the wedges are "
        "drawn. This is the NAMED WEEK's composition and its actual against target."
    )
    trend: list[TrendWeekResponse] = Field(
        description="The quarter by week, oldest first, ending with the named week."
    )
    proposal: BudgetProposalResponse


class AppliedShare(WireModel):
    """One Area's share, as a caller asks for it to be declared."""

    model_config = ConfigDict(extra="forbid")

    area_id: UUID = Field(
        description="The Area to declare this share on. The vacancy has no row here: it is not an "
        "Area, so its share follows from the Areas' own."
    )
    budget_percent: WireDecimal = Field(
        ge=BUDGET_PERCENT_MIN,
        le=BUDGET_PERCENT_MAX,
        description="The share to declare. Shares summing past 100 across Areas are accepted and "
        "reported as oversubscription, never rejected.",
    )


class BudgetApplyRequest(WireModel):
    """The shares to declare, whether they are the proposal's own or adjusted ones.

    There is no "apply wholly" flag, and the absence is the contract. A caller applying the
    proposal sends the proposal's figures; a caller adjusting it sends its own. One path, so an
    adjusted revision cannot take a route a whole one does not.

    An Area the request does not name is left alone, which is what makes rejecting one row of a
    proposal expressible without restating the rest.
    """

    model_config = ConfigDict(extra="forbid")

    percentages: list[AppliedShare] = Field(
        min_length=1,
        description="At least one Area's share. An empty list is refused rather than applied as a "
        "no-op: it is a request that states nothing, and answering 200 to one would report a "
        "revision nobody made.",
    )


class BudgetApplyResponse(WireModel):
    """What one apply changed, and the two figures the caller needs immediately afterwards."""

    applied: int = Field(
        description="How many Areas' shares this call changed. A share replaced by the value it "
        "already held is not one of them, so nothing was written and no solve was invalidated."
    )
    declared: list[UUID] = Field(
        description="The Areas whose share this call changed, so a caller can render exactly what "
        "moved."
    )
    changed_at: WireInstant | None = Field(
        default=None,
        description="When the change was applied, or null when nothing changed.",
    )
    statement: str = Field(description="What was applied, in one sentence.")
