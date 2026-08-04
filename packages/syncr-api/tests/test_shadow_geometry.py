"""The geometry an anchor's type casts, asserted against the settled records rather than reasoned.

Every span here is arithmetic over one commitment's own interval and one declaration's two leads
and four durations, and two review iterations found defects in that arithmetic before it was
written down. So the worked example is asserted as an inventory: what the set holds, in full,
rather than that it holds a particular member.

Seven claims carry the file.

**The worked example closes.** ``docs/design/scratch/block-states.html`` renders prep at
10:00-10:30, the outbound leg at 15:00-15:30, no return leg, and 16:45 to 18:00 as a band, for a
16:00-16:45 interview. Every one of those four figures is asserted, and so is the ``Dinner`` at
18:00 that both records draw legally outside the band.

**One rule decides block or band.** A buffer with an Area is a block carrying it; a buffer with
none is a forbidden window that forbids every Area; recovery is a window whatever the type names.
Both directions of the rule are asserted over the same declarations.

**A zero collapses its own product and nothing else.** Each of the four members is zeroed on its
own, and the declaration with every member at zero casts nothing at all.

**An anchor's own blocks are exempt from its own recovery window.** Recovery is measured from the
commitment's end and so is the journey home, so the two overlap by construction. The exemption is
asserted with a positive control: another commitment's window over the same span does forbid it.

**A lead crossing a boundary is arithmetic, not a special case.** A 14-hour lead lands prep in the
previous ISO week, and a lead crossing a daylight-saving gap lands where elapsed time puts it
rather than where the wall clock would.

**Two commitments close together do not both keep what they cast.** Transit is fitted before prep,
the earlier-cast commitment keeps its block, and a truncation that would build a zero-length or
sub-grid span drops the block instead of raising.

**A shadow is derived, so regeneration is wholesale.** Regenerating one commitment equals
generating it, and regenerating a commitment that moved holds only spans measured from where it
moved to.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, time, timedelta
from typing import Final
from uuid import uuid4

import pytest

from syncr_api.anchors import rules, shadow_collisions
from syncr_api.anchors.config import FORBIDS_AREAS, FORBIDS_EVERYTHING, FORBIDS_NOTHING
from syncr_api.anchors.records import AnchorRecord, AnchorTypeRecord, AnchorTypeSpecification
from syncr_api.anchors.shadow_products import (
    DERIVED_ORIGINS,
    ShadowBlock,
    ShadowRejected,
    ShadowSet,
)
from syncr_api.anchors.shadows import (
    OUTBOUND_TITLE,
    PREP_TITLE,
    REASON_BY_KIND,
    RETURN_TITLE,
    ShadowPairingRejected,
    TypedAnchor,
    generate,
    regenerate,
)
from syncr_domain.gaps import ForbiddenKind, ForbiddenScope
from syncr_domain.identity import NO_OCCURRENCE, BindingError, Origin, TransitLeg, block_id
from syncr_domain.intervals import Instant, Interval
from syncr_domain.snap import SNAP_MINUTES
from syncr_domain.weeks import IsoWeek
from syncr_domain.zones import resolve_zone, to_instant
from tests.anchor_specifications import (
    ATTRIBUTED_EXAM,
    ATTRIBUTED_GEOMETRY,
    ATTRIBUTED_INTERVIEW,
    ATTRIBUTED_LECTURE,
    CAREER,
    DECLARED_AREAS,
    INTERVIEW,
    NOTHING,
    STANDUP,
    STUDY,
    TRANSIT,
)

TENANT = uuid4()
SOURCE = uuid4()
LONDON = "Europe/London"
COMMITMENT = "Kontron Placement Interview"

# The interview `block-states.html` renders, in the zone the reference weeks are drawn in.
INTERVIEW_DAY = date(2026, 2, 10)
# The Monday a 14-hour lead reaches back out of. Its Sunday belongs to the previous ISO week.
EXAM_MONDAY = date(2026, 2, 9)
# 01:00 becomes 02:00 in Europe/London on this date, so a lead across it loses an hour of wall
# time while keeping every minute of elapsed time.
SPRING_FORWARD = date(2026, 3, 29)

MINUTES_IN_AN_HOUR = 60

# Every origin a block can carry that an anchor does not cast. Named as the complement of what a
# shadow IS, so an eighth origin joins this list without anybody remembering to add it.
NOT_CAST_BY_AN_ANCHOR: Final = tuple(sorted(set(Origin) - DERIVED_ORIGINS, key=str))


def at(on: date, hour: int, minute: int = 0) -> Instant:
    """The instant a wall time on this date names in the zone the records are drawn in."""
    return to_instant(time(hour, minute), on, LONDON)


def wall(instant: Instant) -> str:
    """``instant`` as a reader of that week's grid sees it: local date and local time."""
    return instant.astimezone(resolve_zone(LONDON)).strftime("%a %Y-%m-%d %H:%M")


