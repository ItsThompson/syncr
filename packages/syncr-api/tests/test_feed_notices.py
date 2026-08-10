"""The stale-feed panel the api composes, and the days it says are in doubt.

Every claim here is derived from an artifact rather than restated. Which conditions can make a feed
stale comes from ``SOURCE_STATES``; which role owns the failure comes from ``CALENDAR_ROLES``; the
sentence about retained anchors is the one ``sync_state`` writes; and what survives comes from the
single list the composer declares. A hand-typed phrase asserted as a substring would pass while the
composer said something else, and the enumeration of a predicate's inputs is the shape this epic has
found wrong every time it was checked.

Notice identity is asserted by full equality, never by containment. One identifier is a prefix of
another, and a containment check then rests on a delimiter nothing documents.
"""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Final
from uuid import uuid4

import pytest

from syncr_api.calendars import schemas as calendar_schemas
from syncr_api.calendars.config import (
    ANCHOR_SOURCE,
    CALENDAR_ROLES,
    ERROR,
    EXCLUDED,
    HORIZON_DAYS_MIN,
    ICS,
    NEVER_SYNCED,
    OK,
    SOURCE_STATES,
    STALE_AFTER,
    SYNC_INTERVAL,
    WRITE_TARGET,
)
from syncr_api.calendars.feed_notices import (
    ANCHORS_RETAINED,
    FEED_STALE,
    FEED_STILL_WORKS,
    SETTINGS_SCREEN,
    SOLVING_STILL_WORKS,
    StaleFeedReading,
    failing_since,
    is_feed_stale,
    markable_span,
    stale_feed_notices,
)
from syncr_api.calendars.records import CalendarSourceRecord, SyncStateRecord
from syncr_api.calendars.sync_state import RETAINED_NOTICE, recorded_failure
from syncr_api.core.notices import AMBER, PANEL
from syncr_api.core.schemas import WireModel
from syncr_api.google_account.notices import stated_duration
from syncr_domain.intervals import Interval, IntervalError
from syncr_domain.zones import TravelOverride, ZoneProfile

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from syncr_api.calendars.config import SourceState
    from syncr_api.calendars.records import CalendarSourceId
    from syncr_api.core.notices import Notice

# A Monday afternoon, so "earlier today" is a real instant rather than a boundary case.
NOW: Final = datetime(2026, 2, 9, 14, 0, tzinfo=UTC)
TODAY: Final = date(2026, 2, 9)

LONDON: Final = ZoneProfile(home_zone="Europe/London")
HORIZON: Final = Interval(NOW, NOW + timedelta(days=14))

WELL_PAST = NOW - STALE_AFTER - timedelta(hours=1)
WELL_INSIDE = NOW - STALE_AFTER + timedelta(hours=1)

FEED_DID_NOT_ANSWER = "The feed did not answer."


def failed(*, since: datetime | None, at: datetime = NOW) -> SyncStateRecord:
    """A failing sync state written by the writer that owns the sentence about retained anchors."""
    return recorded_failure(
        SyncStateRecord(last_success_at=since, last_attempt_at=since),
        at=at,
        reason=FEED_DID_NOT_ANSWER,
    )


def source(
    *,
    included: bool = True,
    role: str = ANCHOR_SOURCE,
    created_at: datetime = WELL_PAST,
    display_name: str = "University timetable",
    sync_state: SyncStateRecord | None = None,
) -> CalendarSourceRecord:
    return CalendarSourceRecord(
        id=uuid4(),
        tenant_id=uuid4(),
        provider=ICS,
        role=role,  # type: ignore[arg-type]  # a role is a case under test
        display_name=display_name,
        external_id="https://example.ac.uk/timetable.ics",
        included=included,
        horizon_days=None,
        created_at=created_at,
        sync_state=sync_state if sync_state is not None else failed(since=WELL_PAST),
    )


