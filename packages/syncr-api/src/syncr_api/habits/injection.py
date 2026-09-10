"""The dependencies the habit routes declare.

Every repository is scoped to the principal's tenant HERE, at the one point where the principal
is available and before a service exists. That is what makes the scope structural: there is no
code path that builds one of these repositories without a tenant, so no statement they compose
can reach another tenant's rows.

The principal comes from ``accounts.injection``, which carries the origin check with it. This
module adds no second way to resolve one.

Three collaborators come from elsewhere. The Area repository is read because a habit's Area has to
exist and be this tenant's, which is a comparison between stored rows. ``BacklogWideBump`` carries
plan storage's version counter and the settings row the home zone is read from, because a habit is
a solve input and there is one serialization point for anything that invalidates a running solve.
``HabitOutcomeLog`` is plan storage's projection of ``block_outcomes``: the cursor and the debt are
derived from the log on every read, which is why correcting a past confirmation moves both figures
with no further call.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from starlette.requests import Request  # noqa: TC002

# FastAPI resolves this function's annotations at RUNTIME to build the dependency graph, and these
# two names are only reachable from an annotation, so under TYPE_CHECKING they would resolve to a
# NameError while the app is being constructed.
from syncr_api.accounts.injection import PrincipalDep, TransactionDep  # noqa: TC001
from syncr_api.areas.repository import AreaRepository
from syncr_api.calendars.repository import CalendarSourceRepository
from syncr_api.core.clock import utc_now
from syncr_api.habits.repository import HabitRepository
from syncr_api.habits.service import HabitService
from syncr_api.horizon.projection import CurrentProjectionHorizon
from syncr_api.plans.habit_log import HabitOutcomeLog
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.injection import build_solve_requests, configured_debounce
from syncr_api.user_settings.repository import SettingsRepository
from syncr_api.user_settings.solve_inputs import BacklogWideBump, TrackedWeekInputVersions


def get_habit_service(
    request: Request, principal: PrincipalDep, transaction: TransactionDep
) -> HabitService:
    """The habit service, wired for this request and scoped to this tenant."""
    return HabitService(
        habits=HabitRepository(transaction, principal.tenant_id),
        areas=AreaRepository(transaction, principal.tenant_id),
        outcomes=HabitOutcomeLog(transaction, principal.tenant_id),
        bump=BacklogWideBump(
            versions=TrackedWeekInputVersions(
                WeekInputVersionRepository(transaction, principal.tenant_id), clock=utc_now
            ),
            settings=SettingsRepository(transaction, principal.tenant_id),
        ),
        solve_requests=build_solve_requests(
            transaction,
            principal.tenant_id,
            clock=utc_now,
            debounce=configured_debounce(request),
        ),
        horizon=CurrentProjectionHorizon(
            CalendarSourceRepository(transaction, principal.tenant_id),
            SettingsRepository(transaction, principal.tenant_id),
        ),
        clock=utc_now,
    )


type HabitServiceDep = Annotated[HabitService, Depends(get_habit_service)]
