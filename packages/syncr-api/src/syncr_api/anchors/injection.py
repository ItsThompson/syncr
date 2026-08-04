"""The dependencies the anchor and anchor-type routes declare.

Every repository is scoped to the principal's tenant HERE, at the one point where the principal
is available and before a service exists. That is what makes the scope structural: there is no
code path that builds one of these without a tenant, so no statement they compose can reach
another tenant's rows.

Four collaborators come from other feature modules, and each is deliberate rather than
convenient. The calendar-source repository names the source on an anchor's detail panel and
confirms a match rule points at a calendar that exists. The Area repository confirms that a prep
Area, a transit Area, and every forbidden Area were declared. The settings repository is read for
the home zone, because the week a rule change first affects is decided by today's LOCAL date. The
week input version counter is plan storage's, because a shadow is a solve input and there is one
serialization point for anything that invalidates a running solve.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

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
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.user_settings.repository import SettingsRepository
from syncr_api.user_settings.solve_inputs import TrackedWeekInputVersions


def get_anchor_service(principal: PrincipalDep, transaction: TransactionDep) -> AnchorService:
    """The anchor service, wired for this request and scoped to this tenant."""
    return AnchorService(
        anchors=AnchorRepository(transaction, principal.tenant_id),
        types=AnchorTypeRepository(transaction, principal.tenant_id),
        sources=CalendarSourceRepository(transaction, principal.tenant_id),
        settings=SettingsRepository(transaction, principal.tenant_id),
        versions=TrackedWeekInputVersions(
            WeekInputVersionRepository(transaction, principal.tenant_id), clock=utc_now
        ),
        clock=utc_now,
    )


def get_anchor_type_service(
    principal: PrincipalDep, transaction: TransactionDep
) -> AnchorTypeService:
    """The anchor-type service, wired for this request and scoped to this tenant."""
    anchors = AnchorRepository(transaction, principal.tenant_id)
    types = AnchorTypeRepository(transaction, principal.tenant_id)
    return AnchorTypeService(
        types=types,
        anchors=anchors,
        areas=AreaRepository(transaction, principal.tenant_id),
        sources=CalendarSourceRepository(transaction, principal.tenant_id),
        evaluator=RuleEvaluator(anchors, types),
        settings=SettingsRepository(transaction, principal.tenant_id),
        versions=TrackedWeekInputVersions(
            WeekInputVersionRepository(transaction, principal.tenant_id), clock=utc_now
        ),
        clock=utc_now,
    )


type AnchorServiceDep = Annotated[AnchorService, Depends(get_anchor_service)]
type AnchorTypeServiceDep = Annotated[AnchorTypeService, Depends(get_anchor_type_service)]