# One source per state the read model can report, so the enumeration below is the artifact's own
# rather than a list of the cases somebody happened to think of. Each entry is asserted to really
# BE in the state it is filed under, and the set is asserted to be complete.
_IN_STATE: Final[Mapping[SourceState, Callable[[], CalendarSourceRecord]]] = {
    OK: lambda: source(sync_state=SyncStateRecord(last_success_at=WELL_PAST, last_attempt_at=NOW)),
    ERROR: lambda: source(sync_state=failed(since=WELL_PAST)),
    EXCLUDED: lambda: source(included=False, sync_state=failed(since=WELL_PAST)),
    NEVER_SYNCED: lambda: source(sync_state=SyncStateRecord()),
}

# The only state a stale feed can be in. Every other member of the artifact answers false, and the
# test below reads the members rather than this one name.
THE_STALE_STATE: Final = ERROR


class FakeAnchorStarts:
    """When each source's commitments begin, filtered by the span the reading asks for.

    The span filter is applied here rather than assumed, so a test that expects a day to be left out
    is testing the span the composer computed and not this double's convenience.
    """

    def __init__(
        self, starts: Mapping[CalendarSourceId, tuple[datetime, ...]] | None = None
    ) -> None:
        self.starts = dict(starts or {})
        self.asked: list[tuple[CalendarSourceId, Interval]] = []

    async def start_instants_for_source(
        self, source_id: CalendarSourceId, *, span: Interval
    ) -> tuple[datetime, ...]:
        self.asked.append((source_id, span))
        held = self.starts.get(source_id, ())
        return tuple(sorted(at for at in held if span.start <= at < span.end))


def reading(
    starts: Mapping[CalendarSourceId, tuple[datetime, ...]] | None = None,
    *,
    profile: ZoneProfile = LONDON,
    horizon: Interval = HORIZON,
) -> tuple[StaleFeedReading, FakeAnchorStarts]:
    anchors = FakeAnchorStarts(starts)
    return StaleFeedReading(anchors, profile=profile, horizon=horizon), anchors


def only(notices: tuple[Notice, ...]) -> Notice:
    assert len(notices) == 1, f"expected one notice, got {len(notices)}"
    return notices[0]


# --------------------------------------------------------------------------------
# What makes a feed stale, enumerated from the artifact
# --------------------------------------------------------------------------------


def test_every_state_the_read_model_can_report_has_a_case_here() -> None:
    # The completeness check for the mapping above. A fifth member added to the artifact would
    # otherwise leave its answer untested while every existing case still passed.
    assert set(_IN_STATE) == set(SOURCE_STATES)


@pytest.mark.parametrize("state", sorted(SOURCE_STATES))
def test_each_case_is_really_in_the_state_it_is_filed_under(state: SourceState) -> None:
    # Without this the enumeration above could file a healthy row under `error` and the test that
    # follows would pass for the wrong reason.
    assert _IN_STATE[state]().state == state


@pytest.mark.parametrize("state", sorted(SOURCE_STATES))
def test_only_a_failing_source_can_be_stale(state: SourceState) -> None:
    # The whole enumeration in one assertion: exactly one member of the artifact answers true, and
    # the members are read from the artifact rather than listed. An excluded source is the case
    # worth naming: it IS failing and IS past the threshold, and it answers false because the user
    # asked for zero anchors from it.
    assert is_feed_stale(_IN_STATE[state](), now=NOW) is (state == THE_STALE_STATE)


@pytest.mark.parametrize("role", sorted(CALENDAR_ROLES))
def test_only_an_anchor_source_raises_a_stale_feed_notice(role: str) -> None:
    # The write target's `last_error` records a failed PROJECTION, which already raises a banner and
    # a panel of its own. A second notice for one condition is how a reader learns to ignore both.
    failing = source(role=role, sync_state=failed(since=WELL_PAST))

    assert is_feed_stale(failing, now=NOW) is (role == ANCHOR_SOURCE)


# --------------------------------------------------------------------------------
# The threshold, and the feed that has never succeeded
# --------------------------------------------------------------------------------


