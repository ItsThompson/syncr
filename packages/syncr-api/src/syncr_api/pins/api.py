"""The three pin routes.

Thin, on purpose. Each handler validates a body, resolves who is asking, calls exactly one service
method, and maps the result onto a response shape through that shape's own ``of``. No authorization
decision and no persistence: ``tests/test_authorization_boundary.py`` asserts this file cannot reach
either.

The week is a path segment and its shape is validated in the service, by the domain parser that owns
the identifier, so no pattern is declared here that could drift from it.

**All three take the idempotency guard, and none of them demands a key.** The header is offered on
every unsafe method rather than required, which is the api-wide rule. What a key buys here is real
rather than theoretical: an agent retrying a pin must not write a second edit event, because the
event is a training label, and a duplicated one is a preference the user expressed once and a
fitter counts twice. The pin row is keyed by the block, so a retry without a key overwrites rather
than duplicating; the event is append-only, so it is the write the guard protects.

``POST /reject-block`` answers with the same shape as ``POST /pins``, because it creates the same
thing. There is no rejection resource, no rejection status, and no field on the response that says a
pin came from a rejection: section 07 settled that partial rejection is a pin, and a client that
could tell them apart would be a client that could treat them differently.
"""

from __future__ import annotations

from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter
from starlette.responses import Response

from syncr_api.accounts.injection import ClientPrincipalDep, PrincipalDep, TransactionDep
from syncr_api.idempotency.injection import IdempotencyGuardDep
from syncr_api.pins.config import (
    PIN_PATH,
    PIN_ROUTE,
    PINS_PATH,
    REJECT_BLOCK_PATH,
    REJECT_BLOCK_ROUTE,
    UNPIN_ROUTE,
)
from syncr_api.pins.declarations import BlockRejected, PinRequested
from syncr_api.pins.injection import PinServiceDep
from syncr_api.pins.schemas import (
    PinCreateRequest,
    PinnedResponse,
    PinReleased,
    RejectBlockRequest,
)

router = APIRouter()


@router.post(
    PINS_PATH,
    status_code=HTTPStatus.CREATED,
    summary="Pin a block where the user put it. Returns the pin, the verdict, and the operation",
)
async def create_pin(
    iso_week: str,
    body: PinCreateRequest,
    principal: ClientPrincipalDep,
    guard: IdempotencyGuardDep,
    service: PinServiceDep,
    transaction: TransactionDep,
) -> PinnedResponse:
    """Record one manual edit, and answer with a verdict computed without waiting for a solve."""
    requested = PinRequested(block_id=body.block_id, start=body.start)

    async def hold() -> PinnedResponse:
        return PinnedResponse.of(await service.pin(principal, iso_week, requested))

    answered = await guard.once(PIN_ROUTE, PinnedResponse, hold)
    # The answer carries the operation of the solve the pin scheduled, so that row must be
    # readable the instant the client holds its identifier. See `get_transaction` for why this
    # commit is here rather than on teardown.
    await transaction.commit()
    return answered


@router.post(
    REJECT_BLOCK_PATH,
    status_code=HTTPStatus.CREATED,
    summary="Reject one proposed move by pinning the block at its existing placement",
)
async def reject_block(
    iso_week: str,
    body: RejectBlockRequest,
    principal: PrincipalDep,
    guard: IdempotencyGuardDep,
    service: PinServiceDep,
    transaction: TransactionDep,
) -> PinnedResponse:
    """Refuse one change without refusing the rest, which is what makes a rejection teach."""
    rejected = BlockRejected(block_id=body.block_id)

    async def hold() -> PinnedResponse:
        return PinnedResponse.of(await service.reject(principal, iso_week, rejected))

    answered = await guard.once(REJECT_BLOCK_ROUTE, PinnedResponse, hold)
    # Same reason as `create_pin`: the answer carries the scheduled solve's operation.
    await transaction.commit()
    return answered


@router.delete(
    PIN_PATH,
    status_code=HTTPStatus.NO_CONTENT,
    response_class=Response,
    summary="Release one pin. Bumps the week's input version and re-solves",
)
async def remove_pin(
    iso_week: str,
    pin_id: UUID,
    principal: PrincipalDep,
    guard: IdempotencyGuardDep,
    service: PinServiceDep,
) -> Response:
    """Free the block to move again. The pin's record is retained as training data."""

    async def release() -> PinReleased:
        await service.unpin(principal, iso_week, pin_id)
        return PinReleased()

    await guard.once(UNPIN_ROUTE, PinReleased, release)
    # Built here rather than returning None, because a returned None is still serialized and a
    # 204 must carry no body at all.
    return Response(status_code=HTTPStatus.NO_CONTENT)