def a_type(specification: AnchorTypeSpecification) -> AnchorTypeRecord:
    """``specification`` as a stored row, refused here if the boundary would refuse it.

    Every geometry below is therefore stated over a declaration a tenant could really hold. A
    fixture the rules reject describes a shadow the product cannot cast, and a test reading one
    asserts arithmetic against itself.
    """
    rules.validate(specification, declared_areas=DECLARED_AREAS, declared_sources=())
    return AnchorTypeRecord(id=uuid4(), tenant_id=TENANT, rule_order=0, specification=specification)


def an_anchor(
    anchor_type: AnchorTypeRecord | None,
    *,
    start: Instant,
    minutes: int = 45,
    title: str = COMMITMENT,
) -> AnchorRecord:
    """One imported commitment carrying ``anchor_type``, or carrying none."""
    return AnchorRecord(
        id=uuid4(),
        tenant_id=TENANT,
        source_id=SOURCE,
        external_uid=f"{title}@example.ac.uk",
        series_uid=None,
        title=title,
        interval=Interval(start, start + timedelta(minutes=minutes)),
        location=None,
        anchor_type_id=None if anchor_type is None else anchor_type.id,
        type_overridden=False,
        possibly_stale=False,
    )


def spans(shadows: ShadowSet) -> tuple[tuple[str, str, str, str], ...]:
    """Every member of ``shadows``, as the four things a reader of the grid can tell apart.

    An inventory rather than a lookup: a claim about what a declaration does NOT cast is only
    worth making against the whole of what it does.
    """
    blocks = tuple(
        (
            block.origin.value,
            block.occurrence_key,
            wall(block.interval.start),
            wall(block.interval.end),
        )
        for block in shadows.blocks
    )
    windows = tuple(
        (
            window.kind.value,
            window.scope.value,
            wall(window.interval.start),
            wall(window.interval.end),
        )
        for window in shadows.forbidden
    )
    return blocks + windows


def keys(shadows: ShadowSet) -> tuple[tuple[str, str], ...]:
    """Which products these blocks are, by origin and occurrence key."""
    return tuple((block.origin.value, block.occurrence_key) for block in shadows.blocks)


def an_interview_anchor(specification: AnchorTypeSpecification) -> tuple[AnchorRecord, ShadowSet]:
    """The 16:00-16:45 commitment the records render, and the shadows ``specification`` casts."""
    anchor_type = a_type(specification)
    anchor = an_anchor(anchor_type, start=at(INTERVIEW_DAY, 16))
    return anchor, generate(anchor, anchor_type)


# --------------------------------------------------------------------------------
# The fixture itself. Both forms of every rendered declaration have to be storable,
# or the geometry below is stated over something the product cannot hold.
# --------------------------------------------------------------------------------


@pytest.mark.parametrize("specification", ATTRIBUTED_GEOMETRY, ids=lambda spec: spec.name)
def test_every_attributed_form_of_the_fixture_passes_the_boundary_rules(
    specification: AnchorTypeSpecification,
) -> None:
    a_type(specification)


# --------------------------------------------------------------------------------
# The worked example, in full.
# --------------------------------------------------------------------------------


def test_the_worked_example_closes_exactly() -> None:
    _, shadows = an_interview_anchor(ATTRIBUTED_INTERVIEW)

    assert spans(shadows) == (
        ("prep", NO_OCCURRENCE, "Tue 2026-02-10 10:00", "Tue 2026-02-10 10:30"),
        ("transit", "out", "Tue 2026-02-10 15:00", "Tue 2026-02-10 15:30"),
        ("recovery", "areas", "Tue 2026-02-10 16:45", "Tue 2026-02-10 18:00"),
    )


def test_the_interview_casts_no_return_leg() -> None:
    # `return_transit 0` on the rendered Interview, and the record says the commitment casts two
    # shadows rather than three. The inventory is the assertion: a missing member cannot hide
    # behind a query for the one that is absent.
    _, shadows = an_interview_anchor(ATTRIBUTED_INTERVIEW)

    assert keys(shadows) == (("prep", NO_OCCURRENCE), ("transit", TransitLeg.OUT.value))


def test_prep_and_the_outbound_leg_carry_the_areas_their_type_names() -> None:
    _, shadows = an_interview_anchor(ATTRIBUTED_INTERVIEW)

    assert [(block.origin.value, block.area_id) for block in shadows.blocks] == [
        ("prep", CAREER),
        ("transit", TRANSIT),
    ]


def test_a_derived_block_names_the_commitment_it_belongs_to() -> None:
    anchor, shadows = an_interview_anchor(ATTRIBUTED_INTERVIEW)

    assert [block.title for block in shadows.blocks] == [
        PREP_TITLE.format(commitment=COMMITMENT),
        OUTBOUND_TITLE.format(commitment=COMMITMENT),
    ]
    assert {block.anchor_id for block in shadows.blocks} == {anchor.id}


