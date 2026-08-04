"""The immutable view of a routine row.

A repository hands back one of these rather than a mapped instance, so a service cannot
trigger a load it did not ask for, a fake repository in a service test is a function returning
a frozen dataclass, and nothing downstream can change a row by assigning to it.

This is not the wire shape: ``schemas.py`` owns that, so a column added here does not appear in
a response by itself. It is not the frame's arithmetic shape either:
``syncr_domain.routines.RoutineSpan`` is what an occurrence and the elasticity predicate are
stated over, and :meth:`RoutineRecord.as_span` is where the two meet.

There is no Area field, and there is no pigment. A routine defines how much time exists rather
than competing for it, so it is absent from Area budget arithmetic entirely.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_domain.identifiers import RoutineId
from syncr_domain.routines import RoutineSpan

if TYPE_CHECKING:
    from datetime import datetime, time

    from syncr_domain.identifiers import TenantId

# Declared here rather than among the domain's identifier aliases, because a span carries no
# identity: the row is what has one, and the domain's frame arithmetic never needs it.
# Re-exported rather than declared, so a routine's identifier has one spelling. The pure
# package owns it because a pure shape names one: a frame entry says which routine it
# materialized from.
__all__ = ["RoutineId", "RoutineRecord"]


@dataclass(frozen=True, slots=True)
class RoutineRecord:
    """One routine, as persistence knows it."""

    id: RoutineId
    tenant_id: TenantId
    title: str
    target_time: time
    duration_minutes: int
    min_duration_minutes: int
    flex_band_minutes: int
    created_at: datetime

    def as_span(self) -> RoutineSpan:
        """The domain value the frame's arithmetic is stated over.

        Constructing it is also what validates the row's span: the invariants live on
        ``RoutineSpan``, so a caller that builds one has already checked them.
        """
        return RoutineSpan(
            target_time=self.target_time,
            duration_minutes=self.duration_minutes,
            min_duration_minutes=self.min_duration_minutes,
            flex_band_minutes=self.flex_band_minutes,
        )
