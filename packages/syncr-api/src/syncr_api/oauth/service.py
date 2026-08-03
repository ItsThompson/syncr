"""The consent service: where a signed-in browser authorizes a client.

Both methods take a principal first and use it as the only source of the tenant. That is
the authorization boundary here: the grant, the code, and every token that follows are
written under the tenant the SESSION resolved, never under a tenant named in the request, so
there is no parameter a caller could supply to consent on someone else's behalf.

**Consent requires a browser session, not a bearer token.** A holder of an access token must
not be able to mint itself a new grant, because it could then widen its own scopes or
survive its own revocation. The route declares the session-resolving dependency for that
reason, and it is not an oversight that a bearer credential cannot reach it.

The code is minted here and returned once, to the browser's redirect, and only its digest is
stored. Nothing else in the system can recover it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.core.errors import NotFound
from syncr_api.core.principal import authorize_tenant
from syncr_api.core.scopes import format_scopes
from syncr_api.oauth.authorization import (
    GrantedRedirect,
    RedirectedError,
    RedirectedRejection,
    ValidatedAuthorization,
    build_consent_screen,
    validate_authorization,
)
from syncr_api.oauth.config import AUTHORIZATION_CODE_LIFETIME
from syncr_api.oauth.secrets import digest_of, mint_authorization_code
from syncr_common.logging import get_logger
from syncr_common.metrics import measured

if TYPE_CHECKING:
    from syncr_api.accounts.repository import UserRepository
    from syncr_api.core.clock import Clock
    from syncr_api.core.principal import Principal
    from syncr_api.oauth.authorization import AuthorizeParams, ConsentScreen
    from syncr_api.oauth.repository import OAuthRepository, PresentedCredentialRepository

ACCOUNT_RESOURCE = "account"

_log = get_logger("syncr.oauth")


class AuthorizationService:
    """Describe what a client is asking for, and record the user's answer."""

    def __init__(
        self,
        clients: PresentedCredentialRepository,
        grants: OAuthRepository,
        users: UserRepository,
        clock: Clock,
    ) -> None:
        self._clients = clients
        self._grants = grants
        self._users = users
        self._clock = clock

    @measured("oauth")
    async def describe_consent(
        self, principal: Principal, params: AuthorizeParams
    ) -> ConsentScreen | RedirectedRejection:
        """What the consent screen states, or where to send a rejected request.

        Reads the signed-in account's email so the screen can name which account is about to
        be shared. That read goes through the tenant on the principal, so a session for
        another tenant cannot describe this one's.
        """
        validated = await self._validate(params)
        if isinstance(validated, RedirectedRejection):
            self._log_rejection(principal, params, validated)
            return validated
        return build_consent_screen(validated, account_email=await self._account_email(principal))

    @measured("oauth")
    async def decide(
        self, principal: Principal, params: AuthorizeParams, *, approved: bool
    ) -> GrantedRedirect | RedirectedRejection:
        """Record the user's answer and return where the browser goes next.

        Re-validates the request from scratch rather than trusting the form that carried it.
        The consent screen's hidden fields are a payload, so the rules that produced the
        screen are applied again to whatever comes back; a tampered field is simply a
        different request that has to pass them.
        """
        validated = await self._validate(params)
        if isinstance(validated, RedirectedRejection):
            self._log_rejection(principal, params, validated)
            return validated
        if not approved:
            _log.info(
                "oauth.consent.refused",
                tenant_id=str(principal.tenant_id),
                client_id=validated.client.id,
            )
            return RedirectedRejection(
                validated.redirect_uri,
                RedirectedError.ACCESS_DENIED,
                "The account holder refused this request.",
                validated.state,
            )
        return await self._grant(principal, validated)

    async def _grant(
        self, principal: Principal, validated: ValidatedAuthorization
    ) -> GrantedRedirect:
        """Record the grant, mint the single-use code, and hand back the redirect."""
        now = self._clock()
        grant = await self._grants.upsert_grant(
            client_id=validated.client.id, scopes=validated.scopes, at=now
        )
        code = mint_authorization_code()
        await self._grants.create_code(
            code_id=digest_of(code),
            client_id=validated.client.id,
            redirect_uri=validated.redirect_uri,
            scopes=validated.scopes,
            code_challenge=validated.code_challenge,
            created_at=now,
            expires_at=now + AUTHORIZATION_CODE_LIFETIME,
        )
        _log.info(
            "oauth.consent.granted",
            tenant_id=str(principal.tenant_id),
            client_id=validated.client.id,
            grant_id=str(grant.id),
            granted_scopes=format_scopes(validated.scopes),
        )
        return GrantedRedirect(
            redirect_uri=validated.redirect_uri, code=code, state=validated.state
        )

    async def _validate(
        self, params: AuthorizeParams
    ) -> ValidatedAuthorization | RedirectedRejection:
        return validate_authorization(params, await self._clients.find_client(params.client_id))

    async def _account_email(self, principal: Principal) -> str:
        user = await self._users.find(principal.user_id)
        if user is None:
            raise NotFound(f"No {ACCOUNT_RESOURCE} matches that identifier.")
        authorize_tenant(principal, user.tenant_id, resource=ACCOUNT_RESOURCE)
        return user.email

    @staticmethod
    def _log_rejection(
        principal: Principal, params: AuthorizeParams, rejection: RedirectedRejection
    ) -> None:
        _log.warning(
            "oauth.authorize.rejected",
            tenant_id=str(principal.tenant_id),
            client_id=params.client_id,
            reason=rejection.error.value,
        )
