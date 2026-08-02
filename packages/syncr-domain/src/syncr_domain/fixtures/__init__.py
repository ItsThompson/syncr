"""Fixtures shared across packages.

They live in the source tree rather than in a test tree because the api's projector
tests and the domain's own tests must assert against the *same* literals. A fixture
duplicated per package is a fixture that drifts, and the arithmetic these describe is
the one thing this product cannot check any other way.

Nothing here imports a test framework. They are frozen literals, so a consumer wraps
one in whatever fixture idiom its own suite uses.
"""

from __future__ import annotations
