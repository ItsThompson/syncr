"""What a request asked to declare or change, as the service takes it.

These sit between the route that read the request and the service that applies it, so the
service never imports a wire schema and the route never decides anything.

**Both bounds travel as instants rather than as an ``Interval``.** Building one validates it,
and a route is not where a rejected declaration becomes a status: an ``Interval`` constructed
in a handler would raise past every error mapping and answer 500 where the caller deserves a
stated 422. The service builds it, inside the one place that maps a domain rejection.

That is also why :meth:`OffPlanChange.applied_to` returns a declaration rather than a merged
record. A patch moving one bound is checked against the other, and the merged pair is not
known to be a period until it has been through the same rules a new declaration goes through.

Every field of a change is three-valued: absent leaves the stored value alone, a value
replaces it, and null clears it where the column is nullable. Only ``label`` is nullable, so
it is the only field an explicit null can clear.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.core.patches import resolved

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_api.core.patches import Patched
    from syncr_api.offplan.records import OffPlanPeriodRecord


@dataclass(frozen=True, slots=True)
class OffPlanDeclaration:
    """One span to declare off, as the request stated it."""

    start: datetime
    end: datetime
    keep_frame: bool
    label: str | None


@dataclass(frozen=True, slots=True)
class OffPlanChange:
    """What one ``PATCH`` asked to change on an off-plan period."""

    start: Patched[datetime]
    end: Patched[datetime]
    keep_frame: Patched[bool]
    label: Patched[str | None]

    def applied_to(self, current: OffPlanPeriodRecord) -> OffPlanDeclaration:
        """The declaration this change asks the stored period to become."""
        return OffPlanDeclaration(
            start=resolved(self.start, current.interval.start),
            end=resolved(self.end, current.interval.end),
            keep_frame=resolved(self.keep_frame, current.keep_frame),
            label=resolved(self.label, current.label),
        )
