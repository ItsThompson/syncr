"""The dependencies the budget route declares.

Every repository is scoped to the principal's tenant HERE, at the one point where the principal
is available and before the service exists, so no statement they compose can reach another
tenant's rows.

Three of the four collaborators belong to other feature modules, and each is read rather than
reimplemented: the Areas are the declarations the report divides, and the settings row and the
travel overrides are what the week's real span is resolved against. A second zone reading here
would be a second answer to "how long was that week".

Which occupancy reader the report asks is decided here. It is
:class:`~syncr_api.budgets.occupancy.UnplannedWeek`, because nothing in this deployment can
occupy a week's time yet: there is no routine, anchor, forbidden-window, or off-plan table, and
the plan document's interior shape is not defined, so no Area's blocks can be read out of one.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

# FastAPI resolves this function's annotations at RUNTIME to build the dependency graph, and
# these two names are only reachable from an annotation, so under TYPE_CHECKING they would
# resolve to a NameError while the app is being constructed.
from syncr_api.accounts.injection import PrincipalDep, TransactionDep  # noqa: TC001
from syncr_api.areas.repository import AreaRepository
from syncr_api.budgets.occupancy import UnplannedWeek
from syncr_api.budgets.service import BudgetService
from syncr_api.user_settings.repository import SettingsRepository, TravelOverrideRepository


def get_budget_service(principal: PrincipalDep, transaction: TransactionDep) -> BudgetService:
    """The budget service, wired for this request and scoped to this tenant."""
    return BudgetService(
        areas=AreaRepository(transaction, principal.tenant_id),
        settings=SettingsRepository(transaction, principal.tenant_id),
        overrides=TravelOverrideRepository(transaction, principal.tenant_id),
        occupancy=UnplannedWeek(),
    )


type BudgetServiceDep = Annotated[BudgetService, Depends(get_budget_service)]
