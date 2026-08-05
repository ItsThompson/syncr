"""How long a day is, which blocks belong to it, and what a settled day is.

Everything here is stated against real zones and real transition dates with no repository anywhere,
because these two rules are where the boundaries this epic has paid for land. A fixture zone with a
made-up rule would assert the arithmetic against itself.

The zones are the ones that have found real defects in this codebase: ``Europe/London`` for an
ordinary transition, ``Australia/Lord_Howe`` for a 30-minute gap, ``America/Havana`` for a
transition at midnight, and ``Pacific/Apia`` for a date that does not exist at all.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from syncr_api.outcomes.days import blocks_of_the_day, dates_in, day_span
from syncr_api.outcomes.ledger import (
    is_unconfirmed,
    ledger_rows,
    settled_at,
    split_at,
)
from syncr_api.plans.records import BlockOutcomeRecord
from syncr_domain.identity import BindingRef, Origin
from syncr_domain.intervals import Interval
from syncr_domain.outcomes import OutcomeState
from syncr_domain.plan import Block, PlanDocument
from syncr_domain.weeks import IsoWeek, active_zone_by_date
from syncr_domain.zones import ZoneProfile
from tests.assembly_fakes import A_REASON, TENANT, a_travel_override

LONDON = "Europe/London"
HAVANA = "America/Havana"
LORD_HOWE = "Australia/Lord_Howe"
APIA = "Pacific/Apia"

HOURS_IN_A_DAY = 24
MINUTES_PER_HOUR = 60

# 2026-03-29 is the spring-forward date in Europe/London: 01:00 becomes 02:00.
LONDON_SPRING_FORWARD = date(2026, 3, 29)
# 2026-10-25 is the fall-back date there: 02:00 happens twice.
LONDON_FALL_BACK = date(2026, 10, 25)
# America/Havana moves its clock AT midnight, so 2026-03-08 begins at 01:00 local.
HAVANA_SPRING_FORWARD = date(2026, 3, 8)
# Australia/Lord_Howe shifts by 30 minutes rather than an hour.
LORD_HOWE_SPRING_FORWARD = date(2026, 10, 4)
# Pacific/Apia skipped this date entirely when it crossed the date line.
APIA_SKIPPED = date(2011, 12, 30)

AREA = TENANT


def profile(zone: str) -> ZoneProfile:
    return ZoneProfile(home_zone=zone)


def minutes(span: Interval | None) -> int:
    assert span is not None
    return span.total_minutes()


def a_day(on: date, zone: str = LONDON) -> Interval:
    """The span a date covers, for a test whose subject is not whether the date exists."""
    span = day_span(on, profile(zone))
    assert span is not None
    return span


class TestHowLongADayIs:
    """One statement of a local day, and the four transition shapes it has to answer for."""

    def test_an_ordinary_day_is_twenty_four_hours(self) -> None:
        assert minutes(day_span(date(2026, 2, 9), profile(LONDON))) == HOURS_IN_A_DAY * 60

    def test_a_spring_forward_day_is_an_hour_short(self) -> None:
        # The day really was 23 hours long. A ledger that said 24 would place a block in a day the
        # user did not have.
        assert minutes(day_span(LONDON_SPRING_FORWARD, profile(LONDON))) == 23 * MINUTES_PER_HOUR

    def test_a_fall_back_day_is_an_hour_long(self) -> None:
        assert minutes(day_span(LONDON_FALL_BACK, profile(LONDON))) == 25 * MINUTES_PER_HOUR

    def test_a_transition_at_midnight_still_bounds_the_day(self) -> None:
        # Havana moves its clock at midnight, so the date's own first instant is the one that
        # shifts. `to_instant` resolves a nonexistent local midnight forward by the gap, which
        # leaves the day 23 hours long rather than unbuildable.
        assert minutes(day_span(HAVANA_SPRING_FORWARD, profile(HAVANA))) == 23 * MINUTES_PER_HOUR

    def test_a_thirty_minute_transition_is_measured_in_minutes(self) -> None:
        # An hour-shaped rule would report 24 hours here and be wrong by half an hour.
        assert (
            minutes(day_span(LORD_HOWE_SPRING_FORWARD, profile(LORD_HOWE)))
            == HOURS_IN_A_DAY * MINUTES_PER_HOUR - 30
        )

    def test_a_date_the_zone_skipped_entirely_names_no_day(self) -> None:
        # Pacific/Apia crossed the date line and 30 December 2011 never happened there. Local
        # midnight on it and on the 31st are one instant, so there is no day to render and nothing
        # to confirm. The absence is the answer.
        assert day_span(APIA_SKIPPED, profile(APIA)) is None

    def test_the_dates_either_side_of_a_skipped_one_still_exist(self) -> None:
        # The control. Without it, "names no day" could be true of every date in that zone.
        assert day_span(APIA_SKIPPED - timedelta(days=1), profile(APIA)) is not None
        assert day_span(APIA_SKIPPED + timedelta(days=1), profile(APIA)) is not None

    def test_consecutive_days_abut_exactly_across_a_transition(self) -> None:
        # The property the day-membership rule rests on. If one day's end and the next day's start
        # differed, a block could fall in two days or in none, and one falling in none would be
        # lost from every ledger with no symptom.
        for on in (LONDON_SPRING_FORWARD, LONDON_FALL_BACK, HAVANA_SPRING_FORWARD):
            zone = LONDON if on != HAVANA_SPRING_FORWARD else HAVANA
            first = day_span(on, profile(zone))
            second = day_span(on + timedelta(days=1), profile(zone))

            assert first is not None
            assert second is not None
            assert first.end == second.start

    def test_a_travel_boundary_shortens_the_day_it_falls_on(self) -> None:
        # Moving five hours east on 12 February makes that day five hours shorter, which is the
        # day the user really had. The override is read through the profile, so nothing here
        # states a rule about which zone is active.
        travelling = ZoneProfile(
            home_zone=LONDON,
            travel_overrides=(
                a_travel_override(
                    start_date=date(2026, 2, 12), end_date=date(2026, 2, 20), zone="Asia/Karachi"
                ).as_domain(),
            ),
        )

        assert minutes(day_span(date(2026, 2, 11), travelling)) == 19 * MINUTES_PER_HOUR

    def test_a_range_names_every_date_from_the_first_to_the_last(self) -> None:
        assert list(dates_in(date(2026, 2, 9), date(2026, 2, 11))) == [
            date(2026, 2, 9),
            date(2026, 2, 10),
            date(2026, 2, 11),
        ]

    def test_a_range_of_one_day_is_the_same_date_twice(self) -> None:
        assert list(dates_in(date(2026, 2, 9), date(2026, 2, 9))) == [date(2026, 2, 9)]

    def test_a_range_that_runs_backward_names_nothing(self) -> None:
        assert list(dates_in(date(2026, 2, 11), date(2026, 2, 9))) == []


WEEK = IsoWeek(2026, 7)
MONDAY_MIDNIGHT = datetime(2026, 2, 9, tzinfo=UTC)


def at(hour: float, *, day: int = 0) -> datetime:
    return MONDAY_MIDNIGHT + timedelta(days=day, hours=hour)


def a_block(*, interval: Interval, title: str = "Gym", index: int = 0) -> Block:
    return Block(
        iso_week=WEEK,
        interval=interval,
        binding=BindingRef.for_habit(AREA, index=index),
        title=title,
        reason=A_REASON,
        area_id=AREA,
    )


def a_document(*blocks: Block) -> PlanDocument:
    return PlanDocument(
        iso_week=WEEK,
        zone_by_date=active_zone_by_date(WEEK, profile(LONDON)),
        discretionary_minutes=0,
        unallocated_minutes=0,
        oversubscription_minutes=0,
        blocks=blocks,
    )


class TestWhichDayABlockBelongsTo:
    """The block belongs to the day it STARTS in, and that partition is total."""

    def test_a_block_inside_the_day_is_the_days(self) -> None:
        inside = a_block(interval=Interval(at(9), at(10)))

        assert blocks_of_the_day(a_document(inside), a_day(date(2026, 2, 9))) == (inside,)

    def test_a_block_that_runs_past_midnight_belongs_to_the_day_it_began_in(self) -> None:
        # A night's sleep from Monday 23:00 to Tuesday 07:00. Listed on Monday, and on Monday only:
        # listing it on both would make one block confirmable twice, and "what happened to this"
        # would then have two answers.
        overnight = a_block(interval=Interval(at(23), at(7, day=1)), title="Sleep")
        document = a_document(overnight)

        assert blocks_of_the_day(document, a_day(date(2026, 2, 9))) == (overnight,)
        assert blocks_of_the_day(document, a_day(date(2026, 2, 10))) == ()

    def test_a_block_beginning_exactly_at_midnight_is_the_later_days(self) -> None:
        # The half-open boundary, at the one instant a user will really hit: a block at 00:00
        # belongs to the day that starts then, because a day is [midnight, midnight).
        at_midnight = a_block(interval=Interval(at(0, day=1), at(1, day=1)))
        document = a_document(at_midnight)

        assert blocks_of_the_day(document, a_day(date(2026, 2, 9))) == ()
        assert blocks_of_the_day(document, a_day(date(2026, 2, 10))) == (at_midnight,)

    def test_a_week_with_no_plan_holds_no_blocks(self) -> None:
        assert blocks_of_the_day(None, a_day(date(2026, 2, 9))) == ()

    def test_the_days_blocks_are_emitted_in_one_order_whatever_order_they_arrived_in(self) -> None:
        # Two reads of one day have to agree, or the ledger reorders itself under the user between
        # the read and the action they take on it.
        early = a_block(interval=Interval(at(9), at(10)), index=0)
        late = a_block(interval=Interval(at(11), at(12)), index=1)
        monday = a_day(date(2026, 2, 9))

        forward = blocks_of_the_day(a_document(early, late), monday)
        backward = blocks_of_the_day(a_document(late, early), monday)

        assert forward == backward == (early, late)

    def test_two_blocks_sharing_an_interval_and_a_title_still_order_totally(self) -> None:
        # A user-authored multitask is legitimate, so the tie-break has to reach past the title:
        # two rows that compared equal would swap between reads.
        first = a_block(interval=Interval(at(9), at(10)), title="Reading", index=0)
        second = a_block(interval=Interval(at(9), at(10)), title="Reading", index=1)
        monday = a_day(date(2026, 2, 9))

        forward = blocks_of_the_day(a_document(first, second), monday)
        backward = blocks_of_the_day(a_document(second, first), monday)

        assert forward == backward
        assert len(forward) == 2


def an_outcome(
    *, state: OutcomeState = OutcomeState.PRESUMED, confirmed_at: datetime | None = None
) -> BlockOutcomeRecord:
    return BlockOutcomeRecord(
        id=AREA,
        tenant_id=TENANT,
        block_id="whichever",
        binding=BindingRef.for_habit(AREA, index=0),
        revision_id=AREA,
        state=state,
        actual_minutes=None,
        actual_interval=None,
        occurred_at=at(9),
        confirmed_at=confirmed_at,
    )


class TestTheLedgersRowsAndItsHeader:
    """What a row reads as with no outcome on it, and where the two sections part."""

    def test_a_block_with_no_row_reads_as_presumed_and_unconfirmed(self) -> None:
        # O1, as the read model states it: the absence of a row is the ordinary case rather than a
        # gap, because every block defaults to presumed with no user action.
        rows = ledger_rows([a_block(interval=Interval(at(9), at(10)))], outcomes={}, area_names={})

        assert rows[0].state is OutcomeState.PRESUMED
        assert rows[0].outcome is None
        assert not rows[0].is_confirmed

    def test_a_row_carries_the_duration_and_the_areas_name(self) -> None:
        block = a_block(interval=Interval(at(9), at(10.5)))

        rows = ledger_rows([block], outcomes={}, area_names={AREA: "Fitness"})

        assert rows[0].duration_minutes == 90
        assert rows[0].area_name == "Fitness"
        assert rows[0].origin is Origin.HABIT

    def test_a_row_whose_area_no_longer_exists_still_renders(self) -> None:
        # O8's shape at this layer: the row is a fact about a week that happened, and the Area it
        # named may since have been deleted. A missing name is a null, not a refusal.
        rows = ledger_rows([a_block(interval=Interval(at(9), at(10)))], outcomes={}, area_names={})

        assert rows[0].area_id == AREA
        assert rows[0].area_name is None

    def test_a_block_that_has_ended_is_behind_now_and_one_still_running_is_ahead(self) -> None:
        # The grouping boundary is the END, because the ledger asks "did this happen" and a block
        # still running has not happened yet. This is deliberately NOT the immovability boundary,
        # which is the start.
        ended = a_block(interval=Interval(at(8), at(9)), index=0)
        running = a_block(interval=Interval(at(9), at(10)), index=1)
        rows = ledger_rows([ended, running], outcomes={}, area_names={})

        behind, ahead = split_at(rows, at(9.5))

        assert [row.block_id for row in behind] == [ended.id]
        assert [row.block_id for row in ahead] == [running.id]

    def test_every_row_lands_in_exactly_one_section(self) -> None:
        blocks = [
            a_block(interval=Interval(at(hour), at(hour + 1)), index=hour) for hour in range(6)
        ]
        rows = ledger_rows(blocks, outcomes={}, area_names={})

        behind, ahead = split_at(rows, at(3))

        assert len(behind) + len(ahead) == len(rows)
        assert set(behind).isdisjoint(ahead)


class TestWhenADayIsSettled:
    """One rule, taken over one entry per block, so both callers read it the same way."""

    def test_a_day_whose_every_block_carries_a_confirmation_is_settled(self) -> None:
        stamp = at(22)

        assert settled_at([an_outcome(confirmed_at=stamp), an_outcome(confirmed_at=stamp)]) == stamp
        assert not is_unconfirmed([an_outcome(confirmed_at=stamp)])

    def test_a_day_with_one_block_nobody_answered_for_is_not_settled(self) -> None:
        # The case a later re-solve produces: a block added to a confirmed day is a block nobody
        # has answered for, so the day goes back to unconfirmed until they do.
        assert settled_at([an_outcome(confirmed_at=at(22)), None]) is None
        assert is_unconfirmed([an_outcome(confirmed_at=at(22)), None])

    def test_a_row_recorded_without_a_confirmation_does_not_settle_the_day(self) -> None:
        # O3: marking a block skipped says something about the block, not about the day. The day
        # stays excluded from reviews and from learning until the user answers for it.
        assert settled_at([an_outcome(state=OutcomeState.SKIPPED)]) is None
        assert is_unconfirmed([an_outcome(state=OutcomeState.SKIPPED)])

    def test_the_instant_reported_is_the_earliest_of_the_days_confirmations(self) -> None:
        # When the user answered for the day. A correction recorded in March against a day
        # confirmed in February must not make the day read as settled in March.
        early = at(22)
        late = at(22, day=30)

        assert settled_at([an_outcome(confirmed_at=late), an_outcome(confirmed_at=early)]) == early

    @pytest.mark.parametrize("recorded", [[], ()], ids=["an empty list", "an empty tuple"])
    def test_a_day_holding_no_block_is_neither_settled_nor_unconfirmed(
        self, recorded: list[BlockOutcomeRecord]
    ) -> None:
        # Counting such a day would report a backlog of days on which the user had nothing planned.
        assert settled_at(recorded) is None
        assert not is_unconfirmed(recorded)
