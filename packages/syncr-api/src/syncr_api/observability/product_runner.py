"""The scheduled job that computes the four product metrics, and the reads each one needs.

One duty on the worker loop. It reads only permanent tables: ``VerdictEvent``, ``BlockOutcome``,
``PlanRevision``, ``EditEvent`` and the off-plan spans are none of them pruned, which is why a
product metric can be recomputed from history rather than accumulated in a counter that a restart
resets.

## A ratio with no denominator is left ALONE, not set to zero

Three of the four are ratios, and a period can hold nothing to divide by: a fortnight with no
infeasibility, or one where the user resolved no proposal. Zero is the WORST possible score for all
three, so publishing it for an empty period would report total failure of the thing being measured.
The gauge keeps its previous reading instead, and the dashboard shows the trend it had. That is also
why the job never resets a gauge it could not compute.

## The period is four complete ISO weeks, and the boundary is the reason

The current week is excluded. A ratio over a week two days old moves every hour as the week fills,
so a panel trended by week would show a sawtooth rather than a trend, and the acceptance figure
would read lowest on Monday every week for no reason anyone can act on.

## Where the session statement comes from, and the one limit that remains

The engagement streak and the early-catch numerator both read ``VerdictEvent.session_mode_active``.
A client states whether a weekly session is open through a request header, and a solve-scheduling
operation carries a flag that widens to true when any requesting caller stated the session was open
and never narrows back; the solve's recorder writes that flag onto every verdict row it emits, so
both figures follow what callers actually stated rather than assuming silence. One attribution
limit remains: an episode opened by an act carrying no session flag counts as a late discovery,
because the ratio can only credit what the caller stated.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from prometheus_client import Counter

from syncr_api.accounts.repository import TenantRepository
from syncr_api.observability.churn import (
    acceptance_ratio,
    changed_block_count,
    overridden_count,
    repin_count,
)
from syncr_api.observability.early_catch import caught_early_over
from syncr_api.observability.engagement import streak_weeks
from syncr_api.observability.estimate import median_ape_by_area
from syncr_api.observability.product_gauges import (
    CAUGHT_EARLY_RATIO,
    ENGAGEMENT_STREAK,
    ESTIMATE_APE_MEDIAN,
    PROPOSAL_ACCEPTANCE_RATIO,
    REPINS_PER_WEEK,
)
from syncr_api.observability.wiring import build_product_reader
from syncr_common.logging import get_logger
from syncr_common.metrics import REGISTRY, measured

if TYPE_CHECKING:
    from datetime import datetime, timedelta

    from syncr_api.core.clock import Clock
    from syncr_api.observability.readings import ProductReading
    from syncr_api.worker.main import WorkerContext
    from syncr_domain.identifiers import TenantId

_log = get_logger("syncr.observability")

# A tenant whose computation raised. Counted for the reason every other contained-fault counter on
# this loop exists: the boundary means the decorated call no longer raises, so `measured` sees a
# healthy duty while four product gauges quietly stop moving.
TENANT_PRODUCT_FAILURES = Counter(
    "syncr_observability_product_failures_total",
    "Product-metric computations that raised for one tenant and were contained.",
    registry=REGISTRY,
)


class ProductMetricRunner:
    """One duty on the worker loop: recompute the four product metrics when due.

    A callable object rather than a closure, so the loop's name lookup finds a stable name for its
    failure metric and so a test can read when the computation is next due.

    The FIRST tick computes rather than schedules. These are reads, and a gauge absent for an hour
    after every restart is a gauge whose panel is empty exactly when someone has just deployed.
    """

    __name__ = "product_metrics"

    def __init__(self, *, interval: timedelta, clock: Clock) -> None:
        self._interval = interval
        self._clock = clock
        self._next_due_at: datetime | None = None

    @property
    def next_due_at(self) -> datetime | None:
        """When this runner will next do work, or ``None`` before its first tick."""
        return self._next_due_at

    async def __call__(self, context: WorkerContext) -> None:
        now = self._clock()
        if self._next_due_at is not None and now < self._next_due_at:
            return
        self._next_due_at = now + self._interval
        await self.compute(context, now=now)

    @measured("product_metrics")
    async def compute(self, context: WorkerContext, *, now: datetime) -> int:
        """Recompute and publish every product metric for every tenant. Returns tenants read."""
        async with context.database.sessionmaker() as reader:
            tenants = await TenantRepository(reader).list_ids()
        published = 0
        for tenant_id in tenants:
            published += await self._published_tenant(context, tenant_id, now=now)
        return published

    async def _published_tenant(
        self, context: WorkerContext, tenant_id: TenantId, *, now: datetime
    ) -> int:
        try:
            async with context.database.sessionmaker() as session:
                reader = await build_product_reader(session, tenant_id)
                reading = await reader.read(now=now)
        except Exception:  # noqa: BLE001 - one tenant's fault must not stop the others
            TENANT_PRODUCT_FAILURES.inc()
            _log.exception("observability.product.tenant_failed", tenant_id=str(tenant_id))
            return 0
        publish(tenant_id, reading)
        return 1


def publish(tenant_id: TenantId, reading: ProductReading) -> None:
    """Set the four families from one tenant's reading.

    Separated from the read so the arithmetic and the publication are testable apart.

    **A ratio with no denominator is left ALONE, not set to zero.** Zero is the worst possible score
    for all three ratios here, so publishing it for a period that held nothing to divide by would
    report total failure of the thing being measured every time the user took a week off. The gauge
    keeps the reading it had and the panel keeps the trend it had.

    The streak and the re-pin count are always published, because both are counts rather than
    ratios: zero re-pins is the best possible week and a zero streak is the honest reading of a user
    who has stopped.
    """
    tenant = str(tenant_id)

    for area_id, error in median_ape_by_area(reading.estimates).items():
        ESTIMATE_APE_MEDIAN.labels(tenant=tenant, area=str(area_id)).set(error)

    caught_early = caught_early_over(reading.verdict_history_by_week, period=reading.period)
    if caught_early is not None:
        CAUGHT_EARLY_RATIO.labels(tenant=tenant).set(caught_early)

    accepted = sum(
        changed_block_count(live, candidate) for live, candidate in reading.approved_diffs
    )
    acceptance = acceptance_ratio(
        accepted=accepted,
        overridden=overridden_count(edit.binding.origin for edit in reading.edits),
    )
    if acceptance is not None:
        PROPOSAL_ACCEPTANCE_RATIO.labels(tenant=tenant).set(acceptance)

    repinned = repin_count((edit.iso_week, edit.binding) for edit in reading.edits)
    REPINS_PER_WEEK.labels(tenant=tenant).set(repinned / reading.measurement_weeks)

    ENGAGEMENT_STREAK.labels(tenant=tenant).set(streak_weeks(reading.weeks_newest_first))
