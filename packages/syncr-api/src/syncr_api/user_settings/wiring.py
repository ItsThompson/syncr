"""Composition for the settings module: the one factory the app factory calls.

The prefix, the tag, the origin check, and the statuses these routes answer are attached
here rather than repeated per route, so a route added to ``api.py`` inherits them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends

from syncr_api.accounts.injection import require_trusted_origin
from syncr_api.core.error_handlers import PROBLEM_RESPONSES
from syncr_api.core.errors import Conflict, NotFound, Problem, Unauthorized
from syncr_api.user_settings.api import router as settings_routes
from syncr_api.user_settings.config import SETTINGS_PREFIX

if TYPE_CHECKING:
    from collections.abc import Mapping

SETTINGS_TAG = "settings"

# The statuses these routes raise beyond the set every route answers, so the generated
# document describes them and the frontend has types for them. 409 is the overlapping
# travel override, which is the one conflict this module can produce.
_SETTINGS_RESPONSES: Mapping[int | str, dict[str, Any]] = {
    Unauthorized.status: {"model": Problem, "description": Unauthorized.title},
    NotFound.status: {"model": Problem, "description": NotFound.title},
    Conflict.status: {"model": Problem, "description": Conflict.title},
}


def build_settings_router() -> APIRouter:
    """The `/api/v1/settings` router: settings, and travel overrides.

    The prefix is applied at the include rather than on the router itself, because two of
    these routes ARE the prefix: ``GET`` and ``PATCH`` answer ``/api/v1/settings`` with
    nothing after it, and the framework refuses a route whose own path and whose include
    prefix are both empty.
    """
    router = APIRouter(
        tags=[SETTINGS_TAG],
        dependencies=[Depends(require_trusted_origin)],
        responses={**PROBLEM_RESPONSES, **_SETTINGS_RESPONSES},
    )
    router.include_router(settings_routes, prefix=SETTINGS_PREFIX)
    return router
