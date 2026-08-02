"""The origin check that stands in for a CSRF token.

The session cookie is `SameSite=Lax`, so a browser already withholds it from a
cross-site unsafe request. This is the second half of that rule rather than a
replacement for it: it rejects an unsafe request whose stated origin is not one this
deployment serves, which covers the cases `Lax` does not, and it costs a header
comparison.

No token pattern is added. The SPA is same-origin behind the tunnel, so a
synchronizer token would add a mechanism, a storage decision, and a rotation question
while excluding no attacker that these two rules do not already exclude.

`Origin` is what browsers send on every unsafe request. `Referer` is the documented
fallback for the cases where a browser historically omitted `Origin` on a same-origin
request; only its origin component is read, never its path, which is a URL the user
was on and therefore not something to compare or log.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from collections.abc import Iterable

# Methods that can change state, and therefore the ones worth forging. A safe method
# needs no check: reading with someone else's cookie discloses nothing to an attacker
# who cannot read the response.
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def is_origin_trusted(
    method: str, *, origin: str | None, referer: str | None, allowed: Iterable[str]
) -> bool:
    """True when this request may change state from where it says it came from."""
    if method.upper() not in UNSAFE_METHODS:
        return True
    stated = _normalize(origin) or _origin_of(referer)
    if stated is None:
        return False
    return stated in {_normalize(candidate) for candidate in allowed}


def _origin_of(url: str | None) -> str | None:
    """The scheme-and-host origin of a URL, discarding path and query."""
    if not url:
        return None
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


def _normalize(origin: str | None) -> str | None:
    """An origin in the one form comparisons are made in.

    A configured value may carry a trailing slash or a capitalized host; a header
    value will not. Both sides go through this, so a deployment is not rejected for a
    slash.
    """
    if not origin:
        return None
    return _origin_of(origin) or origin.strip().rstrip("/").lower()
