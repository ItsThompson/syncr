"""The dependencies the budget route declares.

Every repository is scoped to the principal's tenant HERE, at the one point where the principal
is available and before the service exists, so no statement they compose can reach another
tenant's rows.

Three of the four collaborators belong to other feature modules, and each is read rather than
reimplemented: the Areas are the declarations the report divides, and the settings row and the
travel overrides are what the week's real span is resolved against. A second zone reading here
would be a second answer to "how long was that week".

Which occupancy reader the report asks is decided here. It is
:class:`~syncr_api.offplan.occupancy.OffPlanOccupancy`, because off-plan periods are the one kind
of span this deployment can store: it fills the denominator's fourth subtrahend and leaves the
other four sets empty, which is still the honest reading for them. There is no routine, anchor,
or forbidden-window table, and the plan document's interior shape is not defined, so no Area's
blocks can be read out of one. Whoever brings one of those online replaces this reader with one
that composes theirs with off-plan's rather than editing off-plan's to know about theirs.

**Two endpoints are composed from the factory below**, and that is deliberate: the week view's
``readings`` are this service's own figures, so the summary strip and the pie review divide one
denominator computed from one occupancy read. Replacing the reader therefore reaches both at once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends

# FastAPI resolves this function's annotations at RUNTIME to build the dependency graph, and
# these two names are only reachable from an annotation, so under TYPE_CHECKING they would
# resolve to a NameError while the app is being constructed.
from syncr_api.accounts.injection import PrincipalDep, TransactionDep  # noqa: TC001
from syncr_api.areas.repository import AreaRepository
from syncr_api.budgets.service import BudgetService
from syncr_api.offplan.occupancy import OffPlanOccupancy
from syncr_api.offplan.repository import OffPlanPeriodRepository
from syncr_api.user_settings.repository import SettingsRepository, TravelOverrideRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_domain.identifiers import TenantId


def get_budget_service(principal: PrincipalDep, transaction: TransactionDep) -> BudgetService:
    """The budget service, wired for this request and scoped to this tenant."""
    return build_budget_service(transaction, principal.tenant_id)


def build_budget_service(transaction: AsyncSession, tenant_id: TenantId) -> BudgetService:
    """One budget service, scoped to ``tenant_id``. The one place its four seams are decided.

    Split from the dependency above because a second caller composes one: the week view's readings
    are this service's own figures, so a strip figure cannot disagree with the same figure in the
    review. A copy of the list below is exactly how the two would come to read different occupancy.
    """
    return BudgetService(
        areas=AreaRepository(transaction, tenant_id),
        settings=SettingsRepository(transaction, tenant_id),
        overrides=TravelOverrideRepository(transaction, tenant_id),
        occupancy=OffPlanOccupancy(OffPlanPeriodRepository(transaction, tenant_id)),
    )


type BudgetServiceDep = Annotated[BudgetService, Depends(get_budget_service)]
