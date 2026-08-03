"""Syncing sources: the one pass a forced sync and a scheduled poll both take.

There is one implementation, called two ways. A route asks for one source now; the worker asks
for every included source of one tenant on a schedule. Both go through :meth:`SourceSyncer.sync`,
so a forced sync and a scheduled poll cannot diverge in what they record.

**The sync state is saved on every attempt.** That is the whole reason this module exists rather
than the route calling the adapter: the write is not optional and it is not the adapter's, so it
happens exactly once, here, whatever the attempt did.

**An excluded source is not fetched.** The user asked for zero anchors from it, so a poll would
spend a request to produce a number the read model discards. A forced sync on one is answered
with a succeeded operation and no fetch, because "nothing happened, by your own instruction" is
the honest answer and an error would be wrong.

**The operation is created and marked succeeded here, synchronously.** ``POST .../sync`` must
answer with an ``Operation`` and the operations table already exists, but the service that owns
an operation's lifecycle does not: **ticket 28 owns the claim, the terminal transitions, the
reaper, and the retention sweep.** Until it lands, this creates the row through the repository
and completes it in the same transaction. It must not grow into a second operation lifecycle.

**Anchors are not written here.** This ticket produces ``RawEvent`` lists; the reconciler that
turns them into anchor rows arrives with the anchors table. So the events are returned to the
caller and counted, and nothing downstream of them exists yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.calendars.config import ICS, SYNC_INTERVAL
from syncr_api.calendars.events import FetchOutcome
from syncr_api.solving.config import CALENDAR_SYNC
from syncr_common.logging import get_logger
from syncr_common.metrics import measured

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_api.calendars.ics_adapter import IcsAdapter
    from syncr_api.calendars.records import CalendarSourceRecord
    from syncr_api.calendars.repository import CalendarSourceRepository
    from syncr_api.core.clock import Clock
    from syncr_api.solving.records import OperationRecord
    from syncr_api.solving.repository import OperationRepository

_log = get_logger("syncr.calendars")


@dataclass(frozen=True, slots=True)
class SyncPass:
    """What one pass over a tenant's sources read, so a caller can report progress.

    A count that changes is how progress is reported in this product, so a pass answers with
    counts rather than with a status.
    """

    attempted: int = 0
    succeeded: int = 0
    events: int = 0
    rejected: int = 0

    def plus(self, outcome: FetchOutcome, *, failed: bool) -> SyncPass:
        return SyncPass(
            attempted=self.attempted + 1,
            succeeded=self.succeeded + (0 if failed else 1),
            events=self.events + len(outcome.events),
            rejected=self.rejected + len(outcome.rejected),
        )

    def as_log_fields(self) -> dict[str, int]:
        """This tally as log fields, under names the redactor does not eat."""
        return {
            "attempt_count": self.attempted,
            "success_count": self.succeeded,
            "event_count": self.events,
            "rejected_count": self.rejected,
        }


class SourceSyncer:
    """One sync pass over one tenant's calendar sources.

    The adapter is injected rather than selected here, because which adapter reads which provider
    is a wiring decision: a syncer built with an ICS adapter syncs ICS sources, and the Google
    one arrives as another entry in the map its caller passes.
    """

    def __init__(
        self,
        sources: CalendarSourceRepository,
        operations: OperationRepository,
        adapter: IcsAdapter,
        clock: Clock,
    ) -> None:
        self._sources = sources
        self._operations = operations
        self._adapter = adapter
        self._clock = clock

    @measured("calendars")
    async def sync(self, source: CalendarSourceRecord) -> FetchOutcome:
        """One attempt on one source, with its sync state written either way.

        An excluded source is not fetched, and its sync state is left exactly as it was: the
        last attempt on it still describes the last time syncr actually read it.
        """
        if not source.included:
            return FetchOutcome()
        outcome, state = await self._adapter.fetch(source)
        await self._sources.save_sync_state(source.id, state)
        return outcome

    @measured("calendars")
    async def sync_now(self, source: CalendarSourceRecord) -> OperationRecord:
        """Sync one source and answer with the operation that did it.

        The operation is created and completed in this transaction. Ticket 28 owns the claim and
        the terminal transitions; this must not become a second operation lifecycle.
        """
        now = self._clock()
        operation = await self._operations.enqueue(
            kind=CALENDAR_SYNC, scheduled_for=now, source_id=source.id
        )
        outcome = await self.sync(source)
        completed = await self._operations.mark_succeeded(operation.id, at=now)
        _log.info(
            "calendars.sync.forced",
            tenant_id=str(source.tenant_id),
            source_id=str(source.id),
            operation_id=str(operation.id),
            **outcome.as_log_fields(),
        )
        return completed

    @measured("calendars")
    async def sync_due(self, *, now: datetime) -> SyncPass:
        """Every included anchor source of this tenant whose poll interval has elapsed.

        Due-ness is read off the source rather than kept in the runner, so a restart does not
        reset every feed's schedule and a source added mid-interval is polled on the next tick
        rather than waiting out an interval it was not present for.
        """
        pass_tally = SyncPass()
        for source in await self._sources.included_for(ICS):
            if not _is_due(source, now=now):
                continue
            outcome, state = await self._adapter.fetch(source)
            await self._sources.save_sync_state(source.id, state)
            pass_tally = pass_tally.plus(outcome, failed=state.last_error is not None)
        if pass_tally.attempted:
            _log.info("calendars.sync.polled", **pass_tally.as_log_fields())
        return pass_tally


def _is_due(source: CalendarSourceRecord, *, now: datetime) -> bool:
    """Whether this source's poll interval has elapsed.

    A source that has never been attempted is due immediately. The interval is measured from the
    last ATTEMPT rather than the last success, so a feed that has been down for a week is retried
    on the same schedule as one that works rather than being hammered every tick.
    """
    attempted = source.sync_state.last_attempt_at
    return attempted is None or now - attempted >= SYNC_INTERVAL
