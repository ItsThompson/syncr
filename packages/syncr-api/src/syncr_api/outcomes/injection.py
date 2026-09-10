"""The dependencies the outcome routes declare.

Every repository is scoped to the principal's tenant HERE, at the one point where the principal is
available and before a service exists. That is what makes the scope structural: there is no code
path that builds one of these without a tenant, so no statement they compose can reach another
tenant's rows.

Four collaborators come from other feature modules, and each is deliberate rather than convenient.
The plan repository and the outcome log are plan storage's, because that package owns both tables
and a second reader of either would be a second answer to what a week holds. The Area repository is
read for the name each ledger row renders as a chip. The settings and travel-override repositories
are read for the zones, because how long a day is and which date it is are decided by where the
user is, and resolving that in a second place would let two surfaces disagree about which instants
"today" covers.

``BacklogWideBump`` is the one implementation of the open-ended version bump, floored at the week
holding today's local date. A confirmation moves the rotation cursor, which is a solve input for
weeks the user has not yet lived, and a past week's approved revision keeps the inputs it was
computed with. ``StoredChargedMisses`` restates each affected habit's stored charge in the same
transaction, from the log this module already composes, so the figure a habit response answers
with never falls behind the rows it came from.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends
from starlette.requests import Request  # noqa: TC002

# FastAPI resolves this function's annotations at RUNTIME to build the dependency graph, and these
# two names are only reachable from an annotation, so under TYPE_CHECKING they would resolve to a
# NameError while the app is being constructed.
from syncr_api.accounts.injection import ClientPrincipalDep, TransactionDep  # noqa: TC001
from syncr_api.areas.repository import AreaRepository
from syncr_api.calendars.repository import CalendarSourceRepository
from syncr_api.core.clock import utc_now
from syncr_api.habits.charged import StoredChargedMisses
from syncr_api.habits.repository import HabitRepository
from syncr_api.horizon.projection import CurrentProjectionHorizon
from syncr_api.outcomes.planned_days import PlannedDayReader
from syncr_api.outcomes.service import OutcomeService
from syncr_api.plans.habit_log import HabitOutcomeLog
from syncr_api.plans.reality import BlockOutcomeRepository
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.injection import build_solve_requests, configured_debounce
from syncr_api.user_settings.repository import SettingsRepository, TravelOverrideRepository
from syncr_api.user_settings.solve_inputs import BacklogWideBump, TrackedWeekInputVersions

if TYPE_CHECKING:
    from datetime import timedelta

    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_domain.identifiers import TenantId


def get_outcome_service(
    request: Request, principal: ClientPrincipalDep, transaction: TransactionDep
) -> OutcomeService:
    """The outcome service, wired for this request and scoped to this tenant."""
    return build_outcome_service(
        transaction, principal.tenant_id, debounce=configured_debounce(request)
    )


def build_outcome_service(
    transaction: AsyncSession, tenant_id: TenantId, *, debounce: timedelta
) -> OutcomeService:
    """The outcome service, wired for one tenant."""
    plans = PlanRepository(transaction, tenant_id)
    settings = SettingsRepository(transaction, tenant_id)
    return OutcomeService(
        plans=plans,
        days=PlannedDayReader(plans),
        outcomes=BlockOutcomeRepository(transaction, tenant_id),
        charged=StoredChargedMisses(
            habits=HabitRepository(transaction, tenant_id),
            outcomes=HabitOutcomeLog(transaction, tenant_id),
            clock=utc_now,
        ),
        areas=AreaRepository(transaction, tenant_id),
        settings=settings,
        overrides=TravelOverrideRepository(transaction, tenant_id),
        bump=BacklogWideBump(
            TrackedWeekInputVersions(
                WeekInputVersionRepository(transaction, tenant_id), clock=utc_now
            ),
            settings,
        ),
        solve_requests=build_solve_requests(
            transaction, tenant_id, clock=utc_now, debounce=debounce
        ),
        horizon=CurrentProjectionHorizon(
            CalendarSourceRepository(transaction, tenant_id), settings
        ),
        clock=utc_now,
    )


type OutcomeServiceDep = Annotated[OutcomeService, Depends(get_outcome_service)]
