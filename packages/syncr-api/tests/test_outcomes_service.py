"""The four acts, over fakes: what each writes, what each refuses, and what each invalidates.

The service suite proves the rules. The integration suite proves that the statements do what these
claim, against a real Postgres and a real request.

Two properties are asserted here rather than anywhere else, because both are about a DECISION the
service makes and neither is visible in a wire shape:

**Recording and confirming are two acts on one row.** Every test that records checks
``confirmed_at`` as well as the state, because the defect is silent in both directions: a recording
that confirmed would sweep a day the user never answered for into reviews and learning, and a
confirmation that overwrote a recording would report a skip as done.

**Every write invalidates the weeks that read the log.** The rotation cursor and outstanding debt
are derived from the log, and they are inputs to weeks the user has NOT yet lived, so a write that
did not bump would leave a solve already running for next week committing against a log that has
moved. Nothing fails loudly when that happens: a stale solve simply commits.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syncr_api.core.errors import NotFound, ValidationFailed
from syncr_api.outcomes.config import MAX_CONFIRM_RANGE_DAYS
from syncr_api.outcomes.declarations import Recording
from syncr_domain.fixtures.dst_weeks import LONDON
from syncr_domain.identity import BindingRef, Origin, TransitLeg
from syncr_domain.intervals import Interval
from syncr_domain.outcomes import MISS_STATE, OutcomeState
from syncr_domain.plan import Block
from syncr_domain.weeks import IsoWeek
from tests.assembly_fakes import (
    A_REASON,
    NOW,
    WEEK,
    FakeAreas,
    FakeOverrides,
    FakeSettings,
    a_habit_block,
    a_plan,
    a_travel_override,
    an_area,
    at,
    between,
)
from tests.outcome_fakes import OWNER, Wired, a_revision, a_service
from tests.solve_request_fakes import FixedProjectionHorizon, RecordingSolveRequests

if TYPE_CHECKING:
    from syncr_domain.plan import PlanDocument

MONDAY = date(2026, 2, 9)
TUESDAY = date(2026, 2, 10)
WEDNESDAY = date(2026, 2, 11)
THURSDAY = date(2026, 2, 12)

# `now` is Wednesday 09:00 in a week that is on GMT throughout, so Monday and Tuesday are behind it
# and Thursday is ahead. The lookback for the count of unconfirmed days therefore reaches Monday and
# Tuesday of this week and no other day this fixture plans.
HABIT = uuid4()
ANCHOR = uuid4()
AREA = an_area(name="Fitness")


def a_prep_block(*, interval: Interval) -> Block:
    """An anchor's prep buffer. A block carrying an Area, not a band."""
    return Block(
        iso_week=WEEK,
        interval=interval,
        binding=BindingRef.for_anchor_prep(ANCHOR),
        title="Prepare for Lecture",
        reason=A_REASON,
        area_id=AREA.id,
    )


def a_transit_block(*, interval: Interval, leg: TransitLeg = TransitLeg.OUT) -> Block:
    return Block(
        iso_week=WEEK,
        interval=interval,
        binding=BindingRef.for_anchor_transit(ANCHOR, leg=leg),
        title="Leave for Uni",
        reason=A_REASON,
        area_id=AREA.id,
    )


def a_gym_block(*, day: int, index: int = 0, hours: tuple[float, float] = (9, 10)) -> Block:
    return a_habit_block(
        habit_id=HABIT, area_id=AREA.id, interval=between(*hours, day=day), index=index
    )


def a_week(*blocks: Block) -> PlanDocument:
    return a_plan(blocks=blocks)


def wired(*blocks: Block, now: datetime = NOW) -> Wired:
    """The service over a week holding ``blocks``, with one Area declared."""
    return a_service(plans=[a_revision(a_week(*blocks))], areas=FakeAreas([AREA]), now=now)


def a_recording(
    state: OutcomeState = OutcomeState.COMPLETED,
    *,
    iso_week: str = str(WEEK),
    actual_minutes: int | None = None,
    actual_interval: Interval | None = None,
) -> Recording:
    return Recording(
        iso_week=iso_week,
        state=state,
        actual_minutes=actual_minutes,
        actual_interval=actual_interval,
    )


