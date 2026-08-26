"""The wire shape of the weekly session's payload.

Separate from ``schemas`` because two reviews share a prefix and nothing else: the pie review is
Areas-shaped arithmetic over a quarter, and this is one week's planning surface. One file holding
both would be the module a reader has to search rather than open.

**The verdict field is named ``verdict``, deliberately.** The guard that holds a read to appending
no ``VerdictEvent`` is stated over the response shapes that declare that field rather than over a
list of paths, so declaring it is what brings this read under the rule. A field named anything else
would have escaped a guard that was armed for this payload before it existed.

**A raised item carries its own sentence.** Every category the session raises renders as one row of
one amber panel, and the words are composed server-side for the reason the pie review's statements
are: two clients would compose two sentences from one row, and the CLI and the screen would then
disagree about the same week.

**Nothing here is addressable and nothing here is an action.** A raised item is a reading rather
than a row, and accepting or declining a promotion is a route of its own. The payload says so in
words, which is what ``US-TPL-05``'s "nothing is applied to the template without the user accepting"
means on a read."""

from __future__ import annotations

from uuid import UUID  # noqa: TC003 - pydantic resolves annotations at runtime

from pydantic import Field

# Referenced from field annotations, which pydantic resolves at RUNTIME to build the model, so under
# TYPE_CHECKING these would resolve to a NameError while the app is being constructed.
from syncr_api.concessions.schemas import AdjustmentResponse  # noqa: TC001
from syncr_api.core.schemas import WireModel, WireSpan
from syncr_api.plans.verdict_schemas import VerdictResponse  # noqa: TC001
from syncr_api.reviews.raised import RaisedKind  # noqa: TC001
from syncr_api.reviews.schemas import CategoryReadingResponse, ReviewDayCounts  # noqa: TC001


class RaisedItemResponse(WireModel):
    """One thing the session raises, at amber panel volume and in session mode only.

    Every category is one shape with a ``kind`` rather than one shape per category, because they
    render as rows of one panel: section 16's notice-volume table gives the whole set one volume and
    one pigment.

    **There is no count field, and every figure is in ``statement``.** A count of weeks on the wire
    as well as in the words would be one fact twice, and a surface rendering both would put the same
    number on the screen in two places, which is the drift ticket 49's own band was corrected for.
    """

    key: str = Field(
        description="Stable for one raised thing across two reads, so a client keys a list on it. "
        "Not an identifier: an item is a reading rather than a row, and nothing addresses one."
    )
    kind: RaisedKind = Field(description="What this item is about.")
    title: str = Field(
        description="The thing itself, in the words the user knows it by. A repeated collision "
        "names BOTH ends here, as 'Standup over Leetcode', which is US-REV-05's own form."
    )
    statement: str = Field(
        description="What to make of it, in the words an interface renders, including every figure "
        "the item states. Composed here so the CLI and the screen cannot say two different things."
    )


class PromotionCandidateResponse(WireModel):
    """One repeated pin the session offers to promote into the template.

    ``US-TPL-05``: pinning the same binding to the same time for three consecutive weeks raises a
    proposal naming the binding, the time, and the number of weeks. Accepting or declining is a
    route of its own, addressed by the ``id`` below, and this shape carries no state: it is the
    question, plus what can be done about it.
    """

    id: str = Field(
        description="What the accept and the decline routes address. It is the GROUP the pattern "
        "was found by -- the kind, the content, the weekday and the minute of the day -- because "
        "nothing stores a candidate: detection runs on every read of this payload. It carries no "
        "week count, so a run that reaches a fourth week is still the pattern a decline silenced."
    )
    entity_id: UUID = Field(
        description="The content that keeps being pinned. Which occurrence of it was pinned is "
        "dropped: the occurrence key is scoped to one week, so a pattern across weeks cannot hold "
        "one."
    )
    kind: str = Field(description="What sort of thing that content is: a habit, a task, a routine.")
    title: str = Field(
        description="What to call the content, resolved HERE from the blocks of the reviewed "
        "window and the planned week. A pattern whose content appears in neither falls back to the "
        "reader's word for its kind, which is the fallback a repeated collision's block takes too: "
        "one absence, one spelling, on both surfaces of this payload."
    )
    weekday: int = Field(description="The ISO weekday the pin keeps landing on, Monday being 1.")
    local_time: str = Field(
        description="The wall time it keeps being pinned to, as a template entry would declare it, "
        "in the home zone. A template entry holds a wall time, so no other zone could be offered."
    )
    consecutive_weeks: int = Field(
        description="How many consecutive weeks the pattern runs for, from the data rather than "
        "from the threshold it passed."
    )
    weeks: list[str] = Field(
        description="Every ISO week of the run, oldest first, so the count can be checked."
    )
    accept_refusal: str | None = Field(
        description="Why the template cannot absorb this pattern, or null when it can. A promotion "
        "MOVES the day-shape entry a pattern is about, so content no entry holds has nothing to "
        "move: the pattern is still worth stating, and this is the sentence saying what the reader "
        "can do instead. A surface renders no accept control when it is set."
    )


