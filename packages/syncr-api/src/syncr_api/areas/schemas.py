"""The wire shapes the Area and Project routes exchange.

Explicit schemas rather than mapped rows, so a column added to a table does not change the
contract by itself and the generated TypeScript changes only when this file does.

Two properties of these shapes are stated in the field descriptions rather than only here,
because the descriptions reach the OpenAPI document and therefore the caller.

**There is no colour anywhere in these shapes.** An Area carries a ``pigmentIndex``, which is
a step of a sealed twelve-step ramp, and the only thing a caller may do with it is choose a
different step. No request accepts a colour, and ``POST`` does not accept a step at all: the
deal assigns it. A colour picker would end the design language on the first day, so the field
that would carry one does not exist.

**A Project has no budget fields**, and the absence is the contract rather than an omission.
It inherits its parent Area's allocation, which is what lets a time-boxed push exist without
carving a new wedge out of the pie.

Both patch requests forbid an unknown field, so a caller sending ``areaId`` to a Project patch
or ``parentId`` to an Area patch gets a stated 422 rather than a value quietly dropped. Both
are immutable for the same reason: the hours already spent were attributed to the Area the
row was declared in, and moving it would rewrite reported history.
"""

from __future__ import annotations

from uuid import UUID  # noqa: TC003 - pydantic resolves annotations at runtime

from pydantic import ConfigDict, Field, field_validator

from syncr_api.areas.config import (
    AREA_NAME_MAX_LENGTH,
    BUDGET_PERCENT_MAX,
    BUDGET_PERCENT_MIN,
    FLOOR_HOURS_MAX,
    FLOOR_HOURS_MIN,
    PROJECT_NAME_MAX_LENGTH,
)
from syncr_api.core.schemas import WireDecimal, WireInstant, WireModel, WireText
from syncr_domain.pigments import PIGMENT_COUNT
from syncr_domain.projects import ProjectStatus

_PIGMENT_DESCRIPTION = (
    f"A step of the sealed ramp, 0 to {PIGMENT_COUNT - 1}. Assigned on creation from the "
    "deal, and re-pickable from the ramp. There is no colour picker: a pigment is a step, "
    "not a value."
)
_BUDGET_PERCENT_DESCRIPTION = (
    "The share of discretionary time REMAINING after every Area's floor is honored, as a "
    f"percentage from {BUDGET_PERCENT_MIN} to {BUDGET_PERCENT_MAX}. Null means the Area "
    "declares no share. Shares summing past 100 across Areas are accepted and reported as "
    "oversubscription, never rejected."
)
_FLOOR_HOURS_DESCRIPTION = (
    "An absolute weekly minimum in hours, which the solver treats as a constraint rather "
    f"than a preference. Bounded at {FLOOR_HOURS_MAX} hours, which rejects a floor no week "
    "could meet. Null means the Area declares no floor."
)
_PARENT_DESCRIPTION = (
    "The Area this one nests under, or null for a top-level Area. Declared once: a child's "
    "time rolls up into its parent in reports, so moving it would rewrite reported history."
)
_AREA_NAME_DESCRIPTION = (
    "Unique within the tenant. Past twelve Areas the ramp repeats, so identity rests on the "
    "hatch and this name."
)


_NOT_NULLABLE_MESSAGE = (
    "this field cannot be cleared, so null is refused rather than read as no change. "
    "Leave it out to keep the stored value."
)


class AreaResponse(WireModel):
    """One Area, and the budget it declares."""

    id: UUID
    parent_id: UUID | None = Field(description=_PARENT_DESCRIPTION)
    name: str = Field(description=_AREA_NAME_DESCRIPTION)
    pigment_index: int = Field(description=_PIGMENT_DESCRIPTION)
    budget_percent: WireDecimal | None = Field(description=_BUDGET_PERCENT_DESCRIPTION)
    floor_hours: WireDecimal | None = Field(description=_FLOOR_HOURS_DESCRIPTION)


class RampReading(WireModel):
    """How much of the sealed ramp this tenant's Areas are using.

    Reported on the list and on every mutation, because both change it. ``statement`` is
    non-null exactly when two Areas hold one step, which is what a thirteenth Area produces:
    the ramp repeats rather than inventing a thirteenth ink, and the interface has to say so.
    """

    pigment_count: int = Field(
        description="How many steps the ramp holds. Sealed: it is always the same number."
    )
    pigments_in_use: int = Field(
        description="How many distinct steps of the ramp this tenant's Areas hold."
    )
    areas_sharing_a_pigment: int = Field(
        description="How many Areas hold a step another Area also holds. Zero until the "
        "ramp is full."
    )
    statement: str | None = Field(
        default=None, description="What identity now rests on, stated when a step is shared."
    )


class AreaView(WireModel):
    """One Area, with the state of the ramp it was dealt from."""

    area: AreaResponse
    ramp: RampReading


