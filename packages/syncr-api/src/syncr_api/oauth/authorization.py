"""The authorize request's rules, and the consent screen's payload.

Pure. Nothing here reads a row, a clock, or a session, so every rule is testable by passing
values in and reading values out, and the orchestration that loads a client and writes a
code lives in ``service.py``.

**Two kinds of rejection, because the protocol requires two.** If the ``client_id`` is
unknown or the ``redirect_uri`` is not registered, the request is answered directly and
nothing is redirected: the redirect target is exactly what cannot be trusted in those two
cases, and bouncing the browser to an attacker-supplied URI to report an error would make
the error report the attack. Every later failure happens with a trusted redirect target, so
it is delivered there as RFC 6749 section 4.1.2.1 requires, which is what lets the client
waiting on its loopback listener fail immediately instead of timing out.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING
from urllib.parse import urlencode, urlsplit

from syncr_api.core.scopes import SCOPE_DESCRIPTIONS, SCOPE_ORDER, format_scopes, parse_scopes
from syncr_api.oauth.config import (
    CODE_CHALLENGE_METHOD_PLAIN,
    CODE_CHALLENGE_METHOD_S256,
    RESPONSE_TYPE_CODE,
)
from syncr_api.oauth.errors import InvalidClient, InvalidRequest
from syncr_api.oauth.pkce import is_well_formed_challenge
from syncr_api.oauth.redirects import is_registered_redirect

if TYPE_CHECKING:
    from syncr_api.core.scopes import Scope
    from syncr_api.oauth.records import ClientRecord

# RFC 6749 section 4.1.2.1 error codes. These reach the client in a query parameter, so they
# are the protocol's spelling rather than syncr's problem types.


class RedirectedError(StrEnum):
    """An authorize failure the client learns about at its redirect URI.

    ``plain`` PKCE and an unsupported response type both arrive here rather than as a
    problem document, because by then the redirect target has been checked against the
    client's registration and is therefore somewhere the answer may safely go.
    """

    INVALID_REQUEST = "invalid_request"
    UNSUPPORTED_RESPONSE_TYPE = "unsupported_response_type"
    INVALID_SCOPE = "invalid_scope"
    ACCESS_DENIED = "access_denied"


# A state value is echoed back verbatim into a redirect and into an HTML form, so it is
# bounded, and a request that exceeds the bound is refused rather than answered without it: a
# client correlating on the value it sent would otherwise get a redirect that silently omits it.
STATE_MAX_LENGTH = 512


@dataclass(frozen=True, slots=True)
class AuthorizeParams:
    """One authorize request exactly as presented, before any rule has been applied."""

    client_id: str
    redirect_uri: str
    response_type: str
    code_challenge: str
    code_challenge_method: str
    scope: str
    state: str | None = None


@dataclass(frozen=True, slots=True)
class ValidatedAuthorization:
    """An authorize request that satisfied every rule, ready for the user to consent to."""

    client: ClientRecord
    redirect_uri: str
    scopes: frozenset[Scope]
    code_challenge: str
    state: str | None

    def as_params(self) -> AuthorizeParams:
        """The request as parameters again, for the consent form to carry back.

        The decision endpoint re-validates from scratch rather than trusting these, so this
        is a form's payload and not a capability: a tampered field yields a different
        request that has to pass the same rules.
        """
        return AuthorizeParams(
            client_id=self.client.id,
            redirect_uri=self.redirect_uri,
            response_type=RESPONSE_TYPE_CODE,
            code_challenge=self.code_challenge,
            code_challenge_method=CODE_CHALLENGE_METHOD_S256,
            scope=format_scopes(self.scopes),
            state=self.state,
        )


@dataclass(frozen=True, slots=True)
class RedirectedRejection:
    """A failure delivered to the client's own redirect URI.

    Carries a description as well as a code, because a client that gets only
    ``invalid_request`` back has to guess which of four rules it broke, and the guess is
    made by a developer wiring a client rather than by an attacker.
    """

    redirect_uri: str
    error: RedirectedError
    description: str
    state: str | None

    @property
    def url(self) -> str:
        """The absolute URL the browser is sent to."""
        return append_query(
            self.redirect_uri,
            {"error": self.error.value, "error_description": self.description}
            | _state_param(self.state),
        )


@dataclass(frozen=True, slots=True)
class GrantedRedirect:
    """The authorization code, delivered to the client's own redirect URI."""

    redirect_uri: str
    code: str
    state: str | None

    @property
    def url(self) -> str:
        """The absolute URL the browser is sent to."""
        return append_query(self.redirect_uri, {"code": self.code} | _state_param(self.state))


@dataclass(frozen=True, slots=True)
class RequestedScope:
    """One scope, as the consent screen shows it: the name granted and what it grants."""

    name: str
    description: str


