"""The three mutating calls the projection makes, and the arm that refuses to make them.

One event in, one answer out, and the answer is a value: a caller applying two hundred writes in
sequence has to be able to stop at the first refusal with an exact count of what landed, and an
exception per call would make that a control-flow problem instead of a value.

**A retry happens only where the provider is known to have rejected the request.** A rate limit is
exactly that: Google refused it, nothing was applied, and waiting is the remedy. A 5xx, a timeout
and a dropped connection are NOT: any of them may have applied the write, and retrying one would
create a second event for the same block. So an ambiguous failure ends the reconciliation, and the
next one recomputes the diff from a fresh read of the target and converges. That is what makes a
duplicate event impossible by construction rather than by hoping the provider deduplicates.

**A body states the whole intended content, including the fields that are absent.** Google's patch
leaves out what a body leaves out, so a description that has gone away has to be sent as null or the
phone keeps showing the old sentence forever.

**The key travels in the private extended properties.** Private rather than shared because syncr
owns the calendar, and an extended property rather than a convention in the title because the title
is the user's to read and a key in it would be a key they could edit.

**A deletion of something already gone is done, and a patch of something already gone is not.**
Both answer 404, and the two mean opposite things: the deletion got what it wanted, and the patch
left the target missing an event the plan holds. Reporting the second as a success is exactly the
failure that reads as a success, so it ends the reconciliation and the next attempt inserts the
event.

**A write refused for want of an authorization has already raised the loudest notice in the
product**, because the token source records a dead grant where it discovers one. This module does
not raise that notice again; it reports what happened to the write.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, Final

import httpx
from pydantic import ValidationError

from syncr_api.calendars.google_backoff import BackoffPolicy, stated_retry_after
from syncr_api.calendars.google_config import (
    MAX_WRITE_ATTEMPTS,
    RATE_LIMIT_REASONS,
    event_url,
    events_url,
)
from syncr_api.calendars.google_payloads import GoogleErrorPayload
from syncr_api.google_account.tokens import GoogleAccess

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from syncr_api.calendars.google_transport import GoogleResponse
    from syncr_api.calendars.google_writes import GoogleWriteTransport
    from syncr_api.calendars.projection import ProjectedEvent
    from syncr_api.core.columns import JsonObject
    from syncr_api.google_account.tokens import AccessTokenSource

type Sleeper = Callable[[float], Awaitable[None]]

# Where the diff key lives on a Google event. Google bounds an extended-property key at 44
# characters and a value at 1024, which this name and a 64-character digest are both well inside.
SYNCR_KEY_PROPERTY: Final = "syncrKey"

_SERVER_ERROR_FLOOR: Final = 500

POST: Final = "POST"
PATCH: Final = "PATCH"
DELETE: Final = "DELETE"

RATE_LIMITED_REASON: Final = (
    "Google is rate limiting syncr, so this reconciliation stopped part way through"
)


@dataclass(frozen=True, slots=True)
class WriteApplied:
    """The provider accepted the write, or the event was already in the state asked for."""


@dataclass(frozen=True, slots=True)
class WriteRefused:
    """The write did not happen, and why, in words a banner can render.

    ``retry_after`` is what the provider asked syncr to wait, and it is meaningful only beside
    ``rate_limited``: a rate limit is the one refusal a retry can clear.
    """

    reason: str
    rate_limited: bool = False
    retry_after: float | None = None


type WriteAnswer = WriteApplied | WriteRefused


@dataclass(frozen=True, slots=True)
class WritesUnavailable:
    """Why this deployment will not write to a calendar at all.

    A value rather than an absent collaborator, so the reason reaches the notice the user reads and
    a reader of the composition sees which arm was chosen. It is checked before anything is read
    from the provider: a refusal that spent a request first would cost a read per attempt to reach a
    conclusion it already held.
    """

    reason: str


def event_body(intended: ProjectedEvent) -> JsonObject:
    """One event as Google states it, with every field syncr intends and no field it does not.

    The absent fields are present and null rather than omitted, because this body is also a patch:
    Google leaves out what a body leaves out, so an omitted description would leave a stale sentence
    on the user's phone for as long as the event lived.
    """
    return {
        "summary": intended.title,
        "description": intended.description,
        "location": intended.location,
        "start": {"dateTime": intended.interval.start.isoformat()},
        "end": {"dateTime": intended.interval.end.isoformat()},
        "extendedProperties": {"private": {SYNCR_KEY_PROPERTY: intended.syncr_key}},
    }


class GoogleEventWriter:
    """Insert, patch, and delete one event on the calendar syncr owns.

    Every dependency is injected, the sleeper included: a wait is part of the behaviour under test,
    and a test that slept through two of them would be a test of ``asyncio.sleep``.
    """

    def __init__(
        self,
        *,
        transport: GoogleWriteTransport,
        tokens: AccessTokenSource,
        backoff: BackoffPolicy | None = None,
        sleep: Sleeper = asyncio.sleep,
    ) -> None:
        self._transport = transport
        self._tokens = tokens
        self._backoff = backoff or BackoffPolicy()
        self._sleep = sleep

    async def insert(self, calendar_id: str, intended: ProjectedEvent) -> WriteAnswer:
        """Create one event syncr intends and the target does not hold."""
        return await self._sent(POST, events_url(calendar_id), body=event_body(intended))

    async def patch(self, calendar_id: str, event_id: str, intended: ProjectedEvent) -> WriteAnswer:
        """Make one event the target already holds say what syncr now intends."""
        return await self._sent(PATCH, event_url(calendar_id, event_id), body=event_body(intended))

    async def delete(self, calendar_id: str, event_id: str) -> WriteAnswer:
        """Remove one event syncr does not intend inside the horizon."""
        return await self._sent(DELETE, event_url(calendar_id, event_id), gone_is_done=True)

    async def _sent(
        self, method: str, url: str, *, body: JsonObject | None = None, gone_is_done: bool = False
    ) -> WriteAnswer:
        """One mutating request, retried only while the provider says it rejected it.

        The token is asked for on every attempt rather than once per reconciliation, so a write two
        hundred events into a pass runs on a token that is still valid.
        """
        made = 0
        while True:
            access = await self._tokens.current()
            if not isinstance(access, GoogleAccess):
                return WriteRefused(reason=access.reason)
            made += 1
            answer = await self._attempted(
                method, url, access.token, body, gone_is_done=gone_is_done
            )
            if isinstance(answer, WriteApplied) or not answer.rate_limited:
                return answer
            if made >= MAX_WRITE_ATTEMPTS:
                return answer
            await self._sleep(self._backoff.wait_before(made, retry_after=answer.retry_after))

    async def _attempted(
        self, method: str, url: str, token: str, body: JsonObject | None, *, gone_is_done: bool
    ) -> WriteAnswer:
        """One call, with a transport failure treated as ambiguous rather than as a retry.

        A request that raised may have been applied, so it ends the reconciliation. Nothing here can
        tell a connection refused before the request was sent from one dropped after it was served,
        and guessing wrong the other way writes the event twice.
        """
        try:
            response = await self._transport.send(method, url, token=token, body=body)
        except (httpx.HTTPError, httpx.InvalidURL) as error:
            return WriteRefused(
                reason=(
                    f"Google could not be reached while writing: {type(error).__name__}. Whether "
                    "that write was applied is unknown, so it was not retried"
                )
            )
        return read_write_answer(response, gone_is_done=gone_is_done)


type EventWriting = GoogleEventWriter | WritesUnavailable
"""What an adapter holds for its write side: a writer, or the stated reason there is none.

