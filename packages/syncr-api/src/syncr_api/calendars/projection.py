"""What syncr intends on the write target, and what one reconciliation did.

Value types and no behaviour. They carry no provider vocabulary, so the writer, the runner, the
metrics, and the notice are all stated over these rather than over Google's shapes.

``syncr_key`` is the whole reconciliation contract. The diff keys on it and on nothing else:
diffing on title and time would churn every event whenever a title changed, and would make a moved
block look like a delete plus an insert. It lives in the provider's extended properties, which is
why an event on the target with no key is one the user created by hand.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syncr_domain.intervals import Interval


class ProjectionAction(StrEnum):
    """What a reconciliation did to one event. The label set of the events metric.

    Four members, one per arm of the diff, so a count reported to a scraper and a count on
    :class:`ReconcileResult` cannot name different things.
    """

    INSERTED = "inserted"
    PATCHED = "patched"
    DELETED = "deleted"
    FOREIGN_DELETED = "foreign_deleted"


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
    that removal visible rather than silent. A sustained non-zero count is a product signal -- the
    user is still editing in their calendar client -- rather than a fault.

    ``unchanged`` is not one of the four actions and is not reported to the events metric. It counts
    the events already correct, which is what makes an ordinary reconciliation cheap, and it is
    carried so a log line can say that a pass wrote nothing because nothing needed writing.
    """

    inserted: int = 0
    patched: int = 0
    deleted: int = 0
    foreign_deleted: int = 0
    duration_ms: int = 0
    unchanged: int = 0

    @property
    def written(self) -> int:
        """How many events this reconciliation changed on the target."""
        return self.inserted + self.patched + self.deleted + self.foreign_deleted

    def by_action(self) -> Mapping[ProjectionAction, int]:
        """This result as one count per action, which is what the events metric observes.

        Total over :class:`ProjectionAction`, so a member with no count cannot exist and the
        exposition carries every action on every reconciliation, including the zeroes: an action
        that appeared only when it was non-zero would make a rate unreadable.
        """
        return {
            ProjectionAction.INSERTED: self.inserted,
            ProjectionAction.PATCHED: self.patched,
            ProjectionAction.DELETED: self.deleted,
            ProjectionAction.FOREIGN_DELETED: self.foreign_deleted,
        }

    def as_log_fields(self) -> dict[str, int]:
        """This result as log fields, under names the redactor does not eat."""
        return {
            "inserted_count": self.inserted,
            "patched_count": self.patched,
            "deleted_count": self.deleted,
            "foreign_deleted_count": self.foreign_deleted,
            "unchanged_count": self.unchanged,
            "duration_ms": self.duration_ms,
        }
