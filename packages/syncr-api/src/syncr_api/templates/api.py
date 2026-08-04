"""The twelve day-type, day-shape, and week-pattern routes.

Thin, on purpose. Each handler validates a body, resolves who is asking, calls exactly one
service method, and maps the result onto a response shape. No authorization decision and no
persistence: ``tests/test_authorization_boundary.py`` asserts this file cannot reach either.

Each response is built field by field rather than validated from the record, so a column added
to a table cannot reach the wire by sharing a name with a schema field.

An entry body is a discriminated union and each member builds its own declaration, so no handler
here asks which kind it received. What the handlers do carry is ``stated_rejection`` around the
value they BUILD from a request: a span or a pattern that the domain refuses is a bad request
rather than a state conflict, and the 422 names the field to fix. The same mapping is applied in
the service where a PATCH merges a span, because that is where the merged value is first
expressible.

``PUT /week-pattern`` replaces the whole mapping. There is no ``PATCH``: a pattern maps all seven
weekdays, so a request naming three would have to mean something about the other four.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from fastapi import APIRouter, Body
from starlette.responses import Response

from syncr_api.accounts.injection import PrincipalDep
from syncr_api.core.patches import stated_unless_null
from syncr_api.templates.config import (
    TEMPLATE_ENTRIES_PATH,
    TEMPLATE_ENTRY_PATH,
    TEMPLATE_PATH,
)
from syncr_api.templates.declarations import (
    DayTypeDeclaration,
    EntryChange,
    TemplateChange,
    TemplateDeclaration,
)
from syncr_api.templates.entry_schemas import (
    ConcreteEntryRequest,
    EntryPatchRequest,
    SlotEntryRequest,
    TemplateEntryResponse,
)
from syncr_api.templates.injection import (
    DayTypeServiceDep,
    TemplateServiceDep,
    WeekPatternServiceDep,
)
from syncr_api.templates.rules import stated_rejection
from syncr_api.templates.schemas import (
    DayTypeCreateRequest,
    DayTypeResponse,
    DayTypesResponse,
    TemplateCreateRequest,
    TemplatePatchRequest,
    TemplateResponse,
    TemplatesResponse,
    TemplateSummary,
    WeekPatternRequest,
    WeekPatternResponse,
)
from syncr_domain.templates import WeekPattern

if TYPE_CHECKING:
    from syncr_api.templates.records import DayTypeRecord, TemplateEntryRecord, TemplateRecord

day_types_router = APIRouter()
templates_router = APIRouter()
week_pattern_router = APIRouter()

# The two shapes an entry may be declared in, told apart by `kind`. A caller sending a slot's
# fields under `kind: "concrete"` is refused by the member it selected rather than by a rule
# somewhere that reads both.
type EntryRequest = Annotated[ConcreteEntryRequest | SlotEntryRequest, Body(discriminator="kind")]


def _as_day_type(record: DayTypeRecord) -> DayTypeResponse:
    return DayTypeResponse(id=record.id, name=record.name)


def _as_entry(record: TemplateEntryRecord) -> TemplateEntryResponse:
    return TemplateEntryResponse(
        id=record.id,
        kind=record.kind,
        target_time=record.span.target_time,
        duration_minutes=record.span.duration_minutes,
        flex_band_minutes=record.span.flex_band_minutes,
        area_id=record.area_id,
        binding_target=record.binding_target,
        binding_ref=record.binding_ref,
    )


def _as_template(record: TemplateRecord) -> TemplateResponse:
    return TemplateResponse(
        id=record.id,
        day_type_id=record.day_type_id,
        name=record.name,
        entries=[_as_entry(entry) for entry in record.entries],
    )


def _as_summary(record: TemplateRecord) -> TemplateSummary:
    return TemplateSummary(
        id=record.id,
        day_type_id=record.day_type_id,
        name=record.name,
        entry_count=len(record.entries),
    )


@day_types_router.get("", summary="Every day type")
async def list_day_types(principal: PrincipalDep, service: DayTypeServiceDep) -> DayTypesResponse:
    """The day types, in the order they were declared."""
    declared = await service.list_all(principal)
    return DayTypesResponse(day_types=[_as_day_type(day_type) for day_type in declared])


@day_types_router.post("", status_code=HTTPStatus.CREATED, summary="Declare a day type")
async def declare_day_type(
    body: DayTypeCreateRequest, principal: PrincipalDep, service: DayTypeServiceDep
) -> DayTypeResponse:
    """Declare a kind of day. The week pattern is what puts weekdays onto it."""
    return _as_day_type(await service.create(principal, DayTypeDeclaration(name=body.name)))


@templates_router.get("", summary="Every day shape, with its entry count")
async def list_templates(principal: PrincipalDep, service: TemplateServiceDep) -> TemplatesResponse:
    """The shapes, oldest first, each stating how many entries it holds."""
    declared = await service.list_all(principal)
    return TemplatesResponse(templates=[_as_summary(shape) for shape in declared])


@templates_router.post("", status_code=HTTPStatus.CREATED, summary="Declare a day shape")
async def declare_template(
    body: TemplateCreateRequest, principal: PrincipalDep, service: TemplateServiceDep
) -> TemplateResponse:
    """Declare the shape of a day type. It starts with no entries."""
    declaration = TemplateDeclaration(day_type_id=body.day_type_id, name=body.name)
    return _as_template(await service.create(principal, declaration))


@templates_router.get(TEMPLATE_PATH, summary="One day shape and its entries")
async def read_template(
    template_id: UUID, principal: PrincipalDep, service: TemplateServiceDep
) -> TemplateResponse:
    """One shape of this tenant's, with its entries in the order the day runs."""
    return _as_template(await service.read(principal, template_id))


