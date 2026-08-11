"""The wire shapes the anchor and anchor-type routes exchange.

Explicit schemas rather than mapped rows, so a column added to a table does not change the
contract by itself and the generated TypeScript changes only when this file does.

Three properties of these shapes are the contract rather than an omission.

**No anchor response carries a location.** ``Anchor.location`` is stored with no reader at all:
transit is declared per anchor type rather than derived from a location, which reinterprets PRD
3.4's "generated from a location". Routing needs a maps integration, a home address, and a
travel-mode preference, none of which is in this epic. The field is absent from every response
here, and a test asserts it: an anchor's location discloses where the user physically is at a
given hour, so it must not reach the wire by sharing a name with a column.

**Every anchor response says it is read-only, and names its source.** A caller does not have to
infer that from the absence of an edit route.

**A recovery scope is a three-way choice, not an empty list.** ``postScope`` and
``forbiddenAreaIds`` travel together and the descriptions state the biconditional, so the
generated client sees the rule rather than discovering it from a 422.

**Every free-text field is collapsed and refuses a control character.** A name that is only
whitespace passes a minimum length and then leaves a rules table row with no label, and a name
carrying a NUL byte reaches a `VARCHAR` column and fails as a fault rather than as a stated
rejection. Both are refused here. A whitespace-only match substring is refused for a third reason:
it is contained in almost every title, so it would be a silent catch-all rule.

There is no ``ruleOrder`` on either request shape. Position is set by appending on create and
rewritten wholly by the reorder route, because moving one rule changes what every rule after it
matches: a request naming one position would be stating a fraction of the change it was making.
"""

from __future__ import annotations

from uuid import UUID  # noqa: TC003 - pydantic resolves annotations at runtime

from pydantic import ConfigDict, Field, field_validator

from syncr_api.anchors.config import (
    ANCHOR_PAGE_LIMIT_DEFAULT,
    ANCHOR_PAGE_LIMIT_MAX,
    ANCHOR_TYPE_NAME_MAX_LENGTH,
    ANCHOR_TYPE_SOURCES,
    DURATION_MINUTES_MAX,
    FORBIDDEN_AREAS_MAX,
    FORBIDS_AREAS,
    LEAD_MINUTES_MAX,
    MATCH_TITLE_MAX_LENGTH,
    MINUTES_MIN,
    POST_SCOPE_LABEL,
    POST_SCOPE_LABELS,
    POST_SCOPES,
    AnchorTypeSource,
    PostScope,
)
from syncr_api.anchors.identity import collapsed_text, is_control
from syncr_api.core.schemas import WireInstant, WireModel

_TYPE_SOURCE_DESCRIPTION = (
    "Where this commitment's type came from. "
    f"`{ANCHOR_TYPE_SOURCES[0]}` means no rule matched it, so it is opaque busy time with no "
    f"shadow of any kind. `{ANCHOR_TYPE_SOURCES[1]}` means a match rule chose it, and a rule "
    f"change may replace it. `{ANCHOR_TYPE_SOURCES[2]}` means you chose it, and no rule change "
    "will replace it."
)
_POST_SCOPE_DESCRIPTION = (
    f"The recovery window's scope, read as \"{POST_SCOPE_LABEL}: "
    + " / ".join(POST_SCOPE_LABELS[scope] for scope in POST_SCOPES)
    + f'". `{FORBIDS_AREAS}` requires a non-empty forbiddenAreaIds and the other two require an '
    "empty one, so the three-way choice is explicit rather than encoded in whether a list "
    "happens to be empty."
)
_FORBIDDEN_AREAS_DESCRIPTION = (
    f"The Areas a recovery window forbids. Non-empty when postScope is `{FORBIDS_AREAS}` and "
    "empty otherwise."
)
_TRANSIT_LEAD_DESCRIPTION = (
    "How long before the commitment the outbound leg starts. Null means it abuts: leave exactly "
    "late enough to arrive on time. A larger lead arrives early and leaves a deliberate gap. "
    "Must be at least transitDurationMinutes, because a shorter lead would still be travelling "
    "when the commitment started."
)
_PREP_LEAD_DESCRIPTION = (
    "How long before the commitment prep STARTS, so a short block can sit hours ahead of it. "
    "When prep has a duration this must be at least that duration plus the transit lead, or prep "
    "would still be running when the outbound leg left."
)
_RETURN_TRANSIT_DESCRIPTION = (
    "The return journey, from the commitment's end. Zero means no return leg, which is not "
    "implied by the outbound duration: an interview has one leg and a lecture day two."
)

