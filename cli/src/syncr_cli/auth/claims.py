"""The claims an access token carries, read for display and for nothing else.

**This is not verification.** A resource server verifies a token's signature against the
published key set before trusting a claim; this client is the token's holder, not its verifier,
and it received the token over its own TLS connection to the Authorization Server. So the payload
is decoded to answer "who am I and what may I do", and no decision here depends on it: the
authorization decision is the api's, on every request, against a signature.

Decoded rather than depending on a JWT library, because verification is the only thing a library
would add and verification is the thing this package must not appear to be doing.
"""

from __future__ import annotations

import json
from base64 import urlsafe_b64decode
from dataclasses import dataclass
from typing import Any, Final, Self

from syncr_cli.errors import MalformedResponse

# The claims beyond the registered ones. `tid` carries the tenant, because a subject alone does
# not name one.
TENANT_CLAIM: Final = "tid"
SCOPE_CLAIM: Final = "scope"
CLIENT_CLAIM: Final = "client_id"

_SEGMENTS: Final = 3


@dataclass(frozen=True, slots=True)
class TokenClaims:
    """Who an access token is for, and what it was granted.

    Every member is optional because this is a display reading of someone else's document: a
    claim this build does not find is reported as absent rather than faulted over, which keeps
    ``auth status`` useful against a deployment whose claim set has grown.
    """

    subject: str | None
    tenant_id: str | None
    client_id: str | None
    scopes: tuple[str, ...]
    expires_at: int | None

    @classmethod
    def of(cls, token: str) -> Self:
        payload = _payload(token)
        raw_scope = payload.get(SCOPE_CLAIM)
        return cls(
            subject=_string(payload, "sub"),
            tenant_id=_string(payload, TENANT_CLAIM),
            client_id=_string(payload, CLIENT_CLAIM),
            scopes=tuple(raw_scope.split()) if isinstance(raw_scope, str) else (),
            expires_at=payload.get("exp") if isinstance(payload.get("exp"), int) else None,
        )


def _payload(token: str) -> dict[str, Any]:
    """The middle segment of a JWS, decoded.

    A value that is not three dot-separated segments is refused: it is not an access token, and
    reporting a principal from it would be reporting a principal from nothing.
    """
    segments = token.split(".")
    if len(segments) != _SEGMENTS:
        raise MalformedResponse(
            "the access token the API issued is not a three-part JWS, so this CLI cannot say who "
            "it is for. Nothing was changed."
        )
    padded = segments[1] + "=" * (-len(segments[1]) % 4)
    try:
        decoded = json.loads(urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, UnicodeDecodeError) as error:
        raise MalformedResponse(
            "the access token the API issued carries no readable claim set. Nothing was changed."
        ) from error
    if not isinstance(decoded, dict):
        raise MalformedResponse(
            "the access token the API issued carries a claim set that is not an object."
        )
    return decoded


def _string(payload: dict[str, Any], claim: str) -> str | None:
    value = payload.get(claim)
    return value if isinstance(value, str) else None
