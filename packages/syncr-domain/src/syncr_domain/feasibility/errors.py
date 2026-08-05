"""The one rejection the feasibility vocabulary raises."""

from __future__ import annotations

from syncr_domain.errors import DomainError


class FeasibilityError(DomainError):
    """A verdict, a shortfall, or a probe input breaks a rule that makes it readable.

    Every use of this is a producer fault rather than a user's: the probe runs on the request
    path with no degraded mode, so anything raised here has to be unreachable from stored data
    and reachable only from a caller that built a value the vocabulary does not allow.
    """
