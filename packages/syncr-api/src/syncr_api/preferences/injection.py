"""The dependencies the preference routes declare.

Every repository is scoped to the principal's tenant HERE, at the one point where the principal is
available and before a service exists. That is what makes the scope structural: there is no code
path that builds one of these repositories without a tenant, so no statement they compose can reach
another tenant's rows.

The principal comes from ``accounts.injection``, which carries the origin check with it. This module
adds no second way to resolve one.

Four collaborators come from elsewhere. Three owner repositories are read because a preference's
owner has to exist and be this tenant's, and because a habit's and a task's Area is what its
resolution chain climbs to. ``BacklogWideBump`` carries plan storage's version counter and the
settings row the home zone is read from, because a preference is a solve input and there is one
serialization point for anything that invalidates a running solve.
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
from syncr_api.habits.repository import HabitRepository
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.preferences.owners import PreferenceOwners
from syncr_api.preferences.repository import PreferenceRepository
from syncr_api.preferences.service import PreferenceService
from syncr_api.tasks.repository import TaskRepository
from syncr_api.user_settings.repository import SettingsRepository
from syncr_api.user_settings.solve_inputs import BacklogWideBump, TrackedWeekInputVersions


def get_preference_service(
    principal: PrincipalDep, transaction: TransactionDep
) -> PreferenceService:
    """The preference service, wired for this request and scoped to this tenant."""
    return PreferenceService(
        preferences=PreferenceRepository(transaction, principal.tenant_id),
        owners=PreferenceOwners(
            areas=AreaRepository(transaction, principal.tenant_id),
            habits=HabitRepository(transaction, principal.tenant_id),
            tasks=TaskRepository(transaction, principal.tenant_id),
        ),
        bump=BacklogWideBump(
            versions=TrackedWeekInputVersions(
                WeekInputVersionRepository(transaction, principal.tenant_id), clock=utc_now
            ),
            settings=SettingsRepository(transaction, principal.tenant_id),
        ),
        clock=utc_now,
    )


type PreferenceServiceDep = Annotated[PreferenceService, Depends(get_preference_service)]
