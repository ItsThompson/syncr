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

**One transaction and one failure boundary per week, and one per TENANT.** A week whose assembly
raises is counted and the weeks after it still run, and a week's revision and its version bump
either both land or neither does. A tenant whose zone or horizon cannot be read is counted too, and
the tenants after it still run: without that boundary one corrupt stored ``home_zone`` would abort
the pass before it reached the gauge, leaving the gauge at whatever it last held. On a fresh process
that is zero, and ``HorizonNotMaintained`` fires above zero, so the alert could not fire for a duty
failing on every pass. Counted rather than only logged, because a contained fault answers with a
tally and a week or a tenant failing every tick would otherwise leave every counter at zero while
the duty reported healthy.

**The FIRST tick schedules rather than plans.** A process that restarts often would otherwise run a
pass on every boot, and a pass reads a revision per horizon week per tenant.

**Duty 2 runs over the weeks duty 1 already resolved**, so the tick reads each tenant's zone and
horizon once and both duties are evaluated against one instant and one horizon. It is timed under
its own label because its cost is unrelated: duty 1 skips a planned week with one indexed read, and
duty 2 assembles every week that has a plan.

**When to come back is decided before duty 2 runs.** Duty 2 contains its own faults per week and per
tenant, but a fault in the containment itself must not leave the runner due immediately, because
that would re-run duty 1 on every tick of the loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from prometheus_client import Counter

from syncr_api.accounts.repository import TenantRepository
from syncr_api.horizon.config import MAINTAINER_INTERVAL, MaintainerDuty
from syncr_api.horizon.maintainer import HorizonPass, PlanHorizonMaintainer
from syncr_api.horizon.metrics import HORIZON_WEEKS_WITHOUT_PLAN, MAINTAINER_TICK_DURATION
from syncr_api.horizon.verdicts import TimeDrivenVerdicts, VerdictPass
from syncr_api.horizon.weeks import next_local_midnight
from syncr_common.logging import get_logger
from syncr_common.metrics import REGISTRY

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime, timedelta

    from syncr_api.core.clock import Clock
    from syncr_api.worker.main import WorkerContext
    from syncr_domain.identifiers import TenantId
    from syncr_domain.weeks import IsoWeek

# A tenant whose horizon could not be read at all. Contained, so it reaches neither the loop's own
# failure counter nor `measured`: a fault that answers with a tally is invisible unless something
# counts it. `18-observability.md` defines no alert on this family yet, which ticket 54 owns.
TENANT_PASS_FAILURES = Counter(
    "syncr_horizon_tenant_failures_total",
    "Plan horizon passes that raised for one tenant before reaching its weeks.",
    registry=REGISTRY,
)

_log = get_logger("syncr.horizon")


