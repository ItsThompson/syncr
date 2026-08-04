"""What syncr intends on the write target, and what one reconciliation did.

Two value types and no behaviour. They are defined here rather than with the writer that will use
them because the adapter's interface is complete from the ticket that reads Google, so the ticket
that writes it changes one method body and no signature.

``syncr_key`` is the whole reconciliation contract. The diff keys on it and on nothing else:
diffing on title and time would churn every event whenever a title changed, and would make a moved
block look like a delete plus an insert. It lives in the provider's extended properties, which is
why an event on the target with no key is one the user created by hand.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syncr_domain.intervals import Interval


@dataclass(frozen=True, slots=True)
class ProjectedEvent:
    """One event as syncr intends it on the write target."""

    syncr_key: str
    interval: Interval
    title: str
    description: str | None = None
    location: str | None = None


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    """What one destructive reconciliation of the write target did.

    ``foreign_deleted`` counts events removed that carried no ``syncr_key``: something the user
    created by hand inside the horizon. Removing it is the contract, and counting it is what keeps
    that removal visible rather than silent.
    """

    inserted: int = 0
    patched: int = 0
    deleted: int = 0
    foreign_deleted: int = 0
    duration_ms: int = 0