def test_a_dinner_at_eighteen_hundred_sits_legally_outside_the_recovery_window() -> None:
    # Both records draw `18:00-18:30 Dinner` on the interview's own Tuesday. The window is
    # half-open, so the block that starts where it ends is clear of it whatever Area it carries.
    _, shadows = an_interview_anchor(ATTRIBUTED_INTERVIEW)
    dinner = Interval(at(INTERVIEW_DAY, 18), at(INTERVIEW_DAY, 18) + timedelta(minutes=30))
    deep_work = Interval(at(INTERVIEW_DAY, 17), at(INTERVIEW_DAY, 17) + timedelta(minutes=30))

    forbidden = [shadows.forbidden_for(area_id) for area_id in (CAREER, STUDY)]

    assert [spans.overlaps(dinner) for spans in forbidden] == [False, False]
    assert [spans.overlaps(deep_work) for spans in forbidden] == [True, True]


def test_recovery_leaves_an_unnamed_area_alone() -> None:
    # `post_scope areas` forbids Career and Study, so the gym is still fine at 17:00: that is what
    # makes the scope a choice rather than a formality.
    _, shadows = an_interview_anchor(ATTRIBUTED_INTERVIEW)
    fitness = uuid4()

    assert not shadows.forbidden_for(fitness)


# --------------------------------------------------------------------------------
# The arithmetic, member by member.
# --------------------------------------------------------------------------------


def test_the_outbound_leg_abuts_the_commitment_when_no_lead_is_declared() -> None:
    # The rendered Lecture declares a 30-minute journey and no lead at all, which means leaving
    # exactly late enough to arrive on time.
    anchor_type = a_type(ATTRIBUTED_LECTURE)
    anchor = an_anchor(anchor_type, start=at(INTERVIEW_DAY, 11), minutes=60)

    shadows = generate(anchor, anchor_type)
    outbound = shadows.blocks[0]

    assert outbound.occurrence_key == TransitLeg.OUT.value
    assert outbound.interval.end == anchor.interval.start
    assert outbound.interval.total_minutes() == 30


def test_a_larger_lead_arrives_early_and_leaves_the_gap_the_record_draws() -> None:
    _, shadows = an_interview_anchor(ATTRIBUTED_INTERVIEW)
    outbound = next(block for block in shadows.blocks if block.origin is Origin.TRANSIT)

    # 60 minutes out for a 30-minute journey: half an hour of deliberate slack before 16:00.
    assert (at(INTERVIEW_DAY, 16) - outbound.interval.end).total_seconds() / 60 == 30


def test_the_return_leg_and_recovery_both_start_at_the_commitments_end() -> None:
    # Recovery is measured from the end of the commitment, never from the end of the journey
    # home, which is why the two overlap rather than follow one another.
    anchor_type = a_type(
        replace(ATTRIBUTED_EXAM, post_scope=FORBIDS_EVERYTHING, forbidden_area_ids=())
    )
    anchor = an_anchor(anchor_type, start=at(EXAM_MONDAY, 9, 30), minutes=120)

    shadows = generate(anchor, anchor_type)
    back = next(block for block in shadows.blocks if block.occurrence_key == TransitLeg.BACK.value)
    recovery = shadows.forbidden[0]

    assert back.interval.start == anchor.interval.end
    assert recovery.interval.start == anchor.interval.end
    assert back.interval.overlaps(recovery.interval)


def test_a_commitment_that_starts_at_seven_minutes_past_keeps_its_own_time() -> None:
    # An imported commitment is exempt from the fifteen-minute grid and so is every buffer
    # measured from it, seconds included: the buffer is derived from the real time, not from a
    # tidied one.
    anchor_type = a_type(ATTRIBUTED_INTERVIEW)
    start = at(INTERVIEW_DAY, 16) + timedelta(minutes=7, seconds=30)
    anchor = an_anchor(anchor_type, start=start, minutes=38)

    shadows = generate(anchor, anchor_type)

    assert [block.interval.start.isoformat() for block in shadows.blocks] == [
        "2026-02-10T10:07:30+00:00",
        "2026-02-10T15:07:30+00:00",
    ]
    assert shadows.forbidden[0].interval.start == anchor.interval.end
    assert shadows.forbidden[0].interval.end.isoformat() == "2026-02-10T18:00:30+00:00"


# --------------------------------------------------------------------------------
# One rule decides block or band. Boundary X11: each branch, both directions.
# --------------------------------------------------------------------------------


def test_a_prep_buffer_with_no_area_is_a_window_forbidding_everything() -> None:
    _, shadows = an_interview_anchor(INTERVIEW)
    prep = shadows.forbidden[0]

    assert (prep.kind, prep.scope, prep.forbidden_area_ids) == (
        ForbiddenKind.PREP_UNATTRIBUTED,
        ForbiddenScope.ALL,
        (),
    )
    assert prep.interval == Interval(at(INTERVIEW_DAY, 10), at(INTERVIEW_DAY, 10, 30))


