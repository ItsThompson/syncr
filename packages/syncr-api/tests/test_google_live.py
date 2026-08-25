"""The one suite that talks to Google, marked and excluded from the default run.

Everything else about this integration is proven against a fake provider, which is the right
default: a suite that needed a network and a real account would be slow, would consume quota, and
would fail for reasons that have nothing to do with the code. What a fake cannot prove is that
syncr's reading of Google's contract matches Google's, so this exists and is run deliberately.

**The destructive write is here, and it is the last test in the file.** It exercises one
reconciliation against the development calendar: it inserts one event syncr
intends, reads the calendar back to confirm the diff key survived the round trip, and then removes
it by reconciling against an empty plan. Nothing else in the account is touched, because the
horizon is a two-hour window on a calendar that holds nothing real, and the window is read before
anything is written: an occupied one refuses rather than removing what it found.

**The write probes before it change only events they created.** A reconciliation is destructive
across its whole horizon; a probe sends one insert, one patch or one delete against an identifier
the provider gave it, so nothing it did not make is reachable from it. They exist because the
answers to a patch and to a second delete are the two halves of Google's write contract that no
read can show and no fake can establish.

**It is excluded by a marker, not by a skip.** ``addopts`` carries ``-m "not google_live"``, so the
default run never collects it and a developer opts in explicitly:

    uv run pytest -m google_live

**Every credential comes from the environment, and an absent one skips rather than fails.** A
refresh token is standing authority over a real account: it is never committed, never a fixture, and
never printed. ``docs/runbooks/google-oauth-verification.md`` holds the procedure that obtains one
and the four values this suite reads.
"""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import TYPE_CHECKING, Final
from uuid import uuid4

import pytest

from syncr_api.calendars.config import GOOGLE, WRITE_TARGET
from syncr_api.calendars.google_adapter import GoogleAdapter
from syncr_api.calendars.google_client import CalendarsRead, EventsRead, GoogleCalendarClient
from syncr_api.calendars.google_config import (
    PROJECTION_BUDGET_SECONDS,
    WRITE_DEADLINE_SECONDS,
    events_url,
)
from syncr_api.calendars.google_events import (
    SYNCR_KEY_PROPERTY,
    GoogleEventWriter,
    WriteApplied,
    WriteRefused,
)
from syncr_api.calendars.google_payloads import GoogleErrorPayload
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
from tests.destructive_window import WindowOccupied, read_window

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syncr_api.calendars.google_payloads import GoogleEventPayload

pytestmark = pytest.mark.google_live

# The development calendar the owning account holds for exactly this: a secondary owned calendar
# holding nothing real, so a read here and the destructive write below cannot touch the user's own
# commitments. `docs/runbooks/google-oauth-verification.md` records why it exists and what it is
# for.
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

# The title every event this suite creates carries. One spelling, because it is the sentence an
# operator reads on a phone if a run leaves something behind.
SAFE_TITLE: Final = "syncr live suite · safe to delete"

# Which days ahead this suite writes on. Every window starts at the top of the current hour on the
# named day and lasts WINDOW_LENGTH, and each is a day of its own so no two of them can leave an
# event in each other's window. The runbook quotes the span, so an operator can clear it first.
RECONCILED_DAY: Final = 2
PATCHED_DAY: Final = 3
GONE_DAY: Final = 4
CHANGED_DAY: Final = 5
WRITE_DAYS_AHEAD: Final = (RECONCILED_DAY, PATCHED_DAY, GONE_DAY, CHANGED_DAY)
WINDOW_LENGTH: Final = timedelta(hours=2)

