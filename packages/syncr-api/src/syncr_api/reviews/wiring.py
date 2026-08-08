"""Composition for the review module: the one factory the app factory calls.

The tag, the origin check, and the statuses these routes answer are attached here rather than
repeated per route, so a route added to ``api.py`` inherits them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends

from syncr_api.accounts.injection import require_trusted_origin
from syncr_api.core.error_handlers import PROBLEM_RESPONSES
from syncr_api.core.errors import Forbidden, Problem, Unauthorized
from syncr_api.reviews.api import router as review_routes
from syncr_api.reviews.config import REVIEWS_PREFIX

if TYPE_CHECKING:
    from collections.abc import Mapping

REVIEWS_TAG = "reviews"

# The statuses these routes raise beyond the set every route answers. There is no 404: a period with
# no Areas and no plan is an empty review rather than an absent one, and a week the horizon has not
# reached is a session whose planned week holds no verdict rather than a missing resource. A body
# naming an Area this tenant does not hold is a 422, because the identifier is in the body and the
# resource addressed is the review. There is no 409 either: applying a revision replaces shares
# wholly, so a second identical apply changes nothing rather than conflicting with the first.
_REVIEW_RESPONSES: Mapping[int | str, dict[str, Any]] = {
    Unauthorized.status: {"model": Problem, "description": Unauthorized.title},
    Forbidden.status: {"model": Problem, "description": Forbidden.title},
}


def build_reviews_router() -> APIRouter:
    """The pie review's read and apply, and the weekly session's payload."""
    router = APIRouter(
        tags=[REVIEWS_TAG],
        dependencies=[Depends(require_trusted_origin)],
        responses={**PROBLEM_RESPONSES, **_REVIEW_RESPONSES},
    )
    router.include_router(review_routes, prefix=REVIEWS_PREFIX)
    return router
