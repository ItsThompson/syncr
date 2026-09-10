"""The pie review's readings: what a confirmed day gives, and what the assembled review says.

These are the rules the routes rest on, asserted over hand-built weeks so every boundary is
reachable without a plan document in a database. The route suite proves the wire shape and the two
writes; this proves the arithmetic and the classification.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from syncr_api.plans.records import BlockOutcomeRecord
from syncr_api.reviews.coverage import (
    ReviewedDay,
    claimed,
    confirmed_coverage,
    day_counts,
    is_covered_by,
)
from syncr_api.reviews.figures import (
    actual_minutes,
    oversubscription,
    targets,
    vacancy_minutes,
    vacancy_share,
    vacancy_target,
)
from syncr_api.reviews.history import ReviewedWeek, ReviewHistoryReader
from syncr_api.reviews.proposals import proposal_over
from syncr_api.reviews.readings import budget_review_reading, categories_of
from syncr_api.reviews.statements import (
    NO_CONFIRMED_DAY,
    NO_CONFIRMED_DAY_IN_THE_QUARTER,
    NO_PLAN_OF_RECORD,
    basis_statement,
    confirmed_day_statement,
    denominator_statement,
    proposal_statement,
    quarter_statement,
)
from syncr_domain.budget_review import QUARTER_WEEKS, ProposalBasis
from syncr_domain.budgets import AreaShare
from syncr_domain.habits import BindingSource
from syncr_domain.identity import BindingRef
from syncr_domain.intervals import Interval, IntervalSet
from syncr_domain.outcomes import OutcomeState
from syncr_domain.reasons import Bound, ReasonRecord
from syncr_domain.weeks import IsoWeek
from syncr_domain.zones import ZoneProfile

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syncr_domain.identifiers import AreaId
    from syncr_domain.plan import Block
    from syncr_domain.zones import Date

A_REASON = ReasonRecord((Bound(BindingSource.ROTATION, "Gym · rotation"),))
WEEK = IsoWeek(2026, 7)
MONDAY = WEEK.monday()
CONFIRMED_AT = datetime(2026, 2, 16, 21, 0, tzinfo=UTC)
MINUTES_PER_HOUR = 60


def an_instant(on: Date, hour: int) -> datetime:
    return datetime.combine(on, time(hour), tzinfo=UTC)


def a_block(
    *, on: Date, hour: int, hours: int = 1, area_id: AreaId | None, index: int = 0
) -> Block:
    from syncr_domain.plan import Block

    return Block(
        iso_week=IsoWeek.containing(on),
        interval=Interval(an_instant(on, hour), an_instant(on, hour + hours)),
        binding=BindingRef.for_habit(uuid4(), index=index),
        title="Gym",
        reason=A_REASON,
        area_id=area_id,
    )


def a_frame_block(*, on: Date, hour: int, hours: int = 1) -> Block:
    """A routine's block, which carries no Area: the frame defines how much time exists."""
    from syncr_domain.plan import Block

    return Block(
        iso_week=IsoWeek.containing(on),
        interval=Interval(an_instant(on, hour), an_instant(on, hour) + timedelta(hours=hours)),
        binding=BindingRef.for_routine(uuid4(), on=on),
        title="Sleep",
        reason=A_REASON,
        area_id=None,
    )


def a_day(
    *,
    on: Date,
    blocks: Sequence[Block] = (),
    confirmed: bool = True,
    off_plan: bool = False,
) -> ReviewedDay:
    return ReviewedDay(
        on=on,
        span=Interval(an_instant(on, 0), an_instant(on + timedelta(days=1), 0)),
        blocks=tuple(blocks),
        confirmed_at=CONFIRMED_AT if confirmed else None,
        is_off_plan=off_plan,
    )


def an_outcome(
    block: Block,
    state: OutcomeState,
    *,
    actual_minutes: int | None = None,
    actual_interval: Interval | None = None,
) -> BlockOutcomeRecord:
    return BlockOutcomeRecord(
        id=uuid4(),
        tenant_id=uuid4(),
        block_id=block.id,
        binding=block.binding,
        revision_id=uuid4(),
        state=state,
        actual_minutes=actual_minutes,
        actual_interval=actual_interval,
        occurred_at=block.interval.start,
        confirmed_at=CONFIRMED_AT,
    )