# A calendar identifier shaped like one Google issues and belonging to no account, for the one read
# that has to see an error body. Nothing is written to it and nothing could be.
ABSENT_CALENDAR: Final = "syncr-live-suite-holds-no-such-calendar@group.calendar.google.com"

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
        "The owning account holds it so a read here and the destructive write below cannot touch a "
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
    examined = 0
    for remote in listed.calendars:
        answer = await live_client.list_events(
            remote.calendar_id,
            sync_token=None,
            window=Interval(now, now + timedelta(days=HORIZON_DAYS)),
        )
        # Failed rather than skipped. A read that did not answer is not a calendar full of readable
        # timestamps, and continuing past it let this test report the contract settled having
        # examined nothing at all.
        assert isinstance(answer, EventsRead), (remote.display_name, answer)
        for payload in answer.events:
            if payload.is_cancelled:
                continue
            examined += 1
            read = read_span(payload.start, payload.end, profile=profile)
            if not isinstance(read, ReadSpan):
                # The identifier and the reason, never the title: a live account holds real ones.
                unreadable.append(f"{payload.id}: {read.detail}")

    assert unreadable == [], f"the real API returned values syncr refused: {unreadable}"
    # The denominator, because the assertion above holds over an empty set. Three ways to reach it
    # with nothing read: an account with no calendars, every read failing, every event cancelled.
    assert examined > 0, (
        "no timestamp was examined, so this run settled nothing about Google's timestamp contract "
        f"however green it looks: {len(listed.calendars)} calendar(s) answered"
    )


async def test_an_incremental_read_after_a_full_one_reports_no_change(
    live_client: GoogleCalendarClient,
) -> None:
    # The token against the real provider: two reads with nothing happening between them
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
    )

    assert isinstance(second, EventsRead), second
    # The two claims that are about GOOGLE rather than about the call just made: it reported no
    # change, and it issued a token for the next poll to spend. An `incremental` flag was asserted
    # here too and was a tautology, since its value was "a token was sent" and the test sent one.
    assert second.events == ()
    assert second.sync_token


async def test_an_error_body_nests_its_reason_where_syncr_reads_it(
    live_client: GoogleCalendarClient,
) -> None:
    """The one distinction a status cannot make, taken from the shape Google actually sends.

    A 403 is what a rate limit answers and also what a grant too narrow to read answers, and those
    two send the user to opposite repairs, so the reason is read out of the body rather than off the
    status. The nesting that read depends on came from Google's documentation and from nothing this
    account ever answered.

    Reaching the transport rather than the client, because the client's whole job is to reduce an
    error to a sentence: by the time it answers, the body is gone. A calendar the account does not
    hold is the benign way to ask for an error, and nothing is written.
    """
    access = await live_client._tokens.current()
    assert isinstance(access, GoogleAccess)

    async with create_google_read_client() as http:
        answer = await HttpxGoogleTransport(http).get(
            events_url(ABSENT_CALENDAR), params={"maxResults": "1"}, token=access.token
        )

    assert answer.is_error, answer.status
    assert answer.body is not None, "an error carrying no body states no reason either"
    assert GoogleErrorPayload.model_validate_json(answer.body).reasons, (
        f"Google answered {answer.status} with no reason where syncr reads one, so a rate limit "
        "and a grant too narrow to read are indistinguishable at this boundary"
    )


# --------------------------------------------------------------------------------------
# What the provider answers to one write, against events this suite created and no others
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
    """The development calendar as a write target, found by the name the owning account gave it."""
    listed = await client.list_calendars()
    assert isinstance(listed, CalendarsRead), listed
    development = next(
        (one for one in listed.calendars if one.display_name == DEVELOPMENT_CALENDAR), None
    )
    assert development is not None, (
        f"{DEVELOPMENT_CALENDAR!r} is not in this account, and every write below lands on it: "
        "this suite will not be pointed at any other calendar."
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
        created_at=datetime.now(UTC),
        sync_state=SyncStateRecord(),
    )


def a_window(days_ahead: int) -> Interval:
    """A window on the development calendar, from the top of the hour ``days_ahead`` days from now.

    Far enough ahead that it cannot overlap anything a person put on the calendar today, and short
    enough that a reconciliation over it reads a handful of events rather than a fortnight.
    """
    start = (utc_now() + timedelta(days=days_ahead)).replace(minute=0, second=0, microsecond=0)
    return Interval(start, start + WINDOW_LENGTH)


def an_intended_event(
    window: Interval, *, description: str, location: str | None = None
) -> ProjectedEvent:
    """One event syncr intends, keyed uniquely so no run can collide with an earlier one's."""
    return ProjectedEvent(
        syncr_key=sha256(f"syncr-live-{uuid4()}".encode()).hexdigest(),
        interval=Interval(window.start, window.start + timedelta(minutes=30)),
        title=SAFE_TITLE,
        description=description,
        location=location,
    )


