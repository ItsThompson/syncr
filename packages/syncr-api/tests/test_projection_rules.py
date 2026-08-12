"""What reaches the phone, keyed how, and described how. One test per row of the rule.

The rule the whole calendar strategy rests on is one sentence: **blocks project, forbidden windows
do not, and anchors are excluded because they came from a calendar in the first place.** It decides
whether two of the reference workflow's block classes ever reach the user, so it is tested per row
rather than per clause.

Five groups.

**The table.** Every origin, driven individually, against the answer the rule requires.
The mapping is also asserted total over the origin vocabulary, so a new kind of block cannot
silently arrive or silently vanish.

**What is not a block.** A recovery window of either scope, an unattributed prep or transit band,
and an empty slot are each put in a document and asserted to produce nothing. The exclusion is
structural -- none of the three is a block -- and an absent guard is a claim, so it is driven rather
than argued.

**The key.** It is the block's identity and nothing else, so a re-titled or moved block keeps it. An
off-plan segment's is built from the period and the local day, and cannot collide with a block's.

**The boundary-crossing span**, on the ``dst_weeks`` fixture: a Sunday-night frame that ends inside
the following ISO week is emitted exactly once across a two-week horizon, from the week it belongs
to. A collection that emitted it twice is refused rather than producing an ambiguous diff.

**The description.** It renders the ``bound`` clause, and a record carrying no such clause renders
nothing rather than a sentence assembled from a clause kind this has no wording for.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syncr_api.calendars.projected_events import (
    OFF_PLAN_DESCRIPTION,
    OFF_PLAN_TITLE,
    OFF_PLAN_WITH_FRAME_DESCRIPTION,
    PROJECTS_BY_ORIGIN,
    desired_events,
    off_plan_key,
    projected_blocks,
    projected_off_plan,
    rendered_reason,
)
from syncr_api.calendars.projection_errors import ProjectionKeysCollide
from syncr_api.calendars.reconciliation import plan_reconciliation
from syncr_api.offplan.records import OffPlanPeriodRecord
from syncr_api.offplan.segments import off_plan_segments
from syncr_domain.fixtures.dst_weeks import FALL_BACK, LONDON, SPRING_FORWARD
from syncr_domain.gaps import ForbiddenKind, ForbiddenScope
from syncr_domain.habits import BindingSource
from syncr_domain.identity import Origin
from syncr_domain.intervals import Interval
from syncr_domain.reasons import (
    Bound,
    ChurnBaseline,
    DerivationSource,
    Dominant,
    Pinned,
    ReasonRecord,
)
from syncr_domain.weeks import IsoWeek
from syncr_domain.zones import TravelOverride, ZoneProfile
from tests.plan_documents import (
    A_BOUND_REASON,
    CAREER,
    a_block,
    a_document,
    a_slot,
    a_window,
    a_zone_map,
    between,
)

if TYPE_CHECKING:
    from syncr_api.calendars.projection import ProjectedEvent
    from syncr_domain.fixtures.dst_weeks import DstWeek
    from syncr_domain.plan import Block
    from syncr_domain.reasons import BoundSource
    from syncr_domain.zones import ZoneId

# What projects, as one expectation per origin. Written out rather than derived
# from the mapping under test, which would assert the mapping against itself.
PROJECTS: dict[Origin, bool] = {
    Origin.TASK: True,
    Origin.HABIT: True,
    Origin.FRAME: True,
    Origin.TEMPLATE_ENTRY: True,
    Origin.PREP: True,
    Origin.TRANSIT: True,
    Origin.ANCHOR: False,
}

A_WIDE_HORIZON = Interval(datetime(2026, 2, 1, tzinfo=UTC), datetime(2026, 3, 1, tzinfo=UTC))

PERIOD = uuid4()

# Both vocabularies a ``bound`` clause's source spans, so "every source has a phrase" is stated over
# the union rather than over whichever half a test remembered.
_EVERY_BOUND_SOURCE: tuple[BoundSource, ...] = (*DerivationSource, *BindingSource)


def keys(events: tuple[ProjectedEvent, ...]) -> set[str]:
    return {event.syncr_key for event in events}


def a_period(
    start: datetime, end: datetime, *, label: str | None = None, keep_frame: bool = False
) -> OffPlanPeriodRecord:
    """One stored off-plan period, as the repository answers with one."""
    return OffPlanPeriodRecord(
        id=PERIOD,
        tenant_id=uuid4(),
        interval=Interval(start, end),
        keep_frame=keep_frame,
        label=label,
        created_at=start,
    )


# --------------------------------------------------------------------------------
# The what-projects table, one row at a time
# --------------------------------------------------------------------------------


@pytest.mark.parametrize("origin", list(PROJECTS))
def test_each_origin_projects_exactly_as_the_rule_states(origin: Origin) -> None:
    block = a_block(origin)

    projected = projected_blocks(a_document(blocks=(block,)), horizon=A_WIDE_HORIZON)

    assert bool(projected) is PROJECTS[origin], origin
    assert keys(projected) == ({block.id} if PROJECTS[origin] else set())


def test_an_anchor_block_does_not_project_beside_blocks_that_do() -> None:
    """The row that matters most: projecting an anchor would duplicate every lecture."""
    anchor = a_block(Origin.ANCHOR, interval=between(14, 15))
    prep = a_block(Origin.PREP, interval=between(10, 10.5))

    projected = projected_blocks(a_document(blocks=(anchor, prep)), horizon=A_WIDE_HORIZON)

    assert keys(projected) == {prep.id}


def test_a_transit_block_projects_under_the_title_the_user_reads() -> None:
    """``Leave for Uni`` is the clearest row in the table: it is useless off the phone."""
    leaving = a_block(Origin.TRANSIT, title="Leave for Uni", interval=between(8, 8.5))

    projected = projected_blocks(a_document(blocks=(leaving,)), horizon=A_WIDE_HORIZON)

    assert [event.title for event in projected] == ["Leave for Uni"]


def test_the_origin_table_is_total_over_the_vocabulary() -> None:
    """A new origin is a decision here rather than a default nobody chose."""
    assert set(PROJECTS_BY_ORIGIN) == set(Origin)


def test_the_table_under_test_answers_what_the_spec_states() -> None:
    assert PROJECTS_BY_ORIGIN == PROJECTS


# --------------------------------------------------------------------------------
# What is not a block
# --------------------------------------------------------------------------------


@pytest.mark.parametrize("scope", list(ForbiddenScope))
def test_a_recovery_window_of_either_scope_does_not_project(scope: ForbiddenScope) -> None:
    window = a_window(
        scope=scope, forbidden_area_ids=(CAREER,) if scope is ForbiddenScope.AREAS else ()
    )

    projected = projected_blocks(
        a_document(blocks=(), forbidden_windows=(window,)), horizon=A_WIDE_HORIZON
    )

    assert projected == ()


@pytest.mark.parametrize(
    "kind", [ForbiddenKind.PREP_UNATTRIBUTED, ForbiddenKind.TRANSIT_UNATTRIBUTED]
)
def test_an_unattributed_buffer_band_does_not_project(kind: ForbiddenKind) -> None:
    """A buffer with no Area is a window, not a block, so it is the absence of an event."""
    band = a_window(kind=kind, scope=ForbiddenScope.ALL, forbidden_area_ids=())

    projected = projected_blocks(
        a_document(blocks=(), forbidden_windows=(band,)), horizon=A_WIDE_HORIZON
    )

    assert projected == ()


def test_an_empty_slot_does_not_project() -> None:
    """Unallocated time with a stated reason is a syncr-side explanation, not an instruction."""
    projected = projected_blocks(
        a_document(blocks=(), empty_slots=(a_slot(),)), horizon=A_WIDE_HORIZON
    )

    assert projected == ()


def test_a_week_holding_every_kind_of_gap_projects_only_its_blocks() -> None:
    document = a_document(
        blocks=(a_block(Origin.TASK),),
        forbidden_windows=(
            a_window(),
            a_window(
                kind=ForbiddenKind.PREP_UNATTRIBUTED,
                scope=ForbiddenScope.ALL,
                forbidden_area_ids=(),
            ),
        ),
        empty_slots=(a_slot(),),
    )

    projected = projected_blocks(document, horizon=A_WIDE_HORIZON)

    assert len(projected) == 1


# --------------------------------------------------------------------------------
# The horizon
# --------------------------------------------------------------------------------


def test_a_block_outside_the_horizon_is_not_desired() -> None:
    inside = a_block(interval=between(9, 10))
    outside = a_block(interval=between(9, 10, day=6))
    horizon = Interval(inside.interval.start, inside.interval.end)

    projected = projected_blocks(a_document(blocks=(inside, outside)), horizon=horizon)

    assert keys(projected) == {inside.id}


def test_a_block_reaching_past_the_horizon_projects_whole() -> None:
    """A projected event IS the block, so trimming its end would put a time on the phone that the
    plan does not say."""
    block = a_block(interval=between(22, 30))
    horizon = Interval(
        block.interval.start - timedelta(hours=1), block.interval.start + timedelta(hours=1)
    )

    projected = projected_blocks(a_document(blocks=(block,)), horizon=horizon)

    assert [event.interval for event in projected] == [block.interval]


# --------------------------------------------------------------------------------
# The key
# --------------------------------------------------------------------------------


def test_the_key_is_the_blocks_identity() -> None:
    block = a_block()

    (event,) = projected_blocks(a_document(blocks=(block,)), horizon=A_WIDE_HORIZON)

    assert event.syncr_key == block.id


def test_a_re_titled_block_keeps_its_key() -> None:
    """Diffing on the title would churn every event whenever one changed."""
    block = a_block()
    renamed = replace(block, title="Gym · Push")

    assert _key_of(renamed) == _key_of(block)


def test_a_moved_block_keeps_its_key() -> None:
    """Diffing on the time would make a move look like a delete plus an insert."""
    block = a_block()
    moved = replace(block, interval=between(13, 14))

    assert _key_of(moved) == _key_of(block)


def test_a_projected_event_carries_no_location() -> None:
    """No block holds one: an anchor's is stored with no reader and an anchor does not project."""
    projected = projected_blocks(a_document(), horizon=A_WIDE_HORIZON)

    assert [event.location for event in projected] == [None]


