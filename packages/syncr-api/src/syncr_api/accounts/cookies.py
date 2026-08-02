"""Reading and writing the session cookie.

The attributes are not negotiable and are therefore not parameters. ``HttpOnly`` keeps
the token out of reach of any script, which is what stops an injected script from
exfiltrating a session. ``Secure`` keeps it off a plaintext connection. ``SameSite=Lax``
withholds it from cross-site unsafe requests.

``max_age`` is set rather than left off, which is what makes the session survive a
browser restart: a cookie with no expiry is discarded when the browser closes, and the
user would be signed out by quitting the browser rather than by the session ending.

It carries the ABSOLUTE lifetime, not the idle window, and that is deliberate. The
idle window slides on every use, and a cookie is written once, at sign-in: a browser
told to discard it after the idle window would sign a daily user out on day 14 no
matter how much they used it, and the absolute cap would be unreachable. The server
remains the only authority on when a session stops working, and a browser holding a
cookie the server will reject is harmless, because the server answers 401 and the
shell sends the user to sign in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.accounts.config import (
    SESSION_ABSOLUTE_LIFETIME,
    SESSION_COOKIE_NAME,
    SESSION_COOKIE_PATH,
    SESSION_COOKIE_SAME_SITE,
)

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

    from syncr_api.accounts.session_tokens import SessionToken

# What the browser is told to keep the cookie for. The server's own expiry is shorter
# whenever the session has been idle, so this is an upper bound rather than a claim
# about validity.
COOKIE_MAX_AGE_SECONDS = int(SESSION_ABSOLUTE_LIFETIME.total_seconds())


def read_session_token(request: Request) -> SessionToken | None:
    """The token this request presented, or ``None``."""
    return request.cookies.get(SESSION_COOKIE_NAME)


def set_session_cookie(response: Response, token: SessionToken) -> None:
    """Carry ``token`` back to the browser, for as long as a session can possibly live."""
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=COOKIE_MAX_AGE_SECONDS,
        path=SESSION_COOKIE_PATH,
        httponly=True,
        secure=True,
        samesite=SESSION_COOKIE_SAME_SITE,
    )


def clear_session_cookie(response: Response) -> None:
    """Drop the cookie in the browser.

    Cosmetic on its own: sign-out already revoked the session server-side, which is
    what makes the token unusable. This spares the browser from sending a dead cookie
    on every subsequent request.
    """
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path=SESSION_COOKIE_PATH,
        httponly=True,
        secure=True,
        samesite=SESSION_COOKIE_SAME_SITE,
    )
