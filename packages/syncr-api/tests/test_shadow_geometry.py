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
own against a declaration that still casts something else, so a collapsed product reads as an
absence rather than as an empty answer.

**One anchor's two journeys are two blocks.** The occurrence key is asserted through the identity
it produces, because deriving one identity between the two is the failure it exists to prevent.

**An anchor's own blocks are exempt from its own recovery window.** Recovery is measured from the
commitment's end and so is the journey home, so the two overlap by construction. The exemption is
asserted with a positive control: another commitment's window over the same span does forbid it.

**A lead crossing a boundary is arithmetic, not a special case.** A 14-hour lead lands prep in the
previous ISO week, and a lead crossing a daylight-saving gap lands where elapsed time puts it
rather than where the wall clock would.

**A shadow is derived, so regeneration is wholesale, and the pair it reads has to agree.**
Regenerating one commitment equals generating it; a commitment that moved keeps none of the spans
it cast before; and a commitment paired with a type it does not carry is refused rather than
answered, because both ways of disagreeing cast one commitment's buffers around another's.

**Two commitments close together are not here.** Which block gives way when their shadows cover
the same minutes is stated in ``test_shadow_collisions.py``, beside the module that decides it.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from typing import TYPE_CHECKING, Final
from uuid import uuid4

import pytest

