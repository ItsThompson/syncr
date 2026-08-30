"""Composition for the approve route: the one factory the app factory calls.

The prefix is the week collection, which the week, concession and pin routes already hang off, so
the week table stays one collection served by four modules rather than four collections
that happen to share a URL.

The tag, the origin check, and the statuses this route answers are attached here rather than on the
route, so a route added to ``api.py`` inherits them.

409 is the one this produces, and it is three states rather than one: a slot that holds nothing, a
slot another approval took a moment earlier, and a proposal that would change the plan of record in
a way it never said it would. Each is a fact about the stored state rather than about the request,
which is what makes each a conflict and not a validation failure. A missing ``Idempotency-Key`` IS a
fact about the request, and it is the 400 the shared dependency already answers with.

There is no 404 among them, deliberately, which is the week collection's own rule: every ISO week
identifier names a week, so a week with nothing to approve is a conflict rather than a broken link.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends

from syncr_api.accounts.injection import require_trusted_origin
from syncr_api.approvals.api import router as approval_routes
from syncr_api.concessions.config import WEEKS_PREFIX
from syncr_api.core.error_handlers import PROBLEM_RESPONSES
from syncr_api.core.errors import Conflict, Forbidden, Problem, Unauthorized

if TYPE_CHECKING:
    from collections.abc import Mapping

APPROVALS_TAG = "approvals"

# The statuses this route raises beyond the set every route answers, so the generated document
# describes them and the frontend has types for them.
_APPROVAL_RESPONSES: Mapping[int | str, dict[str, Any]] = {
    Unauthorized.status: {"model": Problem, "description": Unauthorized.title},
    Forbidden.status: {"model": Problem, "description": Forbidden.title},
    Conflict.status: {"model": Problem, "description": Conflict.title},
}


def build_approvals_router() -> APIRouter:
    """The `/api/v1/weeks/{iso_week}/approve` route."""
    router = APIRouter(
        tags=[APPROVALS_TAG],
        dependencies=[Depends(require_trusted_origin)],
        responses={**PROBLEM_RESPONSES, **_APPROVAL_RESPONSES},
    )
    router.include_router(approval_routes, prefix=WEEKS_PREFIX)
    return router
