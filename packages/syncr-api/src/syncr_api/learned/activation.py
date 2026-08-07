"""Activating a weight-set version, and the re-solve of future weeks that follows it.

Kept out of :mod:`syncr_api.learned.repository`, which states that flipping ``active`` is a
user-facing act with a re-solve behind it. This is that act.

## Three writes and one loop, in this order

The flip is two statements in one transaction: clear the flag, then set it on the named version.
Both are built through the scoped base, so the tenant predicate is what the base applies rather than
something each statement remembers. Postgres's partial unique index over ``(tenant_id) WHERE
active`` refuses two active rows, so the clear has to land first; the index is what makes "exactly
one active per tenant" true rather than the order of these two lines.

Then every FUTURE week the tenant has planned is invalidated and re-solved. Future only, because a
past week's approved revision is immutable: re-deriving one would change history rather than the
plan. The floor is the week holding today's LOCAL date in the home zone, the same floor every
open-ended mutation in this application takes.

**A week with no version row is not re-solved**, and that is not an omission. Such a week has no
plan and no running solve to invalidate, and the horizon maintainer is what brings a week into
range: a version row created here would be this module deciding which weeks a tenant plans.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.core.repository import TenantScopedRepository
from syncr_api.learned.models import WeightSet
from syncr_api.user_settings.solve_inputs import weeks_from
from syncr_api.user_settings.zone_reading import local_date
from syncr_common.logging import get_logger

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_api.plans.versions import WeekInputVersionRepository
    from syncr_api.solving.coordinator import SolveCoordinator
    from syncr_api.solving.records import OperationRecord
    from syncr_api.user_settings.repository import SettingsRepository
    from syncr_domain.weeks import IsoWeek

_log = get_logger("syncr.learned")


class WeightSetActivation(TenantScopedRepository):
    """The two statements that move the active flag. Nothing else writes this column.

    Both are built through :meth:`~syncr_api.core.repository.TenantScopedRepository.scoped_update`,
    not through a bare ``update``. There is no row-level security in this deployment, so the tenant
    predicate IS the isolation, and applying it in the base rather than per statement is what makes
    it impossible to forget: ``tests/test_tenancy_boundary.py`` reads this source for a bare one.
    """

    async def activate(self, version: int) -> None:
        """Make ``version`` the weights in force, and no other version.

        The caller has already confirmed the version exists and belongs to this tenant: a statement
        matching nothing here would leave the tenant with NO active set, which is worse than the
        state it was asked to change.
        """
        await self._session.execute(
            self.scoped_update(WeightSet).where(WeightSet.active.is_(True)).values(active=False)
        )
        await self._session.execute(
            self.scoped_update(WeightSet).where(WeightSet.version == version).values(active=True)
        )


class FutureWeeksResolved:
    """Invalidates and re-solves every future week this tenant has planned.

    A collaborator rather than a function so the service takes one dependency instead of four, and
    so a service test can record which weeks would have been re-solved without a database.
    """

    def __init__(
        self,
        *,
        versions: WeekInputVersionRepository,
        settings: SettingsRepository,
        coordinator: SolveCoordinator,
    ) -> None:
        self._versions = versions
        self._settings = settings
        self._coordinator = coordinator

    async def from_the_week_holding(self, now: datetime) -> list[OperationRecord]:
        """Bump and re-solve every tracked week from the one holding ``now``'s local date on."""
        settings = await self._settings.read()
        span = weeks_from(local_date(now, settings.home_zone))
        tracked = await self._versions.tracked_weeks(span.first, span.last)
        operations = [await self._resolved(week, at=now) for week in tracked]
        _log.info(
            "learned.weight_set.future_weeks_resolved",
            first_week=str(span.first),
            weeks=len(tracked),
        )
        return operations

    async def _resolved(self, week: IsoWeek, *, at: datetime) -> OperationRecord:
        """One week's bump and the solve it asks for, in that order.

        The version is bumped first and handed to the request, so the operation records the input
        state the activation produced rather than the one the week held before it.
        """
        version = await self._versions.bump(week, at=at)
        return await self._coordinator.request_solve(week, version)
