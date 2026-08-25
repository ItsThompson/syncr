"""How much of the sealed ramp a tenant's Areas are using.

Derived from the Areas that exist rather than counted as they are created, so the reading
cannot drift from the rows and a re-picked pigment is reflected without a second write.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_domain.pigments import PIGMENT_COUNT

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_api.areas.records import AreaRecord


@dataclass(frozen=True, slots=True)
class RampReading:
    """The state of the ramp for one tenant."""

    pigment_count: int
    pigments_in_use: int


def ramp_reading(areas: Sequence[AreaRecord]) -> RampReading:
    """How much of the ramp ``areas`` are using."""
    held = [area.pigment_index for area in areas]
    return RampReading(
        pigment_count=PIGMENT_COUNT,
        pigments_in_use=len(set(held)),
    )