@templates_router.patch(TEMPLATE_PATH, summary="Rename a day shape")
async def update_template(
    template_id: UUID,
    body: TemplatePatchRequest,
    principal: PrincipalDep,
    service: TemplateServiceDep,
) -> TemplateResponse:
    """Apply a partial update. An omitted field is left alone."""
    change = TemplateChange(name=stated_unless_null(body.name))
    return _as_template(await service.update(principal, template_id, change))


@templates_router.delete(
    TEMPLATE_PATH,
    status_code=HTTPStatus.NO_CONTENT,
    response_class=Response,
    summary="Remove a day shape and its entries",
)
async def remove_template(
    template_id: UUID, principal: PrincipalDep, service: TemplateServiceDep
) -> Response:
    """Remove a shape. Its entries go with it."""
    await service.remove(principal, template_id)
    # Built here rather than returning None, because a returned None is still serialized and a
    # 204 must carry no body at all.
    return Response(status_code=HTTPStatus.NO_CONTENT)


@templates_router.post(
    TEMPLATE_ENTRIES_PATH,
    status_code=HTTPStatus.CREATED,
    summary="Add a concrete entry or a slot to a day shape",
)
async def add_template_entry(
    template_id: UUID,
    body: EntryRequest,
    principal: PrincipalDep,
    service: TemplateServiceDep,
) -> TemplateEntryResponse:
    """Add one entry. A concrete entry names its content; a slot names an Area."""
    with stated_rejection():
        declaration = body.declaration()
    return _as_entry(await service.add_entry(principal, template_id, declaration))


@templates_router.patch(TEMPLATE_ENTRY_PATH, summary="Move or resize one entry")
async def change_template_entry(
    template_id: UUID,
    entry_id: UUID,
    body: EntryPatchRequest,
    principal: PrincipalDep,
    service: TemplateServiceDep,
) -> TemplateEntryResponse:
    """Apply a partial update to an entry's span. What it holds is declared once."""
    change = EntryChange(
        target_time=stated_unless_null(body.target_time),
        duration_minutes=stated_unless_null(body.duration_minutes),
        flex_band_minutes=stated_unless_null(body.flex_band_minutes),
    )
    return _as_entry(await service.change_entry(principal, template_id, entry_id, change))


@templates_router.delete(
    TEMPLATE_ENTRY_PATH,
    status_code=HTTPStatus.NO_CONTENT,
    response_class=Response,
    summary="Remove one entry from a day shape",
)
async def remove_template_entry(
    template_id: UUID, entry_id: UUID, principal: PrincipalDep, service: TemplateServiceDep
) -> Response:
    """Remove one entry of a shape."""
    await service.remove_entry(principal, template_id, entry_id)
    return Response(status_code=HTTPStatus.NO_CONTENT)


@week_pattern_router.get("", summary="Which day type each weekday uses")
async def read_week_pattern(
    principal: PrincipalDep, service: WeekPatternServiceDep
) -> WeekPatternResponse:
    """The pattern, or a 404 when none has been declared yet."""
    pattern = await service.read(principal)
    return WeekPatternResponse.of(pattern.mapping)


@week_pattern_router.put("", summary="Replace the whole mapping. All seven weekdays required")
async def replace_week_pattern(
    body: WeekPatternRequest, principal: PrincipalDep, service: WeekPatternServiceDep
) -> WeekPatternResponse:
    """Replace the mapping. Future weeks re-materialize; approved past weeks do not."""
    with stated_rejection():
        declared = WeekPattern(body.mapping())
    replaced = await service.replace(principal, declared)
    return WeekPatternResponse.of(replaced.mapping)
