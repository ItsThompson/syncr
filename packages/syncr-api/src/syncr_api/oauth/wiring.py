"""Composition for the Authorization Server: the one factory the app factory calls.

Two routers are mounted under one parent, and that is not tidiness. ``/oauth/...`` is syncr's
own path and could be anything; ``/.well-known/oauth-authorization-server`` is fixed by RFC
8414 at the origin's root, and a client looks for it there and nowhere else. A single prefixed
router could not serve both, so the parent carries no prefix and each child carries its own.

The error responses these routes can answer are attached here rather than repeated per route,
so a route added to ``api.py`` inherits them and the generated document keeps describing what
the api actually sends.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter

from syncr_api.core.error_handlers import PROBLEM_RESPONSES
from syncr_api.core.errors import (
    Forbidden,
    MalformedRequest,
    NotFound,
    OriginRejected,
    Problem,
    Unauthorized,
)
from syncr_api.oauth.api import router as oauth_routes
from syncr_api.oauth.api import well_known_router as well_known_routes
from syncr_api.oauth.config import OAUTH_PREFIX, WELL_KNOWN_PREFIX

if TYPE_CHECKING:
    from collections.abc import Mapping

OAUTH_TAG = "oauth"

# The statuses these routes actually raise. 400 is the protocol's own vocabulary
# (`invalid_request`, `invalid_grant`, `invalid_scope`, `unsupported_grant_type`), 401 is an
# unknown client or an unusable credential, 403 is an untrusted origin on the consent decision
# or a scope a token does not carry, and 404 is the account behind a session that stopped
# working.
_OAUTH_RESPONSES: Mapping[int | str, dict[str, Any]] = {
    MalformedRequest.status: {"model": Problem, "description": MalformedRequest.title},
    Unauthorized.status: {"model": Problem, "description": Unauthorized.title},
    Forbidden.status: {"model": Problem, "description": OriginRejected.title},
    NotFound.status: {"model": Problem, "description": NotFound.title},
}


def build_oauth_router() -> APIRouter:
    """The Authorization Server's routes: consent, tokens, revocation, and discovery."""
    router = APIRouter(tags=[OAUTH_TAG], responses={**PROBLEM_RESPONSES, **_OAUTH_RESPONSES})
    router.include_router(oauth_routes, prefix=OAUTH_PREFIX)
    router.include_router(well_known_routes, prefix=WELL_KNOWN_PREFIX)
    return router