def test_an_off_plan_key_cannot_collide_with_a_blocks() -> None:
    block = a_block()
    segment_key = off_plan_key(PERIOD, IsoWeek(2026, 7).monday())

    assert segment_key != block.id
    assert not segment_key.isalnum()  # a block id is 64 hexadecimal characters and nothing else


def test_an_off_plan_key_is_the_period_and_the_day() -> None:
    monday = IsoWeek(2026, 7).monday()

    assert off_plan_key(PERIOD, monday) == off_plan_key(PERIOD, monday)
    assert off_plan_key(PERIOD, monday) != off_plan_key(PERIOD, monday + timedelta(days=1))
    assert off_plan_key(PERIOD, monday) != off_plan_key(uuid4(), monday)


def _key_of(block: Block) -> str:
    (event,) = projected_blocks(a_document(blocks=(block,)), horizon=A_WIDE_HORIZON)
    return event.syncr_key


# --------------------------------------------------------------------------------
# Off-plan periods: one event per day segment
# --------------------------------------------------------------------------------


def test_a_period_across_a_weekend_projects_one_event_per_day_segment() -> None:
    # Friday 14:00 to Monday 09:00 London: four local days, two of them partial.
    period = a_period(datetime(2026, 2, 13, 14, tzinfo=UTC), datetime(2026, 2, 16, 9, tzinfo=UTC))

    segments = off_plan_segments(
        [period], horizon=A_WIDE_HORIZON, profile=ZoneProfile(home_zone=LONDON)
    )
    projected = projected_off_plan(segments)

    assert [segment.on.isoformat() for segment in segments] == [
        "2026-02-13",
        "2026-02-14",
        "2026-02-15",
        "2026-02-16",
    ]
    assert len(projected) == 4
    assert len(keys(projected)) == 4