def test_the_threshold_outlasts_a_missed_poll() -> None:
    # The one property of the figure that is not a product opinion, and it is derived from the other
    # constant rather than restated: a threshold at or under the poll interval turns a single missed
    # poll into a notice, which is the noise the figure exists to avoid. Nothing here asserts that
    # the figure is twelve hours; pinning that would be the guard the client's own quoted 12 was.
    assert STALE_AFTER > SYNC_INTERVAL


def test_a_feed_failing_for_less_than_the_threshold_raises_nothing() -> None:
    assert is_feed_stale(source(sync_state=failed(since=WELL_INSIDE)), now=NOW) is False


def test_the_threshold_is_exclusive_at_its_own_boundary() -> None:
    # Stated against the constant rather than against twelve hours, so moving the server's figure
    # moves this test with it instead of reddening it.
    at_the_boundary = source(sync_state=failed(since=NOW - STALE_AFTER))
    one_second_past = source(sync_state=failed(since=NOW - STALE_AFTER - timedelta(seconds=1)))

    assert is_feed_stale(at_the_boundary, now=NOW) is False
    assert is_feed_stale(one_second_past, now=NOW) is True


def test_a_feed_that_has_never_succeeded_raises_on_its_first_failure() -> None:
    # Added moments ago and failing on its first poll. There is no last success to be within the
    # threshold of, so waiting would leave a feed added with a wrong address silent for half a day.
    brand_new = source(created_at=NOW - timedelta(minutes=1), sync_state=failed(since=None))

    assert is_feed_stale(brand_new, now=NOW) is True


def test_the_age_of_a_feed_that_never_succeeded_is_measured_from_when_it_was_added() -> None:
    # The two instants are made to differ by days so a reading from the wrong one is a different
    # sentence rather than the same one: the last attempt is refreshed by every failed poll, and an
    # age measured from it would report the same few minutes of staleness forever.
    added = NOW - timedelta(days=3)
    polled_a_minute_ago = source(
        created_at=added, sync_state=failed(since=None, at=NOW - timedelta(minutes=1))
    )

    assert failing_since(polled_a_minute_ago) == added
    raised = only(stale_feed_notices([polled_a_minute_ago], {}, now=NOW))
    assert raised.since == added
    assert stated_duration(NOW - added) in raised.detail
    assert stated_duration(timedelta(minutes=1)) not in raised.detail


def test_the_age_of_a_feed_that_has_succeeded_is_measured_from_that_success() -> None:
    succeeded = NOW - timedelta(days=2)
    failing = source(created_at=NOW - timedelta(days=30), sync_state=failed(since=succeeded))

    assert failing_since(failing) == succeeded
    raised = only(stale_feed_notices([failing], {}, now=NOW))
    assert raised.since == succeeded
    assert stated_duration(NOW - succeeded) in raised.detail


# --------------------------------------------------------------------------------
# What the notice states
# --------------------------------------------------------------------------------


def test_the_panel_is_raised_at_panel_volume() -> None:
    # Volume and pigment are asserted separately, because one assertion over both cannot say which
    # of them moved: volume is WHERE it renders and pigment is WHAT KIND it is.
    assert only(stale_feed_notices([source()], {}, now=NOW)).volume == PANEL


def test_the_panel_is_amber_because_nothing_is_broken() -> None:
    # Amber rather than oxide: the day is complete as far as syncr knew, and what has stopped is
    # learning about changes to it. Oxide is for the plan not reaching the calendar at all.
    assert only(stale_feed_notices([source()], {}, now=NOW)).pigment == AMBER


def test_the_panel_offers_no_action_because_a_publishers_outage_has_no_repair() -> None:
    # A feed that stopped answering is the publisher's to fix, so there is nothing for this reader
    # to press. A notice must not offer a repair the product cannot perform.
    assert only(stale_feed_notices([source()], {}, now=NOW)).action is None


