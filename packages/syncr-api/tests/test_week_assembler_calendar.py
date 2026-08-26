"""The three calendar resolutions: the widened anchor read, the shadows, and the inherited night.

Each of the three exists because a span boundary would otherwise silently lose real occupancy, so
every test here is stated at a boundary. The declarations are the settled ones rather than
literals invented here, and the shadow generator, the collision rule, the zone resolution, and
the interval algebra are all the shipped implementations: a stubbed geometry would let this suite
pass while a week was wrong about what it holds.

Five claims carry the file.

**A commitment AHEAD of the week casts into it.** A 09:30 exam on the Monday of one week casts
prep at 19:30 the evening before, which is the last evening of the week before. So the read is
widened past the week's own end, and the widening is asserted through the span the repository was
actually asked for as well as through the block that arrives.

**Two leads, not one.** The rendered ``Lecture`` declares no prep and an abutting journey, so a
read widened by prep leads alone loses a Sunday-night journey to a Monday-morning commitment.

**A shadow is clipped and an anchor is not.** A prep block is derived content, and which week
holds it is decided by where it falls; a commitment's duration is the publisher's fact. Both
directions are asserted, and so is the span that abuts the week's end and therefore holds no
minute of it.

**The inherited night is resolved as its own week resolves it.** Asserted as an equality between
two real assemblies rather than as a figure: the week before's own occurrence, clipped, IS the
overhang this week carries, its off-plan periods and its approved concessions included.

**An off-plan span suppresses the blocks and neither the windows nor the commitments.** A prep
block carries an Area and is content; a recovery window explains a gap that is real; a commitment
during a period the user declared off is still a commitment.

Collisions are resolved over the set a week reads, so two commitments whose shadows collide
across the week's edge used to resolve differently in each week. The read now takes the widest
reach twice, which loads each collision's partner into both weeks and settles a shared collision
to the same block in both. The residual is measured rather than argued: a chain of three
commitments, each colliding with the next, still differs at the edge, and the control beside the
edge test states why.
"""

from __future__ import annotations

