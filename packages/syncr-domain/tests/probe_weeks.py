"""Probe inputs from literals, shared by the probe's example suite and its property suite.

``ProbeInputs`` is a frozen dataclass with a default for every collection precisely so a case can
be stated as a literal, and these builders keep a case to the fields it is about. Every default
here describes an ordinary week in UTC: 168 hours from Monday, ``now`` on Wednesday morning, and
nothing occupied, so a figure a test asserts is a figure that test put there.

The one rule these follow: **nothing here computes any netting**. A case that needs a demand net
of a placement states both, because the whole failure class the probe is shaped against is a
quantity derived twice.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from syncr_domain.feasibility import DeadlineDemand, FloorReservation, ProbeInputs
from syncr_domain.intervals import Interval, IntervalSet
from tests.instants import at

if TYPE_CHECKING:
    from syncr_domain.identifiers import AreaId
    from syncr_domain.intervals import Instant

# Monday 00:00 to the following Monday 00:00, so the span is exactly 168 hours and no daylight
# transition has to be reasoned about. The zone questions belong to `dst_weeks`.
WEEK = Interval(at(0), at(0, day=7))
WEEK_MINUTES = 168 * 60

# Wednesday 09:00. Two days and nine hours have elapsed, leaving 111 hours of capacity.
NOW = at(9, day=2)
CAPACITY_MINUTES = 111 * 60

FITNESS: AreaId = UUID("dddddddd-0000-4000-8000-000000000001")
CAREER: AreaId = UUID("dddddddd-0000-4000-8000-000000000002")
STUDY: AreaId = UUID("dddddddd-0000-4000-8000-000000000003")

NAMES = {FITNESS: "Fitness", CAREER: "Career", STUDY: "Study"}


def a_week(**overrides: object) -> ProbeInputs:
    """An ordinary week with nothing in it, plus whatever the case is about."""
    stated: dict[str, object] = {
        "span": WEEK,
        "now": NOW,
        "computed_at": NOW,
        "input_version": 12,
    }
    stated.update(overrides)
    return ProbeInputs(**stated)  # type: ignore[arg-type]


def a_reservation(area_id: AreaId, minutes: int) -> FloorReservation:
    """What one Area still has to find to reach its floor, already net."""
    return FloorReservation(area_id=area_id, reserved_minutes=minutes, label=NAMES[area_id])


def a_demand(
    area_id: AreaId, minutes: int, deadline: Instant, *, label: str = "F&F Past Papers"
) -> DeadlineDemand:
    """Work one Area owes before one instant, already net and already deadline-scoped."""
    return DeadlineDemand(
        deadline=deadline, remaining_minutes=minutes, area_id=area_id, labels=(label,)
    )


def occupying(*spans: Interval) -> IntervalSet:
    """The spans as one set, for whichever occupancy field a case is about."""
    return IntervalSet(spans)
