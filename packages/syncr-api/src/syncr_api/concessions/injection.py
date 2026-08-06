"""The dependencies the concession routes declare.

Every repository is scoped to the principal's tenant HERE, at the one point where the principal is
available and before a service exists. That is what makes the scope structural: there is no code
path that builds one of these without a tenant, so no statement they compose can reach another
tenant's rows.

The assembler comes from plan storage's own wiring, labelled ``request``, because a tradeoff request
assembles a week on the request path and the assembly histogram's alert is scoped to the interactive
caller. The probe carries the matching label for the same reason.

The operation lifecycle is the solving module's, and it is the only creation path for an operation:
a second one here would be a second reading of the state machine.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

# FastAPI resolves this function's annotations at RUNTIME to build the dependency graph, and these
# two names are only reachable from an annotation, so under TYPE_CHECKING they would resolve to a
# NameError while the app is being constructed.
from syncr_api.accounts.injection import PrincipalDep, TransactionDep  # noqa: TC001
from syncr_api.concessions.service import ConcessionService
from syncr_api.core.clock import utc_now
from syncr_api.plans.adjustments import WeekAdjustmentRepository
from syncr_api.plans.assembler import AssemblyCaller
from syncr_api.plans.injection import build_week_assembler
from syncr_api.plans.verdicts import ProbeCaller, WeekProbe
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.injection import build_solve_coordinator, configured_debounce
from syncr_api.user_settings.solve_inputs import TrackedWeekInputVersions


def get_concession_service(
    request: Request, principal: PrincipalDep, transaction: TransactionDep
) -> ConcessionService:
    """The concession service, wired for this request and scoped to this tenant."""
    versions = WeekInputVersionRepository(transaction, principal.tenant_id)
    return ConcessionService(
        assembler=build_week_assembler(
            transaction, principal.tenant_id, caller=AssemblyCaller.REQUEST
        ),
        probe=WeekProbe(caller=ProbeCaller.REQUEST),
        adjustments=WeekAdjustmentRepository(transaction, principal.tenant_id),
        coordinator=build_solve_coordinator(
            transaction,
            principal.tenant_id,
            clock=utc_now,
            debounce=configured_debounce(request),
        ),
        current=versions,
        versions=TrackedWeekInputVersions(versions, clock=utc_now),
        clock=utc_now,
    )


type ConcessionServiceDep = Annotated[ConcessionService, Depends(get_concession_service)]
