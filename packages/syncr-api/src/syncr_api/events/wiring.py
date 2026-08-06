"""Composition for the events module: the one factory the app factory calls.

One route, and the two rejections it can produce are the shared set: no credential, or a credential
whose scopes do not include reading the plan. There is no 404 and no 409, because there is nothing
to
name and nothing to conflict with.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends

from syncr_api.accounts.injection import require_trusted_origin
from syncr_api.core.error_handlers import PROBLEM_RESPONSES
from syncr_api.core.errors import Forbidden, Problem, Unauthorized
from syncr_api.events.api import router as event_routes
from syncr_api.events.config import EVENTS_PREFIX, EVENTS_TAG

if TYPE_CHECKING:
    from collections.abc import Mapping

_EVENT_RESPONSES: Mapping[int | str, dict[str, Any]] = {
    Unauthorized.status: {"model": Problem, "description": Unauthorized.title},
    Forbidden.status: {"model": Problem, "description": Forbidden.title},
}


def build_events_router() -> APIRouter:
    """The `/api/v1/events` route.

    The prefix is applied at the include rather than on the router itself, because the stream IS the
    prefix: it answers it with nothing after it, and the framework refuses a route whose own path
    and whose include prefix are both empty.
    """
    router = APIRouter(
        tags=[EVENTS_TAG],
        dependencies=[Depends(require_trusted_origin)],
        responses={**PROBLEM_RESPONSES, **_EVENT_RESPONSES},
    )
    router.include_router(event_routes, prefix=EVENTS_PREFIX)
    return router