# --------------------------------------------------------------------------------
# Recording one block
# --------------------------------------------------------------------------------


async def test_a_recorded_outcome_carries_the_blocks_own_binding_and_scheduled_instant() -> None:
    # The binding comes from the block rather than from the request: it is what the row
    # denormalizes and what the re-derivation keys on, so a caller able to supply one could
    # attribute a fact about one habit to another.
    block = a_gym_block(day=1)
    scene = wired(block)

    recorded = await scene.service.record(OWNER, block.id, a_recording())

    assert recorded.state is OutcomeState.COMPLETED
    assert recorded.binding == block.binding
    assert recorded.occurred_at == block.interval.start


async def test_recording_an_outcome_does_not_confirm_the_day() -> None:
    # At the write: a block marked skipped on a day the user has not answered for is a statement
    # about the block, and the day stays out of reviews and learning until they answer.
    block = a_gym_block(day=1)
    scene = wired(block)

    recorded = await scene.service.record(OWNER, block.id, a_recording(MISS_STATE))
    day = await scene.service.read_day(OWNER, TUESDAY)

    assert recorded.confirmed_at is None
    assert day.confirmed_at is None
    assert day.unconfirmed_days == 1


async def test_correcting_a_recording_after_a_confirmation_keeps_when_the_day_was_settled() -> None:
    # Correcting a past confirmation must re-derive what the log projects, and it must NOT restate
    # when the user answered for the day: a February day corrected in March is still a day settled
    # in February.
    block = a_gym_block(day=1)
    scene = wired(block)
    confirmed = await scene.service.confirm_day(OWNER, TUESDAY)

    corrected = await scene.service.record(OWNER, block.id, a_recording(MISS_STATE))

    assert confirmed.confirmed_at == NOW
    assert corrected.state is MISS_STATE
    assert corrected.confirmed_at == NOW


async def test_past_confirmation_correction_requests_only_horizon_weeks() -> None:
    block = a_gym_block(day=1)
    requests = RecordingSolveRequests()
    scene = a_service(
        plans=[a_revision(a_week(block))],
        areas=FakeAreas([AREA]),
        solve_requests=requests,
        horizon=FixedProjectionHorizon((WEEK.following(),)),
        now=NOW,
    )
    await scene.service.confirm_day(OWNER, TUESDAY)
    requests.requested.clear()

    await scene.service.record(OWNER, block.id, a_recording(MISS_STATE))

    assert requests.requested == [frozenset({WEEK.following()})]


async def test_a_partial_without_its_minutes_is_refused_and_writes_nothing() -> None:
    # The pair is the sole source of the duration-estimate signal, so a row that claims a `partial`
    # without saying by how much records that an estimate was wrong and nothing else.
    block = a_gym_block(day=1)
    scene = wired(block)

    with pytest.raises(ValidationFailed, match="duration-estimate signal"):
        await scene.service.record(OWNER, block.id, a_recording(OutcomeState.PARTIAL))

    assert (await scene.service.read_day(OWNER, TUESDAY)).behind[0].outcome is None


async def test_a_partial_with_its_minutes_is_recorded() -> None:
    block = a_gym_block(day=1)
    scene = wired(block)

    recorded = await scene.service.record(
        OWNER, block.id, a_recording(OutcomeState.PARTIAL, actual_minutes=35)
    )

    assert recorded.actual_minutes == 35


async def test_a_move_that_does_not_say_when_is_refused_and_writes_nothing() -> None:
    # The recorded interval is the signal the time-of-day fitness curve is fitted from, so a move
    # without one says only that the planned hour was wrong.
    block = a_gym_block(day=1)
    scene = wired(block)

    with pytest.raises(ValidationFailed, match="interval it really happened in"):
        await scene.service.record(OWNER, block.id, a_recording(OutcomeState.MOVED))

    assert (await scene.service.read_day(OWNER, TUESDAY)).behind[0].outcome is None


