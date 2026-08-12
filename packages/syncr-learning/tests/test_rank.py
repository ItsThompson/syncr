"""Learning to rank: the seven floats, the five refusals, and the corpora built to be unfittable.

Every refusal here is a corpus a real nightly run will meet, and each one is the case where a fit
that produced a number anyway would be worse than no fit at all. The comparison against the
incumbent is the last of them and the most important: a learned artefact worse than the current one
must not ship.
"""

from __future__ import annotations

import pytest

from syncr_learning.config import OBJECTIVE_TERMS
from syncr_learning.observations import RankExample
from syncr_learning.rank import fit_objective_weights, ranked_correctly

# The version-1 hand-tuned vector, restated here as the incumbent every fit is compared against.
# `test_solver_agreement.py` crosses the api's `P0_WEIGHTS` against this package's two scalar priors
# and against the term names, but nothing crosses these seven values, so a change to either copy has
# to be made in both by hand.
IN_FORCE = {
    "deadline_risk": 10.0,
    "budget_deviation": 3.0,
    "time_of_day_misfit": 2.0,
    "fragmentation": 1.5,
    "churn": 4.0,
    "context_switch": 1.0,
    "staleness": 1.5,
}


def example(**differences: float) -> RankExample:
    """One pair. Any term not named measured identically on both sides."""
    return RankExample(difference={**dict.fromkeys(OBJECTIVE_TERMS, 0.0), **differences})


def rotating(count: int, *, spread: float = 0.3) -> list[RankExample]:
    """A corpus in which every term improves in some pairs and is a cost in others.

    This is the shape a real corpus has: a user's edits are not all about one term. Every term both
    helps and hurts somewhere, so a strictly positive vector can rank the whole corpus, and the fit
    is identified in all seven directions rather than in one.
    """
    terms = list(OBJECTIVE_TERMS)
    return [
        example(
            **{terms[index % len(terms)]: -1.0 - (index % 3) * 0.1},
            **{terms[(index + 1) % len(terms)]: spread + (index % 4) * 0.05},
        )
        for index in range(count)
    ]


def always_costly(term: str, count: int) -> list[RankExample]:
    """``rotating``, plus one term the user's choice only ever WORSENS, by a varying amount.

    Varying, so the term is not constant and the inert-term refusal does not fire first: this corpus
    has to reach the fit for the negative-weight rejection to be the thing it tests.
    """
    return [
        RankExample(difference={**one.difference, term: 0.4 + (index % 5) * 0.15})
        for index, one in enumerate(rotating(count))
    ]


class TestTheSevenFloats:
    def test_a_corpus_every_term_varies_in_fits_seven_non_negative_weights(self) -> None:
        fit = fit_objective_weights(rotating(70), in_force=IN_FORCE)

        assert fit.weights is not None, fit.rejection
        assert set(fit.weights) == set(OBJECTIVE_TERMS)
        assert all(value >= 0 for value in fit.weights.values())

    def test_the_output_is_seven_floats_and_nothing_else(self) -> None:
        # No translation layer: these are the same seven names the solver reads, so there is nothing
        # between what is learned and what is used.
        fit = fit_objective_weights(rotating(70), in_force=IN_FORCE)

        assert fit.weights is not None, fit.rejection
        assert len(fit.weights) == 7
        assert all(isinstance(value, float) for value in fit.weights.values())

    def test_the_fitted_vector_ranks_more_of_the_corpus_than_the_incumbent(self) -> None:
        # The comparison is a measurement rather than an assumption, and it is the reason the fit is
        # allowed to ship at all.
        examples = rotating(70)
        fit = fit_objective_weights(examples, in_force=IN_FORCE)

        assert fit.weights is not None, fit.rejection
        assert fit.ranked_correctly is not None
        assert fit.ranked_correctly > ranked_correctly(IN_FORCE, examples)

    def test_a_negative_weight_is_rejected_and_the_reason_names_the_term(self) -> None:
        # A negative weight would make the solver actively seek the cost the term measures. The fit
        # is deliberately unconstrained so this refusal is reachable at all: a non-negative solver
        # would make the rule a guard that cannot see what it forbids.
        #
        # The corpus: one term the user's choice only ever worsens, by a varying amount. The only
        # vector that ranks such a corpus better weighs that term below zero.
        fit = fit_objective_weights(always_costly("staleness", 70), in_force=IN_FORCE)

        assert fit.weights is None
        assert fit.rejection is not None
        assert "negative weight" in fit.rejection
        assert "staleness" in fit.rejection


