"""``FitResult``: what one fitter answers with, and what "not fittable" answers instead.

Four numbers, and the fourth is the one the Learned screen shows as a quantity: ``shrinkage_weight``
is how much of ``value`` is still the prior, so "still collecting" is a figure rather than a badge.

**Absence is a value here.** A fitter whose data cannot support a figure returns
:meth:`FitResult.unfittable`, which carries the sample count and no value. That is not the same as a
figure at the prior: a prior is a claim the fitter is making, and there are corpora it must refuse
to make one from -- a difference between two populations where one is empty, a curve over six hours
of
the day. Read as "the prior", either would ship a number nobody fitted.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from syncr_learning.config import ConfigError


@dataclass(frozen=True, slots=True, kw_only=True)
class FitResult:
    """One fitted figure, the evidence behind it, and how much of it is still the prior."""

    value: float | None
    samples: int
    confidence: tuple[float, float] | None
    shrinkage_weight: float

    def __post_init__(self) -> None:
        if self.samples < 0:
            raise ConfigError(f"a fit over {self.samples} observations counted something backwards")
        if not 0.0 <= self.shrinkage_weight <= 1.0:
            raise ConfigError(
                f"a shrinkage weight of {self.shrinkage_weight} is not a share of the value: it is "
                "how much of the figure is still the prior, which runs from 0 to 1"
            )
        if self.value is not None and not isfinite(self.value):
            raise ConfigError(f"a fitted value of {self.value} is not a number a solver can apply")
        if (self.value is None) != (self.confidence is None):
            raise ConfigError(
                "a fit states a value and an interval together or neither: an interval around no "
                "value bounds nothing, and a value with no interval hides how little is behind it"
            )
        if self.confidence is not None and self.confidence[0] > self.confidence[1]:
            raise ConfigError(f"a confidence interval of {self.confidence} runs backwards")

    @property
    def is_fitted(self) -> bool:
        """Whether this result carries a figure at all."""
        return self.value is not None

    @classmethod
    def unfittable(cls, samples: int) -> FitResult:
        """A refusal: this many observations, and nothing a solver could apply.

        ``shrinkage_weight`` is one, because a result with no value is entirely prior: nothing of
        the
        evidence reached a figure, so the honest reading of "how much of the value is the prior" is
        all of it.
        """
        return cls(value=None, samples=samples, confidence=None, shrinkage_weight=1.0)
