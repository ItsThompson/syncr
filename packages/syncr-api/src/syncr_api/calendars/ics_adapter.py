"""The ICS adapter: a deep module whose internals absorb a hostile wire format.

One method, one argument, two values out. Everything a real feed does wrong is handled below
this line, and a caller sees only events with absolute instants and the sync state of the
attempt that produced them. That is the point of the shape: the anchor reconciler has no
reason to know that a publisher folds at 75 octets or names zones after Windows.

Three answers, three sync states, and **none of them raises**. A worker tick polling five
feeds must not lose four of them because one publisher is down, and a feed that half-works
must read as neither fully working nor fully broken.

The first return value is the fetch's whole tally rather than a bare list, and the reason is
``reparsed``. An unchanged feed, an unreachable feed, and a feed that genuinely holds no
events all produce an empty event list, and only the last of those means the caller should
remove the anchors it holds. A bare list cannot say which happened, so the caller would have
to reconstruct it from the sync state and would get it wrong for an empty feed whose
validator did not change.

**An excluded source is not fetched at all.** That decision belongs to the caller, which is
what renders an excluded source as excluded rather than as an error; this module would
otherwise spend a request to produce a number the read model discards.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.calendars.events import FetchOutcome
from syncr_api.calendars.feeds import FeedBody, FeedUnchanged
from syncr_api.calendars.ics_parse import parse_feed
from syncr_api.calendars.sync_state import (
    recorded_failure,
    recorded_success,
    recorded_unchanged,
)
from syncr_common.logging import get_logger
from syncr_common.metrics import measured

if TYPE_CHECKING:
    from syncr_api.calendars.feeds import FeedFetcher
    from syncr_api.calendars.records import CalendarSourceRecord, SyncStateRecord
    from syncr_api.core.clock import Clock
    from syncr_domain.intervals import Interval
    from syncr_domain.zones import ZoneProfile

_log = get_logger("syncr.calendars")

type IcsFetch = tuple[FetchOutcome, SyncStateRecord]


class IcsAdapter:
    """Fetch, parse, and expand one ICS feed across the projection horizon.

    The zone profile and the horizon are constructor dependencies rather than per-call
    arguments, because they belong to the tenant rather than to the source: one adapter is
    built per tenant per sync pass, and every source it reads resolves a floating time the
    same way.
    """

    def __init__(
        self, *, fetcher: FeedFetcher, profile: ZoneProfile, horizon: Interval, clock: Clock
    ) -> None:
        self._fetcher = fetcher
        self._profile = profile
        self._horizon = horizon
        self._clock = clock

    @measured("ics_adapter")
    async def fetch(self, source: CalendarSourceRecord) -> IcsFetch:
        """One attempt on ``source``: what it produced, and the sync state to store.

        The events and the rejections travel together, so a caller saves both in one write,
        and the sync state is returned whether the attempt succeeded or not.
        """
        now = self._clock()
        previous = source.sync_state
        answer = await self._fetcher.get(source.external_id, cursor=previous.cursor)
        identity = {"source_id": str(source.id), "tenant_id": str(source.tenant_id)}

        if isinstance(answer, FeedUnchanged):
            _log.info("calendars.ics.unchanged", **identity)
            return FetchOutcome(), recorded_unchanged(previous, at=now, cursor=answer.cursor)

        if isinstance(answer, FeedBody):
            outcome = parse_feed(answer.body, horizon=self._horizon, profile=self._profile)
            _log.info("calendars.ics.parsed", **identity, **outcome.as_log_fields())
            return outcome, recorded_success(outcome, at=now, cursor=answer.cursor)

        _log.warning(
            "calendars.ics.unreachable",
            **identity,
            reason=answer.reason,
            anchors_retained=previous.anchors_current,
        )
        return FetchOutcome(), recorded_failure(previous, at=now, reason=answer.reason)
