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

**The operation is created, claimed and completed here, synchronously.** ``POST .../sync`` must
answer with an ``Operation``, and the work is already done by the time the response is composed, so
there is nothing to hand a worker. It steps the row through the lifecycle service rather than
writing a status, which is what keeps the state machine's ``pending`` to ``running`` to
``succeeded`` true of a request that performs its own work: a row that went straight to
``succeeded`` would be the one operation in the product that never ran.

**Anchors are reconciled here, between the fetch and the sync-state write.** The reconciler is
injected as a protocol declared in :mod:`syncr_api.calendars.anchor_writing`, so this package does
not depend on the anchor package. WHICH of the three attempts happened is decided here, from the
two bits the adapter already returns, so the reconciler is told rather than left to guess.

**Which adapter reads a source is decided by its provider, from a map the caller composed.** The
syncer holds one adapter per provider rather than one adapter: a feed and a Google calendar fail
differently and are read differently, and every rule above them (the sync-state write, the anchor
reconciliation, the due-ness check) is the same for both. Adding a provider is an entry in that map
and a module beside the two that exist.

That distinction matters more than it looks. An unchanged feed and an unreachable feed both carry
an empty event list, so removing anchors on an empty list would clear every commitment of a
healthy feed that answered 304. ``FetchOutcome.reparsed`` distinguishes those two, and
``last_error`` distinguishes a failure from both.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.calendars.config import SYNC_INTERVAL
from syncr_api.calendars.events import FetchOutcome
from syncr_api.solving.config import CALENDAR_SYNC
from syncr_api.solving.outcomes import Succeeded
from syncr_common.logging import get_logger
from syncr_common.metrics import measured

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from syncr_api.calendars.adapters import CalendarAdapter
    from syncr_api.calendars.anchor_writing import AnchorDelta, AnchorWriter
    from syncr_api.calendars.collisions import CollisionDetection
    from syncr_api.calendars.config import CalendarProvider
    from syncr_api.calendars.records import CalendarSourceRecord, SyncStateRecord
    from syncr_api.calendars.repository import CalendarSourceRepository
    from syncr_api.core.clock import Clock
    from syncr_api.solving.lifecycle import OperationLifecycle
    from syncr_api.solving.records import OperationRecord

_log = get_logger("syncr.calendars")

# What one attempt produced, and the state it wrote. Returned together so a caller reports the
# attempt without reading the row back, which is also what lets a failed forced sync log the truth
# rather than a tally of zeroes.
type SyncResult = tuple[FetchOutcome, SyncStateRecord]


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

    The adapters are injected rather than selected here, because which adapter reads which provider
    is a wiring decision: the map a caller passes is what this deployment can read, and a provider
    absent from it is refused by the service before a sync is attempted.
    """

    def __init__(
        self,
        sources: CalendarSourceRepository,
        operations: OperationLifecycle,
        adapters: Mapping[CalendarProvider, CalendarAdapter],
        anchors: AnchorWriter,
        collisions: CollisionDetection,
        clock: Clock,
    ) -> None:
        self._sources = sources
        self._operations = operations
        self._adapters = adapters
        self._anchors = anchors
        self._collisions = collisions
        self._clock = clock

    @property
    def providers(self) -> frozenset[CalendarProvider]:
        """The providers this pass can read, which is what the service's rule is stated over."""
        return frozenset(self._adapters)

    @measured("calendars")
    async def sync(self, source: CalendarSourceRecord) -> SyncResult:
        """One attempt on one source: its anchors reconciled, and its state written either way.

        Returns the state as well as the outcome, so a caller reports what the attempt did without
        reading the row back. An excluded source is not fetched, no anchor of it is touched, and
        its state is handed back untouched: the last attempt on it still describes the last time
        syncr actually read it.
        """
        if not source.included:
            return FetchOutcome(), source.sync_state
        # Keyed rather than searched: the service refuses a provider this pass cannot read before
        # calling, and the runner iterates the map's own keys, so a miss here is a wiring fault
        # rather than a runtime condition.
        outcome, state = await self._adapters[source.provider].fetch(source)
        delta = await self._reconciled(source, outcome, state)
        await self._sources.save_sync_state(source.id, delta.recorded_on(state))
        # After the state is written, and inside the same transaction: a commitment that arrived
        # or moved is what can land on a planned block, and a conflict is detected when it
        # arrives rather than found later by a solve, which is what lets the notice name the
        # block. A pass that removed anchors and a pass that changed nothing both frees space or
        # nothing, so neither can raise one.
        if delta.created or delta.updated:
            await self._collisions.detect(now=self._clock())
        return outcome, state

    async def _reconciled(
        self, source: CalendarSourceRecord, outcome: FetchOutcome, state: SyncStateRecord
    ) -> AnchorDelta:
        """What this attempt did to the source's anchors, chosen by which attempt it was.

        The order of the checks is the invariant. A failed attempt is answered first, so nothing on
        the removal path is reachable from one, and only a read that actually reparsed the feed
        removes an anchor.
        """
        if state.last_error is not None:
            return await self._anchors.mark_possibly_stale(source)
        if not outcome.reparsed:
            return await self._anchors.confirm(source)
        return await self._anchors.reconcile(source, outcome)

    async def sync_now(self, source: CalendarSourceRecord) -> OperationRecord:
        """Sync one source and answer with the operation that did it.

        The operation is created, claimed and completed in this transaction, through the lifecycle
        service, so it takes the same steps a worker-run operation takes.

        Not timed: it delegates to :meth:`sync`, which is, and a timer on both would count one
        attempt twice.
        """
        operation = await self._operations.enqueue(kind=CALENDAR_SYNC, source_id=source.id)
        await self._operations.claim(operation.id)
        outcome, state = await self.sync(source)
        completed = await self._operations.finish(operation.id, Succeeded())
        _log.info(
            "calendars.sync.forced",
            tenant_id=str(source.tenant_id),
            source_id=str(source.id),
            operation_id=str(operation.id),
            failed=state.last_error is not None,
            **outcome.as_log_fields(),
        )
        return completed

    @measured("calendars")
    async def sync_due(self, *, now: datetime) -> SyncPass:
        """Every included anchor source whose poll interval has elapsed, across every provider.

        Due-ness is read off the source rather than kept in the runner, so a restart does not
        reset every source's schedule and a source added mid-interval is polled on the next tick
        rather than waiting out an interval it was not present for.

        The providers come from the adapter map, so a deployment that cannot read one does not
        enumerate its sources: an unreadable provider's sources keep the state they had rather
        than collecting an attempt nothing could have made.
        """
        pass_tally = SyncPass()
        for provider in sorted(self._adapters):
            for source in await self._sources.included_for(provider):
                if not _is_due(source, now=now):
                    continue
                outcome, state = await self.sync(source)
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