def test_the_first_and_last_segments_start_and_end_where_the_period_does() -> None:
    period = a_period(datetime(2026, 2, 13, 14, tzinfo=UTC), datetime(2026, 2, 16, 9, tzinfo=UTC))

    first, _saturday, _sunday, last = off_plan_segments(
        [period], horizon=A_WIDE_HORIZON, profile=ZoneProfile(home_zone=LONDON)
    )

    assert first.interval.start == period.interval.start
    assert last.interval.end == period.interval.end


def test_a_period_ending_at_local_midnight_contributes_no_segment_for_that_day() -> None:
    """The bounds are half-open, so a period ending Monday 00:00 reaches nothing inside Monday."""
    period = a_period(datetime(2026, 2, 14, tzinfo=UTC), datetime(2026, 2, 16, tzinfo=UTC))

    segments = off_plan_segments(
        [period], horizon=A_WIDE_HORIZON, profile=ZoneProfile(home_zone=LONDON)
    )

    assert [segment.on.isoformat() for segment in segments] == ["2026-02-14", "2026-02-15"]


@pytest.mark.parametrize("week", [SPRING_FORWARD, FALL_BACK], ids=lambda week: week.label)
def test_a_transition_days_segment_is_as_long_as_that_day_really_was(week: DstWeek) -> None:
    """A day segment resolves each end in its own date's zone, so it is 23 or 25 hours."""
    period = a_period(week.local_transition_day.start, week.local_transition_day.end)

    (segment,) = off_plan_segments([period], horizon=week.span, profile=week.profile)

    assert segment.interval.total_minutes() == week.local_transition_day_minutes


