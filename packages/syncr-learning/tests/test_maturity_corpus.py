"""The ``maturity_corpus`` fixture, driven either side of every gate.

This is the fixture's own gate test: what it has to guarantee is that ``below_the_gate`` applies
NOTHING and ``at_the_gate`` applies EVERYTHING, for all six parameters at once. A fixture that
straddled five of the six would leave one gate untested by every consumer that trusted it.

``unfittable`` is the third corpus and the assertion over it is the one a count-only gate fails:
plenty of observations, and not one parameter a fit could honestly produce.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from syncr_learning.config import (
    CHURN_TOLERANCE,
    CONTEXT_SWITCH_COST,
    DURATION_MULTIPLIER,
    FITTED_PARAMETERS,
    OBJECTIVE_WEIGHTS,
    SKIP_PROBABILITY,
    THRESHOLDS,
    TIME_OF_DAY_FITNESS,
)
from syncr_learning.fitting import FittedParameters, fit_everything
from syncr_learning.fixtures import AREA, at_the_gate, below_the_gate, unfittable
from syncr_learning.gates import parameter_of
from tests.test_rank import IN_FORCE

AT = datetime(2026, 2, 16, 3, 0, tzinfo=UTC)
SWITCH_IN_FORCE = 1.0
CHURN_IN_FORCE = 3.0


def fitted(observations: object) -> FittedParameters:
    return fit_everything(
        observations,  # type: ignore[arg-type]
        in_force=IN_FORCE,
        switch_cost_in_force=SWITCH_IN_FORCE,
        churn_tolerance_in_force=CHURN_IN_FORCE,
        area_names={str(AREA): "Fitness"},
        at=AT,
    )


class TestTheCorpusStraddlesEveryGate:
    def test_below_the_gate_every_parameter_is_one_observation_short(self) -> None:
        # The fixture's own claim, asserted against the thresholds it was built from rather than
        # against literals: a revised threshold moves both sides of the pair together.
        rows = {parameter_of(row): row for row in fitted(below_the_gate()).artifact.maturity}

        for parameter in FITTED_PARAMETERS:
            assert rows[parameter].samples == THRESHOLDS[parameter] - 1, parameter

    def test_at_the_gate_every_parameter_is_exactly_at_its_threshold(self) -> None:
        rows = {parameter_of(row): row for row in fitted(at_the_gate()).artifact.maturity}

        for parameter in FITTED_PARAMETERS:
            assert rows[parameter].samples == THRESHOLDS[parameter], parameter

    def test_nothing_at_all_is_applied_below_the_gate(self) -> None:
        artifact = fitted(below_the_gate()).artifact

        assert artifact.duration_multiplier == {}
        assert artifact.time_of_day_fitness == {}
        assert artifact.skip_probability == {}
        assert artifact.context_switch_cost == SWITCH_IN_FORCE
        assert artifact.churn_tolerance == CHURN_IN_FORCE
        assert artifact.term_weights == IN_FORCE

    def test_everything_is_applied_at_the_gate(self) -> None:
        artifact = fitted(at_the_gate()).artifact

        assert str(AREA) in artifact.duration_multiplier
        assert len(artifact.time_of_day_fitness[str(AREA)]) == 24
        assert artifact.skip_probability[str(AREA)]
        assert artifact.context_switch_cost != SWITCH_IN_FORCE
        assert artifact.churn_tolerance != CHURN_IN_FORCE
        assert artifact.term_weights != IN_FORCE

    def test_every_row_is_collecting_below_the_gate_and_ready_at_it(self) -> None:
        below = fitted(below_the_gate())
        gated = fitted(at_the_gate())

        assert below.ready == 0
        assert below.collecting == len(FITTED_PARAMETERS)
        assert gated.collecting == 0
        assert gated.ready == len(FITTED_PARAMETERS)

    def test_the_duration_statement_quotes_the_two_medians_at_the_gate(self) -> None:
        row = next(
            row
            for row in fitted(at_the_gate()).artifact.maturity
            if parameter_of(row) == DURATION_MULTIPLIER
        )

        assert "60m" in row.plain_language
        assert "82m" in row.plain_language
        assert row.value == pytest.approx(
            (THRESHOLDS[DURATION_MULTIPLIER] * (82 / 60) + 10 * 1.0)
            / (THRESHOLDS[DURATION_MULTIPLIER] + 10)
        )


class TestTheUnfittableCorpus:
    @pytest.mark.parametrize("parameter", [TIME_OF_DAY_FITNESS, CONTEXT_SWITCH_COST])
    def test_a_count_only_gate_would_pass_on_it(self, parameter: str) -> None:
        # The premise of the corpus for these two: MORE observations than the threshold, so a gate
        # that read only the count would let both through. The refusal has to come from what the
        # data cannot support -- a curve over one hour, a difference with no baseline -- rather than
        # from its size.
        rows = {parameter_of(row): row for row in fitted(unfittable()).artifact.maturity}

        assert rows[parameter].samples > THRESHOLDS[parameter]

    @pytest.mark.parametrize("parameter", [CHURN_TOLERANCE, OBJECTIVE_WEIGHTS])
    def test_the_other_two_are_refused_at_the_count_itself(self, parameter: str) -> None:
        # Their fitters drop the meaningless observations BEFORE counting: a rearrangement that
        # moved nothing is not evidence about tolerance, and a pair of two identical placements
        # states no preference. So the count reported is zero even though the corpus holds twice the
        # threshold, which is a stronger property than refusing afterwards would be.
        rows = {parameter_of(row): row for row in fitted(unfittable()).artifact.maturity}

        assert rows[parameter].samples == 0

    def test_and_yet_nothing_is_applied_from_it(self) -> None:
        artifact = fitted(unfittable()).artifact

        assert artifact.time_of_day_fitness == {}
        assert artifact.context_switch_cost == SWITCH_IN_FORCE
        assert artifact.churn_tolerance == CHURN_IN_FORCE
        assert artifact.term_weights == IN_FORCE

    def test_the_parameters_it_carries_no_evidence_for_have_no_row(self) -> None:
        # Two of the six are absent from the corpus entirely, so they have no row rather than a row
        # with a sample count of zero: a row is per KEY, and there is no key.
        present = {parameter_of(row) for row in fitted(unfittable()).artifact.maturity}

        assert DURATION_MULTIPLIER not in present
        assert SKIP_PROBABILITY not in present

    def test_the_weight_fit_names_why_it_refused(self) -> None:
        rejection = fitted(unfittable()).rank.rejection

        assert rejection is not None
        assert "every difference is zero" in rejection