def test_the_surviving_capabilities_do_not_depend_on_the_write_targets_health() -> None:
    # This module reads the failing feed and its anchors, and nothing about the calendar the plan is
    # written to. A stored write target that cannot be written to has no demotion path in this
    # product, so a sentence claiming the plan still reaches the calendar would promise both a
    # capability that may not hold and a remedy that answers 409. What it says has to be true
    # whatever the write target is doing, which is what composing it twice asserts.
    stale = source()
    failing_target = source(
        role=WRITE_TARGET, display_name="syncr plan", sync_state=failed(since=WELL_PAST)
    )

    alone = only(stale_feed_notices([stale], {}, now=NOW))
    beside = only(stale_feed_notices([stale, failing_target], {}, now=NOW))

    assert alone.still_works == beside.still_works
    assert alone.detail == beside.detail


def test_the_notice_names_what_survives_from_the_one_list_that_declares_it() -> None:
    # Membership by identity of each named constant, not just equality against the tuple: an
    # assertion only against FEED_STILL_WORKS moves with the tuple, so dropping a member from it
    # would leave the notice silent about the retained anchors and this test green.
    raised = only(stale_feed_notices([source()], {}, now=NOW))

    assert ANCHORS_RETAINED in raised.still_works
    assert SOLVING_STILL_WORKS in raised.still_works
    assert raised.still_works == list(FEED_STILL_WORKS)
    assert raised.unavailable == ["Reading new commitments from University timetable"]


def test_the_notice_carries_the_retained_and_possibly_stale_sentence_the_failure_wrote() -> None:
    # The referent resolves: RETAINED_NOTICE is the constant the sync-state writer appends to every
    # failed read, so this asserts the composer carried that sentence through rather than that some
    # phrase happens to appear. Repeating the sentence in the composer would state one fact twice.
    failing = source(sync_state=failed(since=WELL_PAST))

    raised = only(stale_feed_notices([failing], {}, now=NOW))

    assert RETAINED_NOTICE in raised.detail
    assert failing.sync_state.last_error is not None
    assert raised.detail.startswith(failing.sync_state.last_error)


def test_the_notice_names_the_affected_source_by_full_identity() -> None:
    one, two = source(display_name="Timetable"), source(display_name="Lectures")

    raised = stale_feed_notices([one, two], {}, now=NOW)

    assert [notice.id for notice in raised] == [f"{FEED_STALE}.{one.id}", f"{FEED_STALE}.{two.id}"]
    assert [notice.scope and notice.scope.source_id for notice in raised] == [
        str(one.id),
        str(two.id),
    ]
    assert [notice.title for notice in raised] == [
        "Timetable could not be read",
        "Lectures could not be read",
    ]


def test_the_notice_is_scoped_to_the_screen_that_manages_the_source() -> None:
    raised = only(stale_feed_notices([source()], {}, now=NOW))

    assert raised.scope is not None
    assert raised.scope.screen == SETTINGS_SCREEN


def test_a_healthy_source_beside_a_stale_one_raises_nothing_of_its_own() -> None:
    healthy = _IN_STATE[OK]()
    stale = source()

    raised = stale_feed_notices([healthy, stale], {}, now=NOW)

    assert [notice.scope and notice.scope.source_id for notice in raised] == [str(stale.id)]


# --------------------------------------------------------------------------------
# The days the notice names
# --------------------------------------------------------------------------------


async def test_the_notice_names_the_days_the_feeds_commitments_begin_on() -> None:
    stale = source()
    read, _ = reading({stale.id: (NOW + timedelta(days=1), NOW + timedelta(days=3))})

    raised = only(await read.of([stale], now=NOW))

    assert raised.scope is not None
    assert raised.scope.dates == ["2026-02-10", "2026-02-12"]


async def test_the_days_are_named_earliest_first() -> None:
    # Its own assertion rather than a clause of the completeness test above, so reversing the order
    # and dropping a day are two different reds instead of one.
    stale = source()
    read, _ = reading(
        {
            stale.id: (
                NOW + timedelta(days=1),
                NOW + timedelta(days=3),
                NOW + timedelta(days=5),
            )
        }
    )

    raised = only(await read.of([stale], now=NOW))

    assert raised.scope is not None
    assert raised.scope.dates == sorted(raised.scope.dates)


