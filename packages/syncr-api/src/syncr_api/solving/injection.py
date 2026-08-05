"""The dependency the operation routes declare.

The repository is scoped to the principal's tenant HERE, at the one point where the principal is
available and before the service exists. That is what makes the scope structural: there is no code
path that builds one of these without a tenant, so no statement it composes can reach another
tenant's rows.

One dependency, because it is a read service and nothing more: it takes a scoped repository and no
clock, since nothing it does is timed. The WRITES are the lifecycle, which the worker and the inline
calendar sync compose by hand, so there is no second reading of what an operation needs.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

# FastAPI resolves this function's annotations at RUNTIME to build the dependency graph, and these
# two names are only reachable from an annotation, so under TYPE_CHECKING they would resolve to a
# NameError while the app is being constructed.
from syncr_api.accounts.injection import PrincipalDep, TransactionDep  # noqa: TC001
from syncr_api.solving.repository import OperationRepository
from syncr_api.solving.service import OperationService


def get_operation_service(principal: PrincipalDep, transaction: TransactionDep) -> OperationService:
    """The operation read service, wired for this request and scoped to this tenant."""
    return OperationService(OperationRepository(transaction, principal.tenant_id))


type OperationServiceDep = Annotated[OperationService, Depends(get_operation_service)]
