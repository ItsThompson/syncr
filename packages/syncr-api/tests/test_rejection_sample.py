"""The bounded sample of refused components, and the count that travels beside it.

A publisher decides how many components a feed holds, and every refusal used to be appended to a
list that is written to JSONB and served whole on every panel render. So the list is now a sample
and the count is its own figure, and the two claims that need proving are that the list stops
growing and that the count does not.

Every feed here is generated over a stated count, and every expected figure is written out by hand.
Nothing reads a bound off the configuration: a test that asserted the sample's length against the
constant that produced it would pass for a sample of any size, including all of them.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from prometheus_client import generate_latest

from syncr_api.calendars.config import (
    ANCHOR_SOURCE,
    ICS,
    MALFORMED_VALUE,
    MISSING_DURATION,
    READ_BUDGET_SPENT,
    UNKNOWN_ZONE,
)
from syncr_api.calendars.events import FetchOutcome, RejectionTally
from syncr_api.calendars.ics_lines import MAX_COMPONENT_DEPTH
from syncr_api.calendars.ics_parse import parse_feed
from syncr_api.calendars.records import CalendarSourceRecord, SyncStateRecord
from syncr_api.calendars.rejections import RejectionAccumulator, one_rejection
from syncr_api.calendars.sync import SyncPass
from syncr_api.calendars.sync_metrics import observed_attempt
from syncr_api.calendars.sync_state import recorded_success
from syncr_common.metrics import REGISTRY
from syncr_domain.intervals import Interval
from syncr_domain.zones import ZoneProfile
from tests.hostile_ics import nested_feed
from tests.rejection_feeds import (
    KINDS_REFUSED_CHEAPLY,
    NOW,
    ordinary_feed,
    refused_feed,
    rejection,
)

HOME = ZoneProfile(home_zone="Europe/London")
HORIZON = Interval(datetime(2026, 2, 9, 0, 0, tzinfo=UTC), datetime(2026, 2, 23, 0, 0, tzinfo=UTC))

REJECTED_FAMILY = "syncr_calendar_events_rejected_total"


def source(**overrides: object) -> CalendarSourceRecord:
    defaults: dict[str, object] = {
        "id": "0f5f9e6a-0000-4000-8000-00000000cafe",
        "tenant_id": "0f5f9e6a-0000-4000-8000-00000000beef",
        "provider": ICS,
        "role": ANCHOR_SOURCE,
        "display_name": "University timetable",
        "external_id": "https://example.ac.uk/timetable.ics",
        "included": True,
        "horizon_days": None,
        "created_at": NOW,
    }
    return CalendarSourceRecord(**{**defaults, **overrides})  # type: ignore[arg-type]


def counter(reason: str) -> float:
    """The rejection counter's reading for one reason, or zero before the series exists."""
    prefix = f'{REJECTED_FAMILY}{{provider="{ICS}",reason="{reason}"}} '
    for line in generate_latest(REGISTRY).decode().splitlines():
        if line.startswith(prefix):
            return float(line.removeprefix(prefix))
    return 0.0


# --------------------------------------------------------------------------------
# The accumulator itself
# --------------------------------------------------------------------------------


def test_the_sample_keeps_the_first_entries_of_each_kind_and_counts_every_rejection() -> None:
    # Two kinds and five refusals of one of them, because a claim about a bound cannot be told from
    # the constant one by a fixture holding one member of anything.
    accumulated = RejectionAccumulator(kept_per_kind=2)
    for line in range(1, 6):
        accumulated.add(rejection(MISSING_DURATION, line=line))
    for line in (91, 92, 93):
        accumulated.add(rejection(UNKNOWN_ZONE, line=line))

    tally = accumulated.tally()

    # The FIRST of each kind: the two lowest lines of five, not the two highest.
    assert [(entry.kind, entry.line) for entry in tally.sample] == [
        (MISSING_DURATION, 1),
        (MISSING_DURATION, 2),
        (UNKNOWN_ZONE, 91),
        (UNKNOWN_ZONE, 92),
    ]
    assert tally.total == 8
    assert dict(tally.counted) == {MISSING_DURATION: 5, UNKNOWN_ZONE: 3}


