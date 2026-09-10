"""Why the live suite reads its window before it writes, pinned where no credential is needed.

The destructive reconciliation in ``test_google_live.py`` removes every event inside its horizon
that syncr does not intend. Two properties keep that off a person's calendar, and neither was
guarded:

**The assertion set alone cannot see a foreign deletion.** A window occupied by one event nobody
keyed satisfies every count that suite asserts, because the foreign removal happens on the first
pass while the count asserted at zero is read on the third. That is measured here, so the property
survives with no network and no account.

**The refusal has to precede the writer's construction**, not merely appear somewhere in the test.
An occupied window discovered after the adapter exists is a window already reconciled. The order is
read out of the source, because that suite is marker-excluded and its fixtures need a credential:
nothing else in the tree can observe its shape, so an edit that moved the refusal would leave every
check green.

The counts come from the stateful calendar the projection-runner suite uses, so the three passes are
a real sequence over a provider that remembers rather than a script of canned answers. A transport
that answered the same page every time could not express this at all: the whole point is what the
second and third passes see once the first has already removed something.
"""

from __future__ import annotations

import ast
from datetime import timedelta
from pathlib import Path
from typing import Final
from uuid import uuid4

import httpx

from syncr_api.calendars.config import GOOGLE, WRITE_TARGET
from syncr_api.calendars.google_client import GoogleCalendarClient
from syncr_api.calendars.google_events import GoogleEventWriter
from syncr_api.calendars.google_transport import HttpxGoogleTransport
from syncr_api.calendars.google_write_adapter import GoogleWriteTargetAdapter as GoogleAdapter
from syncr_api.calendars.google_writes import HttpxGoogleWriteTransport
from syncr_api.calendars.projection import ProjectedEvent
from syncr_api.calendars.records import CalendarSourceRecord, SyncStateRecord
from syncr_domain.intervals import Interval
from syncr_domain.zones import ZoneProfile
from tests.fake_google import FixedTokens
from tests.test_projection_runner import NOW, FakeCalendar

LIVE_SUITE: Final = Path(__file__).resolve().parent / "test_google_live.py"
DESTRUCTIVE_TEST: Final = "test_one_destructive_reconciliation_against_the_development_calendar"
# Larger than any line number a source file holds, so "no such call" orders after every call.
NEVER: Final = 1 << 30

# The live suite's shape: a short window, and one event syncr intends inside it.
WINDOW: Final = Interval(NOW, NOW + timedelta(hours=2))
KEY: Final = "c" * 64


def a_target() -> CalendarSourceRecord:
    return CalendarSourceRecord(
        id=uuid4(),
        tenant_id=uuid4(),
        provider=GOOGLE,
        role=WRITE_TARGET,
        display_name="syncr (dev)",
        external_id="dev@group.calendar.google.com",
        included=True,
        horizon_days=14,
        created_at=NOW,
        sync_state=SyncStateRecord(),
    )


def intended() -> ProjectedEvent:
    return ProjectedEvent(
        syncr_key=KEY,
        interval=Interval(NOW, NOW + timedelta(minutes=30)),
        title="syncr live suite \u00b7 safe to delete",
        description="Written by the live Google suite.",
    )


def an_adapter_over(calendar: FakeCalendar) -> GoogleAdapter:
    """The adapter the live suite builds, over a provider that remembers what it is sent."""
    client = httpx.AsyncClient(transport=httpx.MockTransport(calendar.handle))
    tokens = FixedTokens()
    return GoogleAdapter(
        client=GoogleCalendarClient(
            transport=HttpxGoogleTransport(client),
            tokens=tokens,
        ),
        profile=ZoneProfile(home_zone="Europe/London"),
        horizon=WINDOW,
        writes=GoogleEventWriter(
            transport=HttpxGoogleWriteTransport(client),
            tokens=tokens,
        ),
    )


def a_calendar_holding_a_persons_event() -> FakeCalendar:
    calendar = FakeCalendar()
    calendar.add_by_hand("evt-theirs", summary="Dentist", start=NOW + timedelta(minutes=15))
    return calendar


def the_destructive_test() -> ast.FunctionDef | ast.AsyncFunctionDef:
    """The live suite's destructive test, as a syntax tree.

    Parsed rather than imported. The module is marker-excluded and its fixtures need a credential,
    so importing it would prove nothing about the order its body runs in.
    """
    parsed = ast.parse(LIVE_SUITE.read_text(encoding="utf-8"))
    found = [
        node
        for node in parsed.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name == DESTRUCTIVE_TEST
    ]
    assert len(found) == 1, f"{DESTRUCTIVE_TEST} is defined {len(found)} times in {LIVE_SUITE.name}"
    return found[0]


