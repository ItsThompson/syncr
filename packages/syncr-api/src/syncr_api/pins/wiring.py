"""Composition for the pin routes: the one factory the app factory calls.

The prefix is the week collection, which the week and concession routes already hang off, so section
13's ten week routes stay one collection served by three modules rather than three collections that
happen to share a URL.

The tag, the origin check, and the statuses these routes answer are attached here rather than
repeated per route, so a route added to ``api.py`` inherits them.

409 is the one these produce most, and it is four states rather than one: a week with no plan to pin
in, a block the week has already reached, a rejection with no proposal to reject, and a rejection of
a change that adds rather than moves. Each is a fact about the stored state rather than about the
request, which is what makes each a conflict and not a validation failure. A start already gone, and
one outside the week, ARE facts about the request, and both are a 422 naming the field that carried
them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends

from syncr_api.accounts.injection import require_trusted_origin
from syncr_api.concessions.config import WEEKS_PREFIX
from syncr_api.core.error_handlers import PROBLEM_RESPONSES
from syncr_api.core.errors import Conflict, Forbidden, NotFound, Problem, Unauthorized
from syncr_api.pins.api import router as pin_routes

if TYPE_CHECKING:
    from collections.abc import Mapping

PINS_TAG = "pins"

# The statuses these routes raise beyond the set every route answers, so the generated document
# describes them and the frontend has types for them.
_PIN_RESPONSES: Mapping[int | str, dict[str, Any]] = {
    Unauthorized.status: {"model": Problem, "description": Unauthorized.title},
    Forbidden.status: {"model": Problem, "description": Forbidden.title},
    NotFound.status: {"model": Problem, "description": NotFound.title},
    Conflict.status: {"model": Problem, "description": Conflict.title},
}


def build_pins_router() -> APIRouter:
    """The `/api/v1/weeks/{iso_week}` pin, unpin and reject-block routes."""
    router = APIRouter(
        tags=[PINS_TAG],
        dependencies=[Depends(require_trusted_origin)],
        responses={**PROBLEM_RESPONSES, **_PIN_RESPONSES},
    )
    router.include_router(pin_routes, prefix=WEEKS_PREFIX)
    return router