import io
import json
from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syncr_api.anchors.config import FORBIDS_EVERYTHING
from syncr_common.logging import configure_logging
from syncr_domain.fixtures.dst_weeks import DST_WEEKS, LONDON
from syncr_domain.gaps import ForbiddenKind, ForbiddenScope
from syncr_domain.identity import NO_OCCURRENCE, BindingKind, TransitLeg, date_occurrence_key
from syncr_domain.intervals import Interval
from syncr_domain.plan import AdjustmentKind
from syncr_domain.routines import MAX_DURATION_MINUTES
from syncr_solver.inputs import WeekAdjustment
from tests.anchor_specifications import (
    ATTRIBUTED_EXAM,
    ATTRIBUTED_INTERVIEW,
    ATTRIBUTED_LECTURE,
    CAREER,
    EXAM,
    INTERVIEW,
    NOTHING,
    STANDUP,
    STUDY,
    TRANSIT,
)
from tests.assembly_fakes import (
    MINUTES_PER_HOUR,
    NOW,
    WEEK,
    FakeAdjustments,
    FakeAnchors,
    FakeAnchorTypes,
    FakeAreas,
    FakeOffPlan,
    FakeRoutines,
    FakeSettings,
    a_routine,
    an_adjustment,
    an_anchor,
    an_anchor_type,
    an_area,
    an_assembler,
    an_off_plan_period,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from syncr_api.anchors.records import AnchorRecord, AnchorTypeRecord, AnchorTypeSpecification
    from syncr_api.offplan.records import OffPlanPeriodRecord
    from syncr_api.routines.records import RoutineRecord
    from syncr_domain.fixtures.dst_weeks import DstWeek
    from syncr_solver.inputs import SolveInputs

MINUTES_PER_DAY = 24 * MINUTES_PER_HOUR

# The week before the one the fakes are built around. Its last evening is where a Monday-morning
# commitment of `WEEK` casts, so it is the week these tests assemble whenever the subject is what
# a boundary would lose.
BEFORE = WEEK.preceding()

# 2026-W06 in London is on GMT throughout, so a wall time on its dates is the same instant in UTC.
SUNDAY = BEFORE.dates()[-1]
PRIOR_MONDAY = BEFORE.monday()


def on_sunday(hour: int, minute: int = 0) -> datetime:
    """An instant on the last evening of ``BEFORE``, which `WEEK` begins the day after."""
    return datetime(SUNDAY.year, SUNDAY.month, SUNDAY.day, hour, minute, tzinfo=UTC)


def on_monday(hour: int, minute: int = 0) -> datetime:
    """An instant on the first morning of ``WEEK``, which is the day after ``SUNDAY``."""
    return on_sunday(0, 0) + timedelta(days=1, hours=hour, minutes=minute)


def before_the_week(*, minutes: int) -> datetime:
    """An instant that many minutes before ``BEFORE`` starts, so it is another week's day."""
    start = datetime(PRIOR_MONDAY.year, PRIOR_MONDAY.month, PRIOR_MONDAY.day, tzinfo=UTC)
    return start - timedelta(minutes=minutes)


def inside_the_week(hour: int, *, day: int = 2) -> datetime:
    """An instant on the ``day``-th date of ``BEFORE``, well clear of either edge."""
    return datetime(
        PRIOR_MONDAY.year, PRIOR_MONDAY.month, PRIOR_MONDAY.day, tzinfo=UTC
    ) + timedelta(days=day, hours=hour)


def a_commitment(
    specification: AnchorTypeSpecification,
    *,
    start: datetime,
    minutes: int = 45,
    title: str = "Kontron Placement Interview",
) -> tuple[AnchorTypeRecord, AnchorRecord]:
    """One declared type and one commitment carrying it, ready for the two fakes."""
    anchor_type = an_anchor_type(specification)
    return anchor_type, an_anchor(
        interval=Interval(start, start + timedelta(minutes=minutes)),
        anchor_type=anchor_type,
        title=title,
    )


async def assemble_before(
    *,
    types: Sequence[AnchorTypeRecord] = (),
    anchors: Sequence[AnchorRecord] = (),
    routines: Sequence[RoutineRecord] = (),
    periods: Sequence[OffPlanPeriodRecord] = (),
    anchor_reader: FakeAnchors | None = None,
) -> SolveInputs:
    """``BEFORE`` assembled over the fakes, which is the week a boundary loses things from."""
    return await an_assembler(
        settings=FakeSettings(LONDON),
        anchors=anchor_reader or FakeAnchors(anchors),
        anchor_types=FakeAnchorTypes(types),
        routines=FakeRoutines(routines),
        off_plan=FakeOffPlan(periods),
    ).assemble(BEFORE, NOW)


# --------------------------------------------------------------------------------
# The read, widened by what the tenant's declarations can cast
# --------------------------------------------------------------------------------


async def test_a_monday_morning_exam_casts_its_sunday_evening_prep_into_the_week_before() -> None:
    # The worked case, and the reason the read is widened at all: the exam is not in this week and
    # its prep is. Without the widening the read stops at the week's own end, the exam is never
    # loaded, and the week silently holds an evening of free time the user is revising in.
    exam_type, exam = a_commitment(ATTRIBUTED_EXAM, start=on_monday(9, 30), title="Analysis Exam")

    inputs = await assemble_before(types=[exam_type], anchors=[exam])

    prep = next(
        block for block in inputs.shadow_blocks if block.binding.kind is BindingKind.ANCHOR_PREP
    )
    assert prep.interval == Interval(on_sunday(19, 30), on_sunday(20, 30))
    assert prep.area_id == STUDY
    assert prep.title == "Prep for Analysis Exam"


async def test_the_read_reaches_past_the_week_by_the_largest_lead_and_not_by_a_sum() -> None:
    # Asserted through the span the repository was asked for, which is the channel that decides
    # what a week can know about. A sum of the two leading products would read 885 minutes past
    # the end for this declaration, and nothing is ever cast that far back: prep and the outbound
    # leg are both measured from the commitment's start and run in parallel. The reach is taken
    # twice so collision partners load too, which is why the read goes twice as far as anything
    # is cast.
    exam_type = an_anchor_type(ATTRIBUTED_EXAM)
    reader = FakeAnchors()

    inputs = await assemble_before(types=[exam_type], anchor_reader=reader)

    read = reader.asked_for[-1]
    assert read.end == inputs.span.end + timedelta(minutes=2 * EXAM.prep_lead_minutes)
    assert read.start == inputs.span.start - timedelta(minutes=2 * EXAM.post_buffer_minutes)


async def test_a_journey_to_a_monday_morning_commitment_needs_the_transit_lead_in_the_read() -> (
    None
):
    # `Lecture` declares no prep at all, so a read widened by prep leads alone would stop at the
    # week's own end and lose the journey that leaves the night before.
    lecture_type, lecture = a_commitment(
        ATTRIBUTED_LECTURE, start=on_monday(0, 20), minutes=60, title="Compilers Lecture"
    )

    inputs = await assemble_before(types=[lecture_type], anchors=[lecture])

    journey = next(
        block
        for block in inputs.shadow_blocks
        if block.binding.occurrence_key == TransitLeg.OUT.value
    )
    assert journey.interval == Interval(on_sunday(23, 50), inputs.span.end)
    assert journey.area_id == TRANSIT


async def test_the_read_reaches_back_by_the_largest_span_measured_from_a_commitments_end() -> None:
    # The other direction: a commitment that ended before this week can reserve time inside it,
    # and recovery runs from its end beside the journey home rather than after it.
    interview_type, interview = a_commitment(
        ATTRIBUTED_INTERVIEW, start=before_the_week(minutes=75)
    )

    inputs = await assemble_before(types=[interview_type], anchors=[interview])

    assert inputs.anchors == ()
    recovery = next(
        window for window in inputs.forbidden_windows if window.kind is ForbiddenKind.RECOVERY
    )
    assert recovery.interval == Interval(
        inputs.span.start,
        before_the_week(minutes=75) + timedelta(minutes=45 + INTERVIEW.post_buffer_minutes),
    )


async def test_a_tenant_whose_declarations_cast_nothing_reads_exactly_its_own_week() -> None:
    # Every member of `Standup` is zero, so no commitment of it can put anything inside a week it
    # is not already inside, and widening the read would cost a wider statement for nothing.
    reader = FakeAnchors()

    inputs = await assemble_before(types=[an_anchor_type(STANDUP)], anchor_reader=reader)

    assert reader.asked_for == [inputs.span]


async def test_a_tenant_with_no_declared_types_still_reads_its_own_commitments() -> None:
    # An untyped commitment casts nothing and still occupies its own time, so the read happens
    # whether or not a type exists to widen it.
    opaque = an_anchor(interval=Interval(inside_the_week(9), inside_the_week(11)), title="Dentist")

    inputs = await assemble_before(anchors=[opaque])

    assert [anchor.title for anchor in inputs.anchors] == ["Dentist"]
    assert inputs.shadow_blocks == ()
    assert inputs.forbidden_windows == ()


# --------------------------------------------------------------------------------
# Clipping: what a week holds of a span that crosses its edge
# --------------------------------------------------------------------------------


async def test_a_shadow_crossing_the_weeks_edge_is_clipped_to_the_week_being_assembled() -> None:
    # One journey, two weeks, and each holds the part inside it: 10 minutes at the end of this
    # week and the remaining 20 in the next one. A shadow is derived content, so which week holds
    # it is decided by where it falls.
    lecture_type, lecture = a_commitment(ATTRIBUTED_LECTURE, start=on_monday(0, 20), minutes=60)

    before = await assemble_before(types=[lecture_type], anchors=[lecture])
    after = await an_assembler(
        settings=FakeSettings(LONDON),
        anchors=FakeAnchors([lecture]),
        anchor_types=FakeAnchorTypes([lecture_type]),
    ).assemble(WEEK, NOW)

    leaving = next(
        block
        for block in before.shadow_blocks
        if block.binding.occurrence_key == TransitLeg.OUT.value
    )
    arriving = next(
        block
        for block in after.shadow_blocks
        if block.binding.occurrence_key == TransitLeg.OUT.value
    )
    assert leaving.interval.total_minutes() == 10
    assert arriving.interval.total_minutes() == 20
    assert leaving.interval.end == arriving.interval.start == before.span.end


async def test_a_shadow_abutting_the_weeks_end_holds_no_minute_of_it_and_is_dropped() -> None:
    # Half-open bounds: a journey home that leaves exactly at the week's end covers none of it.
    # There is no empty interval to carry, so this is a shadow the week does not hold rather than a
    # zero-length one, and the algebra would refuse the alternative by construction. The outbound
    # leg of the same commitment is the control: it is inside, so a rule that dropped both would
    # fail here.
    lecture_type, lecture = a_commitment(
        ATTRIBUTED_LECTURE, start=on_sunday(23, 0), minutes=60, title="Late Lecture"
    )

    inputs = await assemble_before(types=[lecture_type], anchors=[lecture])

    assert [block.binding.occurrence_key for block in inputs.shadow_blocks] == [
        TransitLeg.OUT.value
    ]
    assert inputs.shadow_blocks[0].interval == Interval(on_sunday(22, 30), on_sunday(23, 0))
    assert inputs.anchors[0].interval.end == inputs.span.end


async def test_a_commitment_loaded_only_for_what_it_casts_occupies_nothing_here() -> None:
    # The exam is in the following week and only its prep is in this one, so this week states the
    # prep and does not state the exam: an anchor is occupancy for the week it is inside.
    exam_type, exam = a_commitment(ATTRIBUTED_EXAM, start=on_monday(9, 30))

    inputs = await assemble_before(types=[exam_type], anchors=[exam])

    assert inputs.anchors == ()
    assert len(inputs.shadow_blocks) == 1


async def test_a_commitment_crossing_the_weeks_edge_is_carried_whole_rather_than_clipped() -> None:
    # A commitment's duration is the publisher's fact rather than this week's reading of it, and
    # every figure taken over it subtracts inside the span anyway. Both weeks that overlap it
    # therefore state the same interval.
    straddling = an_anchor(
        interval=Interval(on_sunday(23, 0), on_monday(1, 0)), title="Night Shift"
    )

    before = await assemble_before(anchors=[straddling])
    after = await an_assembler(
        settings=FakeSettings(LONDON), anchors=FakeAnchors([straddling])
    ).assemble(WEEK, NOW)

    assert before.anchors[0].interval == straddling.interval
    assert after.anchors[0].interval == straddling.interval
    assert before.anchors[0].interval.end > before.span.end


async def test_an_anchor_keeps_its_real_time_even_at_seven_minutes_past() -> None:
    # An imported commitment is exempt from the grid: it keeps the time its publisher gave it,
    # and so does every buffer derived from it.
    interview_type, interview = a_commitment(
        ATTRIBUTED_INTERVIEW, start=on_sunday(16, 7), minutes=45
    )

    inputs = await assemble_before(types=[interview_type], anchors=[interview])

    assert inputs.anchors[0].interval == Interval(on_sunday(16, 7), on_sunday(16, 52))
    journey = next(
        block for block in inputs.shadow_blocks if block.binding.occurrence_key == TransitLeg.OUT
    )
    assert journey.interval.start == on_sunday(15, 7)


# --------------------------------------------------------------------------------
# One rule decides a block from a window, and the window keeps its scope
# --------------------------------------------------------------------------------


async def test_a_buffer_with_an_area_reaches_the_snapshot_as_a_block_carrying_it() -> None:
    interview_type, interview = a_commitment(ATTRIBUTED_INTERVIEW, start=on_sunday(16, 0))

    inputs = await assemble_before(types=[interview_type], anchors=[interview])

    assert [
        (block.binding.kind.value, block.binding.occurrence_key, block.area_id, block.title)
        for block in inputs.shadow_blocks
    ] == [
        (
            BindingKind.ANCHOR_PREP.value,
            NO_OCCURRENCE,
            CAREER,
            "Prep for Kontron Placement Interview",
        ),
        (
            BindingKind.ANCHOR_TRANSIT.value,
            TransitLeg.OUT.value,
            TRANSIT,
            "Leave for Kontron Placement Interview",
        ),
    ]


async def test_a_buffer_with_no_area_reaches_the_snapshot_as_a_window_forbidding_everything() -> (
    None
):
    # The same declaration, naming no Area for its prep or its legs. One rule decides which of
    # the two a buffer becomes, and this is the direction that has nothing to charge the minutes
    # to.
    unattributed_type, interview = a_commitment(INTERVIEW, start=on_sunday(16, 0))

    inputs = await assemble_before(types=[unattributed_type], anchors=[interview])

    assert inputs.shadow_blocks == ()
    assert [(window.kind.value, window.scope.value) for window in inputs.forbidden_windows] == [
        (ForbiddenKind.PREP_UNATTRIBUTED.value, ForbiddenScope.ALL.value),
        (ForbiddenKind.TRANSIT_UNATTRIBUTED.value, ForbiddenScope.ALL.value),
        (ForbiddenKind.RECOVERY.value, ForbiddenScope.AREAS.value),
    ]


async def test_a_recovery_window_carries_its_scope_and_the_areas_it_forbids_intact() -> None:
    # The scope is what a `for_probe()` projection splits on, and it splits there and nowhere
    # else, so it has to survive the assembly whole: a window that arrived with its scope
    # flattened would forbid every Area to both consumers.
    interview_type, interview = a_commitment(ATTRIBUTED_INTERVIEW, start=on_sunday(16, 0))

    inputs = await assemble_before(types=[interview_type], anchors=[interview])

    recovery = next(
        window for window in inputs.forbidden_windows if window.kind is ForbiddenKind.RECOVERY
    )
    assert recovery.scope is ForbiddenScope.AREAS
    assert recovery.forbidden_area_ids == (CAREER, STUDY)
    assert recovery.forbids(CAREER)
    assert not recovery.forbids(TRANSIT)
    assert recovery.anchor_id == interview.id


@pytest.fixture
def captured_log() -> Iterator[io.StringIO]:
    """Render to a captured stream, then hand the configuration back.

    structlog holds the stream it was configured with, so the pytest log fixtures see nothing.
    Logging configuration is process-global, and ``conftest.py`` fails the test that leaves it
    changed, so the restore is part of the fixture rather than an afterthought.
    """
    stream = io.StringIO()
    configure_logging(environment="production", log_level="info", stream=stream)
    yield stream
    configure_logging(environment="test", log_level="info")


async def test_a_commitment_whose_type_this_read_did_not_see_is_busy_time_rather_than_a_failure(
    captured_log: io.StringIO,
) -> None:
    # Two statements read a snapshot each, so a type created between them can be carried by an
    # anchor that arrives without it. Refusing the pair, which is what the generator does, would
    # fail every solve and live verdict for the week over a race a version bump already re-solves.
    carrying_a_type_nobody_read = an_anchor(
        interval=Interval(inside_the_week(9), inside_the_week(11)),
        title="Standup",
        anchor_type_id=uuid4(),
    )

    inputs = await assemble_before(anchors=[carrying_a_type_nobody_read])

    assert [anchor.title for anchor in inputs.anchors] == ["Standup"]
    assert inputs.shadow_blocks == ()
    assert inputs.forbidden_windows == ()
    reported = [
        line
        for line in (json.loads(line) for line in captured_log.getvalue().splitlines() if line)
        if line["event"] == "plans.assembly.anchor_type_unread"
    ]
    assert [
        (line["anchors_with_an_unread_type"], line["anchors_read"], line["types_read"])
        for line in reported
    ] == [(1, 1, 0)]


async def test_a_collision_across_the_week_edge_resolves_to_the_same_block_in_both_weeks() -> None:
    # The edge case that used to be a pinned limitation: collisions are resolved over the loaded
    # set, and the loaded set is every commitment whose shadows can decide what the week holds.
    # The read takes the widest reach twice, so both weeks load BOTH commitments here and give
    # way the same way: the journey home outranks the prep in each, and the one surviving block
    # is drawn clipped into whichever week each half of it falls in.
    #
    # The journey home is 90 minutes so it crosses Monday midnight, which is what makes the
    # agreement visible as one block with a half in each week rather than as an absence.
    returns = an_anchor_type(
        replace(NOTHING, name="Returns", return_transit_minutes=90, transit_area_id=TRANSIT)
    )
    preps = an_anchor_type(
        replace(
            NOTHING,
            name="Preps",
            prep_lead_minutes=90,
            prep_duration_minutes=60,
            prep_area_id=CAREER,
        ),
        rule_order=1,
    )
    edge = on_monday(0, 0)
    away = an_anchor(
        interval=Interval(edge - timedelta(minutes=120), edge - timedelta(minutes=60)),
        anchor_type=returns,
        title="Away Match",
    )
    interview = an_anchor(
        interval=Interval(edge + timedelta(minutes=60), edge + timedelta(minutes=120)),
        anchor_type=preps,
        title="Interview",
    )
    reader = FakeAnchors([away, interview])
    assembler = an_assembler(
        settings=FakeSettings(LONDON),
        anchors=reader,
        anchor_types=FakeAnchorTypes([returns, preps]),
    )

    before = await assembler.assemble(BEFORE, NOW)
    after = await assembler.assemble(WEEK, NOW)

    assert [(block.title, block.interval) for block in before.shadow_blocks] == [
        ("Go Home", Interval(on_sunday(23, 0), edge))
    ]
    assert [(block.title, block.interval) for block in after.shadow_blocks] == [
        ("Go Home", Interval(edge, on_monday(0, 30)))
    ]
    # The channel, not just the outcome: WEEK's read reaches back by the trailing reach taken
    # twice (2 x 90 minutes past Sunday midnight) or `away` would not be in its set at all.
    assert reader.asked_for[-1].start == on_sunday(21, 0)


async def test_a_chain_of_three_collisions_still_resolves_differently_at_the_edge() -> None:
    """The residual the widening leaves, measured and kept rather than argued away.

    Three commitments, each colliding with the next: the far match's journey home overlaps the
    away match's, whose journey home overlaps the interview's prep. BEFORE loads all three and
    resolves the chain from its start, where the earlier-cast far journey wins and the prep stands
    behind it; WEEK, whose read is one reach wider than a single reach, loads the away match but
    not the far one, so there the away journey wins and the prep gives way to it. Each answer is
    right for the set that produced it, and the sets still differ: order-dependent resolution is
    narrowed by one reach, not ended, because no finite number of reaches covers every chain.
    """
    returns = an_anchor_type(
        replace(NOTHING, name="Returns", return_transit_minutes=240, transit_area_id=TRANSIT)
    )
    preps = an_anchor_type(
        replace(
            NOTHING,
            name="Preps",
            prep_lead_minutes=90,
            prep_duration_minutes=60,
            prep_area_id=CAREER,
        ),
        rule_order=1,
    )
    edge = on_monday(0, 0)
    far = an_anchor(
        interval=Interval(on_sunday(14, 55), on_sunday(15, 55)),
        anchor_type=returns,
        title="Far Match",
    )
    away = an_anchor(
        interval=Interval(on_sunday(17, 50), on_sunday(19, 50)),
        anchor_type=returns,
        title="Away Match",
    )
    interview = an_anchor(
        interval=Interval(edge + timedelta(minutes=60), edge + timedelta(minutes=120)),
        anchor_type=preps,
        title="Interview",
    )
    reader = FakeAnchors([far, away, interview])
    assembler = an_assembler(
        settings=FakeSettings(LONDON),
        anchors=reader,
        anchor_types=FakeAnchorTypes([returns, preps]),
    )

    before = await assembler.assemble(BEFORE, NOW)
    after = await assembler.assemble(WEEK, NOW)

    # The whole chain: the far journey keeps its whole leg, the away journey gives way whole, and
    # the prep never meets a kept block, so it stands entire up to the edge.
    assert [(block.title, block.interval) for block in before.shadow_blocks] == [
        ("Go Home", Interval(on_sunday(15, 55), on_sunday(19, 55))),
        ("Prep for Interview", Interval(on_sunday(23, 30), edge)),
    ]
    # Without `far`, the away journey wins instead and the prep truncates against it to nothing:
    # the half hour BEFORE draws up to the edge is time WEEK holds free. Nothing survives into
    # WEEK at all, because the away journey home ends before Monday starts.
    assert [(block.title, block.interval) for block in after.shadow_blocks] == []
    # The channel as well: WEEK's read reaches back by the trailing reach taken twice (2 x 240
    # minutes past Sunday midnight), which loads `away` and keeps `far` out of its set.
    assert reader.asked_for[-1].start == on_sunday(16, 0)


# --------------------------------------------------------------------------------
# An off-plan span suppresses the blocks, and neither the windows nor the commitments
# --------------------------------------------------------------------------------


async def test_a_prep_block_inside_a_declared_off_plan_span_is_suppressed_like_any_content() -> (
    None
):
    # A block carries an Area and consumes its budget in the same way a task does, so the rule
    # that nothing discretionary materializes inside a declared span reaches it too.
    interview_type, interview = a_commitment(ATTRIBUTED_INTERVIEW, start=on_sunday(16, 0))
    away = an_off_plan_period(interval=Interval(on_sunday(6, 0), on_sunday(23, 0)))

    inputs = await assemble_before(types=[interview_type], anchors=[interview], periods=[away])

    assert inputs.shadow_blocks == ()


async def test_a_recovery_window_inside_a_declared_off_plan_span_still_reaches_the_snapshot() -> (
    None
):
    # Nothing turns on it either way, because no work is being scheduled in that span at all.
    # The window is kept because it explains a gap, and the gap is real.
    interview_type, interview = a_commitment(ATTRIBUTED_INTERVIEW, start=on_sunday(16, 0))
    away = an_off_plan_period(interval=Interval(on_sunday(6, 0), on_sunday(23, 0)))

    inputs = await assemble_before(types=[interview_type], anchors=[interview], periods=[away])

    assert [window.kind for window in inputs.forbidden_windows] == [ForbiddenKind.RECOVERY]


async def test_a_commitment_inside_a_declared_off_plan_span_still_occupies_its_time() -> None:
    # Off-plan suspends syncr's scheduling, not the world's: a lecture during a week the user
    # declared off is still a lecture.
    lecture = an_anchor(interval=Interval(on_sunday(9, 0), on_sunday(11, 0)), title="Lecture")
    away = an_off_plan_period(interval=Interval(on_sunday(6, 0), on_sunday(23, 0)))

    inputs = await assemble_before(anchors=[lecture], periods=[away])

    assert [anchor.title for anchor in inputs.anchors] == ["Lecture"]


# --------------------------------------------------------------------------------
# The night the week before spent, as this week's occupancy
# --------------------------------------------------------------------------------


@pytest.mark.parametrize("week", DST_WEEKS, ids=lambda week: week.label)
async def test_the_overhang_of_the_preceding_weeks_last_night_is_this_weeks_occupancy(
    week: DstWeek,
) -> None:
    # The fixture's Sunday-night frame span starts inside its week and ends inside the next one.
    # The occurrence belongs to the week its start falls in, so the next week states the part it
    # runs into: seven of the eight hours, in both transition directions.
    sleep = a_routine(
        target_time=week.frame_target_time, duration_minutes=week.frame_duration_minutes
    )
    following = week.iso_week.following()

    inputs = await an_assembler(
        settings=FakeSettings(week.zone), routines=FakeRoutines([sleep])
    ).assemble(following, NOW)

    assert inputs.frame_overhang == (Interval(inputs.span.start, week.sunday_night_frame.end),)
    assert inputs.frame_overhang[0].total_minutes() == 7 * MINUTES_PER_HOUR


@pytest.mark.parametrize("week", DST_WEEKS, ids=lambda week: week.label)
async def test_the_occurrence_itself_appears_in_exactly_one_of_the_two_weeks(
    week: DstWeek,
) -> None:
    # One night, one occurrence, one block, one document. Clipping it into both weeks instead
    # would truncate the routine into two fragments, neither of which matches its duration, and
    # would ask the user to confirm two halves of one night.
    sleep = a_routine(
        target_time=week.frame_target_time, duration_minutes=week.frame_duration_minutes
    )
    assembler = an_assembler(settings=FakeSettings(week.zone), routines=FakeRoutines([sleep]))

    owning = await assembler.assemble(week.iso_week, NOW)
    following = await assembler.assemble(week.iso_week.following(), NOW)

    sunday = date_occurrence_key(week.transition_date)
    assert sunday in {entry.occurrence_key for entry in owning.frame}
    assert sunday not in {entry.occurrence_key for entry in following.frame}
    assert owning.frame[-1].interval == week.sunday_night_frame
    assert owning.frame[-1].interval.total_minutes() == week.frame_duration_minutes


async def test_the_inherited_spans_are_what_the_week_before_resolved_clipped_to_this_week() -> None:
    # An equality between two real assemblies rather than a figure. What makes the two weeks one
    # answer is that this is the same resolution, so anything that changed one and not the other
    # would fail here rather than in a denominator two layers away.
    sleep = a_routine(target_time=time(23, 0), duration_minutes=8 * MINUTES_PER_HOUR)
    assembler = an_assembler(settings=FakeSettings(LONDON), routines=FakeRoutines([sleep]))

    before = await assembler.assemble(BEFORE, NOW)
    inputs = await assembler.assemble(WEEK, NOW)

    crossing = [
        entry.interval.clipped_to(inputs.span)
        for entry in before.frame
        if entry.interval.overlaps(inputs.span)
    ]
    assert inputs.frame_overhang == tuple(crossing)
    assert len(crossing) == 1


async def test_a_reduction_approved_for_the_week_before_shortens_the_night_this_week_inherits() -> (
    None
):
    # The overhang is that week's occurrence, so that week's concessions are part of what the
    # occurrence IS. Resolved from the unreduced declaration instead, this week would hold an hour
    # of occupied time the user was told they had been given back.
    sleep = a_routine(
        target_time=time(23, 0), duration_minutes=8 * MINUTES_PER_HOUR, min_duration_minutes=300
    )
    reduction = an_adjustment(
        kind=AdjustmentKind.REDUCE_ROUTINE.value,
        target_id=sleep.id,
        reductions={SUNDAY.isoformat(): 60},
    )
    stored = replace(reduction, iso_week=BEFORE)

    inputs = await an_assembler(
        settings=FakeSettings(LONDON),
        routines=FakeRoutines([sleep]),
        adjustments=FakeAdjustments([stored]),
    ).assemble(WEEK, NOW)

    assert inputs.frame_overhang[0].total_minutes() == 6 * MINUTES_PER_HOUR


async def test_a_candidate_concession_cannot_shorten_the_night_this_week_inherits() -> None:
    # A candidate is a decision about the week being ASSEMBLED, and the inherited occurrence belongs
    # to the week before it, so a tradeoff request must not report time freed in a week its
    # concession is not about. Nothing but the argument protects this: the candidate is appended to
    # the concession list verbatim rather than filtered by the week's own dates, so a candidate
    # reduction keyed to the preceding week's Sunday would shorten the inherited night if it were
    # folded there.
    sleep = a_routine(
        target_time=time(23, 0), duration_minutes=8 * MINUTES_PER_HOUR, min_duration_minutes=300
    )
    candidate = WeekAdjustment(
        adjustment_id=uuid4(),
        kind=AdjustmentKind.REDUCE_ROUTINE,
        target_id=sleep.id,
        reductions={SUNDAY: 60},
    )

    inputs = await an_assembler(
        settings=FakeSettings(LONDON), routines=FakeRoutines([sleep])
    ).assemble(WEEK, NOW, candidate)

    assert inputs.frame_overhang[0].total_minutes() == 7 * MINUTES_PER_HOUR
    # The candidate still reaches the week it IS about, so this is not a test about a concession
    # being dropped: it is folded here and nowhere else.
    assert [entry.adjustment_id for entry in inputs.adjustments] == [candidate.adjustment_id]


async def test_a_period_the_week_before_declared_suppresses_the_night_it_would_have_carried() -> (
    None
):
    # Judged against the periods of the week that OWNS the occurrence. Judged against this week's
    # instead, an occurrence its own week suppressed would still occupy time here, and the two
    # weeks would disagree about whether the user was asleep.
    sleep = a_routine(target_time=time(23, 0), duration_minutes=8 * MINUTES_PER_HOUR)
    away = an_off_plan_period(interval=Interval(on_sunday(18, 0), on_sunday(23, 30)))

    inputs = await an_assembler(
        settings=FakeSettings(LONDON),
        routines=FakeRoutines([sleep]),
        off_plan=FakeOffPlan([away]),
    ).assemble(WEEK, NOW)

    assert inputs.frame_overhang == ()
    assert inputs.off_plan == ()


async def test_an_occurrence_that_ends_inside_its_own_week_is_inherited_by_nobody() -> None:
    sleep = a_routine(target_time=time(6, 0), duration_minutes=60)

    inputs = await an_assembler(
        settings=FakeSettings(LONDON), routines=FakeRoutines([sleep])
    ).assemble(WEEK, NOW)

    assert inputs.frame_overhang == ()


async def test_the_longest_routine_a_tenant_can_declare_is_carried_whole() -> None:
    # One week back is enough because a routine runs for at most a day, so an occurrence starting
    # on the last date of the week before ends at most a day into this one and no occurrence from
    # any earlier week can reach here at all. The bound is what makes that complete rather than
    # heuristic, so it is read from the domain rather than assumed.
    assert MAX_DURATION_MINUTES <= MINUTES_PER_DAY
    all_day = a_routine(target_time=time(23, 0), duration_minutes=MAX_DURATION_MINUTES)

    inputs = await an_assembler(
        settings=FakeSettings(LONDON), routines=FakeRoutines([all_day])
    ).assemble(WEEK, NOW)

    assert inputs.frame_overhang[0] == Interval(inputs.span.start, on_monday(23, 0))


async def test_the_inherited_night_and_this_weeks_own_are_read_as_one_occupancy() -> None:
    # The rule that keeps the solver off a routine occurrence and the probe's `occupied` both ask
    # what the frame occupies, and the answer is both fields: a consumer reading this week's
    # occurrences alone would place work inside the night the week before already spent.
    sleep = a_routine(target_time=time(23, 0), duration_minutes=8 * MINUTES_PER_HOUR)

    inputs = await an_assembler(
        settings=FakeSettings(LONDON), routines=FakeRoutines([sleep])
    ).assemble(WEEK, NOW)

    occupied = inputs.frame_occupancy()
    assert occupied.overlaps(Interval(inputs.span.start, inputs.span.start + timedelta(hours=1)))
    assert occupied.total_minutes() == 7 * MINUTES_PER_HOUR + 7 * 8 * MINUTES_PER_HOUR


# --------------------------------------------------------------------------------
# The denominator, which is where all four subtrahends meet
# --------------------------------------------------------------------------------


async def a_denominator(**over: object) -> int:
    """The week's discretionary minutes, read through the one Area that claims all of them.

    An Area declaring the whole budget and no floor has a target equal to the denominator, so the
    figure the resolutions feed is observable through the snapshot rather than only inside the
    assembler.
    """
    whole = an_area(name="Everything", budget_percent=Decimal(100))
    inputs = await an_assembler(
        settings=FakeSettings(LONDON),
        areas=FakeAreas([whole]),
        **over,  # type: ignore[arg-type]
    ).assemble(BEFORE, NOW)
    return inputs.areas[0].target_minutes


async def test_the_denominator_subtracts_the_night_inherited_from_the_week_before() -> None:
    # 168 hours, less six whole nights of Sleep from Monday to Saturday, less the one hour of
    # Sunday night this week holds, less the seven hours the week BEFORE this one spent on its own
    # last night. That last term is the one a week reading only its own occurrences leaves in, and
    # leaving it in offers the user seven hours of sleep to plan work in.
    sleep = a_routine(target_time=time(23, 0), duration_minutes=8 * MINUTES_PER_HOUR)

    denominator = await a_denominator(routines=FakeRoutines([sleep]))

    assert denominator == 168 * MINUTES_PER_HOUR - (
        6 * 8 * MINUTES_PER_HOUR + MINUTES_PER_HOUR + 7 * MINUTES_PER_HOUR
    )


async def test_a_recovery_window_scoped_to_areas_stays_in_the_denominator() -> None:
    # The asymmetry the subtraction table exists for, and the only figure here that a
    # whole-week reading can get wrong in the direction that manufactures a shortfall. A scoped
    # window is claimable by every Area it does not name, so it stays in; the commitment itself is
    # time the product does not own, so it leaves. The two blocks the same declaration casts stay
    # in as well, because a buffer with an Area is time ALLOCATED to it rather than removed.
    interview_type, interview = a_commitment(
        ATTRIBUTED_INTERVIEW, start=on_sunday(16, 0), minutes=45
    )

    empty = await a_denominator()
    with_interview = await a_denominator(
        anchors=FakeAnchors([interview]), anchor_types=FakeAnchorTypes([interview_type])
    )

    assert empty - with_interview == 45


async def test_the_denominator_subtracts_a_commitment_and_an_absolute_window() -> None:
    # Time the product does not own, and time no Area can claim. Both leave the denominator, and
    # the two figures are asserted against the empty week rather than against each other.
    lecture = an_anchor(interval=Interval(on_sunday(9, 0), on_sunday(11, 0)), title="Lecture")
    absolute_type, flight = a_commitment(
        replace(
            INTERVIEW,
            post_scope=FORBIDS_EVERYTHING,
            forbidden_area_ids=(),
            post_buffer_minutes=120,
        ),
        start=on_sunday(14, 0),
        minutes=60,
    )

    empty = await a_denominator()
    with_anchor = await a_denominator(anchors=FakeAnchors([lecture]))
    with_window = await a_denominator(
        anchors=FakeAnchors([flight]), anchor_types=FakeAnchorTypes([absolute_type])
    )

    assert empty - with_anchor == 2 * MINUTES_PER_HOUR
    # The flight itself is an hour of occupancy and its recovery is two more hours no Area may
    # claim. Its prep and its outbound leg are windows too, at 30 minutes each.
    assert empty - with_window == 4 * MINUTES_PER_HOUR
