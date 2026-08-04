"""The eight calendar-source routes.

Thin, on purpose. Each handler validates a body, resolves who is asking, calls exactly one
service method, and maps the result onto a response shape. No authorization decision and no
persistence: ``tests/test_authorization_boundary.py`` asserts this file cannot reach either.

``PUT .../role`` takes no body. It assigns the one role there is to assign, and a body naming
which would invite a request to assign ``anchor-source`` to the write target, which is not a
transition this product offers: the projection is destructive, so demoting the calendar syncr
owns would silently turn its overwritten contents into anchors.
"""

from __future__ import annotations

from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter
from starlette.responses import Response

from syncr_api.accounts.injection import PrincipalDep
from syncr_api.calendars.config import (
    SOURCE_HORIZON_PATH,
    SOURCE_PATH,
    SOURCE_REMOTE_CALENDARS_PATH,
    SOURCE_ROLE_PATH,
    SOURCE_SYNC_PATH,
)
from syncr_api.calendars.injection import CalendarSourceServiceDep
from syncr_api.calendars.schemas import (
    AddCalendarSourceRequest,
    CalendarSourcePatchRequest,
    CalendarSourceResponse,
    CalendarSourcesResponse,
    HorizonPatchRequest,
    RemoteCalendarResponse,
    RemoteCalendarsResponse,
)
from syncr_api.calendars.service import NewSource, SourceChange
from syncr_api.idempotency.injection import IdempotencyGuardDep
from syncr_api.solving.schemas import OperationResponse

router = APIRouter()

ADD_SOURCE_ROUTE = "calendars.add_source"
SYNC_SOURCE_ROUTE = "calendars.sync_source"


@router.get("", summary="Every calendar source, with its sync state")
async def list_calendar_sources(
    principal: PrincipalDep, service: CalendarSourceServiceDep
) -> CalendarSourcesResponse:
    """Each source's provider, anchor count, last sync time, and state."""
    sources = await service.list_sources(principal)
    return CalendarSourcesResponse(
        sources=[CalendarSourceResponse.of(source) for source in sources]
    )


@router.post(
    "", status_code=HTTPStatus.CREATED, summary="Add an anchor source. No OAuth for an ICS feed"
)
async def add_calendar_source(
    body: AddCalendarSourceRequest,
    principal: PrincipalDep,
    guard: IdempotencyGuardDep,
    service: CalendarSourceServiceDep,
) -> CalendarSourceResponse:
    """Add a source, with an ICS feed address normalized on the way in."""
    new = NewSource(
        provider=body.provider, display_name=body.display_name, external_id=body.external_id
    )

    async def add() -> CalendarSourceResponse:
        return CalendarSourceResponse.of(await service.add_source(principal, new))

    return await guard.once(ADD_SOURCE_ROUTE, CalendarSourceResponse, add)


@router.get(SOURCE_PATH, summary="One source and its sync state")
async def read_calendar_source(
    source_id: UUID, principal: PrincipalDep, service: CalendarSourceServiceDep
) -> CalendarSourceResponse:
    """One source, or a 404 that discloses nothing about another tenant's rows."""
    return CalendarSourceResponse.of(await service.read_source(principal, source_id))


@router.patch(SOURCE_PATH, summary="Include or exclude a source, or rename it")
async def change_calendar_source(
    source_id: UUID,
    body: CalendarSourcePatchRequest,
    principal: PrincipalDep,
    service: CalendarSourceServiceDep,
) -> CalendarSourceResponse:
    """Apply a partial update. An excluded source reports zero anchors, not an error."""
    change = SourceChange(included=body.included, display_name=body.display_name)
    return CalendarSourceResponse.of(await service.change_source(principal, source_id, change))


@router.delete(
    SOURCE_PATH,
    status_code=HTTPStatus.NO_CONTENT,
    response_class=Response,
    summary="Remove a source and the anchors it contributed",
)
async def remove_calendar_source(
    source_id: UUID, principal: PrincipalDep, service: CalendarSourceServiceDep
) -> Response:
    """Remove a source. Its anchors go with it."""
    await service.remove_source(principal, source_id)
    # Built here rather than returning None, because a returned None is still serialized and a
    # 204 must carry no body at all.
    return Response(status_code=HTTPStatus.NO_CONTENT)


@router.post(SOURCE_SYNC_PATH, summary="Force a sync. Returns an Operation")
async def sync_calendar_source(
    source_id: UUID,
    principal: PrincipalDep,
    guard: IdempotencyGuardDep,
    service: CalendarSourceServiceDep,
) -> OperationResponse:
    """Sync one source now, and answer with the operation that did it."""

    async def sync() -> OperationResponse:
        return OperationResponse.of(await service.sync_source(principal, source_id))

    return await guard.once(SYNC_SOURCE_ROUTE, OperationResponse, sync)


@router.put(SOURCE_ROLE_PATH, summary="Assign the write-target role. 409 if one exists")
async def designate_write_target(
    source_id: UUID, principal: PrincipalDep, service: CalendarSourceServiceDep
) -> CalendarSourceResponse:
    """Make this the one calendar syncr writes the plan to."""
    return CalendarSourceResponse.of(await service.designate_write_target(principal, source_id))


@router.patch(SOURCE_HORIZON_PATH, summary="Set the projection horizon. Write-target only")
async def set_projection_horizon(
    source_id: UUID,
    body: HorizonPatchRequest,
    principal: PrincipalDep,
    service: CalendarSourceServiceDep,
) -> CalendarSourceResponse:
    """Set how many days ahead the plan is projected. 422 on an anchor source."""
    changed = await service.set_horizon(principal, source_id, horizon_days=body.horizon_days)
    return CalendarSourceResponse.of(changed)


@router.get(
    SOURCE_REMOTE_CALENDARS_PATH,
    summary="The account's calendars, for selection during setup. Google only",
)
async def list_remote_calendars(
    source_id: UUID, principal: PrincipalDep, service: CalendarSourceServiceDep
) -> RemoteCalendarsResponse:
    """Every calendar the account behind this source holds. 422 on an ICS source."""
    found = await service.list_remote_calendars(principal, source_id)
    return RemoteCalendarsResponse(
        calendars=[RemoteCalendarResponse.of(calendar) for calendar in found]
    )