async def test_a_move_records_the_interval_it_really_happened_in() -> None:
    block = a_gym_block(day=1)
    elsewhere = between(14, 15, day=1)
    scene = wired(block)

    recorded = await scene.service.record(
        OWNER, block.id, a_recording(OutcomeState.MOVED, actual_interval=elsewhere)
    )

    assert recorded.actual_interval == elsewhere
    assert recorded.occurred_at == block.interval.start


async def test_a_move_longer_than_a_day_is_refused_and_writes_nothing() -> None:
    # The same bound and the same reason `partial`'s minutes carry: a block is placed inside one
    # week and listed on the day it begins, so a span longer than a day describes something other
    # than one block happening elsewhere. Unbounded, a `moved` outcome naming a decade attributes
    # five million minutes to its content, which once a live placement reader exists would zero a
    # task's remaining demand for every deadline and make an infeasible week read as feasible.
    block = a_gym_block(day=1)
    scene = wired(block)
    a_decade = Interval(at(9, day=1), at(9, day=1) + timedelta(days=3650))

    with pytest.raises(ValidationFailed, match="may report at most 1440"):
        await scene.service.record(
            OWNER, block.id, a_recording(OutcomeState.MOVED, actual_interval=a_decade)
        )

    assert (await scene.service.read_day(OWNER, TUESDAY)).behind[0].outcome is None


async def test_a_move_of_exactly_a_day_is_accepted() -> None:
    # The control: the bound distinguishes rather than refusing a long block. A night's sleep is the
    # longest thing a template can declare, and it fits.
    block = a_gym_block(day=1)
    scene = wired(block)
    a_whole_day = Interval(at(9, day=1), at(9, day=2))

    recorded = await scene.service.record(
        OWNER, block.id, a_recording(OutcomeState.MOVED, actual_interval=a_whole_day)
    )

    assert recorded.actual_interval == a_whole_day


async def test_a_block_the_weeks_plan_does_not_hold_is_a_404() -> None:
    scene = wired(a_gym_block(day=1))

    with pytest.raises(NotFound, match="matches that identifier"):
        await scene.service.record(OWNER, "not-a-block-of-this-week", a_recording())


async def test_a_week_with_no_plan_of_record_is_the_same_404() -> None:
    # Disclosing which of the two it is would say whether the week has been solved, which is not
    # this route's business.
    block = a_gym_block(day=1)
    scene = a_service(plans=[], areas=FakeAreas([AREA]), now=NOW)

    with pytest.raises(NotFound, match="matches that identifier"):
        await scene.service.record(OWNER, block.id, a_recording())


async def test_a_malformed_week_identifier_is_refused_before_anything_is_read() -> None:
    block = a_gym_block(day=1)
    scene = wired(block)

    with pytest.raises(ValidationFailed, match="isoWeek"):
        await scene.service.record(OWNER, block.id, a_recording(iso_week="last week"))


async def test_recording_invalidates_every_week_from_the_current_one_onwards() -> None:
    # The rotation cursor and outstanding debt feed weeks the user has not yet lived, so the range
    # is open-ended and floored at the week holding today's local date. A past week's approved
    # revision is immutable and keeps the inputs it was computed with.
    block = a_gym_block(day=1)
    scene = wired(block)

    await scene.service.record(OWNER, block.id, a_recording())

    assert [(one.first, one.last) for one in scene.versions.bumped] == [(WEEK, None)]


# --------------------------------------------------------------------------------
# The day's ledger
# --------------------------------------------------------------------------------


async def test_the_header_states_the_block_count_and_how_many_are_presumed() -> None:
    marked = a_gym_block(day=1, index=0)
    untouched = a_gym_block(day=1, index=1, hours=(11, 12))
    scene = wired(marked, untouched)
    await scene.service.record(OWNER, marked.id, a_recording())

    day = await scene.service.read_day(OWNER, TUESDAY)

    assert day.block_count == 2
    assert day.presumed_count == 1


async def test_the_rows_are_grouped_into_what_has_ended_and_what_has_not() -> None:
    ended = a_gym_block(day=2, index=0, hours=(7, 8))
    running = a_gym_block(day=2, index=1, hours=(8.5, 10))
    ahead = a_gym_block(day=2, index=2, hours=(14, 15))
    scene = wired(ended, running, ahead)

    day = await scene.service.read_day(OWNER, WEDNESDAY)

    assert [row.block_id for row in day.behind] == [ended.id]
    assert [row.block_id for row in day.ahead] == [running.id, ahead.id]


