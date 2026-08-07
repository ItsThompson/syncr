"""The corpora shared with other packages' suites.

They live in the source tree rather than in the test tree for the reason
:mod:`syncr_domain.fixtures` states: a fixture duplicated per package is a fixture that drifts, and
what these describe is the arithmetic this product cannot check any other way.

Nothing here imports a test framework. They are frozen values, so a consumer wraps one in whatever
fixture idiom its own suite uses.

| Fixture | Contents | Read by |
|---|---|---|
| ``maturity_corpus`` | outcomes sized to sit EITHER SIDE of each gate | the learning suite |
"""

from __future__ import annotations

from syncr_learning.fixtures.maturity_corpus import (
    AREA,
    OTHER_AREA,
    at_the_gate,
    below_the_gate,
    unfittable,
)

__all__ = ["AREA", "OTHER_AREA", "at_the_gate", "below_the_gate", "unfittable"]
