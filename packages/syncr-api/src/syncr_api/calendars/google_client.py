"""Reading Google: the calendar list, and one calendar's events, bounded in every direction.

What this hides from the adapter is everything the provider chooses the size and the timing of:
pagination, rate limits, backoff, sync-token invalidation, and the shape of a response body.

Four answers, and every one of them is a value:

``CalendarsRead`` / ``EventsRead``  the read succeeded, with the attempts it took.
``SyncTokenExpired``                Google refused the token with a 410. A full read is the answer.
``GoogleReadFailed``                the read could not be completed, and why, in one sentence.

**The deadline is around the whole read.** Pagination and backoff both happen inside it, so a host
that answers each page slowly is bounded by the same number as one that hangs on the first request.
A per-request timeout cannot see the first case, which is the defect this shape exists to avoid.

**A rate limit is read from the error's REASON, not its status.** A 403 is also what an
insufficient grant answers, and those two send the user to opposite repairs: one waits, the other
reconnects.

**Recurrence is expanded by Google.** ``singleEvents=true`` returns instances rather than series, so
this path parses no recurrence rule and never reaches the expander the ICS path uses. That is the
largest single reason the Google read is simpler than the ICS one.

**``showDeleted`` is never sent.** Google forbids it being false beside a sync token, and an
incremental read must carry deletions or an event removed at the source would stay in the plan
forever. Omitting it on both reads is what keeps the two requests' parameters compatible.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, Final

import httpx
from pydantic import ValidationError

from syncr_api.calendars.events import RemoteCalendar
from syncr_api.calendars.google_backoff import BackoffPolicy, stated_retry_after
from syncr_api.calendars.google_config import (
    CALENDAR_LIST_PAGE_SIZE,
    CALENDAR_LIST_URL,
    EVENTS_PAGE_SIZE,
    MAX_PAGE_BYTES,
    MAX_PAGES,
    RATE_LIMIT_REASONS,
    READ_DEADLINE_SECONDS,
    events_url,
)
from syncr_api.calendars.google_payloads import (
    GoogleCalendarListPage,
    GoogleCalendarPayload,
    GoogleErrorPayload,
    GoogleEventsPage,
)
from syncr_api.google_account.tokens import GoogleAccess

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from syncr_api.calendars.google_payloads import GoogleEventPayload
    from syncr_api.calendars.google_transport import GoogleResponse, GoogleTransport
    from syncr_api.google_account.tokens import AccessTokenSource
    from syncr_domain.intervals import Interval

type Sleeper = Callable[[float], Awaitable[None]]

_SERVER_ERROR_FLOOR: Final = 500

RATE_LIMITED_REASON: Final = "Google is rate limiting syncr, so this read backed off and stopped"


@dataclass(frozen=True, slots=True)
class CalendarsRead:
    """Every calendar the account holds, and how many calls it took to list them."""

    calendars: tuple[RemoteCalendar, ...]
    attempts: int


@dataclass(frozen=True, slots=True)
class EventsRead:
    """One calendar's events, the token to send next time, and the calls it took.

    ``sync_token`` is what the last page carried: a read that pages to its end collects it, and a
    caller that applies the answer stores it. It is ``None`` only when the provider issued no
    token, which keeps whatever cursor the source already held.
    """

    events: tuple[GoogleEventPayload, ...]
    sync_token: str | None
    attempts: int


@dataclass(frozen=True, slots=True)
class SyncTokenExpired:
    """Google invalidated the sync token. The caller reads fully and records why."""

    attempts: int


@dataclass(frozen=True, slots=True)
class GoogleReadFailed:
    """The read could not be completed, and why, in words a panel can render."""

    reason: str
    attempts: int
    rate_limited: bool = False


type EventsAnswer = EventsRead | SyncTokenExpired | GoogleReadFailed
type CalendarsAnswer = CalendarsRead | GoogleReadFailed


@dataclass(frozen=True, slots=True)
class _Page:
    """One successful response body, before it is validated."""

    body: bytes


@dataclass(frozen=True, slots=True)
class _Retryable:
    """A failure waiting may fix, and what the provider asked us to wait."""

    reason: str
    limited: bool = False
    retry_after: float | None = None


@dataclass
class _Tally:
    """How many calls one read has made, across its pages and its retries."""

    attempts: int = 0


class GoogleCalendarClient:
    """The two reads the Google adapter makes, with retries, pagination, and one deadline.

    Every dependency is injected, the sleeper included: a wait is part of the behaviour under test,
    and a test that slept through three of them would be a test of ``asyncio.sleep``.
    """

    def __init__(
        self,
        *,
        transport: GoogleTransport,
        tokens: AccessTokenSource,
        backoff: BackoffPolicy | None = None,
        sleep: Sleeper = asyncio.sleep,
        deadline_seconds: float = READ_DEADLINE_SECONDS,
    ) -> None:
        self._transport = transport
        self._tokens = tokens
        self._backoff = backoff or BackoffPolicy()
        self._sleep = sleep
        # A parameter for the same reason the sleeper is one: the deadline is behaviour under test,
        # and a test that had to wait out the real one would be a minute of sleeping per assertion.
        self._deadline = deadline_seconds

    async def list_calendars(self) -> CalendarsAnswer:
        """Every calendar in the connected account, for selection during setup."""
        tally = _Tally()
        try:
            async with asyncio.timeout(self._deadline):
                return await self._all_calendars(tally)
        except TimeoutError:
            return self._out_of_time(tally)

    async def list_events(
        self,
        calendar_id: str,
        *,
        sync_token: str | None,
        window: Interval,
    ) -> EventsAnswer:
        """One calendar's events: incrementally when a sync token is held, fully otherwise.

        Both readings page to their end, because both are answers a caller applies whole: an
        incremental answer is a delta whose every entry is a change to make, so returning before
        its last page would apply part of one and store a cursor that skips the rest.
        """
        tally = _Tally()
        try:
            async with asyncio.timeout(self._deadline):
                return await self._all_events(calendar_id, sync_token, window, tally)
        except TimeoutError:
            return self._out_of_time(tally)

    async def _all_calendars(self, tally: _Tally) -> CalendarsAnswer:
        found: list[RemoteCalendar] = []
        page_token: str | None = None
        for _ in range(MAX_PAGES):
            params = {"maxResults": str(CALENDAR_LIST_PAGE_SIZE)}
            if page_token is not None:
                params["pageToken"] = page_token
            answer = await self._fetch(CALENDAR_LIST_URL, params, tally)
            if isinstance(answer, GoogleReadFailed):
                return answer
            if isinstance(answer, SyncTokenExpired):
                # Unreachable: a 410 is read as an expired token only on a request that sent one,
                # and the calendar list sends none. Answered rather than asserted, because this
                # read's whole contract is that it does not raise.
                return GoogleReadFailed(
                    reason="Google refused a sync token this read did not send",
                    attempts=tally.attempts,
                )
            try:
                page = GoogleCalendarListPage.model_validate_json(answer.body)
            except ValidationError as invalid:
                return self._unreadable(invalid, tally)
            found.extend(_as_remote_calendar(entry) for entry in page.items if not entry.deleted)
            page_token = page.next_page_token
            if page_token is None:
                return CalendarsRead(calendars=tuple(found), attempts=tally.attempts)
        return self._unbounded_pages("calendar list", tally)

    async def _all_events(
        self,
        calendar_id: str,
        sync_token: str | None,
        window: Interval,
        tally: _Tally,
    ) -> EventsAnswer:
        found: list[GoogleEventPayload] = []
        page_token: str | None = None
        url = events_url(calendar_id)
        for _ in range(MAX_PAGES):
            params = _events_params(sync_token, window, page_token)
            answer = await self._fetch(url, params, tally, sent_sync_token=sync_token is not None)
            if isinstance(answer, GoogleReadFailed | SyncTokenExpired):
                return answer
            try:
                page = GoogleEventsPage.model_validate_json(answer.body)
            except ValidationError as invalid:
                return self._unreadable(invalid, tally)
            found.extend(page.items)
            page_token = page.next_page_token
            if page_token is None:
                return EventsRead(
                    events=tuple(found),
                    sync_token=page.next_sync_token,
                    attempts=tally.attempts,
                )
        return self._unbounded_pages("events read", tally)

    async def _fetch(
        self,
        url: str,
        params: Mapping[str, str],
        tally: _Tally,
        *,
        sent_sync_token: bool = False,
    ) -> _Page | GoogleReadFailed | SyncTokenExpired:
        """One page, retried while the failure is one that waiting can fix.

        The token is asked for on every attempt rather than once per read, so a retry after a long
        backoff runs on a token that is still valid.

        **The retry budget is per REQUEST, not per read.** ``tally`` counts every call the read
        made, because that is what the source reports; the budget is a local count, because a rate
        limit on page four is the same condition as one on page one and deserves the same four
        attempts. One budget shared across pagination gave a later page zero retries, which is not
        what either docstring described. The aggregate bound is the whole-read deadline, which every
        wait counts against.
        """
        made = 0
        while True:
            access = await self._tokens.current()
            if not isinstance(access, GoogleAccess):
                return GoogleReadFailed(reason=access.reason, attempts=tally.attempts)
            tally.attempts += 1
            made += 1
            outcome = await self._attempt(url, params, access.token, tally, sent_sync_token)
            if not isinstance(outcome, _Retryable):
                return outcome
            if not self._backoff.has_another_attempt(made):
                return GoogleReadFailed(
                    reason=outcome.reason, attempts=tally.attempts, rate_limited=outcome.limited
                )
            await self._sleep(self._backoff.wait_before(made, retry_after=outcome.retry_after))

    async def _attempt(
        self,
        url: str,
        params: Mapping[str, str],
        token: str,
        tally: _Tally,
        sent_sync_token: bool,
    ) -> _Page | GoogleReadFailed | SyncTokenExpired | _Retryable:
        """One call, with a transport failure treated as a condition rather than an exception."""
        try:
            response = await self._transport.get(url, params=params, token=token)
        except (httpx.HTTPError, httpx.InvalidURL) as error:
            # InvalidURL is not an HTTPError, so it is named: a calendarId is a provider-chosen
            # string that reaches a URL, and the read's contract is that it answers rather than
            # raises.
            return _Retryable(reason=f"Google could not be reached: {type(error).__name__}")
        return _read_page(response, sent_sync_token=sent_sync_token, tally=tally)

    def _out_of_time(self, tally: _Tally) -> GoogleReadFailed:
        return GoogleReadFailed(
            reason=(
                f"Google did not answer this read within {self._deadline:.0f}s, so it was stopped"
            ),
            attempts=tally.attempts,
        )

    def _unreadable(self, invalid: ValidationError, tally: _Tally) -> GoogleReadFailed:
        return GoogleReadFailed(
            reason=(
                "Google answered a body syncr cannot read: "
                f"{invalid.error_count()} field(s) did not match the expected shape"
            ),
            attempts=tally.attempts,
        )

    def _unbounded_pages(self, what: str, tally: _Tally) -> GoogleReadFailed:
        return GoogleReadFailed(
            reason=f"Google's {what} did not end within {MAX_PAGES} pages",
            attempts=tally.attempts,
        )


def _read_page(
    response: GoogleResponse, *, sent_sync_token: bool, tally: _Tally
) -> _Page | GoogleReadFailed | SyncTokenExpired | _Retryable:
    """What one response means: a page, a retry, a stated failure, or an expired token."""
    if response.status == HTTPStatus.GONE and sent_sync_token:
        return SyncTokenExpired(attempts=tally.attempts)
    if response.is_error:
        return _failure(response, tally)
    if response.body is None:
        return GoogleReadFailed(
            reason=(
                f"Google answered a page larger than {MAX_PAGE_BYTES // (1024 * 1024)}MB, which no "
                "page of a calendar is"
            ),
            attempts=tally.attempts,
        )
    return _Page(body=response.body)


def _failure(response: GoogleResponse, tally: _Tally) -> GoogleReadFailed | _Retryable:
    """Which kind of failure an error response is, read from its reason and not its status alone."""
    status = response.status
    reasons = _reasons(response.body)
    retry_after = stated_retry_after(response.headers)
    if status == HTTPStatus.TOO_MANY_REQUESTS or (
        status == HTTPStatus.FORBIDDEN and reasons & RATE_LIMIT_REASONS
    ):
        return _Retryable(reason=RATE_LIMITED_REASON, limited=True, retry_after=retry_after)
    if status >= _SERVER_ERROR_FLOOR:
        return _Retryable(reason=f"Google answered {status}", retry_after=retry_after)
    return GoogleReadFailed(reason=_stated(status), attempts=tally.attempts)


def _stated(status: int) -> str:
    """The sentence a source's panel shows for a failure waiting cannot fix."""
    if status == HTTPStatus.UNAUTHORIZED:
        return "Google refused syncr's access token, so the authorization may have been revoked"
    if status == HTTPStatus.FORBIDDEN:
        return (
            "Google refused access to this calendar, so the connected account may no longer be "
            "allowed to read it"
        )
    if status == HTTPStatus.NOT_FOUND:
        return "Google no longer holds this calendar, so it cannot be read"
    return f"Google answered {status}"


