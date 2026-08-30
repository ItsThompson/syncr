"""The Google adapter: the same two-value return the ICS one has, over a different provider.

One method a caller uses, one it will use, and one that lists an account's calendars during setup.
What it hides is the whole shape of Google's read model: an opaque sync token, a provider that
invalidates it whenever it likes, a window a sync token forbids sending, and deletions that arrive
as events with no times at all.

**Two answers and three sync states, and none of them raises.** A worker tick polling five
calendars must not lose four because one calendar is gone, so every failure is a recorded attempt
with a stated reason. That is the ICS adapter's contract, kept deliberately: the syncer writes sync
state on every attempt and neither adapter gets to opt out.

**A delta is applied as what it is: a list of changes.** An incremental answer is not the calendar;
it is "these entries changed, everything else is as you last saw it". Handing that to a reconciler
as though absence meant removal would delete every anchor the provider did not happen to mention,
so the delta keeps its own shape all the way to the anchor writer: its events are created and
updated exactly as a full read's are, its removals travel as the identifiers the provider named,
and nothing absent from it is touched. A poll that reports nothing changed is answered exactly as
an ICS ``304`` is. A delta is a fourth kind of successful READ, not a fourth kind of attempt: the
three attempt kinds the syncer already distinguishes stay three.

**The delta itself is carried as a value, marked incremental and naming what the provider removed.**
A cancellation is the one thing a delta cannot express by absence, so it travels as an identifier;
and delta-ness travels with it because the anchor writer removes by absence on one reading and by
identifier on the other. A read of the calendar reports entries too, so both readings carry the
mark that tells them apart.

**The horizon is not applied at the provider.** Google refuses ``timeMin`` beside a sync token, so
an incremental read sees the whole calendar and the full read is windowed. A change outside the
horizon therefore arrives in a delta anyway, and a delta places nothing, so there is no window for
one of its entries to fall outside of.

**The cursor is bounded before it is stored.** A sync token is a value Google chooses the length of,
and the column that holds it is finite. An oversize write does not fail one source: it rolls back
the transaction the whole tenant's sync pass is in, so every sibling source loses the sync state it
had already earned. An oversize token is dropped, the next read is full, and the state says why.

**No title and no token reaches a log line.** Every line here carries identifiers and counts, which
is what the redactor's key names already enforce; the event titles this adapter handles are the most
sensitive values in the product.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from time import perf_counter
from typing import TYPE_CHECKING, Final

from syncr_api.calendars.config import GOOGLE_COMPONENT, SYNC_INTERVAL, UNKNOWN_LINE
from syncr_api.calendars.events import FetchOutcome, RawEvent, RejectedComponent
from syncr_api.calendars.google_client import (
    CalendarsRead,
    EventsRead,
    GoogleReadFailed,
    SyncTokenExpired,
)
from syncr_api.calendars.google_config import WRITE_DEADLINE_SECONDS
from syncr_api.calendars.google_cursors import bounded_cursor, sync_token_of
from syncr_api.calendars.google_events import (
    SYNCR_KEY_PROPERTY,
    WriteRefused,
    WritesUnavailable,
)
from syncr_api.calendars.google_values import ReadSpan, read_span
from syncr_api.calendars.projection import ProjectionAction, ReconcileResult
from syncr_api.calendars.projection_errors import ProjectionFailed, ProjectionRefused
from syncr_api.calendars.reconciliation import ExistingEvent, plan_reconciliation
from syncr_api.calendars.rejections import RejectionAccumulator
from syncr_api.calendars.sync_state import (
    recorded_failure,
    recorded_success,
    recorded_unchanged,
)
from syncr_common.logging import get_logger
from syncr_common.metrics import measured

if TYPE_CHECKING:
    from collections.abc import Awaitable
    from datetime import datetime

    from syncr_api.calendars.google_client import CalendarsAnswer, GoogleCalendarClient
    from syncr_api.calendars.google_events import EventWriting, GoogleEventWriter, WriteAnswer
    from syncr_api.calendars.google_payloads import GoogleEventPayload
    from syncr_api.calendars.projection import ProjectedEvent
    from syncr_api.calendars.reconciliation import ReconciliationPlan
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

# Why a full read happened while a cursor was held. Recorded on the source, because a source
# quietly re-reading a whole calendar every poll looks healthy and is not.
CURSOR_INVALIDATED: Final = (
    "Google invalidated the incremental sync token, so this read was a full one"
)
CURSOR_UNSTORABLE: Final = (
    "Google issued a sync token too long to store, so the next read will be a full one"
)
DELTA_OVER_MAX_PAGES: Final = (
    "Google's incremental read did not finish within the page bound, "
    "so the next read will be a full one"
)


class GoogleAdapter:
    """Read one Google calendar, list an account's calendars, and write the one syncr owns.

    The zone profile and the horizon are constructor dependencies rather than per-call arguments,
    because both belong to the tenant rather than to the source: one adapter is built per tenant per
    sync pass, and every calendar it reads resolves an all-day span the same way.

    ``writes`` is the write side, and it is a two-armed value rather than an optional collaborator.
    **The adapter the request path composes holds the refusing arm**, so no route can reach a
    destructive write however it is wired: the arm is chosen once, in the composition, and a reader
    of that composition sees which one.
    """

    def __init__(
        self,
        *,
        client: GoogleCalendarClient,
        profile: ZoneProfile,
        horizon: Interval,
        clock: Clock,
        writes: EventWriting,
        write_deadline_seconds: float = WRITE_DEADLINE_SECONDS,
    ) -> None:
        self._client = client
        self._profile = profile
        self._horizon = horizon
        self._clock = clock
        self._writes = writes
        # A parameter for the same reason the read client's deadline is one: the deadline is
        # behaviour under test, and a test that had to wait out the real one would spend ninety
        # seconds per assertion.
        self._write_deadline = write_deadline_seconds

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
        """One attempt on ``source``: what it produced, and the sync state to store.

        **The cheap read when a cursor is held, and the whole calendar when there is none.** The
        token buys the poll that costs one small request instead of a fortnight of events, which is
        the saving Google's own guide describes. Whatever that read answers is the attempt's answer:
        a quiet delta is a 304, and a change-bearing one is applied through the anchor writer rather
        than followed by a second read of everything.
        """
        at = self._clock()
        held = sync_token_of(source.sync_state.cursor)
        if held is None:
            return await self._read_fully(source, at=at)
        return await self.read_changes(source, since=held, at=at)

    async def read_changes(
        self, source: CalendarSourceRecord, *, since: str, at: datetime
    ) -> GoogleFetch:
        """What changed on ``source`` since ``since``, as a delta rather than as the calendar.

        Public, unlike its siblings: it is the seam a cursor-driven caller can drive directly (the
        tests do), and the seam later sync work builds on, without going through whichever source
        happens to hold the cursor.

        The same two values ``fetch`` answers with, so an attempt is recorded whatever it found, and
        it does not raise for the same reason nothing here does. Four answers: the token is no
        longer accepted, which is a full read; the read failed, which is a recorded attempt; a
        delta that reports nothing changed, which takes the 304 path; or a delta that reports
        changes, which is marked a successful read and applied by the caller through the anchor
        writer.

        A change-bearing delta pages to its end, because its every entry is a change to make: an
        early stop would apply part of one and keep a cursor that skips the rest. Its fresh token
        replaces the one that produced it, dropped when it will not fit, which costs one full read
        on the next poll rather than a failed write.

        A delta that exceeds the page bound did not finish, so the cursor that produced it is
        dropped rather than retained: retaining it would make the next poll re-page through the
        same bound and never finish. The next read is full, and the state's ``resync_reason``
        names why.

        ``at`` is passed rather than read from the clock here, so a poll records one instant rather
        than two microseconds apart.
        """
        answer = await self._client.list_events(
            source.external_id, sync_token=since, window=self._horizon
        )
        if isinstance(answer, GoogleReadFailed):
            if answer.bounded:
                return self._bounded_delta_failure(source, answer, at=at)
            return self._failed(source, answer, at=at)
        if isinstance(answer, SyncTokenExpired):
            _log.info("calendars.google.sync_token_invalidated", **_identity(source))
            return await self._read_fully(
                source, at=at, spent=answer.attempts, resync_reason=CURSOR_INVALIDATED
            )
        delta = self._delta(answer)
        if not _reports_a_change(delta):
            _log.info(
                "calendars.google.unchanged", **_identity(source), attempt_count=answer.attempts
            )
            # The fresh token replaces the one that produced the match, and the previous one is kept
            # when the new one will not fit, which costs nothing until the next poll reads fully.
            cursor = bounded_cursor(answer.sync_token) or source.sync_state.cursor
            return delta, recorded_unchanged(
                source.sync_state, at=at, cursor=cursor, attempts=answer.attempts
            )
        _log.info(
            "calendars.google.delta",
            **_identity(source),
            changed_count=len(delta.events),
            rejected_count=delta.rejected_count,
            removed_count=len(delta.removed_uids),
            attempt_count=answer.attempts,
        )
        # Marked reparsed, because a delta IS a body successfully read: this is the successful-read
        # attempt, whose changes reach the anchor writer through the reconcile path. The mark does
        # NOT make it a calendar -- ``incremental`` still says what is missing from it -- but a
        # delta that reported nothing would otherwise be indistinguishable from a feed down.
        cursor = bounded_cursor(answer.sync_token)
        unstorable = answer.sync_token is not None and cursor is None
        return replace(delta, reparsed=True), recorded_success(
            delta,
            at=at,
            cursor=cursor,
            attempts=answer.attempts,
            resync_reason=CURSOR_UNSTORABLE if unstorable else None,
        )

    async def reconcile(
        self, target: CalendarSourceRecord, desired: list[ProjectedEvent]
    ) -> ReconcileResult:
        """Make ``target`` match ``desired`` over the horizon, destructively.

        Three phases, and the order of the first two is the whole safety property. The refusal is
        checked BEFORE anything is read, so a deployment that will not write spends no request to
        learn what it already knew. The diff is then computed whole, before any of it is sent, so a
        reconciliation cannot discover halfway through that it is about to delete more than it meant
        to.

        Raises rather than answering when it did not finish, carrying the writes that DID land: the
        one thing a destructive write path must never do is read as a success when the target does
        not match the plan.
        """
        if isinstance(self._writes, WritesUnavailable):
            raise ProjectionRefused(self._writes.reason)
        started = perf_counter()
        identity = _identity(target)
        plan = plan_reconciliation(desired, await self._existing(target))
        _log.info(
            "calendars.projection.planned",
            **identity,
            desired_count=len(desired),
            **plan.as_log_fields(),
        )
        result = await self._applied(target, plan, writer=self._writes, started=started)
        _log.info("calendars.projection.reconciled", **identity, **result.as_log_fields())
        return result

    async def _existing(self, target: CalendarSourceRecord) -> list[ExistingEvent]:
        """What the target already holds over the horizon, as the diff reads it.

        A cancelled event is left out rather than reconciled: it occupies no time, so there is
        nothing on the calendar to remove and a delete would spend a request to change nothing.
        """
        answer = await self._client.list_events(
            target.external_id, sync_token=None, window=self._horizon
        )
        if not isinstance(answer, EventsRead):
            raise ProjectionFailed(
                f"the calendar syncr writes to could not be read, so the plan was not written: "
                f"{_reason_of(answer)}."
            )
        return [
            _as_existing_event(payload, profile=self._profile)
            for payload in answer.events
            if not payload.is_cancelled
        ]

    async def _applied(
        self,
        target: CalendarSourceRecord,
        plan: ReconciliationPlan,
        *,
        writer: GoogleEventWriter,
        started: float,
    ) -> ReconcileResult:
        """Send the plan, in its own order, stopping at the first write the provider refused.

        Sequential rather than concurrent, deliberately. Concurrency would make the set of writes
        that landed before a failure non-deterministic, and this is the one path in the product
        whose partial state is a real calendar on a real phone.

        **The deadline has a stated failure, exactly as the read's does.** Left uncaught, a
        reconciliation stopped part way through a destructive write would raise past every arm that
        records anything: no error on the target, so no banner; no duration and no event
        observation, so the projection's own metrics would say nothing; and the counts that DID land
        discarded, which is the one figure a partially written calendar is diagnosed from. The pass
        most likely to reach it is the FIRST projection of a full horizon, a couple of hundred
        sequential writes.
        """
        counts = dict.fromkeys(ProjectionAction, 0)
        try:
            async with asyncio.timeout(self._write_deadline):
                await self._sent(plan, counts, writer=writer, target=target, started=started)
        except TimeoutError:
            raise ProjectionFailed(
                f"the reconciliation was stopped after {self._write_deadline:.0f}s without "
                "finishing, so part of the plan reached the calendar and part did not.",
                applied=_result(counts, plan, started),
            ) from None
        return _result(counts, plan, started)

    async def _sent(
        self,
        plan: ReconciliationPlan,
        counts: dict[ProjectionAction, int],
        *,
        writer: GoogleEventWriter,
        target: CalendarSourceRecord,
        started: float,
    ) -> None:
        """The plan's three arms, in the order it states them, counting each write as it lands."""
        calendar_id = target.external_id
        for patch in plan.patches:
            await self._one(
                writer.patch(calendar_id, patch.event_id, patch.intended),
                counts,
                ProjectionAction.PATCHED,
                plan,
                started,
            )
        for insert in plan.inserts:
            await self._one(
                writer.insert(calendar_id, insert),
                counts,
                ProjectionAction.INSERTED,
                plan,
                started,
            )
        for removal in plan.deletes:
            await self._one(
                writer.delete(calendar_id, removal.event_id),
                counts,
                ProjectionAction.FOREIGN_DELETED if removal.foreign else ProjectionAction.DELETED,
                plan,
                started,
            )

    async def _one(
        self,
        write: Awaitable[WriteAnswer],
        counts: dict[ProjectionAction, int],
        action: ProjectionAction,
        plan: ReconciliationPlan,
        started: float,
    ) -> None:
        """Perform one write, counting it, and end the reconciliation if the provider refused it."""
        answer = await write
        if isinstance(answer, WriteRefused):
            raise ProjectionFailed(answer.reason, applied=_result(counts, plan, started))
        counts[action] += 1

    async def _read_fully(
        self,
        source: CalendarSourceRecord,
        *,
        at: datetime,
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
            )
        outcome = self._outcome(answer)
        cursor = bounded_cursor(answer.sync_token)
        unstorable = answer.sync_token is not None and cursor is None
        _log.info("calendars.google.read", **_identity(source), **outcome.as_log_fields())
        return outcome, recorded_success(
            outcome,
            at=at,
            cursor=cursor,
            attempts=spent + answer.attempts,
            resync_reason=CURSOR_UNSTORABLE if unstorable else resync_reason,
        )

    def _failed(
        self, source: CalendarSourceRecord, answer: GoogleReadFailed, *, at: datetime
    ) -> GoogleFetch:
        """Record an attempt that read nothing, keeping everything the source already had."""
        _log.warning(
            "calendars.google.unreachable",
            **_identity(source),
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

    def _bounded_delta_failure(
        self, source: CalendarSourceRecord, answer: GoogleReadFailed, *, at: datetime
    ) -> GoogleFetch:
        """Record an incremental read that did not finish, dropping the cursor that produced it.

        A bounded read did not complete, so the cursor it was started from cannot claim the
        read finished: retaining it would make the next poll re-page through the same bound
        and never finish. Dropping it costs one full read on the next poll, and the state
        names why.
        """
        _log.warning(
            "calendars.google.delta_unbounded",
            **_identity(source),
            attempt_count=answer.attempts,
            anchors_retained=source.sync_state.anchors_current,
        )
        state = recorded_failure(
            source.sync_state,
            at=at,
            reason=self._stated(answer, at=at),
            attempts=answer.attempts,
        )
        return FetchOutcome(), replace(state, cursor=None, resync_reason=DELTA_OVER_MAX_PAGES)

    def _stated(self, answer: GoogleReadFailed, *, at: datetime) -> str:
        """The failure as the source's panel reads it, with the next attempt named when it helps."""
        if not answer.rate_limited:
            return answer.reason
        return f"{answer.reason}. {_BACKING_OFF} {(at + SYNC_INTERVAL):%H:%M} UTC."

    def _delta(self, answer: EventsRead) -> FetchOutcome:
        """Partition one incremental read into what changed and what the provider says is gone.

        **Not clipped to the horizon, unlike a full read.** An occurrence the user moved OUT of the
        window is a change this read has to report, and clipping is exactly what would hide it:
        Google refuses ``timeMin`` beside a sync token, so the provider does not hide it either.

        A cancellation becomes an identifier rather than only a count, because that is the only
        form a removal can take here. A read of the calendar removes a commitment by not listing it;
        a list of changes lists almost nothing, so the entry itself is the whole evidence. It is
        still counted as discarded, so one accounting identity covers both reads.
        """
        events: list[RawEvent] = []
        rejections = RejectionAccumulator()
        removed: list[str] = []
        for payload in answer.events:
            if payload.is_cancelled:
                removed.append(payload.id)
                continue
            parsed = _read_one(payload, profile=self._profile)
            if isinstance(parsed, RejectedComponent):
                rejections.add(parsed)
                continue
            events.append(parsed)
        return FetchOutcome(
            events=tuple(events),
            rejections=rejections.tally(),
            events_read=len(answer.events),
            cancelled_discarded=len(removed),
            placed=len(events),
            removed_uids=tuple(removed),
            incremental=True,
        )

    def _outcome(self, answer: EventsRead) -> FetchOutcome:
        """Partition one full read's events into what was kept, rejected, and dropped."""
        events: list[RawEvent] = []
        rejections = RejectionAccumulator()
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
            parsed = _read_one(payload, profile=self._profile)
            if isinstance(parsed, RejectedComponent):
                rejections.add(parsed)
                continue
            if not parsed.interval.overlaps(self._horizon):
                # Outside the window this read was placed over. Not a loss and not an error, but
                # counted, because otherwise it is indistinguishable from occupancy that vanished.
                unplaced += 1
                continue
            events.append(parsed)
            placed += 1
        return FetchOutcome(
            events=tuple(events),
            rejections=rejections.tally(),
            events_read=len(answer.events),
            cancelled_discarded=cancelled,
            placed=placed,
            unplaced=unplaced,
            reparsed=True,
        )


def _identity(source: CalendarSourceRecord) -> dict[str, str]:
    """The two identifiers every line about one source carries, and nothing the redactor eats."""
    return {"source_id": str(source.id), "tenant_id": str(source.tenant_id)}


def _reports_a_change(outcome: FetchOutcome) -> bool:
    """Whether a delta found anything to report.

    Its terms are named rather than counted through ``events_read``, because they are three
    different answers and only two of them are an event. A poll whose every entry is a cancellation
    carries no event at all, and reading such a delta as "nothing changed" leaves the removed
    commitments occupying the plan until something unrelated moves.

    The refusals are read as their COUNT rather than as the sample, which is bounded per kind: what
    is asked here is whether the read refused anything, and that is the figure the accounting closes
    over rather than the one a panel renders.
    """
    return bool(outcome.events or outcome.removed_uids or outcome.rejected_count)


def _read_one(payload: GoogleEventPayload, *, profile: ZoneProfile) -> RawEvent | RejectedComponent:
    """One provider event as the value a caller reads, or the reason it could not be read."""
    read = read_span(payload.start, payload.end, profile=profile)
    if not isinstance(read, ReadSpan):
        return RejectedComponent(
            kind=read.kind,
            line=UNKNOWN_LINE,
            component=GOOGLE_COMPONENT,
            detail=read.detail,
            uid=payload.id,
        )
    return _as_raw_event(payload, read)


def _reason_of(answer: SyncTokenExpired | GoogleReadFailed) -> str:
    """The sentence a failed full read states, including the one that cannot happen."""
    if isinstance(answer, GoogleReadFailed):
        return answer.reason
    return "Google refused a sync token this read did not send"


def _result(
    counts: dict[ProjectionAction, int], plan: ReconciliationPlan, started: float
) -> ReconcileResult:
    """The counts so far as the value a reconciliation answers with, or a failure carries."""
    return ReconcileResult(
        inserted=counts[ProjectionAction.INSERTED],
        patched=counts[ProjectionAction.PATCHED],
        deleted=counts[ProjectionAction.DELETED],
        foreign_deleted=counts[ProjectionAction.FOREIGN_DELETED],
        duration_ms=round((perf_counter() - started) * 1000),
        unchanged=plan.unchanged,
    )


def _as_existing_event(payload: GoogleEventPayload, *, profile: ZoneProfile) -> ExistingEvent:
    """One event on the write target as the diff reads it.

    A span that cannot be read leaves the interval absent rather than dropping the event. The event
    is on the calendar inside the horizon either way, so it still has to be reconciled: with no key
    it is drift and is removed, and with one it is rewritten to what syncr intends.
    """
    read = read_span(payload.start, payload.end, profile=profile)
    return ExistingEvent(
        event_id=payload.id,
        interval=read.interval if isinstance(read, ReadSpan) else None,
        syncr_key=payload.private_property(SYNCR_KEY_PROPERTY),
        title=payload.summary or "",
        description=payload.description,
        location=payload.location,
    )


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
