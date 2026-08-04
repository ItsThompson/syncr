"""Composition for the routines module: the one factory the app factory calls.

One collection, one router. The prefix, the tag, the origin check, and the statuses these routes
answer are attached here rather than repeated per route, so a route added to ``api.py`` inherits
them.

No 409 is declared, and the absence is a statement: a routine has no uniqueness to conflict with.
Two routines may share a title, and a span that will not fit is not a conflict either, because
the frame is what defines how much time exists rather than something competing for it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends

from syncr_api.accounts.injection import require_trusted_origin
from syncr_api.core.error_handlers import PROBLEM_RESPONSES
from syncr_api.core.errors import Forbidden, NotFound, Problem, Unauthorized
from syncr_api.routines.api import router as routines_router
from syncr_api.routines.config import ROUTINES_PREFIX

if TYPE_CHECKING:
    from collections.abc import Mapping

ROUTINES_TAG = "routines"

# The statuses these routes raise beyond the set every route answers, so the generated document
# describes them and the frontend has types for them.
_ROUTINES_RESPONSES: Mapping[int | str, dict[str, Any]] = {
    Unauthorized.status: {"model": Problem, "description": Unauthorized.title},
    Forbidden.status: {"model": Problem, "description": Forbidden.title},
    NotFound.status: {"model": Problem, "description": NotFound.title},
}


def build_routines_router() -> APIRouter:
    """The `/api/v1/routines` routes.

    The prefix is applied at the include rather than on the router itself, because two routes ARE
    the prefix: ``GET`` and ``POST`` answer it with nothing after it, and the framework refuses a
    route whose own path and whose include prefix are both empty.
    """
    router = APIRouter(
        tags=[ROUTINES_TAG],
        dependencies=[Depends(require_trusted_origin)],
        responses={**PROBLEM_RESPONSES, **_ROUTINES_RESPONSES},
    )
    router.include_router(routines_router, prefix=ROUTINES_PREFIX)
    return router
