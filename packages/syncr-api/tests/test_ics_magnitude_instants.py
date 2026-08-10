"""What the magnitude corpus answers with, as instants rather than as an absence of faults.

:data:`tests.hostile_ics.HOSTILE_MAGNITUDES` crosses six starts with every extreme value, and the
adapter's suite asserts that each of the resulting bodies is ANSWERED: no fault escapes and every
component is accounted for as kept, rejected, or read and unplaced. That property holds just as
well when a value lands in the wrong hour, so it cannot see a reading move.

This module pins the reading itself.

The bodies carrying an ``RDATE`` are written out in full, span by span, because an extra date is
resolved against a zone the series does not necessarily name and a shift there is invisible in a
count. The rest of the corpus is pinned by three measured figures, which see a body start or stop
producing events and see a rejection change its reason, and which do NOT see an occurrence move
inside a body that keeps its count. Nothing here is a substitute for the by-hand instants in
``test_ics_parse``: it is the control that says the rest of the corpus answered the same way.

Every figure is measured against the corpus and written out by hand, so a deliberate change to a
reading re-measures it and states the difference.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

import pytest

from syncr_api.calendars.config import MALFORMED_VALUE, UNPARSEABLE_RECURRENCE
from syncr_api.calendars.ics_parse import parse_feed
from syncr_domain.intervals import Interval
from syncr_domain.zones import ZoneProfile
from tests.hostile_ics import HOSTILE_MAGNITUDES

HOME = ZoneProfile(home_zone="Europe/London")
HORIZON = Interval(datetime(2026, 2, 9, 0, 0, tzinfo=UTC), datetime(2026, 2, 23, 0, 0, tzinfo=UTC))

# The six bodies whose extreme value is an `RDATE`, one per start the corpus crosses it with, and
# what each answers with: the spans it produces, and the kinds it rejects.
#
# `RDATE:99991231T235959Z` is an instant at the end of representable time. It is outside the
# horizon from every one of these starts, so no start may produce an event for it, and the two
# starts whose own value cannot be resolved reject the component before recurrence is reached.
_RDATE_BODIES: dict[str, tuple[tuple[tuple[str, str], ...], tuple[str, ...]]] = {
    "an extra date past the end of time with a timed start": (
        (("2026-02-09T09:00:00+00:00", "2026-02-09T10:00:00+00:00"),),
        (),
    ),
    "an extra date past the end of time with a whole-day start": (
        (("2026-02-09T00:00:00+00:00", "2026-02-10T00:00:00+00:00"),),
        (),
    ),
    # 09:00 on Kiritimati, UTC+14, is 19:00 the previous day, which is before the horizon opens.
    "an extra date past the end of time with a zoned start": ((), ()),
    "an extra date past the end of time with a start at the first representable date": ((), ()),
    # 0001-01-01 on Pacific/Midway, UTC-11, is before the first representable instant.
    "an extra date past the end of time with a zoned start at the first representable date": (
        (),
        (MALFORMED_VALUE,),
    ),
    "an extra date past the end of time with a zoned start at the last representable date": (
        (),
        (),
    ),
}

# What the whole corpus answers with. Bodies that produce at least one event, spans across all of
# them, and one entry per rejection kind the corpus reaches.
_PRODUCING_BODIES = 34
_SPANS = 2126
_REJECTION_KINDS = {MALFORMED_VALUE: 62, UNPARSEABLE_RECURRENCE: 194}


@pytest.mark.parametrize("label", sorted(_RDATE_BODIES))
def test_a_body_carrying_an_extra_date_answers_with_these_instants(label: str) -> None:
    spans, kinds = _RDATE_BODIES[label]

    outcome = parse_feed(HOSTILE_MAGNITUDES[label], horizon=HORIZON, profile=HOME)

    produced = tuple(
        (event.interval.start.isoformat(), event.interval.end.isoformat())
        for event in sorted(outcome.events, key=lambda event: event.interval)
    )
    assert produced == spans
    assert tuple(sorted(item.kind for item in outcome.rejected)) == tuple(sorted(kinds))


def test_the_corpus_produces_these_counts_of_events_and_rejections() -> None:
    producing = 0
    spans = 0
    kinds: Counter[str] = Counter()

    for body in HOSTILE_MAGNITUDES.values():
        outcome = parse_feed(body, horizon=HORIZON, profile=HOME)
        kinds.update(item.kind for item in outcome.rejected)
        producing += bool(outcome.events)
        spans += len(outcome.events)

    assert (producing, spans) == (_PRODUCING_BODIES, _SPANS)
    assert dict(kinds) == _REJECTION_KINDS
