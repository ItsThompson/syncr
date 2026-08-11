"""The five fitters, and the corpora each of them must refuse.

The adversarial cases are the point of this file: an empty corpus, a corpus of one, a corpus where
every row is identical, a metric that is undefined on the data, and a corpus constructed to be
unfittable. Each is a shape a nightly job over real data will meet, and each has to produce a stated
answer rather than a number.
"""

from __future__ import annotations

import pytest

from syncr_learning.config import (
    MAX_CHURN_TOLERANCE,
    MAX_DURATION_RATIO,
    MAX_SWITCH_COST_MINUTES,
    MIN_CHURN_TOLERANCE,
    MIN_SWITCH_COST_MINUTES,
    PRIOR_CHURN_TOLERANCE,
    PRIOR_CONTEXT_SWITCH_COST,
    PRIOR_DURATION_MULTIPLIER,
    PRIOR_FITNESS,
    PRIOR_SKIP_PROBABILITY,
    PRIOR_WEIGHT,
    THRESHOLD_CONTEXT_SWITCH_COST,
    THRESHOLD_TIME_OF_DAY_FITNESS,
    TimeBucket,
)
from syncr_learning.fitters import (
    fit_churn_tolerance,
    fit_context_switch_cost,
    fit_duration_multiplier,
    fit_skip_probability,
    fit_time_of_day_fitness,
)
from syncr_learning.fitters.duration import median_actual_minutes, median_planned_minutes
from syncr_learning.fitters.switching import gaps_across_areas
from syncr_learning.observations import (
    ChurnObservation,
    DurationObservation,
    SkipObservation,
    SwitchObservation,
    TimeOfDayObservation,
)
from syncr_learning.shrinkage import outlier_bound, shrunk
from tests.builders import AREA

BASELINE_GAP = 30


def durations(count: int, *, planned: int = 60, actual: int = 82) -> list[DurationObservation]:
    return [
        DurationObservation(area_id=AREA, planned_minutes=planned, actual_minutes=actual)
        for _ in range(count)
    ]


def spread_around_a_baseline(*, far: int, near: int = 5) -> list[SwitchObservation]:
    """Forty cross-Area pairs alternating two gaps, against a within-Area baseline between them.

    The shape a per-observation floor mishandles: half the differences are negative, so truncating
    each one keeps the positive half whole and discards the size of the negative half.
    """
    return switch_corpus(
        across=[near if index % 2 == 0 else far for index in range(40)], baseline=BASELINE_GAP
    )


def switch_corpus(*, across: list[int], baseline: int) -> list[SwitchObservation]:
    """Cross-Area pairs at the given gaps, against twenty within-Area pairs at one gap."""
    return [
        *(SwitchObservation(gap_minutes=gap, changed_area=True) for gap in across),
        *(SwitchObservation(gap_minutes=baseline, changed_area=False) for _ in range(20)),
    ]


def width(interval: tuple[float, float]) -> float:
    return interval[1] - interval[0]


