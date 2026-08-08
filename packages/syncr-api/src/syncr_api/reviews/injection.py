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

**The weekly session's own composition is the week service plus six readers.** The week service is
acquired through plan storage's own builder rather than restated, which is what makes the verdict on
the session's payload and the verdict on the Week screen one computation rather than two that agree
today. The six readers are the questions the session asks that a week view does not: the backlog,
the habits, their outcome log, the arriving commitments, the retained conflicts, and the pins.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from starlette.requests import Request  # noqa: TC002 - resolved at runtime, as above

# FastAPI resolves this function's annotations at RUNTIME to build the dependency graph, and these
# three names are only reachable from an annotation, so under TYPE_CHECKING they would resolve to a
# NameError while the app is being constructed.
from syncr_api.accounts.injection import PrincipalDep, TransactionDep  # noqa: TC001
from syncr_api.anchors.repository import AnchorRepository
from syncr_api.areas.repository import AreaRepository
from syncr_api.core.clock import utc_now
from syncr_api.habits.repository import HabitRepository
from syncr_api.offplan.repository import OffPlanPeriodRepository
from syncr_api.plans.conflicts import PlanConflictRepository
from syncr_api.plans.habit_log import HabitOutcomeLog
from syncr_api.plans.injection import build_week_service
from syncr_api.plans.pins import PinRepository
from syncr_api.plans.reality import BlockOutcomeRepository
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.reviews.history import ReviewHistoryReader
from syncr_api.reviews.service import BudgetReviewService, WeeklySessionService
from syncr_api.reviews.session_sources import SessionSources
from syncr_api.solving.injection import configured_debounce
from syncr_api.tasks.repository import TaskRepository
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


def get_weekly_session_service(
    request: Request,
    principal: PrincipalDep,
    transaction: TransactionDep,
) -> WeeklySessionService:
    """The weekly session's service, wired for this request and scoped to this tenant.

    **The week service is acquired through its own builder rather than recomposed**, which is what
    makes the verdict on this payload and the verdict on the Week screen one computation. That
    builder takes fourteen collaborators; restating them here would be a second composition of the
    rule that decides whether a week can hold its commitments.

    The debounce is read from the app's own configuration because that builder takes one. Nothing on
    this path asks for a solve, so it is never consulted: the session's own mutations are the pin
    and approve routes'.

    ``PrincipalDep`` rather than ``ClientPrincipalDep``, which the composed week read this one wraps
    does take. A weekly session is a MODE of a screen, and the CLI has no command that opens one, so
    admitting a bearer token here would widen the surface a CLI credential reaches for no caller.
    ``tests/test_authorization_boundary.py`` holds the inventory that says so.
    """
    tenant_id = principal.tenant_id
    return WeeklySessionService(
        weeks=build_week_service(
            transaction, tenant_id, clock=utc_now, debounce=configured_debounce(request)
        ),
        areas=AreaRepository(transaction, tenant_id),
        settings=SettingsRepository(transaction, tenant_id),
        overrides=TravelOverrideRepository(transaction, tenant_id),
        history=ReviewHistoryReader(
            plans=PlanRepository(transaction, tenant_id),
            outcomes=BlockOutcomeRepository(transaction, tenant_id),
            periods=OffPlanPeriodRepository(transaction, tenant_id),
        ),
        sources=SessionSources(
            tasks=TaskRepository(transaction, tenant_id),
            habits=HabitRepository(transaction, tenant_id),
            outcomes=HabitOutcomeLog(transaction, tenant_id),
            anchors=AnchorRepository(transaction, tenant_id),
            conflicts=PlanConflictRepository(transaction, tenant_id),
            pins=PinRepository(transaction, tenant_id),
        ),
        clock=utc_now,
    )


type WeeklySessionServiceDep = Annotated[WeeklySessionService, Depends(get_weekly_session_service)]