class SessionRetroResponse(WireModel):
    """Last week: what each Area was allotted, what it held, and how much was answered for."""

    period: str = Field(description="The ISO week under review, which precedes the week planned.")
    span: WireSpan = Field(
        description="The half-open interval the reviewed week covers, ``[start, end)``. Present "
        "because it is what the denominator was derived from."
    )
    discretionary_minutes: int | None = Field(
        description="The reviewed week's own stored denominator, or null when it held no plan of "
        "record: a target divides a denominator such a week does not have."
    )
    days: ReviewDayCounts = Field(
        description="Confirmed, unconfirmed, and off-plan days of the reviewed week. Three "
        "quantities: an off-plan day is one the user declared away rather than one they failed to "
        "answer for."
    )
    off_plan_minutes: int = Field(
        description="How many of the reviewed week's minutes were declared off-plan."
    )
    off_plan_statement: str | None = Field(
        default=None,
        description="Why every figure here is zero, stated when the week was off-plan end to end.",
    )
    statement: str = Field(
        description="How much of the period the figures rest on, always present. A period with no "
        "confirmed day says so rather than leaving a chart to render nothing."
    )
    categories: list[CategoryReadingResponse] = Field(
        description="One row per declared Area, then the vacancy: actual against target for the "
        "reviewed week. The same arithmetic the pie review divides, over the same denominator."
    )


class WeeklySessionResponse(WireModel):
    """The weekly session, as one read that writes nothing at all.

    Addressed by the week it PLANS. The retrospective covers the week before it, which is what
    ``US-REV-01``'s "planning and retrospective in one pass" means on the wire: one request, both
    halves, so last week informs next week without a second sitting.
    """

    iso_week: str = Field(description="The ISO week being planned, such as '2026-W07'.")
    span: WireSpan = Field(
        description="The half-open interval the planned week covers, ``[start, end)``. Present "
        "because it is what the denominator was derived from."
    )
    input_version: int = Field(
        description="The planned week's input version AS THIS PAYLOAD WAS COMPOSED. A client "
        "compares it with the week's own and says the session is stale when the two differ, which "
        "is what happens the moment a pin made inside the session bumps the week: the raises below "
        "were computed against the earlier state and the plan beside them is the later one."
    )
    retro: SessionRetroResponse
    raised: list[RaisedItemResponse] = Field(
        description="Everything the session raises about the planned week and the period before "
        "it. Rendered at amber panel volume, in session mode only."
    )
    verdict: VerdictResponse | None = Field(
        description="Whether the planned week can hold its commitments. Null exactly when that "
        "week holds no plan, because nothing has been computed about it. Computing it appends no "
        "row: reading a review is a read."
    )
    concessions: list[AdjustmentResponse] = Field(
        description="What the planned week has already given up, listed above the gaps that remain."
    )
    promotions: list[PromotionCandidateResponse] = Field(
        description="Repeated pins the session offers to promote into the template. Nothing is "
        "applied without acceptance, which promotionStatement says in words."
    )
    promotion_statement: str = Field(
        description="That syncr has changed nothing and will not without acceptance. Always "
        "present, because the absence of candidates is not the absence of that promise; a client "
        "renders it beside the candidates it has."
    )
