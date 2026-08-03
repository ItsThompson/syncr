"""How much of the sealed ramp a tenant's Areas are using, and what a shared step means.

Derived from the Areas that exist rather than counted as they are created, so the reading
cannot drift from the rows and a re-picked pigment is reflected without a second write.

The statement is composed here rather than by each caller, for the same reason an error's
detail is: there is one sentence for one condition, and two callers cannot word it
differently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_domain.pigments import PIGMENT_COUNT

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_api.areas.records import AreaRecord

SHARED_PIGMENT_STATEMENT = (
    f"The ramp holds {PIGMENT_COUNT} pigments and they are all in use, so a pigment is now "
    "shared. Identity rests on the hatch and the Area name from here, and every wedge and bar "
    "already pairs its ink with a hatch. There is no thirteenth pigment to assign."
)


@dataclass(frozen=True, slots=True)
class RampReading:
    """The state of the ramp for one tenant.

    ``statement`` is non-null exactly when two Areas hold one step, which is what a thirteenth
    Area produces: the ramp repeats rather than inventing a thirteenth ink, and the interface
    has to say so.
    """

    pigment_count: int
    pigments_in_use: int
    areas_sharing_a_pigment: int
    statement: str | None


def ramp_reading(areas: Sequence[AreaRecord]) -> RampReading:
    """How much of the ramp ``areas`` are using."""
    held = [area.pigment_index for area in areas]
    shared = sum(1 for index in held if held.count(index) > 1)
    return RampReading(
        pigment_count=PIGMENT_COUNT,
        pigments_in_use=len(set(held)),
        areas_sharing_a_pigment=shared,
        statement=SHARED_PIGMENT_STATEMENT if shared else None,
    )
