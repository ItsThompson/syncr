"""The dependencies the routine routes declare.

The repository is scoped to the principal's tenant HERE, at the one point where the principal is
available and before a service exists. That is what makes the scope structural: there is no code
path that builds it without a tenant, so no statement it composes can reach another tenant's
rows.

The principal comes from ``accounts.injection``, which carries the origin check with it. This
module adds no second way to resolve one.

Two collaborators come from other feature modules, and both are deliberate rather than convenient.
The bump is ``user_settings``', because the frame is a solve input with no end date and the four
steps that decide which weeks that invalidates have exactly one implementation: it reads the home
zone to resolve the floor, and a copy here would be one more service able to disagree about which
week is current. The version counter it writes through is plan storage's, because there is one
serialization point for anything that invalidates a running solve.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from starlette.requests import Request  # noqa: TC002

# FastAPI resolves this function's annotations at RUNTIME to build the dependency graph, and
# these two names are only reachable from an annotation, so under TYPE_CHECKING they would
# resolve to a NameError while the app is being constructed.
from syncr_api.accounts.injection import PrincipalDep, TransactionDep  # noqa: TC001
from syncr_api.calendars.repository import CalendarSourceRepository
from syncr_api.core.clock import utc_now
from syncr_api.horizon.projection import CurrentProjectionHorizon
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.routines.repository import RoutineRepository
from syncr_api.routines.service import RoutineService
from syncr_api.solving.injection import build_solve_requests, configured_debounce
from syncr_api.user_settings.repository import SettingsRepository
from syncr_api.user_settings.solve_inputs import BacklogWideBump, TrackedWeekInputVersions


def get_routine_service(
    request: Request, principal: PrincipalDep, transaction: TransactionDep
) -> RoutineService:
    """The routine service, wired for this request and scoped to this tenant."""
    return RoutineService(
        routines=RoutineRepository(transaction, principal.tenant_id),
        bump=BacklogWideBump(
            versions=TrackedWeekInputVersions(
                WeekInputVersionRepository(transaction, principal.tenant_id), clock=utc_now
            ),
            settings=SettingsRepository(transaction, principal.tenant_id),
        ),
        solve_requests=build_solve_requests(
            transaction,
            principal.tenant_id,
            clock=utc_now,
            debounce=configured_debounce(request),
        ),
        horizon=CurrentProjectionHorizon(
            CalendarSourceRepository(transaction, principal.tenant_id),
            SettingsRepository(transaction, principal.tenant_id),
        ),
        clock=utc_now,
    )


type RoutineServiceDep = Annotated[RoutineService, Depends(get_routine_service)]
