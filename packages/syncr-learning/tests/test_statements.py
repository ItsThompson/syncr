"""The sentences a maturity row states, and the one claiming a vector shipped when it had not.

The Learned screen is the trust surface: section 11 says the plain-language line is what builds
trust, more than the number beside it. So a sentence that says the opposite of what the artefact did
is worse than a missing one, and each of the six has both branches driven here.

The objective-weights sentence had **no coverage at all** and was false below the gate. It read "The
seven weights were refitted from 49 of your edits" on a row whose state was `collecting`, whose
value was `None`, and whose artefact shipped the incumbent, and it reached `GET /api/v1/learned`
verbatim.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from syncr_learning.config import (
    CHURN_TOLERANCE,
    CONTEXT_SWITCH_COST,
    DURATION_MULTIPLIER,
    OBJECTIVE_WEIGHTS,
    SKIP_PROBABILITY,
    THRESHOLDS,
    TIME_OF_DAY_FITNESS,
    TimeBucket,
)
from syncr_learning.fitting import fit_everything
from syncr_learning.fixtures import AREA, at_the_gate, below_the_gate
from syncr_learning.gates import parameter_of
from syncr_learning.statements import (
    churn_statement,
    duration_statement,
    fitness_statement,
    skip_statement,
    switch_statement,
    weights_statement,
)
from tests.test_rank import IN_FORCE

AT = datetime(2026, 2, 16, 3, 0, tzinfo=UTC)
WEIGHTS_THRESHOLD = THRESHOLDS[OBJECTIVE_WEIGHTS]


def sentence_for(parameter: str, observations: object) -> str:
    """The sentence the row for ``parameter`` states, taken from a whole composed fit."""
    fitted = fit_everything(
        observations,  # type: ignore[arg-type]
        in_force=IN_FORCE,
        switch_cost_in_force=1.0,
        churn_tolerance_in_force=3.0,
        area_names={str(AREA): "Fitness"},
        at=AT,
    )
    return next(
        row.plain_language for row in fitted.artifact.maturity if parameter_of(row) == parameter
    )


class TestTheObjectiveWeightsSentenceIsGatedWithTheVector:
    """The defect: a successful FIT is not a shipped VECTOR, and the sentence said it was."""

    def test_below_the_gate_the_sentence_does_not_claim_the_weights_were_refitted(self) -> None:
        # 49 pairs on a corpus the fit succeeds over. The vector is correctly withheld, so the
        # sentence must not say it shipped.
        said = sentence_for(OBJECTIVE_WEIGHTS, below_the_gate())

        assert "refitted" not in said
        assert f"{WEIGHTS_THRESHOLD - 1} of {WEIGHTS_THRESHOLD}" in said
        assert "collecting" in said

    def test_below_the_gate_the_artefact_and_the_sentence_agree(self) -> None:
        # The two halves of the same claim, asserted together, because either alone passes while the
        # other lies.
        fitted = fit_everything(
            below_the_gate(),
            in_force=IN_FORCE,
            switch_cost_in_force=1.0,
            churn_tolerance_in_force=3.0,
            area_names={str(AREA): "Fitness"},
            at=AT,
        )
        row = next(
            one for one in fitted.artifact.maturity if parameter_of(one) == OBJECTIVE_WEIGHTS
        )

        assert dict(fitted.artifact.term_weights) == IN_FORCE
        assert row.value is None
        assert row.state == "collecting"
        assert row.shrinkage_weight == 1.0
        assert "refitted" not in row.plain_language

    def test_at_the_gate_the_sentence_does_claim_it_and_the_vector_shipped(self) -> None:
        # The other direction. Without this the fix could simply never say "refitted".
        fitted = fit_everything(
            at_the_gate(),
            in_force=IN_FORCE,
            switch_cost_in_force=1.0,
            churn_tolerance_in_force=3.0,
            area_names={str(AREA): "Fitness"},
            at=AT,
        )
        row = next(
            one for one in fitted.artifact.maturity if parameter_of(one) == OBJECTIVE_WEIGHTS
        )

        assert dict(fitted.artifact.term_weights) != IN_FORCE
        assert row.state == "ready"
        assert row.value is not None
        assert row.shrinkage_weight == 0.0
        assert "were refitted" in row.plain_language
        assert f"{WEIGHTS_THRESHOLD} of your edits" in row.plain_language

    def test_a_refused_fit_says_it_was_refused_and_why(self) -> None:
        # The third branch, which the gate does not reach: the corpus is large enough and the fit
        # refuses it anyway.
        said = weights_statement(
            samples=80,
            threshold=WEIGHTS_THRESHOLD,
            rejection="the fit produced a negative weight for staleness",
            ranked=None,
        )

        assert "were not changed" in said
        assert "negative weight for staleness" in said
        assert "refitted" not in said

    def test_the_three_branches_are_mutually_exclusive(self) -> None:
        # A refused fit that is also below the gate must say ONE thing. The rejection wins, because
        # it is the more specific answer to "why did the weights not move".
        said = weights_statement(
            samples=3,
            threshold=WEIGHTS_THRESHOLD,
            rejection="no pair carries a preference",
            ranked=None,
        )

        assert "were not changed" in said
        assert "collecting" not in said


class TestEveryOtherSentenceHasBothBranches:
    @pytest.mark.parametrize(
        "parameter",
        [
            DURATION_MULTIPLIER,
            TIME_OF_DAY_FITNESS,
            SKIP_PROBABILITY,
            CONTEXT_SWITCH_COST,
            CHURN_TOLERANCE,
        ],
    )
    def test_a_collecting_row_says_collecting_is_normal_and_quotes_its_progress(
        self, parameter: str
    ) -> None:
        said = sentence_for(parameter, below_the_gate())

        assert "Still collecting, which is normal." in said
        assert f"of {THRESHOLDS[parameter]}" in said

    @pytest.mark.parametrize(
        "parameter",
        [
            DURATION_MULTIPLIER,
            TIME_OF_DAY_FITNESS,
            SKIP_PROBABILITY,
            CONTEXT_SWITCH_COST,
            CHURN_TOLERANCE,
        ],
    )
    def test_a_ready_row_says_something_about_the_figure_rather_than_the_progress(
        self, parameter: str
    ) -> None:
        said = sentence_for(parameter, at_the_gate())

        assert "Still collecting" not in said
        assert "of " + str(THRESHOLDS[parameter]) not in said

    def test_the_duration_sentence_quotes_both_medians_and_the_direction(self) -> None:
        said = duration_statement(
            "Leetcode",
            multiplier=1.37,
            planned_median=60,
            actual_median=82,
            samples=14,
            threshold=12,
        )

        assert "You estimate 60m for Leetcode" in said
        assert "82m" in said
        assert "longer than planned" in said

    def test_the_duration_sentence_says_shorter_when_it_is_shorter(self) -> None:
        # Both directions of the one branch inside the ready sentence.
        said = duration_statement(
            "Sleep", multiplier=0.8, planned_median=480, actual_median=400, samples=14, threshold=12
        )

        assert "shorter than planned" in said

    def test_the_fitness_sentence_names_both_hours_as_hours_of_a_day(self) -> None:
        said = fitness_statement("Fitness", best_hour=7, worst_hour=22, samples=40, threshold=30)

        assert "07:00" in said
        assert "22:00" in said

    def test_the_skip_sentence_quotes_a_share_out_of_ten(self) -> None:
        said = skip_statement(
            "Fitness", TimeBucket.MORNING, probability=0.4, samples=9, threshold=6
        )

        assert "about 4 times in 10" in said
        assert "morning" in said

    def test_the_switch_sentence_quotes_minutes(self) -> None:
        said = switch_statement(minutes=12.4, samples=25, threshold=20)

        assert "about 12 more minutes" in said

    def test_the_churn_sentence_quotes_moves(self) -> None:
        said = churn_statement(moves=8.2, samples=25, threshold=20)

        assert "about 8 moves" in said
