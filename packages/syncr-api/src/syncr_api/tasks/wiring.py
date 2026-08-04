"""Composition for the tasks module: the one factory the app factory calls.

The prefix, the tag, the origin check, and the statuses these routes answer are attached here
rather than repeated per route, so a route added to ``api.py`` inherits them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends

from syncr_api.accounts.injection import require_trusted_origin
from syncr_api.core.error_handlers import PROBLEM_RESPONSES
from syncr_api.core.errors import Conflict, Forbidden, NotFound, Problem, Unauthorized
from syncr_api.tasks.api import router as tasks_router
from syncr_api.tasks.config import TASKS_PREFIX

if TYPE_CHECKING:
    from collections.abc import Mapping

TASKS_TAG = "tasks"

# The statuses these routes raise beyond the set every route answers, so the generated document
# describes them and the frontend has types for them. 409 is either an idempotency key still in
# flight or a task already ended the other way; a minimum chunk that does not fit is a 422,
# because it is a bad pair of values rather than a conflict with the current state.
_TASKS_RESPONSES: Mapping[int | str, dict[str, Any]] = {
    Unauthorized.status: {"model": Problem, "description": Unauthorized.title},
    Forbidden.status: {"model": Problem, "description": Forbidden.title},
    NotFound.status: {"model": Problem, "description": NotFound.title},
    Conflict.status: {"model": Problem, "description": Conflict.title},
}


def build_tasks_router() -> APIRouter:
    """The `/api/v1/tasks` routes.

    The prefix is applied at the include rather than on the router itself, because two routes ARE
    the prefix: ``GET`` and ``POST`` answer it with nothing after it, and the framework refuses a
    route whose own path and whose include prefix are both empty.
    """
    router = APIRouter(
        tags=[TASKS_TAG],
        dependencies=[Depends(require_trusted_origin)],
        responses={**PROBLEM_RESPONSES, **_TASKS_RESPONSES},
    )
    router.include_router(tasks_router, prefix=TASKS_PREFIX)
    return router
