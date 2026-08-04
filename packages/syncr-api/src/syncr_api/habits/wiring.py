"""Composition for the habits module: the one factory the app factory calls.

One collection, one router. The prefix, the tag, the origin check, and the statuses these routes
answer are attached here rather than repeated per route, so a route added to ``api.py`` inherits
them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends

from syncr_api.accounts.injection import require_trusted_origin
from syncr_api.core.error_handlers import PROBLEM_RESPONSES
from syncr_api.core.errors import Conflict, Forbidden, NotFound, Problem, Unauthorized
from syncr_api.habits.api import router as habits_router
from syncr_api.habits.config import HABITS_PREFIX

if TYPE_CHECKING:
    from collections.abc import Mapping

HABITS_TAG = "habits"

# The statuses these routes raise beyond the set every route answers, so the generated document
# describes them and the frontend has types for them. 409 is the idempotency guard's in-flight
# answer, which every unsafe route here can produce.
_HABITS_RESPONSES: Mapping[int | str, dict[str, Any]] = {
    Unauthorized.status: {"model": Problem, "description": Unauthorized.title},
    Forbidden.status: {"model": Problem, "description": Forbidden.title},
    NotFound.status: {"model": Problem, "description": NotFound.title},
    Conflict.status: {"model": Problem, "description": Conflict.title},
}


def build_habits_router() -> APIRouter:
    """The `/api/v1/habits` routes.

    The prefix is applied at the include rather than on the router itself, because two routes ARE
    the prefix: ``GET`` and ``POST`` answer it with nothing after it, and the framework refuses a
    route whose own path and whose include prefix are both empty.
    """
    router = APIRouter(
        tags=[HABITS_TAG],
        dependencies=[Depends(require_trusted_origin)],
        responses={**PROBLEM_RESPONSES, **_HABITS_RESPONSES},
    )
    router.include_router(habits_router, prefix=HABITS_PREFIX)
    return router
