"""Composition for the accounts module: the one factory the app factory calls.

The prefix, the tag, the error responses the routes can answer, and the origin check
are attached here rather than repeated on each route, so a route added to ``api.py``
inherits them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends

from syncr_api.accounts.api import router as auth_routes
from syncr_api.accounts.config import AUTH_PREFIX
from syncr_api.accounts.injection import require_trusted_origin
from syncr_api.core.error_handlers import PROBLEM_RESPONSES
from syncr_api.core.errors import NotFound, OriginRejected, Problem, Unauthorized

if TYPE_CHECKING:
    from collections.abc import Mapping

AUTH_TAG = "auth"

# The statuses these routes actually raise, added to the set every route answers, so
# the generated document describes them and the frontend generates types for them.
_AUTH_RESPONSES: Mapping[int | str, dict[str, Any]] = {
    Unauthorized.status: {"model": Problem, "description": Unauthorized.title},
    OriginRejected.status: {"model": Problem, "description": OriginRejected.title},
    NotFound.status: {"model": Problem, "description": NotFound.title},
}


def build_accounts_router() -> APIRouter:
    """The `/auth` router: sign in, read the session, sign out."""
    router = APIRouter(
        prefix=AUTH_PREFIX,
        tags=[AUTH_TAG],
        dependencies=[Depends(require_trusted_origin)],
        responses={**PROBLEM_RESPONSES, **_AUTH_RESPONSES},
    )
    router.include_router(auth_routes)
    return router