_NOT_NULLABLE_MESSAGE = (
    "this field cannot be cleared, so null is refused rather than read as no change. "
    "Leave it out to keep the stored value."
)
_BLANK_MESSAGE = "must hold something other than whitespace"
_CONTROL_MESSAGE = "must not contain a control character"


def _readable(value: str | None) -> str | None:
    """``value`` collapsed to single spaces, refusing blank text and control characters.

    ``None`` passes through, because a nullable field's null is decided by its own validator. What
    this refuses is text that would be stored and then read by a person: `'   '` renders as a row
    with no label, and a NUL byte reaches a ``VARCHAR`` column and raises where the caller deserves
    a stated 422.

    :func:`~syncr_api.anchors.identity.is_control` is shared with the ingest boundary, so the two
    paths agree on what a control character IS and differ only in what they do about one. Here it is
    refused, because the person who typed it can remove it; a publisher's is dropped, because nobody
    can tell the publisher anything. Calling ``collapsed_text`` rather than ``scrubbed_text`` is
    load-bearing: scrubbing first would make this rejection unreachable.
    """
    if value is None:
        return None
    collapsed = collapsed_text(value)
    if not collapsed:
        raise ValueError(_BLANK_MESSAGE)
    if any(is_control(character) for character in collapsed):
        raise ValueError(_CONTROL_MESSAGE)
    return collapsed


class ShadowDeclarationResponse(WireModel):
    """Which products a commitment's type declares, before any geometry is computed.

    Every member false is an untyped commitment: opaque busy time with no shadow of any kind.
    """

    prep: bool = Field(description="Whether a prep buffer is declared.")
    outbound_transit: bool = Field(description="Whether an outbound journey is declared.")
    return_transit: bool = Field(description="Whether a return journey is declared.")
    recovery: bool = Field(description="Whether a recovery window is declared.")


class AnchorResponse(WireModel):
    """One imported commitment. Read-only in syncr, and it says so.

    No location field, deliberately. See the module docstring.
    """

    id: UUID
    source_id: UUID = Field(description="The calendar source this commitment was imported from.")
    source_name: str = Field(description="That source's name, as the detail panel states it.")
    read_only: bool = Field(
        description="Always true. syncr never edits or deletes an imported commitment."
    )
    read_only_statement: str = Field(
        description="What read-only means here, naming the source that does own this commitment."
    )
    series_uid: str | None = Field(
        description="The recurring series this occurrence belongs to, or null for a one-off. "
        "Retyping an occurrence of a series persists on the whole series."
    )
    title: str
    starts_at: WireInstant = Field(
        description="Absolute, and NOT snapped to the quarter hour: an imported commitment is a "
        "fact and keeps its real time, even at :07."
    )
    ends_at: WireInstant
    anchor_type_id: UUID | None
    anchor_type_name: str | None = Field(
        description="The matched or overridden type's name, or null when nothing typed it."
    )
    type_source: AnchorTypeSource = Field(description=_TYPE_SOURCE_DESCRIPTION)
    possibly_stale: bool = Field(
        description="True when this commitment's source has been unreachable since it was last "
        "confirmed. It is retained rather than removed: a failed sync is not evidence that a "
        "commitment was cancelled."
    )
    casts: ShadowDeclarationResponse


class AnchorsResponse(WireModel):
    """One page of commitments in a span, earliest first.

    Cursor-paginated rather than offset-paginated. A feed may legitimately contribute thousands
    of commitments inside a year, and an offset page shifts under a sync that inserts a row
    before the cursor, which would silently skip one.
    """

    anchors: list[AnchorResponse]
    next_cursor: str | None = Field(
        default=None,
        description=(
            "Pass back as `cursor` to read the next page. Null when this is the last page. "
            f"A page holds up to `limit` commitments, {ANCHOR_PAGE_LIMIT_DEFAULT} by default and "
            f"{ANCHOR_PAGE_LIMIT_MAX} at most."
        ),
    )


