"""The refusal a retry arriving mid-flight receives.

Its own class rather than a bare :class:`~syncr_api.core.errors.Conflict` carrying a header,
because the wait is a property of this condition rather than of the request that hit it: the
error hierarchy renders ``Retry-After`` from ``retry_after_seconds``, the way
:class:`~syncr_api.core.errors.RateLimited` and
:class:`~syncr_api.core.errors.DependencyUnavailable` do, and a named type is what a route's
response set can describe.
"""

from __future__ import annotations

from syncr_api.core.errors import Conflict
from syncr_api.idempotency.config import IN_FLIGHT_RETRY_AFTER_SECONDS


class RequestInFlight(Conflict):
    """409: a request with this idempotency key has not answered yet."""

    type = "syncr:idempotency-request-in-flight"
    title = "Request already in flight"
    retry_after_seconds = IN_FLIGHT_RETRY_AFTER_SECONDS
