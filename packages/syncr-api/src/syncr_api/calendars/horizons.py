"""How far ahead this tenant's calendar is read, and the plan is kept: one reading, two forms.

The figure is the write target's ``horizon_days`` when one is set, and the default otherwise. Four
consumers ask it, and every one of them has to get the same answer: recurrence expansion widens its
read to it, the projection reconciles over it, the plan horizon maintainer plans exactly the weeks
it covers, and conflict detection reads exactly those weeks' plans. Two readings would let the
calendar be read over one span, planned over another, and detected against a third.

A tenant that has not designated a write target still reads anchors and still needs its weeks
planned, so neither ingest nor the plan horizon waits on a projection bound being configured.

Here rather than in ``injection.py``, where both functions used to live, because this is a READ and
that module is the calendars package's composition root: a consumer in another package that asked
for the figure had to import the composition root to get it, which is how the first import cycle in
this package appeared.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Protocol

from syncr_api.calendars.config import HORIZON_DAYS_DEFAULT
from syncr_domain.intervals import Interval

if TYPE_CHECKING:
    from datetime import datetime


class HorizonTarget(Protocol):
    """The horizon length the designated write target exposes."""

    @property
    def horizon_days(self) -> int | None: ...


class HorizonSourceReader(Protocol):
    """The write-target reading needed to resolve a projection horizon."""

    async def write_target(self) -> HorizonTarget | None: ...


async def read_horizon_days(sources: HorizonSourceReader) -> int:
    """How many days ahead the projection reaches: the write target's horizon, else the default."""
    target = await sources.write_target()
    return HORIZON_DAYS_DEFAULT if target is None else target.horizon_days or HORIZON_DAYS_DEFAULT


async def read_ingest_horizon(sources: HorizonSourceReader, *, now: datetime) -> Interval:
    """How far ahead recurrence is expanded, as the span the adapters clip to.

    From ``now`` rather than from the start of the week, because an occurrence that began before
    now and runs into it is still occupancy, and the parser widens the lower bound by each
    event's own length to catch exactly that.
    """
    return Interval(now, now + timedelta(days=await read_horizon_days(sources)))
