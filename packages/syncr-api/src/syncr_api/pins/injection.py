"""The dependency the pin routes declare, and the pin release the conflict path reaches through.

Every repository is scoped to the principal's tenant HERE, at the one point where the principal is
available and before a service exists. That is what makes the scope structural: there is no code
path that builds one of these without a tenant, so no statement they compose can reach another
tenant's rows.

Four collaborators come from the plan package, and each is deliberate rather than convenient. The
assembler and the probe are the plan package's because a pin's verdict has to be computed over the
same assembly a solve of that week reads, and a second composition of either would be a second
answer to what the week holds. The revision and proposal repositories are the plan package's because
that package owns both tables. The coordinator is the solving module's, and it is the only path that
creates a solve.

``caller`` is bound to the interactive label on both the assembler and the probe, which is what
makes ``syncr_assembly_duration_seconds{caller="request"}`` and
``syncr_probe_duration_seconds{caller= "request"}`` the pair a regression in either is attributable
through. The assembly is the dominant cost by an order of magnitude and the two are watched together
for exactly that reason.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Request

# FastAPI resolves this function's annotations at RUNTIME to build the dependency graph, and these
# two names are only reachable from an annotation, so under TYPE_CHECKING they would resolve to a
# NameError while the app is being constructed.
from syncr_api.accounts.injection import PrincipalDep, TransactionDep  # noqa: TC001
from syncr_api.core.clock import utc_now
from syncr_api.learned.repository import WeightSetRepository
from syncr_api.pins.service import PinService
from syncr_api.plans.assembler import AssemblyCaller
from syncr_api.plans.edits import EditEventRepository
from syncr_api.plans.injection import DEFAULT_DEBOUNCE, build_week_assembler
from syncr_api.plans.pins import PinRepository
from syncr_api.plans.proposals import PendingProposalRepository
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.verdicts import ProbeCaller, WeekProbe
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.injection import build_solve_coordinator, configured_debounce

if TYPE_CHECKING:
    from datetime import timedelta

    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_api.core.clock import Clock
    from syncr_domain.identifiers import TenantId


def get_pin_service(
    request: Request, principal: PrincipalDep, transaction: TransactionDep
) -> PinService:
    """The pin service, wired for this request and scoped to this tenant."""
    return build_pin_service(
        transaction,
        principal.tenant_id,
        clock=utc_now,
        debounce=configured_debounce(request),
    )


def build_pin_service(
    transaction: AsyncSession,
    tenant_id: TenantId,
    *,
    clock: Clock,
    debounce: timedelta = DEFAULT_DEBOUNCE,
) -> PinService:
    """One pin service, scoped to ``tenant_id``, reading time from ``clock``.

    Split from the dependency above for the reason the week service's builder is: the composition is
    ten collaborators, and a caller that wants one against a stated instant should not have to
    restate all ten. ``debounce`` defaults to the documented value rather than being required, and
    the dependency above passes what this deployment configured, so a caller that states nothing
    gets the default the environment variable also defaults to.
    """
    return PinService(
        assembler=build_week_assembler(transaction, tenant_id, caller=AssemblyCaller.REQUEST),
        probe=WeekProbe(caller=ProbeCaller.REQUEST),
        revisions=PlanRepository(transaction, tenant_id),
        proposals=PendingProposalRepository(transaction, tenant_id),
        pins=PinRepository(transaction, tenant_id),
        edits=EditEventRepository(transaction, tenant_id),
        versions=WeekInputVersionRepository(transaction, tenant_id),
        weights=WeightSetRepository(transaction, tenant_id),
        coordinator=build_solve_coordinator(transaction, tenant_id, clock=clock, debounce=debounce),
        clock=clock,
    )


type PinServiceDep = Annotated[PinService, Depends(get_pin_service)]
