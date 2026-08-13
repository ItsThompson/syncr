"""The five routine routes.

Thin, on purpose. Each handler validates a body, resolves who is asking, calls exactly one
service method, and maps the result onto a response shape. No authorization decision and no
persistence: ``tests/test_authorization_boundary.py`` asserts this file cannot reach either.

Each response is built field by field rather than validated from the record, so a column added
to the table cannot reach the wire by sharing a name with a schema field. That is what keeps
the frame free of an Area even if one were ever added to the row.

``PATCH`` is where the sleep floor is set, as ``minDurationMinutes``. Its change is built
through :func:`syncr_api.core.patches.stated_unless_null`, which distinguishes a field the
request omitted from one it sent: nothing on a routine is nullable, so the schema refuses a
null and ``None`` can only mean the field was left out.

Every unsafe method takes the idempotency guard and none demands the header, which is the api-wide
rule: the key is offered and a caller that wants the guarantee sends one. What it buys differs per
method. Nothing about a routine is unique and the table says so deliberately, so a retried ``POST``
leaves a second row and the frame carries the same span twice. A ``PATCH`` and a ``DELETE`` each set
an absolute state and leave no extra row, but re-running either invalidates the weeks a running
solve is reading, and a ``DELETE`` re-run after its row is gone answers 404 for a routine the caller
has just removed.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter
from starlette.responses import Response

from syncr_api.accounts.injection import PrincipalDep
from syncr_api.core.patches import stated_unless_null
from syncr_api.idempotency.injection import IdempotencyGuardDep
from syncr_api.idempotency.schemas import Removed
from syncr_api.routines.config import ROUTINE_PATH
from syncr_api.routines.declarations import RoutineChange, RoutineDeclaration
from syncr_api.routines.injection import RoutineServiceDep
from syncr_api.routines.schemas import (
    RoutineCreateRequest,
    RoutinePatchRequest,
    RoutineResponse,
    RoutinesResponse,
)

if TYPE_CHECKING:
    from syncr_api.routines.records import RoutineRecord

router = APIRouter()

# The key each unsafe route's idempotency claim is taken under, one per handler. A claim is
# `(tenant_id, route, key)` and the request hash carries the addressed path and the body but not the
# method, so two handlers sharing one of these would share a claim.
DECLARE_ROUTE = "routines.declare_routine"
UPDATE_ROUTE = "routines.update_routine"
REMOVE_ROUTE = "routines.remove_routine"


def _as_routine(record: RoutineRecord) -> RoutineResponse:
    return RoutineResponse(
        id=record.id,
        title=record.title,
        target_time=record.target_time,
        duration_minutes=record.duration_minutes,
        min_duration_minutes=record.min_duration_minutes,
        flex_band_minutes=record.flex_band_minutes,
    )


@router.get("", summary="Every routine, in the order the day runs")
async def list_routines(principal: PrincipalDep, service: RoutineServiceDep) -> RoutinesResponse:
    """The circadian frame: the spans the rest of the week is placed around."""
    found = await service.list_all(principal)
    return RoutinesResponse(routines=[_as_routine(routine) for routine in found])


@router.post("", status_code=HTTPStatus.CREATED, summary="Declare a routine")
async def declare_routine(
    body: RoutineCreateRequest,
    principal: PrincipalDep,
    guard: IdempotencyGuardDep,
    service: RoutineServiceDep,
) -> RoutineResponse:
    """Declare a routine. An unstated floor equals the target, which makes it inelastic."""
    declaration = RoutineDeclaration(
        title=body.title,
        target_time=body.target_time,
        duration_minutes=body.duration_minutes,
        min_duration_minutes=body.min_duration_minutes,
        flex_band_minutes=body.flex_band_minutes,
    )

    async def declare() -> RoutineResponse:
        return _as_routine(await service.create(principal, declaration))

    return await guard.once(DECLARE_ROUTE, RoutineResponse, declare)


@router.get(ROUTINE_PATH, summary="One routine")
async def read_routine(
    routine_id: UUID, principal: PrincipalDep, service: RoutineServiceDep
) -> RoutineResponse:
    """One routine of this tenant's."""
    return _as_routine(await service.read(principal, routine_id))


@router.patch(ROUTINE_PATH, summary="Change a target time, a span, the floor, or the band")
async def update_routine(
    routine_id: UUID,
    body: RoutinePatchRequest,
    principal: PrincipalDep,
    guard: IdempotencyGuardDep,
    service: RoutineServiceDep,
) -> RoutineResponse:
    """Apply a partial update. This is where the sleep floor is set."""
    change = RoutineChange(
        title=stated_unless_null(body.title),
        target_time=stated_unless_null(body.target_time),
        duration_minutes=stated_unless_null(body.duration_minutes),
        min_duration_minutes=stated_unless_null(body.min_duration_minutes),
        flex_band_minutes=stated_unless_null(body.flex_band_minutes),
    )

    async def update() -> RoutineResponse:
        return _as_routine(await service.update(principal, routine_id, change))

    return await guard.once(UPDATE_ROUTE, RoutineResponse, update)


@router.delete(
    ROUTINE_PATH,
    status_code=HTTPStatus.NO_CONTENT,
    response_class=Response,
    summary="Remove a routine, giving its span back to discretionary time",
)
async def remove_routine(
    routine_id: UUID,
    principal: PrincipalDep,
    guard: IdempotencyGuardDep,
    service: RoutineServiceDep,
) -> Response:
    """Remove a routine. The frame shrinks, so the denominator grows."""

    async def remove() -> Removed:
        await service.remove(principal, routine_id)
        return Removed()

    await guard.once(REMOVE_ROUTE, Removed, remove)
    # Built here rather than returning None, because a returned None is still serialized and a
    # 204 must carry no body at all.
    return Response(status_code=HTTPStatus.NO_CONTENT)
