"""The four off-plan routes.

Thin, on purpose. Each handler validates a body, resolves who is asking, calls exactly one
service method, and maps the result onto a response shape. No authorization decision and no
persistence: ``tests/test_authorization_boundary.py`` asserts this file cannot reach either.

Each response is built field by field rather than validated from the record, so a column added
to the table cannot reach the wire by sharing a name with a schema field. The record carries an
``Interval`` and the wire carries two instants, which is the one place that pair is taken apart,
and it is on the schema itself because the week view answers with a period too.

The patch handler builds its change through :func:`syncr_api.core.patches.stated`, which is what
distinguishes a field the request omitted from one it sent as null. Reading the request is a
route's job; deciding what an omission means is not, so the three-valued field travels into the
service rather than being flattened here.

Every unsafe method takes the idempotency guard and none demands the header, which is the api-wide
rule: the key is offered and a caller that wants the guarantee sends one. What it buys differs per
method. A retried ``POST`` would be refused by the overlap rule with a 409, which is the wrong
answer to a request that already succeeded, so the guard replays the stored 201 instead. A ``PATCH``
and a ``DELETE`` each name a period and set an absolute state, so neither leaves a second row
behind, but re-running either invalidates every week the span touches a second time, and a
``DELETE`` re-run after its row is gone answers 404 for a period the caller has just removed.
"""

from __future__ import annotations

from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter
from starlette.responses import Response

from syncr_api.accounts.injection import PrincipalDep
from syncr_api.core.patches import stated, stated_unless_null
from syncr_api.idempotency.injection import IdempotencyGuardDep
from syncr_api.idempotency.schemas import Removed
from syncr_api.offplan.config import OFF_PLAN_PATH
from syncr_api.offplan.declarations import OffPlanChange, OffPlanDeclaration
from syncr_api.offplan.injection import OffPlanServiceDep
from syncr_api.offplan.schemas import (
    OffPlanCreateRequest,
    OffPlanPatchRequest,
    OffPlanPeriodResponse,
    OffPlanPeriodsResponse,
)

router = APIRouter()

# The key each unsafe route's idempotency claim is taken under, one per handler. A claim is
# `(tenant_id, route, key)` and the request hash carries the addressed path and the body but not the
# method, so two handlers sharing one of these would share a claim.
DECLARE_ROUTE = "offplan.declare_period"
UPDATE_ROUTE = "offplan.update_period"
REMOVE_ROUTE = "offplan.remove_period"


@router.get("", summary="Every declared off-plan period")
async def list_off_plan_periods(
    principal: PrincipalDep, service: OffPlanServiceDep
) -> OffPlanPeriodsResponse:
    """The periods, earliest first."""
    found = await service.list_all(principal)
    return OffPlanPeriodsResponse(periods=[OffPlanPeriodResponse.of(period) for period in found])


@router.post(
    "", status_code=HTTPStatus.CREATED, summary="Declare a span off-plan. 409 on an overlap"
)
async def declare_off_plan_period(
    body: OffPlanCreateRequest,
    principal: PrincipalDep,
    guard: IdempotencyGuardDep,
    service: OffPlanServiceDep,
) -> OffPlanPeriodResponse:
    """Declare a span off. Any length, and not restricted to whole days or weeks."""
    declaration = OffPlanDeclaration(
        start=body.start, end=body.end, keep_frame=body.keep_frame, label=body.label
    )

    async def declare() -> OffPlanPeriodResponse:
        return OffPlanPeriodResponse.of(await service.declare(principal, declaration))

    return await guard.once(DECLARE_ROUTE, OffPlanPeriodResponse, declare)


@router.get(OFF_PLAN_PATH, summary="One off-plan period")
async def read_off_plan_period(
    period_id: UUID, principal: PrincipalDep, service: OffPlanServiceDep
) -> OffPlanPeriodResponse:
    """One period of this tenant's."""
    return OffPlanPeriodResponse.of(await service.read(principal, period_id))


@router.patch(OFF_PLAN_PATH, summary="Move a bound, rename a span, or change keepFrame")
async def update_off_plan_period(
    period_id: UUID,
    body: OffPlanPatchRequest,
    principal: PrincipalDep,
    guard: IdempotencyGuardDep,
    service: OffPlanServiceDep,
) -> OffPlanPeriodResponse:
    """Apply a partial update. An omitted field is left alone; an explicit null clears a label."""
    change = OffPlanChange(
        start=stated_unless_null(body.start),
        end=stated_unless_null(body.end),
        keep_frame=stated_unless_null(body.keep_frame),
        label=stated(body, "label", body.label),
    )

    async def update() -> OffPlanPeriodResponse:
        return OffPlanPeriodResponse.of(await service.update(principal, period_id, change))

    return await guard.once(UPDATE_ROUTE, OffPlanPeriodResponse, update)


@router.delete(
    OFF_PLAN_PATH,
    status_code=HTTPStatus.NO_CONTENT,
    response_class=Response,
    summary="Remove a period, so its span is on plan again",
)
async def remove_off_plan_period(
    period_id: UUID,
    principal: PrincipalDep,
    guard: IdempotencyGuardDep,
    service: OffPlanServiceDep,
) -> Response:
    """Remove one period. Every week it touched has its inputs invalidated."""

    async def remove() -> Removed:
        await service.remove(principal, period_id)
        return Removed()

    await guard.once(REMOVE_ROUTE, Removed, remove)
    # Built here rather than returning None, because a returned None is still serialized and a
    # 204 must carry no body at all.
    return Response(status_code=HTTPStatus.NO_CONTENT)
