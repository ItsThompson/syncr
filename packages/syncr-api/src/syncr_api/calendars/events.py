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
class RemoteCalendar:
    """One calendar an account holds, as the setup surface lists it for selection.

    ``calendar_id`` is the provider's own opaque identifier and becomes a source's
    ``external_id``, which is why it is carried rather than derived from the title: two calendars
    can share a title and neither can share an identifier.

    ``writable`` decides whether a calendar can be the write target at all. syncr reconciles the
    target destructively, so a calendar the account can only read is not a candidate, and knowing
    that at selection time beats a 403 on the first projection.
    """

    calendar_id: str
    display_name: str
    time_zone: str | None
    writable: bool
    primary: bool


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

    The counts account for every component the feed offered, and each is its own term because
    each is a different thing to have happened: one was kept, rejected, superseded by another
    component, discarded by a cancellation, applied as an override, or read and found to place
    nothing inside the horizon. **Every term is reported rather than derived**, because a term
    recomputed from the events cannot tell two components apart when both contribute events under
    one identity. A component in none of them would be the user's occupancy vanishing with no
    explanation anywhere, which is what the arithmetic exists to make impossible.
    """

    events: tuple[RawEvent, ...] = ()
    rejected: tuple[RejectedComponent, ...] = ()
    events_read: int = 0
    # Components another component superseded: a duplicate master or override the higher SEQUENCE
    # beat, and a repeated cancellation, which has no SEQUENCE question but still loses to the
    # first.
    duplicates_discarded: int = 0
    # Components a cancellation discarded, in any of its five forms. See `Series.cancelled`.
    cancelled_discarded: int = 0
    # Components that produced at least one event. Reported rather than derived from the events,
    # because two components can contribute events carrying ONE ``series_uid``: two orphaned
    # replacements of different occurrences are each placed on their own and both name the series
    # they belong to. Counting the events' series would read those two as one and leave the
    # arithmetic short.
    placed: int = 0
    # Override components applied against a master present in the same body, whether they replaced
    # an occurrence or suppressed one. Neither kept as an event of their own nor discarded, so the
    # accounting needs its own term for them or every override looks like a loss.
    overrides_applied: int = 0
    # Components read that produced no event inside the horizon: every occurrence falls outside it,
    # every one was excluded or cancelled, or the component is a replacement whose occurrence the
    # series it belongs to no longer produces. Not a loss and not an error, but it is counted,
    # because otherwise it is indistinguishable from occupancy that vanished.
    unplaced: int = 0
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
            "placed_count": self.placed,
            "override_count": self.overrides_applied,
            "unplaced_count": self.unplaced,
        }
