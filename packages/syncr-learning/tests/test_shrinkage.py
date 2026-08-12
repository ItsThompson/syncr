"""Shrinkage: the three worked cases, the bound on one outlier, and the interval.

The three cases are quoted with their figures rather than with a direction: an
assertion that the value "moved toward the mean" passes at any ``k`` and would not have caught a
formula that divided by ``n`` instead of ``n + k``.
"""

from __future__ import annotations

from statistics import fmean

import pytest

from syncr_learning.config import (
    MAX_DURATION_RATIO,
    MIN_DURATION_RATIO,
    PRIOR_WEIGHT,
    THRESHOLD_DURATION_MULTIPLIER,
    ConfigError,
)
from syncr_learning.shrinkage import clamped, outlier_bound, shrunk, shrunk_figure

PRIOR = 1.0
OBSERVED = 2.0


class TestTheThreeWorkedCases:
    """``n=1, k=10`` is 91% prior; ``n=10, k=10`` is half and half; ``n=50`` is 83% observed."""

    def test_one_observation_leaves_the_value_ninety_one_percent_prior(self) -> None:
        result = shrunk([OBSERVED] * 1, prior=PRIOR, prior_weight=10)

        assert result.shrinkage_weight == pytest.approx(10 / 11)
        assert result.value == pytest.approx((1 * OBSERVED + 10 * PRIOR) / 11)
        assert result.value == pytest.approx(1.0909, abs=1e-4)

    def test_ten_observations_are_half_prior_and_half_observed(self) -> None:
        result = shrunk([OBSERVED] * 10, prior=PRIOR, prior_weight=10)

        assert result.shrinkage_weight == pytest.approx(0.5)
        assert result.value == pytest.approx(1.5)

    def test_fifty_observations_are_eighty_three_percent_observed(self) -> None:
        result = shrunk([OBSERVED] * 50, prior=PRIOR, prior_weight=10)

        assert result.shrinkage_weight == pytest.approx(10 / 60)
        assert 1 - result.shrinkage_weight == pytest.approx(0.8333, abs=1e-4)
        assert result.value == pytest.approx(1.8333, abs=1e-4)

    def test_the_default_prior_weight_is_the_ten_the_three_cases_are_worked_at(self) -> None:
        # The three cases above pass `prior_weight` explicitly so they state what they are about.
        # This is what says the default is the same figure, so a change to it reddens the cases too.
        assert PRIOR_WEIGHT == 10
        assert shrunk([OBSERVED] * 10, prior=PRIOR).value == pytest.approx(1.5)


class TestNoEvidence:
    def test_no_observations_is_the_prior_at_a_shrinkage_weight_of_one(self) -> None:
        result = shrunk([], prior=PRIOR)

        assert result.value == PRIOR
        assert result.samples == 0
        assert result.shrinkage_weight == 1.0

    def test_a_prior_worth_nothing_is_refused(self) -> None:
        # A prior weight of zero makes the formula the plain empirical mean, which is the erratic
        # behaviour shrinkage exists to prevent, and over an empty list it divides by nothing.
        with pytest.raises(ConfigError, match="prior worth nothing"):
            shrunk([OBSERVED], prior=PRIOR, prior_weight=0)


class TestOneOutlierCannotMoveADisplayedParameter:
    """The property the Learned screen's credibility rests on, asserted as the derived bound.

    Driven over the extremes rather than over a random draw, because the bound is attained at the
    extremes: an observation at either end of the clamp is the worst case, so a sweep that includes
    both is a stronger statement than a sample that probably misses them.
    """

    @pytest.mark.parametrize(
        "outlier",
        [MIN_DURATION_RATIO, MAX_DURATION_RATIO, 0.0, 1000.0, -50.0],
        ids=["at the floor", "at the ceiling", "zero", "absurdly long", "negative"],
    )
    def test_one_further_observation_stays_inside_the_stated_bound(self, outlier: float) -> None:
        at_the_gate = [1.2] * THRESHOLD_DURATION_MULTIPLIER
        before = shrunk(at_the_gate, prior=PRIOR)
        clamped_outlier = clamped(outlier, low=MIN_DURATION_RATIO, high=MAX_DURATION_RATIO)
        after = shrunk([*at_the_gate, clamped_outlier], prior=PRIOR)

        assert before.value is not None
        assert after.value is not None
        bound = outlier_bound(
            low=MIN_DURATION_RATIO,
            high=MAX_DURATION_RATIO,
            threshold=THRESHOLD_DURATION_MULTIPLIER,
        )
        assert abs(after.value - before.value) <= bound

    def test_the_bound_is_the_width_over_the_gate_plus_the_prior_weight_plus_one(self) -> None:
        # Stated as the arithmetic rather than as a literal, so the figure cannot disagree with the
        # three numbers it is derived from.
        assert outlier_bound(low=0.25, high=4.0, threshold=12) == pytest.approx(3.75 / 23)

    def test_an_unclamped_outlier_breaks_the_bound_which_is_why_every_fitter_clamps(self) -> None:
        # The positive control. Without the clamp the same sweep passes nothing: this is the failure
        # the clamp exists to prevent, driven so the clamp is not decoration.
        at_the_gate = [1.2] * THRESHOLD_DURATION_MULTIPLIER
        before = shrunk(at_the_gate, prior=PRIOR)
        after = shrunk([*at_the_gate, 1000.0], prior=PRIOR)

        assert before.value is not None
        assert after.value is not None
        bound = outlier_bound(
            low=MIN_DURATION_RATIO,
            high=MAX_DURATION_RATIO,
            threshold=THRESHOLD_DURATION_MULTIPLIER,
        )
        assert abs(after.value - before.value) > bound


