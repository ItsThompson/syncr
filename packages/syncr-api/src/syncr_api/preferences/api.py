"""The nine preference routes: read, replace, and remove one for each kind of owner.

Thin, on purpose. Each handler validates a body, resolves who is asking, calls exactly one service
method, and maps the result onto a response shape. No authorization decision and no persistence:
``tests/test_authorization_boundary.py`` asserts this file cannot reach either.

Each response is built field by field rather than validated from the record, so a column added to
the table cannot reach the wire by sharing a name with a schema field.

**Each handler names its own kind of owner, and nothing here branches on one.** The kind is a
literal at the call site, which is what keeps the mapping from a kind to the table that answers for
it in one place rather than three.

**``PUT``, not ``PATCH``.** A preference replaces its Area's windows and ideal duration wholly, so
there is no partial update to offer. Only the Area's handler takes a shape carrying a daily cap; the
other two take a shape with no field for one.

**Every unsafe method takes the idempotency guard, offered rather than demanded.** A replacement
and a removal converge by construction, but that equality rests on today's service logic, which
nothing asserts. Under one key a repeat reads the first request's stored answer instead of
re-executing, so a retried ``DELETE`` answers the claim the first one stored rather than whatever
the owner's preference has become since.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter

from syncr_api.accounts.injection import PrincipalDep
from syncr_api.idempotency.injection import IdempotencyGuardDep
from syncr_api.preferences.declarations import DeclaredWindow, PreferenceDeclaration
from syncr_api.preferences.injection import PreferenceServiceDep
from syncr_api.preferences.schemas import (
    AreaPreferenceRequest,
    DeclaredPreferenceResponse,
    EffectivePreferenceResponse,
    OverridePreferenceRequest,
    PreferenceOwnerResponse,
    PreferenceResponse,
)
from syncr_domain.preferences import PreferenceOwnerKind

if TYPE_CHECKING:
    from syncr_api.preferences.service import ReadPreference

area_router = APIRouter()
habit_router = APIRouter()
task_router = APIRouter()

AREA_REPLACE_ROUTE = "preferences.replace_area"
AREA_REMOVE_ROUTE = "preferences.remove_area"
HABIT_REPLACE_ROUTE = "preferences.replace_habit"
HABIT_REMOVE_ROUTE = "preferences.remove_habit"
TASK_REPLACE_ROUTE = "preferences.replace_task"
TASK_REMOVE_ROUTE = "preferences.remove_task"


def _declared_windows(body: OverridePreferenceRequest) -> tuple[DeclaredWindow, ...]:
    """The window pairs the body states, still as wall times.

    Not turned into domain windows here: every refusal a window carries is the domain's, and the
    service is where a domain rejection becomes the 422 the caller owes.
    """
    return tuple(DeclaredWindow(start=window.start, end=window.end) for window in body.windows)


def _declared(body: OverridePreferenceRequest) -> PreferenceDeclaration:
    """The declaration an override's body states. It names no cap, because it has no field for one.

    ``AreaPreferenceRequest`` is a subclass, so this reads the three shared fields off either shape
    and the Area's handler adds the cap. That is what keeps the cap the only difference between the
    two paths.
    """
    return PreferenceDeclaration(
        windows=_declared_windows(body),
        strength=body.strength,
        preferred_duration_minutes=body.preferred_duration_minutes,
        max_per_day_minutes=None,
    )


def _as_response(read: ReadPreference) -> PreferenceResponse:
    return PreferenceResponse(
        owner=PreferenceOwnerResponse.of(read.owner),
        declared=(None if read.declared is None else DeclaredPreferenceResponse.of(read.declared)),
        effective=(
            None
            if read.in_effect is None
            else EffectivePreferenceResponse.of(read.in_effect, owner=read.owner)
        ),
    )


@area_router.get("", summary="An Area's preference, and what is in effect for it")
async def read_area_preference(
    area_id: UUID, principal: PrincipalDep, service: PreferenceServiceDep
) -> PreferenceResponse:
    """An Area's own preference. For an Area, what it declares is what is in effect."""
    return _as_response(await service.read(principal, PreferenceOwnerKind.AREA, area_id))


