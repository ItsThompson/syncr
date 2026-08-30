"""Composition for the week routes: the one factory the app factory calls.

The prefix is the week collection, which the concession routes already hang off, so the seven
routes of the week table are one collection served by two modules rather than two
collections that happen to share a URL.

The tag, the origin check, and the statuses these routes answer are attached here rather than
repeated per route, so a route added to ``api.py`` inherits them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends

from syncr_api.accounts.injection import require_trusted_origin
from syncr_api.concessions.config import WEEKS_PREFIX
from syncr_api.core.error_handlers import PROBLEM_RESPONSES
from syncr_api.core.errors import Conflict, Forbidden, Problem, Unauthorized
from syncr_api.plans.api import router as week_routes

if TYPE_CHECKING:
    from collections.abc import Mapping

WEEKS_TAG = "weeks"

# The statuses these routes raise beyond the set every route answers, so the generated document
# describes them and the frontend has types for them.
#
# There is no 404 among them, deliberately. Every ISO week identifier names a week, so a week with
# no plan is a 200 carrying a null and a stated reason: answering 404 would make navigating past
# the horizon look like a broken link rather than the product's own boundary.
#
# 409 is the one conflict these routes produce: a solve was asked for on a tenant that has not
# declared what a plan needs, which is a fact about the account rather than about the request.
_WEEK_RESPONSES: Mapping[int | str, dict[str, Any]] = {
    Unauthorized.status: {"model": Problem, "description": Unauthorized.title},
    Forbidden.status: {"model": Problem, "description": Forbidden.title},
    Conflict.status: {"model": Problem, "description": Conflict.title},
}


def build_weeks_router() -> APIRouter:
    """The `/api/v1/weeks/{iso_week}` view, history, verdict, and solve routes."""
    router = APIRouter(
        tags=[WEEKS_TAG],
        dependencies=[Depends(require_trusted_origin)],
        responses={**PROBLEM_RESPONSES, **_WEEK_RESPONSES},
    )
    router.include_router(week_routes, prefix=WEEKS_PREFIX)
    return router
