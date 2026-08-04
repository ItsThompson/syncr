"""The seven anchor and anchor-type routes.

Thin, on purpose. Each handler reads a request, resolves who is asking, calls exactly one service
method, and maps the result onto a response shape. No authorization decision and no persistence:
``tests/test_authorization_boundary.py`` asserts this file cannot reach either.

**There is no route that edits or removes an anchor.** ``PUT .../type`` is the only mutation on
one, and it changes what the commitment reserves around itself rather than the commitment. That
absence is asserted mechanically in ``tests/test_anchor_read_only_boundary.py``, because "we did
not add an edit route" is a claim that decays the moment someone needs one.

``PUT /anchor-types/order`` is declared BEFORE ``/{anchor_type_id}``. The framework matches in
declaration order, so the reverse would read ``order`` as an identifier and answer 422 to the
reorder route.

Each response is built field by field rather than validated from a record, so a column added to a
table cannot reach the wire by sharing a name with a schema field. That is what keeps
``Anchor.location`` off the wire: it is stored, it has no reader, and nothing here names it.
"""

from __future__ import annotations

from datetime import datetime
from http import HTTPStatus
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Query
from starlette.responses import Response

from syncr_api.accounts.injection import PrincipalDep
from syncr_api.anchors.config import (
    ANCHOR_PAGE_LIMIT_DEFAULT,
    ANCHOR_PAGE_LIMIT_MAX,
    ANCHOR_TYPE_ASSIGNMENT_PATH,
    ANCHOR_TYPE_ORDER_PATH,
    ANCHOR_TYPE_PATH,
)
from syncr_api.anchors.declarations import AnchorTypeChange, RuleOrder, TypeAssignment
from syncr_api.anchors.injection import AnchorServiceDep, AnchorTypeServiceDep
from syncr_api.anchors.queries import decode_cursor, encode_cursor, read_span
from syncr_api.anchors.records import AnchorTypeSpecification, ShadowDeclaration
from syncr_api.anchors.schemas import (
    AnchorResponse,
    AnchorsResponse,
    AnchorTypeCreateRequest,
    AnchorTypePatchRequest,
    AnchorTypeResponse,
    AnchorTypesResponse,
    ReorderAnchorTypesRequest,
    RetypeAnchorRequest,
    RetypedAnchorResponse,
    ShadowDeclarationResponse,
)
from syncr_api.core.patches import stated, stated_unless_null
from syncr_api.idempotency.injection import IdempotencyGuardDep

if TYPE_CHECKING:
    from syncr_api.anchors.records import AnchorTypeRecord
    from syncr_api.anchors.views import AnchorView

anchors_router = APIRouter()
anchor_types_router = APIRouter()

DECLARE_ANCHOR_TYPE_ROUTE = "anchors.declare_anchor_type"

_FROM = Query(alias="from", description="The start of the span, included.")
_TO = Query(alias="to", description="The end of the span, excluded.")
_CURSOR = Query(default=None, description="The `nextCursor` a previous page handed back.")
_LIMIT = Query(
    default=ANCHOR_PAGE_LIMIT_DEFAULT,
    ge=1,
    le=ANCHOR_PAGE_LIMIT_MAX,
    description="How many commitments one page holds.",
)


def _as_casts(declaration: ShadowDeclaration) -> ShadowDeclarationResponse:
    return ShadowDeclarationResponse(
        prep=declaration.prep,
        outbound_transit=declaration.outbound_transit,
        return_transit=declaration.return_transit,
        recovery=declaration.recovery,
    )


def _as_anchor(view: AnchorView) -> AnchorResponse:
    anchor = view.anchor
    return AnchorResponse(
        id=anchor.id,
        source_id=anchor.source_id,
        source_name=view.source_name,
        read_only=True,
        read_only_statement=view.read_only_statement,
        series_uid=anchor.series_uid,
        title=anchor.title,
        starts_at=anchor.interval.start,
        ends_at=anchor.interval.end,
        anchor_type_id=anchor.anchor_type_id,
        anchor_type_name=None if view.anchor_type is None else view.anchor_type.name,
        type_source=anchor.type_source,
        possibly_stale=anchor.possibly_stale,
        casts=_as_casts(view.casts),
    )