def a_week(
    *,
    iso_week: IsoWeek = WEEK,
    days: Sequence[ReviewedDay] = (),
    discretionary_minutes: int | None = 10080,
    off_plan: IntervalSet | None = None,
    outcomes: Mapping[str, BlockOutcomeRecord] | None = None,
    discretionary: IntervalSet | None = None,
) -> ReviewedWeek:
    span = Interval(an_instant(iso_week.monday(), 0), an_instant(iso_week.following().monday(), 0))
    inside = IntervalSet() if off_plan is None else off_plan.clip(span)
    review_discretionary = discretionary
    if review_discretionary is None:
        review_discretionary = (
            IntervalSet()
            if discretionary_minutes is None
            else (
                IntervalSet()
                if discretionary_minutes == 0
                else IntervalSet(
                    [Interval(span.start, span.start + timedelta(minutes=discretionary_minutes))]
                )
            )
        )
    return ReviewedWeek(
        iso_week=iso_week,
        span=span,
        discretionary_minutes=discretionary_minutes,
        discretionary=review_discretionary,
        days=tuple(days),
        off_plan=inside,
        covered=confirmed_coverage(
            days,
            outcomes=outcomes or {},
            within=span,
            off_plan=inside,
            discretionary=review_discretionary,
        ),
        outcomes=outcomes or {},
    )


def a_share(
    *, percent: str = "0", floor_minutes: int = 0, parent: AreaId | None = None
) -> AreaShare:
    return AreaShare(
        area_id=uuid4(),
        parent_id=parent,
        floor_minutes=floor_minutes,
        budget_percent=Decimal(percent),
    )


class TestWhatAConfirmedDayGives:
    """The numerator: confirmed days only, off-plan excluded, through the attribution table."""

    def test_a_confirmed_block_gives_its_planned_span(self) -> None:
        share = a_share()
        block = a_block(on=MONDAY, hour=9, area_id=share.area_id)
        week = a_week(days=[a_day(on=MONDAY, blocks=[block])])

        assert actual_minutes(week, share.area_id) == MINUTES_PER_HOUR

    def test_an_unconfirmed_day_gives_nothing(self) -> None:
        """Only confirmed days contribute to the actual figure."""
        share = a_share()
        block = a_block(on=MONDAY, hour=9, area_id=share.area_id)
        week = a_week(days=[a_day(on=MONDAY, blocks=[block], confirmed=False)])

        assert actual_minutes(week, share.area_id) == 0

    def test_a_skipped_block_gives_nothing_on_a_confirmed_day(self) -> None:
        share = a_share()
        block = a_block(on=MONDAY, hour=9, area_id=share.area_id)
        week = a_week(
            days=[a_day(on=MONDAY, blocks=[block])],
            outcomes={str(block.id): an_outcome(block, OutcomeState.SKIPPED)},
        )

        assert actual_minutes(week, share.area_id) == 0

    def test_a_partial_block_gives_the_minutes_it_reported(self) -> None:
        share = a_share()
        block = a_block(on=MONDAY, hour=9, area_id=share.area_id)
        week = a_week(
            days=[a_day(on=MONDAY, blocks=[block])],
            outcomes={str(block.id): an_outcome(block, OutcomeState.PARTIAL, actual_minutes=20)},
        )

        assert actual_minutes(week, share.area_id) == 20

    def test_a_moved_block_gives_the_interval_it_happened_in(self) -> None:
        share = a_share()
        block = a_block(on=MONDAY, hour=9, area_id=share.area_id)
        moved = Interval(an_instant(MONDAY, 14), an_instant(MONDAY, 17))
        week = a_week(
            days=[a_day(on=MONDAY, blocks=[block])],
            outcomes={str(block.id): an_outcome(block, OutcomeState.MOVED, actual_interval=moved)},
        )

        assert actual_minutes(week, share.area_id) == 3 * MINUTES_PER_HOUR

    def test_a_block_carrying_no_area_gives_nothing_to_anybody(self) -> None:
        """The frame and an anchor carry no Area, so neither claims discretionary time."""
        week = a_week(days=[a_day(on=MONDAY, blocks=[a_frame_block(on=MONDAY, hour=23, hours=8)])])

        assert week.covered == {}

    def test_an_off_plan_span_is_excluded_entirely(self) -> None:
        share = a_share()
        block = a_block(on=MONDAY, hour=9, area_id=share.area_id)
        away = IntervalSet([Interval(an_instant(MONDAY, 8), an_instant(MONDAY, 12))])
        week = a_week(days=[a_day(on=MONDAY, blocks=[block])], off_plan=away)

        assert actual_minutes(week, share.area_id) == 0

    def test_a_block_half_inside_an_off_plan_span_gives_only_its_other_half(self) -> None:
        share = a_share()
        block = a_block(on=MONDAY, hour=9, hours=2, area_id=share.area_id)
        away = IntervalSet([Interval(an_instant(MONDAY, 10), an_instant(MONDAY, 12))])
        week = a_week(days=[a_day(on=MONDAY, blocks=[block])], off_plan=away)

        assert actual_minutes(week, share.area_id) == MINUTES_PER_HOUR

    def test_two_areas_claiming_one_minute_claim_it_once_in_the_union(self) -> None:
        first, second = a_share(), a_share()
        span = Interval(an_instant(MONDAY, 9), an_instant(MONDAY, 10))
        covered = {first.area_id: IntervalSet([span]), second.area_id: IntervalSet([span])}

        assert claimed(covered).total_minutes() == MINUTES_PER_HOUR

    def test_an_area_with_no_block_is_absent_from_the_coverage_and_reads_as_zero(self) -> None:
        share = a_share()
        week = a_week(days=[a_day(on=MONDAY)])

        assert share.area_id not in week.covered
        assert actual_minutes(week, share.area_id) == 0


