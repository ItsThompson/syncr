"""The four product metrics, in numbers rather than directions.

Every case here asserts an exact figure. A test that a ratio "goes up" passes for a formula that is
wrong by a factor, and the whole reason the early-catch metric counts episodes is that a plausible
formula reads 0.5 where the truth is 1.0.

The arithmetic is pure, so these tests build rows rather than a database. The reads that produce
those rows are driven against Postgres in ``test_product_metrics_integration``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syncr_api.observability.churn import acceptance_ratio, changed_block_count, repin_count
from syncr_api.observability.early_catch import caught_early_over, episodes_beginning_in
from syncr_api.observability.engagement import WeekEngagement, streak_weeks
from syncr_api.observability.estimate import Measurement, median_ape_by_area
from syncr_api.plans.records import VerdictEventRecord
from syncr_api.plans.surfaces import VerdictSurface
from syncr_domain.feasibility import Provenance, ShortfallKind
from syncr_domain.identity import BindingKind, BindingRef
from syncr_domain.intervals import Interval
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from syncr_domain.identifiers import AreaId

A_TENANT = uuid4()
WEEK = IsoWeek.parse("2026-W07")
ANOTHER_WEEK = IsoWeek.parse("2026-W08")

# A period four weeks wide, and the instants inside it every row below is dated in.
PERIOD_START = datetime(2026, 2, 2, tzinfo=UTC)
PERIOD = Interval(PERIOD_START, PERIOD_START + timedelta(weeks=4))
BEFORE_THE_PERIOD = PERIOD_START - timedelta(days=3)


def a_binding() -> BindingRef:
    """One task's content identity, which is what a pin names and a re-pin counts by."""
    return BindingRef(kind=BindingKind.TASK, entity_id=uuid4(), occurrence_key="00")


def row(
    *,
    feasible: bool,
    surface: VerdictSurface,
    session_mode_active: bool = False,
    provenance: Provenance = Provenance.PROBE,
    at: datetime = PERIOD_START,
    iso_week: IsoWeek = WEEK,
) -> VerdictEventRecord:
    """One verdict transition as the table stored it."""
    return VerdictEventRecord(
        id=uuid4(),
        tenant_id=A_TENANT,
        iso_week=iso_week,
        occurred_at=at,
        provenance=provenance,
        feasible=feasible,
        largest_gap_minutes=0 if feasible else 90,
        shortfall_kinds=() if feasible else (ShortfallKind.FLOORS_EXCEED_CAPACITY,),
        surface=surface,
        session_mode_active=session_mode_active,
        input_version=1,
        caused_by_operation_id=uuid4() if provenance is Provenance.SOLVER else None,
    )


def caught_in_session(
    *, at: datetime = PERIOD_START, iso_week: IsoWeek = WEEK
) -> VerdictEventRecord:
    """The discovery: a pin's probe finds a gap while the weekly session is open."""
    return row(
        feasible=False,
        surface=VerdictSurface.PIN,
        session_mode_active=True,
        provenance=Provenance.PROBE,
        at=at,
        iso_week=iso_week,
    )


def confirmed_by_a_solve(
    *, at: datetime = PERIOD_START + timedelta(seconds=2), iso_week: IsoWeek = WEEK
) -> VerdictEventRecord:
    """The provenance-only row: the debounced solve confirms the same gap, session unknown to it."""
    return row(
        feasible=False,
        surface=VerdictSurface.SOLVE,
        session_mode_active=False,
        provenance=Provenance.SOLVER,
        at=at,
        iso_week=iso_week,
    )


def found_mid_week(
    *, at: datetime = PERIOD_START + timedelta(days=3), iso_week: IsoWeek = WEEK
) -> VerdictEventRecord:
    """A discovery nothing but the clock caused: the maintainer's periodic probe."""
    return row(
        feasible=False,
        surface=VerdictSurface.MAINTAINER,
        session_mode_active=False,
        provenance=Provenance.PROBE,
        at=at,
        iso_week=iso_week,
    )