def test_a_segment_outside_the_horizon_is_left_out() -> None:
    period = a_period(datetime(2026, 2, 13, 14, tzinfo=UTC), datetime(2026, 2, 16, 9, tzinfo=UTC))
    saturday_only = Interval(datetime(2026, 2, 14, tzinfo=UTC), datetime(2026, 2, 15, tzinfo=UTC))

    segments = off_plan_segments(
        [period], horizon=saturday_only, profile=ZoneProfile(home_zone=LONDON)
    )

    assert [segment.on.isoformat() for segment in segments] == ["2026-02-14"]


def test_a_segment_ends_at_the_next_days_own_midnight_across_a_travel_boundary() -> None:
    """A day whose successor is in another zone is not 24 hours long.

    The bite check found this: reading one zone for both ends of a segment passed every test,
    because a daylight-saving transition changes the OFFSET and not the zone identifier. Only a
    travel override makes the two ends resolve against different zones, and it moves the segment's
    end by the difference between them.
    """
    auckland: ZoneId = "Pacific/Auckland"
    travelling = ZoneProfile(
        home_zone=LONDON,
        travel_overrides=(
            TravelOverride(zone=auckland, start_date=date(2026, 2, 15), end_date=date(2026, 2, 20)),
        ),
    )
    # Two days in London's reading, the second of which is the trip's first date.
    period = a_period(datetime(2026, 2, 14, tzinfo=UTC), datetime(2026, 2, 16, tzinfo=UTC))

    saturday, *rest = off_plan_segments([period], horizon=A_WIDE_HORIZON, profile=travelling)

    # Auckland is 13 hours ahead in February, so the 15th begins there 13 hours before it begins in
    # London: the Saturday segment is 11 hours long rather than 24.
    assert saturday.interval.end == datetime(2026, 2, 14, 11, tzinfo=UTC)
    assert saturday.interval.total_minutes() == 11 * 60
    # And the same span therefore covers three local days rather than two, which is the other half
    # of the same fact: the days are the traveller's, not the home zone's.
    assert [segment.on.isoformat() for segment in rest] == ["2026-02-15", "2026-02-16"]


