"""The spellings this package restates, held against the packages that own them.

This package must not import ``syncr_solver`` or ``syncr_api``: the solver ships in the api image
and this one pulls scipy, so the arrow only runs one way. The cost is that the spellings below are
each written twice, and this file is what stops the two copies drifting. Both owners are DEV
dependencies, declared as such, and the image's export runs ``--no-dev``.

Exhaustive rather than sampled. All twenty-four hours of the bucketing, all seven term names, every
key of the stored context and the weight-set row, and every parameter a corpus at the gate produces,
because a sample passes on the day the two disagree about the one value it did not draw.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from syncr_api.learned.config import P0_WEIGHTS
from syncr_api.learned.gate_statements import (
    THRESHOLDS_ARE_ESTIMATES as API_THRESHOLDS_ARE_ESTIMATES,
)
from syncr_api.learned.models import WeightSet as WeightSetRow
from syncr_api.learned.subjects import subject_of
from syncr_api.plans import stored_contexts
from syncr_api.plans.edit_context import EditContext
from syncr_learning import artifact, config
from syncr_learning.fitting import fit_everything
from syncr_learning.fixtures import AREA, at_the_gate
from syncr_learning.gates import THRESHOLDS_ARE_ESTIMATES as LEARNING_THRESHOLDS_ARE_ESTIMATES
from syncr_learning.gates import ParameterMaturity, parameter_of
from syncr_learning.storage import spelling
from syncr_solver import weights as solver_weights

# What the corpus's one Area is called, and when the fit ran. Neither is read by the grammar under
# test; they are what a fit needs to run at all.
AREA_NAME = "Fitness"
FIT_AT = datetime(2026, 2, 16, 3, 0, tzinfo=UTC)
SWITCH_COST_IN_FORCE = 1.0
CHURN_TOLERANCE_IN_FORCE = 3.0


class TestTheThresholdStatement:
    def test_the_learning_and_api_copies_are_byte_identical(self) -> None:
        assert LEARNING_THRESHOLDS_ARE_ESTIMATES.encode() == API_THRESHOLDS_ARE_ESTIMATES.encode()


class TestTheObjectiveVocabulary:
    def test_the_seven_term_names_are_the_solver_s_own(self) -> None:
        assert config.OBJECTIVE_TERMS == solver_weights.OBJECTIVE_TERMS

    def test_the_seven_are_also_what_a_weight_set_row_holds_as_columns(self) -> None:
        # The fitted vector is written into those columns, so a term with no column would be a
        # fitted number with nowhere to go.
        columns = set(WeightSetRow.__table__.columns.keys())

        assert set(config.OBJECTIVE_TERMS) <= columns

    def test_a_local_day_has_the_same_number_of_hours_in_both_packages(self) -> None:
        assert config.HOURS_PER_DAY == solver_weights.HOURS_PER_DAY


class TestTheTimeBuckets:
    def test_the_three_bucket_names_match(self) -> None:
        assert {one.value for one in config.TimeBucket} == {
            one.value for one in solver_weights.TimeBucket
        }

    def test_every_hour_of_the_day_buckets_the_same_way_in_both_packages(self) -> None:
        # The boundaries are behaviour rather than a name, so this is the agreement that matters: a
        # fitter that bucketed 17:00 as afternoon would write a probability the solver reads under
        # evening, and the figure would be applied to the wrong part of every day.
        ours = [config.bucket_of(hour).value for hour in range(config.HOURS_PER_DAY)]
        theirs = [solver_weights.bucket_of(hour).value for hour in range(config.HOURS_PER_DAY)]

        assert ours == theirs

    def test_an_hour_no_day_has_is_refused_by_both(self) -> None:
        # Both raise, and each raises its own package's type: the agreement is that neither accepts
        # an hour outside the day, not that they share an exception class.
        for hour in (-1, config.HOURS_PER_DAY, 99):
            with pytest.raises(ValueError, match="hour of a local day"):
                config.bucket_of(hour)
            with pytest.raises(ValueError, match="hour of a local day"):
                solver_weights.bucket_of(hour)


class TestThePriorsAreTheHandTunedFigures:
    """Each prior is the number version 1 ships, because that figure IS the prior belief.

    A differently chosen prior would mean the first observation moved a parameter away from what the
    solver was already using, which is the opposite of what shrinkage is for.
    """

    def test_the_context_switch_price_prior_is_the_hand_tuned_price(self) -> None:
        assert P0_WEIGHTS["context_switch_cost"] == config.PRIOR_CONTEXT_SWITCH_COST

    def test_the_churn_tolerance_prior_is_the_hand_tuned_tolerance(self) -> None:
        assert P0_WEIGHTS["churn_tolerance"] == config.PRIOR_CHURN_TOLERANCE

    def test_every_hand_tuned_figure_is_either_a_term_weight_or_one_of_those_two(self) -> None:
        # Both directions, so a tenth hand-tuned number could not appear with no prior beside it.
        assert set(P0_WEIGHTS) == set(config.OBJECTIVE_TERMS) | {
            "context_switch_cost",
            "churn_tolerance",
        }


class TestTheStoredSpelling:
    def test_the_three_fitted_maps_are_named_as_the_row_names_them(self) -> None:
        columns = set(WeightSetRow.__table__.columns.keys())

        assert artifact.DURATION_MULTIPLIER_KEY in columns
        assert artifact.TIME_OF_DAY_FITNESS_KEY in columns
        assert artifact.SKIP_PROBABILITY_KEY in columns

    def test_every_column_the_artefact_writes_exists_on_the_row(self) -> None:
        # The insert names these directly, so a renamed column is a failed insert at 03:00 rather
        # than a failing test in CI without this.
        written = set(
            artifact.FittedWeightSet(
                term_weights=dict.fromkeys(config.OBJECTIVE_TERMS, 1.0),
                context_switch_cost=1.0,
                churn_tolerance=3.0,
            ).columns()
        )
        columns = set(WeightSetRow.__table__.columns.keys())

        assert written <= columns, sorted(written - columns)

    def test_a_maturity_row_stores_every_field_it_holds(self) -> None:
        fields = {one.name for one in dataclasses.fields(ParameterMaturity)}
        stored = set(
            artifact.stored_maturity(
                ParameterMaturity(
                    parameter="duration_multiplier",
                    samples=12,
                    threshold=12,
                    state="ready",
                    value=1.3,
                    shrinkage_weight=0.45,
                    plain_language="a sentence",
                )
            )
        )

        assert stored == fields

    def test_the_origin_this_job_writes_is_one_the_row_allows(self) -> None:
        from syncr_api.learned.config import FITTED

        assert artifact.FITTED_ORIGIN == FITTED


class TestTheEditContextKeysTheFitterReads:
    def test_the_measurement_difference_key_is_the_same_string_on_both_sides(self) -> None:
        # CROSSED, not pinned. An earlier version asserted the api's constant against a literal,
        # which catches an api-side rename and not a learning-side one: and the learning side is the
        # one that restated the spelling, so it is the side more likely to drift.
        assert spelling.CONTEXT_MEASUREMENT_DELTA == stored_contexts.MEASUREMENT_DELTA
        assert "measurement_delta" in {one.name for one in dataclasses.fields(EditContext)}

    def test_the_off_plan_flag_key_is_the_same_string_on_both_sides(self) -> None:
        assert spelling.CONTEXT_INSIDE_OFF_PLAN == stored_contexts.INSIDE_OFF_PLAN
        assert "inside_off_plan" in {one.name for one in dataclasses.fields(EditContext)}

    def test_every_context_key_this_package_restates_is_a_field_of_the_context(self) -> None:
        # The set direction, so a third key restated here with no field to read cannot pass.
        restated = {spelling.CONTEXT_MEASUREMENT_DELTA, spelling.CONTEXT_INSIDE_OFF_PLAN}

        assert restated <= {one.name for one in dataclasses.fields(EditContext)}

    def test_a_stored_measurement_difference_names_the_seven_terms_this_package_expects(
        self,
    ) -> None:
        from syncr_api.pins.costs import UNCHANGED

        assert set(UNCHANGED) == set(config.OBJECTIVE_TERMS)


class TestTheKeyInsideAParameterToken:
    """The key this package writes into a token, read back by the api that names the Area from it.

    :func:`syncr_learning.gates.maturity` composes ``name[key]`` and
    :mod:`syncr_learning.applied` joins a pair key as the Area then the bucket. The api takes that
    key back out to say what a row is about, and nothing else crosses the two: a respelling on
    either side answers no Area for every row, which is a change no assertion inside either package
    can see.

    Driven through the real fitter over the shared corpus, so every token is composed by the writer
    rather than typed here.
    """

    def test_every_parameter_a_corpus_at_the_gate_produces_names_the_right_subject(self) -> None:
        rows = fit_everything(
            at_the_gate(),
            in_force=P0_WEIGHTS,
            switch_cost_in_force=SWITCH_COST_IN_FORCE,
            churn_tolerance_in_force=CHURN_TOLERANCE_IN_FORCE,
            area_names={str(AREA): AREA_NAME},
            at=FIT_AT,
        ).artifact.maturity

        # Pairs rather than a mapping, so a parameter that produces several rows cannot hide one
        # behind another, and spelled out rather than derived from the resolver under test.
        assert {
            (parameter_of(row), subject_of(row.parameter, {AREA: AREA_NAME})) for row in rows
        } == {
            (config.DURATION_MULTIPLIER, AREA_NAME),
            (config.TIME_OF_DAY_FITNESS, AREA_NAME),
            (config.SKIP_PROBABILITY, AREA_NAME),
            (config.CONTEXT_SWITCH_COST, None),
            (config.CHURN_TOLERANCE, None),
            (config.OBJECTIVE_WEIGHTS, None),
        }
