"""What one sync pass needs from a provider adapter, declared by the caller that needs it.

The syncer's job is to make one attempt on one source and record what it did. WHICH provider that
source belongs to is a wiring decision, so the requirement is declared here as a protocol and each
provider's module implements it: :class:`~syncr_api.calendars.ics_adapter.IcsAdapter` for a feed,
:class:`~syncr_api.calendars.google_adapter.GoogleAdapter` for a Google calendar. Composition puts
the two together, in ``injection.py`` for a request and ``runner.py`` for a worker tick.

**One method, and it does not raise.** A worker tick polling five sources must not lose four because
one publisher is down or one calendar was deleted, so every failure comes back as a recorded attempt
with a stated reason rather than as an exception. Both adapters state that contract in their own
docstrings; this is where the caller states that it depends on it.

**Two values, because the sync state is not optional.** The events are what the reconciler applies
and the state is what makes staleness computable, and an adapter that returned only the first would
leave the second to a caller that cannot know what happened.

:class:`CalendarWriter` is the other direction and it is a separate protocol on purpose. Only one
provider is written to, the contract is the opposite of the read's -- it RAISES rather than
answering, because a reconciliation that did not finish must not read as one that did -- and nothing
that reads a feed should be reachable from something that can delete a calendar.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from syncr_api.calendars.events import FetchOutcome
    from syncr_api.calendars.projection import ProjectedEvent, ReconcileResult
    from syncr_api.calendars.records import CalendarSourceRecord, SyncStateRecord


class CalendarAdapter(Protocol):
    """One attempt on one source: what it produced, and the sync state to store."""

    async def fetch(self, source: CalendarSourceRecord) -> tuple[FetchOutcome, SyncStateRecord]:
        """Read ``source``, whatever its provider does wrong. Never raises for what it did."""
        ...


class CalendarWriter(Protocol):
    """One destructive reconciliation of the one calendar syncr owns."""

    async def reconcile(
        self, target: CalendarSourceRecord, desired: list[ProjectedEvent]
    ) -> ReconcileResult:
        """Make ``target`` hold exactly ``desired`` over the horizon, or raise saying why not."""
        ...
