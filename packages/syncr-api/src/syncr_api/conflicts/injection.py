"""The dependencies the conflict routes declare.

Every repository is scoped to the principal's tenant HERE, at the one point where the principal is
available and before a service exists. That is what makes the scope structural: there is no code
path that builds one of these without a tenant, so no statement they compose can reach another
tenant's rows.

Three collaborators come from other feature modules, and each is deliberate rather than convenient.
The conflict record and the plan repository are plan storage's, because that package owns both
tables and a second reader of either would be a second answer to what a week holds. The anchor
service is the anchor package's, because retyping persists on a commitment's series and invalidates
every week it governs, and a second implementation of that would be a second answer to what a
retype means. The operation lifecycle is the solving module's, and it is the only creation path for
an operation.

``StoredPinRelease`` is the pin feature's answer to the release this path declares. The seam stays a
protocol because the lifecycle question it settles is the pin's: what a release does to the row, and
what still teaches the learning layer afterwards, are decided where pins are written.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

# FastAPI resolves this function's annotations at RUNTIME to build the dependency graph, and these
# two names are only reachable from an annotation, so under TYPE_CHECKING they would resolve to a
# NameError while the app is being constructed.
from syncr_api.accounts.injection import PrincipalDep, TransactionDep  # noqa: TC001
from syncr_api.anchors.injection import get_anchor_service
from syncr_api.conflicts.service import ConflictService
from syncr_api.core.clock import utc_now
from syncr_api.pins.release import StoredPinRelease
from syncr_api.plans.conflicts import PlanConflictRepository
from syncr_api.plans.pins import PinRepository
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.injection import build_solve_coordinator, configured_debounce


def get_conflict_service(
    request: Request, principal: PrincipalDep, transaction: TransactionDep
) -> ConflictService:
    """The conflict service, wired for this request and scoped to this tenant."""
    return ConflictService(
        conflicts=PlanConflictRepository(transaction, principal.tenant_id),
        revisions=PlanRepository(transaction, principal.tenant_id),
        versions=WeekInputVersionRepository(transaction, principal.tenant_id),
        coordinator=build_solve_coordinator(
            transaction,
            principal.tenant_id,
            clock=utc_now,
            debounce=configured_debounce(request),
        ),
        anchors=get_anchor_service(principal, transaction),
        pins=StoredPinRelease(PinRepository(transaction, principal.tenant_id)),
        clock=utc_now,
    )


type ConflictServiceDep = Annotated[ConflictService, Depends(get_conflict_service)]
