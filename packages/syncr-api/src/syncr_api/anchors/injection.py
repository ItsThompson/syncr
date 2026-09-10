"""The dependencies the anchor and anchor-type routes declare.

Every repository is scoped to the principal's tenant HERE, at the one point where the principal
is available and before a service exists. That is what makes the scope structural: there is no
code path that builds one of these without a tenant, so no statement they compose can reach
another tenant's rows.

Four collaborators come from other feature modules, and each is deliberate rather than
convenient. The calendar-source repository names the source on an anchor's detail panel and
confirms a match rule points at a calendar that exists. The Area repository confirms that a prep
Area, a transit Area, and every forbidden Area were declared. The week input version counter is
plan storage's, because a shadow is a solve input and there is one serialization point for
anything that invalidates a running solve. The settings repository is read for the home zone,
because the week a rule change first affects is decided by today's LOCAL date, and resolving that
in a second place would let the two disagree. The last two reach both services inside
``BacklogWideBump``, which is the one implementation of those four steps.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from starlette.requests import Request  # noqa: TC002

# FastAPI resolves these functions' annotations at RUNTIME to build the dependency graph, and
# these two names are only reachable from an annotation, so under TYPE_CHECKING they would resolve
# to a NameError while the app is being constructed.
from syncr_api.accounts.injection import PrincipalDep, TransactionDep  # noqa: TC001
from syncr_api.anchors.evaluation import RuleEvaluator
from syncr_api.anchors.repository import AnchorRepository
from syncr_api.anchors.service import AnchorService, AnchorTypeService
from syncr_api.anchors.type_repository import AnchorTypeRepository
from syncr_api.areas.repository import AreaRepository
from syncr_api.calendars.repository import CalendarSourceRepository
from syncr_api.core.clock import utc_now
from syncr_api.horizon.projection import CurrentProjectionHorizon
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.injection import build_solve_requests, configured_debounce
from syncr_api.user_settings.repository import SettingsRepository
from syncr_api.user_settings.solve_inputs import BacklogWideBump, TrackedWeekInputVersions


def _backlog_wide_bump(
    transaction: TransactionDep, principal: PrincipalDep, settings: SettingsRepository
) -> BacklogWideBump:
    """The open-ended bump both services perform, built once for this request.

    Both of them invalidate the same range for the same reason: a rule-set edit and a retype each
    change what a commitment casts, and a shadow is a solve input.
    """
    return BacklogWideBump(
        versions=TrackedWeekInputVersions(
            WeekInputVersionRepository(transaction, principal.tenant_id), clock=utc_now
        ),
        settings=settings,
    )


def get_anchor_service(
    request: Request, principal: PrincipalDep, transaction: TransactionDep
) -> AnchorService:
    """The anchor service, wired for this request and scoped to this tenant."""
    settings = SettingsRepository(transaction, principal.tenant_id)
    return AnchorService(
        anchors=AnchorRepository(transaction, principal.tenant_id),
        types=AnchorTypeRepository(transaction, principal.tenant_id),
        sources=CalendarSourceRepository(transaction, principal.tenant_id),
        bump=_backlog_wide_bump(transaction, principal, settings),
        solve_requests=build_solve_requests(
            transaction,
            principal.tenant_id,
            clock=utc_now,
            debounce=configured_debounce(request),
        ),
        horizon=CurrentProjectionHorizon(
            CalendarSourceRepository(transaction, principal.tenant_id), settings
        ),
        clock=utc_now,
    )


def get_anchor_type_service(
    request: Request, principal: PrincipalDep, transaction: TransactionDep
) -> AnchorTypeService:
    """The anchor-type service, wired for this request and scoped to this tenant."""
    anchors = AnchorRepository(transaction, principal.tenant_id)
    types = AnchorTypeRepository(transaction, principal.tenant_id)
    settings = SettingsRepository(transaction, principal.tenant_id)
    return AnchorTypeService(
        types=types,
        anchors=anchors,
        areas=AreaRepository(transaction, principal.tenant_id),
        sources=CalendarSourceRepository(transaction, principal.tenant_id),
        evaluator=RuleEvaluator(anchors, types),
        bump=_backlog_wide_bump(transaction, principal, settings),
        solve_requests=build_solve_requests(
            transaction,
            principal.tenant_id,
            clock=utc_now,
            debounce=configured_debounce(request),
        ),
        horizon=CurrentProjectionHorizon(
            CalendarSourceRepository(transaction, principal.tenant_id), settings
        ),
        clock=utc_now,
    )


type AnchorServiceDep = Annotated[AnchorService, Depends(get_anchor_service)]
type AnchorTypeServiceDep = Annotated[AnchorTypeService, Depends(get_anchor_type_service)]
