"""Composition for the preferences module: the one factory the app factory calls.

Three singleton sub-resources, three routers, one prefix each. The tag, the origin check, and the
statuses these routes answer are attached once, so a route added to ``api.py`` inherits them.

The three routers are separate because their paths hang under three different collections, and each
is mounted at its full path rather than at a shared one: there is no ``/preferences`` collection to
hang them under, and inventing one would be a second way to address a preference.

Nothing here is registered by the areas, habits, or backlog modules. A preference is authored
through its owner's own sub-resource, and this package is what mounts those, so adding preferences
edited none of those three modules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends

from syncr_api.accounts.injection import require_trusted_origin
from syncr_api.core.error_handlers import PROBLEM_RESPONSES
from syncr_api.core.errors import Forbidden, NotFound, Problem, Unauthorized
from syncr_api.preferences.api import (
    area_router,
    habit_router,
    task_router,
)
from syncr_api.preferences.config import (
    AREA_PREFERENCE_PATH,
    HABIT_PREFERENCE_PATH,
    TASK_PREFERENCE_PATH,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

PREFERENCES_TAG = "preferences"

# The statuses these routes raise beyond the set every route answers, so the generated document
# describes them and the frontend has types for them. No 409: nothing here conflicts, because a
# preference is replaced whole and an owner has one or none.
_PREFERENCES_RESPONSES: Mapping[int | str, dict[str, Any]] = {
    Unauthorized.status: {"model": Problem, "description": Unauthorized.title},
    Forbidden.status: {"model": Problem, "description": Forbidden.title},
    NotFound.status: {"model": Problem, "description": NotFound.title},
}


def build_preferences_router() -> APIRouter:
    """The three `preference` sub-resources, under the Areas, habits, and tasks collections."""
    router = APIRouter(
        tags=[PREFERENCES_TAG],
        dependencies=[Depends(require_trusted_origin)],
        responses={**PROBLEM_RESPONSES, **_PREFERENCES_RESPONSES},
    )
    router.include_router(area_router, prefix=AREA_PREFERENCE_PATH)
    router.include_router(habit_router, prefix=HABIT_PREFERENCE_PATH)
    router.include_router(task_router, prefix=TASK_PREFERENCE_PATH)
    return router
