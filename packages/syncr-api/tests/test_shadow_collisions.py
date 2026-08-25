"""Two commitments close together, and which of the blocks they cast survives.

Every span is measured from one commitment's own time, so two commitments close together cast
blocks over the same minutes. A person cannot be in both, so one gives way, and which one is a
rule rather than an accident of the order the anchors were read in.

Five claims carry the file.

**Transit gives way last, even to prep that was cast first.** A journey's adjacency to its
commitment is what makes it a journey to it, where a prep lead is a preference about how far
ahead to prepare. So the case that matters is the one where cast order alone would decide the
other way.

**A prep block that gives way ends where the other begins.** The earlier-cast commitment keeps
what it cast; the later-cast prep is truncated to the survivor's start, and dropped when what is
left would be shorter than the grid's own step or nothing at all. The exact-collision case answers
rather than raises, which is the one the interval algebra would otherwise refuse.

**A leg that gives way is dropped whole**, because a journey that stops short of what it is a
journey to reaches nothing. Whole is the load-bearing word, so every assertion here is on the
surviving inventory: a truncation, a division into the pieces either side of an obstacle, and a
fragment left between two obstacles are three different survivors, and only an inventory tells
them apart from an absence.

**A short buffer that collided with nothing is kept whole.** The grid step is a floor on a
truncation, not a minimum length for a buffer: a commitment and everything derived from it are
exempt from the grid.

**Windows are not contested.** Nothing is scheduled in a forbidden window, so two commitments
reserving the same time is a union rather than a collision. The union is asserted where a reader
takes it, because subtracting both windows whole would take the shared minutes out twice.

The last section drives five thousand randomized arrangements through the same entry point, for
the claims an example cannot hold: survivors disjoint, one binding per survivor, every absence
paid for by a collision, and every leg either whole or gone. It counts the shapes the draw reached
and refuses a run whose reach collapsed, because a property over arrangements that never collide
passes for the wrong reason.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import timedelta
from itertools import combinations
from random import Random
from typing import TYPE_CHECKING, Final

import pytest

from syncr_api.anchors import shadow_collisions
from syncr_api.anchors.config import FORBIDS_EVERYTHING
from syncr_api.anchors.shadow_products import DERIVED_ORIGINS
from syncr_api.anchors.shadows import TypedAnchor, generate, regenerate
from syncr_domain.identity import NO_OCCURRENCE, Origin, TransitLeg
from syncr_domain.snap import SNAP, SNAP_MINUTES
from tests.anchor_specifications import (
    ATTRIBUTED_INTERVIEW,
    CAREER,
    INTERVIEW,
    NOTHING,
    STUDY,
    TRANSIT,
)
from tests.shadow_scenes import (
    INTERVIEW_DAY,
    a_journey_only_type,
    a_prep_only_type,
    a_type,
    an_anchor,
    an_interview_anchor,
    at,
    spans,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syncr_api.anchors.records import AnchorTypeRecord
    from syncr_api.anchors.shadow_products import ShadowBlock
    from syncr_domain.identity import BindingRef

MINUTES_IN_AN_HOUR = 60

# The recovery buffer two commitments in this file both declare, long enough that the second
# commitment's window starts inside the first one's.
QUIET_MINUTES = 120


def a_quiet_type() -> AnchorTypeRecord:
    """A declaration that casts nothing but a window forbidding every Area."""
    return a_type(
        replace(NOTHING, post_buffer_minutes=QUIET_MINUTES, post_scope=FORBIDS_EVERYTHING)
    )


def a_journey_home_only_type(*, minutes: int) -> AnchorTypeRecord:
    """A declaration that casts one journey home and nothing else."""
    return a_type(replace(NOTHING, return_transit_minutes=minutes, transit_area_id=TRANSIT))


# --------------------------------------------------------------------------------
# Which block gives way.
# --------------------------------------------------------------------------------


def test_prep_gives_way_to_a_journey_even_when_prep_was_cast_first() -> None:
    # The prep is cast by the EARLIER commitment, so cast order alone would keep it whole and drop
    # the journey entirely. Transit outranks prep because a journey that no longer meets its
    # commitment is not a journey to it.
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


def test_the_later_cast_journey_is_dropped_rather_than_truncated_to_the_earlier_one() -> None:
    # A truncation would leave the later-cast leg as 09:30-10:00: half an hour of reserved travel
    # that ends 90 minutes before the 13:00 commitment it is a journey to.
    earlier = a_journey_only_type(lead=120, duration=60)
    later = a_journey_only_type(lead=210, duration=120)
    # Supplied later-first, so the order the caller read them in is not what decides.
    pair = [
        TypedAnchor(
            an_anchor(later, start=at(INTERVIEW_DAY, 13), minutes=60, title="Later"), later
        ),
        TypedAnchor(
            an_anchor(earlier, start=at(INTERVIEW_DAY, 12), minutes=60, title="Earlier"), earlier
        ),
    ]

    shadows = regenerate(pair)

    assert spans(shadows) == (("transit", "out", "Tue 2026-02-10 10:00", "Tue 2026-02-10 11:00"),)
    # The title as well, for the same reason as the abutting case: an inventory of one leg cannot
    # say which commitment kept its journey, because both legs carry one origin and one key.
    assert [block.title for block in shadows.blocks] == ["Leave for Earlier"]


def test_two_blocks_beginning_at_the_same_instant_drop_one_and_raise_nothing() -> None:
    # A truncation to exactly the surviving block's start would ask for a zero-length interval,
    # which the interval algebra refuses by construction. The block is dropped before any interval
    # is built, so the collision answers rather than raises.
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
    prepares = a_prep_only_type(lead=60, duration=SNAP_MINUTES - 10)
    anchor = an_anchor(prepares, start=at(INTERVIEW_DAY, 12), minutes=60)

    shadows = regenerate([TypedAnchor(anchor, prepares)])

    assert spans(shadows) == (
        ("prep", NO_OCCURRENCE, "Tue 2026-02-10 11:00", "Tue 2026-02-10 11:05"),
    )


def test_a_block_gives_way_to_the_earliest_collision_rather_than_the_first_one_found() -> None:
    # The journeys are kept in cast order, and the commitment cast FIRST is the one whose journey
    # starts later, so a rule that stopped at the first collision it found would leave the prep
    # still covering the other journey. One pass is enough only against the earliest.
    close_journey = a_journey_only_type(lead=30, duration=30)
    distant_journey = a_journey_only_type(lead=180, duration=60)
    long_prep = a_prep_only_type(lead=480, duration=240)
    anchors = [
        TypedAnchor(
            an_anchor(close_journey, start=at(INTERVIEW_DAY, 11), minutes=60), close_journey
        ),
        TypedAnchor(
            an_anchor(distant_journey, start=at(INTERVIEW_DAY, 12), minutes=60), distant_journey
        ),
        TypedAnchor(an_anchor(long_prep, start=at(INTERVIEW_DAY, 16), minutes=60), long_prep),
    ]

    shadows = regenerate(anchors)

    assert spans(shadows) == (
        ("prep", NO_OCCURRENCE, "Tue 2026-02-10 08:00", "Tue 2026-02-10 09:00"),
        ("transit", "out", "Tue 2026-02-10 09:00", "Tue 2026-02-10 10:00"),
        ("transit", "out", "Tue 2026-02-10 10:30", "Tue 2026-02-10 11:00"),
    )


def test_no_two_surviving_blocks_cover_the_same_minute() -> None:
    # The property the rule exists to hold, over four commitments whose leads deliberately reach
    # across one another: one leg is dropped whole, one prep is truncated, and two survivors abut.
    #
    # The arrangement is chosen so that several blocks survive AND something was contested. An
    # arrangement that leaves one survivor holds this property with nothing to compare, which is the
    # way a disjointness test passes for the wrong reason.
    kept_leg = a_journey_only_type(lead=30, duration=30)
    colliding_leg = a_journey_only_type(lead=120, duration=120)
    reaching_prep = a_prep_only_type(lead=480, duration=240)
    clear_prep = a_prep_only_type(lead=300, duration=60)
    declarations = [kept_leg, colliding_leg, reaching_prep, clear_prep]
    hours = (11, 12, 15, 16)
    anchors = [
        TypedAnchor(an_anchor(declared, start=at(INTERVIEW_DAY, hour), minutes=30), declared)
        for declared, hour in zip(declarations, hours, strict=True)
    ]

    blocks = regenerate(anchors).blocks

    pairs = list(combinations(blocks, 2))
    assert pairs
    assert not [(one, other) for one, other in pairs if one.interval.overlaps(other.interval)]
    cast = sum(len(generate(pair.anchor, pair.anchor_type).blocks) for pair in anchors)
    assert len(blocks) < cast


def test_a_leg_that_can_no_longer_meet_its_commitment_is_absent_rather_than_early() -> None:
    # The abutting case, which is the only one that can show the fault: a leg with slack loses only
    # its slack. The 11:00 commitment declares a two-hour abutting journey; an earlier commitment at
    # 10:30 declares a half-hour one and keeps it.
    #
    # Truncating at the end would leave "Leave for Later" at 09:00-10:00, which reserves an hour of
    # travel, covers none of the hour before the commitment, and arrives an hour early. The whole
    # leg goes instead, so the inventory is the earlier commitment's leg and nothing else.
    later = a_journey_only_type(lead=120, duration=120)
    earlier = a_journey_only_type(lead=30, duration=30)
    pair = [
        TypedAnchor(
            an_anchor(later, start=at(INTERVIEW_DAY, 11), minutes=60, title="Later"), later
        ),
        TypedAnchor(
            an_anchor(earlier, start=at(INTERVIEW_DAY, 10, 30), minutes=30, title="Earlier"),
            earlier,
        ),
    ]

    shadows = regenerate(pair)

    assert spans(shadows) == (("transit", "out", "Tue 2026-02-10 10:00", "Tue 2026-02-10 10:30"),)
    # Titles as well as spans, because the two legs are the same origin and the same key: without
    # them an inventory of one leg cannot say WHICH commitment kept its journey.
    assert [block.title for block in shadows.blocks] == ["Leave for Earlier"]


def test_a_leg_reaching_over_two_kept_legs_leaves_no_fragment_between_them() -> None:
    # The arrangement that tells whole from partial. The spanning leg covers two kept legs and the
    # gap between them, so each shape leaves a different survivor: truncated at its end,
    # 09:00-10:00; divided at each obstacle, three pieces; dropped only as far as the first
    # obstacle, 10:30-11:30. An inventory of the two kept legs excludes all three at once.
    early = a_journey_only_type(lead=30, duration=30)
    middle = a_journey_only_type(lead=30, duration=30)
    spanning = a_journey_only_type(lead=300, duration=240)
    anchors = [
        TypedAnchor(
            an_anchor(early, start=at(INTERVIEW_DAY, 10, 30), minutes=30, title="Early"), early
        ),
        TypedAnchor(
            an_anchor(middle, start=at(INTERVIEW_DAY, 12), minutes=30, title="Middle"), middle
        ),
        TypedAnchor(
            an_anchor(spanning, start=at(INTERVIEW_DAY, 14), minutes=60, title="Spanning"), spanning
        ),
    ]

    shadows = regenerate(anchors)

    assert spans(shadows) == (
        ("transit", "out", "Tue 2026-02-10 10:00", "Tue 2026-02-10 10:30"),
        ("transit", "out", "Tue 2026-02-10 11:30", "Tue 2026-02-10 12:00"),
    )
    assert [block.title for block in shadows.blocks] == ["Leave for Early", "Leave for Middle"]


def test_the_drop_takes_the_leg_and_leaves_the_rest_of_what_that_commitment_cast() -> None:
    # Whole cuts both ways: the leg goes entirely, and nothing else of that commitment goes with it.
    # The 12:00 commitment's prep and its journey home are cast by the same anchor as the leg that
    # collided, and one of them is a leg too, so a drop keyed on the commitment or on the origin
    # rather than on the block would take all three.
    travelling = a_type(
        replace(
            NOTHING,
            prep_lead_minutes=240,
            prep_duration_minutes=60,
            prep_area_id=CAREER,
            transit_lead_minutes=120,
            transit_duration_minutes=120,
            return_transit_minutes=30,
            transit_area_id=TRANSIT,
        )
    )
    earlier = a_journey_only_type(lead=30, duration=30)
    pair = [
        TypedAnchor(
            an_anchor(travelling, start=at(INTERVIEW_DAY, 12), minutes=60, title="Travelling"),
            travelling,
        ),
        TypedAnchor(
            an_anchor(earlier, start=at(INTERVIEW_DAY, 11), minutes=30, title="Earlier"), earlier
        ),
    ]

    shadows = regenerate(pair)

    assert spans(shadows) == (
        ("prep", NO_OCCURRENCE, "Tue 2026-02-10 08:00", "Tue 2026-02-10 09:00"),
        ("transit", "out", "Tue 2026-02-10 10:30", "Tue 2026-02-10 11:00"),
        ("transit", "back", "Tue 2026-02-10 13:00", "Tue 2026-02-10 13:30"),
    )
    assert [block.title for block in shadows.blocks] == [
        "Prep for Travelling",
        "Leave for Earlier",
        "Go Home",
    ]


def test_a_prep_truncates_in_the_same_pass_that_drops_a_leg() -> None:
    # The direction is per origin rather than per collision, so one arrangement has to make the two
    # readings disagree: the leg and the prep reach over the same kept leg, and only the prep
    # survives as a shorter block. Truncating both, or dropping both, reds here.
    #
    # The prep ends at 10:30 rather than at 10:00 because the dropped leg reserves nothing for the
    # prep to give way to, which is the one pass reading what the pass before it decided.
    kept = a_journey_only_type(lead=30, duration=30)
    colliding_leg = a_journey_only_type(lead=120, duration=120)
    colliding_prep = a_prep_only_type(lead=420, duration=180)
    anchors = [
        TypedAnchor(an_anchor(kept, start=at(INTERVIEW_DAY, 11), minutes=30, title="Kept"), kept),
        TypedAnchor(
            an_anchor(colliding_leg, start=at(INTERVIEW_DAY, 12), minutes=60, title="Leg"),
            colliding_leg,
        ),
        TypedAnchor(
            an_anchor(colliding_prep, start=at(INTERVIEW_DAY, 16), minutes=60, title="Prep"),
            colliding_prep,
        ),
    ]

    shadows = regenerate(anchors)

    assert spans(shadows) == (
        ("prep", NO_OCCURRENCE, "Tue 2026-02-10 09:00", "Tue 2026-02-10 10:30"),
        ("transit", "out", "Tue 2026-02-10 10:30", "Tue 2026-02-10 11:00"),
    )


def test_a_journey_home_that_gives_way_is_dropped_like_the_outbound_leg() -> None:
    # The rule is keyed to the origin, which both legs carry, so the journey home has to be asserted
    # separately: a rule keyed to the occurrence key instead would truncate this one to 11:00-13:00
    # and leave the user travelling home for two hours they cannot travel in.
    #
    # A four-hour commitment is cast first and keeps its 13:00 journey home. A shorter commitment
    # inside it declares a three-hour one from 11:00, which reaches into the survivor.
    long_commitment = a_journey_home_only_type(minutes=60)
    inner = a_journey_home_only_type(minutes=180)
    keeps_its_journey_home = an_anchor(
        long_commitment, start=at(INTERVIEW_DAY, 9), minutes=240, title="All Day"
    )
    gives_way = an_anchor(inner, start=at(INTERVIEW_DAY, 10), minutes=60, title="Inner")
    pair = [
        TypedAnchor(keeps_its_journey_home, long_commitment),
        TypedAnchor(gives_way, inner),
    ]

    shadows = regenerate(pair)

    assert spans(shadows) == (("transit", "back", "Tue 2026-02-10 13:00", "Tue 2026-02-10 14:00"),)
    # Both journeys home are titled "Go Home", so the commitment is what tells them apart.
    assert [block.anchor_id for block in shadows.blocks] == [keeps_its_journey_home.id]


def test_the_dropped_leg_is_reported_beside_the_survivors() -> None:
    """A drop is carried, not implied by an absence: the block that lost is named.

    The arrangement is the later-cast journey that loses to the earlier one, and what is asserted
    is the report rather than the inventory: a reader on that day has to be able to tell a
    declared journey that did not survive from a journey no type ever declared, which an absence
    alone cannot say.
    """
    earlier = a_journey_only_type(lead=120, duration=60)
    later = a_journey_only_type(lead=210, duration=120)
    keeps = an_anchor(earlier, start=at(INTERVIEW_DAY, 12), minutes=60, title="Earlier")
    loses = an_anchor(later, start=at(INTERVIEW_DAY, 13), minutes=60, title="Later")

    shadows = regenerate([TypedAnchor(loses, later), TypedAnchor(keeps, earlier)])

    assert [block.title for block in shadows.dropped_legs] == ["Leave for Later"]
    assert [(block.origin, block.occurrence_key) for block in shadows.dropped_legs] == [
        (Origin.TRANSIT, TransitLeg.OUT.value)
    ]
    assert [block.anchor_id for block in shadows.dropped_legs] == [loses.id]


def test_a_prep_truncated_to_nothing_is_not_reported_as_a_dropped_leg() -> None:
    """A prep with less than one grid step left is an absence too small to explain.

    Nothing drawable was lost, so reporting it would state that a declared journey was dropped
    when what happened is that a preference about how far ahead to prepare gave way entirely.
    """
    travels = a_journey_only_type(lead=120, duration=60)
    prepares = a_prep_only_type(lead=370, duration=40)
    pair = [
        TypedAnchor(an_anchor(travels, start=at(INTERVIEW_DAY, 12), minutes=60), travels),
        TypedAnchor(an_anchor(prepares, start=at(INTERVIEW_DAY, 16), minutes=60), prepares),
    ]

    shadows = regenerate(pair)

    assert shadows.dropped_legs == ()


def test_every_origin_a_shadow_block_can_carry_has_a_precedence() -> None:
    # The table is bounded by what a block may BE rather than by a list of what it may not, so a
    # block whose origin has no precedence cannot reach the collision rule at all.
    assert set(shadow_collisions.PRECEDENCE_BY_ORIGIN) == DERIVED_ORIGINS


def test_every_origin_a_shadow_block_can_carry_states_how_it_gives_way() -> None:
    # The second table is bounded the same way and for the same reason: an origin missing from it
    # would give way by whatever the lookup fell back to, which is a rule nobody wrote down.
    assert set(shadow_collisions.GIVES_WAY_BY_ORIGIN) == DERIVED_ORIGINS


# --------------------------------------------------------------------------------
# Windows, which are unioned rather than contested.
# --------------------------------------------------------------------------------


def test_two_windows_covering_the_same_minutes_are_both_kept_whole() -> None:
    # Each window still names its own commitment, so the gutter can say which one reserved the
    # time even where two of them reserved it.
    quiet = a_quiet_type()
    pair = [
        TypedAnchor(an_anchor(quiet, start=at(INTERVIEW_DAY, 16), minutes=60), quiet),
        TypedAnchor(an_anchor(quiet, start=at(INTERVIEW_DAY, 17, 30), minutes=30), quiet),
    ]

    shadows = regenerate(pair)

    assert spans(shadows) == (
        ("recovery", "all", "Tue 2026-02-10 17:00", "Tue 2026-02-10 19:00"),
        ("recovery", "all", "Tue 2026-02-10 18:00", "Tue 2026-02-10 20:00"),
    )


def test_two_overlapping_absolute_windows_are_not_subtracted_twice() -> None:
    quiet = a_quiet_type()
    pair = [
        TypedAnchor(an_anchor(quiet, start=at(INTERVIEW_DAY, 16), minutes=60), quiet),
        TypedAnchor(an_anchor(quiet, start=at(INTERVIEW_DAY, 17, 30), minutes=30), quiet),
    ]

    absolute = regenerate(pair).absolute_forbidden()

    # 17:00 to 20:00, as one span. Summed, the two 120-minute windows would subtract 240 minutes
    # from a denominator that only lost 180.
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
    # 30 minutes each, and the areas-scoped recovery window is not among them.
    assert shadows.absolute_forbidden().total_minutes() == 60


# --------------------------------------------------------------------------------
# The same rule over five thousand randomized arrangements.
# --------------------------------------------------------------------------------

CASES: Final = 5000
# Fixed, so a failure is reproducible and today's green run is the one that runs tomorrow.
DRAW_SEED: Final = 20260210

# The quarter hours a commitment can begin on, from 08:00, and how long it runs. Coarse on purpose:
# a draw over every minute would almost never place two blocks at one instant, which is the shape
# the exact-collision case is about.
STARTING_SLOTS: Final = 32
MINUTES_A_COMMITMENT_RUNS: Final = (15, 30, 45, 60)
# How many commitments one arrangement holds. Two is the fewest that can collide at all.
COMMITMENTS_AT_LEAST: Final = 2
COMMITMENTS_AT_MOST: Final = 4
# A buffer's length, and the slack a lead carries over the duration it has to clear.
BUFFER_MINUTES: Final = (15, 30, 60, 120)
LEAD_SLACK_MINUTES: Final = (0, 15, 60)

A_DROPPED_LEG: Final = "a leg dropped whole"
A_DROPPED_JOURNEY_HOME: Final = "a journey home dropped whole"
A_TRUNCATED_PREP: Final = "a prep truncated to a survivor's start"
A_DROPPED_PREP: Final = "a prep dropped for want of one grid step"
A_LEG_OVER_TWO_KEPT_LEGS: Final = "a dropped leg reaching over two surviving legs"
A_LEG_DROPPED_WHERE_ONE_BEGINS: Final = "a leg dropped where a surviving leg begins"
TWO_BLOCKS_SHARING_A_START: Final = "two cast blocks beginning at the same instant"
# What the draw has to produce for the properties above it to mean anything. Every member is a shape
# some other reading of the rule would answer differently, so a draw that reaches none of them
# certifies nothing and this run says so rather than passing.
SHAPES_THE_DRAW_MUST_REACH: Final = (
    A_DROPPED_LEG,
    A_DROPPED_JOURNEY_HOME,
    A_TRUNCATED_PREP,
    A_DROPPED_PREP,
    A_LEG_OVER_TWO_KEPT_LEGS,
    A_LEG_DROPPED_WHERE_ONE_BEGINS,
    TWO_BLOCKS_SHARING_A_START,
)


def test_five_thousand_randomized_arrangements_hold_the_rule_and_reach_every_shape() -> None:
    draw = Random(DRAW_SEED)  # noqa: S311 - a fixed draw of arrangements, not a secret
    reached: Counter[str] = Counter()

    for case in range(CASES):
        anchors = _an_arrangement(draw, case)
        generated = [
            block for pair in anchors for block in generate(pair.anchor, pair.anchor_type).blocks
        ]
        cast = {block.binding: block for block in generated}
        # Keyed by binding, so two blocks sharing one would collapse into a single entry and the
        # absence checks below would never see the second. One binding per cast block is what the
        # occurrence key exists to give, and it is asserted rather than assumed.
        assert len(cast) == len(generated)

        survivors = regenerate(anchors).blocks

        _assert_the_rule_holds(cast, survivors)
        reached.update(_shapes_reached(cast, survivors))

    unreached = [shape for shape in SHAPES_THE_DRAW_MUST_REACH if not reached[shape]]
    assert not unreached, f"{CASES} arrangements produced none of: {unreached}"


def _assert_the_rule_holds(
    cast: Mapping[BindingRef, ShadowBlock], survivors: tuple[ShadowBlock, ...]
) -> None:
    """Every claim the rule makes, over one arrangement."""
    assert not [
        (one, other)
        for one, other in combinations(survivors, 2)
        if one.interval.overlaps(other.interval)
    ]
    # Two pieces of one buffer would take one BlockId, so a division reads as a repeated binding.
    assert len({block.binding for block in survivors}) == len(survivors)
    for block in survivors:
        as_cast = cast[block.binding]
        assert block.interval.start == as_cast.interval.start
        assert block.interval.end <= as_cast.interval.end
        # A leg is whole or it is gone, and anything shorter than it was cast is a prep with at
        # least one grid step of it left.
        assert block.origin is not Origin.TRANSIT or block.interval == as_cast.interval
        whole = block.interval == as_cast.interval
        assert whole or block.interval.end - block.interval.start >= SNAP
    surviving = {block.binding for block in survivors}
    for binding, absent in cast.items():
        if binding in surviving:
            continue
        # Nothing gives way to nothing: an absence is only ever the price of a collision, and the
        # collision a leg pays is always with another leg, because every leg is fitted first.
        obstacles = [one for one in survivors if one.interval.overlaps(absent.interval)]
        assert obstacles
        assert absent.origin is not Origin.TRANSIT or [
            one for one in obstacles if one.origin is Origin.TRANSIT
        ]


def _shapes_reached(
    cast: Mapping[BindingRef, ShadowBlock], survivors: tuple[ShadowBlock, ...]
) -> set[str]:
    """Which of the shapes worth reaching this one arrangement produced."""
    surviving = {block.binding: block for block in survivors}
    absent = [block for binding, block in cast.items() if binding not in surviving]
    shapes = {
        A_DROPPED_LEG: [one for one in absent if one.origin is Origin.TRANSIT],
        A_DROPPED_JOURNEY_HOME: [
            one
            for one in absent
            if one.origin is Origin.TRANSIT and one.occurrence_key == TransitLeg.BACK.value
        ],
        A_DROPPED_PREP: [one for one in absent if one.origin is Origin.PREP],
        A_TRUNCATED_PREP: [
            binding
            for binding, block in surviving.items()
            if block.interval != cast[binding].interval
        ],
        # Surviving LEGS rather than survivors: a prep is fitted after every leg, so counting any
        # survivor lets a leg that met one obstacle satisfy a row about meeting two. Two obstacles
        # is the shape that tells the partial readings apart from each other.
        A_LEG_OVER_TWO_KEPT_LEGS: [
            one
            for one in absent
            if one.origin is Origin.TRANSIT
            and len(
                [
                    kept
                    for kept in survivors
                    if kept.origin is Origin.TRANSIT and kept.interval.overlaps(one.interval)
                ]
            )
            > 1
        ],
        # The exact-collision shape on the transit side, where the old truncation would have asked
        # for a zero-length span. Kept apart from the cast-side row below, which counts any two
        # blocks at one instant whether or not either gave way.
        A_LEG_DROPPED_WHERE_ONE_BEGINS: [
            one
            for one in absent
            if one.origin is Origin.TRANSIT
            and [
                kept
                for kept in survivors
                if kept.origin is Origin.TRANSIT and kept.interval.start == one.interval.start
            ]
        ],
        TWO_BLOCKS_SHARING_A_START: [
            (one, other)
            for one, other in combinations(cast.values(), 2)
            if one.interval.start == other.interval.start
        ],
    }
    return {shape for shape, found in shapes.items() if found}


def _an_arrangement(draw: Random, case: int) -> list[TypedAnchor]:
    """The commitments of one arrangement, each carrying a declaration of its own.

    Named rather than inlined into the loop because it is what the draw REACHES, and a reader
    measuring that reach has to be able to run this and not a copy of it.
    """
    return [
        _a_typed_anchor(draw, f"case {case} commitment {member}")
        for member in range(draw.randint(COMMITMENTS_AT_LEAST, COMMITMENTS_AT_MOST))
    ]


def _a_typed_anchor(draw: Random, title: str) -> TypedAnchor:
    """One commitment on the reference day, carrying a declaration of a random kind."""
    declared = _a_declaration(draw)
    start = at(INTERVIEW_DAY, 8) + timedelta(minutes=SNAP_MINUTES * draw.randrange(STARTING_SLOTS))
    minutes = draw.choice(MINUTES_A_COMMITMENT_RUNS)
    return TypedAnchor(an_anchor(declared, start=start, minutes=minutes, title=title), declared)


def _a_declaration(draw: Random) -> AnchorTypeRecord:
    """A leg, a prep, or a commitment declaring prep and both legs, as a stored row.

    Every lead is derived from the durations it has to clear rather than drawn beside them, so the
    draw spends none of its cases on declarations the boundary rules would refuse.
    """
    journey = draw.choice(BUFFER_MINUTES)
    prep = draw.choice(BUFFER_MINUTES)
    slack = draw.choice(LEAD_SLACK_MINUTES)
    kind = draw.choice(("a leg", "a prep", "both and a journey home"))
    if kind == "a leg":
        return a_journey_only_type(lead=journey + slack, duration=journey)
    if kind == "a prep":
        return a_prep_only_type(lead=prep + slack, duration=prep)
    return a_type(
        replace(
            NOTHING,
            prep_lead_minutes=prep + journey + slack + slack,
            prep_duration_minutes=prep,
            prep_area_id=CAREER,
            transit_lead_minutes=journey + slack,
            transit_duration_minutes=journey,
            return_transit_minutes=draw.choice(BUFFER_MINUTES),
            transit_area_id=TRANSIT,
        )
    )
