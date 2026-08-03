"""The RFC 8414 Authorization Server Metadata document.

A client reads this to learn where the endpoints are, which grant types exist, and which
PKCE method it must use, rather than having those compiled into it. That matters for a CLI
that ships separately from the server: a deployment behind a different hostname is
discovered rather than reconfigured.

Every URL is built from the pinned issuer, never from the request host. ``S256`` is
advertised as the only code challenge method, which matches what the authorize endpoint
enforces: a document that advertised ``plain`` would invite a client to build the weak mode
and then be refused at runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from syncr_api.core.scopes import SCOPE_ORDER
from syncr_api.oauth.config import (
    AS_METADATA_PATH,
    AUTHORIZE_PATH,
    CODE_CHALLENGE_METHOD_S256,
    GRANT_TYPE_AUTHORIZATION_CODE,
    GRANT_TYPE_REFRESH_TOKEN,
    JWKS_PATH,
    OAUTH_PREFIX,
    RESPONSE_TYPE_CODE,
    REVOKE_PATH,
    TOKEN_ENDPOINT_AUTH_NONE,
    TOKEN_PATH,
    WELL_KNOWN_PREFIX,
)

if TYPE_CHECKING:
    from syncr_api.oauth.config import OAuthConfig

# The document's own path, so a caller that has the document can find where it came from.
DISCOVERY_PATH = f"{WELL_KNOWN_PREFIX}{AS_METADATA_PATH}"


def build_metadata(config: OAuthConfig) -> dict[str, Any]:
    """The discovery document for this deployment.

    Keys are the RFC's own spelling, in snake case, so this is not a
    :class:`~syncr_api.core.schemas.WireModel`: the names are the specification's and
    converting them to the product's casing would produce a document no client can read.
    """
    return {
        "issuer": config.issuer,
        "authorization_endpoint": config.endpoint(OAUTH_PREFIX, AUTHORIZE_PATH),
        "token_endpoint": config.endpoint(OAUTH_PREFIX, TOKEN_PATH),
        "revocation_endpoint": config.endpoint(OAUTH_PREFIX, REVOKE_PATH),
        "jwks_uri": config.endpoint(WELL_KNOWN_PREFIX, JWKS_PATH),
        "scopes_supported": [scope.value for scope in SCOPE_ORDER],
        "response_types_supported": [RESPONSE_TYPE_CODE],
        "response_modes_supported": ["query"],
        "grant_types_supported": [GRANT_TYPE_AUTHORIZATION_CODE, GRANT_TYPE_REFRESH_TOKEN],
        "code_challenge_methods_supported": [CODE_CHALLENGE_METHOD_S256],
        "token_endpoint_auth_methods_supported": [TOKEN_ENDPOINT_AUTH_NONE],
        "revocation_endpoint_auth_methods_supported": [TOKEN_ENDPOINT_AUTH_NONE],
        # There is no registration endpoint. P0 registers its one client in a migration, so
        # advertising dynamic registration would offer a capability that does not exist.
    }