def test_a_transit_buffer_with_no_area_is_a_window_forbidding_everything() -> None:
    _, shadows = an_interview_anchor(INTERVIEW)
    outbound = shadows.forbidden[1]

    assert (outbound.kind, outbound.scope, outbound.forbidden_area_ids) == (
        ForbiddenKind.TRANSIT_UNATTRIBUTED,
        ForbiddenScope.ALL,
        (),
    )
    assert outbound.interval == Interval(at(INTERVIEW_DAY, 15), at(INTERVIEW_DAY, 15, 30))


def test_an_unattributed_declaration_casts_no_blocks_at_all() -> None:
    _, shadows = an_interview_anchor(INTERVIEW)

    assert shadows.blocks == ()
    assert [window.kind.value for window in shadows.forbidden] == [
        "prep_unattributed",
        "transit_unattributed",
        "recovery",
    ]


def test_the_post_buffer_is_a_window_even_when_the_type_names_areas_everywhere() -> None:
    # The Areas a recovery window names are the ones it FORBIDS, which is the opposite of
    # belonging to one, so no naming of Areas can turn the post buffer into a block.
    _, shadows = an_interview_anchor(ATTRIBUTED_INTERVIEW)
    recovery = shadows.forbidden[0]

    assert [window.kind for window in shadows.forbidden] == [ForbiddenKind.RECOVERY]
    assert {block.origin for block in shadows.blocks} == DERIVED_ORIGINS
    assert not [block for block in shadows.blocks if block.interval.overlaps(recovery.interval)]


def test_a_window_names_the_reason_and_the_commitment_that_reserved_the_time() -> None:
    anchor, shadows = an_interview_anchor(INTERVIEW)

    assert [window.label for window in shadows.forbidden] == [
        f"prep · {COMMITMENT}",
        f"transit · {COMMITMENT}",
        f"recovery · {COMMITMENT}",
    ]
    assert {window.anchor_id for window in shadows.forbidden} == {anchor.id}


# --------------------------------------------------------------------------------
# The zero-collapse rules, one test each, and the declaration that casts nothing.
# --------------------------------------------------------------------------------


def test_a_zero_journey_casts_no_outbound_leg_whatever_the_lead_says() -> None:
    declaration = replace(
        NOTHING,
        transit_lead_minutes=60,
        transit_duration_minutes=0,
        transit_area_id=TRANSIT,
        post_buffer_minutes=30,
        post_scope=FORBIDS_EVERYTHING,
    )
    _, shadows = an_interview_anchor(declaration)

    # The recovery window is present, so the absent leg is an absence rather than an empty set.
    assert spans(shadows) == (("recovery", "all", "Tue 2026-02-10 16:45", "Tue 2026-02-10 17:15"),)


def test_a_zero_return_casts_no_leg_home() -> None:
    declaration = replace(
        NOTHING,
        transit_lead_minutes=30,
        transit_duration_minutes=30,
        return_transit_minutes=0,
        transit_area_id=TRANSIT,
    )
    _, shadows = an_interview_anchor(declaration)

    assert keys(shadows) == (("transit", TransitLeg.OUT.value),)


def test_a_zero_prep_duration_casts_no_prep_whatever_the_lead_says() -> None:
    declaration = replace(
        NOTHING,
        prep_lead_minutes=360,
        prep_duration_minutes=0,
        prep_area_id=CAREER,
        transit_lead_minutes=30,
        transit_duration_minutes=30,
        transit_area_id=TRANSIT,
    )
    _, shadows = an_interview_anchor(declaration)

    assert keys(shadows) == (("transit", TransitLeg.OUT.value),)


@pytest.mark.parametrize(
    ("buffer_minutes", "scope"),
    [(75, FORBIDS_NOTHING), (0, FORBIDS_EVERYTHING)],
    ids=["scope-forbids-nothing", "zero-buffer"],
)
def test_a_recovery_window_needs_both_a_buffer_and_a_scope(buffer_minutes: int, scope: str) -> None:
    declaration = replace(
        NOTHING,
        transit_lead_minutes=30,
        transit_duration_minutes=30,
        transit_area_id=TRANSIT,
        post_buffer_minutes=buffer_minutes,
        post_scope=scope,  # type: ignore[arg-type]  # the literal is the config alias
    )
    _, shadows = an_interview_anchor(declaration)

    assert shadows.forbidden == ()
    assert keys(shadows) == (("transit", TransitLeg.OUT.value),)


def test_a_declaration_with_every_member_at_zero_casts_no_shadow_at_all() -> None:
    _, shadows = an_interview_anchor(STANDUP)

    assert shadows == ShadowSet.EMPTY


def test_an_untyped_commitment_casts_no_shadow_at_all() -> None:
    anchor = an_anchor(None, start=at(INTERVIEW_DAY, 16))

    assert generate(anchor, None) == ShadowSet.EMPTY