async def test_a_prep_and_a_transit_block_appear_in_the_ledger_and_can_be_confirmed() -> None:
    # They are blocks carrying an Area, not bands. A ledger that dropped them would leave the user
    # unable to say a lecture was skipped while its transit still counted.
    prep = a_prep_block(interval=between(8, 8.5, day=1))
    transit = a_transit_block(interval=between(8.5, 9, day=1))
    scene = wired(prep, transit)

    await scene.service.confirm_day(OWNER, TUESDAY)
    day = await scene.service.read_day(OWNER, TUESDAY)

    assert [row.origin for row in day.behind] == [Origin.PREP, Origin.TRANSIT]
    assert day.confirmed_at == NOW
    assert all(row.is_confirmed for row in day.behind)


async def test_a_day_the_tenants_zone_does_not_hold_is_refused_with_the_date_named() -> None:
    # Reachable rather than theoretical: Pacific/Apia skipped 30 December 2011 when it crossed the
    # date line, and any past day may be named.
    scene = a_service(plans=[], settings=FakeSettings("Pacific/Apia"), now=NOW)

    with pytest.raises(ValidationFailed, match="does not exist in Pacific/Apia"):
        await scene.service.read_day(OWNER, date(2011, 12, 30))


async def test_a_day_in_a_week_with_no_plan_reads_as_an_empty_ledger() -> None:
    # A read never triggers work, so a week the horizon maintainer has not reached has no plan.
    scene = a_service(plans=[], now=NOW)

    day = await scene.service.read_day(OWNER, TUESDAY)

    assert day.block_count == 0
    assert day.rows == ()
    assert day.confirmed_at is None


async def test_the_day_reports_its_own_span_and_the_zone_it_was_resolved_in() -> None:
    scene = wired(a_gym_block(day=1))

    day = await scene.service.read_day(OWNER, TUESDAY)

    assert day.zone == LONDON
    assert day.span == Interval(at(0, day=1), at(0, day=2))


async def test_a_day_read_across_a_travel_boundary_is_as_long_as_it_really_was() -> None:
    # Five hours east from Thursday makes Wednesday nineteen hours long, and the ledger has to read
    # the day the user had rather than a 24-hour slice.
    scene = a_service(
        plans=[a_revision(a_week())],
        overrides=FakeOverrides(
            [
                a_travel_override(
                    start_date=THURSDAY, end_date=date(2026, 2, 20), zone="Asia/Karachi"
                )
            ]
        ),
        now=NOW,
    )

    day = await scene.service.read_day(OWNER, WEDNESDAY)

    assert day.span.total_minutes() == 19 * 60


# --------------------------------------------------------------------------------
# Confirming one day
# --------------------------------------------------------------------------------


async def test_confirming_a_day_records_every_block_including_the_untouched_ones() -> None:
    # A block nobody said anything about becomes a `presumed` row on a settled day, which is what
    # turns the presumption into a fact the learner may read.
    marked = a_gym_block(day=1, index=0)
    untouched = a_gym_block(day=1, index=1, hours=(11, 12))
    scene = wired(marked, untouched)
    await scene.service.record(OWNER, marked.id, a_recording(MISS_STATE))

    day = await scene.service.confirm_day(OWNER, TUESDAY)

    assert day.confirmed_at == NOW
    assert {row.state for row in day.behind} == {MISS_STATE, OutcomeState.PRESUMED}
    assert all(row.is_confirmed for row in day.behind)


async def test_confirming_a_day_twice_keeps_the_instant_it_was_first_settled_at() -> None:
    # Three days later, over the rows the first confirmation wrote. A second service rather than a
    # reassigned clock, so the test stays on the public surface: what moves is time, and time is a
    # constructor argument here.
    block = a_gym_block(day=1)
    scene = wired(block)
    first = await scene.service.confirm_day(OWNER, TUESDAY)

    later = a_service(
        plans=[a_revision(a_week(block))],
        log=scene.log,
        areas=FakeAreas([AREA]),
        now=NOW + timedelta(days=3),
    )
    second = await later.service.confirm_day(OWNER, TUESDAY)

    assert first.confirmed_at == NOW
    assert second.confirmed_at == NOW


