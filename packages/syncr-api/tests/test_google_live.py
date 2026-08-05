"""The one suite that talks to Google, marked and excluded from the default run.

Everything else about this integration is proven against a fake provider, which is the right
default: a suite that needed a network and a real account would be slow, would consume quota, and
would fail for reasons that have nothing to do with the code. What a fake cannot prove is that
syncr's reading of Google's contract matches Google's, so this exists and is run deliberately.

**The destructive write is here, and it is the last test in the file.** It exercises one
reconciliation against the development calendar ticket 2 created: it inserts one event syncr
intends, reads the calendar back to confirm the diff key survived the round trip, and then removes
it by reconciling against an empty plan. Nothing else in the account is touched, because the
horizon is a two-hour window on a calendar that holds nothing real.

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
from hashlib import sha256
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syncr_api.calendars.config import GOOGLE, WRITE_TARGET
from syncr_api.calendars.google_adapter import GoogleAdapter
from syncr_api.calendars.google_client import CalendarsRead, EventsRead, GoogleCalendarClient
from syncr_api.calendars.google_events import (
    SYNCR_KEY_PROPERTY,
    GoogleEventWriter,
)
from syncr_api.calendars.google_transport import HttpxGoogleTransport, create_google_read_client
from syncr_api.calendars.google_values import ReadSpan, read_span
from syncr_api.calendars.google_writes import (
    HttpxGoogleWriteTransport,
    create_google_write_client,
)
from syncr_api.calendars.projection import ProjectedEvent
from syncr_api.calendars.records import CalendarSourceRecord, SyncStateRecord
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
# so a read here and the destructive write below cannot touch the user's own commitments.
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
        "Ticket 2 created it so a read here and the destructive write below cannot touch a "
        "real calendar."
    )
    development = next(one for one in answer.calendars if one.display_name == DEVELOPMENT_CALENDAR)
    # The destructive write below writes to it, so the account has to own it rather than read it.
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
        development.calendar_id,
        sync_token=first.sync_token,
        window=window,
        stop_at_first_change=True,
    )

    assert isinstance(second, EventsRead), second
    # The two claims that are about GOOGLE rather than about the call just made: it reported no
    # change, and it issued a token for the next poll to spend. An `incremental` flag was asserted
    # here too and was a tautology, since its value was "a token was sent" and the test sent one.
    assert second.events == ()
    assert second.sync_token


# --------------------------------------------------------------------------------------
# The destructive write, once, against the development calendar
# --------------------------------------------------------------------------------------


@pytest.fixture
async def live_writer(live_client: GoogleCalendarClient) -> AsyncIterator[GoogleEventWriter]:
    """A writer against the real API, on the same token source the read client holds.

    Built from the read client's own token source deliberately: what a deployment does is share one,
    so the live suite exercises the same arrangement rather than a second grant of its own.
    """
    async with create_google_write_client() as http:
        yield GoogleEventWriter(
            transport=HttpxGoogleWriteTransport(http),
            # The token source the deployment shares between the read and the write.
            tokens=live_client._tokens,
        )


async def a_development_target(client: GoogleCalendarClient) -> CalendarSourceRecord:
    """The development calendar as a write target, found by the name ticket 2 gave it."""
    listed = await client.list_calendars()
    assert isinstance(listed, CalendarsRead), listed
    development = next(
        (one for one in listed.calendars if one.display_name == DEVELOPMENT_CALENDAR), None
    )
    assert development is not None, (
        f"{DEVELOPMENT_CALENDAR!r} is not in this account, and this test writes destructively: "
        "it will not be pointed at any other calendar."
    )
    return CalendarSourceRecord(
        id=uuid4(),
        tenant_id=uuid4(),
        provider=GOOGLE,
        role=WRITE_TARGET,
        display_name=development.display_name,
        external_id=development.calendar_id,
        included=True,
        horizon_days=HORIZON_DAYS,
        sync_state=SyncStateRecord(),
    )


async def test_one_destructive_reconciliation_against_the_development_calendar(
    live_client: GoogleCalendarClient, live_writer: GoogleEventWriter
) -> None:
    """THE claim a fake cannot make: that Google accepts the requests syncr sends and answers them
    the way syncr reads them.

    One reconciliation, over a two-hour window on a calendar that holds nothing real, and then a
    second reconciliation against an empty plan to take the event away again. Four things are
    asserted that no fake can establish: the insert is accepted, the diff key survives the round
    trip through the provider's extended properties, the second pass finds the event unchanged and
    writes nothing, and the delete removes it.
    """
    target = await a_development_target(live_client)
    # A window far enough ahead that it cannot overlap anything a person put on the calendar today,
    # and short enough that the reconciliation reads a handful of events rather than a fortnight.
    start = (utc_now() + timedelta(days=2)).replace(minute=0, second=0, microsecond=0)
    window = Interval(start, start + timedelta(hours=2))
    google = GoogleAdapter(
        client=live_client,
        profile=ZoneProfile(home_zone="Europe/London"),
        horizon=window,
        clock=utc_now,
        writes=live_writer,
    )
    intended = ProjectedEvent(
        syncr_key=sha256(f"syncr-live-{uuid4()}".encode()).hexdigest(),
        interval=Interval(start, start + timedelta(minutes=30)),
        title="syncr live suite · safe to delete",
        description="Written by the live Google suite. It removes this again in the same test.",
    )

    inserted = await google.reconcile(target, [intended])
    unchanged = await google.reconcile(target, [intended])
    removed = await google.reconcile(target, [])

    assert inserted.inserted == 1, inserted
    # The second pass is the one that proves the key round-tripped: without it the event would be
    # found under no key, deleted as foreign, and inserted again.
    assert unchanged.written == 0, unchanged
    assert unchanged.unchanged == 1, unchanged
    assert removed.deleted == 1, removed
    assert removed.foreign_deleted == 0, removed
    # Nothing is left behind on the calendar, whatever else this account holds.
    remaining = await live_client.list_events(target.external_id, sync_token=None, window=window)
    assert isinstance(remaining, EventsRead), remaining
    assert intended.syncr_key not in {
        one.private_property(SYNCR_KEY_PROPERTY) for one in remaining.events
    }
