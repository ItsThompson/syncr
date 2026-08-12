"""The maturity gates: below the threshold nothing is applied, and the two scalars are gated too.

The scalar half is the harder one: ``context_switch_cost`` and ``churn_tolerance`` are non-nullable
columns, so "below its gate" cannot be expressed as an absent key the way it can for the three maps.
What enforces it is that the artefact takes an already-gated value, and the tests here drive that
through the composition rather than asserting the gate function in isolation.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from syncr_learning.config import (
    CHURN_TOLERANCE,
    CONTEXT_SWITCH_COST,
    DURATION_MULTIPLIER,
    FITTED_PARAMETERS,
    OBJECTIVE_TERMS,
    OBJECTIVE_WEIGHTS,
    SKIP_PROBABILITY,
    THRESHOLD_DURATION_MULTIPLIER,
    THRESHOLDS,
    TIME_OF_DAY_FITNESS,
    ConfigError,
    TimeBucket,
)
from syncr_learning.features import extract
from syncr_learning.fitting import FittedParameters, fit_everything
from syncr_learning.gates import (
    COLLECTING,
    READY,
    THRESHOLDS_ARE_ESTIMATES,
    ParameterMaturity,
    gated,
    threshold_for,
)
from syncr_learning.observations import (
    ChurnObservation,
    DurationObservation,
    Observations,
    RankExample,
    SkipObservation,
    SwitchObservation,
    TimeOfDayObservation,
)
from syncr_learning.preferences import unmeasured
from syncr_learning.results import FitResult
from tests.builders import AREA, a_week_of, corpus, edit
from tests.test_rank import IN_FORCE, rotating

AT = datetime(2026, 2, 16, 3, 0, tzinfo=UTC)
AREA_NAMES = {str(AREA): "Fitness"}

# Edit rows that predate the measurement, more of them than the gate needs, so a count that
# included them would clear a gate no fit reached.
ROWS_PREDATING_THE_MEASUREMENT = THRESHOLDS[OBJECTIVE_WEIGHTS] + 10
MEASURED_EDITS = 5
A_MEASURED_DIFFERENCE = dict.fromkeys(OBJECTIVE_TERMS, -1.0)


def fitted_from(observations: Observations) -> FittedParameters:
    return fit_everything(
        observations,
        in_force=IN_FORCE,
        switch_cost_in_force=1.0,
        churn_tolerance_in_force=3.0,
        area_names=AREA_NAMES,
        at=AT,
    )


def observations(
    *,
    durations: tuple[DurationObservation, ...] = (),
    time_of_day: tuple[TimeOfDayObservation, ...] = (),
    skips: tuple[SkipObservation, ...] = (),
    switches: tuple[SwitchObservation, ...] = (),
    churn: tuple[ChurnObservation, ...] = (),
    ranking: tuple[RankExample, ...] = (),
) -> Observations:
    """One corpus of observations with only the kinds a test names populated."""
    return Observations(
        durations=durations,
        time_of_day=time_of_day,
        skips=skips,
        switches=switches,
        churn=churn,
        ranking=ranking,
    )


class TestEveryParameterHasAThreshold:
    def test_the_six_gated_parameters_are_the_six_with_thresholds(self) -> None:
        # Both directions. A parameter with no gate would be applied unfitted, and a threshold for a
        # parameter nothing fits would be a gate on nothing.
        assert set(FITTED_PARAMETERS) == set(THRESHOLDS)

    def test_a_parameter_with_no_threshold_is_a_name_error_rather_than_a_gate_of_zero(self) -> None:
        with pytest.raises(ConfigError, match="no maturity threshold"):
            threshold_for("novelty")

    def test_the_screen_is_given_the_sentence_that_says_these_are_estimates(self) -> None:
        # They are the PRD author's guesses, and asserting a guess as a measurement would violate
        # the product's own standard.
        assert "estimates rather than measurements" in THRESHOLDS_ARE_ESTIMATES
        assert "no migration" in THRESHOLDS_ARE_ESTIMATES


class TestBelowTheThresholdNothingIsApplied:
    def test_one_below_the_gate_writes_no_entry_and_one_at_it_writes_one(self) -> None:
        below = fitted_from(extract(a_week_of(THRESHOLD_DURATION_MULTIPLIER - 1)))
        at_the_gate = fitted_from(extract(a_week_of(THRESHOLD_DURATION_MULTIPLIER)))

        assert below.artifact.duration_multiplier == {}
        assert str(AREA) in at_the_gate.artifact.duration_multiplier

    def test_a_parameter_below_the_gate_is_not_applied_at_a_reduced_weight(self) -> None:
        # Absence rather than a scaled-down figure: a half-fitted number is worse than a hand-tuned
        # one, so the map has no entry at all rather than an entry nearer to one.
        below = fitted_from(extract(a_week_of(THRESHOLD_DURATION_MULTIPLIER - 1)))
        rows = [
            row for row in below.artifact.maturity if row.parameter.startswith(DURATION_MULTIPLIER)
        ]

        assert len(rows) == 1
        assert rows[0].state == COLLECTING
        assert rows[0].value is None
        assert rows[0].samples == THRESHOLD_DURATION_MULTIPLIER - 1

    def test_gated_answers_nothing_below_the_threshold_and_the_value_at_it(self) -> None:
        below = FitResult(value=1.4, samples=1, confidence=(1.4, 1.4), shrinkage_weight=0.9)
        at_the_gate = FitResult(
            value=1.4,
            samples=THRESHOLD_DURATION_MULTIPLIER,
            confidence=(1.4, 1.4),
            shrinkage_weight=0.4,
        )

        assert gated(DURATION_MULTIPLIER, below) is None
        assert gated(DURATION_MULTIPLIER, at_the_gate) == 1.4

    def test_an_unfittable_result_is_not_let_through_however_many_samples_it_has(self) -> None:
        # The switch price over one population: plenty of observations and no defined figure.
        assert gated(CONTEXT_SWITCH_COST, FitResult.unfittable(500)) is None


class TestWhatAnUnmeasuredEditCountsToward:
    """The weights gate's denominator: a row carrying no measured difference is not in it.

    The exclusion is applied where the corpus is built, so the count the gate compares against the
    threshold is taken after it and the excluded rows are in neither. Both figures a reader meets
    come from the one corpus here: the count the row reports, and the figure the gauge is set from.
    """

    def test_an_unmeasured_edit_reaches_neither_the_fit_nor_the_count(self) -> None:
        built = corpus(
            edits=[
                *(edit(difference=None) for _ in range(ROWS_PREDATING_THE_MEASUREMENT)),
                *(edit(difference=A_MEASURED_DIFFERENCE) for _ in range(MEASURED_EDITS)),
            ]
        )
        observed = extract(built)
        row = next(
            one
            for one in fitted_from(observed).artifact.maturity
            if one.parameter == OBJECTIVE_WEIGHTS
        )

        assert unmeasured(built.edits, built.off_plan) == ROWS_PREDATING_THE_MEASUREMENT
        assert len(observed.ranking) == MEASURED_EDITS
        assert row.samples == MEASURED_EDITS
        assert row.threshold == THRESHOLDS[OBJECTIVE_WEIGHTS]
        assert row.state == COLLECTING


class TestTheTwoScalarsComeUnderTheGateToo:
    """The half nothing structurally enforced, because neither column can be absent."""

    def test_a_switch_price_below_its_gate_leaves_the_figure_in_force(self) -> None:
        thin = observations(
            switches=(
                SwitchObservation(gap_minutes=45, changed_area=True),
                SwitchObservation(gap_minutes=10, changed_area=False),
            )
        )
        fitted = fitted_from(thin)

        assert fitted.artifact.context_switch_cost == 1.0

    def test_a_switch_price_at_its_gate_replaces_it(self) -> None:
        plenty = observations(
            switches=(
                *(
                    SwitchObservation(gap_minutes=45, changed_area=True)
                    for _ in range(THRESHOLDS[CONTEXT_SWITCH_COST])
                ),
                *(SwitchObservation(gap_minutes=5, changed_area=False) for _ in range(20)),
            )
        )
        fitted = fitted_from(plenty)

        assert fitted.artifact.context_switch_cost != 1.0
        assert fitted.artifact.context_switch_cost > 1.0

    def test_a_churn_tolerance_below_its_gate_leaves_the_figure_in_force(self) -> None:
        thin = observations(churn=(ChurnObservation(moves=8, overridden=1),))

        assert fitted_from(thin).artifact.churn_tolerance == 3.0

    def test_a_churn_tolerance_at_its_gate_replaces_it(self) -> None:
        plenty = observations(
            churn=tuple(
                ChurnObservation(moves=9, overridden=0) for _ in range(THRESHOLDS[CHURN_TOLERANCE])
            )
        )

        assert fitted_from(plenty).artifact.churn_tolerance > 3.0

    def test_a_refused_switch_fit_leaves_the_figure_in_force_rather_than_the_prior(self) -> None:
        # The distinction that matters for a scalar: the fallback has to be what the solver is
        # using, so a refused fit moves nothing. Falling back to the prior would move the number
        # every time the incumbent had already been retuned.
        one_population = observations(
            switches=tuple(SwitchObservation(gap_minutes=45, changed_area=True) for _ in range(50))
        )
        fitted = fit_everything(
            one_population,
            in_force=IN_FORCE,
            switch_cost_in_force=7.5,
            churn_tolerance_in_force=3.0,
            area_names=AREA_NAMES,
            at=AT,
        )

        assert fitted.artifact.context_switch_cost == 7.5


class TestTheMaturityRow:
    def test_a_ready_row_states_a_value_and_a_collecting_row_states_none(self) -> None:
        with pytest.raises(ConfigError, match="collecting"):
            ParameterMaturity(
                parameter=DURATION_MULTIPLIER,
                samples=99,
                threshold=12,
                state=COLLECTING,
                value=1.4,
                shrinkage_weight=0.1,
                plain_language="a sentence",
            )

    def test_a_ready_row_below_its_threshold_is_refused(self) -> None:
        # A figure the gate did not let through cannot be reported as ready, which is the one way a
        # row could disagree with the artefact beside it.
        with pytest.raises(ConfigError, match="not applied at all"):
            ParameterMaturity(
                parameter=DURATION_MULTIPLIER,
                samples=3,
                threshold=12,
                state=READY,
                value=1.4,
                shrinkage_weight=0.1,
                plain_language="a sentence",
            )

    def test_a_row_with_no_sentence_is_refused(self) -> None:
        with pytest.raises(ConfigError, match="plain language"):
            ParameterMaturity(
                parameter=DURATION_MULTIPLIER,
                samples=12,
                threshold=12,
                state=READY,
                value=1.4,
                shrinkage_weight=0.1,
                plain_language="   ",
            )

    def test_the_sentence_names_the_area_and_both_medians(self) -> None:
        fitted = fitted_from(extract(a_week_of(THRESHOLD_DURATION_MULTIPLIER)))
        row = next(
            row for row in fitted.artifact.maturity if row.parameter.startswith(DURATION_MULTIPLIER)
        )

        assert "Fitness" in row.plain_language
        assert "60m" in row.plain_language
        assert "82m" in row.plain_language

    def test_a_collecting_sentence_says_collecting_is_normal(self) -> None:
        # "Collecting" renders at informational volume, never as a warning: nothing is broken while
        # a parameter collects, and marking it as a fault would teach the user to distrust the
        # system.
        fitted = fitted_from(extract(a_week_of(2)))
        row = next(
            row for row in fitted.artifact.maturity if row.parameter.startswith(DURATION_MULTIPLIER)
        )

        assert "normal" in row.plain_language

    def test_a_row_is_named_for_its_key_so_the_screen_can_draw_one_per_area(self) -> None:
        fitted = fitted_from(extract(a_week_of(THRESHOLD_DURATION_MULTIPLIER)))
        names = [row.parameter for row in fitted.artifact.maturity]

        assert f"{DURATION_MULTIPLIER}[{AREA}]" in names

    def test_every_parameter_the_corpus_touches_has_a_row(self) -> None:
        rich = observations(
            durations=extract(a_week_of(20)).durations,
            time_of_day=extract(a_week_of(20)).time_of_day,
            skips=(SkipObservation(area_id=AREA, bucket=TimeBucket.MORNING, was_refused=False),),
            switches=(SwitchObservation(gap_minutes=30, changed_area=True),),
            churn=(ChurnObservation(moves=3, overridden=0),),
            ranking=tuple(rotating(70)),
        )
        fitted = fitted_from(rich)
        parameters = {row.parameter.split("[", 1)[0] for row in fitted.artifact.maturity}

        assert parameters == {
            DURATION_MULTIPLIER,
            TIME_OF_DAY_FITNESS,
            SKIP_PROBABILITY,
            CONTEXT_SWITCH_COST,
            CHURN_TOLERANCE,
            OBJECTIVE_WEIGHTS,
        }

    def test_ready_and_collecting_partition_the_rows(self) -> None:
        fitted = fitted_from(extract(a_week_of(THRESHOLD_DURATION_MULTIPLIER)))

        assert fitted.ready + fitted.collecting == len(fitted.artifact.maturity)