class TestHowADayIsClassified:
    """Off-plan outranks unconfirmed, and a day holding nothing is neither."""

    def test_a_day_whose_every_block_is_confirmed_is_confirmed(self) -> None:
        day = a_day(on=MONDAY, blocks=[a_block(on=MONDAY, hour=9, area_id=uuid4())])

        assert day.is_confirmed
        assert not day.is_unconfirmed

    def test_a_day_holding_blocks_and_no_confirmation_is_unconfirmed(self) -> None:
        day = a_day(
            on=MONDAY, blocks=[a_block(on=MONDAY, hour=9, area_id=uuid4())], confirmed=False
        )

        assert day.is_unconfirmed
        assert not day.is_confirmed

    def test_a_day_holding_no_block_is_neither(self) -> None:
        """Counting it would report a backlog of days on which nothing was planned.

        Asserted with a confirmation instant ON the day, which is the state a caller could build by
        hand: the rule is a property of this shape rather than of what ``settled_at`` happens to
        answer over an empty run of blocks.
        """
        for day in [a_day(on=MONDAY, confirmed=False), a_day(on=MONDAY, confirmed=True)]:
            assert not day.is_confirmed
            assert not day.is_unconfirmed
            assert day_counts([day]).confirmed == 0
            assert day_counts([day]).unconfirmed == 0

    def test_an_off_plan_day_is_reported_separately_and_never_as_unconfirmed(self) -> None:
        """A day the user declared away is not a day they failed to answer for."""
        day = a_day(
            on=MONDAY,
            blocks=[a_block(on=MONDAY, hour=9, area_id=uuid4())],
            confirmed=False,
            off_plan=True,
        )
        counted = day_counts([day])

        assert counted.off_plan == 1
        assert counted.unconfirmed == 0
        assert counted.confirmed == 0

    def test_an_off_plan_day_that_was_confirmed_is_still_reported_as_off_plan(self) -> None:
        day = a_day(on=MONDAY, blocks=[a_block(on=MONDAY, hour=9, area_id=uuid4())], off_plan=True)
        counted = day_counts([day])

        assert counted.off_plan == 1
        assert counted.confirmed == 0

    def test_the_three_counts_are_summed_across_a_period(self) -> None:
        block = a_block(on=MONDAY, hour=9, area_id=uuid4())
        counted = day_counts(
            [
                a_day(on=MONDAY, blocks=[block]),
                a_day(on=MONDAY + timedelta(days=1), blocks=[block], confirmed=False),
                a_day(on=MONDAY + timedelta(days=2), off_plan=True),
                a_day(on=MONDAY + timedelta(days=3)),
            ]
        )

        assert (counted.confirmed, counted.unconfirmed, counted.off_plan) == (1, 1, 1)

    def test_coverage_is_emptiness_of_the_residual_rather_than_a_minute_comparison(self) -> None:
        """Both counts truncate a sub-minute remainder, and they truncate independently."""
        span = Interval(
            datetime(2026, 2, 16, 0, 0, 30, tzinfo=UTC), datetime(2026, 2, 17, 0, 0, tzinfo=UTC)
        )
        almost = IntervalSet([Interval(span.start, span.end - timedelta(seconds=30))])

        assert not is_covered_by(span, almost)
        assert is_covered_by(span, IntervalSet([span]))


