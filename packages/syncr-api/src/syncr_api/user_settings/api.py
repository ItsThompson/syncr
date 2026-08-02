"""The five settings routes.

Thin, on purpose. Each handler validates a body, resolves who is asking, calls exactly one
service method, and maps the result onto a response shape. No authorization decision and
no persistence: ``tests/test_authorization_boundary.py`` asserts this file cannot reach
either.

The sleep floor is absent from every shape here, and ``SettingsPatchRequest`` rejects an
unknown field, so sending one is a stated 422 rather than a value quietly dropped. The
floor is ``minDurationMinutes`` on the sleep routine.
"""

from __future__ import annotations

from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter
from starlette.responses import Response

from syncr_api.accounts.injection import PrincipalDep
from syncr_api.user_settings.config import TRAVEL_OVERRIDE_PATH, TRAVEL_OVERRIDES_PATH
from syncr_api.user_settings.injection import SettingsServiceDep
from syncr_api.user_settings.schemas import (
    SettingsPatchRequest,
    SettingsResponse,
    TravelOverrideRequest,
    TravelOverrideResponse,
    TravelOverridesResponse,
)
from syncr_api.user_settings.service import SettingsChange, SettingsView

router = APIRouter()


def _as_response(view: SettingsView) -> SettingsResponse:
    return SettingsResponse(
        visible_hours=view.visible_hours,
        day_start=view.day_start,
        day_end=view.day_end,
        review_cadence=view.review_cadence,
        home_zone=view.home_zone,
        active_zone=view.active_zone,
        active_zone_date=view.active_zone_date,
    )


@router.get("", summary="Grid geometry, home zone, review cadence, and the active zone")
async def read_settings(principal: PrincipalDep, service: SettingsServiceDep) -> SettingsResponse:
    """The settings, and which zone is active today."""
    return _as_response(await service.read(principal))


@router.patch("", summary="Change visible hours, day bounds, home zone, or review cadence")
async def update_settings(
    body: SettingsPatchRequest, principal: PrincipalDep, service: SettingsServiceDep
) -> SettingsResponse:
    """Apply a partial update. An omitted field is left alone."""
    change = SettingsChange(
        visible_hours=body.visible_hours,
        day_start=body.day_start,
        day_end=body.day_end,
        review_cadence=body.review_cadence,
        home_zone=body.home_zone,
    )
    return _as_response(await service.update(principal, change))


@router.get(TRAVEL_OVERRIDES_PATH, summary="Declared ranges in another zone")
async def list_travel_overrides(
    principal: PrincipalDep, service: SettingsServiceDep
) -> TravelOverridesResponse:
    """Every override, in date order."""
    overrides = await service.list_travel_overrides(principal)
    return TravelOverridesResponse(
        overrides=[
            TravelOverrideResponse(
                id=override.id,
                start_date=override.start_date,
                end_date=override.end_date,
                zone=override.zone,
            )
            for override in overrides
        ]
    )


@router.post(
    TRAVEL_OVERRIDES_PATH,
    status_code=HTTPStatus.CREATED,
    summary="Declare a range in another zone",
)
async def declare_travel_override(
    body: TravelOverrideRequest, principal: PrincipalDep, service: SettingsServiceDep
) -> TravelOverrideResponse:
    """Declare a range, or state why it overlaps one already declared."""
    created = await service.declare_travel_override(
        principal, start_date=body.start_date, end_date=body.end_date, zone=body.zone
    )
    return TravelOverrideResponse(
        id=created.id,
        start_date=created.start_date,
        end_date=created.end_date,
        zone=created.zone,
    )


@router.delete(
    TRAVEL_OVERRIDE_PATH,
    status_code=HTTPStatus.NO_CONTENT,
    response_class=Response,
    summary="Remove a declared range",
)
async def remove_travel_override(
    override_id: UUID, principal: PrincipalDep, service: SettingsServiceDep
) -> Response:
    """Remove an override, so the home zone governs its dates again."""
    await service.remove_travel_override(principal, override_id)
    # Built here rather than returning None, because a returned None is still serialized
    # and a 204 must carry no body at all.
    return Response(status_code=HTTPStatus.NO_CONTENT)
