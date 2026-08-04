"""The dependencies the routine routes declare.

The repository is scoped to the principal's tenant HERE, at the one point where the principal is
available and before a service exists. That is what makes the scope structural: there is no code
path that builds it without a tenant, so no statement it composes can reach another tenant's
rows.

The principal comes from ``accounts.injection``, which carries the origin check with it. This
module adds no second way to resolve one.

Two collaborators come from other feature modules, and both are deliberate rather than
convenient. The settings repository is read for the home zone, because the week a frame change
first affects is decided by today's LOCAL date, and resolving that in a second place would let
the two disagree. The week input version counter is plan storage's, because the frame is a solve
input and there is one serialization point for anything that invalidates a running solve.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

# FastAPI resolves this function's annotations at RUNTIME to build the dependency graph, and
# these two names are only reachable from an annotation, so under TYPE_CHECKING they would
# resolve to a NameError while the app is being constructed.
from syncr_api.accounts.injection import PrincipalDep, TransactionDep  # noqa: TC001
from syncr_api.core.clock import utc_now
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.routines.repository import RoutineRepository
from syncr_api.routines.service import RoutineService
from syncr_api.user_settings.repository import SettingsRepository
from syncr_api.user_settings.solve_inputs import TrackedWeekInputVersions


def get_routine_service(principal: PrincipalDep, transaction: TransactionDep) -> RoutineService:
    """The routine service, wired for this request and scoped to this tenant."""
    return RoutineService(
        routines=RoutineRepository(transaction, principal.tenant_id),
        settings=SettingsRepository(transaction, principal.tenant_id),
        versions=TrackedWeekInputVersions(
            WeekInputVersionRepository(transaction, principal.tenant_id), clock=utc_now
        ),
        clock=utc_now,
    )


type RoutineServiceDep = Annotated[RoutineService, Depends(get_routine_service)]