class TestDurationMultiplier:
    def test_an_empty_corpus_is_the_prior_at_full_shrinkage(self) -> None:
        result = fit_duration_multiplier([])

        assert result.value == PRIOR_DURATION_MULTIPLIER
        assert result.samples == 0
        assert result.shrinkage_weight == 1.0

    def test_the_ratio_is_actual_over_planned_rather_than_the_difference(self) -> None:
        # A multiplier scales an estimate, so an Area whose 60m blocks run to 82 and one whose 30m
        # blocks run to 41 must fit the same figure. A difference would fit 22 and 11.
        long_blocks = fit_duration_multiplier(durations(20, planned=60, actual=82))
        short_blocks = fit_duration_multiplier(durations(20, planned=30, actual=41))

        assert long_blocks.value == pytest.approx(short_blocks.value)

    def test_twenty_agreeing_observations_pull_the_value_most_of_the_way(self) -> None:
        result = fit_duration_multiplier(durations(20))

        expected = (20 * (82 / 60) + PRIOR_WEIGHT * PRIOR_DURATION_MULTIPLIER) / (20 + PRIOR_WEIGHT)
        assert result.value == pytest.approx(expected)

    def test_a_three_hour_session_against_a_one_hour_plan_is_clamped(self) -> None:
        # The credibility rule, at the observation rather than at the formula. Unclamped this enters
        # as 3.0; clamped it enters at the ceiling, and the outlier bound follows from that.
        absurd = [DurationObservation(area_id=AREA, planned_minutes=60, actual_minutes=1200)]
        result = fit_duration_multiplier(absurd)

        expected = (MAX_DURATION_RATIO + PRIOR_WEIGHT * PRIOR_DURATION_MULTIPLIER) / (
            1 + PRIOR_WEIGHT
        )
        assert result.value == pytest.approx(expected)

    def test_a_corpus_where_every_row_is_identical_has_a_point_interval(self) -> None:
        # It is fittable and its uncertainty is genuinely nothing: twenty rows saying one thing have
        # no spread, and inventing one would invent the uncertainty the interval reports.
        result = fit_duration_multiplier(durations(20))

        assert result.confidence is not None
        assert result.confidence[0] == pytest.approx(result.confidence[1])

    def test_a_block_planned_for_nothing_is_refused_at_the_observation(self) -> None:
        with pytest.raises(ValueError, match="divide by nothing"):
            DurationObservation(area_id=AREA, planned_minutes=0, actual_minutes=82)

    def test_a_partial_of_no_minutes_is_a_skip_and_is_refused(self) -> None:
        with pytest.raises(ValueError, match="is a skip"):
            DurationObservation(area_id=AREA, planned_minutes=60, actual_minutes=0)

    def test_the_medians_the_statement_quotes_are_the_middle_values(self) -> None:
        mixed = [
            DurationObservation(area_id=AREA, planned_minutes=60, actual_minutes=minutes)
            for minutes in (70, 82, 95)
        ]

        assert median_actual_minutes(mixed) == 82
        assert median_planned_minutes(mixed) == 60
        assert median_actual_minutes([]) is None

    def test_an_even_count_takes_the_whole_minute_mean_of_the_middle_two(self) -> None:
        pair = [
            DurationObservation(area_id=AREA, planned_minutes=60, actual_minutes=minutes)
            for minutes in (80, 83)
        ]

        assert median_actual_minutes(pair) == 81


class TestTimeOfDayFitness:
    def test_an_empty_corpus_is_the_prior_at_every_hour(self) -> None:
        curve = fit_time_of_day_fitness([])

        assert curve.curve == (PRIOR_FITNESS,) * 24
        assert curve.distinct_hours == 0
        assert curve.covers_enough_of_the_day is False

    def test_the_prior_charges_nothing_in_the_term_that_reads_it(self) -> None:
        # The misfit term charges `1 - fitness`, so an unobserved hour has to enter at 1.0 or the
        # curve would penalise every hour the user has not yet worked in.
        assert PRIOR_FITNESS == 1.0

    def test_an_hour_the_user_always_skips_is_fitted_below_an_hour_they_always_finish(self) -> None:
        observed = [
            *(TimeOfDayObservation(area_id=AREA, hour=6, went_well=False) for _ in range(20)),
            *(TimeOfDayObservation(area_id=AREA, hour=18, went_well=True) for _ in range(20)),
        ]
        curve = fit_time_of_day_fitness(observed)

        assert curve.curve[6] < curve.curve[18]
        assert curve.worst_hour == 6
        assert curve.distinct_hours == 2

    def test_thirty_observations_at_one_hour_do_not_cover_enough_of_the_day(self) -> None:
        # The gate that a total-only count would pass. Twenty-three hours would sit at the prior
        # while the curve claimed to be fitted, which is a metric undefined on the data it read.
        crowded = [
            TimeOfDayObservation(area_id=AREA, hour=7, went_well=True)
            for _ in range(THRESHOLD_TIME_OF_DAY_FITNESS)
        ]
        curve = fit_time_of_day_fitness(crowded)

        assert curve.result.samples == THRESHOLD_TIME_OF_DAY_FITNESS
        assert curve.covers_enough_of_the_day is False

    def test_the_same_count_spread_across_the_day_does_cover_it(self) -> None:
        spread = [
            TimeOfDayObservation(area_id=AREA, hour=index % 8, went_well=True)
            for index in range(THRESHOLD_TIME_OF_DAY_FITNESS)
        ]
        curve = fit_time_of_day_fitness(spread)

        assert curve.covers_enough_of_the_day is True

    def test_an_hour_no_local_day_has_is_refused_at_the_observation(self) -> None:
        with pytest.raises(ValueError, match="hour of a local day"):
            TimeOfDayObservation(area_id=AREA, hour=24, went_well=True)

    def test_a_tie_names_the_earlier_hour_so_one_corpus_names_one_hour(self) -> None:
        flat = fit_time_of_day_fitness(
            [TimeOfDayObservation(area_id=AREA, hour=hour, went_well=True) for hour in range(24)]
        )

        assert flat.worst_hour == 0
        assert flat.best_hour == 0


