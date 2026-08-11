"""The Area and Project services: authorization, the pigment deal, and the version bump.

Four rules live here rather than anywhere else.

**A pigment is dealt, never chosen.** The step a new Area takes comes from
``syncr_domain.pigments``, derived from how many Areas already hold one, so there is no cursor
to drift from the rows. The ramp has no thirteenth step, so a declaration that would need one
is refused rather than dealt a step another Area already holds.

**A share that does not fit is reported, never rejected.** Percentages summing past 100 are a
legitimate declaration. What answers for them is ``oversubscription`` on the budget report, so
nothing here compares a sum against 100.

**A budget change is a solve-input mutation.** An Area's floor and percentage are read by the
solver's capacity check and by the feasibility probe, so changing either bumps the week input
version from the current week onwards. Past weeks are not touched: an approved revision is
immutable and keeps the inputs it was computed with. A Project change bumps nothing, because a
Project declares no budget and no solve input reads one. The four steps that resolve which
weeks those are live in ``user_settings.solve_inputs.BacklogWideBump``, because every mutation
with no end date needs the same ones and five copies of them would be five services able to
disagree about which week the floor is.

**A Project is validated against its Area, not against its request.** The Area has to exist
and it has to be this tenant's, which is a comparison between two stored rows: a request
schema cannot see the Area at all, so a rule stated there would be a second, weaker statement
of this one.

``authorize_tenant`` is called on the one row a caller addresses by identifier. Every row
these methods touch was fetched through a repository scoped to the principal's own tenant, so
its ``tenant_id`` IS the principal's, and the scoped ``SELECT`` is what turns another tenant's
identifier into a 404 rather than an edit. The call is defense in depth rather than the check
producing that 404, and it sits where the caller supplies an identifier because that is the
only place an unscoped read could ever be introduced.

``require_scope`` **denies nothing over HTTP today, and that is a property of the credential
rather than of the check.** Every route reaching these methods resolves a browser session, and a
session carries every scope because the user is acting directly. The check becomes live the first
time a bearer credential reaches one of these routes, which is where its narrower grant starts
mattering, and it is written now so the authority a route needs is stated where the request is
authorized rather than retrofitted onto nine methods later.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.areas.config import AREA_RESOURCE, PROJECT_RESOURCE
from syncr_api.areas.ramp import ramp_reading
from syncr_api.areas.rules import (
    find_area,
    require_a_declared_parent,
    require_an_unused_name,
    require_room_on_the_ramp,
    unknown_area,
)
from syncr_api.core.errors import NotFound, ValidationFailed
from syncr_api.core.principal import authorize_tenant, require_scope
from syncr_api.core.scopes import Scope
from syncr_common.logging import get_logger
from syncr_common.metrics import measured
from syncr_domain.pigments import next_pigment_index

if TYPE_CHECKING:
    from syncr_api.areas.declarations import (
        AreaChange,
        AreaDeclaration,
        ProjectChange,
        ProjectDeclaration,
    )
    from syncr_api.areas.ramp import RampReading
    from syncr_api.areas.records import AreaRecord, ProjectRecord
    from syncr_api.areas.repository import AreaRepository, ProjectRepository
    from syncr_api.core.clock import Clock
    from syncr_api.core.principal import Principal
    from syncr_api.user_settings.solve_inputs import BacklogWideBump
    from syncr_domain.identifiers import AreaId, ProjectId

_log = get_logger("syncr.areas")


@dataclass(frozen=True, slots=True)
class DealtArea:
    """One Area, and the state of the ramp it was dealt from."""

    area: AreaRecord
    ramp: RampReading


@dataclass(frozen=True, slots=True)
class DeclaredAreas:
    """Every Area a tenant has declared, and the state of the ramp."""

    areas: tuple[AreaRecord, ...]
    ramp: RampReading


class AreaService:
    """Read and change one tenant's Areas, and deal each of them a pigment."""

    def __init__(
        self,
        areas: AreaRepository,
        bump: BacklogWideBump,
        clock: Clock,
    ) -> None:
        self._areas = areas
        self._bump = bump
        self._clock = clock

    @measured("areas")
    async def list_all(self, principal: Principal) -> DeclaredAreas:
        """Every Area, in the order the ramp dealt their pigments. Writes nothing."""
        require_scope(principal, Scope.PLAN_READ)
        declared = await self._areas.list_all()
        return DeclaredAreas(areas=declared, ramp=ramp_reading(declared))

    @measured("areas")
    async def read(self, principal: Principal, area_id: AreaId) -> AreaRecord:
        """One Area of this tenant's, or a 404 that discloses nothing about another's."""
        require_scope(principal, Scope.PLAN_READ)
        found = await self._areas.find(area_id)
        if found is None:
            raise NotFound(f"No {AREA_RESOURCE} matches that identifier.")
        authorize_tenant(principal, found.tenant_id, resource=AREA_RESOURCE)
        return found

    @measured("areas")
    async def create(self, principal: Principal, declaration: AreaDeclaration) -> DealtArea:
        """Declare an Area, dealing it the next step of the ramp.

        The Areas are locked first, so a concurrent declaration cannot change a row this one
        has read. That does not serialize the count: a declaration blocked on those locks is
        answered from the snapshot its own statement took, which predates the blocker's commit,
        so two of them can pass a bound stated over the count and be dealt one step.

        A tenant whose Areas hold every step is refused, before the name is considered: no name
        is available to such a caller, so a refusal naming the name would send them to change
        the one thing that cannot help.
        """
        require_scope(principal, Scope.ADMIN)
        now = self._clock()
        existing = await self._areas.lock_all()
        require_room_on_the_ramp(existing)
        require_an_unused_name(declaration.name, existing)
        if declaration.parent_id is not None:
            require_a_declared_parent(declaration.parent_id, existing)

        created = await self._areas.create(
            parent_id=declaration.parent_id,
            name=declaration.name,
            pigment_index=next_pigment_index(len(existing)),
            budget_percent=declaration.budget_percent,
            floor_hours=declaration.floor_hours,
            created_at=now,
        )
        # The Area's NAME is deliberately absent from this line. It is user-authored content,
        # and an Area named "Job search" discloses as much as a block title does.
        _log.info(
            "areas.area.declared",
            tenant_id=str(principal.tenant_id),
            area_id=str(created.id),
            pigment_index=created.pigment_index,
        )
        await self._bump.from_the_week_holding(now)
        return DealtArea(area=created, ramp=ramp_reading((*existing, created)))

    @measured("areas")
    async def update(self, principal: Principal, area_id: AreaId, change: AreaChange) -> DealtArea:
        """Change a name, a pigment step, a floor, or a share, and bump if a budget moved.

        The Areas are locked for the same reason creation locks them: the name check and the
        ramp reading are both stated over the whole set, so a concurrent declaration must not
        land between reading it and writing.
        """
        require_scope(principal, Scope.ADMIN)
        now = self._clock()
        existing = await self._areas.lock_all()
        current = find_area(area_id, existing)
        if current is None:
            raise NotFound(f"No {AREA_RESOURCE} matches that identifier.")
        authorize_tenant(principal, current.tenant_id, resource=AREA_RESOURCE)

        merged = change.applied_to(current)
        require_an_unused_name(merged.name, existing, apart_from=area_id)
        await self._areas.write(
            area_id,
            name=merged.name,
            pigment_index=merged.pigment_index,
            budget_percent=merged.budget_percent,
            floor_hours=merged.floor_hours,
        )
        _log.info(
            "areas.area.changed",
            tenant_id=str(principal.tenant_id),
            area_id=str(area_id),
            budget_changed=change.changes_a_solve_input(),
        )
        if change.changes_a_solve_input():
            await self._bump.from_the_week_holding(now)
        return DealtArea(
            area=merged,
            ramp=ramp_reading(tuple(merged if row.id == area_id else row for row in existing)),
        )


