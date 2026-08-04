"""The access token every Google read runs on, and the four answers to asking for one.

A refresh token is the standing authority; an access token is what a request carries, and it
lasts minutes. This module is the only place the first becomes the second, and it is a closed
union rather than a raise, because the caller has to record which failure it hit on the source
either way.

**The token is cached for the life of this object, not stored.** One of these is built per sync
pass, so five Google sources cost one refresh rather than five, and nothing writes an access
token to a column, a log line, or a response. A row that never holds one cannot leak one.

**A dead grant and an unreachable Google are different answers.** Only the first means the user
must consent again, and only the first is recorded on the credential as a failure with an
instant, because that instant is what the loudest notice in the product states. Treating a 503
as a dead grant would raise that notice against a healthy credential and teach the user to
ignore it.

**A ciphertext this deployment cannot decrypt is a dead grant.** The key rotated or the row came
from elsewhere; either way no read can be made and the repair is a reconnect.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Protocol

from syncr_api.google_account.config import ACCESS_TOKEN_SKEW
from syncr_api.google_account.oauth_client import (
    GrantRefused,
    TokenEndpointUnreachable,
    TokenPayload,
)

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_api.core.clock import Clock
    from syncr_api.google_account.crypto import TokenCipher
    from syncr_api.google_account.oauth_client import GoogleOAuthClient
    from syncr_api.google_account.repository import GoogleCredentialRepository

NO_ACCOUNT_REASON = (
    "syncr is not connected to a Google account, so this calendar cannot be read. Connect the "
    "account in Settings. Every ICS feed still syncs."
)

UNDECRYPTABLE_REASON = (
    "the stored Google authorization cannot be read by this deployment's key, so it has to be "
    "granted again"
)


@dataclass(frozen=True, slots=True)
class GoogleAccess:
    """A usable access token, and when it stops being one."""

    token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class NoGoogleAccount:
    """No account is connected, so there is nothing to read with."""

    reason: str = NO_ACCOUNT_REASON


@dataclass(frozen=True, slots=True)
class GoogleGrantDead:
    """The grant is gone. Retrying cannot help; the user must reconnect."""

    reason: str


@dataclass(frozen=True, slots=True)
class GoogleUnreachable:
    """Google could not be asked. The grant may be perfectly good."""

    reason: str


type GoogleAccessAnswer = GoogleAccess | NoGoogleAccount | GoogleGrantDead | GoogleUnreachable


class AccessTokenSource(Protocol):
    """One access token, refreshed when it has to be. The seam a test substitutes."""

    async def current(self) -> GoogleAccessAnswer:
        """A usable access token, or why there is none."""
        ...


class GoogleAccessTokens:
    """Turns one tenant's stored grant into an access token, once per pass.

    Every dependency is injected, including the clock, because "is this token still usable"
    is clock arithmetic and a test that had to sleep for it would be a test of ``sleep``.
    """

    def __init__(
        self,
        *,
        credentials: GoogleCredentialRepository,
        oauth: GoogleOAuthClient,
        cipher: TokenCipher,
        clock: Clock,
    ) -> None:
        self._credentials = credentials
        self._oauth = oauth
        self._cipher = cipher
        self._clock = clock
        self._held: GoogleAccess | None = None

    async def current(self) -> GoogleAccessAnswer:
        """A usable access token, refreshing the stored grant when the held one is spent."""
        held = self._held
        if held is not None and self._clock() + ACCESS_TOKEN_SKEW < held.expires_at:
            return held
        return await self._refreshed()

    async def _refreshed(self) -> GoogleAccessAnswer:
        credential = await self._credentials.read()
        if credential is None:
            return NoGoogleAccount()
        refresh_token = self._cipher.decrypt(credential.encrypted_refresh_token)
        if refresh_token is None:
            return await self._dead(UNDECRYPTABLE_REASON)

        answer = await self._oauth.refresh(refresh_token)
        if isinstance(answer, GrantRefused):
            return await self._dead(answer.reason)
        if isinstance(answer, TokenEndpointUnreachable):
            return GoogleUnreachable(answer.reason)
        return await self._granted(answer)

    async def _granted(self, payload: TokenPayload) -> GoogleAccess:
        """Hold the new token and clear whatever failure it repaired."""
        now = self._clock()
        await self._credentials.record_refresh(at=now)
        access = GoogleAccess(
            token=payload.access_token,
            expires_at=now + timedelta(seconds=payload.lifetime_seconds),
        )
        self._held = access
        return access

    async def _dead(self, reason: str) -> GoogleGrantDead:
        """Record that writes are failing, keeping the instant they started failing."""
        await self._credentials.record_refresh_failure(at=self._clock(), reason=reason)
        return GoogleGrantDead(reason)