def resolved(
    *, at: datetime = PERIOD_START + timedelta(days=1), iso_week: IsoWeek = WEEK
) -> VerdictEventRecord:
    """The week reported able to hold its commitments again, which closes an episode."""
    return row(
        feasible=True,
        surface=VerdictSurface.SOLVE,
        provenance=Provenance.SOLVER,
        at=at,
        iso_week=iso_week,
    )


class TestTheEarlyCatchRatioInNumbers:
    """Exact figures, because the row-counting formula reads 0.5 where the truth is 1.0.

    A comment in ``early_catch`` records why a row cannot be the unit: one infeasibility
    deliberately emits two to three rows, so a row-counting formula tops out near 0.5 under PERFECT
    behaviour against an 80% target.
    """

    def test_one_session_catch_confirmed_by_a_solve_is_exactly_one(self) -> None:
        """Two rows, one episode, and the first row is the one that decides it."""
        history = {WEEK: [caught_in_session(), confirmed_by_a_solve()]}

        assert len(episodes_beginning_in(history, period=PERIOD)) == 1
        assert caught_early_over(history, period=PERIOD) == 1.0

    def test_a_session_catch_and_a_mid_week_discovery_is_exactly_one_half(self) -> None:
        history = {
            WEEK: [caught_in_session(), resolved()],
            ANOTHER_WEEK: [found_mid_week(iso_week=ANOTHER_WEEK)],
        }

        assert len(episodes_beginning_in(history, period=PERIOD)) == 2
        assert caught_early_over(history, period=PERIOD) == 0.5

    def test_an_episode_opened_by_a_maintainer_tick_is_exactly_zero(self) -> None:
        """Denominator only, correctly: no session was open and no user action caused it."""
        history = {WEEK: [found_mid_week()]}

        assert caught_early_over(history, period=PERIOD) == 0.0

    def test_a_week_that_broke_twice_in_one_period_counts_two_episodes(self) -> None:
        """Infeasible, resolved, infeasible again is two discoveries."""
        history = {
            WEEK: [
                caught_in_session(),
                resolved(),
                found_mid_week(at=PERIOD_START + timedelta(days=2)),
            ]
        }

        assert len(episodes_beginning_in(history, period=PERIOD)) == 2
        assert caught_early_over(history, period=PERIOD) == 0.5

    def test_an_episode_still_open_at_the_period_end_counts_once(self) -> None:
        """Measured over episodes that BEGAN in the period, so a week ending infeasible is kept."""
        history = {WEEK: [caught_in_session(at=PERIOD.end - timedelta(hours=1))]}

        counted = episodes_beginning_in(history, period=PERIOD)

        assert len(counted) == 1
        assert counted[0].is_open
        assert caught_early_over(history, period=PERIOD) == 1.0

    def test_an_episode_that_began_before_the_period_is_not_counted_in_it(self) -> None:
        """It was counted in the period it began, and counting it twice would inflate a target."""
        history = {
            WEEK: [
                caught_in_session(at=BEFORE_THE_PERIOD),
                confirmed_by_a_solve(at=BEFORE_THE_PERIOD + timedelta(seconds=2)),
            ]
        }

        assert episodes_beginning_in(history, period=PERIOD) == ()
        assert caught_early_over(history, period=PERIOD) is None

    def test_a_provenance_only_row_changes_no_count(self) -> None:
        """The confirming row is diagnostic, not a discovery, so adding it moves nothing."""
        without = {WEEK: [caught_in_session()]}
        with_confirmation = {WEEK: [caught_in_session(), confirmed_by_a_solve()]}

        assert len(episodes_beginning_in(without, period=PERIOD)) == len(
            episodes_beginning_in(with_confirmation, period=PERIOD)
        )
        assert caught_early_over(without, period=PERIOD) == caught_early_over(
            with_confirmation, period=PERIOD
        )

    def test_two_provenance_only_rows_still_change_no_count(self) -> None:
        """Three rows for one infeasibility is the shape the row formula could not express."""
        history = {
            WEEK: [
                caught_in_session(),
                confirmed_by_a_solve(),
                row(
                    feasible=False,
                    surface=VerdictSurface.MAINTAINER,
                    provenance=Provenance.PROBE,
                    at=PERIOD_START + timedelta(minutes=15),
                ),
            ]
        }

        assert len(episodes_beginning_in(history, period=PERIOD)) == 1
        assert caught_early_over(history, period=PERIOD) == 1.0

    def test_a_period_with_no_episode_is_not_a_period_that_caught_none(self) -> None:
        """None rather than zero: zero is the worst score, and a quiet period is not a failure."""
        assert caught_early_over({WEEK: [resolved()]}, period=PERIOD) is None
        assert caught_early_over({}, period=PERIOD) is None

    def test_a_healthy_first_verdict_opens_no_episode(self) -> None:
        """The first verdict a mutation records for a healthy week must not read as a discovery."""
        assert episodes_beginning_in({WEEK: [resolved()]}, period=PERIOD) == ()