async def one_event_on(
    calendar_id: str,
    intended: ProjectedEvent,
    *,
    client: GoogleCalendarClient,
    writer: GoogleEventWriter,
    window: Interval,
) -> str:
    """Insert ``intended``, and answer the identifier the provider gave it.

    The insert's own answer carries no identifier, because the write path reports whether a write
    landed and nothing else. So the identifier comes from a read matched on the key the insert put
    into the private extended properties, which is how the reconciliation finds it as well: a
    failure here is that round trip failing rather than a lookup being awkward.
    """
    applied = await writer.insert(calendar_id, intended)
    assert isinstance(applied, WriteApplied), applied
    read = await client.list_events(calendar_id, sync_token=None, window=window)
    assert isinstance(read, EventsRead), read
    keyed = [
        one.id
        for one in read.events
        if one.private_property(SYNCR_KEY_PROPERTY) == intended.syncr_key
    ]
    assert len(keyed) == 1, (
        "an insert should be findable once by the key it carried, and this window holds "
        f"{len(keyed)} event(s) under it: {keyed}"
    )
    return keyed[0]


def one_named(events: tuple[GoogleEventPayload, ...], identifier: str) -> GoogleEventPayload:
    """The one event carrying this identifier, or the count that is not one."""
    found = [one for one in events if one.id == identifier]
    assert len(found) == 1, f"{identifier} is on the calendar {len(found)} times rather than once"
    return found[0]


async def test_a_patch_stating_a_null_takes_the_field_away_on_the_provider(
    live_client: GoogleCalendarClient, live_writer: GoogleEventWriter
) -> None:
    """THE claim behind every field being present and null in a patch body.

    Google's patch leaves out what a body leaves out, so a description that has gone away has to be
    stated as null or the phone keeps showing the old sentence for as long as the event lives.
    Nothing had ever sent Google a patch at all: the fake answers what syncr expects, and what syncr
    expects is exactly this.
    """
    target = await a_development_target(live_client)
    window = a_window(PATCHED_DAY)
    intended = an_intended_event(
        window,
        description="The sentence a patch has to be able to take away.",
        location="The place a patch has to be able to take away",
    )
    identifier = await one_event_on(
        target.external_id, intended, client=live_client, writer=live_writer, window=window
    )
    try:
        patched = await live_writer.patch(
            target.external_id, identifier, replace(intended, description=None, location=None)
        )
        after = await live_client.list_events(target.external_id, sync_token=None, window=window)

        assert isinstance(patched, WriteApplied), patched
        assert isinstance(after, EventsRead), after
        event = one_named(after.events, identifier)
        assert event.description is None, (
            "Google kept a description a patch stated as null, so a sentence syncr has withdrawn "
            "stays on the calendar for as long as the event lives"
        )
        assert event.location is None, (
            "Google kept a location a patch stated as null, so a place syncr has withdrawn stays "
            "on the calendar for as long as the event lives"
        )
    finally:
        await live_writer.delete(target.external_id, identifier)


async def test_a_delete_of_an_event_already_gone_is_done_and_a_patch_of_one_is_not(
    live_client: GoogleCalendarClient, live_writer: GoogleEventWriter
) -> None:
    """The two readings of Google's answer for an event that is no longer there, and they oppose.

    A deletion got what it wanted, so it is done. A patch left the target missing an event the plan
    holds, so reporting it as a success is exactly the failure that reads as a success. Both
    readings were written from the documentation, and this is the first time either is taken from
    the provider.
    """
    target = await a_development_target(live_client)
    window = a_window(GONE_DAY)
    intended = an_intended_event(window, description="Removed twice, on purpose.")
    identifier = await one_event_on(
        target.external_id, intended, client=live_client, writer=live_writer, window=window
    )

    removed = await live_writer.delete(target.external_id, identifier)
    again = await live_writer.delete(target.external_id, identifier)
    patched = await live_writer.patch(target.external_id, identifier, intended)

    assert isinstance(removed, WriteApplied), removed
    assert isinstance(again, WriteApplied), again
    assert isinstance(patched, WriteRefused), patched
    # Named rather than any refusal at all: a rate limit refuses too, and it means the opposite.
    assert patched.rate_limited is False, patched
    assert "no longer holds" in patched.reason, patched


