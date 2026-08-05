"""RFC 8414 discovery: where this deployment's OAuth endpoints are.

Every endpoint URL is read from the deployment rather than compiled in, because this CLI ships
separately from the server: a deployment behind a different hostname is discovered, not
reconfigured. One document, fetched once per invocation that needs a credential.

**Two claims are checked rather than assumed.** The document must name the three endpoints this
client uses, and it must advertise ``S256``. A server that advertised ``plain`` would be inviting
a client to build the weak mode, and this one would rather say so than proceed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Self

from syncr_cli.auth.pkce import CODE_CHALLENGE_METHOD_S256
from syncr_cli.errors import MalformedResponse
from syncr_cli.wire.reading import mapping, text

if TYPE_CHECKING:
    from syncr_cli.http import Transport
    from syncr_cli.wire.reading import JsonMapping

DISCOVERY_PATH: Final = "/.well-known/oauth-authorization-server"

# The client this CLI is registered as. One value on every deployment, seeded by a migration, so
# it is a constant rather than a setting: a deployment cannot rename it and there is no second
# client for this binary to be.
CLIENT_ID: Final = "syncr-cli"

# What the CLI asks for, and the whole of it. `admin` is absent deliberately: calendar source
# setup and template editing are out of CLI scope, so a stolen CLI token cannot reach them
# however the request is spelled. The Authorization Server refuses `admin` for this client at
# the redirect, and this list is why it never has to.
REQUESTED_SCOPES: Final = ("plan:read", "plan:write")

DOCUMENT = "metadata"


@dataclass(frozen=True, slots=True)
class AuthorizationServer:
    """Where to send a user, where to exchange a code, and where to revoke a token."""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    revocation_endpoint: str

    @classmethod
    def discover(cls, transport: Transport, api_url: str) -> Self:
        """Read this deployment's metadata document."""
        return cls.read(transport.get(f"{api_url}{DISCOVERY_PATH}"))

    @classmethod
    def read(cls, body: object) -> Self:
        payload = mapping(body, DOCUMENT)
        _require_s256(payload)
        return cls(
            issuer=text(payload, "issuer", DOCUMENT),
            authorization_endpoint=text(payload, "authorization_endpoint", DOCUMENT),
            token_endpoint=text(payload, "token_endpoint", DOCUMENT),
            revocation_endpoint=text(payload, "revocation_endpoint", DOCUMENT),
        )


def requested_scope() -> str:
    """The ``scope`` parameter, space-delimited as RFC 6749 spells it."""
    return " ".join(REQUESTED_SCOPES)


def _require_s256(payload: JsonMapping) -> None:
    """Refuse a server that does not support the only PKCE method this client speaks."""
    advertised = payload.get("code_challenge_methods_supported")
    supported = (
        [method for method in advertised if isinstance(method, str)]
        if isinstance(advertised, list)
        else []
    )
    if CODE_CHALLENGE_METHOD_S256 not in supported:
        raise MalformedResponse(
            f"this deployment advertises {supported or 'no'} PKCE method, and this CLI uses "
            f"{CODE_CHALLENGE_METHOD_S256} only. Nothing was changed. It will not fall back to a "
            "weaker mode."
        )
