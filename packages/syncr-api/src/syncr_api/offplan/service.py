"""The off-plan service: authorization, the two invariants, and the version bump.

Four rules live here rather than anywhere else.

**The invariants are the domain's, caught rather than restated.** ``syncr_domain.off_plan``
refuses a span whose bounds are off the quarter-hour grid and a set of periods where two cover
one instant, so declaring or editing a period builds the value the declaration WOULD produce
and answers 422 or 409 when it will not build. Nothing here compares two spans.

**A declaration is serialized on the tenant's settings row.** Overlap is checked against the
periods already stored, so two declarations racing would both pass the check and both insert,
leaving a tenant with two periods covering one instant and no rule able to say which answers
for it. Locking the settings row first makes check-then-insert atomic per tenant, and it works
for a tenant with no periods at all, which is exactly the case a lock over the periods
themselves would leave open. This is the mechanism ``declare_travel_override`` uses, for the
same invariant, over the same row.

**A patch is checked against the merged pair, not against the fields it sent.** Moving one
bound is checked against the stored other and against every other period, so shortening a
holiday can be refused for overlapping the next one.

**Every mutation bumps the week input version of every week the span touches.** An off-plan
span is the denominator's fourth subtrahend, so declaring, moving, or removing one changes how
much discretionary time each week it touches has, and a solve already running for such a week
read a figure that no longer holds. A patch bumps the weeks the span covered AND the weeks it
now covers, because moving a holiday changes two sets of weeks. A label-only patch bumps too:
a label is not a solve input, so that bump buys nothing except a rule with no exception in it,
and renaming a holiday is rare enough that the spare re-solve is cheaper than the rule.

``authorize_tenant`` is called on the one row a caller addresses by identifier. Every row these
methods touch was fetched through a repository scoped to the principal's own tenant, so its
``tenant_id`` IS the principal's, and the scoped ``SELECT`` is what turns another tenant's
identifier into a 404 rather than an edit. The call is defense in depth rather than the check
producing that 404.

``require_scope`` maps the writes to ``admin`` and the reads to ``plan:read``. Time off is
plan CONFIGURATION, like a template or a budget, rather than an act on a week like a pin, and
the CLI is deliberately not granted ``admin``. As on every other domain route today the check
denies nothing over HTTP, because every route reaching these methods resolves a browser
session and a session carries every scope; it becomes live the first time a bearer credential
reaches one of these routes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.core.errors import NotFound
from syncr_api.core.principal import authorize_tenant, require_scope
from syncr_api.core.scopes import Scope
from syncr_api.offplan.config import OFF_PLAN_RESOURCE
from syncr_api.offplan.records import OffPlanPeriodRecord
from syncr_api.offplan.rules import find_period, others_than, stated_rejection
from syncr_api.offplan.weeks import weeks_touching
from syncr_common.logging import get_logger
from syncr_common.metrics import measured
from syncr_domain.intervals import Interval
from syncr_domain.off_plan import OffPlanPeriod, require_disjoint

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_api.core.clock import Clock
    from syncr_api.core.principal import Principal
    from syncr_api.offplan.declarations import OffPlanChange, OffPlanDeclaration
    from syncr_api.offplan.repository import OffPlanPeriodRepository
    from syncr_api.user_settings.repository import SettingsRepository
    from syncr_api.user_settings.solve_inputs import WeekInputVersions
    from syncr_domain.identifiers import OffPlanPeriodId
    from syncr_domain.zones import ZoneId

_log = get_logger("syncr.offplan")


class OffPlanService:
    """Read and change one tenant's off-plan periods, and invalidate the weeks they touch."""

    def __init__(
        self,
        periods: OffPlanPeriodRepository,
        settings: SettingsRepository,
        versions: WeekInputVersions,
        clock: Clock,
    ) -> None:
        self._periods = periods
        self._settings = settings
        self._versions = versions
        self._clock = clock

    @measured("offplan")
    async def list_all(self, principal: Principal) -> tuple[OffPlanPeriodRecord, ...]:
        """Every period this tenant has declared, earliest first. Writes nothing."""
        require_scope(principal, Scope.PLAN_READ)
        return await self._periods.list_all()

    @measured("offplan")
    async def read(self, principal: Principal, period_id: OffPlanPeriodId) -> OffPlanPeriodRecord:
        """One period of this tenant's, or a 404 that discloses nothing about another's."""
        require_scope(principal, Scope.PLAN_READ)
        found = await self._periods.find(period_id)
        if found is None:
            raise NotFound(f"No {OFF_PLAN_RESOURCE} matches that identifier.")
        authorize_tenant(principal, found.tenant_id, resource=OFF_PLAN_RESOURCE)
        return found

    @measured("offplan")
    async def declare(
        self, principal: Principal, declaration: OffPlanDeclaration
    ) -> OffPlanPeriodRecord:
        """Declare a span off, or state why it cannot be declared."""
        require_scope(principal, Scope.ADMIN)
        now = self._clock()
        settings = await self._settings.lock(created_at=now)
        stored = await self._periods.list_all()
        candidate = _declarable(declaration, stored, apart_from=None)

        created = await self._periods.create(
            interval=candidate.interval,
            keep_frame=candidate.keep_frame,
            label=candidate.label,
            created_at=now,
        )
        # The LABEL is deliberately absent from this line. It is the user's own words, and a
        # period labelled "Italy" discloses where they are as plainly as an anchor location does.
        _log.info(
            "offplan.period.declared",
            tenant_id=str(principal.tenant_id),
            period_id=str(created.id),
            keep_frame=created.keep_frame,
            minutes=created.interval.total_minutes(),
        )
        await self._bump(settings.home_zone, created.interval)
        return created

    @measured("offplan")
    async def update(
        self, principal: Principal, period_id: OffPlanPeriodId, change: OffPlanChange
    ) -> OffPlanPeriodRecord:
        """Move a bound, rename a span, or change what survives inside it.

        The settings row is locked for the same reason declaring locks it: the merged pair is
        checked against every other period, so a concurrent declaration must not land between
        reading them and writing.
        """
        require_scope(principal, Scope.ADMIN)
        now = self._clock()
        settings = await self._settings.lock(created_at=now)
        stored = await self._periods.list_all()
        current = find_period(period_id, stored)
        if current is None:
            raise NotFound(f"No {OFF_PLAN_RESOURCE} matches that identifier.")
        authorize_tenant(principal, current.tenant_id, resource=OFF_PLAN_RESOURCE)

        candidate = _declarable(change.applied_to(current), stored, apart_from=period_id)
        await self._periods.write(
            period_id,
            interval=candidate.interval,
            keep_frame=candidate.keep_frame,
            label=candidate.label,
        )
        _log.info(
            "offplan.period.changed",
            tenant_id=str(principal.tenant_id),
            period_id=str(period_id),
            keep_frame=candidate.keep_frame,
            minutes=candidate.interval.total_minutes(),
            moved=candidate.interval != current.interval,
        )
        # Both spans, because a moved period changes the denominator of the weeks it left as
        # well as the weeks it now covers. Identical ranges are bumped once.
        await self._bump(settings.home_zone, current.interval, candidate.interval)
        return _changed(current, candidate)

    @measured("offplan")
    async def remove(self, principal: Principal, period_id: OffPlanPeriodId) -> None:
        """Remove a period, so its span is on plan again."""
        require_scope(principal, Scope.ADMIN)
        found = await self._periods.find(period_id)
        if found is None:
            raise NotFound(f"No {OFF_PLAN_RESOURCE} matches that identifier.")
        authorize_tenant(principal, found.tenant_id, resource=OFF_PLAN_RESOURCE)

        await self._periods.remove(period_id)
        _log.info(
            "offplan.period.removed",
            tenant_id=str(principal.tenant_id),
            period_id=str(period_id),
            minutes=found.interval.total_minutes(),
        )
        settings = await self._settings.read()
        await self._bump(settings.home_zone, found.interval)

    async def _bump(self, home_zone: ZoneId, *spans: Interval) -> None:
        """Invalidate every week the given spans touch, each week at most once."""
        ranges = dict.fromkeys(weeks_touching(span, home_zone=home_zone) for span in spans)
        for affected in ranges:
            await self._versions.bump(affected)


def _declarable(
    declaration: OffPlanDeclaration,
    stored: Sequence[OffPlanPeriodRecord],
    *,
    apart_from: OffPlanPeriodId | None,
) -> OffPlanPeriod:
    """The period ``declaration`` names, or the status its rejection carries.

    Both invariants are checked inside one mapping, so a bad pair of bounds and an overlapping
    span are answered from the same place and neither can be added without a status.
    """
    with stated_rejection():
        candidate = OffPlanPeriod(
            interval=Interval(declaration.start, declaration.end),
            keep_frame=declaration.keep_frame,
            label=declaration.label,
        )
        require_disjoint([*others_than(apart_from, stored), candidate])
    return candidate


def _changed(current: OffPlanPeriodRecord, candidate: OffPlanPeriod) -> OffPlanPeriodRecord:
    """The stored record as the write left it, without reading it back."""
    return OffPlanPeriodRecord(
        id=current.id,
        tenant_id=current.tenant_id,
        interval=candidate.interval,
        keep_frame=candidate.keep_frame,
        label=candidate.label,
        created_at=current.created_at,
    )
