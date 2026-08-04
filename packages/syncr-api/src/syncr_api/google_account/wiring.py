"""Composition for the Google account module: the one factory the app factory calls.

The routes sit under the calendar-sources prefix, because connecting an account is how a Google
calendar becomes readable. They are a router of their own rather than three more handlers in the
calendar package because what they touch is a credential rather than a calendar: the failure, the
repair, and the secret handling are all this package's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends

from syncr_api.accounts.injection import require_trusted_origin
from syncr_api.calendars.config import CALENDAR_SOURCES_PREFIX
from syncr_api.core.error_handlers import PROBLEM_RESPONSES
from syncr_api.core.errors import DependencyUnavailable, NotFound, Problem, Unauthorized
from syncr_api.google_account.api import router as google_account_routes

if TYPE_CHECKING:
    from collections.abc import Mapping

GOOGLE_ACCOUNT_TAG = "google-account"

# The statuses these routes raise beyond the set every route answers. 503 is a deployment with no
# Google OAuth client: there is nothing to connect to, and the detail names what still works.
_GOOGLE_RESPONSES: Mapping[int | str, dict[str, Any]] = {
    Unauthorized.status: {"model": Problem, "description": Unauthorized.title},
    NotFound.status: {"model": Problem, "description": NotFound.title},
    DependencyUnavailable.status: {"model": Problem, "description": DependencyUnavailable.title},
}


def build_google_account_router() -> APIRouter:
    """The Google account routes, under the `/api/v1/calendar-sources` prefix."""
    router = APIRouter(
        tags=[GOOGLE_ACCOUNT_TAG],
        dependencies=[Depends(require_trusted_origin)],
        responses={**PROBLEM_RESPONSES, **_GOOGLE_RESPONSES},
    )
    router.include_router(google_account_routes, prefix=CALENDAR_SOURCES_PREFIX)
    return router
