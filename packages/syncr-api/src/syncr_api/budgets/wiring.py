"""Composition for the budget module: the one factory the app factory calls."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends

from syncr_api.accounts.injection import require_trusted_origin
from syncr_api.budgets.api import router as budget_routes
from syncr_api.budgets.config import BUDGET_PREFIX
from syncr_api.core.error_handlers import PROBLEM_RESPONSES
from syncr_api.core.errors import Forbidden, Problem, Unauthorized

if TYPE_CHECKING:
    from collections.abc import Mapping

BUDGET_TAG = "budgets"

# The statuses this route raises beyond the set every route answers. There is no 404 and no 409:
# a period with no Areas is an empty report rather than an absent one, and a budget that does not
# fit is reported as oversubscription rather than refused.
_BUDGET_RESPONSES: Mapping[int | str, dict[str, Any]] = {
    Unauthorized.status: {"model": Problem, "description": Unauthorized.title},
    Forbidden.status: {"model": Problem, "description": Forbidden.title},
}


def build_budget_router() -> APIRouter:
    """The `/api/v1/budget` route.

    The prefix is applied at the include rather than on the router itself, because the one route
    IS the prefix: it answers ``/api/v1/budget`` with nothing after it, and the framework refuses
    a route whose own path and whose include prefix are both empty.
    """
    router = APIRouter(
        tags=[BUDGET_TAG],
        dependencies=[Depends(require_trusted_origin)],
        responses={**PROBLEM_RESPONSES, **_BUDGET_RESPONSES},
    )
    router.include_router(budget_routes, prefix=BUDGET_PREFIX)
    return router