def test_a_kind_the_sample_has_no_room_for_is_still_counted() -> None:
    # The half a bound on the list alone would lose. Both kinds happened; only one is renderable.
    accumulated = RejectionAccumulator(kept_per_kind=0)
    accumulated.add(rejection(MISSING_DURATION, line=1))
    accumulated.add(rejection(UNKNOWN_ZONE, line=2))

    tally = accumulated.tally()

    assert tally.sample == ()
    assert tally.total == 2
    assert dict(tally.counted) == {MISSING_DURATION: 1, UNKNOWN_ZONE: 1}


def test_a_tally_already_handed_out_does_not_move_when_the_accumulator_counts_more() -> None:
    # A tally is a value: a caller holding one holds a reading of a moment. The accumulator hands
    # out copies for that reason, and the two figures fail differently without them. The counts
    # would keep rising under a caller that already reported them, and the sample would grow past
    # the bound it was built with.
    accumulated = RejectionAccumulator(kept_per_kind=2)
    accumulated.add(rejection(MISSING_DURATION, line=1))
    reported = accumulated.tally()

    accumulated.add(rejection(MISSING_DURATION, line=2))
    accumulated.add(rejection(UNKNOWN_ZONE, line=3))

    assert reported.total == 1
    assert dict(reported.counted) == {MISSING_DURATION: 1}
    assert [entry.line for entry in reported.sample] == [1]
    # And the accumulator did go on counting, so this is a claim about the copy rather than about a
    # dead accumulator.
    assert accumulated.tally().total == 3


def test_a_tally_refuses_a_sample_its_counts_do_not_account_for() -> None:
    # The pair is a figure and its denominator. A sample holding entries the counts never saw is a
    # panel rendering a rejection the total denies happened.
    with pytest.raises(ValueError, match="more"):
        RejectionTally(sample=(rejection(MISSING_DURATION, line=1),), counted={UNKNOWN_ZONE: 4})


def test_a_tally_accepts_a_count_larger_than_its_sample() -> None:
    # The other direction of the same guard: a count ABOVE the sample is the whole point, so the
    # refusal above must not be a refusal of every pair that disagrees.
    tally = RejectionTally(
        sample=(rejection(MISSING_DURATION, line=1),), counted={MISSING_DURATION: 90}
    )

    assert tally.total == 90


# --------------------------------------------------------------------------------
# The parse path
# --------------------------------------------------------------------------------


def test_a_feed_of_fifty_thousand_refused_components_keeps_a_sample_and_the_whole_count() -> None:
    # Nothing bounds a feed's component count, and every refusal was appended to a list stored as
    # JSONB and served whole on a source read. 6.4 MB of body is inside what one fetch may read.
    outcome = parse_feed(refused_feed(50_000), horizon=HORIZON, profile=HOME)

    assert outcome.events_read == 50_000
    assert outcome.rejected_count == 50_000
    # Three refused kinds at three kept each. Written out rather than read off the bound: an
    # expectation composed from the constant would hold for a sample of every one of the 50,000.
    assert len(outcome.rejected) == 9
    assert {entry.kind for entry in outcome.rejected} == set(KINDS_REFUSED_CHEAPLY)
    assert dict(outcome.rejections.counted) == {
        MISSING_DURATION: 16_667,
        UNKNOWN_ZONE: 16_667,
        MALFORMED_VALUE: 16_666,
    }


def test_the_accounting_closes_over_a_feed_that_refused_more_than_the_sample_holds() -> None:
    # The reason the count cannot be dropped in favour of the sample. Every component a feed offered
    # is kept, refused, discarded, applied or read and found to place nothing, and a term that
    # stopped at the sample would leave 49,991 components unaccounted for.
    outcome = parse_feed(refused_feed(50_000), horizon=HORIZON, profile=HOME)

    accounted = (
        outcome.placed
        + outcome.rejected_count
        + outcome.duplicates_discarded
        + outcome.cancelled_discarded
        + outcome.overrides_applied
        + outcome.unplaced
    )
    assert accounted == outcome.events_read == 50_000


