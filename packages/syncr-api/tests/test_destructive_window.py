"""The refusal that keeps the live suite's destructive reconciliation off an occupied window.

Every case here is decided by the payloads a read answered, so none of it needs a network: the
provider's part is fetching the events, and this is the reading of them. The live suite calls the
same function against a real answer.

Both directions of both conditions are exercised, because a condition that is green whichever way
it is written is not a condition. The cancelled filter must let a live event through, and the
emptiness test must refuse a single one.
"""

from __future__ import annotations

from datetime import UTC, datetime

from syncr_api.calendars.google_events import SYNCR_KEY_PROPERTY
from syncr_api.calendars.google_payloads import CANCELLED, GoogleEventPayload
from syncr_domain.intervals import Interval
from tests.destructive_window import WindowClear, WindowOccupied, read_window
from tests.fake_google import event

CALENDAR = "syncr (dev)"
WINDOW = Interval(datetime(2026, 2, 9, 9, tzinfo=UTC), datetime(2026, 2, 9, 11, tzinfo=UTC))
TITLE = "Dentist · Mr Achterberg"


def a_payload(
    identifier: str, *, key: str | None = None, **overrides: object
) -> GoogleEventPayload:
    """One event the provider answered, through the model the read path validates it with."""
    payload = event(
        identifier,
        start="2026-02-09T09:30:00Z",
        end="2026-02-09T10:00:00Z",
        summary=TITLE,
        **overrides,  # type: ignore[arg-type]
    )
    if key is not None:
        payload["extendedProperties"] = {"private": {SYNCR_KEY_PROPERTY: key}}
    return GoogleEventPayload.model_validate(payload)


def a_reading(*events: GoogleEventPayload) -> WindowClear | WindowOccupied:
    return read_window(events, calendar=CALENDAR, window=WINDOW)


def test_an_empty_window_is_clear() -> None:
    assert a_reading() == WindowClear()


def test_one_event_created_by_hand_occupies_the_window() -> None:
    reading = a_reading(a_payload("evt-theirs"))

    assert isinstance(reading, WindowOccupied), reading


def test_one_event_an_earlier_run_left_behind_occupies_the_window() -> None:
    """A leftover carries syncr's key and is still an event on a real calendar."""
    reading = a_reading(a_payload("evt-mine", key="a-digest"))

    assert isinstance(reading, WindowOccupied), reading


def test_a_cancelled_event_does_not_occupy_the_window() -> None:
    """It holds no time, so the reconciliation would spend a request to change nothing."""
    reading = a_reading(a_payload("evt-gone", status=CANCELLED))

    assert reading == WindowClear()


def test_a_cancelled_event_does_not_hide_a_live_one_beside_it() -> None:
    """The other direction of the same filter: a window is not clear because part of it is."""
    reading = a_reading(a_payload("evt-gone", status=CANCELLED), a_payload("evt-theirs"))

    assert isinstance(reading, WindowOccupied), reading
    assert "evt-theirs" in reading.reason
    assert "evt-gone" not in reading.reason


def test_the_refusal_names_the_calendar_and_both_bounds_of_the_window() -> None:
    """An operator has to be able to go and look, which needs where and when."""
    reading = a_reading(a_payload("evt-theirs"))

    assert isinstance(reading, WindowOccupied), reading
    assert CALENDAR in reading.reason
    assert WINDOW.start.isoformat() in reading.reason
    assert WINDOW.end.isoformat() in reading.reason


def test_the_refusal_names_every_identifier_it_found() -> None:
    reading = a_reading(a_payload("evt-one"), a_payload("evt-two", key="a-digest"))

    assert isinstance(reading, WindowOccupied), reading
    assert "evt-one" in reading.reason
    assert "evt-two" in reading.reason


def test_the_refusal_tells_a_persons_event_from_an_earlier_runs_leftover() -> None:
    """The key is the whole distinction, and the two send an operator to different actions."""
    reading = a_reading(a_payload("evt-theirs"), a_payload("evt-mine", key="a-digest"))

    assert isinstance(reading, WindowOccupied), reading
    persons, leftover = reading.reason.split("Carrying syncr's key")
    assert "evt-theirs" in persons
    assert "evt-mine" in leftover


def test_the_refusal_carries_no_event_title() -> None:
    """A live account holds real ones, and this message is printed by a failing test."""
    reading = a_reading(a_payload("evt-theirs"))

    assert isinstance(reading, WindowOccupied), reading
    assert TITLE not in reading.reason


def test_the_refusal_states_how_many_events_occupy_the_window() -> None:
    reading = a_reading(a_payload("evt-one"), a_payload("evt-two"), a_payload("evt-three"))

    assert isinstance(reading, WindowOccupied), reading
    assert "holds 3 event(s)" in reading.reason
