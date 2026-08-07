"""The protocol errors the Authorization Server raises.

One error contract for the whole API. RFC 6749 section 5.2 specifies a
``{"error", "error_description"}`` body, and this file deliberately does not send that:
the api answers RFC 9457 problem details on every other route, the CLI maps a problem
``type`` onto its exit code, and a second error shape would mean the one client this
epoch ships has to parse two. The OAuth error code is carried in the ``type`` instead, so
nothing is lost that a caller reads: ``syncr:oauth-invalid-grant`` names the same
condition ``{"error": "invalid_grant"}`` does, and a future client that wants the RFC
shape can be given a translation at the edge rather than a second vocabulary here.

A 401 from a bearer-protected route carries ``WWW-Authenticate``, which RFC 6750
requires and which :class:`~syncr_api.core.errors.SyncrError` already has a seam for. A
token whose scope is too narrow is :class:`~syncr_api.core.errors.Forbidden`, raised by
:func:`~syncr_api.core.principal.require_scope`: that error already means insufficient
scope, and a second class for the same condition would be a second thing to keep in
step.

There is no class for a bad scope on the authorize request. That failure has a checked
redirect target by the time it is reached, so it is delivered there as
``error=invalid_scope`` in a query parameter, which is the RFC's spelling because it is
what a client parses.
"""

from __future__ import annotations

from syncr_api.core.credentials import BEARER_SCHEME
from syncr_api.core.errors import MalformedRequest, Unauthorized

# What a 401 tells the caller to present. The realm is the issuer's own name rather than a
# URL, because a URL here is a second place the issuer is stated.
_WWW_AUTHENTICATE = f'{BEARER_SCHEME.title()} realm="syncr"'


class InvalidRequest(MalformedRequest):
    """400: a required parameter is missing, unsupported, or malformed."""

    type = "syncr:oauth-invalid-request"
    title = "Invalid authorization request"


class InvalidClient(Unauthorized):
    """401: the client is unknown, so nothing about the request can be trusted."""

    type = "syncr:oauth-invalid-client"
    title = "Unknown client"


class InvalidGrant(MalformedRequest):
    """400: the presented code or refresh token is invalid, expired, or already used.

    Deliberately one error for four conditions. Telling a caller whether a code was
    expired or already consumed tells an attacker holding a stolen code which half of the
    replay defense caught them.
    """

    type = "syncr:oauth-invalid-grant"
    title = "Invalid grant"


class UnsupportedGrantType(MalformedRequest):
    """400: the token endpoint was asked for a grant type this server does not issue."""

    type = "syncr:oauth-unsupported-grant-type"
    title = "Unsupported grant type"


class InvalidToken(Unauthorized):
    """401: a presented bearer token is absent, malformed, expired, or for another audience."""

    type = "syncr:oauth-invalid-token"
    title = "Invalid access token"


def bearer_challenge() -> dict[str, str]:
    """The ``WWW-Authenticate`` header a 401 from a bearer-protected route carries."""
    return {"WWW-Authenticate": _WWW_AUTHENTICATE}
