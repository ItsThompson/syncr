"""Read Google calendars without raising for provider failures.
A delta stays a delta until the anchor writer applies it.
"""

from __future__ import annotations

from dataclasses import replace
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
from syncr_api.calendars.rejections import RejectionAccumulator
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
    from syncr_api.calendars.records import CalendarSourceRecord, SyncStateRecord
    from syncr_api.core.clock import Clock
    from syncr_domain.intervals import Interval
    from syncr_domain.zones import ZoneProfile

_log = get_logger("syncr.calendars")

type GoogleFetch = tuple[FetchOutcome, SyncStateRecord]

_BACKING_OFF: Final = "Sync is backing off and will try again at"
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


class GoogleReadAdapter:
    """Read a Google calendar or list an account's calendars, with recorded failures.
    No method raises for a provider response, so sibling sources keep polling.
    """

    def __init__(
        self,
        *,
        client: GoogleCalendarClient,
        profile: ZoneProfile,
        horizon: Interval,
        clock: Clock,
    ) -> None:
        self._client = client
        self._profile = profile
        self._horizon = horizon
        self._clock = clock

    @measured("google_adapter")
    async def list_calendars(self) -> CalendarsAnswer:
        """List calendars for setup, returning a failure value rather than raising it."""
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
        """Read one source incrementally when it holds a Google cursor, otherwise read it fully."""
        at = self._clock()
        held = sync_token_of(source.sync_state.cursor)
        if held is None:
            return await self._read_fully(source, at=at)
        return await self.read_changes(source, since=held, at=at)

    async def read_changes(
        self, source: CalendarSourceRecord, *, since: str, at: datetime
    ) -> GoogleFetch:
        """Read a delta without treating absent events as removals."""
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
            return self._unchanged(source, delta, answer, at=at)
        _log.info(
            "calendars.google.delta",
            **_identity(source),
            changed_count=len(delta.events),
            rejected_count=delta.rejected_count,
            removed_count=len(delta.removed_uids),
            attempt_count=answer.attempts,
        )
        cursor = bounded_cursor(answer.sync_token)
        return replace(delta, reparsed=True), recorded_success(
            delta,
            at=at,
            cursor=cursor,
            attempts=answer.attempts,
            resync_reason=(
                CURSOR_UNSTORABLE if answer.sync_token is not None and cursor is None else None
            ),
        )

    def _unchanged(
        self,
        source: CalendarSourceRecord,
        delta: FetchOutcome,
        answer: EventsRead,
        *,
        at: datetime,
    ) -> GoogleFetch:
        _log.info("calendars.google.unchanged", **_identity(source), attempt_count=answer.attempts)
        cursor = bounded_cursor(answer.sync_token) or source.sync_state.cursor
        return delta, recorded_unchanged(
            source.sync_state, at=at, cursor=cursor, attempts=answer.attempts
        )

    async def _read_fully(
        self,
        source: CalendarSourceRecord,
        *,
        at: datetime,
        spent: int = 0,
        resync_reason: str | None = None,
    ) -> GoogleFetch:
        answer = await self._client.list_events(
            source.external_id, sync_token=None, window=self._horizon
        )
        if isinstance(answer, SyncTokenExpired | GoogleReadFailed):
            return self._failed(
                source,
                GoogleReadFailed(reason=_reason_of(answer), attempts=spent + answer.attempts),
                at=at,
            )
        outcome = self._outcome(answer)
        cursor = bounded_cursor(answer.sync_token)
        _log.info("calendars.google.read", **_identity(source), **outcome.as_log_fields())
        return outcome, recorded_success(
            outcome,
            at=at,
            cursor=cursor,
            attempts=spent + answer.attempts,
            resync_reason=(
                CURSOR_UNSTORABLE
                if answer.sync_token is not None and cursor is None
                else resync_reason
            ),
        )

    def _failed(
        self, source: CalendarSourceRecord, answer: GoogleReadFailed, *, at: datetime
    ) -> GoogleFetch:
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
        state = self._failed(source, answer, at=at)[1]
        return FetchOutcome(), replace(state, cursor=None, resync_reason=DELTA_OVER_MAX_PAGES)

    def _stated(self, answer: GoogleReadFailed, *, at: datetime) -> str:
        if not answer.rate_limited:
            return answer.reason
        return f"{answer.reason}. {_BACKING_OFF} {(at + SYNC_INTERVAL):%H:%M} UTC."

    def _delta(self, answer: EventsRead) -> FetchOutcome:
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
        events: list[RawEvent] = []
        rejections = RejectionAccumulator()
        cancelled = 0
        placed = 0
        unplaced = 0
        for payload in answer.events:
            if payload.is_cancelled:
                cancelled += 1
                continue
            parsed = _read_one(payload, profile=self._profile)
            if isinstance(parsed, RejectedComponent):
                rejections.add(parsed)
                continue
            if not parsed.interval.overlaps(self._horizon):
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
    return {"source_id": str(source.id), "tenant_id": str(source.tenant_id)}


def _reports_a_change(outcome: FetchOutcome) -> bool:
    return bool(outcome.events or outcome.removed_uids or outcome.rejected_count)


def _read_one(payload: GoogleEventPayload, *, profile: ZoneProfile) -> RawEvent | RejectedComponent:
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
    if isinstance(answer, GoogleReadFailed):
        return answer.reason
    return "Google refused a sync token this read did not send"


def _as_raw_event(payload: GoogleEventPayload, read: ReadSpan) -> RawEvent:
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