class TestTheInterval:
    def test_one_observation_has_no_spread_so_the_interval_is_a_point(self) -> None:
        result = shrunk([OBSERVED], prior=PRIOR)

        assert result.confidence is not None
        assert result.confidence[0] == pytest.approx(result.confidence[1])

    def test_more_agreeing_observations_narrow_the_interval(self) -> None:
        few = shrunk([1.0, 2.0, 3.0] * 2, prior=PRIOR)
        many = shrunk([1.0, 2.0, 3.0] * 20, prior=PRIOR)

        assert few.confidence is not None
        assert many.confidence is not None
        assert _width(many.confidence) < _width(few.confidence)

    def test_the_interval_is_centred_on_the_fitted_value_not_on_the_empirical_mean(self) -> None:
        # The fitted value is what is displayed and applied, so an interval around the empirical
        # mean would describe an estimate nothing reads.
        result = shrunk([3.0, 3.0, 3.0], prior=PRIOR)

        assert result.value is not None
        assert result.confidence is not None
        assert (result.confidence[0] + result.confidence[1]) / 2 == pytest.approx(result.value)
        assert result.value != pytest.approx(3.0)


class TestAFigureShrunkOverAPopulation:
    """``shrunk_figure``: the count and the spread are the population's, the figure is not.

    The shape a fitter needs when its empirical figure is not the mean of what it observed, which is
    the case for a price that clamps the difference of two means.
    """

    def test_the_count_and_the_weight_come_from_the_population(self) -> None:
        result = shrunk_figure(OBSERVED, spread=[0.0] * 40, prior=PRIOR)

        assert result.samples == 40
        assert result.shrinkage_weight == pytest.approx(10 / 50)
        assert result.value == pytest.approx((40 * OBSERVED + 10 * PRIOR) / 50)

    def test_the_interval_is_the_populations_spread_around_the_figure_that_was_shrunk(self) -> None:
        population = [1.0, 2.0, 3.0] * 8
        around_a_figure = shrunk_figure(9.0, spread=population, prior=PRIOR)
        over_the_population = shrunk(population, prior=PRIOR)

        assert around_a_figure.value is not None
        assert around_a_figure.confidence is not None
        assert over_the_population.confidence is not None
        assert around_a_figure.value != pytest.approx(over_the_population.value)
        assert _width(around_a_figure.confidence) == pytest.approx(
            _width(over_the_population.confidence)
        )
        assert (around_a_figure.confidence[0] + around_a_figure.confidence[1]) / 2 == pytest.approx(
            around_a_figure.value
        )

    def test_an_empty_population_is_the_prior_whatever_figure_is_handed_in(self) -> None:
        result = shrunk_figure(999.0, spread=[], prior=PRIOR)

        assert result.value == PRIOR
        assert result.samples == 0
        assert result.shrinkage_weight == 1.0

    def test_shrinking_a_populations_own_mean_over_it_is_exactly_what_shrunk_does(self) -> None:
        # What keeps the four fitters that clamp per observation on the path they were on: the
        # sequence form is the figure form at the population's own mean, not a second formula.
        population = [1.0, 2.0, 6.0]

        assert shrunk_figure(fmean(population), spread=population, prior=PRIOR) == shrunk(
            population, prior=PRIOR
        )


class TestClamping:
    def test_a_value_inside_the_range_is_unchanged(self) -> None:
        assert clamped(1.5, low=0.25, high=4.0) == 1.5

    @pytest.mark.parametrize(("value", "expected"), [(-3.0, 0.25), (99.0, 4.0)])
    def test_a_value_outside_the_range_is_brought_to_the_nearer_edge(
        self, value: float, expected: float
    ) -> None:
        assert clamped(value, low=0.25, high=4.0) == expected

    def test_a_backwards_range_is_refused(self) -> None:
        with pytest.raises(ConfigError, match="runs backwards"):
            clamped(1.0, low=4.0, high=0.25)


def _width(interval: tuple[float, float]) -> float:
    return interval[1] - interval[0]