async def test_an_incremental_read_reports_a_change_and_a_removal_arrives_cancelled(
    live_client: GoogleCalendarClient, live_writer: GoogleEventWriter
) -> None:
    """What a sync token answers when something DID happen, which nothing has ever asked it.

    Two claims the payload model rests on. A change is reported at all, which is the whole of what
    the change detector reads. And a removal arrives as an event carrying an identifier and a
    status, which is why almost every field on an event payload is optional: a model that required a
    start would refuse every deletion, and a deletion nobody can read is occupancy that never goes
    away.
    """
    target = await a_development_target(live_client)
    horizon = Interval(utc_now(), utc_now() + timedelta(days=HORIZON_DAYS))
    full = await live_client.list_events(target.external_id, sync_token=None, window=horizon)
    assert isinstance(full, EventsRead), full
    assert full.sync_token, "a full read must answer with a sync token"

    window = a_window(CHANGED_DAY)
    intended = an_intended_event(window, description="Inserted to make one delta non-empty.")
    identifier = await one_event_on(
        target.external_id, intended, client=live_client, writer=live_writer, window=window
    )
    after_insert = await live_client.list_events(
        target.external_id, sync_token=full.sync_token, window=horizon
    )
    removed = await live_writer.delete(target.external_id, identifier)

    assert isinstance(removed, WriteApplied), removed
    assert isinstance(after_insert, EventsRead), after_insert
    assert identifier in {one.id for one in after_insert.events}, (
        "an incremental read did not report an event inserted after its token was issued, so the "
        "change detector would call a calendar that had changed quiet"
    )
    assert after_insert.sync_token, "an incremental read must answer with the token for the next"
    after_removal = await live_client.list_events(
        target.external_id, sync_token=after_insert.sync_token, window=horizon
    )

    assert isinstance(after_removal, EventsRead), after_removal
    gone = one_named(after_removal.events, identifier)
    assert gone.is_cancelled, gone
    assert (gone.start, gone.end) == (None, None), (
        "a removal arrived carrying times, which is not the shape the payload model's optional "
        "fields were declared for"
    )


# --------------------------------------------------------------------------------------
# The destructive reconciliation, once, against the development calendar
# --------------------------------------------------------------------------------------


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

    **The window is read before anything is written.** A reconciliation removes every event in its
    horizon that syncr does not intend, so an occupied window refuses here rather than being
    discovered afterwards in a count of what has already gone.
    """
    target = await a_development_target(live_client)
    window = a_window(RECONCILED_DAY)
    before = await live_client.list_events(target.external_id, sync_token=None, window=window)
    assert isinstance(before, EventsRead), before
    occupied = read_window(before.events, calendar=target.display_name, window=window)
    if isinstance(occupied, WindowOccupied):
        pytest.fail(occupied.reason)
    google = GoogleAdapter(
        client=live_client,
        profile=ZoneProfile(home_zone="Europe/London"),
        horizon=window,
        clock=utc_now,
        writes=live_writer,
    )
    intended = an_intended_event(
        window,
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
    # Printed as well as asserted, because a passing assertion states no figure and the figure is
    # what a reader of a run needs. Visible with `-s`.
    print(
        f"syncr-live measured over a {WINDOW_LENGTH} window: insert {inserted.duration_ms}ms, "
        f"steady state {unchanged.duration_ms}ms, removal {removed.duration_ms}ms, against a "
        f"{PROJECTION_BUDGET_SECONDS:.0f}s budget and a {WRITE_DEADLINE_SECONDS:.0f}s deadline"
    )
    # The pass the budget is claimed to be reachable on. A steady-state reconciliation writes
    # nothing, so what it spends is one read of the horizon and the diff over it, and a provider
    # that cannot answer that inside the budget cannot meet it on a pass that writes.
    assert unchanged.duration_ms <= PROJECTION_BUDGET_SECONDS * 1000, unchanged
    # Nothing is left behind on the calendar, whatever else this account holds.
    remaining = await live_client.list_events(target.external_id, sync_token=None, window=window)
    assert isinstance(remaining, EventsRead), remaining
    assert intended.syncr_key not in {
        one.private_property(SYNCR_KEY_PROPERTY) for one in remaining.events
    }