def _as_type(record: AnchorTypeRecord) -> AnchorTypeResponse:
    declared = record.specification
    return AnchorTypeResponse(
        id=record.id,
        name=declared.name,
        rule_order=record.rule_order,
        match_title_contains=declared.match_title_contains,
        match_source_id=declared.match_source_id,
        prep_lead_minutes=declared.prep_lead_minutes,
        prep_duration_minutes=declared.prep_duration_minutes,
        prep_area_id=declared.prep_area_id,
        transit_lead_minutes=declared.transit_lead_minutes,
        transit_duration_minutes=declared.transit_duration_minutes,
        return_transit_minutes=declared.return_transit_minutes,
        transit_area_id=declared.transit_area_id,
        post_buffer_minutes=declared.post_buffer_minutes,
        post_scope=declared.post_scope,
        forbidden_area_ids=list(declared.forbidden_area_ids),
        casts=_as_casts(record.declared_shadow()),
    )


@anchors_router.get("", summary="Commitments in a span. Read-only")
async def list_anchors(
    principal: PrincipalDep,
    service: AnchorServiceDep,
    start: datetime = _FROM,
    end: datetime = _TO,
    cursor: str | None = _CURSOR,
    limit: int = _LIMIT,
) -> AnchorsResponse:
    """The commitments overlapping the span, earliest first, one page at a time."""
    page = await service.list_in_span(
        principal, read_span(start, end), limit=limit, after=decode_cursor(cursor)
    )
    return AnchorsResponse(
        anchors=[_as_anchor(view) for view in page.views],
        next_cursor=None if page.next_cursor is None else encode_cursor(page.next_cursor),
    )


@anchors_router.get("/{anchor_id}", summary="One commitment, with its source named")
async def read_anchor(
    anchor_id: UUID, principal: PrincipalDep, service: AnchorServiceDep
) -> AnchorResponse:
    """One commitment. The payload names its source and states that it is read-only."""
    return _as_anchor(await service.read(principal, anchor_id))


@anchors_router.put(
    ANCHOR_TYPE_ASSIGNMENT_PATH, summary="Retype a commitment. Persists on the series"
)
async def retype_anchor(
    anchor_id: UUID,
    body: RetypeAnchorRequest,
    principal: PrincipalDep,
    service: AnchorServiceDep,
) -> RetypedAnchorResponse:
    """Retype one occurrence. The choice persists on its series and survives a rule change."""
    retyped = await service.retype(
        principal, anchor_id, TypeAssignment(anchor_type_id=body.anchor_type_id)
    )
    return RetypedAnchorResponse(
        anchor=_as_anchor(retyped.view), occurrences_retyped=retyped.occurrences_retyped
    )


@anchor_types_router.get("", summary="Every anchor type, in evaluation order")
async def list_anchor_types(
    principal: PrincipalDep, service: AnchorTypeServiceDep
) -> AnchorTypesResponse:
    """The types, in the order rules evaluate. The first match wins."""
    found = await service.list_all(principal)
    return AnchorTypesResponse(anchor_types=[_as_type(record) for record in found])