async def test_a_day_that_has_not_begun_cannot_be_confirmed() -> None:
    scene = wired(a_gym_block(day=3))

    with pytest.raises(ValidationFailed, match="has not begun yet"):
        await scene.service.confirm_day(OWNER, THURSDAY)


async def test_today_itself_can_be_confirmed() -> None:
    # The control for the bound above, and the evening pass the product is designed around.
    scene = wired(a_gym_block(day=2, hours=(7, 8)))

    day = await scene.service.confirm_day(OWNER, WEDNESDAY)

    assert day.confirmed_at == NOW


async def test_confirming_today_answers_for_a_block_that_has_not_ended() -> None:
    # The case the ledger's grouping rule does NOT govern, pinned deliberately rather than left to
    # be read off the code. A day is answered for as a whole, so the 20:00 block is a confirmed
    # presumption at 09:00 and the rotation cursor reads it as a completion.
    #
    # The alternative, settling only what has ended, was rejected because a day's last block
    # routinely ends on the NEXT day: a `Sleep` routine from 23:00 belongs to the day it begins in,
    # so waiting for every block to end would make today unconfirmable until tomorrow morning for
    # every user who sleeps, and the evening pass would settle nothing. An evening that turns out
    # otherwise is one recorded exception away, and the log's projection re-derives from it.
    ended = a_gym_block(day=2, index=0, hours=(7, 8))
    ahead = a_gym_block(day=2, index=1, hours=(20, 21))
    scene = wired(ended, ahead)

    day = await scene.service.confirm_day(OWNER, WEDNESDAY)

    assert day.confirmed_at == NOW
    assert [row.block_id for row in day.behind] == [ended.id]
    assert [row.block_id for row in day.ahead] == [ahead.id]
    assert all(row.is_confirmed for row in day.rows)
    assert all(row.state is OutcomeState.PRESUMED for row in day.rows)


async def test_confirming_a_day_that_holds_no_block_records_nothing() -> None:
    scene = wired(a_gym_block(day=1))

    day = await scene.service.confirm_day(OWNER, MONDAY)

    assert day.block_count == 0
    assert day.confirmed_at is None


async def test_confirming_a_day_invalidates_every_week_from_the_current_one_onwards() -> None:
    scene = wired(a_gym_block(day=1))

    await scene.service.confirm_day(OWNER, TUESDAY)

    assert [(one.first, one.last) for one in scene.versions.bumped] == [(WEEK, None)]


# --------------------------------------------------------------------------------
# Backfilling several days
# --------------------------------------------------------------------------------


async def test_a_backfill_settles_several_days_and_reports_how_many() -> None:
    # Any past day can be confirmed at any later time, and the control that offers the backfill
    # states how many it would settle.
    scene = wired(a_gym_block(day=0), a_gym_block(day=1, index=1))

    backfill = await scene.service.confirm_range(OWNER, MONDAY, WEDNESDAY)

    assert backfill.days == 2
    assert backfill.blocks == 2
    assert backfill.unconfirmed_days == 0


async def test_a_backfill_counts_only_the_days_it_actually_settled() -> None:
    # A day already confirmed and a day holding no block are both passed over, so the figure the
    # control reports is what changed rather than how many dates were named.
    monday = a_gym_block(day=0)
    tuesday = a_gym_block(day=1, index=1)
    scene = wired(monday, tuesday)
    await scene.service.confirm_day(OWNER, MONDAY)

    backfill = await scene.service.confirm_range(OWNER, MONDAY, WEDNESDAY)

    assert backfill.days == 1
    assert backfill.blocks == 1


