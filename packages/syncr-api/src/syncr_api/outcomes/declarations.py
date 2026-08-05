"""What a request asked to record, as a value the service takes.

A route reads a body and a service applies a rule, so the shape between them is neither the wire's
nor the domain's: the wire carries a pair of instants and two nullable figures, and the domain
value refuses a figure its state does not name. This is the one place the interval is assembled
from the pair, so a service method never reads a request schema and a schema never builds an
interval.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syncr_domain.intervals import Interval
    from syncr_domain.outcomes import OutcomeState


@dataclass(frozen=True, slots=True, kw_only=True)
class Recording:
    """What the user says happened to one block, and which week's plan it was placed by."""

    iso_week: str
    state: OutcomeState
    actual_minutes: int | None
    actual_interval: Interval | None
