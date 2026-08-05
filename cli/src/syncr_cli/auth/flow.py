"""The authorization code flow with PKCE, as one function.

```
generate code_verifier, derive S256 code_challenge
start a loopback listener on an ephemeral port
open a browser to /oauth/authorize          the consent screen NAMES THE SCOPES
receive the single-use code on the loopback redirect
POST /oauth/token with code + code_verifier
store the refresh token
```

**The browser is opened, not driven.** The consent screen is the server's and it names the scopes
being requested; this client cannot approve on the user's behalf and does not try. Where a
browser cannot be opened at all -- a headless machine, an SSH session -- the URL is printed so it
can be pasted, and the listener keeps waiting.

**A refusal delivered on the redirect is reported as itself.** An unregistered scope arrives as
``error=invalid_scope`` in a query parameter, which is the RFC's spelling and what lets this fail
immediately rather than at the timeout.
"""

from __future__ import annotations

import secrets
import webbrowser
from typing import TYPE_CHECKING, Final
from urllib.parse import urlencode

from syncr_cli.auth.discovery import CLIENT_ID, requested_scope
from syncr_cli.auth.loopback import (
    CONSENT_TIMEOUT_SECONDS,
    LoopbackReceiver,
    require_expected_state,
)
from syncr_cli.auth.pkce import CODE_CHALLENGE_METHOD_S256, derive_challenge, generate_verifier
from syncr_cli.auth.tokens import exchange_code
from syncr_cli.errors import Failure

if TYPE_CHECKING:
    from syncr_cli.auth.discovery import AuthorizationServer
    from syncr_cli.auth.session import Session
    from syncr_cli.http import Transport
    from syncr_cli.notices import Notices
    from syncr_cli.runtime import BrowserOpener

RESPONSE_TYPE_CODE: Final = "code"

# This run's own nonce, echoed back on the redirect. 16 bytes is 22 characters, well inside the
# length the Authorization Server accepts.
STATE_ENTROPY_BYTES: Final = 16


def log_in(
    *,
    transport: Transport,
    server: AuthorizationServer,
    session: Session,
    notices: Notices,
    open_browser: BrowserOpener,
    consent_timeout_seconds: int = CONSENT_TIMEOUT_SECONDS,
) -> tuple[str, ...]:
    """Run the whole flow and store the result. Answers with the scopes that were granted.

    ``consent_timeout_seconds`` bounds how long a person has to sign in and press a button. A
    parameter rather than a setting, because it bounds a human rather than a poll against the API
    and the two want different figures.
    """
    verifier = generate_verifier()
    state = secrets.token_urlsafe(STATE_ENTROPY_BYTES)
    with LoopbackReceiver() as receiver:
        url = authorize_url(
            server, redirect_uri=receiver.redirect_uri, verifier=verifier, state=state
        )
        _open(url, notices, open_browser=open_browser)
        received = receiver.wait(timeout_seconds=consent_timeout_seconds)
        require_expected_state(received, state)
        if received.error is not None:
            raise Failure(
                f"the API refused the authorization request ({received.error}"
                f"{f': {received.error_description}' if received.error_description else ''}). "
                "Nothing was authorized and nothing was stored."
            )
        if received.code is None:
            raise Failure(
                "the browser came back with neither a code nor an error, so nothing was "
                "authorized. Run 'syncr auth login' again."
            )
        tokens = exchange_code(
            transport,
            server,
            code=received.code,
            verifier=verifier,
            redirect_uri=receiver.redirect_uri,
        )
    session.adopt(tokens)
    return tokens.scopes


def authorize_url(
    server: AuthorizationServer, *, redirect_uri: str, verifier: str, state: str
) -> str:
    """Where the browser is sent, with every parameter the flow requires.

    ``code_challenge_method`` is stated rather than left out. RFC 7636 reads an absent method as
    ``plain``, so omitting it would be choosing the mode that proves nothing.
    """
    parameters = {
        "client_id": CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": RESPONSE_TYPE_CODE,
        "code_challenge": derive_challenge(verifier),
        "code_challenge_method": CODE_CHALLENGE_METHOD_S256,
        "scope": requested_scope(),
        "state": state,
    }
    return f"{server.authorization_endpoint}?{urlencode(parameters)}"


def _open(url: str, notices: Notices, *, open_browser: BrowserOpener) -> None:
    """Open the consent screen, and say where it is either way.

    The URL is always stated. A browser that opened on another display, or a machine with none,
    leaves the user with a listener and no idea what it is waiting for.
    """
    try:
        opened = open_browser(url)
    except webbrowser.Error:
        opened = False
    if opened:
        notices.state(f"Opened a browser to approve the requested scopes: {url}")
        return
    notices.state(f"Open this URL to approve the requested scopes: {url}")
