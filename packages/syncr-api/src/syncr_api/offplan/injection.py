"""The dependencies the off-plan routes declare.

Every repository is scoped to the principal's tenant HERE, at the one point where the principal
is available and before a service exists. That is what makes the scope structural: there is no
code path that builds one of these repositories without a tenant, so no statement they compose
can reach another tenant's rows.

Two collaborators come from other feature modules, and both are deliberate rather than
convenient. The settings repository is read for the home zone, because which ISO weeks a span
touches is decided by LOCAL dates, and resolving that in a second place would let the two
disagree; it is also the row a declaration serializes on. The week input version counter is plan
storage's, because an off-plan span is a solve input and there is one serialization point for
anything that invalidates a running solve.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

# FastAPI resolves this function's annotations at RUNTIME to build the dependency graph, and
# these two names are only reachable from an annotation, so under TYPE_CHECKING they would
# resolve to a NameError while the app is being constructed.
from syncr_api.accounts.injection import PrincipalDep, TransactionDep  # noqa: TC001
from syncr_api.core.clock import utc_now
from syncr_api.offplan.repository import OffPlanPeriodRepository
from syncr_api.offplan.service import OffPlanService
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.user_settings.repository import SettingsRepository
from syncr_api.user_settings.solve_inputs import TrackedWeekInputVersions


def get_off_plan_service(principal: PrincipalDep, transaction: TransactionDep) -> OffPlanService:
    """The off-plan service, wired for this request and scoped to this tenant."""
    return OffPlanService(
        periods=OffPlanPeriodRepository(transaction, principal.tenant_id),
        settings=SettingsRepository(transaction, principal.tenant_id),
        versions=TrackedWeekInputVersions(
            WeekInputVersionRepository(transaction, principal.tenant_id), clock=utc_now
        ),
        clock=utc_now,
    )


type OffPlanServiceDep = Annotated[OffPlanService, Depends(get_off_plan_service)]
