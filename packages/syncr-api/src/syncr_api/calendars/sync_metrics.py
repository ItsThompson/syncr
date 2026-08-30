"""The six calendar families beside the projection's three, and the two that are gauges.

``syncr_calendar_sync_duration_seconds``, ``syncr_calendar_sync_total``,
``syncr_calendar_events_read``, ``syncr_calendar_events_rejected_total``, ``syncr_anchors_current``
and ``syncr_source_staleness_seconds`` are named here. Nothing declared any of them, so the Calendar dashboard had
nothing to draw and ``SourceStale``, one of the twelve alerts, read a series no process produced.

Mirrors ``projection_metrics``, which is the sibling to match: two outcome values, the zeroes
observed as well as the counts, and every reason a rejection can carry named up front.

## Four of them are recorded per attempt, and two are read per tick

An attempt produces a duration, an outcome, a count of events read and a set of rejections, so those
four are recorded where the attempt happens.

Staleness and the anchor count are not attempt-shaped. A gauge set only when a source is polled
freezes at whatever the last poll saw, so both are set from stored state on a duty that runs whether
or not anything else happened. :func:`observed_state` is that reading, and it takes the source rows.

**A SOURCE THAT HAS NEVER SUCCEEDED IS MEASURED FROM WHEN THE USER ADDED IT.** Not from its last
attempt: every failed poll refreshes that instant, so a feed added with a wrong URL, a feed the
publisher took down before syncr ever read it, or a Google calendar whose grant was never valid
would report one poll interval of staleness forever and read as FRESHER than a healthy feed polled
twenty minutes ago. ``created_at`` is the one instant on the row that does not move, so a
never-synced source crosses the 24-hour threshold a day after it was added, which is the condition
the alert is stated over.

**AN EXCLUDED SOURCE PUBLISHES NO STALENESS AT ALL.** Not a growing reading, which is the
conclusion the obvious argument reaches and gets backwards. That argument runs: a poll-driven gauge
freezes at whatever the last poll saw, and an excluded source is never polled, so it would read as
fresh because nobody had looked. The premise is right and the conclusion is not. The user asked for
zero anchors from that source, so it going unread is the EXPECTED OUTCOME of their own instruction
rather than a fault, and `SourceStale` reads a maximum over sources precisely so one stale feed
fires it: a growing reading means the alert sticks firing forever on a source the user switched
off, reachable by one ``PATCH`` with ``included: false``. The record states the principle this
breaks, one property away: "the user asked for zero anchors from it, so a stale error from before
the exclusion must not render as a failure: that would be syncr reporting a problem the user already
resolved."

**The anchor count comes from the record's own property, not from the sync-state column.**
``anchor_count`` is zero for an excluded source whatever the last successful sync read, and
``anchors_current`` is the raw column. Reading the column draws seven anchors for a source
contributing none to any plan, which is the panel disagreeing with every other surface about one
source.

## A source the user removes or excludes takes its series with it, and so does a tenant

These two are labelled gauges set by iterating current rows, and nothing in the client library
removes a child. The worker is long-lived, so without :func:`_reconciled` a source the user deleted
would keep its last reading until the process restarted: if that reading was over 24 hours,
``SourceStale`` would fire forever on a source that no longer exists, which is an alert for a
condition the user cannot act on. The children are removed rather than the family cleared, so no
series goes momentarily absent and one tenant's reading cannot wipe another's.

**The two families reconcile against DIFFERENT sets, and that is the whole of the exclusion rule.**
Every source a tenant holds has an anchor count, including an excluded one, whose count is zero and
worth drawing. Only an INCLUDED source has a staleness worth alerting on, so an excluded source's
staleness child is removed by the same mechanism that removes a deleted source's.

**THE TENANT DIMENSION IS RECONCILED TOO, which is the same seam one level up.** A source is
reconciled when its tenant is observed, so a tenant that stops being enumerated is never visited
again and keeps every child at its last value forever. ``SourceStale`` reads a maximum across every
tenant, so one departed tenant with a stale source would fire it permanently, and no poll could ever
clear it. :func:`forget_tenants` closes that, and the duty calls it with the tenant list it just
read rather than with the tenants it managed to read: a tenant whose read RAISED is still a tenant,
and forgetting it would delete live series on a transient fault.

## Why the label is a source id and not a source name

A display name is the user's own words. The logger redacts a field called ``name`` for exactly that
reason, and an exposition is no safer a place for it: ``syncr_source_staleness_seconds{source_name=
"Kontron interviews"}`` discloses what a block title would. Identifiers are exported; content is
not. The label set is bounded by the sources a tenant holds, which is a handful.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, get_args

from prometheus_client import Counter, Gauge, Histogram

from syncr_api.calendars.config import CALENDAR_PROVIDERS, RejectionKind
from syncr_api.calendars.projection_metrics import FAILED, PROJECTION_OUTCOMES, SUCCEEDED
from syncr_common.metrics import REGISTRY

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable
    from datetime import datetime

    from syncr_api.calendars.events import FetchOutcome
    from syncr_api.calendars.records import CalendarSourceRecord
    from syncr_domain.identifiers import TenantId

# Which source ids each tenant's last reading published, per family, so a source the user removed or
# excluded can have its series removed rather than left at its last value. Keyed by family as well
# as tenant, because the two families reconcile against different sets.
_PUBLISHED: dict[tuple[str, TenantId], frozenset[str]] = {}

# The two family names, used as the reconciliation key so it cannot drift from the gauge it removes.
ANCHORS: Final = "syncr_anchors_current"
STALENESS: Final = "syncr_source_staleness_seconds"

# The same two values the projection uses, read from it rather than restated: a read that came back
# is a success whether the feed had changed or not, and a read that did not is a failure. An
# excluded source produces no attempt at all, so it is not a third value.
SYNC_OUTCOMES: Final = PROJECTION_OUTCOMES

# Every reason one component of a feed can be rejected for, read off the vocabulary itself so a kind
# added to it cannot be one this family has no series for.
REJECTION_KINDS: Final = tuple(get_args(RejectionKind.__value__))

SYNC_DURATION = Histogram(
    "syncr_calendar_sync_duration_seconds",
    "How long one attempt on one calendar source took, by provider and outcome.",
    labelnames=("provider", "outcome"),
    registry=REGISTRY,
)

SYNC_TOTAL = Counter(
    "syncr_calendar_sync_total",
    "Attempts on a calendar source, by provider and outcome.",
    labelnames=("provider", "outcome"),
    registry=REGISTRY,
)

EVENTS_READ = Histogram(
    "syncr_calendar_events_read",
    "Components one attempt read from a source, by provider. Zero is observed too.",
    labelnames=("provider",),
    # A timetable feed offers tens of components and a busy shared calendar a few hundred, so the
    # buckets straddle both rather than defaulting to a latency ladder measured in seconds.
    buckets=(0, 1, 5, 10, 25, 50, 100, 250, 500, 1000),
    registry=REGISTRY,
)

EVENTS_REJECTED = Counter(
    "syncr_calendar_events_rejected_total",
    "Components that produced no event, by provider and why.",
    labelnames=("provider", "reason"),
    registry=REGISTRY,
)

ANCHORS_CURRENT = Gauge(
    ANCHORS,
    "Anchors one source currently contributes to the plan. Zero for an excluded source.",
    labelnames=("source_id",),
    registry=REGISTRY,
)

SOURCE_STALENESS = Gauge(
    STALENESS,
    "Seconds since one INCLUDED source was last read successfully, by source identifier. "
    "An excluded source has no series: it is not polled by the user's own instruction.",
    labelnames=("source_id",),
    registry=REGISTRY,
)

# Which gauge each reconciliation key removes from, so a key cannot drift from the family it names.
_GAUGE_BY_FAMILY: Final[dict[str, Gauge]] = {
    ANCHORS: ANCHORS_CURRENT,
    STALENESS: SOURCE_STALENESS,
}


def seed_the_sync_families() -> None:
    """Export every provider-and-outcome series at zero before the first attempt.

    A labeled family does not exist until a label is used, so ``no sync has failed`` and ``this
    process has recorded nothing yet`` are the same reading until the vocabulary is exported. Both
    are answers an operator needs and they are different answers.

    The rejection family is deliberately NOT seeded across providers: its label set is the product
    of two vocabularies, and a series per provider per reason would export ten zeroes to say a feed
    parsed cleanly, which the ``events_read`` histogram already says.
    """
    for provider in CALENDAR_PROVIDERS:
        EVENTS_READ.labels(provider=provider)
        for outcome in SYNC_OUTCOMES:
            SYNC_TOTAL.labels(provider=provider, outcome=outcome)


def observed_attempt(
    source: CalendarSourceRecord, outcome: FetchOutcome, *, failed: bool, elapsed: float
) -> None:
    """Report one attempt on one source to the four attempt-shaped families.

    ``events_read`` is observed even when it is zero, because a histogram told only about non-empty
    reads makes a rate over it unreadable. The rejections are counted by their own kind, so a feed
    cut short by the read budget is not read as a recurrence the publisher should fix.

    The rejection counts come off the outcome's tally rather than off its sample, which is bounded
    per kind: iterating the sample would cap this counter at the sample size per attempt, so a feed
    refusing fifty thousand components would raise the same rate as one refusing fifteen.
    """
    labels = {"provider": source.provider, "outcome": FAILED if failed else SUCCEEDED}
    SYNC_DURATION.labels(**labels).observe(elapsed)
    SYNC_TOTAL.labels(**labels).inc()
    EVENTS_READ.labels(provider=source.provider).observe(outcome.events_read)
    for reason, count in outcome.rejections.counted.items():
        EVENTS_REJECTED.labels(provider=source.provider, reason=reason).inc(count)


def observed_state(
    tenant_id: TenantId, sources: Iterable[CalendarSourceRecord], *, now: datetime
) -> None:
    """Set the two state gauges from stored rows, for every source this tenant holds.

    Staleness is measured from the last SUCCESS, and from the instant the user ADDED the source when
    there has never been one: every other instant on the row moves when a poll fails, so a feed that
    has never worked would otherwise report one poll interval of staleness forever.

    An EXCLUDED source publishes no staleness at all. It is never polled, so a reading for it would
    grow without bound and stick the alert firing on a source the user switched off deliberately.

    A source this tenant no longer holds, and an included source that has since been excluded, both
    have their staleness child removed, so the maximum the alert reads cannot see either.
    """
    held = tuple(sources)
    published: dict[str, set[str]] = {ANCHORS: set(), STALENESS: set()}
    for source in held:
        source_id = str(source.id)
        # The record's own property rather than the sync-state column: zero for an excluded source,
        # whatever its last successful sync read, which is the figure every other surface uses.
        ANCHORS_CURRENT.labels(source_id=source_id).set(source.anchor_count)
        published[ANCHORS].add(source_id)
        if not source.included:
            continue
        SOURCE_STALENESS.labels(source_id=source_id).set(
            _staleness_seconds(source.sync_state.last_success_at, source.created_at, now=now)
        )
        published[STALENESS].add(source_id)
    for family, present in published.items():
        _reconciled(family, tenant_id, present)


def forget_tenants(present: Collection[TenantId]) -> None:
    """Remove every child published for a tenant this deployment no longer enumerates.

    The tenant end of the same reconciliation. :func:`_reconciled` prunes a tenant's sources when
    that tenant is observed, which leaves a tenant that stops being enumerated frozen at its last
    reading in a long-lived worker. ``SourceStale`` reads a maximum across tenants, so one departed
    tenant holding a stale source fires it forever with nothing able to clear it.

    Called with the tenants the duty ENUMERATED, not the ones it read successfully: a contained
    fault means a tenant went unobserved this tick, not that it is gone, and forgetting it would
    delete live series whenever a read raised.
    """
    kept = {str(one) for one in present}
    for family, tenant_id in [key for key in _PUBLISHED if str(key[1]) not in kept]:
        gauge = _GAUGE_BY_FAMILY[family]
        for source_id in _PUBLISHED.pop((family, tenant_id)):
            gauge.remove(source_id)


def _reconciled(family: str, tenant_id: TenantId, present: set[str]) -> None:
    """Remove every child of this family's gauge this tenant published before and no longer does.

    The published set is tracked here rather than read off the collector, because the client library
    exposes no public way to enumerate a family's children and a private attribute is not a
    contract. Kept per family and per tenant: the two families reconcile against different sets,
    because an excluded source keeps an anchor count of zero and loses its staleness entirely.
    """
    gauge = _GAUGE_BY_FAMILY[family]
    for source_id in _PUBLISHED.get((family, tenant_id), frozenset()) - present:
        gauge.remove(source_id)
    _PUBLISHED[(family, tenant_id)] = frozenset(present)


def _staleness_seconds(
    last_success_at: datetime | None, created_at: datetime, *, now: datetime
) -> float:
    """Seconds since this source was last read successfully, or since the user added it."""
    since = last_success_at if last_success_at is not None else created_at
    return max((now - since).total_seconds(), 0.0)


seed_the_sync_families()
