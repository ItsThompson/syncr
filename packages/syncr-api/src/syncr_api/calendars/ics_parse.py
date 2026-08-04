"""Reading a whole feed into events, and stating why each rejected component produced none.

What one component MEANS to another is :mod:`syncr_api.calendars.ics_series`. What this module owns
is the reading: the order of the passes, the per-feed bound, and the one rule the whole package is
built on.

**Nothing a feed can contain reaches a caller as an exception.** Three boundaries here catch
everything a component's own values can produce, through one tuple, so that is a property of this
module rather than a promise each ``except`` clause remembers. A raise instead of an answer costs a
whole tenant's sync pass: the worker wraps a tenant in one transaction, so the sync state already
written for every feed read before it rolls back too, and the request path answers 500 with no
``last_error`` at all.

**Two passes, because an override may be declared before the series it belongs to.** The first reads
every component and reports what will not parse; the second places what survived, with every
replacement in hand.

**No component's events are silently dropped.** One whose expansion would overrun the per-feed
bound is refused whole with a reason, rather than the total being sliced afterwards: a slice bounds
neither the memory nor the time it took to build, and it discards occupancy with nothing counting
the loss.

The panel's arithmetic closes over every component: kept, rejected, discarded as a duplicate,
discarded by a cancellation, applied as a replacement, or read and found to place nothing inside the
horizon.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import partial
from time import monotonic
from typing import TYPE_CHECKING

from syncr_api.calendars.config import (
    DETAIL_MAX_LENGTH,
    MAX_EVENTS_PER_FEED,
    MAX_PARSE_SECONDS,
    UNKNOWN_LINE,
)
from syncr_api.calendars.events import FetchOutcome, RejectedComponent
from syncr_api.calendars.ics_components import read_component
from syncr_api.calendars.ics_errors import (
    UNREPRESENTABLE,
    IcsRejection,
    ReadBudgetSpent,
    UnparseableRecurrence,
    as_rejection,
)
from syncr_api.calendars.ics_lines import VEVENT, events_in, parse_components
from syncr_api.calendars.ics_series import expand, place_replacement, sort_components, stranded

if TYPE_CHECKING:
    from collections.abc import Callable

    from syncr_api.calendars.config import RejectionKind
    from syncr_api.calendars.events import RawEvent
    from syncr_api.calendars.ics_components import EventComponent
    from syncr_api.calendars.ics_lines import Component
    from syncr_api.calendars.ics_series import OccurrenceKey, Placement
    from syncr_domain.intervals import Interval
    from syncr_domain.zones import ZoneProfile

# Everything a component's own values can produce that belongs on the panel rather than in a
# traceback. One tuple, used at every boundary below.
_REPORTABLE = (IcsRejection, *UNREPRESENTABLE)

# The line a feed-level rejection reports when the lexer gave up before naming one.

_FEED_COMPONENT = "VCALENDAR"


@dataclass(slots=True)
class _Collected:
    """Everything placing components produced, under the one bound that limits them.

    A struct rather than five locals, because the per-feed bound, the rejection, and the count of
    components that placed nothing are the same three steps for a master and for a stranded
    replacement, and a second copy of them is where the two would drift.
    """

    rejected: list[RejectedComponent]
    deadline: float = 0.0
    budget: float = 0.0
    events: list[RawEvent] = field(default_factory=list)
    applied: set[OccurrenceKey] = field(default_factory=set)
    expanded: set[str] = field(default_factory=set)
    placed: int = 0
    unplaced: int = 0
    remaining: int = MAX_EVENTS_PER_FEED

    def take(self, source: EventComponent, produce: Callable[[], Placement]) -> None:
        """Run one component's placement, or report why it produced nothing."""
        try:
            _require_time_left(deadline=self.deadline, budget=self.budget)
            placed = produce()
            _require_room_for(placed.events, remaining=self.remaining)
        except _REPORTABLE as error:
            self.rejected.append(_rejection(source.component, as_rejection(error), uid=source.uid))
            return
        # Recorded on the way through rather than inferred later, because "this series expanded" is
        # what decides the fate of a replacement nothing claimed, and a rejected master expands as
        # little as an absent one.
        self.expanded.add(source.uid)
        if placed.events:
            self.placed += 1
        else:
            self.unplaced += 1
        self.events.extend(placed.events)
        self.applied |= placed.applied
        self.remaining -= len(placed.events)


