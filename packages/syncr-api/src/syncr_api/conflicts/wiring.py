"""Composition for the conflict routes: the one factory the app factory calls.

The tag, the origin check, and the statuses these routes answer are attached here rather than
repeated per route, so a route added to ``api.py`` inherits them.

409 is the one this collection produces most, and it is three states rather than one: a conflict
already answered for, a block nothing may move, and a commitment that has left the calendar. Each
is a fact about the stored state rather than about the request, which is what makes each a conflict
and not a validation failure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends

from syncr_api.accounts.injection import require_trusted_origin
from syncr_api.conflicts.api import router as conflict_routes
from syncr_api.conflicts.config import CONFLICTS_PREFIX
from syncr_api.core.error_handlers import PROBLEM_RESPONSES
from syncr_api.core.errors import Conflict, Forbidden, NotFound, Problem, Unauthorized

if TYPE_CHECKING:
    from collections.abc import Mapping

CONFLICTS_TAG = "conflicts"

# The statuses these routes raise beyond the set every route answers, so the generated document
# describes them and the frontend has types for them.
_CONFLICT_RESPONSES: Mapping[int | str, dict[str, Any]] = {
    Unauthorized.status: {"model": Problem, "description": Unauthorized.title},
    Forbidden.status: {"model": Problem, "description": Forbidden.title},
    NotFound.status: {"model": Problem, "description": NotFound.title},
    Conflict.status: {"model": Problem, "description": Conflict.title},
}


def build_conflicts_router() -> APIRouter:
    """The `/api/v1/conflicts` list and the resolve route."""
    router = APIRouter(
        tags=[CONFLICTS_TAG],
        dependencies=[Depends(require_trusted_origin)],
        responses={**PROBLEM_RESPONSES, **_CONFLICT_RESPONSES},
    )
    router.include_router(conflict_routes, prefix=CONFLICTS_PREFIX)
    return router
