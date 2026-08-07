"""The dependency the approve route declares.

Every repository is scoped to the principal's tenant HERE, at the one point where the principal is
available and before a service exists. That is what makes the scope structural: there is no code
path that builds one of these without a tenant, so no statement they compose can reach another
tenant's rows.

Five collaborators, and each is another package's because that package owns the table: the plan of
record, the pending slot, the concessions, and the version counter are the plan package's, and the
operation lifecycle is the solving module's, which is the only place an operation is created.

There is no coordinator here, and its absence is the trigger table's row rather than an omission:
approval bumps the version and asks for no solve.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

# Runtime, not type-only: FastAPI resolves this module's annotations while the dependency graph is
# built, and `build_approval_service` is called from tests with a session of their own.
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

# FastAPI resolves this function's annotations at RUNTIME to build the dependency graph, and these
# two names are only reachable from an annotation, so under TYPE_CHECKING they would resolve to a
# NameError while the app is being constructed.
from syncr_api.accounts.injection import PrincipalDep, TransactionDep  # noqa: TC001
from syncr_api.approvals.service import ApprovalService
from syncr_api.core.clock import Clock, utc_now
from syncr_api.plans.adjustments import WeekAdjustmentRepository
from syncr_api.plans.proposals import PendingProposalRepository
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.lifecycle import OperationLifecycle
from syncr_api.solving.repository import OperationRepository
from syncr_domain.identifiers import TenantId  # noqa: TC001 - as above


def get_approval_service(principal: PrincipalDep, transaction: TransactionDep) -> ApprovalService:
    """The approval service, wired for this request and scoped to this tenant."""
    return build_approval_service(transaction, principal.tenant_id, clock=utc_now)


def build_approval_service(
    transaction: AsyncSession, tenant_id: TenantId, *, clock: Clock
) -> ApprovalService:
    """One approval service, scoped to ``tenant_id``, reading time from ``clock``.

    Split from the dependency above for the reason the week service's builder is: a caller that
    wants one against a stated instant should not have to restate the composition.
    """
    return ApprovalService(
        revisions=PlanRepository(transaction, tenant_id),
        proposals=PendingProposalRepository(transaction, tenant_id),
        adjustments=WeekAdjustmentRepository(transaction, tenant_id),
        versions=WeekInputVersionRepository(transaction, tenant_id),
        operations=OperationLifecycle(OperationRepository(transaction, tenant_id), clock),
        clock=clock,
    )


type ApprovalServiceDep = Annotated[ApprovalService, Depends(get_approval_service)]
