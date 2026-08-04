"""The one suite that talks to Google, marked and excluded from the default run.

Everything else about this integration is proven against a fake provider, which is the right
default: a suite that needed a network and a real account would be slow, would consume quota, and
would fail for reasons that have nothing to do with the code. What a fake cannot prove is that
syncr's reading of Google's contract matches Google's, so this exists and is run deliberately.

**It reads and never writes.** The destructive reconciliation is ticket 30's behaviour under test,
and it points at the development calendar. This suite lists the account's calendars, finds that
development calendar by name, and reads its events over a horizon. Nothing here inserts, patches or
deletes anything, so it cannot damage a real calendar even if it is pointed at one by mistake.

**It is excluded by a marker, not by a skip.** ``addopts`` carries ``-m "not google_live"``, so the
default run never collects it and a developer opts in explicitly:

    uv run pytest -m google_live

**Every credential comes from the environment, and an absent one skips rather than fails.** A
refresh token is standing authority over a real account: it is never committed, never a fixture, and
never printed. Obtain one by completing the connect flow once against a development deployment; the
runbook records where it lives afterwards.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syncr_api.calendars.google_client import CalendarsRead, EventsRead, GoogleCalendarClient
from syncr_api.calendars.google_transport import HttpxGoogleTransport, create_google_read_client
from syncr_api.calendars.google_values import ReadSpan, read_span
from syncr_api.core.clock import utc_now
from syncr_api.google_account.crypto import TokenCipher
from syncr_api.google_account.oauth_client import GoogleOAuthClient
from syncr_api.google_account.records import GoogleCredentialRecord
from syncr_api.google_account.tokens import GoogleAccess, GoogleAccessTokens
from syncr_domain.intervals import Interval
from syncr_domain.zones import ZoneProfile

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.google_live

# The calendar ticket 2 created for exactly this: a secondary owned calendar holding nothing real,
# so a read here and a destructive write in ticket 30 cannot touch the user's own commitments.
DEVELOPMENT_CALENDAR = "syncr (dev)"

CLIENT_ID_VAR = "GOOGLE_OAUTH_CLIENT_ID"
CLIENT_SECRET_VAR = "GOOGLE_OAUTH_CLIENT_SECRET"  # pragma: allowlist secret
REDIRECT_URI_VAR = "GOOGLE_OAUTH_REDIRECT_URI"
REFRESH_TOKEN_VAR = "SYNCR_GOOGLE_LIVE_REFRESH_TOKEN"  # pragma: allowlist secret
# A key of the suite's own, so the plaintext token from the environment is encrypted and decrypted
# by the real cipher rather than handed to the token layer directly: what runs here is the same path
# a deployment runs.
SUITE_KEY = "bGl2ZS1zdWl0ZS1nb29nbGUtdG9rZW4tY2lwaGVyISE="  # pragma: allowlist secret

HORIZON_DAYS = 14

_MISSING = (
    "set {names} to run the live Google suite. Every value is a real credential, so none is "
    "committed: complete the connect flow once against a development deployment to obtain the "
    "refresh token, and see docs/runbooks/google-oauth-verification.md for the client credentials."
)


def required(*names: str) -> dict[str, str]:
    """The named environment values, or a skip naming every one that is absent."""
    found = {name: os.environ.get(name, "").strip() for name in names}
    absent = sorted(name for name, value in found.items() if not value)
    if absent:
        pytest.skip(_MISSING.format(names=", ".join(absent)))
    return found


@pytest.fixture
async def live_client() -> AsyncIterator[GoogleCalendarClient]:
    """A client against the real API, authorized by a refresh token from the environment."""
    credentials = required(CLIENT_ID_VAR, CLIENT_SECRET_VAR, REDIRECT_URI_VAR, REFRESH_TOKEN_VAR)
    cipher = TokenCipher(SUITE_KEY)
    stored = GoogleCredentialRecord(
        id=uuid4(),
        tenant_id=uuid4(),
        encrypted_refresh_token=cipher.encrypt(credentials[REFRESH_TOKEN_VAR]),
        granted_scopes=(),
        connected_at=utc_now(),
    )

    class _HeldCredential:
        """The one row the token layer reads, without a database for a read-only suite."""

        async def read(self) -> GoogleCredentialRecord:
            return stored

        async def record_refresh(self, *, at: datetime) -> None:
            del at

        async def record_refresh_failure(self, *, at: datetime, reason: str) -> None:
            raise AssertionError(f"the live refresh failed: {reason}")

    async with create_google_read_client() as http:
        yield GoogleCalendarClient(
            transport=HttpxGoogleTransport(http),
            tokens=GoogleAccessTokens(
                credentials=_HeldCredential(),  # type: ignore[arg-type]
                oauth=GoogleOAuthClient(
                    client=http,
                    client_id=credentials[CLIENT_ID_VAR],
                    client_secret=credentials[CLIENT_SECRET_VAR],
                    redirect_uri=credentials[REDIRECT_URI_VAR],
                ),
                cipher=cipher,
                clock=utc_now,
            ),
        )


async def test_the_stored_grant_still_refreshes_into_an_access_token(
    live_client: GoogleCalendarClient,
) -> None:
    # The first thing to know when this suite fails: whether the credential is alive. Everything
    # below depends on it, and a dead grant is a reconnect rather than a code change.
    # Reaching the token source directly, because the claim IS about the credential rather than
    # about a read that happens to use one.
    access = await live_client._tokens.current()

    assert isinstance(access, GoogleAccess)
    assert access.expires_at > utc_now()


async def test_the_accounts_calendars_include_the_development_calendar(
    live_client: GoogleCalendarClient,
) -> None:
    answer = await live_client.list_calendars()

    assert isinstance(answer, CalendarsRead), answer
    names = [one.display_name for one in answer.calendars]
    assert DEVELOPMENT_CALENDAR in names, (
        f"the development calendar {DEVELOPMENT_CALENDAR!r} is not in this account: {names}. "
        "Ticket 2 created it so a read here and a destructive write in ticket 30 cannot touch a "
        "real calendar."
    )
    development = next(one for one in answer.calendars if one.display_name == DEVELOPMENT_CALENDAR)
    # Ticket 30 writes to it, so the account has to own it rather than merely read it.
    assert development.writable is True


async def test_a_full_read_of_the_development_calendar_answers_with_a_sync_token(
    live_client: GoogleCalendarClient,
) -> None:
    listed = await live_client.list_calendars()
    assert isinstance(listed, CalendarsRead), listed
    development = next(one for one in listed.calendars if one.display_name == DEVELOPMENT_CALENDAR)
    now = utc_now()

    answer = await live_client.list_events(
        development.calendar_id,
        sync_token=None,
        window=Interval(now, now + timedelta(days=HORIZON_DAYS)),
    )

    assert isinstance(answer, EventsRead), answer
    # The token is what the next poll spends. Without one on the last page, every read is full.
    assert answer.sync_token, "a full read must answer with a sync token"
    assert answer.attempts == 1


async def test_every_event_the_real_api_returns_is_one_syncr_can_read(
    live_client: GoogleCalendarClient,
) -> None:
    # THE claim a fake cannot make: that syncr's reading of Google's timestamp contract matches what
    # Google actually sends. A rejection here is a divergence between the two, which is the class of
    # defect this suite exists to find.
    listed = await live_client.list_calendars()
    assert isinstance(listed, CalendarsRead), listed
    now = utc_now()
    profile = ZoneProfile(home_zone="Europe/London")

    unreadable: list[str] = []
    for remote in listed.calendars:
        answer = await live_client.list_events(
            remote.calendar_id,
            sync_token=None,
            window=Interval(now, now + timedelta(days=HORIZON_DAYS)),
        )
        if not isinstance(answer, EventsRead):
            continue
        for payload in answer.events:
            if payload.is_cancelled:
                continue
            read = read_span(payload.start, payload.end, profile=profile)
            if not isinstance(read, ReadSpan):
                # The identifier and the reason, never the title: a live account holds real ones.
                unreadable.append(f"{payload.id}: {read.detail}")

    assert unreadable == [], f"the real API returned values syncr refused: {unreadable}"


async def test_an_incremental_read_after_a_full_one_reports_no_change(
    live_client: GoogleCalendarClient,
) -> None:
    # The change detector against the real provider: two reads with nothing happening between them
    # must produce an empty second answer, which is what makes a quiet poll cheap.
    listed = await live_client.list_calendars()
    assert isinstance(listed, CalendarsRead), listed
    development = next(one for one in listed.calendars if one.display_name == DEVELOPMENT_CALENDAR)
    now = utc_now()
    window = Interval(now, now + timedelta(days=HORIZON_DAYS))

    first = await live_client.list_events(development.calendar_id, sync_token=None, window=window)
    assert isinstance(first, EventsRead), first
    second = await live_client.list_events(
        development.calendar_id, sync_token=first.sync_token, window=window
    )

    assert isinstance(second, EventsRead), second
    assert second.incremental is True
    assert second.events == ()
    assert second.sync_token
