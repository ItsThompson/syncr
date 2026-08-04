"""The wire shapes the routine routes exchange.

Explicit schemas rather than mapped rows, so a column added to the table does not change the
contract by itself and the generated TypeScript changes only when this file does.

Three properties of these shapes are stated in the field descriptions rather than only here,
because the descriptions reach the OpenAPI document and therefore the caller.

**There is no Area field anywhere, and no pigment.** A routine defines how much time exists, so
it is not competing for it: it is absent from Area budget arithmetic, and it renders with the
frame wash rather than with an Area's ink. Both requests forbid an unknown field, so sending
``areaId`` is a stated 422 rather than a value quietly dropped.

**``minDurationMinutes`` is the sleep floor.** On the sleep routine it is the negotiable
resource the solver may propose spending and may never spend silently, and there is no settings
field for it. It is the same field on every other routine, defaulting to the target duration,
which is what makes ``Lunch`` incompressible until the user says otherwise.

**``flexBandMinutes`` shifts, it does not shrink.** It is how far a placement may move the
routine from its target time. No operation resizes a routine.

``targetTime`` is wall time and is validated as such. A time carrying an offset is refused
rather than stored with the offset dropped, and so is one carrying seconds: the frame's whole
arithmetic is in minutes, so a sub-minute target would make a duration in minutes untrue by
construction.
"""

from __future__ import annotations

# `time` is used at runtime by the WallTime alias below, so it carries no type-checking
# suppression the way the identifier import does.
from datetime import time
from typing import Annotated
from uuid import UUID  # noqa: TC003 - pydantic resolves annotations at runtime

from pydantic import AfterValidator, ConfigDict, Field, field_validator

from syncr_api.core.schemas import WireModel
from syncr_api.routines.config import ROUTINE_TITLE_MAX_LENGTH
from syncr_domain.routines import (
    MAX_DURATION_MINUTES,
    MAX_FLEX_BAND_MINUTES,
    MIN_DURATION_MINUTES,
)

_TITLE_DESCRIPTION = (
    "What the routine is called, as it reads in a block label on the Week grid. Two routines "
    "may share a title: a morning and an evening 'Shower' are both real."
)
_TARGET_TIME_DESCRIPTION = (
    "Wall time, no date and no zone: 'Wake 05:00' means 05:00 wherever the user is, resolved "
    "against the zone active on each day. Minute resolution, and an offset is refused."
)
_DURATION_DESCRIPTION = (
    f"How long the routine runs, {MIN_DURATION_MINUTES} to {MAX_DURATION_MINUTES} minutes. "
    "Required, because a routine is a span rather than a marker: without a duration there is "
    "nothing to subtract from the day and discretionary time cannot be computed. The upper "
    "bound is a day, because a routine materializes once per local date."
)
_MIN_DURATION_DESCRIPTION = (
    "The elastic floor: how far the routine may be compressed, at most its target duration. "
    "On the sleep routine this is THE SLEEP FLOOR, the negotiable resource a solver may "
    "propose spending and may never spend silently, and it lives nowhere else: there is no "
    "settings field for it. Unstated on creation it equals the target duration, which makes "
    "the routine inelastic, and a routine whose floor equals its target is never offered as a "
    "reduction."
)
_FLEX_BAND_DESCRIPTION = (
    f"How far a placement may SHIFT the routine from its target time, 0 to "
    f"{MAX_FLEX_BAND_MINUTES} minutes. Never how far it may shrink it: nothing resizes a "
    "routine, and its effective duration is derived per week rather than stored. 0 pins it to "
    "the target time."
)

_NOT_NULLABLE_MESSAGE = (
    "no field of a routine is nullable, so null is refused rather than read as no change. "
    "Leave it out to keep the stored value."
)


def _refuse_a_time_that_is_not_wall_time(value: time) -> time:
    """Refuse a target time that names a zone or a second.

    An offset would be dropped by the column and the frame would sit in the wrong hour with
    nothing to say so. A second would survive, and every duration in this module is in minutes,
    so the stored span would be a minute-count of an interval that does not start on a minute.
    """
    if value.tzinfo is not None:
        raise ValueError(
            "a target time is wall time and names no zone, so an offset is refused. "
            "Send '05:00' rather than '05:00+01:00': the zone comes from the day it "
            "materializes on."
        )
    if value.second or value.microsecond:
        raise ValueError(
            "a target time is minute-resolution, so seconds are refused. The frame's "
            "durations are counted in minutes, and a span starting mid-minute could not be "
            "one of them."
        )
    return value


