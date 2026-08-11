"""The wire shapes the off-plan routes exchange.

Explicit schemas rather than mapped rows, so a column added to the table does not change the
contract by itself and the generated TypeScript changes only when this file does.

Three properties are stated in the field descriptions rather than only here, because the
descriptions reach the OpenAPI document and therefore every caller.

**The bounds are instants, and they are half-open.** ``start`` is inside the period and ``end``
is not, so a period ending at 09:00 leaves 09:00 itself on plan and a period beginning at 09:00
may be declared the same morning. Both land on a quarter hour, and both are refused otherwise.

**``keepFrame`` carries two meanings and both are the user's to choose.** False means no
routine materializes inside the span. True means routines materialize and nothing else does.
It is offered on declaration and editable afterwards, so a holiday abroad and a quiet week at
home can differ without redeclaring the span.

**A period is not restricted to whole days or whole weeks.** Friday 14:00 to Monday 09:00 is
one declaration, and it is one record even though two ISO weeks each hold part of it.

The patch request forbids an unknown field, so a caller sending ``keepframe`` or ``interval``
gets a stated 422 rather than a value quietly dropped.

**An empty ``label`` is refused, and a whitespace-only one is not.** The field is nullable, so
``null`` already says "this span has no name" and ``""`` would be a second spelling of it: every
comparable user-authored name in the product refuses the empty string the same way, the nearest
sibling being ``calendars.CalendarSourcePatchRequest.display_name``, which is also nullable and
optional. Whether a whitespace-only value should be stripped, refused, or read as ``null`` is a
different question, and it is deliberately not answered here: it is one policy for every text field
on the wire, and ticket 1135 owns deciding it once in ``core/schemas.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self
from uuid import UUID  # noqa: TC003 - pydantic resolves annotations at runtime

from pydantic import ConfigDict, Field, field_validator

from syncr_api.core.schemas import WireInstant, WireModel
from syncr_api.offplan.config import LABEL_MAX_LENGTH, LABEL_MIN_LENGTH
from syncr_domain.snap import SNAP_MINUTES

if TYPE_CHECKING:
    from syncr_api.offplan.records import OffPlanPeriodRecord

_START_DESCRIPTION = (
    "When the period begins, as an instant. Inside the period, and on a "
    f"{SNAP_MINUTES}-minute boundary."
)
_END_DESCRIPTION = (
    "When the period ends, as an instant. NOT inside the period: a period ending at 09:00 "
    "leaves 09:00 itself on plan, and another period may begin exactly there. On a "
    f"{SNAP_MINUTES}-minute boundary, and after the start."
)
_KEEP_FRAME_DESCRIPTION = (
    "Whether routines still materialize inside the span. False, the default, means no routine "
    "materializes inside it: the frame goes with everything else, which is the holiday-abroad "
    "reading. True means routines materialize and nothing else does, which is the quiet-week-"
    "at-home reading. Editable after the period is declared."
)
_LABEL_DESCRIPTION = (
    "What to call the span, rendered in the gutter beside it. Null when it carries no name; an "
    "empty string is refused, because null is how a span with no name is said."
)

_NOT_NULLABLE_MESSAGE = (
    "this field cannot be cleared, so null is refused rather than read as no change. "
    "Leave it out to keep the stored value."
)


class OffPlanPeriodResponse(WireModel):
    """One declared span of time off."""

    id: UUID
    start: WireInstant = Field(description=_START_DESCRIPTION)
    end: WireInstant = Field(description=_END_DESCRIPTION)
    keep_frame: bool = Field(description=_KEEP_FRAME_DESCRIPTION)
    label: str | None = Field(description=_LABEL_DESCRIPTION)

    @classmethod
    def of(cls, record: OffPlanPeriodRecord) -> Self:
        """The wire shape of one stored period.

        Here rather than in a route module because two routes answer with a period: the off-plan
        collection, and the week view whose gutter draws the spans reaching into that week.
        """
        return cls(
            id=record.id,
            start=record.interval.start,
            end=record.interval.end,
            keep_frame=record.keep_frame,
            label=record.label,
        )


class OffPlanPeriodsResponse(WireModel):
    """Every off-plan period a tenant has declared, earliest first.

    A wrapper rather than a bare array, matching the Areas collection: the number of periods a
    person declares is bounded by the number of holidays they take, so it is not paginated, and
    an object leaves room for a reading beside the list.
    """

    periods: list[OffPlanPeriodResponse]


class OffPlanCreateRequest(WireModel):
    """A span to declare off."""

    model_config = ConfigDict(extra="forbid")

    start: WireInstant = Field(description=_START_DESCRIPTION)
    end: WireInstant = Field(description=_END_DESCRIPTION)
    keep_frame: bool = Field(default=False, description=_KEEP_FRAME_DESCRIPTION)
    label: str | None = Field(
        default=None,
        min_length=LABEL_MIN_LENGTH,
        max_length=LABEL_MAX_LENGTH,
        description=_LABEL_DESCRIPTION,
    )


class OffPlanPatchRequest(WireModel):
    """A partial update. An omitted field is left alone; an explicit null clears the label.

    Either bound may be moved on its own: the one that moves is checked against the stored
    other, so shortening a holiday by a day is one field rather than a redeclaration.
    """

    model_config = ConfigDict(extra="forbid")

    start: WireInstant | None = Field(default=None, description=_START_DESCRIPTION)
    end: WireInstant | None = Field(default=None, description=_END_DESCRIPTION)
    keep_frame: bool | None = Field(default=None, description=_KEEP_FRAME_DESCRIPTION)
    label: str | None = Field(
        default=None,
        min_length=LABEL_MIN_LENGTH,
        max_length=LABEL_MAX_LENGTH,
        description=_LABEL_DESCRIPTION,
    )

    @field_validator("start", "end", "keep_frame")
    @classmethod
    def _refuse_an_explicit_null(cls, value: object) -> object:
        """Refuse ``null`` on the three fields that have nothing to clear.

        A validator runs only for a field the request actually named, so an omitted field is
        untouched by this and an explicit null is a stated 422. Without it, both would arrive as
        ``None`` and the two intentions would be indistinguishable.

        ``label`` is absent from this list on purpose: a span may genuinely lose its name, and
        ``null`` is how that is said.
        """
        if value is None:
            raise ValueError(_NOT_NULLABLE_MESSAGE)
        return value