# --------------------------------------------------------------------------------
# Identity: two legs, two blocks.
# --------------------------------------------------------------------------------


def test_the_two_legs_of_one_commitment_derive_two_identities() -> None:
    anchor_type = a_type(replace(ATTRIBUTED_LECTURE, return_transit_minutes=30))
    anchor = an_anchor(anchor_type, start=at(INTERVIEW_DAY, 11), minutes=60)
    week = IsoWeek.containing(INTERVIEW_DAY)

    shadows = generate(anchor, anchor_type)
    ids = [block_id(week, block.binding) for block in shadows.blocks]

    assert keys(shadows) == (
        ("transit", TransitLeg.OUT.value),
        ("transit", TransitLeg.BACK.value),
    )
    assert len(set(ids)) == len(ids)


def test_a_retitled_commitment_keeps_the_identity_its_buffers_derive() -> None:
    # Identity is the commitment's identifier, never its text, so a publisher renaming a lecture
    # does not orphan an outcome recorded against the journey to it.
    anchor_type = a_type(ATTRIBUTED_INTERVIEW)
    anchor = an_anchor(anchor_type, start=at(INTERVIEW_DAY, 16))
    retitled = replace(anchor, title=f"{COMMITMENT} (moved room)")
    week = IsoWeek.containing(INTERVIEW_DAY)

    before = generate(anchor, anchor_type).blocks
    after = generate(retitled, anchor_type).blocks

    assert [block_id(week, block.binding) for block in before] == [
        block_id(week, block.binding) for block in after
    ]
    assert [block.title for block in before] != [block.title for block in after]


@pytest.mark.parametrize("origin", NOT_CAST_BY_AN_ANCHOR, ids=str)
def test_a_shadow_block_refuses_an_origin_an_anchor_cannot_cast(origin: Origin) -> None:
    with pytest.raises(ShadowRejected):
        ShadowBlock(
            interval=Interval(at(INTERVIEW_DAY, 10), at(INTERVIEW_DAY, 10, 30)),
            origin=origin,
            occurrence_key=NO_OCCURRENCE,
            area_id=CAREER,
            title="Prep",
            anchor_id=uuid4(),
        )


@pytest.mark.parametrize(
    ("origin", "occurrence_key"),
    [
        (Origin.PREP, TransitLeg.OUT.value),
        (Origin.TRANSIT, NO_OCCURRENCE),
        (Origin.TRANSIT, "outbound"),
    ],
    ids=["prep-keyed-as-a-leg", "leg-with-no-key", "leg-with-an-invented-key"],
)
def test_a_shadow_block_refuses_a_key_its_own_binding_would_refuse(
    origin: Origin, occurrence_key: str
) -> None:
    with pytest.raises(BindingError):
        ShadowBlock(
            interval=Interval(at(INTERVIEW_DAY, 10), at(INTERVIEW_DAY, 10, 30)),
            origin=origin,
            occurrence_key=occurrence_key,
            area_id=CAREER,
            title="Prep",
            anchor_id=uuid4(),
        )


# --------------------------------------------------------------------------------
# The exemption: an anchor's own blocks against its own recovery window.
# --------------------------------------------------------------------------------


def a_lecture_with_recovery() -> AnchorTypeSpecification:
    """The rendered Lecture, given a recovery window that forbids the Area its legs belong to.

    Forbidding ``Transit`` is what makes the exemption bite: a window that did not forbid the
    leg's own Area would leave the journey home legal for a reason other than the exemption.
    """
    return replace(
        ATTRIBUTED_LECTURE,
        return_transit_minutes=30,
        post_buffer_minutes=60,
        post_scope=FORBIDS_AREAS,
        forbidden_area_ids=(TRANSIT,),
    )


def test_the_journey_home_sits_inside_its_own_recovery_window_without_violating_it() -> None:
    anchor_type = a_type(a_lecture_with_recovery())
    anchor = an_anchor(anchor_type, start=at(INTERVIEW_DAY, 16, 30), minutes=60)

    shadows = generate(anchor, anchor_type)
    home = next(block for block in shadows.blocks if block.occurrence_key == TransitLeg.BACK.value)
    recovery = shadows.forbidden[0]

    assert wall(home.interval.start) == "Tue 2026-02-10 17:30"
    assert wall(home.interval.end) == "Tue 2026-02-10 18:00"
    assert home.title == RETURN_TITLE
    assert recovery.interval.overlaps(home.interval)
    assert recovery.forbids(home.area_id)
    assert shadows.forbidding_window(home) is None