class TestSkipProbability:
    def test_an_empty_corpus_is_the_prior_of_refusing_nothing(self) -> None:
        result = fit_skip_probability([])

        assert result.value == PRIOR_SKIP_PROBABILITY == 0.0

    def test_a_bucket_the_user_always_refuses_fits_above_one_they_never_do(self) -> None:
        always = [
            SkipObservation(area_id=AREA, bucket=TimeBucket.MORNING, was_refused=True)
            for _ in range(20)
        ]
        never = [
            SkipObservation(area_id=AREA, bucket=TimeBucket.EVENING, was_refused=False)
            for _ in range(20)
        ]
        refused = fit_skip_probability(always)
        kept = fit_skip_probability(never)

        assert refused.value is not None
        assert kept.value is not None
        assert refused.value > kept.value
        assert 0.0 <= kept.value <= refused.value <= 1.0

    def test_the_fitted_share_never_leaves_zero_to_one(self) -> None:
        # The solver refuses a share outside it, so a fitter that could produce one would fail every
        # solve after the version was activated.
        for refusals in range(21):
            observed = [
                SkipObservation(
                    area_id=AREA, bucket=TimeBucket.MORNING, was_refused=index < refusals
                )
                for index in range(20)
            ]
            value = fit_skip_probability(observed).value
            assert value is not None
            assert 0.0 <= value <= 1.0


