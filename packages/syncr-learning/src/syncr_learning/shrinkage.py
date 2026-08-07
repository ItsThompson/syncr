"""The shrinkage formula, the bound it puts on one outlier, and the interval it reports.

```
fitted = (n x empirical + k x prior) / (n + k)
```

Estimates blend with priors rather than jumping to the empirical mean at low sample counts, so
maturation feels like gradual sharpening instead of erratic swings. Section 11 works three cases at
``k = 10``: one observation leaves the value 91% prior, ten make it half and half, and fifty make it
83% observed.

## The bound on a single outlier, derived rather than asserted

Let ``m = n + k`` and ``A = n x empirical + k x prior``, so the fitted value is ``A / m``. Adding
one observation ``x``:

```
fitted(n+1) - fitted(n) = (A + x)/(m + 1) - A/m = (m x - A) / (m (m + 1))
                        = (x - fitted(n)) / (n + k + 1)
```

So **one observation moves the value by at most its distance from the current value, divided by ``n
+ k + 1``.** Two things follow, and they are the whole of the credibility rule:

- Every fitter CLAMPS each observation into a documented range, so that distance is bounded by the
  width of the range whatever the row said. A three-hour session against a one-hour plan is clamped
  rather than dropped: it did run long, and dropping it would discard the direction of the evidence
  along with its size.
- A parameter is only DISPLAYED at or above its gate, so ``n`` is at least the threshold whenever a
  value exists. The bound on a displayed parameter is therefore ``width / (threshold + k + 1)``,
  which is :func:`outlier_bound`, and it is computed from the three numbers rather than stated as a
  fourth that could disagree with them.
"""

from __future__ import annotations

from math import isfinite, sqrt
from statistics import fmean
from typing import TYPE_CHECKING

from scipy.stats import norm

from syncr_learning.config import CONFIDENCE, PRIOR_WEIGHT, ConfigError
from syncr_learning.results import FitResult

if TYPE_CHECKING:
    from collections.abc import Sequence


def clamped(value: float, *, low: float, high: float) -> float:
    """``value`` brought inside ``[low, high]``, which is what bounds one outlier's influence."""
    if low > high:
        raise ConfigError(f"a clamp range of [{low}, {high}] runs backwards")
    return min(max(value, low), high)


def shrunk(
    measurements: Sequence[float],
    *,
    prior: float,
    prior_weight: int = PRIOR_WEIGHT,
) -> FitResult:
    """The shrinkage formula over already-clamped measurements, with its interval.

    ``prior_weight`` is ``k``, and it is a parameter rather than a constant read here so a fitter
    can state its own. Every one takes the default today; section 11 says changing one must be a
    configuration change and this is the shape that makes it one.

    An empty list is the prior at a shrinkage weight of one, which is the correct reading rather
    than a refusal: no evidence means the whole of the figure is the prior. What a caller does about
    that is the GATE's decision, and the gate is what stops an unevidenced figure reaching the
    solver.
    """
    if prior_weight <= 0:
        raise ConfigError(
            f"a prior weight of {prior_weight} is how many observations the prior is worth, and a "
            "prior worth nothing is no prior at all: the formula would divide by the sample count"
        )
    if not isfinite(prior):
        raise ConfigError(f"a prior of {prior} is not a figure any evidence could move")
    samples = len(measurements)
    weight = prior_weight / (samples + prior_weight)
    if samples == 0:
        return FitResult(value=prior, samples=0, confidence=(prior, prior), shrinkage_weight=weight)
    empirical = fmean(measurements)
    value = (samples * empirical + prior_weight * prior) / (samples + prior_weight)
    return FitResult(
        value=value,
        samples=samples,
        confidence=_interval(value, measurements),
        shrinkage_weight=weight,
    )


def outlier_bound(
    *, low: float, high: float, threshold: int, prior_weight: int = PRIOR_WEIGHT
) -> float:
    """The most one further observation can move a DISPLAYED parameter of this shape.

    ``width / (threshold + k + 1)``, straight from the derivation in this module's own docstring.
    The threshold appears because a parameter below its gate is neither displayed nor applied, so
    the smallest sample count a displayed figure can have is the gate itself.
    """
    return (high - low) / (threshold + prior_weight + 1)


def _interval(value: float, measurements: Sequence[float]) -> tuple[float, float]:
    """A normal-approximation interval around the fitted value, at :data:`CONFIDENCE`.

    Centred on the FITTED value rather than on the empirical mean, because the fitted value is what
    is displayed and applied: an interval around a figure nothing reads would describe a different
    estimate from the one the row carries.

    The half-width is the standard error of the sample, so it narrows as evidence accumulates and is
    zero for a single observation. Zero is the honest reading there: one measurement has no spread,
    and inventing one would be inventing the uncertainty the interval exists to report.
    """
    samples = len(measurements)
    mean = fmean(measurements)
    variance = sum((one - mean) ** 2 for one in measurements) / samples
    half = float(norm.ppf(0.5 + CONFIDENCE / 2)) * sqrt(variance / samples)
    return (value - half, value + half)
