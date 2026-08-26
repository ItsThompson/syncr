"""Duty 1: ask for a solve of every ISO week overlapping the projection horizon that holds no plan.

```
for each tenant:
  now     = one instant, read ONCE by the runner and passed to everything below
  horizon = [today_local, today_local + write_target.horizon_days)
  weeks   = every ISO week overlapping the horizon, CHRONOLOGICALLY

  for each week:
    has a live revision?                    ──▶ nothing to do
    no live revision, minimum inputs exist? ──▶ track the week (bump) and request a solve,
                                                due one debounce window later. The solve
                                                produces the plan; this pass writes none
    no live revision, minimum inputs MISSING ──▶ nothing. Asking for a solve without Areas
                                                would fail at load time with less to say
                                                than this pass can say now
```

**The pass requests and does not produce.** A week entering the horizon becomes a ``solve``
operation like any other trigger's, and the coordinator is what plans weeks. The bump travels with
the request because tracking the week IS this trigger's write: without the row, every later
backlog-wide mutation would enumerate past this week and leave its plan uninvalidated.

**A week whose emptiness is answered stays answered.** A solve over a backlog with nothing to place
adopts no plan, so a content-less horizon would otherwise be bumped and asked about again every
cadence forever. When the week's own last solve succeeded without appending anything and its input
version still stands, the pass counts the week settled and asks no more; the next mutation moves
the version and the asking resumes.

**``now`` is read once and passed down.** A tick that read the clock per week could compute a
horizon from one date and a week's version stamp from another, and at 00:00 the two would differ by
a day: the week brought in would not be the week tracked. Every decision a tick makes is evaluated
against one instant, so a tick is reproducible.

**Chronological order matters on first run.** Three weeks with no plan are asked for oldest first,
so the week the user is looking at is due before the two they are not.

**Idempotent, and cheaply so.** A week with a live revision is skipped by a read, and a week whose
solve is already pending is joined by the coordinator rather than duplicated, so a second tick a
second later creates no operation and appends no revision. That is what makes the fifteen-minute
cadence free on the ordinary path: the pass costs one revision read per horizon week.

**One transaction per week**, so one week's fault cannot lose another week's request, and one
failure boundary per week, so a week whose request raised does not stop the weeks after it. A week
that failed is counted as without a plan, which is what the gauge exists to say.

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
from syncr_api.plans.readiness import MinimumInputs
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.config import SOLVE, SUCCEEDED
from syncr_api.solving.injection import build_solve_coordinator
from syncr_api.solving.repository import OperationRepository
from syncr_api.templates.repository import WeekPatternRepository
from syncr_api.user_settings.repository import SettingsRepository
from syncr_api.user_settings.zone_reading import local_date
from syncr_common.logging import get_logger

if TYPE_CHECKING:
    from datetime import datetime, timedelta

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
    settled: int = 0

    @property
    def without_a_plan(self) -> int:
        """Horizon weeks this pass left with no live plan, which is what the gauge reports.

        A week the maintainer could not plan and a week it failed to plan are both weeks inside the
        horizon with nothing to project, so both count: the gauge measures the hole rather than the
        cause, and the cause is in the log line beside it.

        **A settled week counts as zero.** A week whose emptiness a solve has already stated is not
        a hole the duty can fill: the backlog holds nothing to place, and asking again asks the same
        question. It is counted on its own field so an operator can see how much of the horizon is
        empty by content rather than by fault.

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
            settled=self.settled + other.settled,
        )

    def as_log_fields(self) -> dict[str, int]:
        return {
            "horizon_weeks": self.weeks,
            "planned": self.planned,
            "already_planned": self.already_planned,
            "not_ready": self.not_ready,
            "failed": self.failed,
            "tenants_failed": self.tenants_failed,
            "settled": self.settled,
        }


class PlanHorizonMaintainer:
    """Asks for a solve of every horizon week of one tenant that has no plan, oldest first."""

    def __init__(
        self, session: AsyncSession, tenant_id: TenantId, clock: Clock, *, debounce: timedelta
    ) -> None:
        self._session = session
        self._tenant_id = tenant_id
        self._clock = clock
        # This deployment's window, threaded from the composition root. The request is not urgent
        # -- time passing is nobody's deadline -- so it is scheduled like any other trigger's and
        # the window is what the coordinator schedules against.
        self._debounce = debounce

    async def home_zone(self) -> ZoneId:
        """The zone this tenant's dates are resolved in, which is also what its midnight is."""
        return (await SettingsRepository(self._session, self._tenant_id).read()).home_zone

    async def weeks_in_the_horizon(self, *, now: datetime, zone: ZoneId) -> tuple[IsoWeek, ...]:
        """Every ISO week overlapping this tenant's horizon, earliest first.

        The horizon's length is the write target's, so a tenant who has widened it asks for more
        weeks on the next tick and their input versions are bumped as each is requested.
        """
        sources = CalendarSourceRepository(self._session, self._tenant_id)
        return horizon_weeks(
            today=local_date(now, zone), horizon_days=await read_horizon_days(sources)
        )

    async def plan(self, iso_week: IsoWeek, *, now: datetime) -> HorizonPass:
        """One week: skipped, asked for, settled, or left alone because a plan cannot exist yet.

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

        if await self._settled(iso_week):
            _log.info(
                "horizon.week.settled",
                tenant_id=str(self._tenant_id),
                iso_week=str(iso_week),
            )
            return HorizonPass(weeks=1, settled=1)

        await self._request(iso_week, now=now)
        return HorizonPass(weeks=1, planned=1)

    async def _settled(self, iso_week: IsoWeek) -> bool:
        """Whether this week's emptiness is already answered, so asking again asks nothing new.

        A solve of a week whose backlog holds nothing to place adopts no plan: the candidate has no
        fill, so the week keeps no revision, and without this check every pass would bump and ask
        again forever over inputs that have not moved. The answer is read off the operation itself:
        it succeeded, it appended no revision, and the input version it stamped is still the one
        the week holds. Any later mutation bumps that version, and the next pass asks afresh.
        """
        versions = WeekInputVersionRepository(self._session, self._tenant_id)
        version = await versions.current(iso_week)
        if version is None:
            return False
        last = await OperationRepository(self._session, self._tenant_id).latest_of(
            iso_week, kinds=(SOLVE,)
        )
        return (
            last is not None
            and last.status == SUCCEEDED
            and last.result_revision_id is None
            and last.input_version == version
        )

    async def _request(self, iso_week: IsoWeek, *, now: datetime) -> None:
        """Track the week and ask the coordinator for its solve, in that order.

        The bump is this trigger's own write, not an invalidation: a week entering the horizon has
        no plan and no running solve, and version 1 is what creates the row later mutations and
        backlog-wide bumps enumerate. It is handed to the request so the operation records the
        input state the pass left rather than an untracked placeholder.
        """
        versions = WeekInputVersionRepository(self._session, self._tenant_id)
        version = await versions.bump(iso_week, at=now)
        coordinator = build_solve_coordinator(
            self._session, self._tenant_id, clock=self._clock, debounce=self._debounce
        )
        # Time passing states nothing about the weekly session, and there is no caller to ask.
        operation = await coordinator.request_solve(iso_week, version, session_mode_active=False)
        _log.info(
            "horizon.week.requested",
            tenant_id=str(self._tenant_id),
            iso_week=str(iso_week),
            operation_id=str(operation.id),
            input_version=version,
        )
