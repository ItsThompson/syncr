"""The dependencies the day-type, day-shape, and week-pattern routes declare.

Every repository is scoped to the principal's tenant HERE, at the one point where the principal
is available and before a service exists. That is what makes the scope structural: there is no
code path that builds one of these repositories without a tenant, so no statement they compose
can reach another tenant's rows.

Four collaborators come from other feature modules, and each is deliberate rather than
convenient. The Areas repository is read because a slot names an Area and the Area has to be this
tenant's. The routines and habits repositories are read because a concrete entry's binding names a
row of one of them, and only a scoped read answers another tenant's identifier as absent.
``BacklogWideBump`` carries plan storage's version counter and the settings read the home
zone: a day shape is a solve input with no end date, so it needs the same four steps every such
mutation needs, and there is one implementation of them.

The two services that declare a row behind a unique index are handed the request transaction's
savepoint, which is what lets a write refused by that index be answered by the read it passed
rather than abandoning the transaction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends
from starlette.requests import Request  # noqa: TC002

# FastAPI resolves this function's annotations at RUNTIME to build the dependency graph, and
# these two names are only reachable from an annotation, so under TYPE_CHECKING they would
# resolve to a NameError while the app is being constructed.
from syncr_api.accounts.injection import PrincipalDep, TransactionDep  # noqa: TC001
from syncr_api.areas.repository import AreaRepository
from syncr_api.calendars.repository import CalendarSourceRepository
from syncr_api.core.clock import utc_now
from syncr_api.habits.repository import HabitRepository
from syncr_api.horizon.projection import CurrentProjectionHorizon
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.routines.repository import RoutineRepository
from syncr_api.solving.injection import build_solve_requests, configured_debounce
from syncr_api.templates.bindings import TemplateBindings
from syncr_api.templates.invalidation import FutureWeeks
from syncr_api.templates.repository import (
    DayTypeRepository,
    TemplateRepository,
    WeekPatternRepository,
)
from syncr_api.templates.service import DayTypeService, TemplateService, WeekPatternService
from syncr_api.user_settings.repository import SettingsRepository
from syncr_api.user_settings.solve_inputs import BacklogWideBump, TrackedWeekInputVersions

if TYPE_CHECKING:
    from datetime import timedelta

    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_domain.identifiers import TenantId


def _future_weeks(
    transaction: AsyncSession, tenant_id: TenantId, *, debounce: timedelta
) -> FutureWeeks:
    """The invalidation rule, wired for one tenant."""
    settings = SettingsRepository(transaction, tenant_id)
    return FutureWeeks(
        patterns=WeekPatternRepository(transaction, tenant_id),
        bump=BacklogWideBump(
            versions=TrackedWeekInputVersions(
                WeekInputVersionRepository(transaction, tenant_id), clock=utc_now
            ),
            settings=settings,
        ),
        solve_requests=build_solve_requests(
            transaction,
            tenant_id,
            clock=utc_now,
            debounce=debounce,
        ),
        horizon=CurrentProjectionHorizon(
            CalendarSourceRepository(transaction, tenant_id), settings
        ),
        clock=utc_now,
    )


def get_day_type_service(principal: PrincipalDep, transaction: TransactionDep) -> DayTypeService:
    """The day-type service. It bumps no input version: a new day type is mapped by nothing."""
    return DayTypeService(
        day_types=DayTypeRepository(transaction, principal.tenant_id),
        clock=utc_now,
        savepoint=transaction.begin_nested,
    )


def get_template_service(
    request: Request, principal: PrincipalDep, transaction: TransactionDep
) -> TemplateService:
    """The day-shape service, wired for this request and scoped to this tenant."""
    return build_template_service(
        transaction, principal.tenant_id, debounce=configured_debounce(request)
    )


def build_template_service(
    transaction: AsyncSession, tenant_id: TenantId, *, debounce: timedelta
) -> TemplateService:
    """The day-shape service, wired for one tenant."""
    return TemplateService(
        templates=TemplateRepository(transaction, tenant_id),
        day_types=DayTypeRepository(transaction, tenant_id),
        areas=AreaRepository(transaction, tenant_id),
        bindings=TemplateBindings(
            routines=RoutineRepository(transaction, tenant_id),
            habits=HabitRepository(transaction, tenant_id),
        ),
        weeks=_future_weeks(transaction, tenant_id, debounce=debounce),
        clock=utc_now,
        savepoint=transaction.begin_nested,
    )


def get_week_pattern_service(
    request: Request, principal: PrincipalDep, transaction: TransactionDep
) -> WeekPatternService:
    """The week-pattern service. Replacing the mapping invalidates every future week."""
    return build_week_pattern_service(
        transaction, principal.tenant_id, debounce=configured_debounce(request)
    )


def build_week_pattern_service(
    transaction: AsyncSession, tenant_id: TenantId, *, debounce: timedelta
) -> WeekPatternService:
    """The week-pattern service, wired for one tenant."""
    return WeekPatternService(
        patterns=WeekPatternRepository(transaction, tenant_id),
        day_types=DayTypeRepository(transaction, tenant_id),
        weeks=_future_weeks(transaction, tenant_id, debounce=debounce),
    )


type DayTypeServiceDep = Annotated[DayTypeService, Depends(get_day_type_service)]
type TemplateServiceDep = Annotated[TemplateService, Depends(get_template_service)]
type WeekPatternServiceDep = Annotated[WeekPatternService, Depends(get_week_pattern_service)]