@area_router.put("", summary="Replace an Area's preference whole. The only shape taking a cap")
async def replace_area_preference(
    area_id: UUID,
    body: AreaPreferenceRequest,
    principal: PrincipalDep,
    guard: IdempotencyGuardDep,
    service: PreferenceServiceDep,
) -> PreferenceResponse:
    """Replace an Area's preference. Every habit and task inside it inherits unless it overrides."""
    declaration = PreferenceDeclaration(
        windows=_declared_windows(body),
        strength=body.strength,
        preferred_duration_minutes=body.preferred_duration_minutes,
        max_per_day_minutes=body.max_per_day_minutes,
    )

    async def replace() -> PreferenceResponse:
        return _as_response(
            await service.replace(principal, PreferenceOwnerKind.AREA, area_id, declaration)
        )

    return await guard.once(AREA_REPLACE_ROUTE, PreferenceResponse, replace)


@area_router.delete("", summary="Remove an Area's preference. Nothing then biases its placement")
async def remove_area_preference(
    area_id: UUID,
    principal: PrincipalDep,
    guard: IdempotencyGuardDep,
    service: PreferenceServiceDep,
) -> PreferenceResponse:
    """Remove an Area's preference. Its habits and tasks fall back to their own overrides only."""

    async def remove() -> PreferenceResponse:
        return _as_response(await service.remove(principal, PreferenceOwnerKind.AREA, area_id))

    return await guard.once(AREA_REMOVE_ROUTE, PreferenceResponse, remove)


@habit_router.get("", summary="A habit's preference, and which one is in effect")
async def read_habit_preference(
    habit_id: UUID, principal: PrincipalDep, service: PreferenceServiceDep
) -> PreferenceResponse:
    """A habit's own preference if it has one, and its Area's otherwise."""
    return _as_response(await service.read(principal, PreferenceOwnerKind.HABIT, habit_id))


@habit_router.put("", summary="Replace a habit's preference whole. It replaces its Area's")
async def replace_habit_preference(
    habit_id: UUID,
    body: OverridePreferenceRequest,
    principal: PrincipalDep,
    guard: IdempotencyGuardDep,
    service: PreferenceServiceDep,
) -> PreferenceResponse:
    """Override a habit's Area wholly. A cap is not a field of this shape, so one is a 422."""

    async def replace() -> PreferenceResponse:
        return _as_response(
            await service.replace(principal, PreferenceOwnerKind.HABIT, habit_id, _declared(body))
        )

    return await guard.once(HABIT_REPLACE_ROUTE, PreferenceResponse, replace)


@habit_router.delete("", summary="Remove a habit's override, restoring its Area's preference")
async def remove_habit_preference(
    habit_id: UUID,
    principal: PrincipalDep,
    guard: IdempotencyGuardDep,
    service: PreferenceServiceDep,
) -> PreferenceResponse:
    """Remove the override. The response states which preference is in effect afterwards."""

    async def remove() -> PreferenceResponse:
        return _as_response(await service.remove(principal, PreferenceOwnerKind.HABIT, habit_id))

    return await guard.once(HABIT_REMOVE_ROUTE, PreferenceResponse, remove)


@task_router.get("", summary="A task's preference, and which one is in effect")
async def read_task_preference(
    task_id: UUID, principal: PrincipalDep, service: PreferenceServiceDep
) -> PreferenceResponse:
    """A task's own preference if it has one, and its Area's otherwise."""
    return _as_response(await service.read(principal, PreferenceOwnerKind.TASK, task_id))


@task_router.put("", summary="Replace a task's preference whole. It replaces its Area's")
async def replace_task_preference(
    task_id: UUID,
    body: OverridePreferenceRequest,
    principal: PrincipalDep,
    guard: IdempotencyGuardDep,
    service: PreferenceServiceDep,
) -> PreferenceResponse:
    """Override a task's Area wholly. A cap is not a field of this shape, so one is a 422."""

    async def replace() -> PreferenceResponse:
        return _as_response(
            await service.replace(principal, PreferenceOwnerKind.TASK, task_id, _declared(body))
        )

    return await guard.once(TASK_REPLACE_ROUTE, PreferenceResponse, replace)


@task_router.delete("", summary="Remove a task's override, restoring its Area's preference")
async def remove_task_preference(
    task_id: UUID,
    principal: PrincipalDep,
    guard: IdempotencyGuardDep,
    service: PreferenceServiceDep,
) -> PreferenceResponse:
    """Remove the override. The response states which preference is in effect afterwards."""

    async def remove() -> PreferenceResponse:
        return _as_response(await service.remove(principal, PreferenceOwnerKind.TASK, task_id))

    return await guard.once(TASK_REMOVE_ROUTE, PreferenceResponse, remove)
