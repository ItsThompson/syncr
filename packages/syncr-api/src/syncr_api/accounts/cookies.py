"""Reading and writing the session cookie.

The attributes are not negotiable and are therefore not parameters. ``HttpOnly`` keeps
the token out of reach of any script, which is what stops an injected script from
exfiltrating a session. ``Secure`` keeps it off a plaintext connection. ``SameSite=Lax``
withholds it from cross-site unsafe requests.

``max_age`` is set rather than left off, which is what makes the session survive a
browser restart: a cookie with no expiry is discarded when the browser closes, and the
user would be signed out by quitting the browser rather than by the session ending.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.accounts.config import (
    SESSION_COOKIE_NAME,
    SESSION_COOKIE_PATH,
    SESSION_COOKIE_SAME_SITE,
)

if TYPE_CHECKING:
    from datetime import datetime

    from starlette.requests import Request
    from starlette.responses import Response

    from syncr_api.accounts.session_tokens import SessionToken


def read_session_token(request: Request) -> SessionToken | None:
    """The token this request presented, or ``None``."""
    return request.cookies.get(SESSION_COOKIE_NAME)


def set_session_cookie(
    response: Response, token: SessionToken, *, expires_at: datetime, now: datetime
) -> None:
    """Carry ``token`` back to the browser, expiring when the session does."""
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=max(int((expires_at - now).total_seconds()), 0),
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