@dataclass(frozen=True, slots=True)
class PlannedHorizon:
    """What duty 1 leaves behind: when the next pass is due, and the weeks it resolved.

    The weeks are carried rather than recomputed because duty 2 runs over the same set, and a second
    resolution would read every tenant's zone and horizon again and could answer differently: a pass
    that crossed local midnight between its two duties would probe a week it had not planned.

    A tenant whose horizon could not be read holds no entry, which is what keeps its contained fault
    counted once rather than once per duty.
    """

    due_at: datetime
    weeks: Mapping[TenantId, tuple[IsoWeek, ...]]


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
            planned = await self.plan(context, now=now)
        self._next_due_at = planned.due_at
        with MAINTAINER_TICK_DURATION.labels(duty=MaintainerDuty.VERDICTS.value).time():
            await self.record_transitions(context, planned.weeks, now=now)

    async def plan(self, context: WorkerContext, *, now: datetime) -> PlannedHorizon:
        """Duty 1: one pass over every tenant's horizon, planning the weeks that hold no plan.

        Answers when the next pass is due and which weeks it resolved, which is what duty 2 runs
        over.

        The gauge is SET from the pass's own tally rather than nudged per week, so a contained fault
        leaves an honest number: a gauge incremented per week would drift permanently the first time
        a pass raised between two weeks.
        """
        async with context.database.sessionmaker() as reader:
            tenants = await TenantRepository(reader).list_ids()

        total = HorizonPass()
        midnights: list[datetime] = []
        resolved: dict[TenantId, tuple[IsoWeek, ...]] = {}
        for tenant_id in tenants:
            tally, midnight, weeks = await self._tenant(context, tenant_id, now=now)
            total = total.plus(tally)
            if midnight is not None:
                midnights.append(midnight)
            if weeks:
                resolved[tenant_id] = weeks

        HORIZON_WEEKS_WITHOUT_PLAN.set(total.without_a_plan)
        if total.weeks or total.tenants_failed:
            _log.info("horizon.pass.completed", **total.as_log_fields())
        return PlannedHorizon(due_at=min([now + self._interval, *midnights]), weeks=resolved)

    async def record_transitions(
        self,
        context: WorkerContext,
        weeks: Mapping[TenantId, tuple[IsoWeek, ...]],
        *,
        now: datetime,
    ) -> VerdictPass:
        """Duty 2: probe every resolved week that has a plan, and record what changed.

        The only writer for a week that became impossible because Monday's slack went unused. Each
        week is probed in a transaction of its own, so one week's transition cannot be lost to
        another week's failure.
        """
        total = VerdictPass()
        for tenant_id, resolved in weeks.items():
            for iso_week in resolved:
                total = total.plus(await self._transition(context, tenant_id, iso_week, now=now))
        if total.weeks:
            _log.info("horizon.verdicts.completed", **total.as_log_fields())
        return total

    async def _tenant(
        self, context: WorkerContext, tenant_id: TenantId, *, now: datetime
    ) -> tuple[HorizonPass, datetime | None, tuple[IsoWeek, ...]]:
        """One tenant's horizon, week by week, when its local date next changes, and its weeks.

        The zone and the week list are read in a session of their own and each week is then planned
        in a transaction of its own, so a week that fails rolls back its own write and nothing else.

        That read is contained too, and it is the one fault that would otherwise abort the whole
        pass: ``local_date`` resolves the stored ``home_zone`` through the zone layer, which refuses
        an identifier it does not know. Answers with no midnight in that case, because a tenant
        whose zone cannot be read has no knowable midnight either, so the interval is the only bound
        left, and with no weeks, so duty 2 does not re-read what has already failed once.
        """
        try:
            async with context.database.sessionmaker() as reader:
                maintainer = PlanHorizonMaintainer(reader, tenant_id, self._clock)
                zone = await maintainer.home_zone()
                weeks = await maintainer.weeks_in_the_horizon(now=now, zone=zone)
        except Exception:  # noqa: BLE001 - one tenant's fault must not stop the others
            TENANT_PASS_FAILURES.inc()
            _log.exception("horizon.tenant.failed", tenant_id=str(tenant_id))
            return HorizonPass(tenants_failed=1), None, ()

        total = HorizonPass()
        for iso_week in weeks:
            total = total.plus(await self._week(context, tenant_id, iso_week, now=now))
        return total, next_local_midnight(now, zone), weeks

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

    async def _transition(
        self, context: WorkerContext, tenant_id: TenantId, iso_week: IsoWeek, *, now: datetime
    ) -> VerdictPass:
        """One week's duty-2 probe, in its own transaction, with its own fault contained.

        ``VE5``: the transaction is the job that computed the verdict, so a tick cannot record a
        week's transition partially, and a week whose assembly raises leaves no row at all.

        The fault is contained here so the weeks after this one are still probed. What counts it is
        ``syncr_method_errors_total{component="horizon_verdicts"}`` from the raise itself, because a
        recording duty that failed on every week would otherwise leave both transition counters at
        zero, which reads exactly like a week nobody's plan changed.
        """
        try:
            async with context.database.sessionmaker() as session, session.begin():
                return await TimeDrivenVerdicts(session, tenant_id).record(iso_week, now=now)
        except Exception:  # noqa: BLE001 - one week's fault must not stop the others
            _log.exception(
                "horizon.verdict.failed", tenant_id=str(tenant_id), iso_week=str(iso_week)
            )
            return VerdictPass(weeks=1, failed=1)