def test_a_feed_that_spends_its_reading_budget_keeps_a_sample_and_the_whole_count() -> None:
    # The other shape, and the one the budget was wrongly thought to bound. Every component past the
    # deadline is refused individually so the arithmetic keeps closing, which means the budget
    # bounds the WORK and not the list: 2,000 ordinary masters produce 2,000 rejections.
    #
    # A budget of zero states a spent budget rather than waiting for one.
    outcome = parse_feed(ordinary_feed(2_000), horizon=HORIZON, profile=HOME, budget=0.0)

    assert outcome.events_read == 2_000
    assert outcome.rejected_count == 2_000
    # One kind, so three kept.
    assert len(outcome.rejected) == 3
    assert dict(outcome.rejections.counted) == {READ_BUDGET_SPENT: 2_000}


def test_a_body_the_lexer_refused_counts_the_one_rejection_it_produced() -> None:
    # The feed-level path returns before any component is read, and it goes through the accumulator
    # like every other rejection rather than composing a tally of its own.
    outcome = parse_feed(nested_feed(MAX_COMPONENT_DEPTH + 1), horizon=HORIZON, profile=HOME)

    assert outcome.rejected_count == 1
    assert [entry.component for entry in outcome.rejected] == ["VCALENDAR"]


def test_the_tally_of_a_single_rejection_counts_it() -> None:
    tally = one_rejection(rejection(MALFORMED_VALUE, line=7))

    assert tally.total == 1
    assert len(tally.sample) == 1


# --------------------------------------------------------------------------------
# What reads the count
# --------------------------------------------------------------------------------


def test_the_recorded_success_stores_the_count_and_not_the_length_of_the_sample() -> None:
    outcome = parse_feed(refused_feed(50_000), horizon=HORIZON, profile=HOME)

    state = recorded_success(outcome, at=NOW, cursor=None)

    assert state.rejected_count == 50_000
    assert len(state.rejections) == 9


def test_the_rejection_counter_is_spent_once_per_rejection_and_not_once_per_kept_entry() -> None:
    # The metric is labelled by kind and the sample keeps three per kind, so a counter fed from the
    # sample would raise the same rate for a feed refusing 50,000 components as for one refusing 15,
    # and the alert reading it would be measuring the bound rather than the feed.
    #
    # Read as a delta, because the registry is process-global and the family is a counter.
    outcome = parse_feed(refused_feed(50_000), horizon=HORIZON, profile=HOME)
    before = {reason: counter(reason) for reason in KINDS_REFUSED_CHEAPLY}

    observed_attempt(source(), outcome, failed=False, elapsed=1.0)

    spent = {reason: counter(reason) - before[reason] for reason in KINDS_REFUSED_CHEAPLY}
    assert spent == {MISSING_DURATION: 16_667.0, UNKNOWN_ZONE: 16_667.0, MALFORMED_VALUE: 16_666.0}
    assert sum(spent.values()) == 50_000.0


def test_a_pass_over_a_source_reports_what_it_refused_and_not_what_it_kept() -> None:
    # The figure the worker logs for a whole tick. Read off the sample it would report 9 rejections
    # from a feed that made 50,000 of them, and the log line is the only place a tick's refusals are
    # visible at all.
    outcome = parse_feed(refused_feed(50_000), horizon=HORIZON, profile=HOME)

    tally = SyncPass().plus(outcome, failed=False)

    assert tally.rejected == 50_000
    assert tally.as_log_fields()["rejected_count"] == 50_000


def test_an_outcome_with_no_rejections_reports_no_count() -> None:
    # The identity row. Every figure above is a difference from this one, so a bound that swallowed
    # the empty case would make the rest unreadable.
    outcome = FetchOutcome(reparsed=True)

    assert outcome.rejected == ()
    assert outcome.rejected_count == 0
    assert SyncStateRecord().rejected_count == 0
    assert recorded_success(outcome, at=NOW, cursor=None).rejected_count == 0


def test_a_stored_state_reports_the_count_it_was_given_rather_than_the_sample_it_holds() -> None:
    # The record's own half, away from any parse: two entries kept out of nine refusals.
    state = SyncStateRecord(
        last_success_at=NOW,
        last_attempt_at=NOW,
        rejections=(rejection(MISSING_DURATION, line=1), rejection(UNKNOWN_ZONE, line=2)),
        rejected_total=9,
    )

    assert len(state.rejections) == 2
    assert state.rejected_count == 9
