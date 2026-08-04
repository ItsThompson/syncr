"""Google's token endpoint: the code exchange, the refresh, and what each failure means.

Two calls, one shape of answer, and the distinction between the two failures is the whole point
of this module.

**A permanent failure means the grant is gone.** ``invalid_grant`` is Google's answer to a
revoked, expired, or superseded refresh token. Retrying cannot fix it and the user must consent
again, so it raises the loudest notice in the product rather than a retry.

**A transient failure means Google was unreachable.** A 5xx, a timeout, or a refused connection
says nothing about the grant. Treating it as permanent would tell the user to reconnect a
credential that is fine, and would train them to ignore the one notice that matters.

Nothing here raises for a network condition: both answers are values, because the caller has to
record one of them on the credential either way.

**The response is validated at the boundary.** A token response is JSON from a service that can
change under us, so the fields are declared and an answer that does not carry an access token is
a stated failure rather than a ``KeyError`` three layers up. The refresh token is optional on
purpose: Google returns one only when the flow asked for offline access with a forced consent.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from syncr_api.core.http_reads import read_bounded_body
from syncr_api.google_account.config import (
    DEFAULT_ACCESS_TOKEN_LIFETIME,
    MAX_TOKEN_RESPONSE_BYTES,
    SCOPE_SEPARATOR,
    TOKEN_ENDPOINT,
    TOKEN_TIMEOUT_SECONDS,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

# Google's own name for "this refresh token is no longer a credential". The only error code the
# flow treats as permanent, because every other one either retries or is a bug in our request.
INVALID_GRANT: Final = "invalid_grant"

_AUTHORIZATION_CODE_GRANT: Final = "authorization_code"
_REFRESH_TOKEN_GRANT: Final = "refresh_token"  # noqa: S105 - a grant type, not a credential


class TokenPayload(BaseModel):
    """The token endpoint's success body, as syncr reads it.

    Unknown fields are ignored rather than refused: Google adds fields (``id_token``,
    ``refresh_token_expires_in``) and a strict model would turn an additive change into an
    outage. What is NOT tolerated is a missing access token, which is the field every caller
    needs.
    """

    model_config = ConfigDict(extra="ignore")

    access_token: str = Field(min_length=1)
    expires_in: int | None = Field(default=None, ge=0)
    refresh_token: str | None = None
    scope: str | None = None

    @property
    def granted_scopes(self) -> tuple[str, ...]:
        """The scopes Google says it granted, which can be narrower than those requested."""
        return tuple(self.scope.split(SCOPE_SEPARATOR)) if self.scope else ()

    @property
    def lifetime_seconds(self) -> int:
        """How long the access token lasts, with a floor for an answer that states nothing."""
        if self.expires_in is None:
            return int(DEFAULT_ACCESS_TOKEN_LIFETIME.total_seconds())
        return self.expires_in


@dataclass(frozen=True, slots=True)
class GrantRefused:
    """Google refused the credential itself. Retrying cannot help; the user must reconnect."""

    reason: str


@dataclass(frozen=True, slots=True)
class TokenEndpointUnreachable:
    """Google could not be asked. The credential may be perfectly good."""

    reason: str


type TokenAnswer = TokenPayload | GrantRefused | TokenEndpointUnreachable


@dataclass(frozen=True, slots=True)
class GoogleOAuthClient:
    """The two token-endpoint calls, bounded in time and in size.

    The HTTP client is injected so a worker tick reuses connections and a test hands in a
    transport. The credentials are injected for the same reason the zone profile is injected into
    the ICS adapter: they belong to the deployment, and reading the environment here would put a
    settings dependency inside a transport.
    """

    client: httpx.AsyncClient
    client_id: str
    client_secret: str
    redirect_uri: str

    async def exchange_code(self, code: str) -> TokenAnswer:
        """Trade an authorization code for an access token and a refresh token."""
        return await self._post(
            {
                "code": code,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": self.redirect_uri,
                "grant_type": _AUTHORIZATION_CODE_GRANT,
            }
        )

    async def refresh(self, refresh_token: str) -> TokenAnswer:
        """Trade a refresh token for a fresh access token."""
        return await self._post(
            {
                "refresh_token": refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": _REFRESH_TOKEN_GRANT,
            }
        )

    async def _post(self, form: Mapping[str, str]) -> TokenAnswer:
        try:
            # The client's own timeout is per operation, so a host that trickles resets the read
            # clock on every chunk. This deadline covers the whole exchange, which is what a
            # request and a worker tick each need.
            async with asyncio.timeout(TOKEN_TIMEOUT_SECONDS):
                return await self._read(form)
        except (httpx.TimeoutException, TimeoutError):
            return TokenEndpointUnreachable(
                f"Google's token endpoint did not answer within {TOKEN_TIMEOUT_SECONDS:.0f}s"
            )
        except (httpx.HTTPError, httpx.InvalidURL) as error:
            # InvalidURL is not an HTTPError, so it is named: the contract above is that neither
            # method raises, and one word here is cheaper than a lost worker tick.
            return TokenEndpointUnreachable(
                f"Google's token endpoint could not be reached: {type(error).__name__}"
            )

    async def _read(self, form: Mapping[str, str]) -> TokenAnswer:
        async with self.client.stream("POST", TOKEN_ENDPOINT, data=dict(form)) as response:
            body = await read_bounded_body(response, max_bytes=MAX_TOKEN_RESPONSE_BYTES)
            status = response.status_code
            failed = response.is_error
        if body is None:
            return TokenEndpointUnreachable(
                "Google's token endpoint answered a body larger than "
                f"{MAX_TOKEN_RESPONSE_BYTES // 1024}KB, which no token response is"
            )
        if failed:
            return _refusal(status, body)
        try:
            return TokenPayload.model_validate_json(body)
        except ValidationError as invalid:
            return TokenEndpointUnreachable(
                "Google's token endpoint answered a body syncr cannot read: "
                f"{invalid.error_count()} field(s) did not match the expected shape"
            )


def _refusal(status: int, body: bytes) -> TokenAnswer:
    """Which kind of failure an error status is.

    The error CODE decides, not the status: Google answers ``invalid_grant`` with a 400, and a
    400 is also what a malformed request gets. Only the named code means the grant is gone, so a
    bad request of ours does not tell the user to reconnect a healthy credential.
    """
    code = _error_code(body)
    if code == INVALID_GRANT:
        return GrantRefused(
            "Google refused the stored authorization: it was revoked, expired, or replaced"
        )
    stated = f" ({code})" if code else ""
    return TokenEndpointUnreachable(f"Google's token endpoint answered {status}{stated}")


class _ErrorPayload(BaseModel):
    """The error body's one field syncr reads. Everything else is Google's prose."""

    model_config = ConfigDict(extra="ignore")

    error: str | None = None


def _error_code(body: bytes) -> str | None:
    """The OAuth error code the body states, or ``None`` when it states none.

    A token endpoint behind a proxy can answer HTML, so this cannot assume JSON.
    """
    try:
        return _ErrorPayload.model_validate_json(body).error
    except ValidationError:
        return None