@anchor_types_router.post(
    "", status_code=HTTPStatus.CREATED, summary="Declare an anchor type at the end of the order"
)
async def declare_anchor_type(
    body: AnchorTypeCreateRequest,
    principal: PrincipalDep,
    guard: IdempotencyGuardDep,
    service: AnchorTypeServiceDep,
) -> AnchorTypeResponse:
    """Declare a type. It is appended, so it cannot silently outrank rules already ordered."""
    specification = AnchorTypeSpecification(
        name=body.name,
        match_title_contains=body.match_title_contains,
        match_source_id=body.match_source_id,
        prep_lead_minutes=body.prep_lead_minutes,
        prep_duration_minutes=body.prep_duration_minutes,
        prep_area_id=body.prep_area_id,
        transit_lead_minutes=body.transit_lead_minutes,
        transit_duration_minutes=body.transit_duration_minutes,
        return_transit_minutes=body.return_transit_minutes,
        transit_area_id=body.transit_area_id,
        post_buffer_minutes=body.post_buffer_minutes,
        post_scope=body.post_scope,
        forbidden_area_ids=tuple(body.forbidden_area_ids),
    )

    async def declare() -> AnchorTypeResponse:
        return _as_type(await service.create(principal, specification))

    return await guard.once(DECLARE_ANCHOR_TYPE_ROUTE, AnchorTypeResponse, declare)


@anchor_types_router.put(
    ANCHOR_TYPE_ORDER_PATH, summary="Reorder the rules. Re-evaluates existing commitments"
)
async def reorder_anchor_types(
    body: ReorderAnchorTypesRequest,
    principal: PrincipalDep,
    service: AnchorTypeServiceDep,
) -> AnchorTypesResponse:
    """Rewrite the whole evaluation order, and re-match every commitment a rule may still type."""
    reordered = await service.reorder(
        principal, RuleOrder(anchor_type_ids=tuple(body.anchor_type_ids))
    )
    return AnchorTypesResponse(anchor_types=[_as_type(record) for record in reordered])


@anchor_types_router.get(ANCHOR_TYPE_PATH, summary="One anchor type and the shadow it declares")
async def read_anchor_type(
    anchor_type_id: UUID, principal: PrincipalDep, service: AnchorTypeServiceDep
) -> AnchorTypeResponse:
    """One type of this tenant's."""
    return _as_type(await service.read(principal, anchor_type_id))


@anchor_types_router.patch(ANCHOR_TYPE_PATH, summary="Change a match rule or a shadow member")
async def update_anchor_type(
    anchor_type_id: UUID,
    body: AnchorTypePatchRequest,
    principal: PrincipalDep,
    service: AnchorTypeServiceDep,
) -> AnchorTypeResponse:
    """Apply a partial update. An omitted field is left alone; an explicit null clears one."""
    change = AnchorTypeChange(
        name=stated_unless_null(body.name),
        match_title_contains=stated(body, "match_title_contains", body.match_title_contains),
        match_source_id=stated(body, "match_source_id", body.match_source_id),
        prep_lead_minutes=stated_unless_null(body.prep_lead_minutes),
        prep_duration_minutes=stated_unless_null(body.prep_duration_minutes),
        prep_area_id=stated(body, "prep_area_id", body.prep_area_id),
        transit_lead_minutes=stated(body, "transit_lead_minutes", body.transit_lead_minutes),
        transit_duration_minutes=stated_unless_null(body.transit_duration_minutes),
        return_transit_minutes=stated_unless_null(body.return_transit_minutes),
        transit_area_id=stated(body, "transit_area_id", body.transit_area_id),
        post_buffer_minutes=stated_unless_null(body.post_buffer_minutes),
        post_scope=stated_unless_null(body.post_scope),
        forbidden_area_ids=stated_unless_null(
            None if body.forbidden_area_ids is None else tuple(body.forbidden_area_ids)
        ),
    )
    return _as_type(await service.update(principal, anchor_type_id, change))


@anchor_types_router.delete(
    ANCHOR_TYPE_PATH,
    status_code=HTTPStatus.NO_CONTENT,
    response_class=Response,
    summary="Remove an anchor type. Its commitments return to rule matching",
)
async def remove_anchor_type(
    anchor_type_id: UUID, principal: PrincipalDep, service: AnchorTypeServiceDep
) -> Response:
    """Remove a type. Every commitment holding it is released back to the rules."""
    await service.remove(principal, anchor_type_id)
    # Built here rather than returning None, because a returned None is still serialized and a
    # 204 must carry no body at all.
    return Response(status_code=HTTPStatus.NO_CONTENT)
