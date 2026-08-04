"""The Google adapter: the same two-value return the ICS one has, over a different provider.

One method a caller uses, one it will use, and one that lists an account's calendars during setup.
What it hides is the whole shape of Google's read model: an opaque sync token, a provider that
invalidates it whenever it likes, a window a sync token forbids sending, and deletions that arrive
as events with no times at all.

**Two answers and three sync states, and none of them raises.** A worker tick polling five
calendars must not lose four because one calendar is gone, so every failure is a recorded attempt
with a stated reason. That is the ICS adapter's contract, kept deliberately: the syncer writes sync
state on every attempt and neither adapter gets to opt out.

**The sync token is a CHANGE DETECTOR, and the read that follows it is a full one.** An incremental
answer is a delta: "these entries changed, everything else is as you last saw it". Handing that to a
reconciler as though it were the calendar would delete every anchor the provider did not happen to
mention, and applying it as a delta is a second reconciliation path with its own removal rule. So an
incremental read that reports nothing changed is answered exactly as an ICS ``304`` is, and one that
reports any change is followed by a full read of the horizon, whose events ARE the calendar. What
the token buys is the poll that costs one small request instead of a fortnight of events, which is
the saving Google's own guide describes; what it costs is one extra request on a poll that found a
change. The three attempt kinds the syncer already distinguishes stay three.

**The horizon is applied here, not at the provider.** Google refuses ``timeMin`` beside a sync
token, so the detector read sees the whole calendar and the full read that follows is windowed. A
change
outside the horizon therefore triggers a windowed read that finds nothing new, which is a wasted
request rather than a wrong answer.

**The cursor is bounded before it is stored.** A sync token is a value Google chooses the length of,
and the column that holds it is finite. An oversize write does not fail one source: it rolls back
the transaction the whole tenant's sync pass is in, so every sibling source loses the sync state it
had already earned. An oversize token is dropped, the next read is full, and the state says why.

**No title and no token reaches a log line.** Every line here carries identifiers and counts, which
is what the redactor's key names already enforce; the event titles this adapter handles are the most
sensitive values in the product.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from syncr_api.calendars.config import GOOGLE_COMPONENT, SYNC_INTERVAL, UNKNOWN_LINE
from syncr_api.calendars.events import FetchOutcome, RawEvent, RejectedComponent
from syncr_api.calendars.google_client import (
    CalendarsRead,
    EventsRead,
    GoogleReadFailed,
    SyncTokenExpired,
)
from syncr_api.calendars.google_cursors import bounded_cursor, sync_token_of
from syncr_api.calendars.google_values import ReadSpan, read_span
from syncr_api.calendars.sync_state import (
    recorded_failure,
    recorded_success,
    recorded_unchanged,
)
from syncr_common.logging import get_logger
from syncr_common.metrics import measured

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_api.calendars.google_client import CalendarsAnswer, GoogleCalendarClient
    from syncr_api.calendars.google_payloads import GoogleEventPayload
    from syncr_api.calendars.projection import ProjectedEvent, ReconcileResult
    from syncr_api.calendars.records import CalendarSourceRecord, SyncStateRecord
    from syncr_api.core.clock import Clock
    from syncr_domain.intervals import Interval
    from syncr_domain.zones import ZoneProfile

_log = get_logger("syncr.calendars")

type GoogleFetch = tuple[FetchOutcome, SyncStateRecord]

# What a rate-limited read's message adds: when syncr will try again. The poll interval is the
# answer, because a read that backed off and stopped is retried by the next scheduled poll rather
# than by a timer of its own.
_BACKING_OFF: Final = "Sync is backing off and will try again at"

# Why a full read happened while a cursor was held. Both are recorded on the source, because a
# source quietly re-reading a whole calendar every poll looks healthy and is not.
CURSOR_INVALIDATED: Final = (
    "Google invalidated the incremental sync token, so this read was a full one"
)
CURSOR_UNSTORABLE: Final = (
    "Google issued a sync token too long to store, so the next read will be a full one"
)
CHANGES_DETECTED: Final = (
    "the incremental read reported changes, so the calendar was read in full to place them"
)


class GoogleAdapter:
    """Read one Google calendar, list an account's calendars, and own the write target's shape.

    The zone profile and the horizon are constructor dependencies rather than per-call arguments,
    because both belong to the tenant rather than to the source: one adapter is built per tenant per
    sync pass, and every calendar it reads resolves an all-day span the same way.
    """

    def __init__(
        self, *, client: GoogleCalendarClient, profile: ZoneProfile, horizon: Interval, clock: Clock
    ) -> None:
        self._client = client
        self._profile = profile
        self._horizon = horizon
        self._clock = clock

    @measured("google_adapter")
    async def list_calendars(self) -> CalendarsAnswer:
        """Every calendar the connected account holds, for selection during setup.

        Answers with the failure rather than raising it, so the service maps it to a status and this
        module stays free of HTTP vocabulary.
        """
        answer = await self._client.list_calendars()
        if isinstance(answer, CalendarsRead):
            _log.info(
                "calendars.google.listed",
                calendar_count=len(answer.calendars),
                attempt_count=answer.attempts,
            )
        else:
            _log.warning("calendars.google.list_failed", attempt_count=answer.attempts)
        return answer

    @measured("google_adapter")
    async def fetch(self, source: CalendarSourceRecord) -> GoogleFetch:
        """One attempt on ``source``: what it produced, and the sync state to store."""
        now = self._clock()
        identity = {"source_id": str(source.id), "tenant_id": str(source.tenant_id)}
        held = sync_token_of(source.sync_state.cursor)
        if held is None:
            return await self._read_fully(source, at=now, identity=identity)
        return await self._after_detecting(source, held, at=now, identity=identity)

    async def reconcile(
        self, target: CalendarSourceRecord, desired: list[ProjectedEvent]
    ) -> ReconcileResult:
        """Make ``target`` match ``desired`` over the horizon, destructively.

        Not implemented here. The interface is complete from this module so the projection writer
        changes one method body and no signature: ticket 30 owns the diff, the delete of an event
        syncr did not intend, and the count of the ones the user created by hand.
        """
        message = (
            f"projecting the plan onto {target.display_name!r} is not implemented yet, so the "
            f"{len(desired)} events syncr intends were not written. Reading anchors from every "
            "source still works."
        )
        raise NotImplementedError(message)

    async def _after_detecting(
        self, source: CalendarSourceRecord, held: str, *, at: datetime, identity: dict[str, str]
    ) -> GoogleFetch:
        """Ask what changed since the held token, and decide what that means.

        Three answers: nothing changed, something changed, or the token is no longer accepted. The
        first is the cheap poll the token exists for; the other two are a full read, and each says
        so on the source.
        """
        answer = await self._client.list_events(
            source.external_id, sync_token=held, window=self._horizon
        )
        if isinstance(answer, GoogleReadFailed):
            return self._failed(source, answer, at=at, identity=identity)
        if isinstance(answer, SyncTokenExpired):
            _log.info("calendars.google.sync_token_invalidated", **identity)
            return await self._read_fully(
                source,
                at=at,
                identity=identity,
                spent=answer.attempts,
                resync_reason=CURSOR_INVALIDATED,
            )
        if answer.events:
            _log.info(
                "calendars.google.changes_detected", **identity, changed_count=len(answer.events)
            )
            return await self._read_fully(
                source,
                at=at,
                identity=identity,
                spent=answer.attempts,
                resync_reason=CHANGES_DETECTED,
            )
        return self._unchanged(source, answer, at=at, identity=identity)

    async def _read_fully(
        self,
        source: CalendarSourceRecord,
        *,
        at: datetime,
        identity: dict[str, str],
        spent: int = 0,
        resync_reason: str | None = None,
    ) -> GoogleFetch:
        """Read the calendar over the horizon, and record what it holds.

        ``spent`` carries the attempts a detector read already cost, so the count on the source is
        what the whole poll cost rather than what its second half did.
        """
        answer = await self._client.list_events(
            source.external_id, sync_token=None, window=self._horizon
        )
        if isinstance(answer, SyncTokenExpired | GoogleReadFailed):
            # A 410 cannot follow a read that sent no token; a failure can. Either way the attempt
            # is recorded, so a source that could not be read never looks like one that is empty.
            return self._failed(
                source,
                GoogleReadFailed(reason=_reason_of(answer), attempts=spent + answer.attempts),
                at=at,
                identity=identity,
            )
        outcome = self._outcome(answer)
        cursor = bounded_cursor(answer.sync_token)
        unstorable = answer.sync_token is not None and cursor is None
        _log.info("calendars.google.read", **identity, **outcome.as_log_fields())
        return outcome, recorded_success(
            outcome,
            at=at,
            cursor=cursor,
            attempts=spent + answer.attempts,
            resync_reason=CURSOR_UNSTORABLE if unstorable else resync_reason,
        )

    def _unchanged(
        self,
        source: CalendarSourceRecord,
        answer: EventsRead,
        *,
        at: datetime,
        identity: dict[str, str],
    ) -> GoogleFetch:
        """Record a poll that found no change: a success that read nothing.

        The token is replaced by the fresh one Google issued, and dropped when it will not fit,
        which costs one full read on the next poll rather than a failed write.
        """
        _log.info("calendars.google.unchanged", **identity, attempt_count=answer.attempts)
        cursor = bounded_cursor(answer.sync_token) or source.sync_state.cursor
        return FetchOutcome(), recorded_unchanged(
            source.sync_state, at=at, cursor=cursor, attempts=answer.attempts
        )

    def _failed(
        self,
        source: CalendarSourceRecord,
        answer: GoogleReadFailed,
        *,
        at: datetime,
        identity: dict[str, str],
    ) -> GoogleFetch:
        """Record an attempt that read nothing, keeping everything the source already had."""
        _log.warning(
            "calendars.google.unreachable",
            **identity,
            attempt_count=answer.attempts,
            rate_limited=answer.rate_limited,
            anchors_retained=source.sync_state.anchors_current,
        )
        return FetchOutcome(), recorded_failure(
            source.sync_state,
            at=at,
            reason=self._stated(answer, at=at),
            attempts=answer.attempts,
        )

    def _stated(self, answer: GoogleReadFailed, *, at: datetime) -> str:
        """The failure as the source's panel reads it, with the next attempt named when it helps."""
        if not answer.rate_limited:
            return answer.reason
        return f"{answer.reason}. {_BACKING_OFF} {(at + SYNC_INTERVAL):%H:%M} UTC."

    def _outcome(self, answer: EventsRead) -> FetchOutcome:
        """Partition one full read's events into what was kept, rejected, and dropped."""
        events: list[RawEvent] = []
        rejected: list[RejectedComponent] = []
        cancelled = 0
        placed = 0
        unplaced = 0
        for payload in answer.events:
            if payload.is_cancelled:
                # A full read asks for no deleted events, so this is a provider answering with one
                # anyway. Counted rather than rejected: nothing is wrong with the feed, and an
                # event that occupies no time is not occupancy.
                cancelled += 1
                continue
            read = read_span(payload.start, payload.end, profile=self._profile)
            if not isinstance(read, ReadSpan):
                rejected.append(
                    RejectedComponent(
                        kind=read.kind,
                        line=UNKNOWN_LINE,
                        component=GOOGLE_COMPONENT,
                        detail=read.detail,
                        uid=payload.id,
                    )
                )
                continue
            if not read.interval.overlaps(self._horizon):
                # Outside the window this read was placed over. Not a loss and not an error, but
                # counted, because otherwise it is indistinguishable from occupancy that vanished.
                unplaced += 1
                continue
            events.append(_as_raw_event(payload, read))
            placed += 1
        return FetchOutcome(
            events=tuple(events),
            rejected=tuple(rejected),
            events_read=len(answer.events),
            cancelled_discarded=cancelled,
            placed=placed,
            unplaced=unplaced,
            reparsed=True,
        )


def _reason_of(answer: SyncTokenExpired | GoogleReadFailed) -> str:
    """The sentence a failed full read states, including the one that cannot happen."""
    if isinstance(answer, GoogleReadFailed):
        return answer.reason
    return "Google refused a sync token this read did not send"


def _as_raw_event(payload: GoogleEventPayload, read: ReadSpan) -> RawEvent:
    """One provider event as the value the anchor reconciler reads.

    ``uid`` is the instance's own identifier, which Google keeps when an instance of a series is
    moved. That is the identity rule the ICS path derives by hand from the occurrence's original
    wall time; here the provider maintains it, so a moved occurrence reconciles to the anchor the
    unmoved one created.

    A missing title stays missing rather than becoming a placeholder: what an untitled commitment is
    called is a rendering decision, and inventing a name here would write it into an anchor row.
    """
    return RawEvent(
        uid=payload.id,
        series_uid=payload.recurring_event_id,
        title=payload.summary or "",
        interval=read.interval,
        location=payload.location,
        sequence=payload.sequence or 0,
        all_day=read.all_day,
        transparent=payload.is_transparent,
    )
