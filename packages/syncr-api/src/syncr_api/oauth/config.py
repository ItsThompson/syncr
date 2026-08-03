"""Paths, lifetimes, the one registered client, and the pinned URLs built from settings.

Every URL the Authorization Server publishes is built from the deployment's pinned
``PUBLIC_BASE_URL`` and never from the request host. Cloudflare Tunnel reaches this
process as ``http://api:8000`` from inside ``app-net``, so a request-derived issuer would
advertise URLs no client can reach and would mint tokens whose ``iss`` does not match the
one the client opened the flow at. That failure appears only through the tunnel, which is
to say only in the deployed stack, so the URLs are resolved once here.

The audience is derived from :data:`~syncr_api.core.settings.API_PREFIX` rather than
restated. The audience IS the resource server the token may be presented to, and that
resource server is the versioned API, so the two cannot be allowed to disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from syncr_api.core.scopes import Scope
from syncr_api.core.settings import API_PREFIX

if TYPE_CHECKING:
    from syncr_api.core.settings import ServiceSettings

# --- Mounted paths ----------------------------------------------------------
# `/oauth` and `/.well-known` sit OUTSIDE the versioned prefix: they are how a caller
# obtains the credential every versioned route requires, so they are not themselves
# versioned resources. Two routers, because RFC 8414 fixes the discovery path at the
# origin root and it cannot be nested under a prefix.
OAUTH_PREFIX = "/oauth"
WELL_KNOWN_PREFIX = "/.well-known"

AUTHORIZE_PATH = "/authorize"
CONSENT_DECISION_PATH = "/authorize/decision"
TOKEN_PATH = "/token"  # noqa: S105 - an endpoint path, not a token
REVOKE_PATH = "/revoke"
AS_METADATA_PATH = "/oauth-authorization-server"
JWKS_PATH = "/jwks.json"

# --- Protocol vocabulary ----------------------------------------------------
RESPONSE_TYPE_CODE = "code"
GRANT_TYPE_AUTHORIZATION_CODE = "authorization_code"
GRANT_TYPE_REFRESH_TOKEN = "refresh_token"  # noqa: S105 - a grant type's name
# A public client cannot hold a secret, so it authenticates by proving possession of the
# PKCE verifier rather than by presenting one.
TOKEN_ENDPOINT_AUTH_NONE = "none"  # noqa: S105 - names the absence of client authentication
CODE_CHALLENGE_METHOD_S256 = "S256"
# Named so the rejection can say what was presented. `plain` is a code challenge that is
# the verifier, which proves nothing against an attacker who intercepted the redirect.
CODE_CHALLENGE_METHOD_PLAIN = "plain"
TOKEN_TYPE_BEARER = "Bearer"  # noqa: S105 - the token TYPE, not a token
BEARER_SCHEME = "bearer"

# --- Lifetimes --------------------------------------------------------------
# Minutes, because an access token cannot be revoked: it is a signed claim set the
# resource server verifies without a database read, so revocation takes effect within
# this window and the window is the cost of that read not happening.
ACCESS_TOKEN_LIFETIME = timedelta(minutes=15)
# Long and revocable. The CLI stores it in the OS keychain and refreshes as it goes, so a
# fortnight of holiday must not end in a re-authorization.
REFRESH_TOKEN_LIFETIME = timedelta(days=60)
# Very short: a code is exchanged immediately by a process that is already waiting on the
# loopback listener. Anything longer is a window for a code sitting in a browser history.
AUTHORIZATION_CODE_LIFETIME = timedelta(minutes=1)
# How long a dead grant's rows are kept before the sweep removes them. Not zero, so an
# operator investigating a revoked grant has something to read.
DEAD_GRANT_RETENTION = timedelta(days=7)

# --- The one registered client ---------------------------------------------
# P0 registers one client, in the migration, and has no dynamic registration: nothing
# else may ask for a token, so an open registration endpoint would add an attack surface
# for a capability no P0 client needs. P1's MCP server is a second seeded row.
CLI_CLIENT_ID = "syncr-cli"
CLI_CLIENT_NAME = "syncr CLI"
# The scopes the CLI may ever request. `admin` is absent deliberately: calendar source
# setup and template editing are out of CLI scope, so a stolen CLI token cannot reach
# them however the request is spelled.
CLI_CLIENT_SCOPES: frozenset[Scope] = frozenset({Scope.PLAN_READ, Scope.PLAN_WRITE})
# The loopback redirect the CLI's ephemeral listener answers on. The port is not part of
# the registration: RFC 8252 requires the AS to accept any port on a loopback redirect,
# because a fresh ephemeral port per run is what stops two runs from colliding.
CLI_REDIRECT_URIS: tuple[str, ...] = (
    "http://127.0.0.1/callback",
    "http://[::1]/callback",
)


@dataclass(frozen=True, slots=True)
class OAuthConfig:
    """The pinned values every OAuth URL, claim, and lifetime is derived from."""

    issuer: str
    audience: str
    keys_path: str
    key_encryption_key: str
    is_dev: bool

    def endpoint(self, prefix: str, path: str) -> str:
        """The absolute URL of a mounted path, built from the pinned issuer only."""
        return f"{self.issuer}{prefix}{path}"


def build_oauth_config(settings: ServiceSettings, *, is_dev: bool) -> OAuthConfig:
    """Compose the Authorization Server's configuration from process settings.

    ``is_dev`` is passed rather than re-derived from ``settings.environment``: one
    predicate has one definition, and it lives on the settings object that produced
    these values.
    """
    issuer = settings.public_base_url.rstrip("/")
    return OAuthConfig(
        issuer=issuer,
        audience=f"{issuer}{API_PREFIX}",
        keys_path=settings.oauth_keys_path,
        key_encryption_key=settings.oauth_key_encryption_key.get_secret_value(),
        is_dev=is_dev,
    )
