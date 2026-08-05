"""Composition for the concession module: the one factory the app factory calls.

One collection, one router. The prefix, the tag, the origin check, and the statuses these routes
answer are attached here rather than repeated per route, so a route added to ``api.py`` inherits
them.

The prefix is the week collection, because both paths hang off one week and the week is the resource
they belong to. The route table's other week routes are ticket 31's and join the same prefix from
their own module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends

from syncr_api.accounts.injection import require_trusted_origin
from syncr_api.concessions.api import router as concession_routes
from syncr_api.concessions.config import WEEKS_PREFIX
from syncr_api.core.error_handlers import PROBLEM_RESPONSES
from syncr_api.core.errors import Conflict, Forbidden, NotFound, Problem, Unauthorized

if TYPE_CHECKING:
    from collections.abc import Mapping

CONCESSIONS_TAG = "concessions"

# The statuses these routes raise beyond the set every route answers, so the generated document
# describes them and the frontend has types for them. 409 is the one conflict this module can
# produce: a solve of that week is already RUNNING, so there is no second non-terminal solve to
# create and a tradeoff request may not join the one that exists.
_CONCESSION_RESPONSES: Mapping[int | str, dict[str, Any]] = {
    Unauthorized.status: {"model": Problem, "description": Unauthorized.title},
    Forbidden.status: {"model": Problem, "description": Forbidden.title},
    NotFound.status: {"model": Problem, "description": NotFound.title},
    Conflict.status: {"model": Problem, "description": Conflict.title},
}


def build_concessions_router() -> APIRouter:
    """The `/api/v1/weeks/{iso_week}` tradeoff and concession routes."""
    router = APIRouter(
        tags=[CONCESSIONS_TAG],
        dependencies=[Depends(require_trusted_origin)],
        responses={**PROBLEM_RESPONSES, **_CONCESSION_RESPONSES},
    )
    router.include_router(concession_routes, prefix=WEEKS_PREFIX)
    return router
