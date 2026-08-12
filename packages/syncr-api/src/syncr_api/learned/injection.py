"""The dependencies the learning routes declare.

Every repository is scoped to the principal's tenant HERE, at the one point where the principal is
available and before the service exists, so no statement they compose reaches another tenant's rows.

Three collaborators come from other feature modules and each is read rather than reimplemented. The
week input version counter is plan storage's, because that table is the single serialization point
for every mutation a running solve has to see. The settings row is ``user_settings``', because which
week holds today's local date is one question with one answer. And the solve coordinator is the
solving module's, because it is the only creation path for a ``solve`` operation.

The Areas are read through their own repository for the same reason: a maturity row names the Area
it is about by identifier, and what an Area is CALLED has one owner.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

# FastAPI resolves this function's annotations at RUNTIME to build the dependency graph, and these
# two names are only reachable from an annotation, so under TYPE_CHECKING they would resolve to a
# NameError while the app is being constructed.
from syncr_api.accounts.injection import PrincipalDep, TransactionDep  # noqa: TC001
from syncr_api.areas.repository import AreaRepository
from syncr_api.core.clock import utc_now
from syncr_api.learned.activation import FutureWeeksResolved, WeightSetActivation
from syncr_api.learned.repository import WeightSetRepository
from syncr_api.learned.service import LearnedService
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.injection import build_solve_coordinator, configured_debounce
from syncr_api.user_settings.repository import SettingsRepository


def get_learned_service(
    request: Request, principal: PrincipalDep, transaction: TransactionDep
) -> LearnedService:
    """The learning service, wired for this request and scoped to this tenant."""
    tenant_id = principal.tenant_id
    return LearnedService(
        weights=WeightSetRepository(transaction, tenant_id),
        areas=AreaRepository(transaction, tenant_id),
        activation=WeightSetActivation(transaction, tenant_id),
        resolver=FutureWeeksResolved(
            versions=WeekInputVersionRepository(transaction, tenant_id),
            settings=SettingsRepository(transaction, tenant_id),
            coordinator=build_solve_coordinator(
                transaction,
                tenant_id,
                clock=utc_now,
                debounce=configured_debounce(request),
            ),
        ),
        clock=utc_now,
    )


type LearnedServiceDep = Annotated[LearnedService, Depends(get_learned_service)]
