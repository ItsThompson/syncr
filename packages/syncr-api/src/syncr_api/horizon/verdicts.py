"""Duty 2: record the verdict transitions no mutation causes, because time passing is not one.

```
for each horizon week WITH a live plan:
  inputs  = assemble(week, now)          the tick's own instant, read once above
  verdict = probe(inputs.for_probe())    provenance = probe, sub-millisecond
  transitioned against this week's latest VerdictEvent?
    yes ──▶ append VerdictEvent(surface="maintainer", session_mode_active=False)
    no  ──▶ nothing
```

**This is the only writer for the most ordinary way a week becomes impossible**: Monday's slack went
unused, so Friday's deadline is now unreachable. No mutation causes that, and no read may write, so
the denominator of the early-catch product metric would lose its most common case and the ratio
would report a number better than the truth.

**What it costs is the assembly, not the probe.** Three weeks every fifteen minutes is roughly 288
assemblies and probes a day; the probe arithmetic is sub-millisecond and the assembly is the cost.
``syncr_assembly_duration_seconds{caller="maintainer"}`` is what makes those assemblies visible, and
it is the figure to read before shortening the interval.

**A week with no live plan is skipped**, because a verdict about a plan that does not exist is a
verdict about nothing. Duty 1 is what brings that plan into existence, and this duty reads the
revision rather than duty 1's tally so the two are independent: which of ``materialized``,
``horizon_advanced`` or an adopted solve produced the plan is not a thing this duty can read.

**One instant for the whole tick.** ``now`` comes from the runner, is handed to the assembler, and
the assembler stamps it onto its output, which the probe carries onto the verdict and the row
carries from there. No clock is read here at all, so a tick's transitions cannot be evaluated
against two instants.

**``session_mode_active`` is ``False``**, stated as a literal below. The worker cannot know
whether a weekly session is open, and a background probe is by definition not a user planning their
week.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.horizon.metrics import MAINTAINER_VERDICT_TRANSITIONS, TransitionDirection
from syncr_api.plans.assembler import AssemblyCaller
from syncr_api.plans.injection import build_verdict_recorder, build_week_assembler
from syncr_api.plans.recording import NO_SESSION_IS_OPEN
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.surfaces import VerdictSurface
from syncr_api.plans.verdicts import ProbeCaller, WeekProbe
from syncr_common.logging import get_logger
from syncr_common.metrics import measured

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_api.plans.recording import VerdictRecorder
    from syncr_domain.identifiers import TenantId
    from syncr_domain.weeks import IsoWeek

_log = get_logger("syncr.horizon")


@dataclass(frozen=True, slots=True)
class VerdictPass:
    """What one duty-2 pass probed and recorded, so one log line says it."""

    weeks: int = 0
    without_a_plan: int = 0
    unchanged: int = 0
    to_infeasible: int = 0
    to_feasible: int = 0
    failed: int = 0

    @property
    def recorded(self) -> int:
        """Rows this pass appended, which is the two directions together."""
        return self.to_infeasible + self.to_feasible

    def plus(self, other: VerdictPass) -> VerdictPass:
        return VerdictPass(
            weeks=self.weeks + other.weeks,
            without_a_plan=self.without_a_plan + other.without_a_plan,
            unchanged=self.unchanged + other.unchanged,
            to_infeasible=self.to_infeasible + other.to_infeasible,
            to_feasible=self.to_feasible + other.to_feasible,
            failed=self.failed + other.failed,
        )

    def as_log_fields(self) -> dict[str, int]:
        return {
            "probed_weeks": self.weeks,
            "without_a_plan": self.without_a_plan,
            "unchanged": self.unchanged,
            "to_infeasible": self.to_infeasible,
            "to_feasible": self.to_feasible,
            "failed": self.failed,
        }


class TimeDrivenVerdicts:
    """Duty 2 for one tenant: probes one week and records the transition, if there is one."""

    def __init__(self, session: AsyncSession, tenant_id: TenantId) -> None:
        self._session = session
        self._tenant_id = tenant_id

    @measured("horizon_verdicts")
    async def record(self, iso_week: IsoWeek, *, now: datetime) -> VerdictPass:
        """One week: skipped for want of a plan, unchanged, or a transition appended.

        The live-revision read is first and it is what makes a week with nothing to probe cost one
        indexed read. The assembly follows only for a week that has a plan, which is the cost this
        duty is measured by.
        """
        if await PlanRepository(self._session, self._tenant_id).latest(iso_week) is None:
            return VerdictPass(weeks=1, without_a_plan=1)

        assembler = build_week_assembler(
            self._session, self._tenant_id, caller=AssemblyCaller.MAINTAINER
        )
        verdict = WeekProbe(caller=ProbeCaller.MAINTAINER).verdict_for(
            await assembler.assemble(iso_week, now)
        )
        written = await self._recorder().record(iso_week, verdict)
        if written is None:
            return VerdictPass(weeks=1, unchanged=1)

        direction = TransitionDirection.of(feasible=written.feasible)
        # Incremented before the commit, as the transition counter beside it is: the ROWS are the
        # fact this metric describes, so a failure after the append leaves this counter one above
        # the row count until the process restarts. An operator comparing the two reads the rows.
        MAINTAINER_VERDICT_TRANSITIONS.labels(direction=direction.value).inc()
        _log.info(
            "horizon.verdict.transitioned",
            tenant_id=str(self._tenant_id),
            iso_week=str(iso_week),
            direction=direction.value,
            shortfall_minutes=written.shortfall_minutes,
            input_version=written.input_version,
        )
        return VerdictPass(
            weeks=1,
            to_feasible=int(written.feasible),
            to_infeasible=int(not written.feasible),
        )

    def _recorder(self) -> VerdictRecorder:
        return build_verdict_recorder(
            self._session,
            self._tenant_id,
            surface=VerdictSurface.MAINTAINER,
            session_mode_active=NO_SESSION_IS_OPEN,
        )
