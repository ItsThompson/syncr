"""A stored weight set, as the value the objective reads. One direction: nothing writes back.

The solver takes plain floats and maps of them, and knows nothing about versions, origins, maturity,
or when a fit ran. Those are storage's concerns, so the projection happens here rather than the
solver growing a second constructor that takes a record.

## The two fitted maps, and the shape each is stored in

``time_of_day_fitness`` is a curve per Area: ``{area: [24 values]}``, one per hour of the local day,
each from 0 to 1. ``skip_probability`` is nested rather than keyed on a joined string, because the
domain key is a PAIR and a JSONB object cannot hold a tuple: ``{area: {bucket: share}}`` keeps both
halves addressable in a ``psql`` session and needs no delimiter an identifier could contain. The
offline fitters write both, and this is the reader.

**An unreadable entry is DROPPED and reported rather than failing the projection**, which is the
reading ``plans.multipliers`` already takes for the third map. The maps are written by our own
fitter, so a malformed value is a defect upstream; taking every solve down over it would stop the
whole product for an optional correction, and the honest fallback is exactly the state of an Area
nothing has been fitted for. What is NOT tolerated is a value inside the map that would change the
arithmetic silently: a curve missing an hour is dropped whole rather than read short, because a
curve applied to some of an Area's blocks and not others is the least explainable failure an Area
could have.

**An absent entry is not the same as one fitted at zero.** A parameter below its maturity gate is
not applied at all rather than at a reduced weight, and absence is how the weight set expresses
that. Read as a default, an absent fitness would enter the misfit term as ``1 - 0`` and become the
largest fitted charge it can carry, which is the inverse of the rule.

``duration_multiplier`` is deliberately absent from this projection. It is read by the ASSEMBLER,
which applies it to estimates and elastic durations before a solve begins, so the solver never sees
it: applying it here as well would correct one estimate twice.
"""

from __future__ import annotations

from math import isfinite
from typing import TYPE_CHECKING
from uuid import UUID

from syncr_common.logging import get_logger
from syncr_solver.weights import HOURS_PER_DAY, TimeBucket, WeightSet

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syncr_api.learned.records import WeightSetRecord
    from syncr_domain.identifiers import AreaId

_log = get_logger("syncr.learned")


def as_weight_set(stored: WeightSetRecord) -> WeightSet:
    """The weights ``stored`` names, as the value one solve is produced under."""
    return WeightSet(
        deadline_risk=stored.deadline_risk,
        budget_deviation=stored.budget_deviation,
        time_of_day_misfit=stored.time_of_day_misfit,
        fragmentation=stored.fragmentation,
        churn=stored.churn,
        context_switch=stored.context_switch,
        staleness=stored.staleness,
        context_switch_cost=stored.context_switch_cost,
        churn_tolerance=stored.churn_tolerance,
        time_of_day_fitness=fitted_curves(stored.time_of_day_fitness, version=stored.version),
        skip_probability=fitted_probabilities(stored.skip_probability, version=stored.version),
    )


def fitted_curves(
    stored: Mapping[str, object], *, version: int
) -> Mapping[AreaId, tuple[float, ...]]:
    """The entries of a stored fitness map that name an Area and a whole day of shares."""
    readable: dict[AreaId, tuple[float, ...]] = {}
    unreadable: list[str] = []
    for key, value in stored.items():
        area_id = _an_area_id(key)
        curve = _a_curve(value)
        if area_id is None or curve is None:
            unreadable.append(str(key))
            continue
        readable[area_id] = curve
    _report(unreadable, named="time_of_day_fitness", version=version)
    return readable


def fitted_probabilities(
    stored: Mapping[str, object], *, version: int
) -> Mapping[tuple[AreaId, TimeBucket], float]:
    """The entries of a stored skip map that name an Area, a known bucket, and a share."""
    readable: dict[tuple[AreaId, TimeBucket], float] = {}
    unreadable: list[str] = []
    for key, buckets in stored.items():
        area_id = _an_area_id(key)
        if area_id is None or not isinstance(buckets, dict):
            unreadable.append(str(key))
            continue
        for name, value in buckets.items():
            bucket = _a_bucket(name)
            share = _a_share(value)
            if bucket is None or share is None:
                unreadable.append(f"{key}.{name}")
                continue
            readable[(area_id, bucket)] = share
    _report(unreadable, named="skip_probability", version=version)
    return readable


def _report(unreadable: list[str], *, named: str, version: int) -> None:
    if unreadable:
        _log.warning(
            "learned.fitted_parameter.unreadable",
            parameter=named,
            weight_set_version=version,
            entries=len(unreadable),
        )


def _an_area_id(key: object) -> AreaId | None:
    if not isinstance(key, str):
        return None
    try:
        return UUID(key)
    except ValueError:
        return None


def _a_curve(value: object) -> tuple[float, ...] | None:
    """A whole day of shares, or nothing because the stored list is not one.

    Dropped WHOLE rather than padded or clipped. A curve missing an hour would be applied to some of
    an Area's blocks and not others depending on when they start, and the solver refuses one anyway,
    so reading it short would trade an explainable absence for an unexplainable solve failure.
    """
    if not isinstance(value, list) or len(value) != HOURS_PER_DAY:
        return None
    shares = [_a_share(one) for one in value]
    if any(one is None for one in shares):
        return None
    return tuple(one for one in shares if one is not None)


def _a_bucket(name: object) -> TimeBucket | None:
    if not isinstance(name, str):
        return None
    try:
        return TimeBucket(name)
    except ValueError:
        return None


def _a_share(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if isfinite(value) and 0.0 <= value <= 1.0 else None
