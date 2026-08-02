"""The base of every domain invariant violation.

A domain error means data reached an entity or an arithmetic function that its
invariants forbid: a zero-length interval, a wall time carrying a zone, two travel
overrides covering one date. It is not a transport concern, so this package maps
nothing to a status code; the HTTP layer catches these and maps them once.

`ValueError` is the base because every one of them is a bad argument, so a caller
that knows nothing about syncr still catches it in the category it belongs to.
"""

from __future__ import annotations


class DomainError(ValueError):
    """A domain invariant was violated."""