def test_another_commitments_window_does_forbid_that_journey_home() -> None:
    lecture = a_type(a_lecture_with_recovery())
    quarantine = a_type(
        replace(
            NOTHING, post_buffer_minutes=60, post_scope=FORBIDS_AREAS, forbidden_area_ids=(TRANSIT,)
        )
    )
    ends_at_the_same_instant = at(INTERVIEW_DAY, 16, 30) + timedelta(minutes=60)
    pair = [
        TypedAnchor(an_anchor(lecture, start=at(INTERVIEW_DAY, 16, 30), minutes=60), lecture),
        TypedAnchor(
            an_anchor(
                quarantine, start=ends_at_the_same_instant - timedelta(minutes=30), minutes=30
            ),
            quarantine,
        ),
    ]

    shadows = regenerate(pair)
    home = next(block for block in shadows.blocks if block.occurrence_key == TransitLeg.BACK.value)
    offending = shadows.forbidding_window(home)

    assert offending is not None
    assert offending.anchor_id != home.anchor_id


# --------------------------------------------------------------------------------
# Leads across a day, a week, and a daylight-saving transition.
# --------------------------------------------------------------------------------


def test_a_fourteen_hour_lead_puts_prep_in_the_previous_evening_and_the_previous_week() -> None:
    anchor_type = a_type(ATTRIBUTED_EXAM)
    anchor = an_anchor(
        anchor_type, start=at(EXAM_MONDAY, 9, 30), minutes=120, title="Compilers Exam"
    )

    shadows = generate(anchor, anchor_type)
    prep = shadows.blocks[0]
    prep_week = IsoWeek.containing(prep.interval.start.astimezone(resolve_zone(LONDON)).date())

    assert wall(prep.interval.start) == "Sun 2026-02-08 19:30"
    assert wall(prep.interval.end) == "Sun 2026-02-08 20:30"
    assert prep_week.following() == IsoWeek.containing(EXAM_MONDAY)


def test_a_lead_across_a_spring_forward_gap_is_elapsed_time_rather_than_wall_time() -> None:
    # The transition is inside the lead, so 14 hours of elapsed time reaches back to 18:30 by the
    # clock rather than 19:30. Stated rather than corrected: a lead is a duration, and the hour
    # the clock skipped is an hour the person did not have.
    anchor_type = a_type(ATTRIBUTED_EXAM)
    anchor = an_anchor(
        anchor_type, start=at(SPRING_FORWARD, 9, 30), minutes=120, title="Compilers Exam"
    )

    prep = generate(anchor, anchor_type).blocks[0]

    assert (anchor.interval.start - prep.interval.start) == timedelta(minutes=840)
    assert wall(prep.interval.start) == "Sat 2026-03-28 18:30"


# --------------------------------------------------------------------------------
# Two commitments close together.
# --------------------------------------------------------------------------------


def a_journey_only_type(*, lead: int, duration: int) -> AnchorTypeRecord:
    """A declaration that casts one outbound leg and nothing else."""
    return a_type(
        replace(
            NOTHING,
            transit_lead_minutes=lead,
            transit_duration_minutes=duration,
            transit_area_id=TRANSIT,
        )
    )


def a_prep_only_type(*, lead: int, duration: int) -> AnchorTypeRecord:
    """A declaration that casts one prep block and nothing else."""
    return a_type(
        replace(
            NOTHING, prep_lead_minutes=lead, prep_duration_minutes=duration, prep_area_id=CAREER
        )
    )


def test_prep_gives_way_to_a_journey_even_when_prep_was_cast_first() -> None:
    # The prep is cast by the EARLIER commitment, so cast order alone would keep it and drop the
    # journey. Transit outranks prep because a journey that no longer meets its commitment is not
    # a journey to it.
    prepares = a_prep_only_type(lead=120, duration=120)
    travels = a_journey_only_type(lead=60, duration=60)
    pair = [
        TypedAnchor(an_anchor(prepares, start=at(INTERVIEW_DAY, 11, 30), minutes=60), prepares),
        TypedAnchor(an_anchor(travels, start=at(INTERVIEW_DAY, 12), minutes=60), travels),
    ]

    shadows = regenerate(pair)

    assert spans(shadows) == (
        ("prep", NO_OCCURRENCE, "Tue 2026-02-10 09:30", "Tue 2026-02-10 11:00"),
        ("transit", "out", "Tue 2026-02-10 11:00", "Tue 2026-02-10 12:00"),
    )


def test_the_later_cast_journey_is_truncated_to_the_earlier_one() -> None:
    earlier = a_journey_only_type(lead=120, duration=60)
    later = a_journey_only_type(lead=210, duration=120)
    pair = [
        TypedAnchor(an_anchor(later, start=at(INTERVIEW_DAY, 13), minutes=60), later),
        TypedAnchor(an_anchor(earlier, start=at(INTERVIEW_DAY, 12), minutes=60), earlier),
    ]

    shadows = regenerate(pair)

    assert spans(shadows) == (
        ("transit", "out", "Tue 2026-02-10 09:30", "Tue 2026-02-10 10:00"),
        ("transit", "out", "Tue 2026-02-10 10:00", "Tue 2026-02-10 11:00"),
    )


