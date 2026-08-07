"""The dependency the operation routes declare, and the one factory the coordinator is built by.

The repository is scoped to the principal's tenant HERE, at the one point where the principal is
available and before the service exists. That is what makes the scope structural: there is no code
path that builds one of these without a tenant, so no statement it composes can reach another
tenant's rows.

One route dependency, because it is a read service and nothing more: it takes a scoped repository
and no clock, since nothing it does is timed. The WRITES are the lifecycle and the coordinator, and
both are composed by the caller that holds a transaction: a request-facing service, or the worker.

:func:`build_solve_coordinator` is a plain factory rather than a dependency, because five callers
compose one -- three request-facing services, the worker's runner, and its dispatch -- and only two
of them are inside a request. Stating the composition once is what keeps the debounce window a value
resolved at the composition root instead of an environment variable read five times.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Request

# FastAPI resolves this function's annotations at RUNTIME to build the dependency graph, and these
# two names are only reachable from an annotation, so under TYPE_CHECKING they would resolve to a
# NameError while the app is being constructed.
from syncr_api.accounts.injection import (  # noqa: TC001
    ClientPrincipalDep,
    PrincipalDep,
    TransactionDep,
)
from syncr_api.core.clock import utc_now
from syncr_api.solving.coordinator import SolveCoordinator
from syncr_api.solving.lifecycle import OperationLifecycle
from syncr_api.solving.queue import OperationQueue
from syncr_api.solving.repository import OperationRepository
from syncr_api.solving.service import OperationService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio.session import AsyncSession

    from syncr_api.core.clock import Clock
    from syncr_domain.identifiers import TenantId


def get_operation_service(
    principal: ClientPrincipalDep, transaction: TransactionDep
) -> OperationService:
    """The operation read service, wired for this request and scoped to this tenant."""
    return OperationService(OperationRepository(transaction, principal.tenant_id))


type OperationServiceDep = Annotated[OperationService, Depends(get_operation_service)]


def build_solve_coordinator(
    transaction: AsyncSession,
    tenant_id: TenantId,
    *,
    clock: Clock,
    debounce: timedelta,
) -> SolveCoordinator:
    """One coordinator, scoped to ``tenant_id``, holding its single-flight invariant.

    ``debounce`` is passed rather than read here, because it is deployment configuration: the api
    resolves it from ``app.state.settings`` and the worker from its own, so nothing below the
    composition root reads an environment variable.
    """
    operations = OperationRepository(transaction, tenant_id)
    return SolveCoordinator(
        operations=operations,
        queue=OperationQueue(transaction, tenant_id),
        lifecycle=OperationLifecycle(operations, clock),
        clock=clock,
        debounce=debounce,
    )


def get_solve_coordinator(
    request: Request, principal: PrincipalDep, transaction: TransactionDep
) -> SolveCoordinator:
    """The coordinator, wired for this request, with this deployment's debounce window."""
    return build_solve_coordinator(
        transaction,
        principal.tenant_id,
        clock=utc_now,
        debounce=configured_debounce(request),
    )


type SolveCoordinatorDep = Annotated[SolveCoordinator, Depends(get_solve_coordinator)]


def configured_debounce(request: Request) -> timedelta:
    """This deployment's debounce window, read from the settings the api booted with.

    One reading for every request-facing service that composes a coordinator, so three of them
    cannot debounce by three different figures.
    """
    return debounce_window(request.app.state.settings.solve_debounce_ms)


def debounce_window(milliseconds: int) -> timedelta:
    """The configured window as the value the coordinator schedules against.

    One conversion, so the api and the worker cannot read the same figure as two different lengths.
    """
    return timedelta(milliseconds=milliseconds)
