"""The routine service: authorization, the refused span, and the version bump.

Three rules live here rather than anywhere else.

**Every mutation bumps the week input version.** The frame is the denominator: routine spans are
subtracted from total time before any Area gets a share, so declaring, changing, or removing one
changes how much discretionary time exists. The bump runs from the current week onwards. Past
weeks are not touched: an approved revision is immutable and keeps the inputs it was computed
with. The four steps that resolve which weeks those are live in
``user_settings.solve_inputs.BacklogWideBump``, because every mutation with no end date needs the
same ones, and the step that can disagree is the floor: it is the week holding today's date in
the HOME zone, so a second copy resolving it anywhere else would move the floor by up to a day
around a date change and one mutation would silently leave a running solve valid.

A title-only change bumps as well, and that is deliberate. It is a wider rule than the Area
service's, which leaves a rename alone, and the reason is that the frame's materialized blocks
carry the routine's title into the plan document a solve produces, so a stale title would
survive in an approved week. Invalidating one week's inputs costs a re-solve; a plan naming a
routine the user has renamed is a plan that disagrees with the entity it came from.

**The span's invariants are the domain's, and this layer only states them.** ``RoutineSpan``
refuses a routine with no duration, a floor outside its target, and a band wider than half a
day. Both write paths build the span the request WOULD produce and let that refusal become a
422, so a create and a patch cannot disagree about what is legal.

**A routine carries no Area, so nothing here takes one.** There is no parameter, no column, and
no wire field: the frame defines how much time exists rather than competing for it.

``authorize_tenant`` is called on the one row a caller addresses by identifier. Every row these
methods touch was fetched through a repository scoped to the principal's own tenant, so its
``tenant_id`` IS the principal's, and the scoped ``SELECT`` is what turns another tenant's
identifier into a 404 rather than an edit. The call is defense in depth rather than the check
producing that 404.

Mutations require ``admin`` rather than ``plan:write``. A routine is part of the plan's
definition, alongside budgets, templates, and settings, rather than something a caller does to a
week that already exists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.core.errors import NotFound
from syncr_api.core.principal import authorize_tenant, require_scope
from syncr_api.core.scopes import Scope
from syncr_api.routines.config import ROUTINE_RESOURCE
from syncr_api.routines.rules import stated_rejection
from syncr_common.logging import get_logger
from syncr_common.metrics import measured

if TYPE_CHECKING:
    from syncr_api.core.clock import Clock
    from syncr_api.core.principal import Principal
    from syncr_api.routines.declarations import RoutineChange, RoutineDeclaration
    from syncr_api.routines.records import RoutineId, RoutineRecord
    from syncr_api.routines.repository import RoutineRepository
    from syncr_api.user_settings.solve_inputs import BacklogWideBump

_log = get_logger("syncr.routines")


class RoutineService:
    """Read and change one tenant's routines: the circadian frame the day is built around."""

    def __init__(
        self,
        routines: RoutineRepository,
        bump: BacklogWideBump,
        clock: Clock,
    ) -> None:
        self._routines = routines
        self._bump = bump
        self._clock = clock

    @measured("routines")
    async def list_all(self, principal: Principal) -> tuple[RoutineRecord, ...]:
        """Every routine, in the order the day runs. Writes nothing."""
        require_scope(principal, Scope.PLAN_READ)
        return await self._routines.list_all()

    @measured("routines")
    async def read(self, principal: Principal, routine_id: RoutineId) -> RoutineRecord:
        """One routine of this tenant's, or a 404 that discloses nothing about another's."""
        require_scope(principal, Scope.PLAN_READ)
        return await self._require_routine(principal, routine_id)

    @measured("routines")
    async def create(self, principal: Principal, declaration: RoutineDeclaration) -> RoutineRecord:
        """Declare a routine, or state why its span was refused.

        A declaration with no floor gets one equal to its target, which makes it inelastic. The
        span is built before anything is written, so a refused routine is not stored.
        """
        require_scope(principal, Scope.ADMIN)
        now = self._clock()
        with stated_rejection():
            span = declaration.span()

        created = await self._routines.create(
            title=declaration.title,
            target_time=span.target_time,
            duration_minutes=span.duration_minutes,
            min_duration_minutes=span.min_duration_minutes,
            flex_band_minutes=span.flex_band_minutes,
            created_at=now,
        )
        # The routine's TITLE is deliberately absent from this line. It is user-authored content,
        # and the redactor would eat it under that name anyway.
        _log.info(
            "routines.routine.declared",
            tenant_id=str(principal.tenant_id),
            routine_id=str(created.id),
            elastic=span.is_elastic,
        )
        await self._bump.from_the_week_holding(now)
        return created

    @measured("routines")
    async def update(
        self, principal: Principal, routine_id: RoutineId, change: RoutineChange
    ) -> RoutineRecord:
        """Change a title, a target time, a duration, the floor, or the band.

        This is where the sleep floor is set. The change is merged onto the stored row and the
        merged span is validated as a whole, so a request that lowers a target below the stored
        floor is refused for the same reason one that raises the floor above the target is.
        """
        require_scope(principal, Scope.ADMIN)
        now = self._clock()
        current = await self._require_routine(principal, routine_id)
        merged = change.applied_to(current)
        with stated_rejection():
            span = merged.as_span()

        await self._routines.write(
            routine_id,
            title=merged.title,
            target_time=span.target_time,
            duration_minutes=span.duration_minutes,
            min_duration_minutes=span.min_duration_minutes,
            flex_band_minutes=span.flex_band_minutes,
        )
        _log.info(
            "routines.routine.changed",
            tenant_id=str(principal.tenant_id),
            routine_id=str(routine_id),
            elastic=span.is_elastic,
        )
        await self._bump.from_the_week_holding(now)
        return merged

    @measured("routines")
    async def remove(self, principal: Principal, routine_id: RoutineId) -> None:
        """Remove a routine, giving its span back to discretionary time."""
        require_scope(principal, Scope.ADMIN)
        now = self._clock()
        await self._require_routine(principal, routine_id)

        await self._routines.remove(routine_id)
        _log.info(
            "routines.routine.removed",
            tenant_id=str(principal.tenant_id),
            routine_id=str(routine_id),
        )
        await self._bump.from_the_week_holding(now)

    async def _require_routine(self, principal: Principal, routine_id: RoutineId) -> RoutineRecord:
        found = await self._routines.find(routine_id)
        if found is None:
            raise NotFound(f"No {ROUTINE_RESOURCE} matches that identifier.")
        authorize_tenant(principal, found.tenant_id, resource=ROUTINE_RESOURCE)
        return found