def test_two_blocks_beginning_at_the_same_instant_drop_one_and_raise_nothing() -> None:
    # A truncation to exactly the surviving block's start would ask for a zero-length interval,
    # which the interval algebra refuses by construction. The block is dropped before any
    # interval is built, so the collision answers rather than raises.
    travels = a_journey_only_type(lead=120, duration=60)
    prepares = a_prep_only_type(lead=360, duration=120)
    pair = [
        TypedAnchor(an_anchor(travels, start=at(INTERVIEW_DAY, 12), minutes=60), travels),
        TypedAnchor(an_anchor(prepares, start=at(INTERVIEW_DAY, 16), minutes=60), prepares),
    ]

    shadows = regenerate(pair)

    assert spans(shadows) == (("transit", "out", "Tue 2026-02-10 10:00", "Tue 2026-02-10 11:00"),)


@pytest.mark.parametrize(
    ("prep_lead", "prep_duration", "expected"),
    [
        (370, 40, ()),
        (375, 45, (("prep", NO_OCCURRENCE, "Tue 2026-02-10 09:45", "Tue 2026-02-10 10:00"),)),
    ],
    ids=["ten-minutes-left-is-dropped", "one-grid-step-left-is-kept"],
)
def test_a_block_truncated_below_one_grid_step_is_dropped(
    prep_lead: int, prep_duration: int, expected: tuple[tuple[str, str, str, str], ...]
) -> None:
    travels = a_journey_only_type(lead=120, duration=60)
    prepares = a_prep_only_type(lead=prep_lead, duration=prep_duration)
    pair = [
        TypedAnchor(an_anchor(travels, start=at(INTERVIEW_DAY, 12), minutes=60), travels),
        TypedAnchor(an_anchor(prepares, start=at(INTERVIEW_DAY, 16), minutes=60), prepares),
    ]

    shadows = regenerate(pair)
    prep = tuple(span for span in spans(shadows) if span[0] == "prep")

    assert prep == expected


def test_a_short_block_that_collided_with_nothing_is_kept_whole() -> None:
    # The grid step is the floor a TRUNCATION has to clear, not a minimum length for a buffer: a
    # commitment and everything derived from it are exempt from the grid.
    prepares = a_prep_only_type(lead=60, duration=SNAP_MINUTES - 10)
    anchor = an_anchor(prepares, start=at(INTERVIEW_DAY, 12), minutes=60)

    shadows = regenerate([TypedAnchor(anchor, prepares)])

    assert spans(shadows) == (
        ("prep", NO_OCCURRENCE, "Tue 2026-02-10 11:00", "Tue 2026-02-10 11:05"),
    )


def test_no_two_surviving_blocks_cover_the_same_minute() -> None:
    # The property the truncation exists to hold, over four commitments whose leads deliberately
    # reach across one another.
    declarations = [
        a_journey_only_type(lead=120, duration=60),
        a_journey_only_type(lead=210, duration=120),
        a_prep_only_type(lead=360, duration=180),
        a_prep_only_type(lead=300, duration=90),
    ]
    hours = (12, 13, 16, 15)
    anchors = [
        TypedAnchor(an_anchor(declared, start=at(INTERVIEW_DAY, hour), minutes=60), declared)
        for declared, hour in zip(declarations, hours, strict=True)
    ]

    blocks = regenerate(anchors).blocks

    assert blocks
    assert not [
        (one, other)
        for index, one in enumerate(blocks)
        for other in blocks[index + 1 :]
        if one.interval.overlaps(other.interval)
    ]


def test_two_windows_covering_the_same_minutes_are_both_kept_whole() -> None:
    # Windows are not contested. Nothing is scheduled in one, so two commitments reserving the
    # same time is a union rather than a collision, and each window still names its own
    # commitment for the gutter.
    quiet = a_type(replace(NOTHING, post_buffer_minutes=120, post_scope=FORBIDS_EVERYTHING))
    pair = [
        TypedAnchor(an_anchor(quiet, start=at(INTERVIEW_DAY, 16), minutes=60), quiet),
        TypedAnchor(an_anchor(quiet, start=at(INTERVIEW_DAY, 17, 30), minutes=30), quiet),
    ]

    shadows = regenerate(pair)

    assert spans(shadows) == (
        ("recovery", "all", "Tue 2026-02-10 17:00", "Tue 2026-02-10 19:00"),
        ("recovery", "all", "Tue 2026-02-10 18:00", "Tue 2026-02-10 20:00"),
    )


# --------------------------------------------------------------------------------
# The spans a reader subtracts, unioned per scope.
# --------------------------------------------------------------------------------


