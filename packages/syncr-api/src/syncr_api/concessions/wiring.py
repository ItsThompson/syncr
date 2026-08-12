"""Composition for the concession module: the one factory the app factory calls.

One collection, two routers. The prefix, the tag, the origin check, and the statuses these routes
answer are attached here rather than repeated per route, so a route added to ``api.py`` inherits the
set its own router declares.

The prefix is the week collection, because both paths hang off one week and the week is the resource
they belong to. The route table's other week routes are ticket 31's and join the same prefix from
their own module.

**The 409 is declared on the tradeoff route alone**, because it is the only route here that can send
one: a week whose plan holds nothing a solve placed has no solve to concede against. Reading the
week's concessions and revoking one cannot conflict with anything, and a document declaring a status
they never answer types a response no caller can receive.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends

from syncr_api.accounts.injection import require_trusted_origin
from syncr_api.concessions.api import adjustment_router, tradeoff_router
from syncr_api.concessions.config import WEEKS_PREFIX
from syncr_api.core.error_handlers import PROBLEM_RESPONSES
from syncr_api.core.errors import Conflict, Forbidden, NotFound, Problem, Unauthorized

if TYPE_CHECKING:
    from collections.abc import Mapping

CONCESSIONS_TAG = "concessions"

# The statuses every route here raises beyond the set every route in the application answers, so the
# generated document describes them and the frontend has types for them.
_CONCESSION_RESPONSES: Mapping[int | str, dict[str, Any]] = {
    Unauthorized.status: {"model": Problem, "description": Unauthorized.title},
    Forbidden.status: {"model": Problem, "description": Forbidden.title},
    NotFound.status: {"model": Problem, "description": NotFound.title},
}

# The tradeoff route's own, and the condition is a state of the week rather than a fault in the
# request: its plan holds nothing a solve placed, so there is no solve to concede against.
_TRADEOFF_RESPONSES: Mapping[int | str, dict[str, Any]] = {
    Conflict.status: {"model": Problem, "description": Conflict.title},
}


def build_concessions_router() -> APIRouter:
    """The `/api/v1/weeks/{iso_week}` tradeoff and concession routes."""
    router = APIRouter(
        tags=[CONCESSIONS_TAG],
        dependencies=[Depends(require_trusted_origin)],
        responses={**PROBLEM_RESPONSES, **_CONCESSION_RESPONSES},
    )
    router.include_router(tradeoff_router, prefix=WEEKS_PREFIX, responses=dict(_TRADEOFF_RESPONSES))
    router.include_router(adjustment_router, prefix=WEEKS_PREFIX)
    return router
