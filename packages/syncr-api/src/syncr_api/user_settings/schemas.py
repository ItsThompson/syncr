"""The wire shapes the settings routes exchange.

Explicit schemas rather than mapped rows, so a column added to a table does not change
the contract by itself and the generated TypeScript changes only when this file does.

Two properties of these shapes are stated in the field descriptions rather than only in
this docstring, because the descriptions reach the OpenAPI document and therefore the
caller. **Day start and day end are a default extent, never a crop:** the Week grid's
axis expands to contain every block in the visible week, so a block outside these bounds
widens the axis rather than being hidden. And **there is no sleep floor here:** it is
``minDurationMinutes`` on the sleep routine.

``SettingsPatchRequest`` forbids unknown fields. That is what makes the missing sleep
floor a stated 422 rather than a silently dropped value, which is the failure an earlier
draft of this endpoint would have had.
"""

from __future__ import annotations

from datetime import date, time  # noqa: TC003 - pydantic resolves annotations at runtime
from uuid import UUID  # noqa: TC003 - pydantic resolves annotations at runtime

from pydantic import ConfigDict, Field, ValidationInfo, field_validator

from syncr_api.core.schemas import WireModel
from syncr_api.user_settings.config import (
    VISIBLE_HOURS_MAX,
    VISIBLE_HOURS_MIN,
    ReviewCadence,
)
from syncr_domain.zones import MAX_ZONE_KEY_LENGTH

_DAY_BOUNDS_DESCRIPTION = (
    "Wall time, no zone. Sets the DEFAULT extent of the Week grid's axis, never a crop: "
    "the axis expands to contain every block in the visible week, because a block hidden "
    "by the axis is a scheduling error the reader cannot see."
)
_ZONE_DESCRIPTION = "An IANA zone identifier, such as 'Europe/London'."
_VISIBLE_HOURS_DESCRIPTION = (
    "How many hours of the day the grid shows at once. The Week screen narrows this "
    "range further on a short display, so a thirty-minute block keeps its title."
)


class SettingsResponse(WireModel):
    """One tenant's settings, and the zone active today.

    ``activeZone`` is resolved through the same function the solver and the assembler
    read, so the screen and the plan cannot disagree about where the user is. One zone,
    for one date: no time in this product is ever shown in two zones at once.
    """

    visible_hours: int = Field(description=_VISIBLE_HOURS_DESCRIPTION)
    day_start: time = Field(description=_DAY_BOUNDS_DESCRIPTION)
    day_end: time = Field(description=_DAY_BOUNDS_DESCRIPTION)
    review_cadence: ReviewCadence
    home_zone: str = Field(description=_ZONE_DESCRIPTION)
    active_zone: str = Field(
        description=(
            "The zone in force on activeZoneDate: the travel override covering it, else "
            "the home zone."
        )
    )
    active_zone_date: date = Field(
        description=(
            "The local date activeZone was resolved for, taken in the home zone. A date "
            "selects a travel override, so it cannot itself be read in the zone the "
            "override names."
        )
    )


class SettingsPatchRequest(WireModel):
    """A partial update. An omitted field is left alone.

    No settings value is nullable, so nothing here can be cleared: a field sent as null
    means unchanged, exactly as an absent field does.

    The sleep floor is not a member of this shape and an unknown field is rejected, so
    sending one is a stated 422. The floor is ``minDurationMinutes`` on the sleep
    routine, set through ``PATCH /api/v1/routines/{id}``, where the solver reads it.
    """

    model_config = ConfigDict(extra="forbid")

    visible_hours: int | None = Field(
        default=None,
        ge=VISIBLE_HOURS_MIN,
        le=VISIBLE_HOURS_MAX,
        description=_VISIBLE_HOURS_DESCRIPTION,
    )
    day_start: time | None = Field(default=None, description=_DAY_BOUNDS_DESCRIPTION)
    day_end: time | None = Field(default=None, description=_DAY_BOUNDS_DESCRIPTION)
    review_cadence: ReviewCadence | None = None
    # Bounded by the domain's own limit, so this rejects nothing the zone lookup would
    # have accepted and the two bounds cannot drift apart.
    home_zone: str | None = Field(
        default=None, min_length=1, max_length=MAX_ZONE_KEY_LENGTH, description=_ZONE_DESCRIPTION
    )


class TravelOverrideResponse(WireModel):
    """A declared range in another zone. Both dates are inclusive."""

    id: UUID
    start_date: date
    end_date: date
    zone: str = Field(description=_ZONE_DESCRIPTION)


class TravelOverridesResponse(WireModel):
    """Every override a tenant has declared, in date order.

    A wrapper rather than a bare array. The collection is bounded by how much a person
    travels, so it is not paginated, and an object leaves room for a later field without
    changing the shape of what is already there.
    """

    overrides: list[TravelOverrideResponse]


class TravelOverrideRequest(WireModel):
    """A range to declare. Both dates inclusive, and the range may not overlap another.

    ``startDate`` after ``endDate`` is a 422 naming ``endDate``, and an overlap with an
    existing override is a 409 naming both ranges. Two ranges that abut exactly are
    accepted: adjacency is not overlap.
    """

    model_config = ConfigDict(extra="forbid")

    start_date: date
    end_date: date
    zone: str = Field(min_length=1, max_length=MAX_ZONE_KEY_LENGTH, description=_ZONE_DESCRIPTION)

    @field_validator("end_date")
    @classmethod
    def _not_before_the_start(cls, end_date: date, info: ValidationInfo) -> date:
        """Reject a range that runs backwards, pointing at the field that has to move.

        The domain refuses the pair too, but as a zone rejection: it raises the same error
        type an unreadable identifier does, so a caller who inverted two dates would be
        told to supply an IANA identifier. Checked here so the field pointer and the
        remedy both name what is actually wrong.

        ``start_date`` is absent from ``info.data`` when it failed its own validation,
        which is already a stated 422 of its own.
        """
        start_date = info.data.get("start_date")
        if start_date is None or start_date <= end_date:
            return end_date
        message = (
            f"is {end_date}, before the start date {start_date}. Both dates are inclusive, "
            "so a one-day range states the same date twice."
        )
        raise ValueError(message)
