"""The two promotion routes.

Thin, on purpose. Each reads the identifier out of the path, resolves who is asking, calls one
service method, and maps the result through that shape's own ``of``. No authorization decision and
no persistence.

**Neither takes a request body.** Everything a promotion states is in its identifier: which content,
which weekday, which minute. A body would be a second place the same four values could be sent, and
a request whose body disagreed with its path would have to be refused for saying one thing twice.

**Neither takes the idempotency guard.** Both are naturally idempotent: an accept sets a target time
to a stated value, and a decline writes one row keyed by the pattern. Repeating either produces the
state the first attempt produced, and neither queues work, so there is nothing a stored response
would protect a retry from.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path

from syncr_api.accounts.injection import PrincipalDep
from syncr_api.promotions.config import (
    ACCEPT_PATH,
    DECLINE_PATH,
    PROMOTION_ID_FIELD,
    PROMOTION_ID_MAX_LENGTH,
)
from syncr_api.promotions.injection import PromotionServiceDep
from syncr_api.promotions.queries import require_a_promotion_ref
from syncr_api.promotions.schemas import PromotionAcceptedResponse, PromotionDeclinedResponse
from syncr_api.promotions.statements import accepted_statement, declined_statement

promotions_router = APIRouter()

_PROMOTION_ID = Annotated[
    str,
    Path(
        description="The candidate's identifier, as the weekly session's payload carries it: the "
        "kind, the content, the ISO weekday and the minute of the day.",
        max_length=PROMOTION_ID_MAX_LENGTH,
        examples=["template_entry:0b7d1f2e-2f4a-4c8e-9c1a-2f9f8f6b5a41:2:780"],
    ),
]


@promotions_router.post(ACCEPT_PATH, summary="Absorb a repeated pin into the day shape")
async def accept_promotion(
    promotion_id: _PROMOTION_ID, principal: PrincipalDep, service: PromotionServiceDep
) -> PromotionAcceptedResponse:
    """Move the day-shape entry this pattern is about to the time it keeps being pinned to."""
    ref = require_a_promotion_ref(promotion_id, field=PROMOTION_ID_FIELD)
    accepted = await service.accept(principal, ref)
    return PromotionAcceptedResponse.of(accepted, statement=accepted_statement(accepted))


@promotions_router.post(DECLINE_PATH, summary="Decline it, and do not raise it again for a while")
async def decline_promotion(
    promotion_id: _PROMOTION_ID, principal: PrincipalDep, service: PromotionServiceDep
) -> PromotionDeclinedResponse:
    """Record the answer. Nothing reaches the template, and the pattern is silenced for a period."""
    ref = require_a_promotion_ref(promotion_id, field=PROMOTION_ID_FIELD)
    declined = await service.decline(principal, ref)
    return PromotionDeclinedResponse.of(declined, statement=declined_statement(declined))
