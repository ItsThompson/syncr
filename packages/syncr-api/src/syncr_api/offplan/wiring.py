"""Composition for the off-plan module: the one factory the app factory calls.

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
from syncr_api.offplan.api import router as off_plan_routes
from syncr_api.offplan.config import OFF_PLAN_PREFIX

if TYPE_CHECKING:
    from collections.abc import Mapping

OFF_PLAN_TAG = "off-plan"

# The statuses these routes raise beyond the set every route answers, so the generated document
# describes them and the frontend has types for them. 409 is a span overlapping one already
# declared, which is the one conflict this module can produce: a span of any length, at any hour,
# is otherwise a legitimate declaration.
_OFF_PLAN_RESPONSES: Mapping[int | str, dict[str, Any]] = {
    Unauthorized.status: {"model": Problem, "description": Unauthorized.title},
    Forbidden.status: {"model": Problem, "description": Forbidden.title},
    NotFound.status: {"model": Problem, "description": NotFound.title},
    Conflict.status: {"model": Problem, "description": Conflict.title},
}


def build_off_plan_router() -> APIRouter:
    """The `/api/v1/off-plan` routes.

    The prefix is applied at the include rather than on the router itself, because two of the
    four routes ARE the prefix: ``GET`` and ``POST`` answer it with nothing after it, and the
    framework refuses a route whose own path and whose include prefix are both empty.
    """
    router = APIRouter(
        tags=[OFF_PLAN_TAG],
        dependencies=[Depends(require_trusted_origin)],
        responses={**PROBLEM_RESPONSES, **_OFF_PLAN_RESPONSES},
    )
    router.include_router(off_plan_routes, prefix=OFF_PLAN_PREFIX)
    return router
