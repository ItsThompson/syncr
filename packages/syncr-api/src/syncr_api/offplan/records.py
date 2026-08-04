"""The immutable view of an off-plan row.

A repository hands back one of these rather than a mapped instance, so a service cannot
trigger a load it did not ask for, a fake repository in a service test is a function returning
a frozen dataclass, and nothing downstream can change a row by assigning to it.

The record carries an ``Interval`` where the table carries two columns. That is the whole
reason it exists rather than the row being passed around: every reader of a period wants its
span as one value, and building the interval in one place is what keeps ``[start, end)`` from
being re-derived by each caller.

:meth:`OffPlanPeriodRecord.as_domain` is where persistence meets the invariants.
``syncr_domain.off_plan.OffPlanPeriod`` re-checks the quarter-hour grid, so a row written past
the service, by hand in ``psql`` say, is refused there rather than silently accepted: the same
property ``ZoneProfile`` gives a stored travel override.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_domain.off_plan import OffPlanPeriod

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_domain.identifiers import OffPlanPeriodId, TenantId
    from syncr_domain.intervals import Interval


@dataclass(frozen=True, slots=True)
class OffPlanPeriodRecord:
    """One off-plan period, as persistence knows it."""

    id: OffPlanPeriodId
    tenant_id: TenantId
    interval: Interval
    keep_frame: bool
    label: str | None
    created_at: datetime

    def as_domain(self) -> OffPlanPeriod:
        """The domain value the off-plan invariants are stated over."""
        return OffPlanPeriod(interval=self.interval, keep_frame=self.keep_frame, label=self.label)