@dataclass(frozen=True, slots=True)
class ConsentScreen:
    """What the consent screen states, separate from how it is rendered.

    A payload rather than a template's local variables, so the rule "the consent screen
    names the scopes" is assertable without parsing HTML, and so a designed surface can
    render the same values later without the rules moving.
    """

    client_name: str
    account_email: str
    scopes: tuple[RequestedScope, ...]
    request: AuthorizeParams

    @property
    def scope_names(self) -> tuple[str, ...]:
        """Every scope this screen asks the user to grant."""
        return tuple(scope.name for scope in self.scopes)


def validate_authorization(
    params: AuthorizeParams, client: ClientRecord | None
) -> ValidatedAuthorization | RedirectedRejection:
    """Apply every authorize rule to ``params``.

    Raises for the two failures that must not be redirected, and returns a
    :class:`RedirectedRejection` for the rest. The order is the order the protocol
    requires: establish who is asking and where the answer may be sent, and only then judge
    what was asked for.
    """
    if client is None:
        raise InvalidClient(
            "No client is registered under that client_id, so no authorization can be "
            "granted. Nothing was changed."
        )
    if not is_registered_redirect(
        params.redirect_uri, client.redirect_uris, loopback_only=client.loopback_only
    ):
        raise InvalidRequest(
            "That redirect_uri is not registered for this client, so the authorization "
            f"code has nowhere it may be sent. {_redirect_hint(client)}"
        )

    if params.state is not None and len(params.state) > STATE_MAX_LENGTH:
        return RedirectedRejection(
            params.redirect_uri,
            RedirectedError.INVALID_REQUEST,
            f"state must be at most {STATE_MAX_LENGTH} characters, and this one is "
            f"{len(params.state)}. It is echoed back verbatim, so it is bounded.",
            None,
        )
    if params.response_type != RESPONSE_TYPE_CODE:
        return RedirectedRejection(
            params.redirect_uri,
            RedirectedError.UNSUPPORTED_RESPONSE_TYPE,
            f"Only response_type={RESPONSE_TYPE_CODE} is issued.",
            params.state,
        )
    if params.code_challenge_method != CODE_CHALLENGE_METHOD_S256:
        return RedirectedRejection(
            params.redirect_uri,
            RedirectedError.INVALID_REQUEST,
            f"code_challenge_method must be {CODE_CHALLENGE_METHOD_S256}. "
            f"{CODE_CHALLENGE_METHOD_PLAIN} is refused, because it proves nothing to a "
            "client that cannot hold a secret.",
            params.state,
        )
    if not is_well_formed_challenge(params.code_challenge):
        return RedirectedRejection(
            params.redirect_uri,
            RedirectedError.INVALID_REQUEST,
            "code_challenge is not an S256 challenge.",
            params.state,
        )

    requested = parse_scopes(params.scope)
    if requested is None:
        return RedirectedRejection(
            params.redirect_uri,
            RedirectedError.INVALID_SCOPE,
            "scope names a scope this server does not serve.",
            params.state,
        )
    if not client.permits(requested):
        return RedirectedRejection(
            params.redirect_uri,
            RedirectedError.INVALID_SCOPE,
            "scope asks for more than this client is registered for. It may request "
            f"{format_scopes(client.allowed_scopes)}.",
            params.state,
        )

    return ValidatedAuthorization(
        client=client,
        redirect_uri=params.redirect_uri,
        scopes=requested,
        code_challenge=params.code_challenge,
        state=params.state,
    )


def build_consent_screen(
    authorization: ValidatedAuthorization, *, account_email: str
) -> ConsentScreen:
    """The consent screen for a validated request.

    Every requested scope is listed, in the widening order the vocabulary declares, so two
    requests for the same authority present identically and the user reads the least
    authority first.
    """
    held = authorization.scopes
    return ConsentScreen(
        client_name=authorization.client.name,
        account_email=account_email,
        scopes=tuple(
            RequestedScope(name=scope.value, description=SCOPE_DESCRIPTIONS[scope])
            for scope in SCOPE_ORDER
            if scope in held
        ),
        request=authorization.as_params(),
    )


def append_query(uri: str, params: dict[str, str]) -> str:
    """``uri`` with ``params`` added to its query string, preserving what was there."""
    separator = "&" if urlsplit(uri).query else "?"
    return f"{uri}{separator}{urlencode(params)}"


def _state_param(state: str | None) -> dict[str, str]:
    return {} if state is None else {"state": state}


def _redirect_hint(client: ClientRecord) -> str:
    if client.loopback_only:
        return "This client may only redirect to a loopback address on this machine, on any port."
    return "Register the URI first, exactly as it will be presented."
