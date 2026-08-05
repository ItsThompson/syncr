"""One tenant's projection pass: the reconciliation, and what it records either way.

Separate from the duty that schedules it, because the two answer different questions. The duty asks
which tenants have work and contains one tenant's fault; this asks what one tenant's write does and
what is written down about it.

**The values a pass is against are the pass**, rather than five arguments threaded through five
methods. The session, the tenant, the operations it claimed and the instant it reads everything at
do not change while it runs, so they are the object and each method's signature carries only what
is its own: the target it is writing, the failure it is recording, the state it is storing.

**Everything here is one transaction, the caller's.** The claim is already committed when a pass
begins, so a worker that dies mid-reconciliation leaves its operations ``running`` for the reaper
rather than for nobody. Everything after it -- the reads, the token refresh the token source
performs, the write, the sync state and the operation transitions -- lands together, exactly as a
calendar poll's tenant pass does, so a projection can never be observed as succeeded with its target
looking untried.

That last point is a measured decision rather than a preference. An earlier shape kept the
reconciliation's session read-only to avoid holding a transaction across the network, and it lost
the token layer's record of a dead grant: ``record_refresh_failure`` writes through the session it
was built with, so with nothing to commit it, the one write that raises the loudest notice in the
product was rolled back. **The cost is a transaction open across up to the write deadline**, which
on a serial worker loop also bounds every other duty at ``tenants x WRITE_DEADLINE_SECONDS``. At
one tenant that is the trade as made; the shape that removes it is for the token layer to own a
committing session for its own failure record, which would let the reconciliation run outside a
transaction entirely.

**A tenant with no write target drains its queue and writes nothing.** There is no calendar to
project onto, by the user's own configuration, so each operation succeeds having done what it could:
the same answer a forced sync gives for an excluded source. No notice is raised, because a tenant
that has not designated a write target is not a tenant whose writes are failing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.calendars.config import GOOGLE
from syncr_api.calendars.horizons import read_horizon_days
from syncr_api.calendars.injection import build_write_target_adapter, read_zone_profile_of
from syncr_api.calendars.projection_errors import ProjectionFailed, ProjectionRefused
from syncr_api.calendars.projection_metrics import FAILED, SUCCEEDED, observed
from syncr_api.calendars.projection_state import (
    recorded_projection,
    recorded_projection_failure,
)
from syncr_api.calendars.projection_writer import ProjectionWriter
from syncr_api.calendars.repository import CalendarSourceRepository
from syncr_api.horizon.weeks import horizon_span, weeks_reaching_the_horizon
from syncr_api.offplan.repository import OffPlanPeriodRepository
from syncr_api.plans.repository import PlanRepository
from syncr_api.solving.lifecycle import OperationLifecycle
from syncr_api.solving.outcomes import Failed, Succeeded
from syncr_api.solving.repository import OperationRepository
from syncr_api.user_settings.zone_reading import local_date
from syncr_common.logging import get_logger

if TYPE_CHECKING:
    from datetime import datetime

    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_api.calendars.records import CalendarSourceRecord, SyncStateRecord
    from syncr_api.core.clock import Clock
    from syncr_api.solving.outcomes import Outcome
    from syncr_api.solving.records import OperationRecord
    from syncr_api.worker.main import WorkerContext
    from syncr_domain.identifiers import TenantId

_log = get_logger("syncr.calendars")

# Why nothing was written when the tenant has designated no write target. Not an error: the queue is
# drained and the operations succeed, because there is no calendar to project onto by the user's own
# configuration.
NO_WRITE_TARGET = (
    "no calendar is designated as the one syncr writes the plan to, so there was nothing to "
    "project onto"
)

# Why nothing was written when the designated calendar is one syncr cannot write to. Assigning the
# write-target role does not currently require a Google source, so an ICS feed can hold it and
# cannot be written to: a feed is published by somebody else and has no API to write through.
#
# A REFUSAL rather than a failure, because retrying cannot clear it: the provider of a source is
# immutable, so every attempt reaches the conclusion the first one did, and the repair is to
# designate a different calendar. Classified as a failure it would spend three attempts and two
# backoffs per plan change to say so, and would contradict the runbook's own table. Whether the role
# assignment should refuse it too is ticket 1301; this refusal has to exist either way, because a
# stored role predates any rule about assigning one.
UNWRITABLE_TARGET = (
    "the calendar designated as syncr's write target is a {provider} feed, and the plan can only "
    "be written to a Google calendar: a feed is published by somebody else and has no API to write "
    "through. Designate a Google calendar in Settings."
)


@dataclass(frozen=True, slots=True)
class TenantPass:
    """One tenant's projection pass, and the six values every step of it is against.

    Frozen, because none of them changes while a pass runs. ``now`` in particular is the instant the
    drain read once and handed down, so every row a pass writes carries it and a pass is
    reproducible.
    """

    context: WorkerContext
    session: AsyncSession
    tenant_id: TenantId
    claimed: tuple[OperationRecord, ...]
    now: datetime
    clock: Clock

    async def run(self, reads: httpx.AsyncClient, writes: httpx.AsyncClient) -> int:
        """Reconcile if there is a calendar to reconcile, and record the attempt either way.

        Answers 1 when a reconciliation was performed and 0 when there was nothing to perform one
        against, which is what the drain counts.
        """
        target = await self._sources().write_target()
        if target is None:
            await self._close(Succeeded())
            _log.info(
                "calendars.projection.skipped", **self.as_log_fields(), reason=NO_WRITE_TARGET
            )
            return 0
        if target.provider != GOOGLE:
            await self._stopped(
                target, ProjectionRefused(UNWRITABLE_TARGET.format(provider=target.provider))
            )
            return 0
        return await self._reconciled(target, reads, writes)

    def as_log_fields(self) -> dict[str, object]:
        """The two fields every line a pass emits carries, under names the redactor keeps."""
        return {"tenant_id": str(self.tenant_id), "operation_count": len(self.claimed)}

    async def _reconciled(
        self, target: CalendarSourceRecord, reads: httpx.AsyncClient, writes: httpx.AsyncClient
    ) -> int:
        """Read what the write needs, write it, and record the attempt either way.

        The horizon and the week list are derived from one ``today`` and one ``horizon_days``, so
        the span the calendar is reconciled over and the weeks whose plans are read cannot disagree
        about where the horizon ends.
        """
        profile = await read_zone_profile_of(self.session, self.tenant_id)
        horizon_days = await read_horizon_days(self._sources())
        today = local_date(self.now, profile.home_zone)
        horizon = horizon_span(today=today, horizon_days=horizon_days, zone=profile.home_zone)
        writer = ProjectionWriter(
            target=target,
            adapter=build_write_target_adapter(
                self.context.settings,
                self.session,
                self.tenant_id,
                reads=reads,
                writes=writes,
                profile=profile,
                horizon=horizon,
            ),
            revisions=PlanRepository(self.session, self.tenant_id),
            periods=OffPlanPeriodRepository(self.session, self.tenant_id),
            profile=profile,
        )
        try:
            result = await writer.project(
                horizon, weeks_reaching_the_horizon(today=today, horizon_days=horizon_days)
            )
        except ProjectionFailed as failure:
            await self._stopped(target, failure)
            return 0
        observed(result, outcome=SUCCEEDED)
        await self._record(target, recorded_projection(target.sync_state, at=self.now))
        _log.info(
            "calendars.projection.completed",
            **self.as_log_fields(),
            source_id=str(target.id),
            **result.as_log_fields(),
        )
        return 1

    async def _stopped(self, target: CalendarSourceRecord, failure: ProjectionFailed) -> None:
        """Record a reconciliation that did not finish: on the metric, the source, and every claim.

        The partial counts are observed, because those writes happened. The outcome is ``failed``
        whether the write was refused or attempted, because the consequence is the same and the
        alert that watches it must fire for both; the difference is the error code and the sentence.
        """
        observed(failure.applied, outcome=FAILED)
        await self._record(
            target,
            recorded_projection_failure(target.sync_state, at=self.now, reason=failure.reason),
            outcome=Failed(code=failure.code, message=str(failure)),
        )
        _log.warning(
            "calendars.projection.failed",
            **self.as_log_fields(),
            source_id=str(target.id),
            error_code=failure.code,
            **failure.applied.as_log_fields(),
        )

    async def _record(
        self,
        target: CalendarSourceRecord,
        state: SyncStateRecord,
        *,
        outcome: Outcome | None = None,
    ) -> None:
        """Write the attempt onto the write target and close every claimed operation, together.

        A target row deleted since the claim matches no row and writes nothing, which is the right
        answer: there is no source left to record an attempt on.
        """
        await self._sources().save_sync_state(target.id, state)
        await self._close(outcome or Succeeded())

    async def _close(self, outcome: Outcome) -> None:
        """Close every claimed operation with the outcome this pass reached."""
        lifecycle = OperationLifecycle(
            OperationRepository(self.session, self.tenant_id), self.clock
        )
        for operation in self.claimed:
            await lifecycle.finish(operation.id, outcome)

    def _sources(self) -> CalendarSourceRepository:
        return CalendarSourceRepository(self.session, self.tenant_id)