Two arms rather than an optional writer, so a composition states which one it chose and a reader of
the adapter sees that the refusal is a value with a reason in it rather than an absent dependency.
"""


def read_write_answer(response: GoogleResponse, *, gone_is_done: bool) -> WriteAnswer:
    """What one response to a mutating request means.

    ``gone_is_done`` is true for a deletion and false for everything else, which is the whole of the
    difference between the two readings of a 404.
    """
    status = response.status
    if not response.is_error:
        return WriteApplied()
    if status in {HTTPStatus.NOT_FOUND, HTTPStatus.GONE}:
        return (
            WriteApplied()
            if gone_is_done
            else WriteRefused(
                reason=(
                    "Google no longer holds an event syncr was updating, so it was removed while "
                    "the plan was being written"
                )
            )
        )
    reasons = _reasons(response.body)
    if status == HTTPStatus.TOO_MANY_REQUESTS or (
        status == HTTPStatus.FORBIDDEN and reasons & RATE_LIMIT_REASONS
    ):
        return WriteRefused(
            reason=RATE_LIMITED_REASON,
            rate_limited=True,
            retry_after=stated_retry_after(response.headers),
        )
    if status == HTTPStatus.UNAUTHORIZED:
        return WriteRefused(
            reason=(
                "Google refused syncr's access token on a write, so the authorization may have "
                "been revoked"
            )
        )
    if status == HTTPStatus.FORBIDDEN:
        return WriteRefused(
            reason=(
                "Google refused to change this calendar, so the connected account may no longer be "
                "allowed to write to it"
            )
        )
    if status >= _SERVER_ERROR_FLOOR:
        return WriteRefused(
            reason=(
                f"Google answered {status} to a write. Whether it was applied is unknown, so it "
                "was not retried"
            )
        )
    return WriteRefused(reason=f"Google answered {status} to a write")


def _reasons(body: bytes | None) -> frozenset[str]:
    """The reasons an error body states, or none when it states none or is not JSON.

    Read for the one distinction the status cannot make: a 403 is what a rate limit answers and also
    what an account that may no longer write answers, and those two send the user to opposite
    repairs.
    """
    if body is None:
        return frozenset()
    try:
        return frozenset(GoogleErrorPayload.model_validate_json(body).reasons)
    except ValidationError:
        return frozenset()