async def test_a_backfilled_day_is_indistinguishable_from_one_settled_the_same_evening() -> None:
    # A backfilled day counts identically for maturity gates. Nothing on the row records how late
    # the answer came, so no gate can read the difference.
    monday = a_gym_block(day=0)
    tuesday = a_gym_block(day=1, index=1)
    scene = wired(monday, tuesday)

    await scene.service.confirm_day(OWNER, TUESDAY)
    await scene.service.confirm_range(OWNER, MONDAY, MONDAY)
    settled_now = (await scene.service.read_day(OWNER, TUESDAY)).behind[0]
    backfilled = (await scene.service.read_day(OWNER, MONDAY)).behind[0]

    assert settled_now.outcome is not None
    assert backfilled.outcome is not None
    assert settled_now.outcome.state == backfilled.outcome.state
    assert settled_now.outcome.confirmed_at == backfilled.outcome.confirmed_at


async def test_a_range_that_runs_backward_is_refused() -> None:
    scene = wired(a_gym_block(day=1))

    with pytest.raises(ValidationFailed, match="runs forward"):
        await scene.service.confirm_range(OWNER, WEDNESDAY, MONDAY)


async def test_a_range_of_one_day_is_the_same_date_twice() -> None:
    # The control for the rule above: it distinguishes rather than refusing a one-day range.
    scene = wired(a_gym_block(day=1))

    backfill = await scene.service.confirm_range(OWNER, TUESDAY, TUESDAY)

    assert backfill.days == 1


async def test_a_range_wider_than_the_window_the_count_reads_is_refused() -> None:
    scene = wired(a_gym_block(day=1))
    first = WEDNESDAY - timedelta(days=MAX_CONFIRM_RANGE_DAYS)

    with pytest.raises(ValidationFailed, match="at most 28 days"):
        await scene.service.confirm_range(OWNER, first, WEDNESDAY)


async def test_a_range_of_exactly_the_window_is_accepted() -> None:
    scene = wired(a_gym_block(day=1))
    first = WEDNESDAY - timedelta(days=MAX_CONFIRM_RANGE_DAYS - 1)

    backfill = await scene.service.confirm_range(OWNER, first, WEDNESDAY)

    assert backfill.days == 1


async def test_a_range_reaching_into_the_future_is_refused() -> None:
    scene = wired(a_gym_block(day=1))

    with pytest.raises(ValidationFailed, match="has not begun yet"):
        await scene.service.confirm_range(OWNER, TUESDAY, THURSDAY)


async def test_a_backfill_across_a_zone_change_settles_each_day_it_really_had() -> None:
    # The days either side of a travel boundary are different lengths, so a backfill that read a
    # 24-hour slice per date would miss a block or claim one twice.
    monday = a_gym_block(day=0)
    tuesday = a_gym_block(day=1, index=1)
    scene = a_service(
        plans=[a_revision(a_week(monday, tuesday))],
        areas=FakeAreas([AREA]),
        overrides=FakeOverrides(
            [a_travel_override(start_date=TUESDAY, end_date=date(2026, 2, 20), zone="Asia/Karachi")]
        ),
        now=NOW,
    )

    backfill = await scene.service.confirm_range(OWNER, MONDAY, WEDNESDAY)

    assert backfill.days == 2
    assert backfill.blocks == 2


async def test_the_count_of_unconfirmed_days_reads_the_days_behind_now_only() -> None:
    # Today is excluded: a day the user is still living is not one they have failed to answer for.
    scene = wired(a_gym_block(day=0), a_gym_block(day=1, index=1), a_gym_block(day=2, index=2))

    day = await scene.service.read_day(OWNER, WEDNESDAY)

    assert day.unconfirmed_days == 2


async def test_the_count_reads_exactly_the_weeks_inside_the_lookback_window() -> None:
    # The bound is on the COUNT rather than on the act, so what it costs has to be bounded too: a
    # week older than the window is never read, and one ahead of it never is either. Asserted over
    # the weeks the plan repository was asked for, because an unbounded read has no other symptom
    # than a slow request.
    scene = wired(a_gym_block(day=0), a_gym_block(day=1, index=1))

    await scene.service.read_day(OWNER, WEDNESDAY)

    assert set(scene.plans.weeks_read) == {
        IsoWeek(2026, 3),
        IsoWeek(2026, 4),
        IsoWeek(2026, 5),
        IsoWeek(2026, 6),
        WEEK,
    }