def first_line_calling(node: ast.AST, name: str) -> int:
    """The line of the first call to ``name`` inside ``node``, or ``NEVER`` when it makes none."""
    return min(
        (
            found.lineno
            for found in ast.walk(node)
            if isinstance(found, ast.Call)
            and isinstance(found.func, ast.Name)
            and found.func.id == name
        ),
        default=NEVER,
    )


def the_body() -> str:
    source = ast.get_source_segment(LIVE_SUITE.read_text(encoding="utf-8"), the_destructive_test())
    assert source is not None, f"{DESTRUCTIVE_TEST} has no source segment"
    return source


class TestTheAssertionSetCannotSeeAForeignDeletion:
    """Why the pre-flight exists, measured rather than argued.

    Every assertion the live suite made before the pre-flight landed holds while an event nobody
    keyed is destroyed. So that set was satisfiable by a run that removed a person's commitment, and
    no reordering or strengthening of those five could have caught it: the removal happens on the
    first pass and the count that would show it is read on the third.
    """

    async def test_the_five_counts_hold_while_a_persons_event_is_destroyed(self) -> None:
        calendar = a_calendar_holding_a_persons_event()
        google = an_adapter_over(calendar)

        first = await google.reconcile(a_target(), [intended()])
        second = await google.reconcile(a_target(), [intended()])
        third = await google.reconcile(a_target(), [])

        # The five the live suite asserted before the pre-flight landed. Every one holds.
        assert first.inserted == 1
        assert second.written == 0
        assert second.unchanged == 1
        assert third.deleted == 1
        assert third.foreign_deleted == 0
        # And the count none of them reads: a person's event was removed on the first pass.
        assert first.foreign_deleted == 1, (
            "this case exists to show a foreign deletion happening, so a run where none happens is "
            "not exercising the hazard the pre-flight refusal prevents"
        )
        # The provider agrees, which is what makes this a destruction rather than a count.
        assert "Dentist" not in calendar.titles()

    async def test_the_removal_pass_reads_zero_because_the_removal_already_happened(self) -> None:
        """Why the count asserted at zero could never have caught it, stated on its own."""
        google = an_adapter_over(a_calendar_holding_a_persons_event())

        first = await google.reconcile(a_target(), [intended()])
        third = await google.reconcile(a_target(), [])

        assert first.foreign_deleted == 1
        assert third.foreign_deleted == 0

    async def test_a_clear_window_destroys_nothing(self) -> None:
        """The other direction: the same passes over an empty window remove nothing foreign."""
        calendar = FakeCalendar()
        google = an_adapter_over(calendar)

        first = await google.reconcile(a_target(), [intended()])

        assert first.inserted == 1
        assert first.foreign_deleted == 0


class TestTheLiveSuiteReadsItsWindowBeforeItCanWrite:
    """The ordering property, read out of the source, because the suite cannot be collected here."""

    def test_the_window_is_read_before_the_writing_adapter_exists(self) -> None:
        body = the_destructive_test()

        refusal = first_line_calling(body, "read_window")
        adapter = first_line_calling(body, "GoogleAdapter")

        assert refusal < adapter, (
            f"{DESTRUCTIVE_TEST} constructs GoogleAdapter at line {adapter} and reads its window "
            f"at line {refusal}. A window read after the writer exists is one already reconciled"
        )

    def test_both_calls_the_ordering_compares_are_present(self) -> None:
        """The control. An ordering against a call that is gone would hold vacuously forever."""
        body = the_destructive_test()

        assert first_line_calling(body, "read_window") != NEVER, (
            f"{DESTRUCTIVE_TEST} calls no read_window, so its window is never checked"
        )
        assert first_line_calling(body, "GoogleAdapter") != NEVER, (
            f"{DESTRUCTIVE_TEST} constructs no GoogleAdapter, so this file compares the order of "
            "things that are no longer there"
        )

    def test_the_refusal_stops_the_test_rather_than_noting_what_it_found(self) -> None:
        """A refusal that did not raise would be read, and then written over."""
        assert "pytest.fail" in the_body(), (
            f"{DESTRUCTIVE_TEST} must stop on an occupied window rather than carry on"
        )

    def test_the_window_it_checks_is_the_horizon_it_reconciles(self) -> None:
        """One name for both, so the check and the destruction cannot cover different spans."""
        body = the_body()

        assert "window=window" in body, "the pre-flight must read the span about to be written"
        assert "horizon=window" in body, "the adapter must reconcile the span that was checked"