def parse_feed(
    body: str, *, horizon: Interval, profile: ZoneProfile, budget: float = MAX_PARSE_SECONDS
) -> FetchOutcome:
    """Every event ``body`` declares inside ``horizon``, plus the rejections it produced.

    ``budget`` is the seconds the whole parse may spend. It is a parameter rather than only a
    constant so a test can state a spent budget instead of waiting for one.
    """
    deadline = monotonic() + budget
    try:
        components = tuple(events_in(parse_components(body)))
    except _REPORTABLE as error:
        # The lexer refused the body itself, so there is no component to attribute this to and no
        # events to keep. One rejection for the whole feed, at the line it gave up on.
        return FetchOutcome(reparsed=True, rejected=(_feed_rejection(as_rejection(error)),))

    rejected: list[RejectedComponent] = []
    readable: list[EventComponent] = []
    for component in components:
        try:
            readable.append(read_component(component, profile))
        except _REPORTABLE as error:
            rejected.append(_rejection(component, as_rejection(error)))

    series = sort_components(readable)
    collected = _Collected(rejected=rejected, deadline=deadline, budget=budget)
    for master in series.masters:
        collected.take(master, partial(expand, master, series, horizon=horizon, profile=profile))

    # Which replacements found an occurrence is only known once every master has expanded, so the
    # ones that found none are accounted for after that rather than guessed at during the partition.
    reachable, superseded, unclaimed = stranded(
        series,
        frozenset(collected.applied),
        expanded=frozenset(collected.expanded),
        horizon=horizon,
        profile=profile,
    )
    for replacement in (*series.orphans, *reachable):
        collected.take(
            replacement,
            partial(place_replacement, replacement, horizon=horizon, profile=profile),
        )

    return FetchOutcome(
        reparsed=True,
        events=tuple(collected.events),
        rejected=tuple(collected.rejected),
        events_read=len(components),
        duplicates_discarded=series.duplicates,
        cancelled_discarded=series.cancelled + unclaimed,
        placed=collected.placed,
        overrides_applied=len(collected.applied),
        # A replacement no occurrence claimed is counted here rather than as a duplicate. Sometimes
        # another revision did supersede it, but often the rule was simply edited and nothing
        # replaced it, so "superseded" would be a claim the parser cannot support. "Read, and placed
        # nothing" is true in every case.
        unplaced=collected.unplaced + superseded,
    )


def _require_time_left(*, deadline: float, budget: float) -> None:
    """Refuse a component the feed no longer has time to expand, naming the bound.

    Checked between components rather than inside one, because a bound syncr owns cannot interrupt a
    third-party expander mid-call. That is the shape of the problem: one component's cost is not
    bounded, so what has to be bounded is how many of them a feed gets to spend.

    Every component past the deadline is rejected individually rather than the parse returning
    early, which is what keeps the panel's arithmetic closing: each one is accounted for, with a
    reason a reader can act on.

    ``monotonic`` rather than the injected clock seam, because this is a duration and not an
    instant: the seam exists so a service can be asked what it would do an hour from now, and a wall
    clock can step backwards under an NTP correction while a work budget must not.
    """
    if monotonic() < deadline:
        return
    message = (
        f"this feed spent its {budget:g} seconds of reading before reaching this component, "
        "so none of it was read"
    )
    raise ReadBudgetSpent(message)


def _require_room_for(produced: tuple[RawEvent, ...], *, remaining: int) -> None:
    """Refuse a component whose events would overrun the per-feed bound.

    Refused whole rather than truncated, which is also what keeps the component counted exactly
    once, in ``rejected``: a partial contribution would be both kept and refused.
    """
    if len(produced) <= remaining:
        return
    message = (
        f"this component expands to {len(produced)} events and only {remaining} of the "
        f"{MAX_EVENTS_PER_FEED} syncr reads per feed are left, so none of it was read"
    )
    raise UnparseableRecurrence(message)


def _detail(error: IcsRejection) -> str:
    """One rejection's detail, bounded because a feed can choose how long it is.

    Several messages quote a value the publisher supplied, or a converter's complaint about one, so
    the length of this string is the feed's to decide unless something decides it here. It is stored
    as JSONB on the sync state and served whole by the read route, so an unbounded detail is an
    unbounded write and an unbounded response.

    The full length is named rather than the text silently ending, so a reader can tell a long value
    from a truncated explanation.
    """
    stated = str(error)
    if len(stated) <= DETAIL_MAX_LENGTH:
        return stated
    return f"{stated[:DETAIL_MAX_LENGTH]}... ({len(stated)} characters in all)"


def _rejection(
    component: Component, error: IcsRejection, *, uid: str | None = None
) -> RejectedComponent:
    """The rejection this failure renders as, with the component and the line it began on."""
    kind: RejectionKind = error.kind
    return RejectedComponent(
        kind=kind,
        line=component.line,
        component=component.name or VEVENT,
        detail=_detail(error),
        uid=uid,
    )


def _feed_rejection(error: IcsRejection) -> RejectedComponent:
    """The rejection a body the lexer refused renders as.

    The line comes off the error rather than off a component, because the lexer gave up before any
    component closed and there is nothing to attribute it to.
    """
    kind: RejectionKind = error.kind
    return RejectedComponent(
        kind=kind,
        line=error.line or UNKNOWN_LINE,
        component=_FEED_COMPONENT,
        detail=_detail(error),
    )
