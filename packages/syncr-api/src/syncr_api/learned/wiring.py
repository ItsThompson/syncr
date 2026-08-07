"""Composition for the learning routes: the one factory the app factory calls.

Two prefixes on one router, because the two collections answer different questions and share every
concern around them: the tag, the origin check, and the statuses. A route added to either sub-router
inherits all three.

There is no 409. Activating the version already in force is a no-op flip plus a re-solve, which is
what the caller asked for either way, so there is no stored state for the request to conflict with.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends

from syncr_api.accounts.injection import require_trusted_origin
from syncr_api.core.error_handlers import PROBLEM_RESPONSES
from syncr_api.core.errors import Forbidden, NotFound, Problem, Unauthorized
from syncr_api.learned.api import learned_router, weight_set_router
from syncr_api.learned.config import LEARNED_PREFIX, WEIGHT_SETS_PREFIX

if TYPE_CHECKING:
    from collections.abc import Mapping

LEARNED_TAG = "learned"

# The statuses these routes raise beyond the set every route answers. 404 is the activation naming a
# version this account does not hold; the two reads cannot produce one, because an account with no
# fitted parameters has a version 1 that says so.
_LEARNED_RESPONSES: Mapping[int | str, dict[str, Any]] = {
    Unauthorized.status: {"model": Problem, "description": Unauthorized.title},
    Forbidden.status: {"model": Problem, "description": Forbidden.title},
    NotFound.status: {"model": Problem, "description": NotFound.title},
}


def build_learned_router() -> APIRouter:
    """The `/api/v1/learned` read, the `/api/v1/weight-sets` list, and the activation."""
    router = APIRouter(
        tags=[LEARNED_TAG],
        dependencies=[Depends(require_trusted_origin)],
        responses={**PROBLEM_RESPONSES, **_LEARNED_RESPONSES},
    )
    router.include_router(learned_router, prefix=LEARNED_PREFIX)
    router.include_router(weight_set_router, prefix=WEIGHT_SETS_PREFIX)
    return router