class RetypeAnchorRequest(WireModel):
    """The type one occurrence was retyped to. Null means "not any of my types"."""

    model_config = ConfigDict(extra="forbid")

    anchor_type_id: UUID | None = Field(
        default=None,
        description="The type to apply, or null to leave this commitment as opaque busy time. "
        "Either way the choice persists on the series and survives a rule change.",
    )


class RetypedAnchorResponse(WireModel):
    """The retyped occurrence, and how many occurrences of its series moved with it.

    The count is how progress is reported in this product: retyping one daily standup answers
    with 250, which is what says the correction reached the series rather than the occurrence.
    """

    anchor: AnchorResponse
    occurrences_retyped: int = Field(
        description="How many occurrences of this series were retyped, this one included."
    )


class AnchorTypeResponse(WireModel):
    """One declared class of commitment, and the shadow every commitment of it casts."""

    id: UUID
    name: str
    rule_order: int = Field(
        description="Evaluation position. Rules evaluate in this order and the FIRST match wins."
    )
    match_title_contains: str | None = Field(
        description="Matches when the commitment's title contains this, ignoring case. Null "
        "matches any title."
    )
    match_source_id: UUID | None = Field(
        description="Matches only commitments from this calendar source. Null matches any source."
    )
    prep_lead_minutes: int = Field(description=_PREP_LEAD_DESCRIPTION)
    prep_duration_minutes: int = Field(
        description="How long prep lasts. Zero means no prep, whatever the lead says."
    )
    prep_area_id: UUID | None = Field(
        description="The Area a prep block belongs to. Null makes prep a forbidden window rather "
        "than a block, because a buffer with no Area has no budget to consume."
    )
    transit_lead_minutes: int | None = Field(description=_TRANSIT_LEAD_DESCRIPTION)
    transit_duration_minutes: int = Field(
        description="The outbound journey. Zero means no outbound leg, whatever the lead says."
    )
    return_transit_minutes: int = Field(description=_RETURN_TRANSIT_DESCRIPTION)
    transit_area_id: UUID | None = Field(
        description="The Area a transit block belongs to, typically a dedicated Transit Area. "
        "Null makes transit a forbidden window rather than a block."
    )
    post_buffer_minutes: int = Field(
        description="The recovery window, measured from the commitment's END and never from the "
        "end of a return leg. Zero means no window."
    )
    post_scope: PostScope = Field(description=_POST_SCOPE_DESCRIPTION)
    forbidden_area_ids: list[UUID] = Field(description=_FORBIDDEN_AREAS_DESCRIPTION)
    casts: ShadowDeclarationResponse


class AnchorTypesResponse(WireModel):
    """Every type a tenant declares, in evaluation order.

    A wrapper rather than a bare array. The collection is bounded by how many classes of
    commitment a person distinguishes, so it is not paginated.
    """

    anchor_types: list[AnchorTypeResponse]


