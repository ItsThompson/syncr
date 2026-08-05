"""Composition for the solving module: the one factory the app factory calls.

One collection, one router. The prefix, the tag, the origin check, and the statuses these routes
answer are attached here rather than repeated per route, so a route added to ``api.py`` inherits
them.

No 409 and no 422 beyond the shared set: both routes are reads, and the two rejections they can
produce -- an unknown status or kind, and a page cursor this api did not mint -- are validation
failures, which every route already answers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends

from syncr_api.accounts.injection import require_trusted_origin
from syncr_api.core.error_handlers import PROBLEM_RESPONSES
from syncr_api.core.errors import Forbidden, NotFound, Problem, Unauthorized
from syncr_api.solving.api import router as operation_routes
from syncr_api.solving.config import OPERATIONS_PREFIX

if TYPE_CHECKING:
    from collections.abc import Mapping

OPERATIONS_TAG = "operations"

_OPERATION_RESPONSES: Mapping[int | str, dict[str, Any]] = {
    Unauthorized.status: {"model": Problem, "description": Unauthorized.title},
    Forbidden.status: {"model": Problem, "description": Forbidden.title},
    NotFound.status: {"model": Problem, "description": NotFound.title},
}


def build_operations_router() -> APIRouter:
    """The `/api/v1/operations` routes.

    The prefix is applied at the include rather than on the router itself, because the list route
    IS the prefix: it answers it with nothing after it, and the framework refuses a route whose own
    path and whose include prefix are both empty.
    """
    router = APIRouter(
        tags=[OPERATIONS_TAG],
        dependencies=[Depends(require_trusted_origin)],
        responses={**PROBLEM_RESPONSES, **_OPERATION_RESPONSES},
    )
    router.include_router(operation_routes, prefix=OPERATIONS_PREFIX)
    return router
