"""Test doubles for the Google integration: recorded payloads, and transports that record calls.

Two boundaries are faked and nothing else is. The transport is external by every definition, and a
clock is non-deterministic; the parsers, the sync-state arithmetic, the backoff schedule, and the
service are all real in every test that uses these.

The two transports differ in what they are for. :class:`RecordedGoogle` answers the calendar reads
by URL and records what was asked, because "an incremental read sends the token it holds" is a claim
about what was SENT as much as about what came back. :func:`token_transport` is an httpx transport,
so the OAuth client's own streaming, bounding, and form encoding are exercised rather than replaced.

:class:`RecordedGoogleWrites` is the third, and it exists because the write path's claims are all
about what was sent: which method, in which order, carrying which body, and how many of them landed
before a refusal.

No payload here carries an expected figure. A fixture that stated "three events" would be asserting
against itself; the tests count what the adapter produced.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx

from syncr_api.calendars.google_transport import GoogleResponse
from syncr_api.google_account.tokens import GoogleAccess, GoogleAccessAnswer

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

ACCESS_TOKEN = "ya29.a0-test-access-token"  # pragma: allowlist secret
REFRESH_TOKEN = "1//0e-test-refresh-token"  # pragma: allowlist secret
# A Fernet key for the tests, 32 bytes as URL-safe base64.
TEST_ENCRYPTION_KEY = "dGVzdC1vbmx5LWdvb2dsZS10b2tlbi1lbmNyeXB0ISE="  # pragma: allowlist secret

CLIENT_ID = "581707053568-example.apps.googleusercontent.com"
CLIENT_SECRET = "GOCSPX-test-not-a-real-secret"  # pragma: allowlist secret
REDIRECT_URI = "http://localhost:8000/api/v1/calendar-sources/google/callback"

CALENDAR_ID = "primary"
SYNC_TOKEN = "CPDAlvWDx70CEPDAlvWDx"  # pragma: allowlist secret

FAR_FUTURE = datetime(2099, 1, 1, tzinfo=UTC)


def event(
    identifier: str = "evt-1",
    *,
    start: str | None = "2026-02-09T09:00:00Z",
    end: str | None = "2026-02-09T10:00:00Z",
    date_start: str | None = None,
    date_end: str | None = None,
    summary: str | None = "Lecture",
    status: str | None = None,
    recurring_event_id: str | None = None,
    transparency: str | None = None,
    location: str | None = None,
    sequence: int | None = None,
) -> dict[str, Any]:
    """One event as the provider states it, with only the fields under test present."""
    payload: dict[str, Any] = {"id": identifier}
    if status is not None:
        payload["status"] = status
    if summary is not None:
        payload["summary"] = summary
    if location is not None:
        payload["location"] = location
    if transparency is not None:
        payload["transparency"] = transparency
    if sequence is not None:
        payload["sequence"] = sequence
    if recurring_event_id is not None:
        payload["recurringEventId"] = recurring_event_id
    if date_start is not None:
        payload["start"] = {"date": date_start}
        payload["end"] = {"date": date_end}
        return payload
    if start is not None:
        payload["start"] = {"dateTime": start, "timeZone": "Europe/London"}
    if end is not None:
        payload["end"] = {"dateTime": end, "timeZone": "Europe/London"}
    return payload


def events_page(
    *items: dict[str, Any], page_token: str | None = None, sync_token: str | None = SYNC_TOKEN
) -> bytes:
    """One page of an events read, as bytes, because that is what a transport answers."""
    page: dict[str, Any] = {"kind": "calendar#events", "items": list(items)}
    if page_token is not None:
        page["nextPageToken"] = page_token
    elif sync_token is not None:
        page["nextSyncToken"] = sync_token
    return json.dumps(page).encode("utf-8")


def calendar(
    identifier: str = "primary",
    *,
    summary: str | None = "Personal",
    access_role: str = "owner",
    primary: bool = False,
    deleted: bool = False,
) -> dict[str, Any]:
    """One calendar-list entry."""
    entry: dict[str, Any] = {"id": identifier, "accessRole": access_role}
    if summary is not None:
        entry["summary"] = summary
    if primary:
        entry["primary"] = True
    if deleted:
        entry["deleted"] = True
    return entry


def calendar_list_page(*items: dict[str, Any], page_token: str | None = None) -> bytes:
    page: dict[str, Any] = {"kind": "calendar#calendarList", "items": list(items)}
    if page_token is not None:
        page["nextPageToken"] = page_token
    return json.dumps(page).encode("utf-8")


def error_body(reason: str, *, code: int = 403, message: str = "Rate Limit Exceeded") -> bytes:
    """An error body in the nested shape Google actually sends."""
    return json.dumps(
        {"error": {"code": code, "message": message, "errors": [{"reason": reason}]}}
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class Call:
    """One request the client made, as the assertions read it."""

    url: str
    params: dict[str, str]
    token: str


@dataclass
class RecordedGoogle:
    """A :class:`~syncr_api.calendars.google_transport.GoogleTransport` answering from a script.

    Answers are taken in order, so a test can say "the first read reports a change and the second
    returns the calendar". Every call is recorded, which is how "the incremental read sent the token
    it held" is asserted.
    """

    answers: Sequence[GoogleResponse]
    calls: list[Call] = field(default_factory=list)
    raises: Exception | None = None

    async def get(self, url: str, *, params: Mapping[str, str], token: str) -> GoogleResponse:
        self.calls.append(Call(url=url, params=dict(params), token=token))
        if self.raises is not None:
            raise self.raises
        index = min(len(self.calls) - 1, len(self.answers) - 1)
        return self.answers[index]


def ok(body: bytes, **headers: str) -> GoogleResponse:
    return GoogleResponse(status=200, body=body, headers=headers)


def failed(status: int, body: bytes | None = None, **headers: str) -> GoogleResponse:
    return GoogleResponse(status=status, body=body, headers=headers)


# What Google answers a successful delete: no content, and no body to read.
NO_CONTENT = GoogleResponse(status=204, body=b"")
# What it answers a successful insert or patch: the event it stored. Nothing syncr reads, but a body
# is what a real answer carries and a fake that answered none would hide a reader of one.
EVENT_STORED = GoogleResponse(status=200, body=b'{"id": "evt-stored"}')


@dataclass(frozen=True, slots=True)
class Write:
    """One mutating request the projection made, as the assertions read it."""

    method: str
    url: str
    token: str
    body: dict[str, Any] | None


@dataclass
class RecordedGoogleWrites:
    """A :class:`~syncr_api.calendars.google_writes.GoogleWriteTransport` answering from a script.

    Answers are keyed by METHOD rather than by position, because that is how the claims read: "every
    delete is refused", "a patch answers 404". ``fail_after`` is the one positional case, and it is
    the one that matters most: a reconciliation that fails part way through has to report exactly
    what it applied, so the count of writes before the failure is the assertion.
    """

    by_method: Mapping[str, GoogleResponse] = field(default_factory=dict)
    default: GoogleResponse = EVENT_STORED
    fail_after: int | None = None
    failure: GoogleResponse = field(default_factory=lambda: failed(503))
    raises: Exception | None = None
    # How long each write past `stall_after` takes. A reconciliation that overruns its deadline part
    # way through a destructive write has its own stated failure, and this is what drives it.
    stall_after: int | None = None
    stall_seconds: float = 0.0
    writes: list[Write] = field(default_factory=list)

    async def send(
        self, method: str, url: str, *, token: str, body: dict[str, Any] | None = None
    ) -> GoogleResponse:
        self.writes.append(Write(method=method, url=url, token=token, body=body))
        if self.raises is not None:
            raise self.raises
        if self.stall_after is not None and len(self.writes) > self.stall_after:
            await asyncio.sleep(self.stall_seconds)
        if self.fail_after is not None and len(self.writes) > self.fail_after:
            return self.failure
        if method in self.by_method:
            return self.by_method[method]
        return NO_CONTENT if method == "DELETE" else self.default

    def methods(self) -> list[str]:
        """The order the reconciliation applied its plan in."""
        return [write.method for write in self.writes]


@dataclass
class FixedTokens:
    """An access-token source that answers with whatever the test set."""

    answer: GoogleAccessAnswer = field(
        default_factory=lambda: GoogleAccess(token=ACCESS_TOKEN, expires_at=FAR_FUTURE)
    )
    asked: int = 0

    async def current(self) -> GoogleAccessAnswer:
        self.asked += 1
        return self.answer


def token_transport(handler: object, *, timeout: float | None = None) -> httpx.AsyncClient:
    """An httpx client whose transport is a callable, so the real client code runs."""
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
        timeout=timeout,
        follow_redirects=False,
    )


def token_answer(**overrides: Any) -> httpx.Response:
    """A token-endpoint success body, with only what syncr reads."""
    body: dict[str, Any] = {
        "access_token": ACCESS_TOKEN,
        "expires_in": 3599,
        "refresh_token": REFRESH_TOKEN,
        "scope": (
            "https://www.googleapis.com/auth/calendar.calendarlist.readonly "
            "https://www.googleapis.com/auth/calendar.events.readonly"
        ),
        "token_type": "Bearer",
        "id_token": "an.id.token",
    }
    body.update(overrides)
    return httpx.Response(200, json=body)