def test_an_unlabelled_period_still_says_why_the_calendar_is_empty() -> None:
    period = a_period(datetime(2026, 2, 14, tzinfo=UTC), datetime(2026, 2, 15, tzinfo=UTC))

    (event,) = projected_off_plan(
        off_plan_segments([period], horizon=A_WIDE_HORIZON, profile=ZoneProfile(home_zone=LONDON))
    )

    assert event.title == OFF_PLAN_TITLE
    assert event.description == OFF_PLAN_DESCRIPTION


def test_a_labelled_period_carries_the_users_own_words() -> None:
    period = a_period(
        datetime(2026, 2, 14, tzinfo=UTC), datetime(2026, 2, 15, tzinfo=UTC), label="Skiing"
    )

    (event,) = projected_off_plan(
        off_plan_segments([period], horizon=A_WIDE_HORIZON, profile=ZoneProfile(home_zone=LONDON))
    )

    assert event.title == f"{OFF_PLAN_TITLE}: Skiing"


def test_a_period_keeping_the_frame_says_the_routines_still_run() -> None:
    period = a_period(
        datetime(2026, 2, 14, tzinfo=UTC), datetime(2026, 2, 15, tzinfo=UTC), keep_frame=True
    )

    (event,) = projected_off_plan(
        off_plan_segments([period], horizon=A_WIDE_HORIZON, profile=ZoneProfile(home_zone=LONDON))
    )

    assert event.description == OFF_PLAN_WITH_FRAME_DESCRIPTION


# --------------------------------------------------------------------------------
# The span that crosses the ISO week boundary
# --------------------------------------------------------------------------------


def a_sunday_night_frame(week: IsoWeek, span: Interval) -> Block:
    """The Sunday-night ``Sleep`` occurrence: it starts inside ``week`` and ends inside the next."""
    return a_block(Origin.FRAME, week=week, interval=span, title="Sleep")


def test_a_boundary_crossing_frame_span_is_emitted_once_across_a_two_week_horizon() -> None:
    # The fixture's own span, written as a literal before this module existed: 2026-W13's last
    # night runs from Sunday 23:00 local into Monday, which belongs to 2026-W14.
    owning = SPRING_FORWARD.iso_week
    following = IsoWeek(2026, 14)
    crossing = a_sunday_night_frame(owning, SPRING_FORWARD.sunday_night_frame)
    horizon = Interval(SPRING_FORWARD.span.start, SPRING_FORWARD.span.start + timedelta(days=14))
    documents = [
        a_document(week=owning, blocks=(crossing,), zone_by_date=a_zone_map(owning, LONDON)),
        a_document(week=following, blocks=(), zone_by_date=a_zone_map(following, LONDON)),
    ]

    desired = desired_events(documents, (), horizon=horizon)

    assert [event.title for event in desired] == ["Sleep"]
    assert [event.syncr_key for event in desired] == [crossing.id]
    assert [event.interval for event in desired] == [SPRING_FORWARD.sunday_night_frame]


def test_the_following_weeks_own_sunday_night_is_a_second_event_with_its_own_key() -> None:
    """Two weeks in one horizon hold two Sunday nights, not one and not three."""
    owning = SPRING_FORWARD.iso_week
    following = IsoWeek(2026, 14)
    first = a_sunday_night_frame(owning, SPRING_FORWARD.sunday_night_frame)
    second = a_sunday_night_frame(
        following,
        Interval(
            SPRING_FORWARD.sunday_night_frame.start + timedelta(days=7),
            SPRING_FORWARD.sunday_night_frame.end + timedelta(days=7),
        ),
    )
    horizon = Interval(SPRING_FORWARD.span.start, second.interval.start + timedelta(hours=1))

    desired = desired_events(
        [
            a_document(week=owning, blocks=(first,), zone_by_date=a_zone_map(owning, LONDON)),
            a_document(
                week=following, blocks=(second,), zone_by_date=a_zone_map(following, LONDON)
            ),
        ],
        (),
        horizon=horizon,
    )

    assert {event.syncr_key for event in desired} == {first.id, second.id}


