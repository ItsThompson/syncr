"""The Google account service: connect, complete, and describe. Three methods, one credential.

The ordering decisions are here; the rules they apply are in the modules that own them.

**The state is verified before the code is spent.** A callback carrying a valid code and a state
this deployment did not issue is a code somebody else obtained, so the exchange does not happen.
The session's tenant is compared against the state's for the same reason: the two answer
different questions, and a connect is only safe when they agree.

**A completed connect clears the failure it repaired.** ``connect`` replaces the row, so the
notice built from ``refresh_failing_since`` stops being raised in the same transaction that
stores the new grant. A reconnect that left the old failure behind would leave the loudest notice
in the product on screen after the repair, which is how a user learns to ignore it.

**Nothing here logs a token.** The connect path handles the two most sensitive values in the
product, and every line it writes carries identifiers and counts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.calendars.config import GOOGLE
from syncr_api.core.errors import DependencyUnavailable, ValidationFailed
from syncr_api.core.principal import require_scope
from syncr_api.core.scopes import Scope
from syncr_api.google_account.config import (
    GRANTED_SCOPES_MAX_LENGTH,
    PUBLISHED_KEY_DETAIL,
    REQUESTED_SCOPES,
    SCOPE_SEPARATOR,
)
from syncr_api.google_account.connect import GoogleConsent, consent_surface
from syncr_api.google_account.crypto import RefreshTokenTooLong
from syncr_api.google_account.notices import write_target_expiry_notices
from syncr_api.google_account.oauth_client import GrantRefused, TokenEndpointUnreachable
from syncr_api.google_account.outcomes import (
    CONNECTED,
    DENIED,
    EXPIRED,
    FAILED,
    ConnectOutcome,
)
from syncr_api.google_account.state import StateAccepted, issue_state, read_state
from syncr_common.logging import get_logger
from syncr_common.metrics import measured

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from syncr_api.calendars.repository import CalendarSourceRepository
    from syncr_api.core.clock import Clock
    from syncr_api.core.notices import Notice
    from syncr_api.core.principal import Principal
    from syncr_api.google_account.crypto import TokenCipher
    from syncr_api.google_account.oauth_client import GoogleOAuthClient
    from syncr_api.google_account.repository import GoogleCredentialRepository

_log = get_logger("syncr.google_account")

NOT_CONFIGURED_DETAIL = (
    "This deployment has no Google OAuth client, so there is nothing to connect to. Set "
    "GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, and GOOGLE_OAUTH_REDIRECT_URI from the "
    "host secret file and restart. Every ICS feed still syncs and the plan still solves; only "
    "Google reading and the projection are unavailable."
)

NO_CODE_DETAIL = (
    "Google did not return an authorization code, so nothing was connected. Start the connect "
    "again from Settings."
)


@dataclass(frozen=True, slots=True)
class GoogleConnection:
    """What Settings renders about the account: whether it is connected, and what is wrong."""

    configured: bool
    connected: bool
    granted_scopes: tuple[str, ...]
    connected_at: datetime | None
    last_refresh_at: datetime | None
    notices: tuple[Notice, ...]


class GoogleConnectionService:
    """Connect one Google account per tenant, and report the state of that connection."""

    def __init__(
        self,
        *,
        credentials: GoogleCredentialRepository,
        sources: CalendarSourceRepository,
        oauth: GoogleOAuthClient,
        cipher: TokenCipher,
        client_id: str,
        redirect_uri: str,
        state_secret: str,
        clock: Clock,
        may_store_tokens: bool = True,
    ) -> None:
        self._credentials = credentials
        self._sources = sources
        self._oauth = oauth
        self._cipher = cipher
        self._client_id = client_id
        self._redirect_uri = redirect_uri
        self._state_secret = state_secret
        self._clock = clock
        # Whether this deployment may write a NEW authorization: false when the encryption key is
        # the one this repository publishes and the environment is not development. Received as an
        # answer rather than computed, because reading the key and the environment is the
        # composition's job.
        self._may_store_tokens = may_store_tokens

    @measured("google_account")
    async def begin_connect(self, principal: Principal) -> GoogleConsent:
        """The consent surface for a new connect: the scopes, the calendars, and the URL."""
        require_scope(principal, Scope.ADMIN)
        self._require_a_configured_client()
        state = issue_state(
            tenant_id=principal.tenant_id, secret=self._state_secret, at=self._clock()
        )
        surface = consent_surface(
            client_id=self._client_id,
            redirect_uri=self._redirect_uri,
            state=state,
            sources=await self._sources.list_for(GOOGLE),
        )
        _log.info(
            "google_account.connect.started",
            tenant_id=str(principal.tenant_id),
            scope_count=len(surface.scopes),
            calendar_count=len(surface.calendars_read),
        )
        return surface

    @measured("google_account")
    async def complete_connect(
        self, principal: Principal, *, code: str | None, state: str | None, error: str | None
    ) -> ConnectOutcome:
        """Finish a connect Google redirected back from, and say how it ended.

        Answers with an outcome rather than raising, because the caller is a browser following a
        redirect: a problem-details body in a top-level navigation is a blank page, and every
        outcome here has a Settings surface that states what to do next.
        """
        require_scope(principal, Scope.ADMIN)
        self._require_a_configured_client()
        if error or not code:
            return self._refused(principal, error=error)
        if not isinstance(verdict := self._verified(principal, state), StateAccepted):
            return verdict
        return await self._exchanged(principal, code=code)

    @measured("google_account")
    async def describe_connection(self, principal: Principal) -> GoogleConnection:
        """Whether an account is connected, and every notice its state raises."""
        require_scope(principal, Scope.PLAN_READ)
        credential = await self._credentials.read()
        return GoogleConnection(
            configured=bool(self._client_id),
            connected=credential is not None,
            granted_scopes=credential.granted_scopes if credential else (),
            connected_at=credential.connected_at if credential else None,
            last_refresh_at=credential.last_refresh_at if credential else None,
            notices=write_target_expiry_notices(credential, now=self._clock()),
        )

    def _require_a_configured_client(self) -> None:
        """Refuse a connect this deployment has no credentials for, naming what still works."""
        if self._client_id and self._redirect_uri:
            return
        raise DependencyUnavailable(NOT_CONFIGURED_DETAIL)

    def _refused(self, principal: Principal, *, error: str | None) -> ConnectOutcome:
        """The outcome when Google sent no code: the user declined, or the flow broke.

        The error CODE is logged and the reason is not rendered from it: it is a value Google
        chose the content of, and it reaches a browser's address bar.
        """
        _log.info(
            "google_account.connect.refused",
            tenant_id=str(principal.tenant_id),
            error_code=error or "no_code",
        )
        return DENIED if error else FAILED

    def _verified(self, principal: Principal, state: str | None) -> ConnectOutcome | StateAccepted:
        """The state's tenant once it verifies and matches the session's, or the outcome."""
        if not state:
            return EXPIRED
        verdict = read_state(state, secret=self._state_secret, now=self._clock())
        if not isinstance(verdict, StateAccepted):
            _log.warning(
                "google_account.connect.state_rejected", tenant_id=str(principal.tenant_id)
            )
            return EXPIRED
        if verdict.tenant_id != principal.tenant_id:
            # The flow was started by another account. Refused rather than connected to whoever
            # is signed in now, which is the whole reason the state carries a tenant.
            _log.warning(
                "google_account.connect.state_mismatched", tenant_id=str(principal.tenant_id)
            )
            return EXPIRED
        return verdict

    async def _exchanged(self, principal: Principal, *, code: str) -> ConnectOutcome:
        """Trade the code for a grant and store it, or say which half failed."""
        answer = await self._oauth.exchange_code(code)
        if isinstance(answer, GrantRefused | TokenEndpointUnreachable):
            _log.warning(
                "google_account.connect.exchange_failed",
                tenant_id=str(principal.tenant_id),
                permanent=isinstance(answer, GrantRefused),
            )
            return FAILED
        if answer.refresh_token is None:
            # Google issues one only with offline access and a forced consent, both of which the
            # authorization URL asks for. Reaching here means the request was built wrong or the
            # user reached the callback by another route, and storing the access token alone
            # would produce an account that works for minutes and then dies silently.
            _log.warning(
                "google_account.connect.no_refresh_token", tenant_id=str(principal.tenant_id)
            )
            return FAILED
        return await self._stored(
            principal, refresh_token=answer.refresh_token, granted=answer.granted_scopes
        )

    async def _stored(
        self, principal: Principal, *, refresh_token: str, granted: Sequence[str]
    ) -> ConnectOutcome:
        """Encrypt and store the grant, replacing whatever the tenant held.

        A grant whose response stated no scopes is recorded as the requested set: Google omits the
        field rather than granting nothing, and an empty list would make the surface report an
        account that can do nothing while it reads calendars perfectly well.

        Two values are bounded here rather than at the column, because both are the provider's to
        size and a column refusal is a 500 whose log line renders the whole failing statement,
        ciphertext included. The refresh token is bounded by the cipher; the scope string is bounded
        here beside it.
        """
        if not self._may_store_tokens:
            # Refused at the one point that WRITES a new authorization, so reading a feed, listing
            # sources and polling a calendar are all unaffected and the message's promises are true.
            raise DependencyUnavailable(PUBLISHED_KEY_DETAIL)
        joined = SCOPE_SEPARATOR.join(granted or REQUESTED_SCOPES)
        if len(joined) > GRANTED_SCOPES_MAX_LENGTH:
            raise ValidationFailed(
                f"Google granted a scope list of {len(joined)} characters, and syncr stores up to "
                f"{GRANTED_SCOPES_MAX_LENGTH}. Nothing was connected, and every calendar syncr "
                "already reads still works."
            )
        try:
            encrypted = self._cipher.encrypt(refresh_token)
        except RefreshTokenTooLong as oversize:
            # Refused before the write, so an oversize value cannot roll back the transaction it
            # is in and take every sibling write with it.
            raise ValidationFailed(
                f"{oversize} Nothing was connected, and every calendar syncr already reads still "
                "works."
            ) from oversize
        stored = await self._credentials.connect(
            encrypted_refresh_token=encrypted,
            granted_scopes=granted or REQUESTED_SCOPES,
            at=self._clock(),
        )
        _log.info(
            "google_account.connected",
            tenant_id=str(principal.tenant_id),
            grant_id=str(stored.id),
            granted_scope_count=len(stored.granted_scopes),
        )
        return CONNECTED