class TestContextSwitchCost:
    def test_a_corpus_with_no_within_area_pairs_is_not_fittable(self) -> None:
        # The metric is a DIFFERENCE between two populations. With one empty it is undefined, and
        # returning the prior would ship a hand-tuned number dressed as a measurement.
        across_only = [SwitchObservation(gap_minutes=45, changed_area=True) for _ in range(40)]
        result = fit_context_switch_cost(across_only)

        assert result.is_fitted is False
        assert result.value is None
        assert result.samples == 40

    def test_a_corpus_with_no_cross_area_pairs_is_not_fittable_either(self) -> None:
        within_only = [SwitchObservation(gap_minutes=5, changed_area=False) for _ in range(40)]
        result = fit_context_switch_cost(within_only)

        assert result.is_fitted is False
        assert result.samples == 0

    def test_the_price_is_the_extra_room_left_across_a_change(self) -> None:
        observed = [
            *(SwitchObservation(gap_minutes=45, changed_area=True) for _ in range(30)),
            *(SwitchObservation(gap_minutes=15, changed_area=False) for _ in range(30)),
        ]
        result = fit_context_switch_cost(observed)

        expected = (30 * 30.0 + PRIOR_WEIGHT * PRIOR_CONTEXT_SWITCH_COST) / (30 + PRIOR_WEIGHT)
        assert result.value == pytest.approx(expected)

    def test_a_user_who_leaves_no_more_room_across_a_change_fits_a_low_price(self) -> None:
        # The floor: a negative extra is clamped to zero, because a negative price would pay the
        # plan for changing Area.
        observed = [
            *(SwitchObservation(gap_minutes=5, changed_area=True) for _ in range(30)),
            *(SwitchObservation(gap_minutes=60, changed_area=False) for _ in range(30)),
        ]
        result = fit_context_switch_cost(observed)

        assert result.value is not None
        assert result.value >= 0.0
        assert result.value == pytest.approx(
            PRIOR_WEIGHT * PRIOR_CONTEXT_SWITCH_COST / (30 + PRIOR_WEIGHT)
        )

    def test_the_sample_count_is_the_cross_area_pairs_not_the_whole_corpus(self) -> None:
        # A corpus of one switch and forty same-Area pairs must not clear a gate about switches.
        observed = [
            SwitchObservation(gap_minutes=45, changed_area=True),
            *(SwitchObservation(gap_minutes=15, changed_area=False) for _ in range(40)),
        ]

        assert fit_context_switch_cost(observed).samples == 1

    def test_a_negative_gap_is_refused_at_the_observation(self) -> None:
        with pytest.raises(ValueError, match="room the week left"):
            SwitchObservation(gap_minutes=-30, changed_area=True)

    def test_a_population_spread_around_the_baseline_fits_the_difference_of_the_means(self) -> None:
        # The clamp is applied ONCE, to the difference of the two means. Applied to each pair's
        # difference instead it keeps this population's positive half at full size and truncates its
        # negative half, and a user whose true extra room is zero fits 10.2 rather than 0.2.
        result = fit_context_switch_cost(spread_around_a_baseline(far=55))

        assert result.value == pytest.approx(0.2)
        assert result.value != pytest.approx(10.2)
        assert result.value == pytest.approx(
            (40 * 0.0 + PRIOR_WEIGHT * PRIOR_CONTEXT_SWITCH_COST) / (40 + PRIOR_WEIGHT)
        )

    def test_the_count_is_the_cross_area_pairs_not_the_one_figure_that_was_shrunk(self) -> None:
        # One clamped figure is shrunk, over forty pairs. Counting the figure would leave 91% of a
        # value the user has forty observations of standing at the prior.
        observed = spread_around_a_baseline(far=55)
        result = fit_context_switch_cost(observed)

        assert len(gaps_across_areas(observed)) == 40
        assert result.samples == 40
        assert result.shrinkage_weight == pytest.approx(PRIOR_WEIGHT / (40 + PRIOR_WEIGHT))

    def test_the_interval_is_the_spread_of_the_unclamped_differences(self) -> None:
        # The one clamped figure has no spread, so an interval read off it would report forty
        # disagreeing pairs as a point. The pairs' own differences carry the disagreement and the
        # floor is not applied to them, so the interval is as wide as their population's while the
        # value it is centred on is the clamped one.
        observed = spread_around_a_baseline(far=45)
        differences = [gap - BASELINE_GAP for gap in gaps_across_areas(observed)]
        result = fit_context_switch_cost(observed)
        over_the_population = shrunk(differences, prior=PRIOR_CONTEXT_SWITCH_COST)

        assert result.value == pytest.approx(0.2)
        assert result.value is not None
        assert result.confidence is not None
        assert over_the_population.confidence is not None
        assert over_the_population.value != pytest.approx(result.value)
        assert result.confidence[0] < result.value < result.confidence[1]
        assert width(result.confidence) == pytest.approx(width(over_the_population.confidence))

    @pytest.mark.parametrize("gap", [0, 5, 600, 100_000])
    def test_the_fitted_price_never_leaves_the_clamp_range(self, gap: int) -> None:
        # Clamping the difference of the means bounds the figure a solver reads, whatever a row
        # said, and the absurd row is what drives it.
        observed = switch_corpus(across=[gap, *([30] * 39)], baseline=30)
        value = fit_context_switch_cost(observed).value

        assert value is not None
        assert MIN_SWITCH_COST_MINUTES <= value <= MAX_SWITCH_COST_MINUTES

    @pytest.mark.parametrize("outlier", [0, 1, 60, 119, 120], ids=str)
    def test_one_further_pair_cannot_move_the_price_past_the_stated_bound(
        self, outlier: int
    ) -> None:
        # Clamping the difference of the means leaves each pair's own difference outside the range's
        # reach, so the credibility bound has to be re-driven for this parameter rather than read
        # off the formula. What holds it is the OTHER bound: a gap at or above the ceiling absorbs
        # any price, so it is not evidence about one and never reaches here, which leaves a pair's
        # difference inside the width in both directions. Driven at the gate, from a settled corpus
        # of the smallest admissible gap, which is where the movement is largest.
        at_the_gate = [0] * THRESHOLD_CONTEXT_SWITCH_COST
        before = fit_context_switch_cost(switch_corpus(across=at_the_gate, baseline=0))
        after = fit_context_switch_cost(switch_corpus(across=[*at_the_gate, outlier], baseline=0))

        assert before.value is not None
        assert after.value is not None
        assert abs(after.value - before.value) <= outlier_bound(
            low=MIN_SWITCH_COST_MINUTES,
            high=MAX_SWITCH_COST_MINUTES,
            threshold=THRESHOLD_CONTEXT_SWITCH_COST,
        )

    def test_a_gap_the_extraction_drops_would_break_that_bound(self) -> None:
        # The positive control, and the reason the paragraph above is about the extraction rather
        # than about the clamp: the bound survives on what reaches the fitter, not on anything the
        # fitter does. A gap past the ceiling is refused upstream, in `features.py`.
        at_the_gate = [0] * THRESHOLD_CONTEXT_SWITCH_COST
        before = fit_context_switch_cost(switch_corpus(across=at_the_gate, baseline=0))
        after = fit_context_switch_cost(switch_corpus(across=[*at_the_gate, 100_000], baseline=0))

        assert before.value is not None
        assert after.value is not None
        assert abs(after.value - before.value) > outlier_bound(
            low=MIN_SWITCH_COST_MINUTES,
            high=MAX_SWITCH_COST_MINUTES,
            threshold=THRESHOLD_CONTEXT_SWITCH_COST,
        )


