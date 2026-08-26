"""How far a declaration casts, crossed against what the generator actually produces.

The reach is not an independent statement of the geometry: it is a bound on it, and a bound
nobody checks against the thing it bounds is a claim. So every case here generates the real
shadows and compares them with the envelope, over the settled declarations rather than over
literals invented here.

Three claims carry the file.

**No product falls outside the envelope.** Asserted per member over every fixture declaration,
in both the attributed form and the unattributed one, because a block and a window are produced
by different branches of the generator and both are bounded by the same reach.

**The envelope is tight in both halves.** For each of the four products there is a declaration
whose generated span touches the edge the reach claims, so neither half can be narrowed without
losing a real span. A lead whose product collapsed contributes nothing, which is the other
direction of tightness.

**The span an assembly reads inverts the directions.** A commitment AHEAD of a week casts prep
BACK into it, so the read widens forwards by the lead and backwards by what runs from a
commitment's end. Asserted as the "is it loaded" question over a commitment placed at each edge,
against the generated shadows for the same commitment.

**The envelope and the read are one bound from two sides**, and that biconditional is what lets a
writer answer "which weeks is this commitment an input of" without restating the geometry: a week
reads a commitment exactly when the commitment's envelope reaches that week.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from syncr_api.anchors.config import (
    ASSEMBLY_READ_MINUTES_MAX,
    DURATION_MINUTES_MAX,
    FORBIDS_EVERYTHING,
    FORBIDS_NOTHING,
    LEAD_MINUTES_MAX,
)
from syncr_api.anchors.reach import (
    ShadowReach,
    casting_reach,
    casting_span,
    shadow_reach,
    widest_reach,
)
from syncr_api.anchors.shadows import generate
from syncr_domain.intervals import Interval
from tests.anchor_specifications import (
    ATTRIBUTED_EXAM,
    ATTRIBUTED_GEOMETRY,
    EXAM,
    INTERVIEW,
    LECTURE,
    NOTHING,
    SHADOW_GEOMETRY,
    STANDUP,
)
from tests.shadow_scenes import EXAM_MONDAY, INTERVIEW_DAY, a_type, an_anchor, at

if TYPE_CHECKING:
    from syncr_api.anchors.records import AnchorTypeSpecification
    from syncr_domain.intervals import Instant

# Every declaration the settled records name, in both forms: the rendered one, whose prep and
# legs name no Area and therefore cast windows, and the attributed one, whose cast blocks. The
# reach bounds both, and a fixture reaching the generator through only one form would leave the
# other branch unbounded.
EVERY_DECLARATION = (*SHADOW_GEOMETRY, *ATTRIBUTED_GEOMETRY, STANDUP, NOTHING)

MINUTES_PER_HOUR = 60


def spans(
    specification: AnchorTypeSpecification, *, start: Instant | None = None
) -> tuple[Interval, ...]:
    """Every span the generator produces for one commitment carrying ``specification``."""
    anchor_type = a_type(specification)
    anchor = an_anchor(anchor_type, start=start or at(INTERVIEW_DAY, 16))
    shadows = generate(anchor, anchor_type)
    return (
        *(block.interval for block in shadows.blocks),
        *(window.interval for window in shadows.forbidden),
    )


@pytest.mark.parametrize("specification", EVERY_DECLARATION, ids=lambda spec: spec.name)
def test_no_span_a_declaration_casts_falls_outside_its_envelope(
    specification: AnchorTypeSpecification,
) -> None:
    anchor_type = a_type(specification)
    anchor = an_anchor(anchor_type, start=at(INTERVIEW_DAY, 16))
    envelope = shadow_reach(specification).envelope(anchor.interval)

    for span in spans(specification):
        assert envelope.start <= span.start, (specification.name, span)
        assert span.end <= envelope.end, (specification.name, span)


def test_the_leading_half_is_the_larger_of_the_two_leads_rather_than_their_sum() -> None:
    # Prep and the outbound leg are both measured from the commitment's start and run in
    # parallel, so a sum would read back further than anything is ever cast.
    reach = shadow_reach(ATTRIBUTED_EXAM)

    assert reach.before_minutes == EXAM.prep_lead_minutes
    assert (
        reach.before_minutes
        < EXAM.prep_lead_minutes + ATTRIBUTED_EXAM.effective_transit_lead_minutes
    )


def test_the_trailing_half_is_the_larger_of_the_return_leg_and_the_recovery() -> None:
    # Recovery runs from the commitment's end BESIDE the journey home rather than after it, so
    # this half is a maximum for the same reason the other one is.
    both = replace(
        NOTHING,
        return_transit_minutes=30,
        post_buffer_minutes=75,
        post_scope=FORBIDS_EVERYTHING,
    )

    assert shadow_reach(both).after_minutes == 75
    assert shadow_reach(replace(both, post_buffer_minutes=0)).after_minutes == 30


def test_each_half_is_touched_by_a_span_the_generator_really_casts() -> None:
    # Tightness. A reach wider than this would still bound every product, and would make every
    # assembly read commitments that can cast nothing into it.
    anchor_type = a_type(ATTRIBUTED_EXAM)
    anchor = an_anchor(anchor_type, start=at(EXAM_MONDAY, 9, 30))
    envelope = shadow_reach(ATTRIBUTED_EXAM).envelope(anchor.interval)
    cast = spans(ATTRIBUTED_EXAM, start=at(EXAM_MONDAY, 9, 30))

    assert min(span.start for span in cast) == envelope.start
    assert max(span.end for span in cast) == envelope.end


def test_a_lead_whose_product_collapsed_reaches_nowhere() -> None:
    # `Exam` declares a fourteen-hour prep lead. With no prep duration there is no prep block,
    # and a reach that read the column rather than the declaration would widen every assembly's
    # read by fourteen hours to find a span nothing casts.
    lead_but_no_prep = replace(ATTRIBUTED_EXAM, prep_duration_minutes=0)

    assert spans(lead_but_no_prep) != ()
    assert shadow_reach(lead_but_no_prep).before_minutes == EXAM.transit_lead_minutes


def test_a_recovery_buffer_that_forbids_nothing_reaches_nowhere() -> None:
    # The other collapse rule: a buffer with a scope of nothing generates no window at all, so
    # the trailing half has nothing to cover.
    forbids_nothing = replace(
        NOTHING, post_buffer_minutes=DURATION_MINUTES_MAX, post_scope=FORBIDS_NOTHING
    )

    assert spans(forbids_nothing) == ()
    assert shadow_reach(forbids_nothing) == ShadowReach.NOTHING


def test_a_declaration_that_casts_nothing_reaches_nowhere() -> None:
    assert shadow_reach(STANDUP) == ShadowReach.NOTHING
    assert spans(STANDUP) == ()


def test_the_widest_reach_covers_every_declaration_a_tenant_holds() -> None:
    # One reach for the set, because which type a commitment carries is not known until the
    # commitments have been read.
    widest = widest_reach(ATTRIBUTED_GEOMETRY)

    assert widest.before_minutes == max(
        shadow_reach(specification).before_minutes for specification in ATTRIBUTED_GEOMETRY
    )
    assert widest.after_minutes == max(
        shadow_reach(specification).after_minutes for specification in ATTRIBUTED_GEOMETRY
    )


def test_the_casting_reach_covers_the_widest_reach_twice_over() -> None:
    # One reach covers what can cast into the week; the second is added to it, so it covers what
    # can collide with those products. Stated over the halves rather than through `widened`,
    # because a reach widened with itself would keep its own halves and add nothing.
    reach = widest_reach(ATTRIBUTED_GEOMETRY)

    assert casting_reach(ATTRIBUTED_GEOMETRY) == ShadowReach(
        before_minutes=2 * reach.before_minutes,
        after_minutes=2 * reach.after_minutes,
    )


def test_a_tenant_with_no_declared_types_reads_exactly_its_own_week() -> None:
    week = Interval(at(EXAM_MONDAY, 0), at(EXAM_MONDAY, 0) + timedelta(days=7))

    assert casting_span(week, ()) == week


def test_the_read_widens_forwards_by_the_lead_and_backwards_by_the_trailing_span() -> None:
    # The inversion, stated as the two bounds: a commitment ahead of the week casts prep back
    # into it, and a commitment behind it casts recovery forward into it. The reach is taken
    # twice, so the partners those products collide with load as well.
    week = Interval(at(EXAM_MONDAY, 0), at(EXAM_MONDAY, 0) + timedelta(days=7))

    read = casting_span(week, ATTRIBUTED_GEOMETRY)

    assert read.end == week.end + timedelta(minutes=2 * EXAM.prep_lead_minutes)
    assert read.start == week.start - timedelta(minutes=2 * INTERVIEW.post_buffer_minutes)


def test_the_commitment_whose_prep_lands_in_the_previous_week_is_inside_that_weeks_read() -> None:
    # The worked case: a 09:30 exam on the Monday of one week casts prep at 19:30 the evening
    # before, which is the last day of the PREVIOUS ISO week. So it is that week's read that has
    # to reach the exam, and it reaches it forwards.
    previous_week = Interval(at(EXAM_MONDAY, 0) - timedelta(days=7), at(EXAM_MONDAY, 0))
    exam = an_anchor(a_type(ATTRIBUTED_EXAM), start=at(EXAM_MONDAY, 9, 30), minutes=120)
    prep = min(spans(ATTRIBUTED_EXAM, start=at(EXAM_MONDAY, 9, 30)))

    read = casting_span(previous_week, ATTRIBUTED_GEOMETRY)

    assert prep.overlaps(previous_week)
    assert exam.interval.start < read.end
    assert not exam.interval.start < previous_week.end


def test_a_commitment_is_read_by_exactly_the_weeks_its_envelope_reaches() -> None:
    """The two sides of one bound, crossed over a week swept past a fixed commitment.

    An assembly loads every commitment overlapping ``casting_span(week)``. A writer that has just
    moved a commitment needs the same question from the other side: which weeks was it an input of.
    ``envelope`` is that answer, taken over the same widened reach the read applies, and the two
    agree by derivation rather than by coincidence, so this asserts the biconditional directly. If
    they came apart, a week could load a commitment that nothing told it had moved, and its plan
    would be stale with every counter green.

    Swept rather than asserted at one offset, because the two disagree only at an edge, and a
    single offset in the middle of the overlap would pass for a bound that was wrong by a day.
    """
    reach = casting_reach(ATTRIBUTED_GEOMETRY)
    anchor = Interval(at(EXAM_MONDAY, 9, 30), at(EXAM_MONDAY, 11, 30))
    envelope = reach.envelope(anchor)
    monday = at(EXAM_MONDAY, 0)
    reached = []

    for offset in range(-21, 22):
        week = Interval(monday + timedelta(days=offset), monday + timedelta(days=offset + 7))

        assert anchor.overlaps(casting_span(week, ATTRIBUTED_GEOMETRY)) == envelope.overlaps(
            week
        ), offset
        if envelope.overlaps(week):
            reached.append(offset)

    # Neither side is vacuous: the week holding the commitment reads it, a week three weeks away
    # does not, and the sweep covers both answers.
    assert 0 in reached
    assert -21 not in reached
    assert 0 < len(reached) < 43


def test_a_journey_at_the_turn_of_the_week_needs_the_transit_lead_in_the_read() -> None:
    # `Lecture` declares no prep and an abutting outbound leg, so its whole reach is its transit
    # lead. A read widened by prep leads alone would stop at the week's own end and lose the
    # Sunday-night journey to a Monday-morning commitment.
    previous_week = Interval(at(EXAM_MONDAY, 0) - timedelta(days=7), at(EXAM_MONDAY, 0))
    lecture = an_anchor(a_type(LECTURE), start=at(EXAM_MONDAY, 0, 20), minutes=60)
    journey = min(spans(LECTURE, start=at(EXAM_MONDAY, 0, 20)))

    read = casting_span(previous_week, (LECTURE,))

    assert journey.overlaps(previous_week)
    assert lecture.interval.start < read.end
    assert read.end == previous_week.end + timedelta(minutes=2 * LECTURE.transit_duration_minutes)


def test_the_read_is_bounded_by_the_two_column_bounds_rather_than_by_a_declaration() -> None:
    # The reason the lead column has a bound at all: without one a single declaration would
    # widen every assembly's read without limit. The widest declaration the columns permit widens
    # the read by two weeks forwards and two days backwards, the reach taken twice.
    widest = replace(
        NOTHING,
        prep_lead_minutes=LEAD_MINUTES_MAX,
        prep_duration_minutes=DURATION_MINUTES_MAX,
        transit_lead_minutes=LEAD_MINUTES_MAX,
        transit_duration_minutes=DURATION_MINUTES_MAX,
        return_transit_minutes=DURATION_MINUTES_MAX,
        post_buffer_minutes=DURATION_MINUTES_MAX,
        post_scope=FORBIDS_EVERYTHING,
    )
    week = Interval(at(EXAM_MONDAY, 0), at(EXAM_MONDAY, 0) + timedelta(days=7))

    read = casting_span(week, (widest,))

    assert read.end - week.end == timedelta(minutes=2 * LEAD_MINUTES_MAX)
    assert week.start - read.start == timedelta(minutes=2 * DURATION_MINUTES_MAX)


def test_the_widest_read_a_week_can_ask_for_is_inside_the_bound_the_repository_enforces() -> None:
    # The two halves of one guard, crossed: the repository refuses a span wider than
    # `ASSEMBLY_READ_MINUTES_MAX`, and this is the widest span an assembly can produce. A week
    # itself is not 168 hours either, so the case is built over a travel week that resolves its two
    # Mondays 26 hours apart, which is the widest a zone pair permits.
    widest = replace(
        NOTHING,
        prep_lead_minutes=LEAD_MINUTES_MAX,
        prep_duration_minutes=DURATION_MINUTES_MAX,
        transit_lead_minutes=LEAD_MINUTES_MAX,
        transit_duration_minutes=DURATION_MINUTES_MAX,
        return_transit_minutes=DURATION_MINUTES_MAX,
        post_buffer_minutes=DURATION_MINUTES_MAX,
        post_scope=FORBIDS_EVERYTHING,
    )
    longest_week = Interval(at(EXAM_MONDAY, 0), at(EXAM_MONDAY, 0) + timedelta(days=7, hours=26))

    read = casting_span(longest_week, (widest,))

    assert read.total_minutes() <= ASSEMBLY_READ_MINUTES_MAX


def test_the_repository_bound_is_the_widened_read_derived_from_the_two_column_bounds() -> None:
    # Written out over literals rather than re-derived from the constants, so a change to how the
    # bound is composed is a decision this failure forces someone to look at rather than
    # arithmetic that silently moves with the code it guards: nine days of week and zone slack,
    # plus the lead bound and the duration bound taken twice each.
    assert ASSEMBLY_READ_MINUTES_MAX == 9 * 24 * 60 + 2 * (7 * 24 * 60) + 2 * (24 * 60)