async def test_two_commitments_on_one_day_name_that_day_once() -> None:
    stale = source()
    morning, evening = NOW + timedelta(days=1), NOW + timedelta(days=1, hours=6)
    read, _ = reading({stale.id: (morning, evening)})

    raised = only(await read.of([stale], now=NOW))

    assert raised.scope is not None
    assert raised.scope.dates == ["2026-02-10"]


async def test_a_commitment_is_in_doubt_on_the_day_it_begins_in() -> None:
    # 23:30 London on the 10th, running into the 11th. It belongs to the day it started in, which
    # is the reading every other day-shaped read in this product uses.
    stale = source()
    read, _ = reading({stale.id: (datetime(2026, 2, 10, 23, 30, tzinfo=UTC),)})

    raised = only(await read.of([stale], now=NOW))

    assert raised.scope is not None
    assert raised.scope.dates == ["2026-02-10"]


async def test_today_is_in_doubt_even_when_its_commitments_are_already_past() -> None:
    # The span starts at local midnight rather than at `now`. A reader looking at today has already
    # had the morning, and a span starting at the current instant would leave today off the list
    # while the day plainly holds the feed's commitments.
    stale = source()
    this_morning = NOW - timedelta(hours=5)
    read, _ = reading({stale.id: (this_morning,)})

    raised = only(await read.of([stale], now=NOW))

    assert raised.scope is not None
    assert raised.scope.dates == [TODAY.isoformat()]


async def test_a_day_already_gone_is_not_named() -> None:
    stale = source()
    read, _ = reading({stale.id: (NOW - timedelta(days=1),)})

    raised = only(await read.of([stale], now=NOW))

    assert raised.scope is not None
    assert raised.scope.dates == []


async def test_a_day_past_the_horizon_is_not_named() -> None:
    stale = source()
    read, _ = reading({stale.id: (HORIZON.end + timedelta(days=1),)})

    raised = only(await read.of([stale], now=NOW))

    assert raised.scope is not None
    assert raised.scope.dates == []


async def test_a_stale_feed_that_fed_no_day_ahead_still_raises_naming_no_day() -> None:
    # The feed is still failing, so silence would be the degraded-state-looks-healthy failure this
    # notice exists to close. What it must not claim is that a day is in doubt.
    stale = source()
    read, _ = reading({})

    raised = only(await read.of([stale], now=NOW))

    assert raised.scope is not None
    assert raised.scope.dates == []


async def test_a_healthy_tenant_costs_no_anchor_read() -> None:
    read, anchors = reading({})

    assert await read.of([_IN_STATE[OK]()], now=NOW) == ()
    assert anchors.asked == []


async def test_only_the_stale_feeds_anchors_are_read() -> None:
    healthy, stale = _IN_STATE[OK](), source()
    read, anchors = reading({})

    await read.of([healthy, stale], now=NOW)

    assert [source_id for source_id, _ in anchors.asked] == [stale.id]


# --------------------------------------------------------------------------------
# The span the days are read over
# --------------------------------------------------------------------------------


def test_the_span_runs_from_local_midnight_today_to_the_horizon() -> None:
    span = markable_span(now=NOW, profile=LONDON, horizon=HORIZON)

    assert span == Interval(datetime(2026, 2, 9, 0, 0, tzinfo=UTC), HORIZON.end)