class TestTheEstimateAccuracyMedian:
    def test_the_error_is_a_percentage_of_the_estimate(self) -> None:
        measured = Measurement(area_id=uuid4(), estimated_minutes=60, actual_minutes=90)

        assert measured.absolute_percentage_error == 50.0

    def test_an_overrun_and_an_underrun_of_the_same_size_read_the_same(self) -> None:
        """Absolute, because an estimate 30 minutes short is as wrong as one 30 minutes long."""
        area: AreaId = uuid4()
        over = Measurement(area_id=area, estimated_minutes=60, actual_minutes=90)
        under = Measurement(area_id=area, estimated_minutes=60, actual_minutes=30)

        assert over.absolute_percentage_error == under.absolute_percentage_error == 50.0

    def test_the_median_is_the_middle_error_rather_than_the_mean(self) -> None:
        """One block estimated at 15 minutes and taking two hours must not be the whole figure."""
        area: AreaId = uuid4()
        measured = [
            Measurement(area_id=area, estimated_minutes=60, actual_minutes=60),
            Measurement(area_id=area, estimated_minutes=60, actual_minutes=66),
            Measurement(area_id=area, estimated_minutes=15, actual_minutes=120),
        ]

        assert median_ape_by_area(measured)[area] == 10.0

    def test_each_area_is_its_own_figure(self) -> None:
        first: AreaId = uuid4()
        second: AreaId = uuid4()
        measured = [
            Measurement(area_id=first, estimated_minutes=60, actual_minutes=90),
            Measurement(area_id=second, estimated_minutes=60, actual_minutes=60),
        ]

        assert median_ape_by_area(measured) == {first: 50.0, second: 0.0}

    def test_an_area_with_no_measurement_is_absent_rather_than_perfect(self) -> None:
        assert median_ape_by_area([]) == {}

    def test_a_zero_estimate_is_refused_by_the_type_that_divides_by_it(self) -> None:
        """The invariant lives on the dataclass, not one layer out in the reader that filters."""
        with pytest.raises(ValueError, match="measures nothing"):
            Measurement(area_id=uuid4(), estimated_minutes=0, actual_minutes=30)


class TestTheChurnFigures:
    def test_a_move_is_a_change_even_though_the_block_id_is_unchanged(self) -> None:
        """A block id is a digest of the week and the binding, so a move keeps it."""
        earlier = Interval(PERIOD_START, PERIOD_START + timedelta(hours=1))
        later = Interval(PERIOD_START + timedelta(hours=2), PERIOD_START + timedelta(hours=3))

        assert changed_block_count({"block": earlier}, {"block": later}) == 1

    def test_an_unchanged_plan_holds_no_changes(self) -> None:
        placed = Interval(PERIOD_START, PERIOD_START + timedelta(hours=1))

        assert changed_block_count({"block": placed}, {"block": placed}) == 0

    def test_an_added_and_a_removed_block_are_one_change_each(self) -> None:
        placed = Interval(PERIOD_START, PERIOD_START + timedelta(hours=1))

        assert changed_block_count({"gone": placed}, {"new": placed}) == 2

    def test_the_acceptance_ratio_is_accepted_over_resolved(self) -> None:
        assert acceptance_ratio(accepted=3, overridden=1) == 0.75

    def test_a_period_the_user_resolved_nothing_in_has_no_ratio(self) -> None:
        """None rather than zero, which would read as the solver proposing nothing acceptable."""
        assert acceptance_ratio(accepted=0, overridden=0) is None

    def test_only_the_second_edit_of_one_binding_in_one_week_is_a_re_pin(self) -> None:
        binding = a_binding()

        assert repin_count([(WEEK, binding)]) == 0
        assert repin_count([(WEEK, binding), (WEEK, binding)]) == 1
        assert repin_count([(WEEK, binding), (WEEK, binding), (WEEK, binding)]) == 2

    def test_the_same_binding_in_two_weeks_is_two_first_pins(self) -> None:
        """A pin binds one week and does not carry forward, so next week's pin corrects nothing."""
        binding = a_binding()

        assert repin_count([(WEEK, binding), (ANOTHER_WEEK, binding)]) == 0

    def test_two_bindings_in_one_week_are_two_first_pins(self) -> None:
        """Counted by the block the user moved, so pinning two blocks is not a correction."""
        assert repin_count([(WEEK, a_binding()), (WEEK, a_binding())]) == 0


