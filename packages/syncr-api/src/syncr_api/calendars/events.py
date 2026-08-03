"""The calendar package's public value types: what an adapter returns to a caller.

``RawEvent`` is the whole contract between an adapter and the anchor reconciler. It carries
absolute instants, so every provider quirk (a floating time, a `VALUE=DATE` day, a zone
alias) has already been resolved by the time one exists. That is what "callers never see
raw ICS" means concretely: there is no residue of the wire format on this shape.

``RejectedComponent`` is the other half of the same contract, and it is why a fetch does
not raise on a bad event. A feed that half-works must read as neither fully working nor
fully broken, so the rejections travel back alongside the events with enough detail to
render a panel: the component, the line it started on, and the class of the failure.

``FetchOutcome`` binds them together with the counts the source's panel reports. A count
that changes is how progress is reported in this product, so the counts are part of the
return rather than something a caller derives. It is ONE shape for both the parser and the
adapter: an unchanged feed is a fetch that read nothing, which is the same tally with
``reparsed`` unset, and a second near-identical struct would have to be kept in step by hand.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syncr_api.calendars.config import RejectionKind
    from syncr_domain.intervals import Interval


@dataclass(frozen=True, slots=True)
class RawEvent:
    """One occupied span a provider reported, with every zone question already answered.

    ``uid`` is the reconciliation key. A recurring series expands into many events sharing one
    ``series_uid``, and each occurrence's ``uid`` carries the original wall time of the occurrence
    it stands for, so an override that moved one keeps that occurrence's identity rather than
    becoming a second event.

    ``sequence`` is carried rather than dropped because it is what resolves a duplicate
    ``UID`` within one feed: the later revision wins.

    ``transparent`` is carried and **not acted on here**. A feed can declare that an event does not
    consume the user's time, which a holiday feed does for every whole day it publishes. Whether
    that makes it occupancy is a question about what an anchor MEANS, which the anchor-typing work
    owns; carrying the bit is what lets that work decide without reopening the parser.
    """

    uid: str
    series_uid: str | None
    title: str
    interval: Interval
    location: str | None
    sequence: int
    all_day: bool
    transparent: bool = False


@dataclass(frozen=True, slots=True)
class RejectedComponent:
    """One component that produced no event, and enough to say why on a panel.

    ``line`` is the line the component began on in the feed as delivered, before
    unfolding, because that is the line a publisher can look at. ``detail`` names the
    specific thing that was wrong (the zone that mapped to nothing, the property that
    would not parse) so the panel states a reason rather than a count alone.
    """

    kind: RejectionKind
    line: int
    component: str
    detail: str
    uid: str | None = None


@dataclass(frozen=True, slots=True)
class FetchOutcome:
    """Everything one fetch produced: the events, the rejections, and the counts.

    ``events_read`` counts the components the feed offered, which is a larger number than
    ``len(events)`` whenever a rejection or a duplicate happened and a smaller one whenever
    a recurrence expanded. Both are reported, because "12 events read, 48 anchors" and "12
    events read, 9 anchors, 3 rejected" are different stories about the same feed.

    The four discard counts account for every component the feed offered: each one was kept,
    rejected, discarded as a duplicate, discarded as cancelled, or applied as an override. A
    component that appeared in none of those would be the user's occupancy vanishing with no
    explanation anywhere.
    """

    events: tuple[RawEvent, ...] = ()
    rejected: tuple[RejectedComponent, ...] = ()
    events_read: int = 0
    duplicates_discarded: int = 0
    cancelled_discarded: int = 0
    # Whether this outcome came from reading a feed body. False for an unchanged feed and for
    # an unreachable one, and it is the ONLY thing that distinguishes those from a feed that
    # genuinely holds no events: all three carry an empty event list, and only one of them
    # means the caller should remove the anchors it holds.
    reparsed: bool = False

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)

    def as_log_fields(self) -> dict[str, int]:
        """This tally as log fields, under names the redactor does not eat.

        Redaction is by key name, so a count bound under a key containing ``title`` or
        ``name`` would render as ``[redacted]`` and the line would say nothing. Naming the
        fields on the tally rather than at each call site is what stops the next caller
        reintroducing that.
        """
        return {
            "events_read": self.events_read,
            "event_count": len(self.events),
            "rejected_count": self.rejected_count,
            "duplicate_count": self.duplicates_discarded,
            "cancelled_count": self.cancelled_discarded,
        }