from syncr_api.anchors.config import FORBIDS_AREAS, FORBIDS_EVERYTHING, FORBIDS_NOTHING
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
from syncr_api.core.errors import ValidationFailed
from syncr_domain.gaps import ForbiddenKind, ForbiddenScope
from syncr_domain.identity import NO_OCCURRENCE, BindingError, Origin, TransitLeg, block_id
from syncr_domain.intervals import Interval
from syncr_domain.weeks import IsoWeek
from syncr_domain.zones import resolve_zone
from tests.anchor_specifications import (
    ATTRIBUTED_EXAM,
    ATTRIBUTED_GEOMETRY,
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
from tests.shadow_scenes import (
    COMMITMENT,
    EXAM_MONDAY,
    INTERVIEW_DAY,
    LONDON,
    SPRING_FORWARD,
    a_type,
    an_anchor,
    an_interview_anchor,
    at,
    keys,
    spans,
    wall,
)

if TYPE_CHECKING:
    from syncr_api.anchors.config import PostScope
    from syncr_api.anchors.records import AnchorTypeSpecification

# Every origin a block can carry that an anchor does not cast. Named as the complement of what a
# shadow IS, so an eighth origin joins this list without anybody remembering to add it.
NOT_CAST_BY_AN_ANCHOR: Final = tuple(sorted(set(Origin) - DERIVED_ORIGINS, key=str))

# The transitions a lead is read across, and the wall time a 14-hour one lands on. An hour-long
# transition cannot show what a 30-minute one does, and neither shows what one falling at midnight
# does, so all three zones are here in both directions.
TRANSITIONS = [
    pytest.param(LONDON, SPRING_FORWARD, "Sat 2026-03-28 18:30", id="london-hour-gap"),
    pytest.param(LONDON, date(2026, 10, 25), "Sat 2026-10-24 20:30", id="london-hour-fold"),
    pytest.param(
        "Australia/Lord_Howe", date(2026, 10, 4), "Sat 2026-10-03 19:00", id="lord-howe-30m-gap"
    ),
    pytest.param(
        "Australia/Lord_Howe", date(2026, 4, 5), "Sat 2026-04-04 20:00", id="lord-howe-30m-fold"
    ),
    pytest.param(
        "America/Havana", date(2026, 3, 8), "Sat 2026-03-07 18:30", id="havana-midnight-gap"
    ),
    pytest.param(
        "America/Havana", date(2026, 11, 1), "Sat 2026-10-31 20:30", id="havana-midnight-fold"
    ),
]


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
    # The two readings of "which commitment" agree, because the binding is built from the same
    # identifier: a reader holding a plan block finds the anchor at `binding.entity_id`, and a
    # reader holding the buffer finds it at `anchor_id`.
    assert {block.binding.entity_id for block in shadows.blocks} == {anchor.id}


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
# One rule decides block or band: each branch, both directions.
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


def test_a_window_that_forbids_everything_forbids_an_area_declared_after_it() -> None:
    # `all` is not a longer list of Areas, it is the answer that no Area may claim the time. A
    # window generated before an Area existed still forbids that Area, which is what makes the
    # scope a choice the user made rather than a list that happens to be empty.
    declaration = replace(NOTHING, post_buffer_minutes=60, post_scope=FORBIDS_EVERYTHING)
    _, shadows = an_interview_anchor(declaration)
    declared_later = uuid4()

    assert shadows.forbidden_for(declared_later).total_minutes() == 60
    assert shadows.forbidden_for(CAREER).total_minutes() == 60


def test_a_window_names_the_reason_and_the_commitment_that_reserved_the_time() -> None:
    anchor, shadows = an_interview_anchor(INTERVIEW)

    assert [window.label for window in shadows.forbidden] == [
        f"prep · {COMMITMENT}",
        f"transit · {COMMITMENT}",
        f"recovery · {COMMITMENT}",
    ]
    assert {window.anchor_id for window in shadows.forbidden} == {anchor.id}


def test_an_unattributed_return_leg_is_a_window_like_the_outbound_one() -> None:
    # The rendered Exam declares both legs and names no Area for either, so it casts TWO
    # `transit_unattributed` windows. They carry the same label and different spans, because a
    # window explains why time is reserved rather than which journey reserved it: the leg's own
    # identity belongs to a block, and this declaration casts none.
    anchor_type = a_type(EXAM)
    anchor = an_anchor(
        anchor_type, start=at(EXAM_MONDAY, 9, 30), minutes=120, title="Compilers Exam"
    )

    shadows = generate(anchor, anchor_type)

    assert spans(shadows) == (
        ("prep_unattributed", "all", "Sun 2026-02-08 19:30", "Sun 2026-02-08 20:30"),
        ("transit_unattributed", "all", "Mon 2026-02-09 08:45", "Mon 2026-02-09 09:15"),
        ("transit_unattributed", "all", "Mon 2026-02-09 11:30", "Mon 2026-02-09 12:00"),
        ("recovery", "areas", "Mon 2026-02-09 11:30", "Mon 2026-02-09 12:30"),
    )
    assert {window.label for window in shadows.forbidden} == {
        "prep · Compilers Exam",
        "transit · Compilers Exam",
        "recovery · Compilers Exam",
    }


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
def test_a_recovery_window_needs_both_a_buffer_and_a_scope(
    buffer_minutes: int, scope: PostScope
) -> None:
    declaration = replace(
        NOTHING,
        transit_lead_minutes=30,
        transit_duration_minutes=30,
        transit_area_id=TRANSIT,
        post_buffer_minutes=buffer_minutes,
        post_scope=scope,
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
    anchor_type = a_type(ATTRIBUTED_LECTURE)
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
    leg's own Area would leave the journey home legal for a reason other than the exemption. The
    return leg is the fixture's own, since the rendered Lecture already declares one.
    """
    return replace(
        ATTRIBUTED_LECTURE,
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


@pytest.mark.parametrize(("zone", "on", "expected"), TRANSITIONS)
def test_a_lead_across_a_transition_is_elapsed_time_rather_than_wall_time(
    zone: str, on: date, expected: str
) -> None:
    # The transition sits inside the lead, so 14 hours of ELAPSED time reaches back to a different
    # wall time than 14 hours of clock subtraction would. Stated rather than corrected: a lead is a
    # duration, and an hour the clock skipped is an hour the person did not have.
    anchor_type = a_type(ATTRIBUTED_EXAM)
    anchor = an_anchor(
        anchor_type, start=at(on, 9, 30, zone=zone), minutes=120, title="Compilers Exam"
    )

    prep = generate(anchor, anchor_type).blocks[0]

    assert (anchor.interval.start - prep.interval.start) == timedelta(minutes=840)
    assert wall(prep.interval.start, zone=zone) == expected


# --------------------------------------------------------------------------------
# Regeneration is wholesale.
# --------------------------------------------------------------------------------


def test_regenerating_one_commitment_equals_generating_it() -> None:
    anchor_type = a_type(ATTRIBUTED_INTERVIEW)
    anchor = an_anchor(anchor_type, start=at(INTERVIEW_DAY, 16))

    assert regenerate([TypedAnchor(anchor, anchor_type)]) == generate(anchor, anchor_type)


@pytest.mark.parametrize("specification", ATTRIBUTED_GEOMETRY, ids=lambda spec: spec.name)
def test_one_commitments_own_blocks_never_cover_the_same_minute(
    specification: AnchorTypeSpecification,
) -> None:
    # This is what makes the equality above hold rather than happen to hold: only the many-anchor
    # path resolves collisions, so a regeneration of one commitment equals a generation of it
    # because a declaration cannot collide with itself.
    _, shadows = an_interview_anchor(specification)
    blocks = shadows.blocks

    assert blocks
    assert not [
        (one, other)
        for index, one in enumerate(blocks)
        for other in blocks[index + 1 :]
        if one.interval.overlaps(other.interval)
    ]


def test_the_declaration_that_would_break_that_is_refused_at_the_boundary() -> None:
    # Sixty minutes of prep starting sixty minutes out, against a journey leaving thirty minutes
    # out: prep would still be running when the journey left, and one commitment would cast two
    # overlapping blocks that only the many-anchor path resolves. What makes that unrepresentable is
    # the boundary rule, said again as a check constraint on the table, so a relaxation of either
    # reds this rather than silently changing what a regeneration produces.
    self_overlapping = replace(
        NOTHING,
        prep_lead_minutes=60,
        prep_duration_minutes=60,
        prep_area_id=CAREER,
        transit_lead_minutes=30,
        transit_duration_minutes=30,
        transit_area_id=TRANSIT,
    )

    with pytest.raises(ValidationFailed) as refused:
        a_type(self_overlapping)

    assert refused.value.errors is not None
    assert [error.field for error in refused.value.errors] == ["prepLeadMinutes"]


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
    now = a_type(ATTRIBUTED_LECTURE)
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
# The wording table, against the inventory it is stated over.
# --------------------------------------------------------------------------------


def test_every_forbidden_kind_has_a_reason_a_gutter_can_read() -> None:
    # Bounded by the kinds a window may BE rather than by the three this file happens to build, so
    # a fourth kind reds this rather than rendering a label nobody wrote.
    assert set(REASON_BY_KIND) == set(ForbiddenKind)
