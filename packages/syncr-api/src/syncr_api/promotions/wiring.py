"""Composition for the promotion routes: the one factory the app factory calls.

The statuses these two raise beyond the set every route answers are a 409 and a 422, and both are
about a pattern rather than about a body: 409 when the template cannot absorb this pattern or no
longer holds the entry it names, and 422 when the identifier is not one this product produced.

There is no 404. A promotion candidate is not a row, so there is nothing to be absent: an identifier
that parses names a pattern whether or not the reader currently has one, and what the accept can
refuse is the ABSORPTION rather than the candidate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends

from syncr_api.accounts.injection import require_trusted_origin
from syncr_api.core.error_handlers import PROBLEM_RESPONSES
from syncr_api.core.errors import Conflict, Forbidden, Problem, Unauthorized, ValidationFailed
from syncr_api.promotions.api import promotions_router
from syncr_api.promotions.config import PROMOTIONS_PREFIX

if TYPE_CHECKING:
    from collections.abc import Mapping

PROMOTIONS_TAG = "promotions"

_PROMOTION_RESPONSES: Mapping[int | str, dict[str, Any]] = {
    Unauthorized.status: {"model": Problem, "description": Unauthorized.title},
    Forbidden.status: {"model": Problem, "description": Forbidden.title},
    Conflict.status: {"model": Problem, "description": Conflict.title},
    ValidationFailed.status: {"model": Problem, "description": ValidationFailed.title},
}


def build_promotions_router() -> APIRouter:
    """The `/api/v1/promotions/{id}/accept` and `/decline` routes."""
    router = APIRouter(
        prefix=PROMOTIONS_PREFIX,
        tags=[PROMOTIONS_TAG],
        dependencies=[Depends(require_trusted_origin)],
        responses={**PROBLEM_RESPONSES, **_PROMOTION_RESPONSES},
    )
    router.include_router(promotions_router)
    return router
