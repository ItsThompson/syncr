"""The eight Area and Project routes.

Thin, on purpose. Each handler validates a body, resolves who is asking, calls exactly one
service method, and maps the result onto a response shape. No authorization decision and no
persistence: ``tests/test_authorization_boundary.py`` asserts this file cannot reach either.

Each response is built field by field rather than validated from the record, so a column added
to a table cannot reach the wire by sharing a name with a schema field.

Both patch handlers build their change through :func:`syncr_api.core.patches.stated`, which is
what distinguishes a field the request omitted from one it sent as null. Reading the request is
a route's job; deciding what an omission means is not, so the three-valued field travels into
the service rather than being flattened here.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Query

from syncr_api.accounts.injection import ClientPrincipalDep, PrincipalDep
from syncr_api.areas.declarations import (
    AreaChange,
    AreaDeclaration,
    ProjectChange,
    ProjectDeclaration,
)
from syncr_api.areas.injection import AreaServiceDep, ProjectServiceDep
from syncr_api.areas.schemas import (
    AreaCreateRequest,
    AreaPatchRequest,
    AreaResponse,
    AreasResponse,
    AreaView,
    ProjectCreateRequest,
    ProjectPatchRequest,
    ProjectResponse,
    ProjectsResponse,
    RampReading,
)
from syncr_api.core.patches import stated, stated_unless_null

if TYPE_CHECKING:
    from syncr_api.areas.ramp import RampReading as RampState
    from syncr_api.areas.records import AreaRecord, ProjectRecord
    from syncr_api.areas.service import DealtArea

areas_router = APIRouter()
projects_router = APIRouter()


def _as_area(record: AreaRecord) -> AreaResponse:
    return AreaResponse(
        id=record.id,
        parent_id=record.parent_id,
        name=record.name,
        pigment_index=record.pigment_index,
        budget_percent=record.budget_percent,
        floor_hours=record.floor_hours,
    )


def _as_ramp(state: RampState) -> RampReading:
    return RampReading(
        pigment_count=state.pigment_count,
        pigments_in_use=state.pigments_in_use,
    )


def _as_view(dealt: DealtArea) -> AreaView:
    return AreaView(area=_as_area(dealt.area), ramp=_as_ramp(dealt.ramp))


def _as_project(record: ProjectRecord) -> ProjectResponse:
    return ProjectResponse(
        id=record.id,
        area_id=record.area_id,
        name=record.name,
        deadline=record.deadline,
        status=record.status,
    )


@areas_router.get("", summary="Every Area, with the state of the pigment ramp")
async def list_areas(principal: ClientPrincipalDep, service: AreaServiceDep) -> AreasResponse:
    """The Areas, in the order the ramp dealt their pigments."""
    view = await service.list_all(principal)
    return AreasResponse(areas=[_as_area(area) for area in view.areas], ramp=_as_ramp(view.ramp))


@areas_router.post(
    "", status_code=HTTPStatus.CREATED, summary="Declare an Area and deal it a pigment"
)
async def declare_area(
    body: AreaCreateRequest, principal: PrincipalDep, service: AreaServiceDep
) -> AreaView:
    """Declare an Area. The next step of the ramp is assigned; no colour is accepted."""
    declaration = AreaDeclaration(
        name=body.name,
        parent_id=body.parent_id,
        budget_percent=body.budget_percent,
        floor_hours=body.floor_hours,
    )
    return _as_view(await service.create(principal, declaration))


@areas_router.get("/{area_id}", summary="One Area and the budget it declares")
async def read_area(
    area_id: UUID, principal: PrincipalDep, service: AreaServiceDep
) -> AreaResponse:
    """One Area of this tenant's."""
    return _as_area(await service.read(principal, area_id))


@areas_router.patch("/{area_id}", summary="Change a name, floor, share, or pigment step")
async def update_area(
    area_id: UUID,
    body: AreaPatchRequest,
    principal: PrincipalDep,
    service: AreaServiceDep,
) -> AreaView:
    """Apply a partial update. An omitted field is left alone; an explicit null clears one."""
    change = AreaChange(
        name=stated_unless_null(body.name),
        pigment_index=stated_unless_null(body.pigment_index),
        budget_percent=stated(body, "budget_percent", body.budget_percent),
        floor_hours=stated(body, "floor_hours", body.floor_hours),
    )
    return _as_view(await service.update(principal, area_id, change))


@projects_router.get("", summary="Every Project, or the ones inside one Area")
async def list_projects(
    principal: PrincipalDep,
    service: ProjectServiceDep,
    area_id: UUID | None = Query(default=None, alias="areaId"),
) -> ProjectsResponse:
    """The Projects, oldest first."""
    found = await service.list_all(principal, area_id=area_id)
    return ProjectsResponse(projects=[_as_project(project) for project in found])


@projects_router.post(
    "", status_code=HTTPStatus.CREATED, summary="Declare a Project inside an Area"
)
async def declare_project(
    body: ProjectCreateRequest, principal: PrincipalDep, service: ProjectServiceDep
) -> ProjectResponse:
    """Declare a Project. It carries no budget: its Area's allocation covers it."""
    declaration = ProjectDeclaration(
        area_id=body.area_id, name=body.name, deadline=body.deadline, status=body.status
    )
    return _as_project(await service.create(principal, declaration))


@projects_router.get("/{project_id}", summary="One Project")
async def read_project(
    project_id: UUID, principal: PrincipalDep, service: ProjectServiceDep
) -> ProjectResponse:
    """One Project of this tenant's."""
    return _as_project(await service.read(principal, project_id))


@projects_router.patch("/{project_id}", summary="Change a name, deadline, or status")
async def update_project(
    project_id: UUID,
    body: ProjectPatchRequest,
    principal: PrincipalDep,
    service: ProjectServiceDep,
) -> ProjectResponse:
    """Apply a partial update. Completing a Project is a status change and nothing else."""
    change = ProjectChange(
        name=stated_unless_null(body.name),
        deadline=stated(body, "deadline", body.deadline),
        status=stated_unless_null(body.status),
    )
    return _as_project(await service.update(principal, project_id, change))
