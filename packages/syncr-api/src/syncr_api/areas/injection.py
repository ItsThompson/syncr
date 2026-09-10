"""The dependencies the Area and Project routes declare.

Every repository is scoped to the principal's tenant HERE, at the one point where the principal
is available and before a service exists. That is what makes the scope structural: there is no
code path that builds one of these repositories without a tenant, so no statement they compose
can reach another tenant's rows.

The principal comes from ``accounts.injection``, which carries the origin check with it. This
module adds no second way to resolve one.

Two collaborators come from other feature modules, and both are deliberate rather than
convenient. The week input version counter is plan storage's, because a budget is a solve input
and there is one serialization point for anything that invalidates a running solve. The settings
repository is read for the home zone, because the week a budget change first affects is decided
by today's LOCAL date, and resolving that in a second place would let the two disagree. Both
reach the service inside ``BacklogWideBump``, which is the one implementation of those four
steps.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends
from starlette.requests import Request  # noqa: TC002

# FastAPI resolves this function's annotations at RUNTIME to build the dependency graph, and
# these two names are only reachable from an annotation, so under TYPE_CHECKING they would
# resolve to a NameError while the app is being constructed.
from syncr_api.accounts.injection import (  # noqa: TC001
    ClientPrincipalDep,
    PrincipalDep,
    TransactionDep,
)
from syncr_api.areas.repository import AreaRepository, ProjectRepository
from syncr_api.areas.service import AreaService, ProjectService
from syncr_api.calendars.repository import CalendarSourceRepository
from syncr_api.core.clock import utc_now
from syncr_api.horizon.projection import CurrentProjectionHorizon
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.injection import build_solve_requests, configured_debounce
from syncr_api.user_settings.repository import SettingsRepository
from syncr_api.user_settings.solve_inputs import BacklogWideBump, TrackedWeekInputVersions

if TYPE_CHECKING:
    from datetime import timedelta

    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_domain.identifiers import TenantId


def get_area_service(
    request: Request, principal: ClientPrincipalDep, transaction: TransactionDep
) -> AreaService:
    """The Area service, wired for this request and scoped to this tenant."""
    return build_area_service(
        transaction,
        principal.tenant_id,
        debounce=configured_debounce(request),
    )


def build_area_service(
    transaction: AsyncSession, tenant_id: TenantId, *, debounce: timedelta
) -> AreaService:
    """The Area service, wired for a tenant with its deployment debounce setting."""
    return AreaService(
        areas=AreaRepository(transaction, tenant_id),
        bump=BacklogWideBump(
            versions=TrackedWeekInputVersions(
                WeekInputVersionRepository(transaction, tenant_id), clock=utc_now
            ),
            settings=SettingsRepository(transaction, tenant_id),
        ),
        solve_requests=build_solve_requests(
            transaction,
            tenant_id,
            clock=utc_now,
            debounce=debounce,
        ),
        horizon=CurrentProjectionHorizon(
            CalendarSourceRepository(transaction, tenant_id),
            SettingsRepository(transaction, tenant_id),
        ),
        clock=utc_now,
    )


def get_project_service(principal: PrincipalDep, transaction: TransactionDep) -> ProjectService:
    """The Project service. It bumps no input version, because a Project declares no budget."""
    return ProjectService(
        projects=ProjectRepository(transaction, principal.tenant_id),
        areas=AreaRepository(transaction, principal.tenant_id),
        clock=utc_now,
    )


type AreaServiceDep = Annotated[AreaService, Depends(get_area_service)]
type ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]