def test_two_overlapping_absolute_windows_are_not_subtracted_twice() -> None:
    quiet = a_type(replace(NOTHING, post_buffer_minutes=120, post_scope=FORBIDS_EVERYTHING))
    pair = [
        TypedAnchor(an_anchor(quiet, start=at(INTERVIEW_DAY, 16), minutes=60), quiet),
        TypedAnchor(an_anchor(quiet, start=at(INTERVIEW_DAY, 17, 30), minutes=30), quiet),
    ]

    absolute = regenerate(pair).absolute_forbidden()

    # 17:00 to 20:00 unioned. Summed, the two 120-minute windows would subtract 240.
    assert len(absolute) == 1
    assert absolute.total_minutes() == 3 * MINUTES_IN_AN_HOUR


def test_a_window_scoped_to_named_areas_is_not_subtracted_from_the_denominator() -> None:
    # Some Area can still claim that time, so it stays in the denominator and comes out of the
    # per-Area read instead. Both halves are asserted, because the pair is the rule.
    _, shadows = an_interview_anchor(ATTRIBUTED_INTERVIEW)

    assert not shadows.absolute_forbidden()
    assert shadows.forbidden_for(STUDY).total_minutes() == 75


def test_an_unattributed_buffer_is_subtracted_like_a_window_that_forbids_everything() -> None:
    _, shadows = an_interview_anchor(INTERVIEW)

    # Prep and the leg have no Area to charge their minutes to, so no Area can claim those spans:
    # 30 minutes each, and the areas-scoped recovery is not among them.
    assert shadows.absolute_forbidden().total_minutes() == 60


# --------------------------------------------------------------------------------
# Regeneration is wholesale.
# --------------------------------------------------------------------------------


def test_regenerating_one_commitment_equals_generating_it() -> None:
    anchor_type = a_type(ATTRIBUTED_INTERVIEW)
    anchor = an_anchor(anchor_type, start=at(INTERVIEW_DAY, 16))

    assert regenerate([TypedAnchor(anchor, anchor_type)]) == generate(anchor, anchor_type)


def test_a_commitment_that_moved_regenerates_rather_than_patches() -> None:
    anchor_type = a_type(ATTRIBUTED_INTERVIEW)
    before = an_anchor(anchor_type, start=at(INTERVIEW_DAY, 16))
    after = replace(
        before,
        interval=Interval(at(INTERVIEW_DAY, 9), at(INTERVIEW_DAY, 9) + timedelta(minutes=45)),
    )

    moved = regenerate([TypedAnchor(after, anchor_type)])

    assert moved == generate(after, anchor_type)
    assert not set(moved.blocks) & set(regenerate([TypedAnchor(before, anchor_type)]).blocks)


def test_a_retyped_commitment_casts_what_the_new_type_declares() -> None:
    was = a_type(ATTRIBUTED_INTERVIEW)
    now = a_type(replace(ATTRIBUTED_LECTURE, return_transit_minutes=30))
    anchor = an_anchor(was, start=at(INTERVIEW_DAY, 16))
    retyped = replace(anchor, anchor_type_id=now.id)

    assert regenerate([TypedAnchor(retyped, now)]) == generate(retyped, now)
    assert keys(generate(retyped, now)) == (
        ("transit", TransitLeg.OUT.value),
        ("transit", TransitLeg.BACK.value),
    )


def test_an_empty_span_of_commitments_casts_nothing() -> None:
    assert regenerate([]) == ShadowSet.EMPTY


# --------------------------------------------------------------------------------
# The pair a caller supplies has to be the pair the commitment carries.
# --------------------------------------------------------------------------------


def test_a_type_the_commitment_does_not_carry_is_refused() -> None:
    carried = a_type(ATTRIBUTED_INTERVIEW)
    other = a_type(ATTRIBUTED_EXAM)
    anchor = an_anchor(carried, start=at(INTERVIEW_DAY, 16))

    with pytest.raises(ShadowPairingRejected):
        generate(anchor, other)


def test_a_typed_commitment_paired_with_no_type_is_refused() -> None:
    # Answering with an empty set would silently lose the commitment's own prep, transit and
    # recovery, which reads on the grid as a type the user never declared.
    carried = a_type(ATTRIBUTED_INTERVIEW)
    anchor = an_anchor(carried, start=at(INTERVIEW_DAY, 16))

    with pytest.raises(ShadowPairingRejected):
        generate(anchor, None)


def test_an_untyped_commitment_paired_with_a_type_is_refused() -> None:
    anchor = an_anchor(None, start=at(INTERVIEW_DAY, 16))

    with pytest.raises(ShadowPairingRejected):
        generate(anchor, a_type(ATTRIBUTED_INTERVIEW))


# --------------------------------------------------------------------------------
# The two tables this file reads, against the inventory each is stated over.
# --------------------------------------------------------------------------------


def test_every_forbidden_kind_has_a_reason_a_gutter_can_read() -> None:
    assert set(REASON_BY_KIND) == set(ForbiddenKind)


def test_every_origin_a_shadow_block_can_carry_has_a_precedence() -> None:
    assert set(shadow_collisions.PRECEDENCE_BY_ORIGIN) == DERIVED_ORIGINS