class AreasResponse(WireModel):
    """Every Area a tenant has declared, in the order the ramp dealt their pigments.

    A wrapper rather than a bare array. The collection is bounded by how many life categories
    a person holds, so it is not paginated, and an object leaves room for the ramp reading
    beside it.
    """

    areas: list[AreaResponse]
    ramp: RampReading


class AreaCreateRequest(WireModel):
    """An Area to declare.

    No pigment field: creation assigns the next step from the deal, so a caller cannot pick
    one before the Area exists. Re-pick it through ``PATCH`` if the assignment is unwanted.
    """

    model_config = ConfigDict(extra="forbid")

    name: WireText = Field(
        min_length=1, max_length=AREA_NAME_MAX_LENGTH, description=_AREA_NAME_DESCRIPTION
    )
    parent_id: UUID | None = Field(default=None, description=_PARENT_DESCRIPTION)
    budget_percent: WireDecimal | None = Field(
        default=None,
        ge=BUDGET_PERCENT_MIN,
        le=BUDGET_PERCENT_MAX,
        description=_BUDGET_PERCENT_DESCRIPTION,
    )
    floor_hours: WireDecimal | None = Field(
        default=None, ge=FLOOR_HOURS_MIN, le=FLOOR_HOURS_MAX, description=_FLOOR_HOURS_DESCRIPTION
    )


class AreaPatchRequest(WireModel):
    """A partial update. An omitted field is left alone; an explicit null clears one.

    The distinction is the point. ``floorHours: null`` removes the floor, and omitting
    ``floorHours`` leaves whatever floor is stored, so both intentions are expressible.
    ``name`` and ``pigmentIndex`` are not nullable and reject null.

    ``parentId`` is not a member of this shape and an unknown field is rejected, so sending
    one is a stated 422.
    """

    model_config = ConfigDict(extra="forbid")

    name: WireText | None = Field(
        default=None,
        min_length=1,
        max_length=AREA_NAME_MAX_LENGTH,
        description=_AREA_NAME_DESCRIPTION,
    )
    pigment_index: int | None = Field(
        default=None, ge=0, lt=PIGMENT_COUNT, description=_PIGMENT_DESCRIPTION
    )
    budget_percent: WireDecimal | None = Field(
        default=None,
        ge=BUDGET_PERCENT_MIN,
        le=BUDGET_PERCENT_MAX,
        description=_BUDGET_PERCENT_DESCRIPTION,
    )
    floor_hours: WireDecimal | None = Field(
        default=None, ge=FLOOR_HOURS_MIN, le=FLOOR_HOURS_MAX, description=_FLOOR_HOURS_DESCRIPTION
    )

    @field_validator("name", "pigment_index")
    @classmethod
    def _refuse_an_explicit_null(cls, value: object) -> object:
        """Refuse ``null`` on the two fields that have nothing to clear.

        A validator runs only for a field the request actually named, so an omitted field is
        untouched by this and an explicit null is a stated 422. Without it, both would arrive as
        ``None`` and the two intentions would be indistinguishable.
        """
        if value is None:
            raise ValueError(_NOT_NULLABLE_MESSAGE)
        return value


class ProjectResponse(WireModel):
    """One Project. It carries no budget field, because it inherits its Area's allocation."""

    id: UUID
    area_id: UUID = Field(
        description="The one Area this Project sits in. A Project never spans Areas, so time "
        "spent on it counts toward exactly this Area."
    )
    name: str
    deadline: WireInstant | None
    status: ProjectStatus


class ProjectsResponse(WireModel):
    """Every Project a tenant has declared, oldest first."""

    projects: list[ProjectResponse]


class ProjectCreateRequest(WireModel):
    """A Project to declare, inside an Area that already exists."""

    model_config = ConfigDict(extra="forbid")

    area_id: UUID
    name: WireText = Field(min_length=1, max_length=PROJECT_NAME_MAX_LENGTH)
    deadline: WireInstant | None = None
    status: ProjectStatus = ProjectStatus.ACTIVE


class ProjectPatchRequest(WireModel):
    """A partial update. An omitted field is left alone; an explicit null clears the deadline.

    Completing a Project is ``status: "completed"`` here. It leaves the Project's historical
    time attribution intact, because the attribution was always to its Area.

    ``areaId`` is not a member of this shape and an unknown field is rejected.
    """

    model_config = ConfigDict(extra="forbid")

    name: WireText | None = Field(default=None, min_length=1, max_length=PROJECT_NAME_MAX_LENGTH)
    deadline: WireInstant | None = None
    status: ProjectStatus | None = None

    @field_validator("name", "status")
    @classmethod
    def _refuse_an_explicit_null(cls, value: object) -> object:
        """Refuse ``null`` on the two fields that have nothing to clear.

        ``deadline`` is absent from this list on purpose: a Project may genuinely lose its
        deadline, and ``null`` is how that is said.
        """
        if value is None:
            raise ValueError(_NOT_NULLABLE_MESSAGE)
        return value