def test_a_span_collected_from_two_weeks_is_refused_by_the_diff() -> None:
    """The bite the assertion above rests on: two events under one key would make the diff pair one
    and never see the other, so it refuses rather than resolving."""
    crossing = a_sunday_night_frame(SPRING_FORWARD.iso_week, SPRING_FORWARD.sunday_night_frame)
    twice = a_document(
        week=SPRING_FORWARD.iso_week,
        blocks=(crossing,),
        zone_by_date=a_zone_map(SPRING_FORWARD.iso_week, LONDON),
    )

    collected = desired_events([twice, twice], (), horizon=SPRING_FORWARD.span)

    with pytest.raises(ProjectionKeysCollide, match="share the key"):
        plan_reconciliation(collected, [])


def test_a_block_and_an_off_plan_segment_never_share_the_desired_set() -> None:
    """One horizon holds both, and the two key spaces are disjoint by construction."""
    period = a_period(datetime(2026, 2, 13, 14, tzinfo=UTC), datetime(2026, 2, 14, 9, tzinfo=UTC))
    segments = off_plan_segments(
        [period], horizon=A_WIDE_HORIZON, profile=ZoneProfile(home_zone=LONDON)
    )

    desired = desired_events([a_document()], segments, horizon=A_WIDE_HORIZON)

    assert len(desired) == 1 + len(segments)
    assert len({event.syncr_key for event in desired}) == len(desired)


# --------------------------------------------------------------------------------
# The description
# --------------------------------------------------------------------------------


def test_the_description_renders_the_bound_clause() -> None:
    (event,) = projected_blocks(a_document(), horizon=A_WIDE_HORIZON)

    assert event.description is not None
    assert "Sleep · 23:00 + 8h" in event.description


@pytest.mark.parametrize(
    "source",
    [
        DerivationSource.ROUTINE,
        DerivationSource.TEMPLATE_ENTRY,
        DerivationSource.ANCHOR,
        DerivationSource.ANCHOR_TYPE,
        BindingSource.FIXED,
        BindingSource.ROTATION,
        BindingSource.QUEUE,
    ],
)
def test_every_bound_source_renders_a_phrase_in_words(source: BoundSource) -> None:
    """A source with no wording would render a value from the code onto the user's phone."""
    rendered = rendered_reason(ReasonRecord((Bound(source, "Something · 09:00"),)))

    assert rendered is not None
    assert rendered.endswith("Something · 09:00")
    # The code vocabulary spells a multi-word member with an underscore, and no sentence does.
    assert "_" not in rendered


def test_no_two_bound_sources_render_the_same_phrase() -> None:
    """Two sources sharing a phrase would make the description say less than it appears to."""
    phrases = [
        rendered_reason(ReasonRecord((Bound(source, "x"),))) for source in _EVERY_BOUND_SOURCE
    ]

    assert len(set(phrases)) == len(_EVERY_BOUND_SOURCE)


def test_a_record_with_no_bound_clause_renders_nothing() -> None:
    """Only a ``bound`` clause has copy, so a record carrying another kind renders nothing rather
    than a sentence assembled from a clause kind this has no wording for."""
    dominant = ReasonRecord((Dominant(term="context_switch", share=0.5, baseline=ChurnBaseline()),))

    assert rendered_reason(dominant) is None


def test_a_record_carrying_other_clauses_still_renders_the_bound_one() -> None:
    both = ReasonRecord(
        (
            Dominant(term="context_switch", share=0.5, baseline=ChurnBaseline()),
            Bound(DerivationSource.ROUTINE, "Sleep · 23:00 + 8h"),
        )
    )

    assert rendered_reason(both) == rendered_reason(A_BOUND_REASON)


def test_a_block_whose_reason_renders_nothing_still_projects() -> None:
    """The description is a courtesy; the event is the plan. A block with no renderable clause must
    still reach the phone."""
    block = a_block(
        Origin.HABIT,
        reason=ReasonRecord((Pinned(at=between(9, 10), pinned_on=IsoWeek(2026, 7).monday()),)),
    )

    (event,) = projected_blocks(a_document(blocks=(block,)), horizon=A_WIDE_HORIZON)

    assert event.description is None
    assert event.syncr_key == block.id
