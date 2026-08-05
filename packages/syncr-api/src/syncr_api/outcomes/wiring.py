"""Composition for the outcome module: the one factory the app factory calls.

Two collections under one router, because the routes address two different things: an outcome is
recorded on a BLOCK, and a day is confirmed by its local DATE. Neither is under the other on the
wire, and the week a block belongs to cannot be recovered from its id, so a single prefix would
have to invent a nesting the identity does not have.

The tag, the origin check, and the statuses these routes answer are attached here rather than
repeated per route, so a route added to ``api.py`` inherits them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends

from syncr_api.accounts.injection import require_trusted_origin
from syncr_api.core.error_handlers import PROBLEM_RESPONSES
from syncr_api.core.errors import Forbidden, NotFound, Problem, Unauthorized
from syncr_api.outcomes.api import blocks_router, days_router
from syncr_api.outcomes.config import BLOCKS_PREFIX, DAYS_PREFIX

if TYPE_CHECKING:
    from collections.abc import Mapping

OUTCOMES_TAG = "outcomes"

# The statuses these routes raise beyond the set every route answers, so the generated document
# describes them and the frontend has types for them. 409 is deliberately absent: recording an
# outcome states an absolute state rather than a delta, and confirming a day that is already
# confirmed is a request that has already succeeded rather than one the stored state refuses.
_OUTCOME_RESPONSES: Mapping[int | str, dict[str, Any]] = {
    Unauthorized.status: {"model": Problem, "description": Unauthorized.title},
    Forbidden.status: {"model": Problem, "description": Forbidden.title},
    NotFound.status: {"model": Problem, "description": NotFound.title},
}


def build_outcomes_router() -> APIRouter:
    """The `/api/v1/blocks/{id}/outcome` route and the three `/api/v1/days` routes.

    The prefixes are applied at each include rather than on the router itself, because the two
    collections live at different paths and the framework applies one prefix per include.
    """
    router = APIRouter(
        tags=[OUTCOMES_TAG],
        dependencies=[Depends(require_trusted_origin)],
        responses={**PROBLEM_RESPONSES, **_OUTCOME_RESPONSES},
    )
    router.include_router(blocks_router, prefix=BLOCKS_PREFIX)
    router.include_router(days_router, prefix=DAYS_PREFIX)
    return router