class TestTheDenominatorAndTheTargets:
    """The plan of record's own figure, and what a week with no plan reports instead."""

    async def test_a_week_with_no_plan_keeps_an_empty_discretionary_set(self) -> None:
        plans = MagicMock()
        plans.latest = AsyncMock(return_value=None)
        outcomes = MagicMock()
        outcomes.for_span = AsyncMock(return_value=[])
        periods = MagicMock()
        periods.for_span = AsyncMock(return_value=[])
        history = ReviewHistoryReader(plans, outcomes, periods)

        (week,) = await history.read([WEEK], ZoneProfile("UTC"))

        assert week.discretionary == IntervalSet()
        plans.latest.assert_awaited_once_with(WEEK)

    def test_the_denominator_is_the_documents_own_stored_figure(self) -> None:
        """A week that sleeps for 56 hours has 112 discretionary, not its whole 168-hour span."""
        week = a_week(discretionary_minutes=6720)

        assert week.discretionary_minutes == 6720
        assert week.span.total_minutes() == 10080

    def test_a_week_with_no_plan_of_record_reports_no_denominator_at_all(self) -> None:
        week = a_week(discretionary_minutes=None)

        assert vacancy_minutes(week) is None
        assert targets(week, [a_share(percent="30")]) == {}
        assert oversubscription(week, [a_share(percent="30")]) is None
        assert denominator_statement(week.discretionary_minutes) == NO_PLAN_OF_RECORD

    def test_a_planned_week_states_nothing_about_its_denominator(self) -> None:
        assert denominator_statement(6720) is None

    def test_a_target_is_a_floor_plus_a_share_of_what_the_floors_leave(self) -> None:
        floored = a_share(percent="0", floor_minutes=300)
        shared = a_share(percent="50")
        week = a_week(discretionary_minutes=1300)

        declared = targets(week, [floored, shared])

        assert declared[floored.area_id] == 300
        assert declared[shared.area_id] == 500

    def test_an_area_declaring_nothing_has_a_zero_target_rather_than_an_absent_one(self) -> None:
        share = a_share()
        week = a_week(discretionary_minutes=6720)

        assert targets(week, [share]) == {share.area_id: 0}


