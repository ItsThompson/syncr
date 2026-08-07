"""Learning to rank the seven objective weights from pairwise pins. The one model in this product.

For every edit, the user preferred ``accepted`` over ``proposed`` in a known context. The feature is
the difference between the two placements under the seven objective terms, already measured and
stored at the edit, and the fit produces weights under which the accepted placement scores better
than the proposed one across the corpus.

Output is **seven floats, the same seven the solver consumes**. No translation layer, so there is
nothing that can diverge between what is learned and what is used.

## Standard pairwise ranking, and why the label is mirrored

A pair contributes ``x = -difference``, so a positive score means the accepted side is cheaper.
Fitted against a constant label of one, any classifier can reach zero loss by scaling a single
coefficient: the label carries no information, so the fit is unidentified. Each pair is therefore
emitted twice, once as ``(x, 1)`` and once as ``(-x, 0)``, which is the standard construction and
makes the two classes exactly balanced by design rather than by luck.

## Why the fit is unconstrained, and rejected afterwards

A negative weight would make the solver actively seek the cost the term measures, which is never the
intent. A non-negative solver would make that unreachable and would therefore make the rejection
unreachable too: the rule "a fit that would produce a negative weight is rejected and logged" would
be a guard that cannot see what it forbids. So the fit is unconstrained and the whole vector is
refused if any component comes back negative.

## What is refused, and why each refusal is a measurement rather than a policy

- A corpus with no usable pair. Nothing to rank.
- A pair whose difference is all zeros. The two placements measured identically, so the pair states
  no preference; kept in the corpus and dropped here, because the sample count that decides the gate
  is taken after the drop.
- A term whose difference is zero in EVERY pair. The corpus contains no evidence about it, so any
  weight fits equally well, and a fitted number would be an artefact of the optimiser's start point.
- A vector that ranks the corpus no better than the weights in force. A learned artefact that is
  worse than the current one must not ship, and that is a comparison rather than an assumption: both
  vectors are scored on the same pairs and the incumbent keeps the tie.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from sklearn.linear_model import LogisticRegression

from syncr_learning.config import OBJECTIVE_TERMS

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syncr_learning.observations import RankExample

# The optimiser's regularisation strength, and it is a real choice rather than a default left in
# place. `C` is the inverse of it, so a large C is a nearly-unregularised fit: the corpus is
# hundreds of examples over seven features, so the fit is not short of data per parameter, and heavy
# regularisation would pull every weight toward zero, which is the direction the negative-weight
# rejection already guards. A finite value rather than none, so a perfectly separable corpus
# terminates instead of growing its coefficients without bound.
_REGULARISATION_INVERSE = 100.0

# How many passes the optimiser may take. Reached rather than converged is a failed fit, not a
# quietly worse one: `converged` reports it and the job refuses the vector.
_MAX_ITERATIONS = 1000


@dataclass(frozen=True, slots=True, kw_only=True)
class RankFit:
    """What the weight fit answers with: a vector, or a refusal that names itself.

    ``weights`` is ``None`` for every refusal, and ``rejection`` says which. Two fields rather than
    an exception, because a refused fit is an ordinary outcome of a young corpus and the run reports
    it as a metric and carries on with the weights in force.
    """

    weights: Mapping[str, float] | None
    samples: int
    rejection: str | None
    ranked_correctly: float | None
    """The share of pairs the fitted vector ranks the right way, or nothing because there is
    none."""

    def __post_init__(self) -> None:
        if (self.weights is None) == (self.rejection is None):
            raise ValueError(
                "a rank fit answers with a vector or with the reason there is none, never with "
                "both and never with neither"
            )

    @classmethod
    def rejected(cls, reason: str, *, samples: int) -> RankFit:
        return cls(weights=None, samples=samples, rejection=reason, ranked_correctly=None)


def fit_objective_weights(
    examples: Sequence[RankExample], *, in_force: Mapping[str, float]
) -> RankFit:
    """Seven floats such that the accepted placement scores better, or the reason there are none.

    ``in_force`` is the vector the solver is using now. It is the comparison the last refusal is
    stated against: a fitted vector that ranks this corpus no better than the incumbent does not
    ship.
    """
    usable = [one for one in examples if not one.is_degenerate]
    if not usable:
        return RankFit.rejected(
            f"no pair in {len(examples)} carries a preference: every difference is zero, so the "
            "corpus states which placement the user chose and nothing about why",
            samples=0,
        )
    inert = _terms_no_pair_measures(usable)
    if inert:
        return RankFit.rejected(
            f"{', '.join(inert)} measured identically in every one of {len(usable)} pairs, so any "
            "weight fits the corpus equally well and the fitted one would be the optimiser's "
            "starting point rather than the user's preference",
            samples=len(usable),
        )
    fitted, converged = _pairwise_logistic(usable)
    if not converged:
        return RankFit.rejected(
            f"the fit did not converge in {_MAX_ITERATIONS} passes over {len(usable)} pairs",
            samples=len(usable),
        )
    negative = sorted(term for term, weight in fitted.items() if weight < 0)
    if negative:
        return RankFit.rejected(
            f"the fit produced a negative weight for {', '.join(negative)}, and a negative weight "
            "would make the solver actively seek the cost that term measures",
            samples=len(usable),
        )
    fitted_score = ranked_correctly(fitted, usable)
    incumbent_score = ranked_correctly(in_force, usable)
    if fitted_score <= incumbent_score:
        return RankFit.rejected(
            f"the fitted vector ranks {fitted_score:.3f} of {len(usable)} pairs correctly and the "
            f"weights in force rank {incumbent_score:.3f}, so shipping it would replace the "
            "current artefact with a worse one",
            samples=len(usable),
        )
    return RankFit(
        weights=fitted,
        samples=len(usable),
        rejection=None,
        ranked_correctly=fitted_score,
    )


def ranked_correctly(weights: Mapping[str, float], examples: Sequence[RankExample]) -> float:
    """The share of pairs this vector prices the user's own choice below the solver's proposal.

    A pair the vector prices EQUALLY is not ranked correctly. It expresses no preference under those
    weights, and counting it would let a vector of all zeros score one.
    """
    if not examples:
        return 0.0
    correct = sum(
        1
        for one in examples
        if sum(weights.get(term, 0.0) * one.difference[term] for term in OBJECTIVE_TERMS) < 0
    )
    return correct / len(examples)


def _terms_no_pair_measures(examples: Sequence[RankExample]) -> list[str]:
    """The terms whose difference is exactly zero in every pair."""
    return [
        term for term in OBJECTIVE_TERMS if all(one.difference[term] == 0.0 for one in examples)
    ]


def _pairwise_logistic(examples: Sequence[RankExample]) -> tuple[dict[str, float], bool]:
    """The mirrored pairwise fit, and whether the optimiser converged.

    No intercept: a bias would be a cost the objective charges every plan alike, which is not a term
    the solver holds and not a number the weight set has a field for.
    """
    preferred = np.array(
        [[-one.difference[term] for term in OBJECTIVE_TERMS] for one in examples], dtype=float
    )
    features = np.vstack([preferred, -preferred])
    labels = np.concatenate([np.ones(len(examples)), np.zeros(len(examples))])
    model = LogisticRegression(
        fit_intercept=False, C=_REGULARISATION_INVERSE, max_iter=_MAX_ITERATIONS
    )
    model.fit(features, labels)
    converged = bool(np.all(np.asarray(model.n_iter_) < _MAX_ITERATIONS))
    return dict(
        zip(OBJECTIVE_TERMS, (float(one) for one in model.coef_[0]), strict=True)
    ), converged
