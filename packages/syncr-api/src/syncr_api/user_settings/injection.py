"""The dependencies the settings routes declare.

Both repositories are scoped to the principal's tenant HERE, at the one point where the
principal is available and before the service exists. That is what makes the scope
structural: there is no code path that builds one of these repositories without a tenant,
so no statement they compose can reach another tenant's rows.

The principal comes from ``accounts.injection``, which carries the origin check with it.
This module adds no second way to resolve one.

This is also where the settings module meets plan storage, and the only place it does: the
service takes a counter it can bump, and which counter that is, is decided here.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from starlette.requests import Request  # noqa: TC002

# FastAPI resolves this function's annotations at RUNTIME to build the dependency graph,
# and these two names are only reachable from an annotation, so under TYPE_CHECKING they
# would resolve to a NameError while the app is being constructed.
from syncr_api.accounts.injection import PrincipalDep, TransactionDep  # noqa: TC001
from syncr_api.calendars.repository import CalendarSourceRepository
from syncr_api.core.clock import utc_now
from syncr_api.horizon.projection import CurrentProjectionHorizon
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.injection import build_solve_requests, configured_debounce
from syncr_api.user_settings.repository import SettingsRepository, TravelOverrideRepository
from syncr_api.user_settings.service import SettingsService
from syncr_api.user_settings.solve_inputs import TrackedWeekInputVersions


def get_settings_service(
    request: Request, principal: PrincipalDep, transaction: TransactionDep
) -> SettingsService:
    """The settings service, wired for this request and scoped to this tenant."""
    settings = SettingsRepository(transaction, principal.tenant_id)
    return SettingsService(
        settings=settings,
        overrides=TravelOverrideRepository(transaction, principal.tenant_id),
        versions=TrackedWeekInputVersions(
            WeekInputVersionRepository(transaction, principal.tenant_id), clock=utc_now
        ),
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


type SettingsServiceDep = Annotated[SettingsService, Depends(get_settings_service)]
