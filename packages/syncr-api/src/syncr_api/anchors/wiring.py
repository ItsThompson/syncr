"""Composition for the anchor module: the one factory the app factory calls.

Two collections, one router. The prefixes, the tag, the origin check, and the statuses these
routes answer are attached here rather than repeated per route, so a route added to ``api.py``
inherits them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends

from syncr_api.accounts.injection import require_trusted_origin
from syncr_api.anchors.api import anchor_types_router, anchors_router
from syncr_api.anchors.config import ANCHOR_TYPES_PREFIX, ANCHORS_PREFIX
from syncr_api.core.error_handlers import PROBLEM_RESPONSES
from syncr_api.core.errors import Conflict, Forbidden, NotFound, Problem, Unauthorized

if TYPE_CHECKING:
    from collections.abc import Mapping

ANCHORS_TAG = "anchors"

# The statuses these routes raise beyond the set every route answers, so the generated document
# describes them and the frontend has types for them. 409 is two conflicts: a name another type
# already holds, and a tenant already holding as many types as syncr evaluates.
_ANCHOR_RESPONSES: Mapping[int | str, dict[str, Any]] = {
    Unauthorized.status: {"model": Problem, "description": Unauthorized.title},
    Forbidden.status: {"model": Problem, "description": Forbidden.title},
    NotFound.status: {"model": Problem, "description": NotFound.title},
    Conflict.status: {"model": Problem, "description": Conflict.title},
}


def build_anchors_router() -> APIRouter:
    """The `/api/v1/anchors` and `/api/v1/anchor-types` routes.

    The prefixes are applied at the include rather than on the routers themselves, because a route
    in each collection IS the prefix: ``GET`` on anchors and ``GET``/``POST`` on anchor types
    answer it with nothing after it, and the framework refuses a route whose own path and whose
    include prefix are both empty.
    """
    router = APIRouter(
        tags=[ANCHORS_TAG],
        dependencies=[Depends(require_trusted_origin)],
        responses={**PROBLEM_RESPONSES, **_ANCHOR_RESPONSES},
    )
    router.include_router(anchors_router, prefix=ANCHORS_PREFIX)
    router.include_router(anchor_types_router, prefix=ANCHOR_TYPES_PREFIX)
    return router
