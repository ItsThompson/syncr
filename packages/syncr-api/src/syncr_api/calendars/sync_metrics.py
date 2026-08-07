"""The six calendar families beside the projection's three, and the two that are gauges.

Section 18 names ``syncr_calendar_sync_duration_seconds``, ``syncr_calendar_sync_total``,
``syncr_calendar_events_read``, ``syncr_calendar_events_rejected_total``, ``syncr_anchors_current``
and ``syncr_source_staleness_seconds``. Nothing declared any of them, so the Calendar dashboard had
nothing to draw and ``SourceStale``, one of the twelve alerts, read a series no process produced.

Mirrors ``projection_metrics``, which is the sibling to match: two outcome values, the zeroes
observed as well as the counts, and every reason a rejection can carry named up front.

## Four of them are recorded per attempt, and two are read per tick

An attempt produces a duration, an outcome, a count of events read and a set of rejections, so those
four are recorded where the attempt happens.

Staleness and the anchor count are not attempt-shaped. A gauge set only when a source is polled
freezes at whatever the last poll saw, and an EXCLUDED source is never polled at all: the reading
would then say a feed was fresh because nobody had looked at it, which is precisely backwards for an
alert stated at 24 hours. So both are set from stored state on a duty that runs whether or not
anything else happened. :func:`observed_state` is that reading, and it takes the source rows.

**A SOURCE THAT HAS NEVER SUCCEEDED IS MEASURED FROM WHEN THE USER ADDED IT.** Not from its last
attempt: every failed poll refreshes that instant, so a feed added with a wrong URL, a feed the
publisher took down before syncr ever read it, or a Google calendar whose grant was never valid
would report one poll interval of staleness forever and read as FRESHER than a healthy feed polled
twenty minutes ago. ``created_at`` is the one instant on the row that does not move, so a
never-synced source crosses the 24-hour threshold a day after it was added, which is the condition
the alert is stated over.

## A source the user removes takes its series with it

These two are labelled gauges set by iterating current rows, and nothing in the client library
removes a child. The worker is long-lived, so without :func:`_forgotten` a source the user deleted
would keep its last reading until the process restarted: if that reading was over 24 hours,
``SourceStale`` would fire forever on a source that no longer exists, which is an alert for a
condition the user cannot act on. The children are removed rather than the family cleared, so no
series goes momentarily absent and one tenant's reading cannot wipe another's.

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
    from collections.abc import Iterable
    from datetime import datetime

    from syncr_api.calendars.events import FetchOutcome
    from syncr_api.calendars.records import CalendarSourceRecord
    from syncr_domain.identifiers import TenantId

# Which source ids each tenant's last reading published, so a source the user removed can have its
# series removed rather than left at its last value.
_PUBLISHED: dict[TenantId, frozenset[str]] = {}

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
    "syncr_anchors_current",
    "Anchors one source currently holds, by source identifier.",
    labelnames=("source_id",),
    registry=REGISTRY,
)

SOURCE_STALENESS = Gauge(
    "syncr_source_staleness_seconds",
    "Seconds since one source was last read successfully, by source identifier.",
    labelnames=("source_id",),
    registry=REGISTRY,
)


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
    """
    labels = {"provider": source.provider, "outcome": FAILED if failed else SUCCEEDED}
    SYNC_DURATION.labels(**labels).observe(elapsed)
    SYNC_TOTAL.labels(**labels).inc()
    EVENTS_READ.labels(provider=source.provider).observe(outcome.events_read)
    for rejection in outcome.rejected:
        EVENTS_REJECTED.labels(provider=source.provider, reason=rejection.kind).inc()


def observed_state(
    tenant_id: TenantId, sources: Iterable[CalendarSourceRecord], *, now: datetime
) -> None:
    """Set the two state gauges from stored rows, for every source this tenant holds.

    Staleness is measured from the last SUCCESS, and from the instant the user ADDED the source when
    there has never been one: every other instant on the row moves when a poll fails, so a feed that
    has never worked would otherwise report one poll interval of staleness forever.

    A source this tenant no longer holds has its two series removed, so a deleted source cannot go
    on contributing to the maximum the alert reads.
    """
    held = tuple(sources)
    for source in held:
        state = source.sync_state
        ANCHORS_CURRENT.labels(source_id=str(source.id)).set(state.anchors_current)
        SOURCE_STALENESS.labels(source_id=str(source.id)).set(
            _staleness_seconds(state.last_success_at, source.created_at, now=now)
        )
    _forgotten(tenant_id, {str(source.id) for source in held})


def _forgotten(tenant_id: TenantId, present: set[str]) -> None:
    """Remove the two series of every source this tenant published before and no longer holds.

    The published set is tracked here rather than read off the collector, because the client library
    exposes no public way to enumerate a family's children and a private attribute is not a
    contract. Kept per tenant, so one tenant's reading cannot remove another's series.
    """
    for source_id in _PUBLISHED.get(tenant_id, frozenset()) - present:
        ANCHORS_CURRENT.remove(source_id)
        SOURCE_STALENESS.remove(source_id)
    _PUBLISHED[tenant_id] = frozenset(present)


def _staleness_seconds(
    last_success_at: datetime | None, created_at: datetime, *, now: datetime
) -> float:
    """Seconds since this source was last read successfully, or since the user added it."""
    since = last_success_at if last_success_at is not None else created_at
    return max((now - since).total_seconds(), 0.0)


seed_the_sync_families()
