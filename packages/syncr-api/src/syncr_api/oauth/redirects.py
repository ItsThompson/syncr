"""Redirect-URI validation. Loopback only, for the one client that exists.

The redirect URI is where the authorization code is delivered, so it is the one parameter
a client does not get to choose freely: whoever controls the redirect controls the code.
A requested URI is therefore matched against the client's registered list, and the CLI
client is registered as loopback only, so nothing that is not a process on the user's own
machine can receive a syncr authorization code.

The port is excluded from the loopback comparison, per RFC 8252 section 7.3. The CLI binds
an ephemeral port per run, which is what stops two concurrent runs from colliding and what
avoids asking the user to keep a fixed port free; requiring an exact port match would mean
either registering every port or registering one and losing that property.

Everything else about a loopback URI is compared exactly: the scheme, the host, and the
path. A registered ``http://127.0.0.1/callback`` does not admit
``http://127.0.0.1/anything-else``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from collections.abc import Iterable

# The three spellings of "this machine". `localhost` is included because a browser opened
# by the CLI may be handed either form, but it is the weakest of the three: it resolves
# through the host's name service, so RFC 8252 recommends the literal addresses. The CLI
# registers the two literals and this set is what admits a redirect at all.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
LOOPBACK_SCHEME = "http"


def is_loopback(uri: str) -> bool:
    """True for an ``http`` URI whose host is this machine."""
    parts = urlsplit(uri)
    return parts.scheme == LOOPBACK_SCHEME and (parts.hostname or "") in LOOPBACK_HOSTS


def is_registered_redirect(
    requested: str, registered: Iterable[str], *, loopback_only: bool
) -> bool:
    """True when ``requested`` may receive this client's authorization code.

    ``loopback_only`` is the client's own restriction rather than a global rule, so a
    later client that legitimately redirects to an https URL is registered with it off and
    matched exactly. A loopback-only client cannot be handed a non-loopback URI at all,
    even one that appears in its registered list, so a registration mistake cannot widen
    it.
    """
    candidates = list(registered)
    if is_loopback(requested):
        target = _loopback_identity(requested)
        return any(
            is_loopback(candidate) and _loopback_identity(candidate) == target
            for candidate in candidates
        )
    if loopback_only:
        return False
    return requested in candidates


def _loopback_identity(uri: str) -> tuple[str, str, str]:
    """The scheme, host, and path of a loopback URI, discarding the ephemeral port."""
    parts = urlsplit(uri)
    return parts.scheme, (parts.hostname or ""), parts.path
