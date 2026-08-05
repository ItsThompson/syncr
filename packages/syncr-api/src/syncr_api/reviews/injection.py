"""The dependencies the pie-review routes declare.

Every repository is scoped to the principal's tenant HERE, at the one point where the principal is
available and before the service exists, so no statement they compose can reach another tenant's
rows.

Every collaborator belongs to another feature module and each is read rather than reimplemented. The
plan repository and the outcome log are plan storage's, because that package owns both tables and a
second reader of either would be a second answer to what a week held. The off-plan periods are
`offplan`'s. The Areas are the declarations the review compares behaviour against, and the settings
row and the travel overrides are what each week's real span is resolved against: a second zone
reading here would be a second answer to how long those weeks were.

``BacklogWideBump`` is the one implementation of the open-ended version bump. Applying a revision
changes the shares the solver's capacity check and the feasibility probe both read, so it bumps from
the week holding today's local date onward, and a past week's approved revision keeps the inputs it
was computed with.

**No occupancy reader appears here, and the absence is the design.** The budget report acquires one
to recompute a denominator; a review reads the plan of record's own stored figure instead, so it has
no denominator to compose. ``reviews.history`` states why.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

# FastAPI resolves this function's annotations at RUNTIME to build the dependency graph, and these
# two names are only reachable from an annotation, so under TYPE_CHECKING they would resolve to a
# NameError while the app is being constructed.
from syncr_api.accounts.injection import PrincipalDep, TransactionDep  # noqa: TC001
from syncr_api.areas.repository import AreaRepository
from syncr_api.core.clock import utc_now
from syncr_api.offplan.repository import OffPlanPeriodRepository
from syncr_api.plans.reality import BlockOutcomeRepository
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.reviews.history import ReviewHistoryReader
from syncr_api.reviews.service import BudgetReviewService
from syncr_api.user_settings.repository import SettingsRepository, TravelOverrideRepository
from syncr_api.user_settings.solve_inputs import BacklogWideBump, TrackedWeekInputVersions


def get_budget_review_service(
    principal: PrincipalDep, transaction: TransactionDep
) -> BudgetReviewService:
    """The review service, wired for this request and scoped to this tenant."""
    tenant_id = principal.tenant_id
    settings = SettingsRepository(transaction, tenant_id)
    return BudgetReviewService(
        areas=AreaRepository(transaction, tenant_id),
        settings=settings,
        overrides=TravelOverrideRepository(transaction, tenant_id),
        history=ReviewHistoryReader(
            plans=PlanRepository(transaction, tenant_id),
            outcomes=BlockOutcomeRepository(transaction, tenant_id),
            periods=OffPlanPeriodRepository(transaction, tenant_id),
        ),
        bump=BacklogWideBump(
            TrackedWeekInputVersions(
                WeekInputVersionRepository(transaction, tenant_id), clock=utc_now
            ),
            settings,
        ),
        clock=utc_now,
    )


type BudgetReviewServiceDep = Annotated[BudgetReviewService, Depends(get_budget_review_service)]
