"""The three authentication routes.

Thin, on purpose. Each handler validates a body, resolves who is asking, calls exactly
one collaborator method, and translates the result into a response. There is no
authorization decision here and no persistence: those belong to ``service.py`` and
``repository.py``, and ``tests/test_authorization_boundary.py`` asserts this file
cannot reach either of them.

Sign-in is the one route in the application that resolves no principal, because it is
what produces one. ``tests/test_authorization_boundary.py`` holds the allowlist of
such routes and asserts every other route resolves one, so a second unauthenticated
route is a visible edit to the file named for the boundary rather than a quiet
omission in a router.
"""

from __future__ import annotations

from http import HTTPStatus

from fastapi import APIRouter
from starlette.responses import Response

from syncr_api.accounts.cookies import clear_session_cookie, set_session_cookie
from syncr_api.accounts.injection import (
    AuthenticatorDep,
    PrincipalDep,
    SessionIdDep,
    SessionServiceDep,
)
from syncr_api.accounts.schemas import LoginRequest, SessionResponse
from syncr_api.core.clock import utc_now

router = APIRouter()


@router.post("/login", summary="Establish a browser session")
async def log_in(
    body: LoginRequest, response: Response, authenticator: AuthenticatorDep
) -> SessionResponse:
    """Verify credentials, establish a session, and set the cookie that carries it."""
    established = await authenticator.log_in(body.email, body.password)
    set_session_cookie(
        response, established.token, expires_at=established.expires_at, now=utc_now()
    )
    return SessionResponse(
        tenant_id=established.principal.tenant_id,
        user_id=established.principal.user_id,
        email=established.email,
        expires_at=established.expires_at,
    )


@router.get("/session", summary="The current principal")
async def read_session(
    principal: PrincipalDep, session_id: SessionIdDep, service: SessionServiceDep
) -> SessionResponse:
    """The signed-in principal, or 401 when the presented session no longer works."""
    described = await service.describe(principal, session_id)
    return SessionResponse(
        tenant_id=described.tenant_id,
        user_id=described.user_id,
        email=described.email,
        expires_at=described.expires_at,
    )


@router.post(
    "/logout",
    status_code=HTTPStatus.NO_CONTENT,
    response_class=Response,
    summary="Revoke the current session",
)
async def log_out(
    principal: PrincipalDep, session_id: SessionIdDep, service: SessionServiceDep
) -> Response:
    """Revoke server-side and drop the cookie, so the token cannot be replayed."""
    await service.log_out(principal, session_id)
    # Built here rather than by returning None with a 204 status, because a returned
    # None is still serialized and a 204 must carry no body at all.
    response = Response(status_code=HTTPStatus.NO_CONTENT)
    clear_session_cookie(response)
    return response
