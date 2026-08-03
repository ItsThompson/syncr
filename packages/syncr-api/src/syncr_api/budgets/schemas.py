"""The wire shape of one period's budget report.

Every duration is integer minutes, which is section 13's convention throughout: never a string
and never a float, so a client can add two of them without narrowing anything first.

The four figures are separately named on purpose. ``unallocatedMinutes`` is discretionary time
in no block carrying an Area, and ``oversubscriptionMinutes`` is how far the Area targets exceed
discretionary time. They are different quantities, they are routinely confused, and neither is
ever rendered as the other: an oversubscribed budget does not produce a negative residual, it
produces a positive oversubscription and a residual that is still whatever nothing covered.

No Area name appears here. This is arithmetic over identifiers, and the names live on
``/api/v1/areas``, so a rename cannot make a cached report read as another Area's.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - pydantic resolves annotations at runtime
from uuid import UUID  # noqa: TC003 - pydantic resolves annotations at runtime

from pydantic import Field

from syncr_api.core.schemas import WireModel


class PeriodSpan(WireModel):
    """The half-open interval the period covers, ``[start, end)``.

    Present because it is what the denominator was derived from. It may be 167 or 169 hours
    across a daylight-saving transition, and something else again in a zone whose transition is
    not an hour, so a reader that needs the length reads these two instants rather than assuming
    one.
    """

    start: datetime
    end: datetime


class AreaBudgetReading(WireModel):
    """One Area's row of the report.

    ``targetMinutes`` is the Area's floor plus its share of what the floors leave. It is gross:
    netted against nothing, because it is a reporting figure rather than a reservation.
    """

    area_id: UUID
    target_minutes: int = Field(
        description="The Area's floor plus its share of the discretionary time remaining after "
        "every floor is honored."
    )
    actual_minutes: int = Field(
        description="Discretionary minutes covered by blocks carrying this Area."
    )
    rolled_up_target_minutes: int = Field(
        description="This Area's target plus every descendant Area's, because a child's time "
        "counts toward its parent in reports."
    )
    rolled_up_actual_minutes: int = Field(
        description="This Area's actual plus every descendant Area's."
    )


class BudgetResponse(WireModel):
    """One period's discretionary time, and how the Areas divide it."""

    period: str = Field(description="The ISO week the report covers, such as '2026-W07'.")
    span: PeriodSpan
    discretionary_minutes: int = Field(
        description="Total time in the period minus the INTERVAL UNION of the circadian frame, "
        "external anchors, absolutely forbidden windows, and off-plan periods. This is the "
        "denominator every percentage is measured against: never scheduled time, which would "
        "inflate every Area's share by excluding the hours nobody planned."
    )
    unallocated_minutes: int = Field(
        description="Discretionary minutes covered by NO block carrying an Area. Never negative, "
        "and not zero merely because the shares sum to 100."
    )
    oversubscription_minutes: int = Field(
        description="How far the Area targets exceed discretionary time. Zero when they fit. A "
        "separate quantity from unallocatedMinutes, and never rendered as a negative one."
    )
    areas: list[AreaBudgetReading]