class TestTheVacancyAndOversubscription:
    """Two quantities that are routinely confused, reported separately and never as each other."""

    def test_shares_summing_to_a_hundred_do_not_make_the_vacancy_zero(self) -> None:
        """Shares summing to a hundred, and the defect the residual formula had."""
        shares = [a_share(percent="60"), a_share(percent="40")]
        block = a_block(on=MONDAY, hour=9, area_id=shares[0].area_id)
        week = a_week(discretionary_minutes=6720, days=[a_day(on=MONDAY, blocks=[block])])

        assert sum(share.budget_percent for share in shares) == Decimal(100)
        assert vacancy_minutes(week) == 6720 - MINUTES_PER_HOUR
        assert oversubscription(week, shares) == 0

    def test_shares_summing_past_a_hundred_leave_the_vacancy_non_negative(self) -> None:
        shares = [a_share(percent="100"), a_share(percent="30")]
        week = a_week(discretionary_minutes=6720)

        assert vacancy_minutes(week) == 6720
        assert oversubscription(week, shares) == 2016

    def test_oversubscription_is_its_own_quantity_rather_than_a_negative_vacancy(self) -> None:
        shares = [a_share(percent="100"), a_share(percent="30")]
        week = a_week(discretionary_minutes=6720)
        reading = budget_review_reading([week], shares=shares)

        assert reading.unallocated_minutes is not None
        assert reading.unallocated_minutes >= 0
        assert reading.oversubscription_minutes == 2016

    def test_the_vacancys_target_is_what_the_areas_own_targets_leave(self) -> None:
        shares = [a_share(percent="25")]
        week = a_week(discretionary_minutes=1000)

        assert vacancy_target(week, targets(week, shares)) == 750

    def test_the_vacancys_target_is_none_rather_than_negative_when_oversubscribed(self) -> None:
        shares = [a_share(percent="130")]
        week = a_week(discretionary_minutes=1000)

        assert vacancy_target(week, targets(week, shares)) == 0

    def test_the_vacancys_share_is_what_the_areas_have_not_claimed(self) -> None:
        assert vacancy_share([a_share(percent="30"), a_share(percent="20")]) == Decimal(50)

    def test_the_vacancys_share_is_zero_rather_than_negative_when_oversubscribed(self) -> None:
        assert vacancy_share([a_share(percent="130")]) == Decimal(0)

    def test_the_vacancy_holds_the_whole_denominator_when_nothing_was_confirmed(self) -> None:
        week = a_week(discretionary_minutes=6720, days=[a_day(on=MONDAY, confirmed=False)])

        assert vacancy_minutes(week) == 6720

    def test_a_moved_outcome_inside_the_frame_leaves_the_pie_tiling_the_denominator(self) -> None:
        frame = Interval(an_instant(MONDAY, 0), an_instant(MONDAY, 7))
        discretionary = IntervalSet(
            [Interval(an_instant(MONDAY, 0), an_instant(WEEK.following().monday(), 0))]
        ).subtract(IntervalSet([frame]))
        share = a_share(percent="100")
        block = a_block(on=MONDAY, hour=9, area_id=share.area_id)
        moved = Interval(an_instant(MONDAY, 0), an_instant(MONDAY, 0) + timedelta(minutes=7000))
        week = a_week(
            discretionary_minutes=discretionary.total_minutes(),
            discretionary=discretionary,
            days=[a_day(on=MONDAY, blocks=[block])],
            outcomes={str(block.id): an_outcome(block, OutcomeState.MOVED, actual_interval=moved)},
        )

        rows = categories_of(week, shares=[share])

        assert sum(row.actual_minutes for row in rows) == week.discretionary_minutes


class TestTheCategories:
    """One row per Area, then the vacancy, which is the order the wedges are drawn in."""

    def test_the_vacancy_is_the_last_row_and_carries_no_area(self) -> None:
        shares = [a_share(percent="30"), a_share(percent="20")]
        rows = categories_of(a_week(), shares=shares)

        assert [row.area_id for row in rows] == [shares[0].area_id, shares[1].area_id, None]

    def test_no_areas_still_leaves_the_vacancy(self) -> None:
        """A tenant who has declared nothing: the whole denominator is the vacancy."""
        rows = categories_of(a_week(discretionary_minutes=6720), shares=[])

        assert len(rows) == 1
        assert rows[0].area_id is None
        assert rows[0].actual_minutes == 6720

    def test_one_area_and_the_vacancy_tile_the_denominator(self) -> None:
        share = a_share(percent="100")
        block = a_block(on=MONDAY, hour=9, hours=2, area_id=share.area_id)
        week = a_week(discretionary_minutes=600, days=[a_day(on=MONDAY, blocks=[block])])

        rows = categories_of(week, shares=[share])

        assert sum(row.actual_minutes for row in rows) == 600

    @pytest.mark.parametrize("count", [1, 12, 13])
    def test_every_declared_area_takes_a_row_however_many_there_are(self, count: int) -> None:
        """Past twelve the ramp repeats. The review still reports each Area on its own row."""
        shares = [a_share(percent="1") for _ in range(count)]
        rows = categories_of(a_week(), shares=shares)

        assert len(rows) == count + 1

    def test_a_child_area_takes_its_own_row_beside_its_parent(self) -> None:
        parent = a_share(percent="30")
        child = a_share(percent="10", parent=parent.area_id)
        rows = categories_of(a_week(), shares=[parent, child])

        assert [row.area_id for row in rows] == [parent.area_id, child.area_id, None]

    def test_a_week_with_no_plan_leaves_every_target_absent_and_every_actual_zero(self) -> None:
        share = a_share(percent="30")
        rows = categories_of(a_week(discretionary_minutes=None), shares=[share])

        assert [row.target_minutes for row in rows] == [None, None]
        assert [row.actual_minutes for row in rows] == [0, 0]