class TestTheCorporaThatCannotBeFitted:
    def test_an_empty_corpus_is_refused(self) -> None:
        fit = fit_objective_weights([], in_force=IN_FORCE)

        assert fit.weights is None
        assert fit.samples == 0
        assert fit.rejection is not None

    def test_a_corpus_of_only_degenerate_pairs_is_refused_and_counts_none(self) -> None:
        # A pin that keeps a block where it already is compares a plan with itself. Counted as
        # samples these would clear a gate on a corpus with no signal in it.
        toggles = [example() for _ in range(80)]
        fit = fit_objective_weights(toggles, in_force=IN_FORCE)

        assert fit.weights is None
        assert fit.samples == 0
        assert fit.rejection is not None
        assert "every difference is zero" in fit.rejection

    def test_a_degenerate_pair_beside_real_ones_is_dropped_from_the_count(self) -> None:
        mixed = [*rotating(70), *(example() for _ in range(20))]
        fit = fit_objective_weights(mixed, in_force=IN_FORCE)

        assert fit.samples == 70

    def test_a_term_that_is_identical_in_every_pair_is_refused_rather_than_invented(self) -> None:
        # Any weight fits such a term equally well, so a fitted number would be the optimiser's
        # starting point rather than the user's preference.
        only_two_terms_move = [
            example(deadline_risk=-1.0, churn=0.5, budget_deviation=0.5, fragmentation=0.5)
            for _ in range(60)
        ]
        fit = fit_objective_weights(only_two_terms_move, in_force=IN_FORCE)

        assert fit.weights is None
        assert fit.rejection is not None
        assert "measured identically in every one of 60 pairs" in fit.rejection
        for silent in ("time_of_day_misfit", "context_switch", "staleness"):
            assert silent in fit.rejection

    def test_a_corpus_of_one_pair_is_refused_for_the_terms_it_says_nothing_about(self) -> None:
        # A single pair moves at most a few terms, so the rest carry no evidence. The refusal names
        # them rather than fitting six numbers from one row.
        fit = fit_objective_weights([example(churn=-1.0)], in_force=IN_FORCE)

        assert fit.weights is None
        assert fit.rejection is not None

    def test_a_corpus_no_vector_can_rank_better_than_the_incumbent_is_refused(self) -> None:
        # The incumbent already ranks every pair, so no fitted vector can improve on it. Shipping
        # one would replace the current artefact with an equal-or-worse one for no reason.
        already_right = [example(**dict.fromkeys(OBJECTIVE_TERMS, -1.0)) for _ in range(60)]
        fit = fit_objective_weights(already_right, in_force=IN_FORCE)

        assert ranked_correctly(IN_FORCE, already_right) == 1.0
        assert fit.weights is None
        assert fit.rejection is not None
        assert "worse one" in fit.rejection


class TestRankedCorrectly:
    def test_a_pair_the_vector_prices_equally_is_not_ranked_correctly(self) -> None:
        # Otherwise a vector of all zeros would score one on every corpus.
        zeros = dict.fromkeys(OBJECTIVE_TERMS, 0.0)

        assert ranked_correctly(zeros, rotating(14)) == 0.0

    def test_an_empty_corpus_scores_nothing_rather_than_everything(self) -> None:
        assert ranked_correctly(IN_FORCE, []) == 0.0

    def test_the_score_is_the_share_of_pairs_priced_the_user_s_way(self) -> None:
        half_right = [
            *[example(churn=-1.0) for _ in range(5)],
            *[example(churn=1.0) for _ in range(5)],
        ]

        assert ranked_correctly(IN_FORCE, half_right) == pytest.approx(0.5)


class TestTheAnswerShape:
    def test_a_fit_answers_with_a_vector_or_a_reason_and_never_with_both(self) -> None:
        with pytest.raises(ValueError, match="never with both"):
            _both()


def _both() -> object:
    from syncr_learning.rank import RankFit

    return RankFit(
        weights=dict.fromkeys(OBJECTIVE_TERMS, 1.0),
        samples=1,
        rejection="and a reason",
        ranked_correctly=1.0,
    )
