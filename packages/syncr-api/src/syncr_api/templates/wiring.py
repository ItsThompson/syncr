"""Composition for the day-shape module: the one factory the app factory calls.

Three collections, one router. The prefixes, the tag, the origin check, and the statuses these
routes answer are attached here rather than repeated per route, so a route added to ``api.py``
inherits them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends

from syncr_api.accounts.injection import require_trusted_origin
from syncr_api.core.error_handlers import PROBLEM_RESPONSES
from syncr_api.core.errors import Conflict, Forbidden, NotFound, Problem, Unauthorized
from syncr_api.templates.api import day_types_router, templates_router, week_pattern_router
from syncr_api.templates.config import (
    DAY_TYPES_PREFIX,
    TEMPLATES_PREFIX,
    WEEK_PATTERN_PREFIX,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

TEMPLATES_TAG = "templates"

# The statuses these routes raise beyond the set every route answers, so the generated document
# describes them and the frontend has types for them. 409 is a day-type name another already
# holds, or a second shape for a day type that has one: both are conflicts with what exists
# rather than bad requests.
_TEMPLATES_RESPONSES: Mapping[int | str, dict[str, Any]] = {
    Unauthorized.status: {"model": Problem, "description": Unauthorized.title},
    Forbidden.status: {"model": Problem, "description": Forbidden.title},
    NotFound.status: {"model": Problem, "description": NotFound.title},
    Conflict.status: {"model": Problem, "description": Conflict.title},
}


def build_templates_router() -> APIRouter:
    """The `/api/v1/day-types`, `/api/v1/templates`, and `/api/v1/week-pattern` routes.

    The prefixes are applied at the include rather than on the routers themselves, because
    several routes ARE the prefix: they answer it with nothing after it, and the framework
    refuses a route whose own path and whose include prefix are both empty.
    """
    router = APIRouter(
        tags=[TEMPLATES_TAG],
        dependencies=[Depends(require_trusted_origin)],
        responses={**PROBLEM_RESPONSES, **_TEMPLATES_RESPONSES},
    )
    router.include_router(day_types_router, prefix=DAY_TYPES_PREFIX)
    router.include_router(templates_router, prefix=TEMPLATES_PREFIX)
    router.include_router(week_pattern_router, prefix=WEEK_PATTERN_PREFIX)
    return router
