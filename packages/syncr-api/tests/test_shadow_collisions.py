"""Two commitments close together, and which of the blocks they cast survives.

Every span is measured from one commitment's own time, so two commitments close together cast
blocks over the same minutes. A person cannot be in both, so one gives way, and which one is a
rule rather than an accident of the order the anchors were read in.

Four claims carry the file.

**Transit gives way last, even to prep that was cast first.** A journey's adjacency to its
commitment is what makes it a journey to it, where a prep lead is a preference about how far
ahead to prepare. So the case that matters is the one where cast order alone would decide the
other way.

**A block gives way by ending where the other begins.** The earlier-cast commitment keeps what it
cast; the later-cast block is truncated to the survivor's start, and dropped when what is left
would be shorter than the grid's own step or nothing at all. The exact-collision case answers
rather than raises, which is the one the interval algebra would otherwise refuse.

**A short buffer that collided with nothing is kept whole.** The grid step is a floor on a
truncation, not a minimum length for a buffer: a commitment and everything derived from it are
exempt from the grid.

**Windows are not contested.** Nothing is scheduled in a forbidden window, so two commitments
reserving the same time is a union rather than a collision. The union is asserted where a reader
takes it, because subtracting both windows whole would take the shared minutes out twice.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from syncr_api.anchors import shadow_collisions
from syncr_api.anchors.config import FORBIDS_EVERYTHING
from syncr_api.anchors.shadow_products import DERIVED_ORIGINS
from syncr_api.anchors.shadows import TypedAnchor, regenerate
from syncr_domain.identity import NO_OCCURRENCE
from syncr_domain.snap import SNAP_MINUTES
from tests.anchor_specifications import ATTRIBUTED_INTERVIEW, INTERVIEW, NOTHING, STUDY
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
    from syncr_api.anchors.records import AnchorTypeRecord

MINUTES_IN_AN_HOUR = 60

# The recovery buffer two commitments in this file both declare, long enough that the second
# commitment's window starts inside the first one's.
QUIET_MINUTES = 120


def a_quiet_type() -> AnchorTypeRecord:
    """A declaration that casts nothing but a window forbidding every Area."""
    return a_type(
        replace(NOTHING, post_buffer_minutes=QUIET_MINUTES, post_scope=FORBIDS_EVERYTHING)
    )


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


def test_the_later_cast_journey_is_truncated_to_the_earlier_one() -> None:
    earlier = a_journey_only_type(lead=120, duration=60)
    later = a_journey_only_type(lead=210, duration=120)
    # Supplied later-first, so the order the caller read them in is not what decides.
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


def test_every_origin_a_shadow_block_can_carry_has_a_precedence() -> None:
    # The table is bounded by what a block may BE rather than by a list of what it may not, so a
    # block whose origin has no precedence cannot reach the collision rule at all.
    assert set(shadow_collisions.PRECEDENCE_BY_ORIGIN) == DERIVED_ORIGINS


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
