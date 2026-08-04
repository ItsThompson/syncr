"""The five habit routes.

Thin, on purpose. Each handler validates a body, resolves who is asking, calls exactly one
service method, and maps the result onto a response shape. No authorization decision and no
persistence: ``tests/test_authorization_boundary.py`` asserts this file cannot reach either.

Each response is built field by field rather than validated from the record, so a column added
to the table cannot reach the wire by sharing a name with a schema field. That is also what
keeps the cursor read-only: it is rendered from the derivation's own reading and there is no
field on any request that could carry one back.

All three unsafe methods take the idempotency guard, because an agent retrying a mutation must
not apply it twice. The removal takes it too, which is why it has a response model at all: the
guard replays a stored response, and without one a retry with the same key would find the habit
already gone and answer 404 for a request that succeeded.

``PATCH`` builds its change through :func:`syncr_api.core.patches.stated_unless_null`. Nothing on
a habit is nullable, so the schema refuses an explicit null and ``None`` can only mean the
request left the field out.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Query
from starlette.responses import Response

from syncr_api.accounts.injection import PrincipalDep
from syncr_api.core.patches import stated_unless_null
from syncr_api.habits.config import HABIT_PATH
from syncr_api.habits.declarations import DeclaredCadence, HabitChange, HabitDeclaration
from syncr_api.habits.injection import HabitServiceDep
from syncr_api.habits.schemas import (
    CadenceResponse,
    CursorResponse,
    DebtResponse,
    HabitCreateRequest,
    HabitPatchRequest,
    HabitRemoved,
    HabitResponse,
    HabitsResponse,
)
from syncr_api.idempotency.injection import IdempotencyGuardDep

if TYPE_CHECKING:
    from syncr_api.habits.records import HabitRecord
    from syncr_api.habits.schemas import CadenceRequest
    from syncr_api.habits.service import ReadHabit
    from syncr_domain.cursor import CursorReading
    from syncr_domain.debt import DebtReading

router = APIRouter()

DECLARE_HABIT_ROUTE = "habits.declare"
CHANGE_HABIT_ROUTE = "habits.change"
REMOVE_HABIT_ROUTE = "habits.remove"


def _declared_cadence(body: CadenceRequest) -> DeclaredCadence:
    return DeclaredCadence(
        kind=body.kind, times_per_week=body.times_per_week, approx_days=body.approx_days
    )


def _as_cadence(record: HabitRecord) -> CadenceResponse:
    return CadenceResponse(
        kind=record.cadence_kind,
        times_per_week=record.cadence_times_per_week,
        approx_days=record.cadence_approx_days,
    )


def _as_cursor(reading: CursorReading | None) -> CursorResponse | None:
    if reading is None:
        return None
    return CursorResponse(
        index=reading.index,
        variant=reading.variant,
        confirmed_completions=reading.confirmed_completions,
        previous_variant=reading.previous_variant,
        advanced_at=reading.advanced_at,
        statement=reading.statement,
    )


def _as_debt(reading: DebtReading) -> DebtResponse:
    return DebtResponse(
        outstanding=reading.outstanding,
        cap=reading.cap,
        misses=reading.misses,
        forgiven_at_cap=reading.forgiven_at_cap,
        raised_in_weekly_session=reading.raised_in_weekly_session,
        statement=reading.statement,
    )


def _as_habit(read: ReadHabit) -> HabitResponse:
    record = read.habit
    return HabitResponse(
        id=record.id,
        area_id=record.area_id,
        title=record.title,
        cadence=_as_cadence(record),
        min_duration_minutes=record.duration_min_minutes,
        max_duration_minutes=record.duration_max_minutes,
        miss_policy=record.miss_policy,
        binding_source=record.binding_source,
        variants=list(record.variants),
        debt_cap_periods=record.debt_cap_periods,
        cursor=_as_cursor(read.cursor),
        debt=_as_debt(read.debt),
    )


@router.get("", summary="Every habit, with its cursor and its debt")
async def list_habits(
    principal: PrincipalDep,
    service: HabitServiceDep,
    area_id: UUID | None = Query(default=None, alias="areaId"),
) -> HabitsResponse:
    """The habits, in the order they were declared. Both derived figures travel with each."""
    found = await service.list_all(principal, area_id=area_id)
    return HabitsResponse(habits=[_as_habit(read) for read in found])


@router.post("", status_code=HTTPStatus.CREATED, summary="Declare a habit inside an Area")
async def declare_habit(
    body: HabitCreateRequest,
    principal: PrincipalDep,
    guard: IdempotencyGuardDep,
    service: HabitServiceDep,
) -> HabitResponse:
    """Declare a habit. Cadence lives here; a preferred time does not."""
    declaration = HabitDeclaration(
        area_id=body.area_id,
        title=body.title,
        cadence=_declared_cadence(body.cadence),
        min_duration_minutes=body.min_duration_minutes,
        max_duration_minutes=body.max_duration_minutes,
        miss_policy=body.miss_policy,
        binding_source=body.binding_source,
        variants=tuple(body.variants),
        debt_cap_periods=body.debt_cap_periods,
    )

    async def declare() -> HabitResponse:
        return _as_habit(await service.create(principal, declaration))

    return await guard.once(DECLARE_HABIT_ROUTE, HabitResponse, declare)


@router.get(HABIT_PATH, summary="One habit, with its cursor read-only and its provenance")
async def read_habit(
    habit_id: UUID, principal: PrincipalDep, service: HabitServiceDep
) -> HabitResponse:
    """One habit of this tenant's."""
    return _as_habit(await service.read(principal, habit_id))


@router.patch(HABIT_PATH, summary="Change a cadence, duration, policy, source, or variants")
async def change_habit(
    habit_id: UUID,
    body: HabitPatchRequest,
    principal: PrincipalDep,
    guard: IdempotencyGuardDep,
    service: HabitServiceDep,
) -> HabitResponse:
    """Apply a partial update. Future occurrences change; recorded past ones do not."""
    change = HabitChange(
        title=stated_unless_null(body.title),
        cadence=stated_unless_null(
            None if body.cadence is None else _declared_cadence(body.cadence)
        ),
        min_duration_minutes=stated_unless_null(body.min_duration_minutes),
        max_duration_minutes=stated_unless_null(body.max_duration_minutes),
        miss_policy=stated_unless_null(body.miss_policy),
        binding_source=stated_unless_null(body.binding_source),
        variants=stated_unless_null(None if body.variants is None else tuple(body.variants)),
        debt_cap_periods=stated_unless_null(body.debt_cap_periods),
    )

    async def change_it() -> HabitResponse:
        return _as_habit(await service.update(principal, habit_id, change))

    return await guard.once(CHANGE_HABIT_ROUTE, HabitResponse, change_it)


@router.delete(
    HABIT_PATH,
    status_code=HTTPStatus.NO_CONTENT,
    response_class=Response,
    summary="Remove a habit. Its recorded outcomes stay, because they are facts",
)
async def remove_habit(
    habit_id: UUID,
    principal: PrincipalDep,
    guard: IdempotencyGuardDep,
    service: HabitServiceDep,
) -> Response:
    """Remove a habit. Future occurrences stop; weeks that already happened read as they did."""

    async def remove() -> HabitRemoved:
        await service.remove(principal, habit_id)
        return HabitRemoved()

    await guard.once(REMOVE_HABIT_ROUTE, HabitRemoved, remove)
    # Built here rather than returning None, because a returned None is still serialized and a
    # 204 must carry no body at all.
    return Response(status_code=HTTPStatus.NO_CONTENT)
