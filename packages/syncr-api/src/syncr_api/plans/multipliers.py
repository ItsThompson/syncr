"""The learned duration multiplier, and why it is applied here rather than in the solver.

A user underestimates. The duration multiplier is what the learning layer fits per Area to
correct for it, and it **sizes work rather than expressing a preference**: nothing in the
objective reads it.

It is applied during assembly, so a plan is always solved against already-corrected durations.
Applied in the solver instead, the same task would have two durations depending on which code
path read it, and the golden-file tests would encode the multiplier rather than the objective.

**A parameter below its maturity gate is not applied at all**, rather than applied at a reduced
weight: a half-fitted number is worse than a hand-tuned one. Absence is how that is expressed.
A fitter that has not cleared an Area's gate writes no entry for it, so an empty map is what
"nothing has been learned yet" looks like, and an Area the map does not name is scaled by
nothing.

An unreadable entry degrades to the same thing rather than failing the assembly. The map is
written by our own fitter, so a malformed value is a defect upstream; taking the assembly down
over it would stop every pin, every verdict, and every solve for an optional correction, and
the honest fallback is exactly the state of an Area nothing has been fitted for.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from math import isfinite
from typing import TYPE_CHECKING
from uuid import UUID

from syncr_common.logging import get_logger
from syncr_domain.habits import Duration
from syncr_domain.snap import nearest_snap_multiple

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syncr_api.learned.records import WeightSetRecord
    from syncr_domain.identifiers import AreaId

_log = get_logger("syncr.plans")

# What an Area nothing has been fitted for is scaled by.
NOT_APPLIED = Decimal(1)


class DurationMultipliers:
    """What the user's stated durations are worth, per Area, under the active weight set."""

    __slots__ = ("_by_area",)

    def __init__(self, by_area: Mapping[AreaId, Decimal]) -> None:
        self._by_area = dict(by_area)

    @classmethod
    def of(cls, weights: WeightSetRecord | None) -> DurationMultipliers:
        """The multipliers the active weight set carries, or none at all.

        ``None`` is a tenant with no active weight set. That is not the normal state, because
        provisioning seeds the hand-tuned set, and it is still the correct reading: a week
        assembled without weights is sized at the user's own estimates.
        """
        if weights is None:
            return cls({})
        return cls(_readable(weights.duration_multiplier, version=weights.version))

    def of_area(self, area_id: AreaId) -> Decimal:
        """This Area's multiplier, or one for an Area nothing has been fitted for."""
        return self._by_area.get(area_id, NOT_APPLIED)

    def scale_estimate(self, minutes: int, *, area_id: AreaId) -> int:
        """A stated estimate, corrected. Rounded half to even, so it drifts in no direction.

        Not moved onto the fifteen-minute grid, because an estimate is a total to be divided
        into chunks rather than the length of one block. What the chunks owe the grid is a
        question about the chunk, and it is answered where a chunk is declared.
        """
        scaled = Decimal(minutes) * self.of_area(area_id)
        return int(scaled.to_integral_value(rounding=ROUND_HALF_EVEN))

    def scale_duration(self, duration: Duration, *, area_id: AreaId) -> Duration:
        """An occurrence's duration, corrected if it is elastic and left alone if it is fixed.

        A fixed duration is the user's claim that the occurrence is this long or nothing, so
        scaling it would overrule a declaration. An elastic range is the room the solver may
        size within, and correcting the room is what the multiplier is for.

        Both scaled bounds are moved back onto the grid, because a block starts and ends on it
        and a scaled 45 minutes is 54.
        """
        multiplier = self.of_area(area_id)
        if duration.is_fixed or multiplier == NOT_APPLIED:
            return duration
        return Duration(
            min_minutes=self._scaled_to_grid(duration.min_minutes, multiplier),
            max_minutes=self._scaled_to_grid(duration.max_minutes, multiplier),
        )

    def _scaled_to_grid(self, minutes: int, multiplier: Decimal) -> int:
        scaled = Decimal(minutes) * multiplier
        return nearest_snap_multiple(int(scaled.to_integral_value(rounding=ROUND_HALF_EVEN)))


def _readable(stored: Mapping[str, object], *, version: int) -> Mapping[AreaId, Decimal]:
    """The entries of a stored map that name an Area and a positive finite factor.

    Every other entry is dropped and reported, because the alternative readings are worse: a
    non-positive factor would size a task at nothing and a non-finite one would size it at
    everything, and either would look like a fitted correction.
    """
    readable: dict[AreaId, Decimal] = {}
    unreadable: list[str] = []
    for key, value in stored.items():
        area_id = _an_area_id(key)
        factor = _a_factor(value)
        if area_id is None or factor is None:
            unreadable.append(key)
            continue
        readable[area_id] = factor
    if unreadable:
        _log.warning(
            "plans.duration_multiplier.unreadable",
            weight_set_version=version,
            entries=len(unreadable),
        )
    return readable


def _an_area_id(key: object) -> AreaId | None:
    if not isinstance(key, str):
        return None
    try:
        return UUID(key)
    except ValueError:
        return None


def _a_factor(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if not isfinite(value) or value <= 0:
        return None
    # Through `str` rather than from the float directly, so the stored 1.2 scales as 1.2
    # rather than as its binary expansion, and two assemblies of one row agree exactly.
    return Decimal(str(value))