type WallTime = Annotated[time, AfterValidator(_refuse_a_time_that_is_not_wall_time)]


class RoutineResponse(WireModel):
    """One routine: where it targets, how long it runs, and how far it may give.

    No Area and no pigment, and the absence is the contract rather than an omission.
    """

    id: UUID
    title: str = Field(description=_TITLE_DESCRIPTION)
    target_time: time = Field(description=_TARGET_TIME_DESCRIPTION)
    duration_minutes: int = Field(description=_DURATION_DESCRIPTION)
    min_duration_minutes: int = Field(description=_MIN_DURATION_DESCRIPTION)
    flex_band_minutes: int = Field(description=_FLEX_BAND_DESCRIPTION)


class RoutinesResponse(WireModel):
    """Every routine a tenant has declared, in the order the day runs.

    A wrapper rather than a bare array. The collection is bounded by how many fixed points a
    person's day has, so it is not paginated, and an object leaves room for a later field
    without changing the shape of what is already there.
    """

    routines: list[RoutineResponse]


class RoutineCreateRequest(WireModel):
    """A routine to declare.

    ``minDurationMinutes`` may be left out, in which case it equals the target duration and the
    routine is inelastic. ``flexBandMinutes`` may be left out, in which case the routine is
    pinned to its target time.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(
        min_length=1, max_length=ROUTINE_TITLE_MAX_LENGTH, description=_TITLE_DESCRIPTION
    )
    target_time: WallTime = Field(description=_TARGET_TIME_DESCRIPTION)
    duration_minutes: int = Field(
        ge=MIN_DURATION_MINUTES, le=MAX_DURATION_MINUTES, description=_DURATION_DESCRIPTION
    )
    min_duration_minutes: int | None = Field(
        default=None,
        ge=MIN_DURATION_MINUTES,
        le=MAX_DURATION_MINUTES,
        description=_MIN_DURATION_DESCRIPTION,
    )
    flex_band_minutes: int = Field(
        default=0, ge=0, le=MAX_FLEX_BAND_MINUTES, description=_FLEX_BAND_DESCRIPTION
    )


class RoutinePatchRequest(WireModel):
    """A partial update. An omitted field is left alone.

    This is where the sleep floor is set. Nothing on a routine is nullable, so an explicit null
    is refused on every field rather than read as no change: the two intentions would otherwise
    be indistinguishable, and clearing a duration is not a thing a routine survives.

    ``areaId`` is not a member of this shape and an unknown field is rejected, so sending one is
    a stated 422.
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(
        default=None,
        min_length=1,
        max_length=ROUTINE_TITLE_MAX_LENGTH,
        description=_TITLE_DESCRIPTION,
    )
    target_time: WallTime | None = Field(default=None, description=_TARGET_TIME_DESCRIPTION)
    duration_minutes: int | None = Field(
        default=None,
        ge=MIN_DURATION_MINUTES,
        le=MAX_DURATION_MINUTES,
        description=_DURATION_DESCRIPTION,
    )
    min_duration_minutes: int | None = Field(
        default=None,
        ge=MIN_DURATION_MINUTES,
        le=MAX_DURATION_MINUTES,
        description=_MIN_DURATION_DESCRIPTION,
    )
    flex_band_minutes: int | None = Field(
        default=None, ge=0, le=MAX_FLEX_BAND_MINUTES, description=_FLEX_BAND_DESCRIPTION
    )

    @field_validator(
        "title", "target_time", "duration_minutes", "min_duration_minutes", "flex_band_minutes"
    )
    @classmethod
    def _refuse_an_explicit_null(cls, value: object) -> object:
        """Refuse ``null`` on every field, because none of them has anything to clear.

        A validator runs only for a field the request actually named, so an omitted field is
        untouched by this and an explicit null is a stated 422. Without it, both would arrive as
        ``None`` and the two intentions would be indistinguishable.
        """
        if value is None:
            raise ValueError(_NOT_NULLABLE_MESSAGE)
        return value
