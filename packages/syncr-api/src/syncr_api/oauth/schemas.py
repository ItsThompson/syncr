"""The wire shapes the token endpoint exchanges.

These are the one place in the api that does NOT extend
:class:`~syncr_api.core.schemas.WireModel`. Every other response is camelCase because the
frontend generates its types from this document and TypeScript reads ``lastSeenAt``. RFC 6749
fixes these member names as ``access_token``, ``token_type``, ``expires_in``, and
``refresh_token``, and a generic OAuth client looks for exactly those, so converting them
would produce a response nothing standard can read. The frontend consumes none of these:
the browser holds a cookie and never a token.

The access token and refresh token appear in this response and nowhere else. Neither is
stored as itself, neither is logged, and neither can be recovered from a row.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from syncr_api.core.scopes import format_scopes

if TYPE_CHECKING:
    from syncr_api.oauth.tokens import IssuedTokens


class TokenResponse(BaseModel):
    """RFC 6749 section 5.1: the token endpoint's success response."""

    access_token: str
    token_type: str
    expires_in: int
    refresh_token: str
    scope: str

    @classmethod
    def of(cls, issued: IssuedTokens) -> TokenResponse:
        """The response for a completed exchange."""
        return cls(
            access_token=issued.access_token,
            token_type=issued.token_type,
            expires_in=issued.expires_in,
            refresh_token=issued.refresh_token,
            scope=format_scopes(issued.scopes),
        )


class JsonWebKeySet(BaseModel):
    """RFC 7517: the published key set. Public material only.

    Typed loosely on purpose. A JWK's members depend on its key type, so pinning today's
    ES256 shape in a schema would make an algorithm change a contract change in two places.
    :meth:`~syncr_api.oauth.keys.SigningKey.as_public_jwk` is where the shape is decided.
    """

    keys: list[dict[str, str]] = Field(default_factory=list)