class ProjectService:
    """Read and change one tenant's Projects, each inside exactly one Area."""

    def __init__(self, projects: ProjectRepository, areas: AreaRepository, clock: Clock) -> None:
        self._projects = projects
        self._areas = areas
        self._clock = clock

    @measured("areas")
    async def list_all(
        self, principal: Principal, *, area_id: AreaId | None = None
    ) -> tuple[ProjectRecord, ...]:
        """Every Project, or the ones inside one Area. Writes nothing."""
        require_scope(principal, Scope.PLAN_READ)
        return await self._projects.list_all(area_id=area_id)

    @measured("areas")
    async def read(self, principal: Principal, project_id: ProjectId) -> ProjectRecord:
        """One Project of this tenant's."""
        require_scope(principal, Scope.PLAN_READ)
        return await self._require_project(principal, project_id)

    @measured("areas")
    async def create(self, principal: Principal, declaration: ProjectDeclaration) -> ProjectRecord:
        """Declare a Project inside an Area that already exists."""
        require_scope(principal, Scope.ADMIN)
        if await self._areas.find(declaration.area_id) is None:
            raise ValidationFailed(
                f"No {AREA_RESOURCE} matches that identifier, so a project cannot be declared "
                "inside it. Nothing was changed. Declare the Area first: a project inherits "
                "its Area's allocation rather than carrying a budget of its own.",
                errors=unknown_area("areaId"),
            )
        created = await self._projects.create(
            area_id=declaration.area_id,
            name=declaration.name,
            deadline=declaration.deadline,
            status=declaration.status,
            created_at=self._clock(),
        )
        _log.info(
            "areas.project.declared",
            tenant_id=str(principal.tenant_id),
            project_id=str(created.id),
            area_id=str(created.area_id),
        )
        return created

    @measured("areas")
    async def update(
        self, principal: Principal, project_id: ProjectId, change: ProjectChange
    ) -> ProjectRecord:
        """Change a name, a deadline, or a status. Completing a Project is a status change.

        The Area is untouched, so the hours already attributed to it stay attributed to it:
        completing a Project is a statement about the Project, not a re-attribution of what
        was spent on it.
        """
        require_scope(principal, Scope.ADMIN)
        merged = change.applied_to(await self._require_project(principal, project_id))
        await self._projects.write(
            project_id, name=merged.name, deadline=merged.deadline, status=merged.status
        )
        _log.info(
            "areas.project.changed",
            tenant_id=str(principal.tenant_id),
            project_id=str(project_id),
            status=merged.status.value,
        )
        return merged

    async def _require_project(self, principal: Principal, project_id: ProjectId) -> ProjectRecord:
        found = await self._projects.find(project_id)
        if found is None:
            raise NotFound(f"No {PROJECT_RESOURCE} matches that identifier.")
        authorize_tenant(principal, found.tenant_id, resource=PROJECT_RESOURCE)
        return found