def test_todays_date_is_read_in_the_home_zone_and_its_start_in_the_zone_active_on_it() -> None:
    # Two zones, one question each, and reading either with the other's zone is wrong. The home zone
    # decides WHICH DATE today is, because the date is what selects a travel override and reading it
    # in the override's own zone would need the answer before it could be computed. The zone active
    # on that date then decides WHEN it began.
    on_the_ninth = date(2026, 2, 9)
    travelling = ZoneProfile(
        home_zone="Europe/London",
        travel_overrides=(TravelOverride(on_the_ninth, on_the_ninth, "Pacific/Auckland"),),
    )
    late = datetime(2026, 2, 9, 23, 30, tzinfo=UTC)

    span = markable_span(
        now=late, profile=travelling, horizon=Interval(late, late + timedelta(days=14))
    )

    # Auckland is thirteen hours ahead in February, so the ninth there began on the eighth in UTC.
    # Read in Auckland the instant would have been the TENTH in London, whose midnight is later than
    # `now` and would have taken the whole of the ninth off the list.
    assert span.start == datetime(2026, 2, 8, 11, 0, tzinfo=UTC)


def test_a_span_whose_local_midnight_falls_after_the_horizon_ends_still_resolves() -> None:
    # The one-day horizon is the floor the schema allows, and 26 hours of zone swing is reachable:
    # the home zone decides which date today is, and the override decides when that date began.
    # Taking the earlier of the two ends is what keeps this an interval rather than a 500.
    tomorrow = date(2026, 2, 10)
    travelling = ZoneProfile(
        home_zone="Pacific/Kiritimati",
        travel_overrides=(TravelOverride(tomorrow, tomorrow, "Etc/GMT+12"),),
    )
    now = datetime(2026, 2, 9, 11, 0, tzinfo=UTC)
    horizon = Interval(now, now + timedelta(days=HORIZON_DAYS_MIN))

    span = markable_span(now=now, profile=travelling, horizon=horizon)

    assert span == Interval(now, horizon.end)
    # The control: the unguarded expression this line stands in for is not an interval at all.
    with pytest.raises(IntervalError):
        Interval(datetime(2026, 2, 10, 12, 0, tzinfo=UTC), horizon.end)


# --------------------------------------------------------------------------------
# The threshold does not reach the wire
# --------------------------------------------------------------------------------

# What a threshold field would be called. A name rather than a value, because the defect the ticket
# forbids is a figure a client can read and apply, whatever number it happens to hold.
THRESHOLD_SHAPED = ("stale", "threshold")


def threshold_shaped_fields(shape: type[WireModel]) -> list[str]:
    """Every field of ``shape`` whose name reads as a staleness threshold a client could apply."""
    return [
        name
        for name in shape.model_fields
        if any(word in name.lower() for word in THRESHOLD_SHAPED)
    ]


def calendar_wire_shapes() -> list[type[WireModel]]:
    """Every wire shape the calendar routes exchange, read off the module rather than listed."""
    return [
        member
        for _, member in inspect.getmembers(calendar_schemas, inspect.isclass)
        if issubclass(member, WireModel)
        and member is not WireModel
        and member.__module__ == calendar_schemas.__name__
    ]


def test_the_reading_of_the_calendar_wire_shapes_finds_something_to_read() -> None:
    # The control. A reading that found no shapes would report every rule below as satisfied while
    # testing nothing, which is the guard-that-cannot-fail this suite exists to refuse.
    found = calendar_wire_shapes()

    assert calendar_schemas.SyncStateResponse in found
    assert len(found) > 1


def test_no_calendar_wire_shape_carries_a_staleness_threshold() -> None:
    # `SyncStateResponse` is where the input ticket asked for it, and the neighbours are where the
    # same defect would reopen. A field here is a figure every surface can apply for itself, which
    # is three answers to one question.
    offending = {
        shape.__name__: threshold_shaped_fields(shape)
        for shape in calendar_wire_shapes()
        if threshold_shaped_fields(shape)
    }

    assert offending == {}


def test_the_reading_reports_a_threshold_field_that_is_planted() -> None:
    # The positive control for the rule above, so a reading that could not see a threshold field is
    # distinguishable from a document that carries none.
    class PlantedResponse(WireModel):
        stale_after_hours: int

    assert threshold_shaped_fields(PlantedResponse) == ["stale_after_hours"]