class TestWhatAWeekIsEvidenceFor:
    """A partly confirmed week is reported and is not evidence."""

    def test_a_week_whose_every_planned_day_is_confirmed_is_evidence(self) -> None:
        block = a_block(on=MONDAY, hour=9, area_id=uuid4())
        week = a_week(days=[a_day(on=MONDAY, blocks=[block]), a_day(on=MONDAY + timedelta(days=1))])

        assert week.is_fully_confirmed

    def test_a_week_with_one_unanswered_day_is_not_evidence(self) -> None:
        block = a_block(on=MONDAY, hour=9, area_id=uuid4())
        week = a_week(
            days=[
                a_day(on=MONDAY, blocks=[block]),
                a_day(on=MONDAY + timedelta(days=1), blocks=[block], confirmed=False),
            ]
        )

        assert not week.is_fully_confirmed

    def test_a_week_holding_nothing_is_not_evidence(self) -> None:
        """Otherwise a tenant who planned nothing for a quarter would have a quarter's evidence."""
        week = a_week(days=[a_day(on=MONDAY)])

        assert not week.is_fully_confirmed

    def test_a_week_that_was_entirely_off_plan_is_not_evidence(self) -> None:
        week = a_week(days=[a_day(on=MONDAY, off_plan=True)])

        assert not week.is_fully_confirmed


class TestTheProposal:
    """Nothing until a quarter of fully confirmed weeks exists, and the count says why."""

    def a_confirmed_quarter(self, share: AreaShare, *, weeks: int) -> list[ReviewedWeek]:
        """``weeks`` fully confirmed weeks, each giving ``share`` one hour of its 600 minutes."""
        built = []
        for offset in range(weeks):
            iso_week = IsoWeek.containing(MONDAY - timedelta(weeks=weeks - offset))
            on = iso_week.monday()
            block = a_block(on=on, hour=9, area_id=share.area_id)
            built.append(
                a_week(
                    iso_week=iso_week,
                    discretionary_minutes=600,
                    days=[a_day(on=on, blocks=[block])],
                )
            )
        return built

    def test_below_the_quarter_there_is_no_proposal_and_the_count_says_so(self) -> None:
        share = a_share(percent="30")
        reading = proposal_over(self.a_confirmed_quarter(share, weeks=3), shares=[share])

        assert reading.shares == ()
        assert reading.confirmed_weeks == 3
        assert reading.required_weeks == QUARTER_WEEKS
        assert not reading.is_proposed

    def test_a_quarter_of_confirmed_weeks_proposes_a_share_per_category(self) -> None:
        share = a_share(percent="30")
        reading = proposal_over(
            self.a_confirmed_quarter(share, weeks=QUARTER_WEEKS), shares=[share]
        )

        assert reading.is_proposed
        assert [one.area_id for one in reading.shares] == [share.area_id, None]

    def test_the_observed_share_is_one_ratio_over_the_whole_quarter(self) -> None:
        """60 minutes of each week's 600, which is 10% however many weeks there are."""
        share = a_share(percent="30")
        reading = proposal_over(
            self.a_confirmed_quarter(share, weeks=QUARTER_WEEKS), shares=[share]
        )

        assert reading.shares[0].observed_percent == Decimal("10.0")
        assert reading.shares[0].proposed_percent == Decimal(20)
        assert reading.shares[1].observed_percent == Decimal("90.0")

    def test_a_target_missed_in_every_confirmed_week_reads_as_never_met(self) -> None:
        share = a_share(percent="30")
        reading = proposal_over(
            self.a_confirmed_quarter(share, weeks=QUARTER_WEEKS), shares=[share]
        )

        assert reading.shares[0].basis is ProposalBasis.NEVER_MET

    def test_an_area_declaring_a_floor_is_proposed_unchanged(self) -> None:
        share = a_share(percent="30", floor_minutes=300)
        reading = proposal_over(
            self.a_confirmed_quarter(share, weeks=QUARTER_WEEKS), shares=[share]
        )

        assert reading.shares[0].basis is ProposalBasis.FLOOR_HOLDS_IT
        assert reading.shares[0].proposed_percent == Decimal(30)

    def test_a_partly_confirmed_week_does_not_count_toward_the_quarter(self) -> None:
        share = a_share(percent="30")
        quarter = self.a_confirmed_quarter(share, weeks=QUARTER_WEEKS)
        spoiled = quarter[0]
        tuesday = spoiled.iso_week.monday() + timedelta(days=1)
        quarter[0] = a_week(
            iso_week=spoiled.iso_week,
            discretionary_minutes=600,
            days=[
                *spoiled.days,
                a_day(
                    on=tuesday,
                    blocks=[a_block(on=tuesday, hour=9, area_id=share.area_id)],
                    confirmed=False,
                ),
            ],
        )
        reading = proposal_over(quarter, shares=[share])

        assert reading.confirmed_weeks == QUARTER_WEEKS - 1
        assert reading.shares == ()


