"""The dependencies the promotion routes declare.

Every repository is scoped to the principal's tenant HERE, at the one point where the principal is
available and before the service exists, so no statement they compose reaches another tenant's rows.

**The day-shape service is composed by its own module, not rebuilt here.** An accept is a template
edit, so it takes the service that performs one, with its four collaborators and its invalidation
rule. Rebuilding those here would be a second wiring of one write, and the two would drift the first
time a template edit gained a step.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

# FastAPI resolves this function's annotations at RUNTIME to build the dependency graph, and these
# two names are only reachable from an annotation, so under TYPE_CHECKING they would resolve to a
# NameError while the app is being constructed.
from syncr_api.accounts.injection import PrincipalDep, TransactionDep  # noqa: TC001
from syncr_api.core.clock import utc_now
from syncr_api.promotions.repository import PromotionDeclineRepository
from syncr_api.promotions.service import PromotionService
from syncr_api.templates.injection import get_template_service
from syncr_api.templates.repository import TemplateRepository


def get_promotion_service(principal: PrincipalDep, transaction: TransactionDep) -> PromotionService:
    """The promotion service, wired for this request and scoped to this tenant."""
    return PromotionService(
        shapes=TemplateRepository(transaction, principal.tenant_id),
        templates=get_template_service(principal, transaction),
        declines=PromotionDeclineRepository(transaction, principal.tenant_id),
        clock=utc_now,
    )


type PromotionServiceDep = Annotated[PromotionService, Depends(get_promotion_service)]
