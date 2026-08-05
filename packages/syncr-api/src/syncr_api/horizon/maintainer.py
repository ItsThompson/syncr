"""Duty 1: keep every ISO week overlapping the projection horizon supplied with a live plan.

```
for each tenant:
  now     = one instant, read ONCE by the runner and passed to everything below
  horizon = [today_local, today_local + write_target.horizon_days)
  weeks   = every ISO week overlapping the horizon, CHRONOLOGICALLY

  for each week:
    has a live revision?                    ──▶ nothing to do
    no live revision, minimum inputs exist? ──▶ produce one, reason horizon_advanced
    no live revision, minimum inputs MISSING ──▶ nothing. Guessing at a plan without
                                                Areas would be worse than showing why
                                                one cannot exist
```

**``now`` is read once and passed down.** A tick that read the clock per week could compute a
horizon from one date and a week's inputs from another, and at 00:00 the two would differ by a day:
the week brought in would not be the week planned. Every decision a tick makes is evaluated against
one instant, and the assembler stamps that same instant onto its output, so a tick is reproducible.

**Chronological order matters on first run.** Three weeks with no plan are planned oldest first, so
the week the user is looking at exists before the two they are not.

**Idempotent, and cheaply so.** A week with a live revision is skipped by a read, so a second tick a
second later creates no operation and appends no revision. That is what makes the fifteen-minute
cadence free on the ordinary path: the pass costs one revision read per horizon week.

**One transaction per week**, so one week's fault cannot lose another week's plan, and one failure
boundary per week, so a week whose assembly raised does not stop the weeks after it. A week that
failed is counted as without a plan, which is what the gauge exists to say.

**A read never reaches this.** The maintainer is composed by the worker and by nothing else, and the
one place it is constructed is the runner beside it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.areas.repository import AreaRepository
from syncr_api.calendars.horizons import read_horizon_days
from syncr_api.calendars.repository import CalendarSourceRepository
from syncr_api.horizon.weeks import horizon_weeks
from syncr_api.learned.repository import WeightSetRepository
from syncr_api.plans.assembler import AssemblyCaller
from syncr_api.plans.injection import build_week_assembler
from syncr_api.plans.production import WeekProducer
from syncr_api.plans.readiness import MinimumInputs
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.lifecycle import OperationLifecycle
from syncr_api.solving.repository import OperationRepository
from syncr_api.templates.repository import WeekPatternRepository
from syncr_api.user_settings.repository import SettingsRepository
from syncr_api.user_settings.zone_reading import local_date
from syncr_common.logging import get_logger

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_api.core.clock import Clock
    from syncr_domain.identifiers import TenantId
    from syncr_domain.weeks import IsoWeek
    from syncr_domain.zones import ZoneId

_log = get_logger("syncr.horizon")


@dataclass(frozen=True, slots=True)
class HorizonPass:
    """What one pass found and did, so one log line says it and the gauge is set once."""

    weeks: int = 0
    planned: int = 0
    already_planned: int = 0
    not_ready: int = 0
    failed: int = 0
    tenants_failed: int = 0

    @property
    def without_a_plan(self) -> int:
        """Horizon weeks this pass left with no live plan, which is what the gauge reports.

        A week the maintainer could not plan and a week it failed to plan are both weeks inside the
        horizon with nothing to project, so both count: the gauge measures the hole rather than the
        cause, and the cause is in the log line beside it.

        **A tenant whose horizon could not be read at all counts as one week.** How many weeks it
        really has is unknowable, because the read that would have said so is the read that failed,
        and one is the honest lower bound. Reporting zero for it would leave the gauge at zero for a
        tenant whose weeks are never planned, and ``HorizonNotMaintained`` fires above zero, so the
        alert would be silent for exactly the failure it exists to catch.
        """
        return self.not_ready + self.failed + self.tenants_failed

    def plus(self, other: HorizonPass) -> HorizonPass:
        return HorizonPass(
            weeks=self.weeks + other.weeks,
            planned=self.planned + other.planned,
            already_planned=self.already_planned + other.already_planned,
            not_ready=self.not_ready + other.not_ready,
            failed=self.failed + other.failed,
            tenants_failed=self.tenants_failed + other.tenants_failed,
        )

    def as_log_fields(self) -> dict[str, int]:
        return {
            "horizon_weeks": self.weeks,
            "planned": self.planned,
            "already_planned": self.already_planned,
            "not_ready": self.not_ready,
            "failed": self.failed,
            "tenants_failed": self.tenants_failed,
        }


class PlanHorizonMaintainer:
    """Plans every horizon week of one tenant that has no plan, in chronological order."""

    def __init__(self, session: AsyncSession, tenant_id: TenantId, clock: Clock) -> None:
        self._session = session
        self._tenant_id = tenant_id
        self._clock = clock

    async def home_zone(self) -> ZoneId:
        """The zone this tenant's dates are resolved in, which is also what its midnight is."""
        return (await SettingsRepository(self._session, self._tenant_id).read()).home_zone

    async def weeks_in_the_horizon(self, *, now: datetime, zone: ZoneId) -> tuple[IsoWeek, ...]:
        """Every ISO week overlapping this tenant's horizon, earliest first.

        The horizon's length is the write target's, so a tenant who has widened it plans more weeks
        on the next tick and their input versions are bumped as each is planned.
        """
        sources = CalendarSourceRepository(self._session, self._tenant_id)
        return horizon_weeks(
            today=local_date(now, zone), horizon_days=await read_horizon_days(sources)
        )

    async def plan(self, iso_week: IsoWeek, *, now: datetime) -> HorizonPass:
        """One week: skipped, planned, or left alone because a plan cannot exist for it yet.

        The live-revision read is first and it is the whole of the idempotence: a week that has a
        plan costs one indexed read and creates nothing.
        """
        revisions = PlanRepository(self._session, self._tenant_id)
        if await revisions.latest(iso_week) is not None:
            return HorizonPass(weeks=1, already_planned=1)

        readiness = await MinimumInputs(
            AreaRepository(self._session, self._tenant_id),
            WeekPatternRepository(self._session, self._tenant_id),
        ).read()
        if not readiness.is_ready:
            _log.info(
                "horizon.week.not_ready",
                tenant_id=str(self._tenant_id),
                iso_week=str(iso_week),
                missing=[one.value for one in readiness.missing],
            )
            return HorizonPass(weeks=1, not_ready=1)

        await self._producer(revisions).advance_into(iso_week, now=now)
        return HorizonPass(weeks=1, planned=1)

    def _producer(self, revisions: PlanRepository) -> WeekProducer:
        return WeekProducer(
            assembler=build_week_assembler(
                self._session, self._tenant_id, caller=AssemblyCaller.MAINTAINER
            ),
            revisions=revisions,
            versions=WeekInputVersionRepository(self._session, self._tenant_id),
            weights=WeightSetRepository(self._session, self._tenant_id),
            operations=OperationLifecycle(
                OperationRepository(self._session, self._tenant_id), self._clock
            ),
        )