class TestTheStatements:
    """Non-null exactly when they say something the figures do not."""

    def test_a_period_with_no_confirmed_day_says_so_rather_than_drawing_empty_charts(self) -> None:
        assert confirmed_day_statement(0) == NO_CONFIRMED_DAY
        assert confirmed_day_statement(1) is None

    def test_a_quarter_with_no_confirmed_day_says_so_in_its_own_words(self) -> None:
        assert quarter_statement(0) == NO_CONFIRMED_DAY_IN_THE_QUARTER
        assert quarter_statement(1) is None

    def test_every_basis_has_a_sentence(self) -> None:
        assert {basis_statement(basis) for basis in ProposalBasis} == {
            basis_statement(basis) for basis in ProposalBasis
        }
        assert all(basis_statement(basis) for basis in ProposalBasis)

    def test_below_the_quarter_the_proposal_states_what_is_missing_and_what_is_shown(self) -> None:
        stated = proposal_statement(confirmed_weeks=3, required_weeks=QUARTER_WEEKS)

        assert "13" in stated
        assert "3 exist" in stated
        assert "gap between actual and target only" in stated

    def test_one_confirmed_week_is_stated_in_the_singular(self) -> None:
        assert "1 exists" in proposal_statement(confirmed_weeks=1, required_weeks=QUARTER_WEEKS)

    def test_at_the_quarter_the_proposal_states_what_it_rests_on_and_who_decides(self) -> None:
        stated = proposal_statement(confirmed_weeks=13, required_weeks=QUARTER_WEEKS)

        assert "13 fully confirmed weeks" in stated
        assert "never re-cuts the budget on its own" in stated


class TestTheAssembledReview:
    """The named week is the last of the quarter, and the trend is every week of it."""

    def test_the_review_is_anchored_at_the_last_week_of_the_quarter(self) -> None:
        earlier = a_week(iso_week=IsoWeek(2026, 6))
        named = a_week(iso_week=IsoWeek(2026, 7))
        reading = budget_review_reading([earlier, named], shares=[])

        assert reading.period == IsoWeek(2026, 7)
        assert [week.iso_week for week in reading.trend] == [IsoWeek(2026, 6), IsoWeek(2026, 7)]

    def test_the_quarters_day_counts_are_its_weeks_own_summed(self) -> None:
        block = a_block(on=MONDAY, hour=9, area_id=uuid4())
        earlier = a_week(iso_week=IsoWeek(2026, 6), days=[a_day(on=IsoWeek(2026, 6).monday())])
        named = a_week(iso_week=WEEK, days=[a_day(on=MONDAY, blocks=[block])])
        reading = budget_review_reading([earlier, named], shares=[])

        assert reading.days.confirmed == 1
        assert reading.quarter_days.confirmed == 1

    def test_a_week_off_plan_from_end_to_end_carries_the_statement_that_explains_it(self) -> None:
        span = Interval(an_instant(MONDAY, 0), an_instant(WEEK.following().monday(), 0))
        week = a_week(discretionary_minutes=0, off_plan=IntervalSet([span]))
        reading = budget_review_reading([week], shares=[])

        assert reading.off_plan.minutes == 10080
        assert reading.off_plan.statement is not None
