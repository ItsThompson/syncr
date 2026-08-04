"""The wire shapes the day-type, day-shape, and week-pattern routes exchange.

Explicit schemas rather than mapped rows, so a column added to a table does not change the
contract by itself and the generated TypeScript changes only when this file does. The shapes one
ENTRY is declared in are in ``entry_schemas.py``, where the two kinds and their union live.

Two properties are stated in the field descriptions rather than only here, because the
descriptions reach the OpenAPI document and therefore the caller.

**The template list states each shape's entry count**, not its entries. A screen listing shapes
renders the count; reading one shape is what returns the entries.

**The week pattern is seven required fields rather than a map** of weekday to day type. That is
what makes a partial mapping impossible to send: a caller cannot leave Thursday out of an object
whose Thursday field is required, and the generated TypeScript names all seven.

Every request forbids unknown fields, which is what makes a cadence a stated 422 anywhere in this
package rather than a value quietly dropped.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID  # noqa: TC003 - pydantic resolves annotations at runtime

from pydantic import ConfigDict, Field, field_validator

from syncr_api.core.schemas import WireModel
from syncr_api.templates.config import DAY_TYPE_NAME_MAX_LENGTH, TEMPLATE_NAME_MAX_LENGTH
from syncr_api.templates.entry_schemas import (
    TemplateEntryResponse,  # noqa: TC001 - pydantic resolves annotations at runtime
)
from syncr_domain.weeks import Weekday

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syncr_domain.identifiers import DayTypeId

_DAY_TYPE_DESCRIPTION = (
    "The kind of day this shape describes. One shape per day type: materializing a date "
    "resolves its weekday to a day type and the day type to one shape."
)
_WEEKDAY_DESCRIPTION = "The day type this weekday uses."
_NOT_NULLABLE_MESSAGE = (
    "this field cannot be cleared, so null is refused rather than read as no change. "
    "Leave it out to keep the stored value."
)


class DayTypeResponse(WireModel):
    """One kind of day: ``Weekday``, ``Uni day``, ``Weekend``."""

    id: UUID
    name: str = Field(
        description="Unique within the tenant, because the week pattern names a day type by it."
    )


class DayTypesResponse(WireModel):
    """Every day type a tenant has declared, in the order they were declared.

    A wrapper rather than a bare array. The collection is bounded by how many kinds of day a
    person has, so it is not paginated, and an object leaves room for a later field.
    """

    day_types: list[DayTypeResponse]


class DayTypeCreateRequest(WireModel):
    """A kind of day to declare. A name is the whole declaration."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=DAY_TYPE_NAME_MAX_LENGTH)


class TemplateResponse(WireModel):
    """One day shape and its entries, in the order the day runs."""

    id: UUID
    day_type_id: UUID = Field(description=_DAY_TYPE_DESCRIPTION)
    name: str
    entries: list[TemplateEntryResponse]


class TemplateSummary(WireModel):
    """One day shape as the list states it: named, bound to a day type, and counted."""

    id: UUID
    day_type_id: UUID = Field(description=_DAY_TYPE_DESCRIPTION)
    name: str
    entry_count: int = Field(
        description="How many entries this shape holds. The list states the count rather than "
        "the entries; read one shape to get them."
    )


class TemplatesResponse(WireModel):
    """Every day shape a tenant has declared, oldest first, each with its entry count."""

    templates: list[TemplateSummary]


class TemplateCreateRequest(WireModel):
    """A day shape to declare, for a day type that has none yet.

    It carries no entries. A shape is declared and then filled in, so one request does one thing
    and a rejected entry does not take a whole shape with it.
    """

    model_config = ConfigDict(extra="forbid")

    day_type_id: UUID = Field(description=_DAY_TYPE_DESCRIPTION)
    name: str = Field(min_length=1, max_length=TEMPLATE_NAME_MAX_LENGTH)


class TemplatePatchRequest(WireModel):
    """A partial update. An omitted field is left alone.

    ``dayTypeId`` is not a member of this shape and an unknown field is rejected, so sending one
    is a stated 422. A shape IS the shape of its day type and there is one per day type, so
    moving it is indistinguishable from declaring a shape for the other day type.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=TEMPLATE_NAME_MAX_LENGTH)

    @field_validator("name")
    @classmethod
    def _refuse_an_explicit_null(cls, value: str | None) -> str | None:
        """Refuse ``null`` on a field that has nothing to clear.

        A validator runs only for a field the request actually named, so an omitted field is
        untouched by this and an explicit null is a stated 422. Without it, both would arrive as
        ``None`` and the two intentions would be indistinguishable.
        """
        if value is None:
            raise ValueError(_NOT_NULLABLE_MESSAGE)
        return value


class _WeekPatternFields(WireModel):
    """Which day type each weekday uses. All seven, because a partial pattern is not one.

    Each field is named for its weekday, which is what lets the mapping be read back without
    seven statements of the same thing. ``test_the_pattern_shape_names_every_weekday`` is what
    keeps the field names and the weekday vocabulary in step.
    """

    monday: UUID = Field(description=_WEEKDAY_DESCRIPTION)
    tuesday: UUID = Field(description=_WEEKDAY_DESCRIPTION)
    wednesday: UUID = Field(description=_WEEKDAY_DESCRIPTION)
    thursday: UUID = Field(description=_WEEKDAY_DESCRIPTION)
    friday: UUID = Field(description=_WEEKDAY_DESCRIPTION)
    saturday: UUID = Field(description=_WEEKDAY_DESCRIPTION)
    sunday: UUID = Field(description=_WEEKDAY_DESCRIPTION)

    def mapping(self) -> dict[Weekday, DayTypeId]:
        """These seven fields as the weekday-to-day-type mapping a pattern is stated over."""
        return {weekday: getattr(self, weekday.value) for weekday in Weekday}


class WeekPatternResponse(_WeekPatternFields):
    """The declared pattern. Every weekday names a day type."""

    @classmethod
    def of(cls, mapping: Mapping[Weekday, DayTypeId]) -> WeekPatternResponse:
        """The response for a pattern, which already covers every weekday."""
        return cls(**{weekday.value: day_type_id for weekday, day_type_id in mapping.items()})


class WeekPatternRequest(_WeekPatternFields):
    """The whole mapping to declare. Every weekday is required, which rejects a partial one.

    ``PUT`` rather than ``PATCH``, because a pattern is replaced whole. There is no per-weekday
    merge rule to express: a day with no day type would materialize nothing at all, so a request
    naming three weekdays would have to mean something about the other four.
    """

    model_config = ConfigDict(extra="forbid")