def _reasons(body: bytes | None) -> frozenset[str]:
    """The reasons an error body states, or none when it states none or is not JSON."""
    if body is None:
        return frozenset()
    try:
        return frozenset(GoogleErrorPayload.model_validate_json(body).reasons)
    except ValidationError:
        return frozenset()


def _events_params(
    sync_token: str | None, window: Interval, page_token: str | None
) -> dict[str, str]:
    """The query for one page of an events read.

    ``timeMin`` and ``timeMax`` are sent only on a full read, because Google refuses them beside a
    sync token. An incremental read therefore returns changes from the whole calendar and the
    caller clips them itself, which it has to do anyway: an occurrence moved INTO the window is a
    change the provider reports and a window filter at the provider would have hidden.
    """
    params = {"singleEvents": "true", "maxResults": str(EVENTS_PAGE_SIZE)}
    if sync_token is not None:
        params["syncToken"] = sync_token
    else:
        params["timeMin"] = window.start.isoformat()
        params["timeMax"] = window.end.isoformat()
    if page_token is not None:
        params["pageToken"] = page_token
    return params


def _as_remote_calendar(entry: GoogleCalendarPayload) -> RemoteCalendar:
    """One calendar-list entry as the value the selection surface renders.

    A calendar with no title reads back as its identifier rather than as an empty row: the
    identifier is an address the user can recognise, and a blank line in a list is not a choice.
    """
    return RemoteCalendar(
        calendar_id=entry.id,
        display_name=entry.summary or entry.id,
        time_zone=entry.time_zone,
        writable=entry.is_writable,
        primary=bool(entry.primary),
    )
