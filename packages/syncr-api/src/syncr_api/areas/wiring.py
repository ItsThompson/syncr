"""Composition for the Areas module: the one factory the app factory calls.

Two collections, one router. The prefix, the tag, the origin check, and the statuses these
routes answer are attached here rather than repeated per route, so a route added to ``api.py``
inherits them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends

from syncr_api.accounts.injection import require_trusted_origin
from syncr_api.areas.api import areas_router, projects_router
from syncr_api.areas.config import AREAS_PREFIX, PROJECTS_PREFIX
from syncr_api.core.error_handlers import PROBLEM_RESPONSES
from syncr_api.core.errors import Conflict, Forbidden, NotFound, Problem, Unauthorized

if TYPE_CHECKING:
    from collections.abc import Mapping

AREAS_TAG = "areas"

# The statuses these routes raise beyond the set every route answers, so the generated document
# describes them and the frontend has types for them. 409 is a name another Area already holds,
# which is the one conflict this module can produce: a share that does not fit is reported as
# oversubscription rather than refused.
_AREAS_RESPONSES: Mapping[int | str, dict[str, Any]] = {
    Unauthorized.status: {"model": Problem, "description": Unauthorized.title},
    Forbidden.status: {"model": Problem, "description": Forbidden.title},
    NotFound.status: {"model": Problem, "description": NotFound.title},
    Conflict.status: {"model": Problem, "description": Conflict.title},
}


def build_areas_router() -> APIRouter:
    """The `/api/v1/areas` and `/api/v1/projects` routes.

    The prefixes are applied at the include rather than on the routers themselves, because two
    routes in each collection ARE the prefix: ``GET`` and ``POST`` answer it with nothing after
    it, and the framework refuses a route whose own path and whose include prefix are both
    empty.
    """
    router = APIRouter(
        tags=[AREAS_TAG],
        dependencies=[Depends(require_trusted_origin)],
        responses={**PROBLEM_RESPONSES, **_AREAS_RESPONSES},
    )
    router.include_router(areas_router, prefix=AREAS_PREFIX)
    router.include_router(projects_router, prefix=PROJECTS_PREFIX)
    return router
