"""``auth login``, ``auth logout``, and ``auth status``.

Three commands, one credential. Login runs the flow and stores the refresh token; logout revokes
it server-side before removing it locally, because deleting a local file leaves a live grant;
status reports the principal and the granted scopes from the token it holds.

**Logout revokes first and removes second.** If revocation fails, the local token is left where
it is: a user who has been told the grant is dead must not also have lost the credential that
would let them try again.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_cli.auth.flow import log_in
from syncr_cli.auth.tokens import revoke
from syncr_cli.parser import add_verb, register_command
from syncr_cli.rendering.auth_views import LoginView, LogoutView, StatusView
from syncr_cli.results import CliResult

if TYPE_CHECKING:
    from syncr_cli.parser import Invocation, Parser, Verbs
    from syncr_cli.runtime import Runtime

NOUN = "auth"


def register(nouns: Verbs, shared: Parser) -> None:
    """Put the three authorization commands in the catalog."""
    verbs = add_verb(
        nouns, shared, noun=NOUN, noun_help="Authorize this machine, and report what it holds"
    )
    register_command(
        verbs,
        noun=NOUN,
        verb="login",
        summary=(
            "Authorize this machine through a browser, with PKCE. Requests plan:read and "
            "plan:write, and never admin"
        ),
        handler=login,
        shared=shared,
        examples=("syncr auth login", "syncr auth login --api-url https://syncr.example"),
    )
    register_command(
        verbs,
        noun=NOUN,
        verb="logout",
        summary="Revoke this machine's refresh token server-side, and remove it locally",
        handler=logout,
        shared=shared,
        examples=("syncr auth logout",),
    )
    register_command(
        verbs,
        noun=NOUN,
        verb="status",
        summary="The principal this machine is authenticated as, and the scopes it was granted",
        handler=status,
        shared=shared,
        examples=("syncr auth status", "syncr auth status --json"),
    )


def login(runtime: Runtime, _invocation: Invocation) -> CliResult:
    """Run the authorization code flow and store what it produced."""
    scopes = log_in(
        transport=runtime.transport,
        server=runtime.server,
        session=runtime.session,
        notices=runtime.notices,
        open_browser=runtime.host.open_browser,
    )
    return CliResult.succeeded(
        LoginView(
            api_url=runtime.settings.api_url,
            scopes=scopes,
            token_location=runtime.store.location,
            fell_back=runtime.store.fell_back,
        )
    )


def logout(runtime: Runtime, _invocation: Invocation) -> CliResult:
    """Revoke the stored grant server-side, then remove the token from this machine."""
    stored = runtime.store.read()
    if stored is None:
        return CliResult.succeeded(LogoutView(api_url=runtime.settings.api_url, revoked=False))
    revoke(runtime.transport, runtime.server, refresh_token=stored)
    runtime.store.clear()
    return CliResult.succeeded(LogoutView(api_url=runtime.settings.api_url, revoked=True))


def status(runtime: Runtime, _invocation: Invocation) -> CliResult:
    """Report the principal and the scopes, from a freshly refreshed access token."""
    claims = runtime.session.claims
    return CliResult.succeeded(
        StatusView(
            api_url=runtime.settings.api_url,
            claims=claims,
            token_location=runtime.store.location,
            fell_back=runtime.store.fell_back,
        )
    )
