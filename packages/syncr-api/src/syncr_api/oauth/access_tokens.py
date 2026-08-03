"""The access token: what it claims, how it is signed, and what verifying it proves.

The token is a JWS the resource server verifies against the published JWKS, so a request
costs no database read. Four properties are checked on every presented token, and each
one closes a specific hole:

``iss``   this deployment issued it, not another syncr install whose JWKS is reachable.
``aud``   it was issued FOR this API. This is the binding that keeps P1 safe: a token
          the CLI holds names the syncr API as its audience, so an MCP server (or any
          other resource) presented with it rejects it, and a token minted for another
          audience is rejected here. Without it, one stolen token would be a credential
          at every resource the same issuer ever serves.
``exp``   it has not expired. Revocation cannot reach a signed claim set, so the lifetime
          IS the revocation window.
``kid``   it was signed by a key this server holds, current or previous, so a rotation
          does not invalidate a token minted a minute earlier.

Signing and verification are delegated to PyJWT. What is written here is the claim set,
the audience rule, and the mapping from verified claims back to a principal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

import jwt

from syncr_api.core.principal import Principal
from syncr_api.core.scopes import format_scopes, parse_scopes
from syncr_api.oauth.config import ACCESS_TOKEN_LIFETIME
from syncr_api.oauth.keys import SIGNING_ALGORITHM

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_api.core.scopes import Scope
    from syncr_api.oauth.keys import SigningKeySet
    from syncr_domain.identifiers import TenantId, UserId

# The claims beyond the registered ones. `tid` carries the tenant because a scoped
# repository cannot be built without one and the subject alone does not name it: a tenant
# holds exactly one user today, and deriving one from the other at every request would bake
# that into the request path rather than into the schema that enforces it.
TENANT_CLAIM = "tid"
SCOPE_CLAIM = "scope"
CLIENT_CLAIM = "client_id"


@dataclass(frozen=True, slots=True)
class MintedAccessToken:
    """A freshly signed access token and the seconds a client may hold it."""

    token: str
    expires_in: int


class AccessTokenCodec:
    """Mints and verifies access tokens for one key set, issuer, and audience.

    The key set is injected rather than read, so a test can rotate keys and assert that a
    token signed by the retired key still verifies. Both directions live in one class
    because the claim set is one contract: a change to what is minted and a change to what
    is required have to be made together or tokens stop verifying.
    """

    def __init__(self, keys: SigningKeySet, *, issuer: str, audience: str) -> None:
        self._keys = keys
        self._issuer = issuer
        self._audience = audience

    @property
    def keys(self) -> SigningKeySet:
        """The key set this codec signs with and verifies against."""
        return self._keys

    def mint(
        self,
        *,
        tenant_id: TenantId,
        user_id: UserId,
        client_id: str,
        scopes: frozenset[Scope],
        issued_at: datetime,
    ) -> MintedAccessToken:
        """Sign a short-lived token bound to this API's audience."""
        expires_in = int(ACCESS_TOKEN_LIFETIME.total_seconds())
        issued = int(issued_at.timestamp())
        claims: dict[str, Any] = {
            "iss": self._issuer,
            "sub": str(user_id),
            "aud": self._audience,
            "iat": issued,
            "exp": issued + expires_in,
            TENANT_CLAIM: str(tenant_id),
            SCOPE_CLAIM: format_scopes(scopes),
            CLIENT_CLAIM: client_id,
        }
        signing = self._keys.current
        token = jwt.encode(
            claims,
            signing.private_key,
            algorithm=SIGNING_ALGORITHM,
            headers={"kid": signing.kid},
        )
        return MintedAccessToken(token=token, expires_in=expires_in)

    def verify(self, token: str, *, at: datetime) -> Principal | None:
        """The principal ``token`` authenticates, or ``None`` if it authenticates nobody.

        ``None`` rather than a raised error for every failure, so one caller decides what
        a rejection looks like on the wire and no rejection can accidentally answer with a
        different status than its siblings. Which rule rejected the token is deliberately
        not reported: a caller learns "present a working token", and the operator's answer
        is in the log line the caller writes.
        """
        key = self._keys.find(self._kid_of(token))
        if key is None:
            return None
        try:
            claims = jwt.decode(
                token,
                key.public_key,
                algorithms=[SIGNING_ALGORITHM],
                audience=self._audience,
                issuer=self._issuer,
                leeway=0,
                options={
                    "require": ["iss", "sub", "aud", "exp", "iat"],
                    "verify_exp": False,
                },
            )
        except jwt.InvalidTokenError:
            return None
        # Expiry is checked against the injected instant rather than PyJWT's own clock, so
        # one clock governs minting and verification and a test reaches an expiry by moving
        # time rather than by sleeping.
        if int(claims["exp"]) <= int(at.timestamp()):
            return None
        return self._principal_from(claims)

    @staticmethod
    def _kid_of(token: str) -> str | None:
        try:
            return jwt.get_unverified_header(token).get("kid")
        except jwt.InvalidTokenError:
            return None

    @staticmethod
    def _principal_from(claims: dict[str, Any]) -> Principal | None:
        scopes = parse_scopes(claims.get(SCOPE_CLAIM))
        raw_tenant = claims.get(TENANT_CLAIM)
        if scopes is None or not isinstance(raw_tenant, str):
            return None
        try:
            tenant_id = UUID(raw_tenant)
            user_id = UUID(str(claims["sub"]))
        except ValueError:
            return None
        return Principal(tenant_id=tenant_id, user_id=user_id, scopes=scopes)