class TestChurnTolerance:
    def test_an_empty_corpus_is_the_prior(self) -> None:
        assert fit_churn_tolerance([]).value == PRIOR_CHURN_TOLERANCE

    def test_a_user_who_absorbs_eight_moves_fits_near_eight(self) -> None:
        observed = [ChurnObservation(moves=8, overridden=0) for _ in range(30)]
        result = fit_churn_tolerance(observed)

        expected = (30 * 8.0 + PRIOR_WEIGHT * PRIOR_CHURN_TOLERANCE) / (30 + PRIOR_WEIGHT)
        assert result.value == pytest.approx(expected)

    def test_a_user_who_pins_back_every_move_fits_at_the_floor_not_at_zero(self) -> None:
        # Zero is not a tolerance: it is a shape with no knee, and the term it shapes would be
        # undefined rather than steep. The solver's own guard refuses zero, so the clamp makes it
        # unreachable from here.
        observed = [ChurnObservation(moves=6, overridden=6) for _ in range(30)]
        result = fit_churn_tolerance(observed)

        assert result.value is not None
        assert result.value >= MIN_CHURN_TOLERANCE
        assert result.value == pytest.approx(
            (30 * MIN_CHURN_TOLERANCE + PRIOR_WEIGHT * PRIOR_CHURN_TOLERANCE) / (30 + PRIOR_WEIGHT)
        )

    def test_a_rearrangement_that_moved_nothing_is_not_evidence_about_tolerance(self) -> None:
        # A quiet week shows the user no rearrangement, so they absorbed none: counting it would
        # drag every tolerance toward the floor as weeks pass.
        quiet = [ChurnObservation(moves=0, overridden=0) for _ in range(30)]
        result = fit_churn_tolerance(quiet)

        assert result.samples == 0
        assert result.value == PRIOR_CHURN_TOLERANCE

    def test_more_overrides_than_moves_absorbs_nothing_rather_than_a_negative(self) -> None:
        # A user may pin a block the revision left alone, so the two counts are over overlapping but
        # not nested sets.
        assert ChurnObservation(moves=2, overridden=5).absorbed == 0

    def test_an_absurd_absorption_is_clamped_to_the_ceiling(self) -> None:
        observed = [ChurnObservation(moves=500, overridden=0) for _ in range(30)]
        result = fit_churn_tolerance(observed)

        assert result.value == pytest.approx(
            (30 * MAX_CHURN_TOLERANCE + PRIOR_WEIGHT * PRIOR_CHURN_TOLERANCE) / (30 + PRIOR_WEIGHT)
        )

    def test_a_negative_count_is_refused_at_the_observation(self) -> None:
        with pytest.raises(ValueError, match="can be negative"):
            ChurnObservation(moves=-1, overridden=0)
