"""The dependencies the backlog routes declare.

Every repository is scoped to the principal's tenant HERE, at the one point where the principal is
available and before a service exists. That is what makes the scope structural: there is no code
path that builds one of these repositories without a tenant, so no statement they compose can
reach another tenant's rows.

The principal comes from ``accounts.injection``, which carries the origin check with it. This
module adds no second way to resolve one.

Three collaborators come from other feature modules. The Area and Project repositories are read
because a task's Area has to exist and a named Project's Area has to be the task's Area, and both
are comparisons between stored rows. ``BacklogWideBump`` carries plan storage's version counter
and the settings row the home zone is read from, because a task is a solve input and there is one
serialization point for anything that invalidates a running solve.

A fourth is plan storage's too: the at-risk column is the week verdict's ``deadline_capacity``
shortfalls, so the backlog reads the SAME verdict the Week screen serves, through the same builder.
Composing that rule here instead would be a second answer to whether a week can hold its
commitments.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

# FastAPI resolves this function's annotations at RUNTIME to build the dependency graph, and these
# two names are only reachable from an annotation, so under TYPE_CHECKING they would resolve to a
# NameError while the app is being constructed.
from syncr_api.accounts.injection import ClientPrincipalDep, TransactionDep  # noqa: TC001
from syncr_api.areas.repository import AreaRepository, ProjectRepository
from syncr_api.core.clock import utc_now
from syncr_api.plans.injection import build_current_week_verdict
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.tasks.repository import TaskRepository
from syncr_api.tasks.service import TaskService
from syncr_api.user_settings.repository import SettingsRepository
from syncr_api.user_settings.solve_inputs import BacklogWideBump, TrackedWeekInputVersions


def get_task_service(principal: ClientPrincipalDep, transaction: TransactionDep) -> TaskService:
    """The Task service, wired for this request and scoped to this tenant."""
    return TaskService(
        tasks=TaskRepository(transaction, principal.tenant_id),
        areas=AreaRepository(transaction, principal.tenant_id),
        projects=ProjectRepository(transaction, principal.tenant_id),
        bump=BacklogWideBump(
            versions=TrackedWeekInputVersions(
                WeekInputVersionRepository(transaction, principal.tenant_id), clock=utc_now
            ),
            settings=SettingsRepository(transaction, principal.tenant_id),
        ),
        verdict=build_current_week_verdict(transaction, principal.tenant_id, clock=utc_now),
        clock=utc_now,
    )


type TaskServiceDep = Annotated[TaskService, Depends(get_task_service)]
