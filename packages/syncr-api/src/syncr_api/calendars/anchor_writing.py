"""What one sync pass needs from the anchor reconciler, declared by the caller that needs it.

The syncer's job is to make one attempt on one source and record what it did. Writing anchor
rows is not that job, and the anchor package is not this package's dependency: so the
requirement is declared here, as a protocol and the tally it answers with, and the anchor
package implements it. Composition is what puts the two together, in ``calendars/injection.py``
for a request and ``calendars/runner.py`` for a worker tick.

**Three methods, because there are three attempts.** The adapter distinguishes them already and
each has a different consequence for the anchors a source contributed:

| Attempt | ``FetchOutcome.reparsed`` | ``last_error`` | What the anchors do |
|---|---|---|---|
| the feed was read | ``True`` | unset | reconciled: created, updated, and **removed** |
| the feed was unchanged | ``False`` | unset | confirmed: retained, and no longer possibly stale |
| the feed was unreachable | ``False`` | set | retained, and marked **possibly stale** |

The third row is the invariant that matters. A failed sync must not remove an anchor: the
occupancy read on the last success is still the best syncr has, and a feed being down is not
evidence that a lecture was cancelled. Only a SUCCESSFUL read removes one, which is exactly
what ``reparsed`` distinguishes: an unchanged feed and an unreachable feed both carry an empty
event list, and removing on an empty list would clear every anchor of a feed that answered 304.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from syncr_api.calendars.events import FetchOutcome
    from syncr_api.calendars.records import CalendarSourceRecord, SyncStateRecord


@dataclass(frozen=True, slots=True)
class AnchorDelta:
    """What one attempt did to the anchors a source contributes.

    ``current`` is the count AFTER the attempt and is read from the rows rather than derived
    from the other three, so the number the panel reports is the number the table holds even if
    a previous attempt recorded a count that has since become wrong.
    """

    created: int = 0
    updated: int = 0
    removed: int = 0
    marked_stale: int = 0
    current: int = 0

    def recorded_on(self, state: SyncStateRecord) -> SyncStateRecord:
        """``state`` with this pass's own count of the rows the source contributes.

        The adapter fills ``anchors_current`` with the count of EVENTS it parsed, which is the only
        number it can answer. The two differ whenever two events reach one reconciliation key, and
        the panel reports anchors, so the reconciler's count is what gets written.

        Applied after every attempt rather than only after a successful parse. The count is read
        from the table, so an unchanged or unreachable feed writes back the number the rows actually
        hold instead of carrying forward one an earlier attempt recorded, and a count that drifted
        for any reason is corrected by the next poll rather than persisting.

        Only that one field moves: a rewritten state that dropped the error would make a failed
        sync read as a success, which is the failure the sync-state rules exist to prevent.
        """
        return replace(state, anchors_current=self.current)

    def as_log_fields(self) -> dict[str, int]:
        """This tally as log fields, under names the redactor does not eat.

        Counts only. An anchor's title and its location are never logged: a line carrying
        `Kontron Placement Interview` discloses a job search to anyone with log access.
        """
        return {
            "anchors_created": self.created,
            "anchors_updated": self.updated,
            "anchors_removed": self.removed,
            "anchors_marked_stale": self.marked_stale,
            "anchors_current": self.current,
        }


class AnchorWriter(Protocol):
    """The reconciler, as one sync pass needs it."""

    async def reconcile(self, source: CalendarSourceRecord, outcome: FetchOutcome) -> AnchorDelta:
        """Make this source's anchors match what the feed just produced.

        Called only for an attempt that actually read the feed. Anchors absent from ``outcome``
        are removed, which is what makes a commitment cancelled at the source stop occupying
        the plan.
        """
        ...

    async def confirm(self, source: CalendarSourceRecord) -> AnchorDelta:
        """Record that this source's anchors are current, without reparsing anything.

        For a feed that answered "unchanged": the last parse still stands, so nothing is
        created or removed and anything marked possibly stale is no longer stale.
        """
        ...

    async def mark_possibly_stale(self, source: CalendarSourceRecord) -> AnchorDelta:
        """Retain this source's anchors and mark them possibly stale.

        For a feed that could not be read. Nothing is removed: a failed sync is not evidence
        that a commitment was cancelled.
        """
        ...