class TestTheEngagementStreak:
    def test_a_week_needs_both_halves(self) -> None:
        planned_only = WeekEngagement(ran_a_session=True, confirmed_days=0, majority_off_plan=False)
        confirmed_only = WeekEngagement(
            ran_a_session=False, confirmed_days=7, majority_off_plan=False
        )

        assert streak_weeks([planned_only]) == 0
        assert streak_weeks([confirmed_only]) == 0

    def test_five_confirmed_days_is_enough_and_four_is_not(self) -> None:
        def week(confirmed_days: int) -> WeekEngagement:
            return WeekEngagement(
                ran_a_session=True, confirmed_days=confirmed_days, majority_off_plan=False
            )

        assert streak_weeks([week(5)]) == 1
        assert streak_weeks([week(4)]) == 0

    def test_consecutive_engaged_weeks_count(self) -> None:
        engaged = WeekEngagement(ran_a_session=True, confirmed_days=6, majority_off_plan=False)

        assert streak_weeks([engaged, engaged, engaged]) == 3

    def test_a_majority_off_plan_week_is_skipped_rather_than_a_failure(self) -> None:
        """Without the skip, the metric would punish the feature that lets the user stop."""
        engaged = WeekEngagement(ran_a_session=True, confirmed_days=6, majority_off_plan=False)
        away = WeekEngagement(ran_a_session=False, confirmed_days=0, majority_off_plan=True)

        assert streak_weeks([engaged, away, engaged]) == 2

    def test_a_skipped_week_adds_nothing_of_its_own(self) -> None:
        away = WeekEngagement(ran_a_session=False, confirmed_days=0, majority_off_plan=True)

        assert streak_weeks([away, away]) == 0

    def test_the_walk_stops_at_the_first_week_that_is_neither(self) -> None:
        engaged = WeekEngagement(ran_a_session=True, confirmed_days=6, majority_off_plan=False)
        lapsed = WeekEngagement(ran_a_session=False, confirmed_days=1, majority_off_plan=False)

        assert streak_weeks([engaged, lapsed, engaged, engaged]) == 1


def test_the_row_counting_formula_would_have_disagreed() -> None:
    """The failure the episode unit exists to prevent, measured rather than described.

    Counting rows gives 0.5 for a perfectly caught infeasibility, which against an 80% target would
    ship a metric reading as failure while the product worked correctly. Both halves are asserted
    together, so the test SEPARATES the two formulas: replacing the production grouping with row
    counting fails the first assertion, and the second is what says the two disagree.
    """
    rows = [caught_in_session(), confirmed_by_a_solve()]

    by_rows = sum(one.session_mode_active for one in rows) / len(rows)

    assert caught_early_over({WEEK: rows}, period=PERIOD) == 1.0
    assert by_rows == 0.5


def test_the_two_formulas_agree_on_a_mid_week_discovery() -> None:
    """Stated separately because it does NOT discriminate: the row formula also reads 0.0 here.

    Kept because it is the denominator-only case, and asserting it beside the discriminating one is
    what shows the episode unit changes only the readings it should.
    """
    rows = [found_mid_week()]

    by_rows = sum(one.session_mode_active for one in rows) / len(rows)

    assert caught_early_over({WEEK: rows}, period=PERIOD) == 0.0
    assert by_rows == 0.0
