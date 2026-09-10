"""The dependencies the promotion routes declare.

Every repository is scoped to the principal's tenant HERE, at the one point where the principal is
available and before the service exists, so no statement they compose reaches another tenant's rows.

**The day-shape service is composed by its own module, not rebuilt here.** An accept is a template
edit, so it takes the service that performs one, with its four collaborators and its invalidation
rule. Rebuilding those here would be a second wiring of one write, and the two would drift the first
time a template edit gained a step.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Request

# FastAPI resolves this function's annotations at RUNTIME to build the dependency graph, and these
# two names are only reachable from an annotation, so under TYPE_CHECKING they would resolve to a
# NameError while the app is being constructed.
from syncr_api.accounts.injection import PrincipalDep, TransactionDep  # noqa: TC001
from syncr_api.core.clock import utc_now
from syncr_api.promotions.repository import PromotionDeclineRepository
from syncr_api.promotions.service import PromotionService
from syncr_api.solving.injection import configured_debounce
from syncr_api.templates.injection import build_template_service
from syncr_api.templates.repository import TemplateRepository

if TYPE_CHECKING:
    from datetime import timedelta

    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_domain.identifiers import TenantId


def get_promotion_service(
    request: Request, principal: PrincipalDep, transaction: TransactionDep
) -> PromotionService:
    """The promotion service, wired for this request and scoped to this tenant."""
    return build_promotion_service(
        transaction,
        principal.tenant_id,
        debounce=configured_debounce(request),
    )


def build_promotion_service(
    transaction: AsyncSession, tenant_id: TenantId, *, debounce: timedelta
) -> PromotionService:
    """The promotion service, wired for one tenant."""
    return PromotionService(
        shapes=TemplateRepository(transaction, tenant_id),
        templates=build_template_service(transaction, tenant_id, debounce=debounce),
        declines=PromotionDeclineRepository(transaction, tenant_id),
        clock=utc_now,
    )


type PromotionServiceDep = Annotated[PromotionService, Depends(get_promotion_service)]
