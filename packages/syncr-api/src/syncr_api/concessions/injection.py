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

The verdict recorder is bound to the ``tradeoff`` surface and to whether this request states that
the weekly session is open, because only the caller knows the second. A tradeoff is asked for
during a weekly session more often than not, so a surface that reported false here would
under-report the metric's numerator on its most likely path.

**Three dependencies rather than two, and the split is the header.** Only the tradeoff ``POST``
computes a verdict, and the header's refusal is a 422 saying nothing was changed: on the ``GET``
that lists a week's concessions that message is meaningless and the header is one the read has no
use for. So the read resolves a service that never looks at it. The revocation computes no verdict
either, but it schedules a solve whose recorder reads the statement, so it resolves the header and
lets the operation carry the answer instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Request

# FastAPI resolves this function's annotations at RUNTIME to build the dependency graph, and these
# two names are only reachable from an annotation, so under TYPE_CHECKING they would resolve to a
# NameError while the app is being constructed.
from syncr_api.accounts.injection import PrincipalDep, TransactionDep  # noqa: TC001
from syncr_api.concessions.service import ConcessionService
from syncr_api.core.clock import utc_now
from syncr_api.core.session_mode import SessionModeDep  # noqa: TC001
from syncr_api.plans.adjustments import WeekAdjustmentRepository
from syncr_api.plans.assembler import AssemblyCaller
from syncr_api.plans.injection import build_verdict_recorder, build_week_assembler
from syncr_api.plans.surfaces import VerdictSurface
from syncr_api.plans.verdicts import ProbeCaller, WeekProbe
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.injection import build_solve_coordinator, configured_debounce
from syncr_api.user_settings.solve_inputs import TrackedWeekInputVersions

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_domain.identifiers import TenantId


def get_tradeoff_service(
    request: Request,
    principal: PrincipalDep,
    transaction: TransactionDep,
    session_mode: SessionModeDep,
) -> ConcessionService:
    """The service the tradeoff ``POST`` resolves: the one path here that computes a verdict."""
    return _service(request, principal.tenant_id, transaction, session_mode_active=session_mode)


def get_concession_service(
    request: Request, principal: PrincipalDep, transaction: TransactionDep
) -> ConcessionService:
    """The service the read resolves, which states nothing about a session.

    The list answers no mutation and schedules no solve, so the recorder this carries is never
    called and the header is never read: a read refused for a malformed mutation header would be
    answering a question nobody asked it.
    """
    return _service(request, principal.tenant_id, transaction, session_mode_active=False)


def get_revocation_service(
    request: Request,
    principal: PrincipalDep,
    transaction: TransactionDep,
    session_mode: SessionModeDep,
) -> ConcessionService:
    """The service the revocation resolves, which carries the caller's statement onward.

    A withdrawal computes no verdict of its own, but it bumps the week and asks for the solve that
    reads it, and that solve's recorder decides what an episode's first row says. So this route
    resolves the header even though nothing here records under it: the answer travels on the
    operation instead.
    """
    return _service(request, principal.tenant_id, transaction, session_mode_active=session_mode)


def _service(
    request: Request,
    tenant_id: TenantId,
    transaction: AsyncSession,
    *,
    session_mode_active: bool,
) -> ConcessionService:
    """One composition, so the two dependencies above differ only in what they were told."""
    versions = WeekInputVersionRepository(transaction, tenant_id)
    return ConcessionService(
        assembler=build_week_assembler(transaction, tenant_id, caller=AssemblyCaller.REQUEST),
        probe=WeekProbe(caller=ProbeCaller.REQUEST),
        adjustments=WeekAdjustmentRepository(transaction, tenant_id),
        verdicts=build_verdict_recorder(
            transaction,
            tenant_id,
            surface=VerdictSurface.TRADEOFF,
            session_mode_active=session_mode_active,
        ),
        coordinator=build_solve_coordinator(
            transaction,
            tenant_id,
            clock=utc_now,
            debounce=configured_debounce(request),
        ),
        current=versions,
        versions=TrackedWeekInputVersions(versions, clock=utc_now),
        clock=utc_now,
        session_mode_active=session_mode_active,
    )


type TradeoffServiceDep = Annotated[ConcessionService, Depends(get_tradeoff_service)]
type ConcessionServiceDep = Annotated[ConcessionService, Depends(get_concession_service)]
type RevocationServiceDep = Annotated[ConcessionService, Depends(get_revocation_service)]
