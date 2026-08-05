"""The worker duty that runs the plan horizon maintainer: every fifteen minutes, and at midnight.

**The tick reads the clock ONCE.** ``now`` is taken at the top of the pass and passed to every
decision below it, so a tick's horizon, its week list and each week's assembly are all evaluated
against one instant. A tick that read the clock per week could compute a horizon from one local date
and a week's inputs from another, and at 00:00 the two would differ by a day.

**Due-ness is the earlier of the interval and the next local midnight.** The horizon is
``[today_local, today_local + horizon_days)``, so it advances AT local midnight; the interval alone
would advance it up to fifteen minutes late, at whatever phase a restart left. The midnight is
computed at the END of a pass, when every tenant's zone has already been read, so the gate itself
costs nothing: the earliest midnight across tenants is the one that matters, because a tick serves
all of them.

**One transaction and one failure boundary per week.** A week whose assembly raises is counted and
the weeks after it still run, and a week's revision and its version bump either both land or neither
does. Counted rather than only logged, because a contained fault answers with a tally and a week
failing every tick would otherwise leave every counter at zero while the duty reported healthy.

**The FIRST tick schedules rather than plans.** A process that restarts often would otherwise run a
pass on every boot, and a pass reads a revision per horizon week per tenant.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.accounts.repository import TenantRepository
from syncr_api.horizon.config import MAINTAINER_INTERVAL, MaintainerDuty
from syncr_api.horizon.maintainer import HorizonPass, PlanHorizonMaintainer
from syncr_api.horizon.metrics import HORIZON_WEEKS_WITHOUT_PLAN, MAINTAINER_TICK_DURATION
from syncr_api.horizon.weeks import next_local_midnight
from syncr_common.logging import get_logger

if TYPE_CHECKING:
    from datetime import datetime, timedelta

    from syncr_api.core.clock import Clock
    from syncr_api.worker.main import WorkerContext
    from syncr_domain.identifiers import TenantId
    from syncr_domain.weeks import IsoWeek

_log = get_logger("syncr.horizon")


class PlanHorizonRunner:
    """One duty on the worker loop: plan the horizon when due, return immediately when not.

    A callable object rather than a closure, so the loop's name lookup finds a stable name for its
    failure metric and so a test can read when the maintainer is next due.
    """

    __name__ = "plan_horizon_maintainer"

    def __init__(self, *, interval: timedelta = MAINTAINER_INTERVAL, clock: Clock) -> None:
        self._interval = interval
        self._clock = clock
        self._next_due_at: datetime | None = None

    @property
    def next_due_at(self) -> datetime | None:
        """When this runner will next plan, or ``None`` before its first tick."""
        return self._next_due_at

    async def __call__(self, context: WorkerContext) -> None:
        now = self._clock()
        if self._next_due_at is None or now < self._next_due_at:
            self._next_due_at = self._next_due_at or now + self._interval
            return
        with MAINTAINER_TICK_DURATION.labels(duty=MaintainerDuty.HORIZON.value).time():
            self._next_due_at = await self.plan(context, now=now)

    async def plan(self, context: WorkerContext, *, now: datetime) -> datetime:
        """One pass over every tenant's horizon. Answers when the next pass is due.

        The gauge is SET from the pass's own tally rather than nudged per week, so a contained fault
        leaves an honest number: a gauge incremented per week would drift permanently the first time
        a pass raised between two weeks.
        """
        async with context.database.sessionmaker() as reader:
            tenants = await TenantRepository(reader).list_ids()

        total = HorizonPass()
        midnights: list[datetime] = []
        for tenant_id in tenants:
            tally, midnight = await self._tenant(context, tenant_id, now=now)
            total = total.plus(tally)
            midnights.append(midnight)

        HORIZON_WEEKS_WITHOUT_PLAN.set(total.without_a_plan)
        if total.weeks:
            _log.info("horizon.pass.completed", **total.as_log_fields())
        return min([now + self._interval, *midnights])

    async def _tenant(
        self, context: WorkerContext, tenant_id: TenantId, *, now: datetime
    ) -> tuple[HorizonPass, datetime]:
        """One tenant's horizon, week by week, and when its local date next changes.

        The zone and the week list are read in a session of their own and each week is then planned
        in a transaction of its own, so a week that fails rolls back its own write and nothing else.
        """
        async with context.database.sessionmaker() as reader:
            maintainer = PlanHorizonMaintainer(reader, tenant_id, self._clock)
            zone = await maintainer.home_zone()
            weeks = await maintainer.weeks_in_the_horizon(now=now, zone=zone)

        total = HorizonPass()
        for iso_week in weeks:
            total = total.plus(await self._week(context, tenant_id, iso_week, now=now))
        return total, next_local_midnight(now, zone)

    async def _week(
        self, context: WorkerContext, tenant_id: TenantId, iso_week: IsoWeek, *, now: datetime
    ) -> HorizonPass:
        """One week, in its own transaction, with its own fault contained.

        Answers with a failure tally rather than re-raising, so the weeks after this one are still
        planned. The failure is counted and named HERE rather than left to the worker loop's
        handler,
        which isolates one DUTY and would therefore drop every remaining week of every tenant.
        """
        try:
            async with context.database.sessionmaker() as session, session.begin():
                return await PlanHorizonMaintainer(session, tenant_id, self._clock).plan(
                    iso_week, now=now
                )
        except Exception:  # noqa: BLE001 - one week's fault must not stop the others
            _log.exception("horizon.week.failed", tenant_id=str(tenant_id), iso_week=str(iso_week))
            return HorizonPass(weeks=1, failed=1)
