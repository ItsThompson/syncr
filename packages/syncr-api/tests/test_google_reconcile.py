"""The destructive write against a fake provider: what was sent, in what order, and what landed.

This is the one path in the product whose partial state is a real calendar on a real phone, so the
assertions are about the requests: which method, carrying which body, and how many of them had
landed when the provider refused one.

**Nothing here has ever run against the real Google API.** The live suite that would prove syncr's
reading of Google's write contract needs a standing authorization only a person at a consent screen
can obtain, so the destructive write ships behind a refusal and the marked test in
``test_google_live.py`` is where it will first meet the real thing.

Six groups.

**The refusal.** A deployment that will not write refuses before reading anything, so it spends no
request to reach a conclusion it already held. The adapter a request composes always holds that arm.

**The four arms, through the provider.** Each diff decision becomes the request it should, with the
key in the private extended properties and the times in the body.

**foreign_deleted is counted separately**, because removing something the user made by hand must be
visible rather than silent.

**A partial failure reports what it applied and does not read as a success.** The counts on the
raised failure are exact, and the events that had already landed are still counted.

**What is retried and what is not.** A rate limit is retried, because the provider is known to have
rejected it. A 5xx, a dropped connection and a timeout are not, because any of them may have applied
the write and a retry would create a second event for the same block.

**The token.** A dead grant refuses the write and has already raised the loudest notice in the
product, because the token source records the expiry where it discovers it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import httpx
import pytest

from syncr_api.calendars.config import GOOGLE, WRITE_TARGET
from syncr_api.calendars.google_adapter import GoogleAdapter
from syncr_api.calendars.google_backoff import BackoffPolicy
from syncr_api.calendars.google_client import GoogleCalendarClient
from syncr_api.calendars.google_config import MAX_PAGE_BYTES, WRITE_DEADLINE_SECONDS
from syncr_api.calendars.google_events import (
    DELETE,
    PATCH,
    POST,
    SYNCR_KEY_PROPERTY,
    GoogleEventWriter,
    WritesUnavailable,
)
from syncr_api.calendars.google_writes import (
    HttpxGoogleWriteTransport,
    create_google_write_client,
)
from syncr_api.calendars.projection import ProjectedEvent
from syncr_api.calendars.projection_errors import (
    PREVIOUS_PROJECTION_STANDS,
    ProjectionFailed,
    ProjectionRefused,
)
from syncr_api.calendars.records import CalendarSourceRecord, SyncStateRecord
from syncr_api.google_account.tokens import GoogleGrantDead
from syncr_domain.intervals import Interval
from syncr_domain.zones import ZoneProfile
from tests.fake_google import (
    ACCESS_TOKEN,
    EVENT_STORED,
    NO_CONTENT,
    FixedTokens,
    RecordedGoogle,
    RecordedGoogleWrites,
    error_body,
    event,
    events_page,
    failed,
    ok,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_api.calendars.google_events import EventWriting
    from syncr_api.calendars.google_transport import GoogleResponse

NOW = datetime(2026, 2, 9, 9, tzinfo=UTC)
HORIZON = Interval(NOW, NOW + timedelta(days=14))
LONDON = ZoneProfile(home_zone="Europe/London")

CALENDAR = "syncr-dev@group.calendar.google.com"
KEY = "a" * 64
OTHER_KEY = "b" * 64

# The one deployment state a projection needs: a Google calendar holding the write-target role.
TARGET = CalendarSourceRecord(
    id=uuid4(),
    tenant_id=uuid4(),
    provider=GOOGLE,
    role=WRITE_TARGET,
    display_name="syncr (dev)",
    external_id=CALENDAR,
    included=True,
    horizon_days=14,
    sync_state=SyncStateRecord(),
)


def intended(key: str = KEY, *, title: str = "Gym · Legs", hour: int = 18) -> ProjectedEvent:
    start = NOW.replace(hour=hour, minute=0)
    return ProjectedEvent(
        syncr_key=key,
        interval=Interval(start, start + timedelta(hours=1)),
        title=title,
        description="Chosen by the rotation: Gym · Legs",
    )


def mine(key: str = KEY, *, identifier: str = "evt-mine", **overrides: object) -> dict[str, object]:
    """One event on the target that syncr wrote: it carries the key in its private properties."""
    payload = event(
        identifier,
        start="2026-02-09T18:00:00Z",
        end="2026-02-09T19:00:00Z",
        summary="Gym · Legs",
        **overrides,  # type: ignore[arg-type]
    )
    payload["description"] = "Chosen by the rotation: Gym · Legs"
    payload["extendedProperties"] = {"private": {SYNCR_KEY_PROPERTY: key}}
    return payload


def theirs(identifier: str = "evt-theirs") -> dict[str, object]:
    """One event the user created by hand: nothing ever wrote a key into it."""
    return event(
        identifier, start="2026-02-09T12:00:00Z", end="2026-02-09T13:00:00Z", summary="Dentist"
    )


def a_writer(
    transport: RecordedGoogleWrites, *, tokens: FixedTokens | None = None
) -> GoogleEventWriter:
    """A writer whose waits are injected: a real one would sleep out a backoff under a defect."""

    async def sleep(_seconds: float) -> None:
        return None

    return GoogleEventWriter(
        transport=transport, tokens=tokens or FixedTokens(), backoff=BackoffPolicy(), sleep=sleep
    )


def an_adapter(
    reads: Sequence[GoogleResponse],
    writes: EventWriting,
    *,
    tokens: FixedTokens | None = None,
    write_deadline_seconds: float = WRITE_DEADLINE_SECONDS,
) -> GoogleAdapter:
    async def sleep(_seconds: float) -> None:
        return None

    return GoogleAdapter(
        client=GoogleCalendarClient(
            transport=RecordedGoogle(answers=reads),
            tokens=tokens or FixedTokens(),
            backoff=BackoffPolicy(),
            sleep=sleep,
        ),
        profile=LONDON,
        horizon=HORIZON,
        clock=lambda: NOW,
        writes=writes,
        write_deadline_seconds=write_deadline_seconds,
    )


def projecting(
    *held: dict[str, object], **transport_options: object
) -> tuple[GoogleAdapter, RecordedGoogleWrites]:
    """An adapter reading a target that holds ``held``, with a recording write transport."""
    written = RecordedGoogleWrites(**transport_options)  # type: ignore[arg-type]
    return an_adapter([ok(events_page(*held))], a_writer(written)), written


# --------------------------------------------------------------------------------
# The refusal
# --------------------------------------------------------------------------------


async def test_a_deployment_that_will_not_write_refuses_before_reading_anything() -> None:
    reads = RecordedGoogle(answers=[ok(events_page())])
    google = GoogleAdapter(
        client=GoogleCalendarClient(transport=reads, tokens=FixedTokens()),
        profile=LONDON,
        horizon=HORIZON,
        clock=lambda: NOW,
        writes=WritesUnavailable(reason="writing is switched off in this deployment."),
    )

    with pytest.raises(ProjectionRefused, match="switched off") as refusal:
        await google.reconcile(TARGET, [intended()])

    assert reads.calls == []
    assert refusal.value.applied.written == 0
    assert PREVIOUS_PROJECTION_STANDS in str(refusal.value)


async def test_a_refusal_and_a_failure_carry_different_codes() -> None:
    """The repair differs: a failure is retried and may clear, a refusal holds until an operator
    acts."""
    assert ProjectionRefused.code != ProjectionFailed.code


# --------------------------------------------------------------------------------
# The four arms, through the provider
# --------------------------------------------------------------------------------


async def test_an_event_syncr_intends_and_the_target_lacks_is_inserted() -> None:
    google, written = projecting()

    result = await google.reconcile(TARGET, [intended()])

    assert written.methods() == [POST]
    assert result.inserted == 1
    assert result.written == 1


async def test_an_insert_carries_the_key_in_the_private_extended_properties() -> None:
    google, written = projecting()

    await google.reconcile(TARGET, [intended()])

    (write,) = written.writes
    assert write.body is not None
    assert write.body["extendedProperties"] == {"private": {SYNCR_KEY_PROPERTY: KEY}}
    assert write.body["summary"] == "Gym · Legs"
    assert write.body["start"] == {"dateTime": "2026-02-09T18:00:00+00:00"}
    assert write.token == ACCESS_TOKEN


async def test_an_event_in_both_and_differing_is_patched_at_its_own_address() -> None:
    google, written = projecting(mine(identifier="evt-7"))

    result = await google.reconcile(TARGET, [intended(title="Gym · Push")])

    assert written.methods() == [PATCH]
    assert written.writes[0].url.endswith("/evt-7")
    assert written.writes[0].body is not None
    assert written.writes[0].body["summary"] == "Gym · Push"
    assert result.patched == 1


async def test_an_event_already_correct_is_not_written_at_all() -> None:
    google, written = projecting(mine())

    result = await google.reconcile(TARGET, [intended()])

    assert written.writes == []
    assert result.written == 0
    assert result.unchanged == 1


async def test_an_event_syncr_no_longer_intends_is_deleted() -> None:
    google, written = projecting(mine(identifier="evt-stale"))

    result = await google.reconcile(TARGET, [])

    assert written.methods() == [DELETE]
    assert written.writes[0].url.endswith("/evt-stale")
    assert written.writes[0].body is None
    assert result.deleted == 1
    assert result.foreign_deleted == 0


async def test_the_four_arms_are_applied_patches_inserts_deletes() -> None:
    """A partial application leaves a stale event rather than a gap where a commitment should be."""
    google, written = projecting(mine(OTHER_KEY, identifier="evt-patch"), mine(identifier="x"))

    await google.reconcile(
        TARGET,
        [intended(OTHER_KEY, title="Leetcode"), intended("c" * 64, title="Prep", hour=10)],
    )

    assert written.methods() == [PATCH, POST, DELETE]


# --------------------------------------------------------------------------------
# foreign_deleted
# --------------------------------------------------------------------------------


async def test_an_event_with_no_syncr_key_is_deleted_and_counted_as_foreign() -> None:
    google, written = projecting(theirs())

    result = await google.reconcile(TARGET, [])

    assert written.methods() == [DELETE]
    assert result.foreign_deleted == 1
    assert result.deleted == 0


async def test_a_foreign_deletion_is_counted_apart_from_syncrs_own() -> None:
    google, _written = projecting(theirs(), mine(identifier="evt-stale"))

    result = await google.reconcile(TARGET, [])

    assert (result.deleted, result.foreign_deleted) == (1, 1)
    # The per-action mapping is what the events metric observes, and it accounts for every write.
    assert sum(result.by_action().values()) == result.written


async def test_an_all_day_event_the_user_created_is_still_removed() -> None:
    """Destructive within the horizon means every shape of event, not only the timed ones."""
    all_day = event("evt-holiday", date_start="2026-02-10", date_end="2026-02-11", summary="Away")
    google, written = projecting(all_day)

    result = await google.reconcile(TARGET, [])

    assert written.methods() == [DELETE]
    assert result.foreign_deleted == 1


async def test_a_cancelled_event_is_not_written_to_at_all() -> None:
    """It occupies no time, so there is nothing on the calendar to remove."""
    google, written = projecting(event("evt-gone", status="cancelled", start=None, end=None))

    result = await google.reconcile(TARGET, [])

    assert written.writes == []
    assert result.written == 0


# --------------------------------------------------------------------------------
# A partial failure
# --------------------------------------------------------------------------------


async def test_a_write_refused_part_way_through_raises_with_what_it_applied() -> None:
    google, written = projecting(
        mine(identifier="evt-stale"), mine(OTHER_KEY, identifier="evt-patch"), fail_after=1
    )

    with pytest.raises(ProjectionFailed) as failure:
        await google.reconcile(TARGET, [intended(OTHER_KEY, title="Leetcode")])

    # The patch landed and the delete was refused, so exactly one write is reported as applied.
    assert written.methods() == [PATCH, DELETE]
    assert failure.value.applied.patched == 1
    assert failure.value.applied.deleted == 0
    assert failure.value.applied.written == 1


async def test_a_failure_states_that_the_previous_projection_is_still_in_place() -> None:
    google, _written = projecting(fail_after=0)

    with pytest.raises(ProjectionFailed) as failure:
        await google.reconcile(TARGET, [intended()])

    assert PREVIOUS_PROJECTION_STANDS in str(failure.value)


async def test_a_reconciliation_that_could_not_read_the_target_writes_nothing() -> None:
    written = RecordedGoogleWrites()
    google = an_adapter([failed(403, error_body("insufficientPermissions"))], a_writer(written))

    with pytest.raises(ProjectionFailed, match="could not be read"):
        await google.reconcile(TARGET, [intended()])

    assert written.writes == []


async def test_a_patch_of_an_event_that_vanished_does_not_read_as_a_success() -> None:
    """The target is left missing an event the plan holds, so the reconciliation did not finish."""
    google, _written = projecting(mine(identifier="evt-7"), by_method={PATCH: failed(404)})

    with pytest.raises(ProjectionFailed, match="removed while the plan was being written"):
        await google.reconcile(TARGET, [intended(title="Gym · Push")])


async def test_a_delete_of_an_event_that_vanished_is_done() -> None:
    """The two readings of a 404 are opposite, and this one got what it asked for."""
    google, _written = projecting(mine(identifier="evt-stale"), by_method={DELETE: failed(404)})

    result = await google.reconcile(TARGET, [])

    assert result.deleted == 1


# --------------------------------------------------------------------------------
# What is retried, and what is not
# --------------------------------------------------------------------------------


async def test_a_rate_limited_write_is_retried_because_the_provider_rejected_it() -> None:
    written = RecordedGoogleWrites(
        by_method={POST: failed(429, error_body("rateLimitExceeded", code=429))}
    )
    google = an_adapter([ok(events_page())], a_writer(written))

    with pytest.raises(ProjectionFailed, match="rate limiting"):
        await google.reconcile(TARGET, [intended()])

    # Three attempts at one request: bounded, because the next reconciliation starts fresh.
    assert written.methods() == [POST, POST, POST]


async def test_a_server_error_is_not_retried_because_it_may_have_applied() -> None:
    """Retrying an ambiguous write is what would put two events on the phone for one block."""
    written = RecordedGoogleWrites(by_method={POST: failed(503)})
    google = an_adapter([ok(events_page())], a_writer(written))

    with pytest.raises(ProjectionFailed, match="unknown"):
        await google.reconcile(TARGET, [intended()])

    assert written.methods() == [POST]


async def test_a_dropped_connection_is_not_retried_either() -> None:
    written = RecordedGoogleWrites(raises=httpx.ConnectError("connection reset"))
    google = an_adapter([ok(events_page())], a_writer(written))

    with pytest.raises(ProjectionFailed, match="unknown"):
        await google.reconcile(TARGET, [intended()])

    assert written.methods() == [POST]


async def test_a_write_google_refused_outright_states_the_status() -> None:
    written = RecordedGoogleWrites(by_method={POST: failed(400)})
    google = an_adapter([ok(events_page())], a_writer(written))

    with pytest.raises(ProjectionFailed, match="400"):
        await google.reconcile(TARGET, [intended()])


async def test_an_account_that_may_no_longer_write_is_not_reported_as_a_rate_limit() -> None:
    """A 403 is what both answer, and the two send the user to opposite repairs."""
    written = RecordedGoogleWrites(by_method={POST: failed(403, error_body("forbidden"))})
    google = an_adapter([ok(events_page())], a_writer(written))

    with pytest.raises(ProjectionFailed, match="no longer be allowed to write"):
        await google.reconcile(TARGET, [intended()])

    assert written.methods() == [POST]


# --------------------------------------------------------------------------------
# The token
# --------------------------------------------------------------------------------


async def test_a_dead_grant_refuses_the_write_and_names_the_repair() -> None:
    # The loudest notice in the product is raised by the token source, where the expiry is
    # discovered: this asserts the write path goes through that source rather than around it.
    tokens = FixedTokens(
        answer=GoogleGrantDead(reason="the Google authorization has to be granted again")
    )
    written = RecordedGoogleWrites()
    google = an_adapter(
        [ok(events_page(mine(identifier="evt-stale")))],
        a_writer(written, tokens=tokens),
    )

    with pytest.raises(ProjectionFailed, match="granted again"):
        await google.reconcile(TARGET, [])

    assert written.writes == []
    assert tokens.asked == 1


async def test_every_write_asks_for_a_token_of_its_own() -> None:
    """A pass two hundred events long must not run its last write on a token that expired."""
    tokens = FixedTokens()
    written = RecordedGoogleWrites()
    google = an_adapter([ok(events_page())], a_writer(written, tokens=tokens))

    await google.reconcile(TARGET, [intended(), intended(OTHER_KEY, title="Leetcode", hour=20)])

    assert tokens.asked == 2


# --------------------------------------------------------------------------------
# What the answers mean
# --------------------------------------------------------------------------------


@pytest.mark.parametrize("answer", [NO_CONTENT, EVENT_STORED], ids=["204", "200 with a body"])
async def test_either_shape_of_success_counts_as_applied(answer: GoogleResponse) -> None:
    written = RecordedGoogleWrites(by_method={POST: answer})
    google = an_adapter([ok(events_page())], a_writer(written))

    result = await google.reconcile(TARGET, [intended()])

    assert result.inserted == 1


async def test_a_reconciliation_that_overruns_its_deadline_states_what_it_applied() -> None:
    """The pass most likely to reach the deadline is the first projection of a full horizon.

    Left uncaught, a ``TimeoutError`` here reaches the runner's contained-fault boundary: no error
    on the write target, therefore no banner, no duration and no event observation, and the counts
    that landed discarded. The read path's own deadline states its failure, and so does this one.
    """
    written = RecordedGoogleWrites(stall_after=1, stall_seconds=0.2)
    google = an_adapter([ok(events_page())], a_writer(written), write_deadline_seconds=0.05)

    with pytest.raises(ProjectionFailed, match="stopped after 0s without finishing") as failure:
        await google.reconcile(TARGET, [intended(), intended(OTHER_KEY, title="Leetcode", hour=20)])

    # The first insert landed and is reported; the second was still in flight when time ran out.
    assert failure.value.applied.inserted == 1
    assert PREVIOUS_PROJECTION_STANDS in str(failure.value)


async def test_a_reconciliation_inside_its_deadline_is_not_stopped() -> None:
    """The control on the assertion above: the same stall, under a deadline that accommodates it."""
    written = RecordedGoogleWrites(stall_after=1, stall_seconds=0.01)
    google = an_adapter([ok(events_page())], a_writer(written), write_deadline_seconds=5.0)

    result = await google.reconcile(
        TARGET, [intended(), intended(OTHER_KEY, title="Leetcode", hour=20)]
    )

    assert result.inserted == 2


# --------------------------------------------------------------------------------
# An event on the target whose span syncr cannot read
# --------------------------------------------------------------------------------


def unreadable(identifier: str, *, key: str | None = None) -> dict[str, Any]:
    """One event the provider states with a timestamp syncr refuses.

    A naive date-time is the dangerous case rather than an absurd one: Python parses it, and
    reading it as UTC would misplace the event by up to thirteen hours, so the read path refuses it.
    """
    payload = event(identifier, start="2026-02-09T18:00:00", end="2026-02-09T19:00:00")
    if key is not None:
        payload["extendedProperties"] = {"private": {SYNCR_KEY_PROPERTY: key}}
    return payload


async def test_an_event_with_an_unreadable_span_and_no_key_is_removed_as_drift() -> None:
    google, written = projecting(unreadable("evt-odd"))

    result = await google.reconcile(TARGET, [])

    assert written.methods() == [DELETE]
    assert result.foreign_deleted == 1


async def test_an_event_with_an_unreadable_span_and_syncrs_key_is_rewritten() -> None:
    """It carries the key, so it is the event syncr means; the span it holds is not one syncr can
    compare, so it cannot match what syncr intends and is patched back to it."""
    google, written = projecting(unreadable("evt-odd", key=KEY))

    result = await google.reconcile(TARGET, [intended()])

    assert written.methods() == [PATCH]
    assert written.writes[0].url.endswith("/evt-odd")
    assert result.patched == 1
    assert result.unchanged == 0


# --------------------------------------------------------------------------------
# The write transport itself
# --------------------------------------------------------------------------------


async def test_the_write_transport_presents_the_bearer_token_and_sends_the_body() -> None:
    seen: dict[str, str] = {}
    sent: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.headers))
        sent.append(request.content)
        return httpx.Response(200, content=b'{"id": "evt-1"}')

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        answer = await HttpxGoogleWriteTransport(http).send(
            POST, "https://example.test/events", token=ACCESS_TOKEN, body={"summary": "Gym"}
        )

    assert answer.status == 200
    assert seen["authorization"] == f"Bearer {ACCESS_TOKEN}"
    assert sent == [b'{"summary":"Gym"}']


async def test_the_write_transport_sends_no_body_on_a_delete() -> None:
    sent: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.content)
        return httpx.Response(204)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        answer = await HttpxGoogleWriteTransport(http).send(
            DELETE, "https://example.test/events/evt-1", token=ACCESS_TOKEN
        )

    assert answer.status == 204
    assert sent == [b""]


async def test_the_write_transport_reports_an_oversize_body_as_no_body() -> None:
    """Half a JSON document is not a smaller document, so the bound answers with nothing."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * (MAX_PAGE_BYTES + 1))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        answer = await HttpxGoogleWriteTransport(http).send(
            POST, "https://example.test/events", token=ACCESS_TOKEN, body={}
        )

    assert answer.body is None


def test_the_write_client_does_not_follow_a_redirect() -> None:
    """Following one would send a bearer token, and the body, to whatever it named."""
    client = create_google_write_client()

    assert client.follow_redirects is False