class AnchorTypeCreateRequest(WireModel):
    """A type to declare. It is appended to the end of the evaluation order.

    Every geometry member defaults to zero, so the smallest legal request is a name: a type that
    casts nothing at all is legitimate, and it is how a `Standup` is declared.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=ANCHOR_TYPE_NAME_MAX_LENGTH)
    match_title_contains: str | None = Field(
        default=None, min_length=1, max_length=MATCH_TITLE_MAX_LENGTH
    )
    match_source_id: UUID | None = None
    prep_lead_minutes: int = Field(
        default=0, ge=MINUTES_MIN, le=LEAD_MINUTES_MAX, description=_PREP_LEAD_DESCRIPTION
    )
    prep_duration_minutes: int = Field(default=0, ge=MINUTES_MIN, le=DURATION_MINUTES_MAX)
    prep_area_id: UUID | None = None
    transit_lead_minutes: int | None = Field(
        default=None, ge=MINUTES_MIN, le=LEAD_MINUTES_MAX, description=_TRANSIT_LEAD_DESCRIPTION
    )
    transit_duration_minutes: int = Field(default=0, ge=MINUTES_MIN, le=DURATION_MINUTES_MAX)
    return_transit_minutes: int = Field(
        default=0,
        ge=MINUTES_MIN,
        le=DURATION_MINUTES_MAX,
        description=_RETURN_TRANSIT_DESCRIPTION,
    )
    transit_area_id: UUID | None = None
    post_buffer_minutes: int = Field(default=0, ge=MINUTES_MIN, le=DURATION_MINUTES_MAX)
    post_scope: PostScope = Field(default="none", description=_POST_SCOPE_DESCRIPTION)
    forbidden_area_ids: list[UUID] = Field(
        default_factory=list,
        max_length=FORBIDDEN_AREAS_MAX,
        description=_FORBIDDEN_AREAS_DESCRIPTION,
    )

    _read_free_text = field_validator("name", "match_title_contains")(_readable)


class AnchorTypePatchRequest(WireModel):
    """A partial update. An omitted field is left alone; an explicit null clears a nullable one.

    The distinction is the point. ``transitLeadMinutes: null`` restores the abutting default, and
    omitting it keeps whatever lead is stored. ``name``, the durations, ``postScope``, and
    ``forbiddenAreaIds`` are not nullable and reject null.

    ``ruleOrder`` is not a member of this shape and an unknown field is rejected, so sending one
    is a stated 422.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=ANCHOR_TYPE_NAME_MAX_LENGTH)
    match_title_contains: str | None = Field(
        default=None, min_length=1, max_length=MATCH_TITLE_MAX_LENGTH
    )
    match_source_id: UUID | None = None
    prep_lead_minutes: int | None = Field(default=None, ge=MINUTES_MIN, le=LEAD_MINUTES_MAX)
    prep_duration_minutes: int | None = Field(default=None, ge=MINUTES_MIN, le=DURATION_MINUTES_MAX)
    prep_area_id: UUID | None = None
    transit_lead_minutes: int | None = Field(
        default=None, ge=MINUTES_MIN, le=LEAD_MINUTES_MAX, description=_TRANSIT_LEAD_DESCRIPTION
    )
    transit_duration_minutes: int | None = Field(
        default=None, ge=MINUTES_MIN, le=DURATION_MINUTES_MAX
    )
    return_transit_minutes: int | None = Field(
        default=None, ge=MINUTES_MIN, le=DURATION_MINUTES_MAX
    )
    transit_area_id: UUID | None = None
    post_buffer_minutes: int | None = Field(default=None, ge=MINUTES_MIN, le=DURATION_MINUTES_MAX)
    post_scope: PostScope | None = Field(default=None, description=_POST_SCOPE_DESCRIPTION)
    forbidden_area_ids: list[UUID] | None = Field(
        default=None, max_length=FORBIDDEN_AREAS_MAX, description=_FORBIDDEN_AREAS_DESCRIPTION
    )

    @field_validator(
        "name",
        "prep_lead_minutes",
        "prep_duration_minutes",
        "transit_duration_minutes",
        "return_transit_minutes",
        "post_buffer_minutes",
        "post_scope",
        "forbidden_area_ids",
    )
    @classmethod
    def _refuse_an_explicit_null(cls, value: object) -> object:
        """Refuse ``null`` on the fields that have nothing to clear.

        A validator runs only for a field the request actually named, so an omitted field is
        untouched by this and an explicit null is a stated 422. Without it, both would arrive as
        ``None`` and the two intentions would be indistinguishable.

        ``transitLeadMinutes`` is absent from this list on purpose: null is a legal value there
        and it means the outbound leg abuts the commitment.
        """
        if value is None:
            raise ValueError(_NOT_NULLABLE_MESSAGE)
        return value

    _read_free_text = field_validator("name", "match_title_contains")(_readable)


class ReorderAnchorTypesRequest(WireModel):
    """The whole evaluation order: every type the tenant holds, exactly once.

    A partial order would leave the unnamed types at positions the caller could not see, and
    first-match semantics make that a silent change to what every one of them matches.
    """

    model_config = ConfigDict(extra="forbid")

    anchor_type_ids: list[UUID] = Field(
        description="Every anchor type, in the order rules should evaluate. The first match wins."
    )
