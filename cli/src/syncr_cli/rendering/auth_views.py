"""What the three ``auth`` commands answer with, in both renderings.

Each is a payload with no body group: nothing an authorization command says belongs below a
verdict, because none of them changes a plan. The three share that emptiness and the way they print
an instant with every other payload that carries no week, so both answers come off
:class:`~syncr_cli.rendering.views.PlainView`.

**No credential appears in either rendering.** The principal, the scopes, and where the token is
kept are what these report. The refresh token and the access token are reported by their existence
and never by their value, which is what a test asserts by searching both streams for the values a
flow actually minted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from syncr_cli.rendering.views import PlainView

if TYPE_CHECKING:
    from syncr_cli.auth.claims import TokenClaims
    from syncr_cli.wire.reading import JsonMapping

# How wide the label column is, so three lines of a status read as a table rather than as prose.
_LABEL: Final = 10

# What a status prints when the token carries no expiry claim. A rendered `None` would read as a
# value rather than as its absence.
UNKNOWN_EXPIRY: Final = "an unstated time"


@dataclass(frozen=True, slots=True)
class LoginView(PlainView):
    """What a completed authorization reports: the scopes granted, and where the token is."""

    api_url: str
    scopes: tuple[str, ...]
    token_location: str
    fell_back: bool

    @property
    def payload(self) -> JsonMapping:
        return {
            "apiUrl": self.api_url,
            "scopes": list(self.scopes),
            "tokenStore": self.token_location,
            "tokenStoreIsFallback": self.fell_back,
        }

    def header_lines(self) -> list[str]:
        return [
            f"{'authorized':<{_LABEL}} {self.api_url}",
            f"{'scopes':<{_LABEL}} {' '.join(self.scopes)}",
            f"{'token':<{_LABEL}} {self.token_location}",
        ]


@dataclass(frozen=True, slots=True)
class LogoutView(PlainView):
    """What a logout reports: whether there was a grant to revoke, and that it is gone."""

    api_url: str
    revoked: bool

    @property
    def payload(self) -> JsonMapping:
        return {"apiUrl": self.api_url, "revoked": self.revoked}

    def header_lines(self) -> list[str]:
        if self.revoked:
            return [
                f"{'revoked':<{_LABEL}} {self.api_url}",
                f"{'token':<{_LABEL}} removed from this machine",
            ]
        return [
            f"{'nothing':<{_LABEL}} this machine held no authorization for {self.api_url}",
        ]


@dataclass(frozen=True, slots=True)
class StatusView(PlainView):
    """Who this machine is authenticated as, what it may do, and where its token lives."""

    api_url: str
    claims: TokenClaims
    token_location: str
    fell_back: bool

    @property
    def payload(self) -> JsonMapping:
        return {
            "apiUrl": self.api_url,
            "tenantId": self.claims.tenant_id,
            "userId": self.claims.subject,
            "clientId": self.claims.client_id,
            "scopes": list(self.claims.scopes),
            "accessTokenExpiresAt": self.expires_at,
            "tokenStore": self.token_location,
            "tokenStoreIsFallback": self.fell_back,
        }

    def header_lines(self) -> list[str]:
        return [
            f"{'api':<{_LABEL}} {self.api_url}",
            f"{'principal':<{_LABEL}} tenant {self.claims.tenant_id} user {self.claims.subject}",
            f"{'scopes':<{_LABEL}} {' '.join(self.claims.scopes)}",
            f"{'client':<{_LABEL}} {self.claims.client_id}",
            f"{'token':<{_LABEL}} {self.token_location}, "
            f"valid until {self.expires_at or UNKNOWN_EXPIRY}",
        ]

    @property
    def expires_at(self) -> str | None:
        """When the access token this invocation holds stops verifying, as an RFC 3339 instant.

        The one instant this package authors rather than passes through, so it is the one place the
        wire's own convention has to be applied here: UTC with an explicit offset, like every other
        instant a caller reads, so an agent comparing it with a span from the api compares two
        values of one shape.
        """
        if self.claims.expires_at is None:
            return None
        return datetime.fromtimestamp(self.claims.expires_at, tz=UTC).isoformat()
