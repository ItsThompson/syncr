"""The wire shapes the settings routes exchange.

Explicit schemas rather than mapped rows, so a column added to a table does not change
the contract by itself and the generated TypeScript changes only when this file does.

Three properties of these shapes are stated in the field descriptions rather than only in
this docstring, because the descriptions reach the OpenAPI document and therefore the
caller. **Day start and day end are a default extent, never a crop:** the Week grid's
axis expands to contain every block in the visible week, so a block outside these bounds
widens the axis rather than being hidden. **The day bounds are wall time and are validated
as such:** a bound carrying an offset is refused rather than stored with the offset
dropped, and so is one carrying seconds, while any whole minute is accepted because these
two bounds draw the axis a block is measured against and materialize no block. And **there
is no sleep floor here:** it is ``minDurationMinutes`` on the sleep routine.

``SettingsPatchRequest`` forbids unknown fields. That is what makes the missing sleep
floor a stated 422 rather than a silently dropped value, which is the failure an earlier
draft of this endpoint would have had.
"""

from __future__ import annotations

# `time` is used at runtime by the DayBound alias below, so this import carries no
# type-checking suppression the way the identifier import does.
from datetime import date, time
from typing import Annotated
from uuid import UUID  # noqa: TC003 - pydantic resolves annotations at runtime

from pydantic import AfterValidator, ConfigDict, Field, ValidationInfo, field_validator

from syncr_api.core.schemas import WireModel, WireText
from syncr_api.user_settings.config import (
    VISIBLE_HOURS_MAX,
    VISIBLE_HOURS_MIN,
    ReviewCadence,
)
from syncr_domain.snap import NotAWallTime, not_a_wall_time
from syncr_domain.zones import MAX_ZONE_KEY_LENGTH

_DAY_BOUNDS_DESCRIPTION = (
    "Wall time, no zone. Sets the DEFAULT extent of the Week grid's axis, never a crop: "
    "the axis expands to contain every block in the visible week, because a block hidden "
    "by the axis is a scheduling error the reader cannot see."
)
# The refusals and the imperative are the patch shape's alone: a response is received rather
# than sent, and its own value may be one the patch shape refuses.
_DAY_BOUNDS_ON_PATCH = (
    f"{_DAY_BOUNDS_DESCRIPTION} An offset is refused rather than dropped, and so is a value "
    "below minute resolution: send '07:00', not '07:00+05:00' or '07:00:30'. Any whole "
    "minute is accepted, because these bounds draw the axis rather than a block."
)
_DAY_BOUNDS_ON_READ = (
    f"{_DAY_BOUNDS_DESCRIPTION} Rendered as HH:MM:SS, and a stored bound may carry seconds, "
    "which the patch shape refuses: a client sending this value back normalizes it to the "
    "minute first."
)
_ZONE_DESCRIPTION = "An IANA zone identifier, such as 'Europe/London'."
_VISIBLE_HOURS_DESCRIPTION = (
    "How many hours of the day the grid shows at once. The Week screen narrows this "
    "range further on a short display, so a thirty-minute block keeps its title."
)


def _refuse_a_day_bound_that_is_not_wall_time(value: time) -> time:
    """Refuse a day bound that names a zone or a second, at the boundary.

    Which values those are is the domain's statement of the rule rather than a reading of
    this module's own, so a bound and every other declared time of day cannot disagree about
    what a wall time is. What this adds is a 422 naming the request's own field.

    A bound is stored in a column that holds no offset, so an offset sent here is dropped:
    the stored bound then sits an hour or more from the one that was sent, and the response
    carries the offset that was not kept.

    The fifteen-minute snap is deliberately not read: these bounds draw the axis a block is
    measured against and materialize no block, so any whole minute is a legal bound.
    """
    broken = not_a_wall_time(value)
    if broken is NotAWallTime.CARRIES_A_ZONE:
        raise ValueError(
            "a day bound is wall time and names no zone, so an offset is refused. Send "
            "'07:00' rather than '07:00+05:00': the bound is stored without an offset, so "
            "one sent here is dropped rather than honoured."
        )
    if broken is NotAWallTime.BELOW_MINUTE_RESOLUTION:
        raise ValueError(
            "a day bound is minute-resolution, so seconds are refused. Send '07:00' rather "
            "than '07:00:30': the axis this bound opens on is drawn in whole minutes."
        )
    return value


type DayBound = Annotated[time, AfterValidator(_refuse_a_day_bound_that_is_not_wall_time)]


class SettingsResponse(WireModel):
    """One tenant's settings, and the zone active today.

    ``activeZone`` is resolved through the same function the solver and the assembler
    read, so the screen and the plan cannot disagree about where the user is. One zone,
    for one date: no time in this product is ever shown in two zones at once.
    """

    visible_hours: int = Field(description=_VISIBLE_HOURS_DESCRIPTION)
    day_start: time = Field(description=_DAY_BOUNDS_ON_READ)
    day_end: time = Field(description=_DAY_BOUNDS_ON_READ)
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
    day_start: DayBound | None = Field(default=None, description=_DAY_BOUNDS_ON_PATCH)
    day_end: DayBound | None = Field(default=None, description=_DAY_BOUNDS_ON_PATCH)
    review_cadence: ReviewCadence | None = None
    # Bounded by the domain's own limit, so this rejects nothing the zone lookup would
    # have accepted and the two bounds cannot drift apart.
    home_zone: WireText | None = Field(
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
    zone: WireText = Field(
        min_length=1, max_length=MAX_ZONE_KEY_LENGTH, description=_ZONE_DESCRIPTION
    )

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
        # Pydantic prefixes this with "Value error, ", so it reads as a clause rather than
        # opening with a capital.
        message = (
            f"the end date {end_date} is before the start date {start_date}. Both dates are "
            "inclusive, so a one-day range states the same date twice."
        )
        raise ValueError(message)
