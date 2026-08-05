"""``ProjectionWriter``: make the write target match the live plan over the horizon, destructively.

This is the promise the whole calendar strategy rests on. Publishing an ICS feed for the user to
subscribe to takes 8 to 24 hours to reach a phone, which would delete adaptation, so syncr writes to
one calendar it owns through the provider API and reconciles it destructively instead.

```
project(horizon)
  ├── desired  = live plan blocks in the horizon, mapped to ProjectedEvent
  │              + one event per day segment for each off-plan period
  ├── existing = remote events in the horizon on the write target      (the adapter's)
  ├── diff by the stable syncr key                                     (the adapter's)
  └── ReconcileResult { inserted, patched, deleted, foreign_deleted, duration_ms }
```

**The tenant is on the repositories, not on the method.** The ticket states
``project(tenant_id, horizon)``; every repository this holds is already scoped to a tenant at
construction, and the boundary suite enforces that no scoped statement can be built without one. A
second statement of the tenant on the method could only ever disagree with the scope the statements
actually run under, so it is left off and the deviation is recorded here.

**The desired set is drawn from the horizon weeks' own plans.** A block belongs to the week its
start falls in, so a boundary-crossing Sunday-night span is emitted from that week alone. A week
with no live revision contributes nothing rather than raising: the plan horizon maintainer is what
brings a week into existence, and a projection that refused to run because next week has no plan
yet would stop this week's plan reaching the phone.

**A block whose week has left the horizon is no longer desired**, so the event on the target is
deleted on the next reconciliation. That is what the horizon being a window means, and it is the one
place a span crossing into the horizon from the week before it is affected: the sleep that began
last night is removed at local midnight when its week drops out. Stable rather than churning, and
stated here rather than left for a reader to discover from the counts.

**Nothing about the WRITE lives here.** The diff, the provider calls, the refusal and the failure
are the adapter's, because they are provider-specific and this is not.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.calendars.projected_events import desired_events
from syncr_api.offplan.segments import off_plan_segments
from syncr_api.plans.stored_documents import plan_document
from syncr_common.logging import get_logger
from syncr_common.metrics import measured

if TYPE_CHECKING:
    from syncr_api.calendars.adapters import CalendarWriter
    from syncr_api.calendars.projection import ProjectedEvent, ReconcileResult
    from syncr_api.calendars.records import CalendarSourceRecord
    from syncr_api.offplan.repository import OffPlanPeriodRepository
    from syncr_api.plans.repository import PlanRepository
    from syncr_domain.intervals import Interval
    from syncr_domain.plan import PlanDocument
    from syncr_domain.weeks import IsoWeek
    from syncr_domain.zones import ZoneProfile

_log = get_logger("syncr.calendars")


class ProjectionWriter:
    """Turns one tenant's live plan into the events on the calendar syncr owns."""

    def __init__(
        self,
        *,
        target: CalendarSourceRecord,
        adapter: CalendarWriter,
        revisions: PlanRepository,
        periods: OffPlanPeriodRepository,
        profile: ZoneProfile,
    ) -> None:
        self._target = target
        self._adapter = adapter
        self._revisions = revisions
        self._periods = periods
        self._profile = profile

    @measured("projection")
    async def project(self, horizon: Interval, weeks: tuple[IsoWeek, ...]) -> ReconcileResult:
        """Make the write target match the live plan over ``horizon``.

        ``weeks`` are the ISO weeks the horizon covers, in chronological order, computed by the
        caller from the same ``today`` and ``horizon_days`` the horizon itself is. Passed in rather
        than re-derived, so the span written over and the weeks read cannot disagree.

        Destructive: events syncr does not intend within the horizon are removed. Raises rather than
        answering when the target does not end up matching the plan.
        """
        desired = await self.intended(horizon, weeks)
        return await self._adapter.reconcile(self._target, desired)

    async def intended(self, horizon: Interval, weeks: tuple[IsoWeek, ...]) -> list[ProjectedEvent]:
        """Everything syncr means the target to hold over ``horizon``.

        Separate from the write so the desired set can be asserted without a provider, and so the
        reads all happen before the network call rather than interleaved with it.
        """
        documents = [document for week in weeks if (document := await self._live(week)) is not None]
        segments = off_plan_segments(
            await self._periods.for_span(horizon), horizon=horizon, profile=self._profile
        )
        return desired_events(documents, segments, horizon=horizon)

    async def _live(self, iso_week: IsoWeek) -> PlanDocument | None:
        """One week's live plan, or ``None`` when nothing has planned it yet.

        A week inside the horizon with no live revision is a hole the maintainer fills; this answers
        with nothing for it rather than raising, so one unplanned week cannot stop the weeks that
        are planned from reaching the phone.
        """
        revision = await self._revisions.latest(iso_week)
        if revision is None:
            _log.info(
                "calendars.projection.week_without_a_plan",
                tenant_id=str(self._target.tenant_id),
                iso_week=str(iso_week),
            )
            return None
        return plan_document(revision.document)
