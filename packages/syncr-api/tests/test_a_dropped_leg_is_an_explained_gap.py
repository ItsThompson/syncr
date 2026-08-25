"""A journey a collision dropped whole, as the explained gap the day renders.

The collision rule decides which leg survives; this is the crossing where that decision becomes
something a reader can see. A dropped leg reserves nothing and draws nothing, so without a stated
cause its span is pixel-identical to time no anchor type ever declared. What turns it into an
explained gap is one member of the reason vocabulary every other empty surface uses, charged to
the leg's own Area and rendered by whatever draws the day.

Three claims carry the file.

**The drop is reported with the cause it lost to.** The slot carries ``dropped_leg`` and the
leg's own Area: every contested leg had one, because a buffer whose type named no Area became a
forbidden window at generation and was never in a collision at all.

**A span declared off-plan suppresses the explanation along with everything else.** The user said
nothing is scheduled there; a gap that says a journey was lost would argue with them.

**The week's edge clips the explanation like it clips every product.** A journey half inside the
week explains only the minutes this week holds.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from syncr_api.anchors.shadows import TypedAnchor
from syncr_api.plans.calendar_occupancy import calendar_occupancy
from syncr_api.plans.materialization import OffPlanSuppression
from syncr_domain.gaps import EmptySlotReason
from syncr_domain.intervals import Interval
from syncr_domain.off_plan import OffPlanPeriod
from tests.anchor_specifications import TRANSIT
from tests.shadow_scenes import (
    INTERVIEW_DAY,
    a_journey_only_type,
    an_anchor,
    at,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_api.anchors.records import AnchorTypeRecord
    from syncr_domain.gaps import EmptySlot

MONDAY = INTERVIEW_DAY - timedelta(days=INTERVIEW_DAY.weekday())
NEXT_MONDAY = MONDAY + timedelta(days=7)


def colliding_pair() -> tuple[list[TypedAnchor], None]:
    """Two journeys over the same minutes: the earlier-cast keeps theirs, the later loses."""
    earlier = a_journey_only_type(lead=120, duration=60)
    later = a_journey_only_type(lead=210, duration=120)
    keeps = an_anchor(earlier, start=at(INTERVIEW_DAY, 12), minutes=60, title="Earlier")
    loses = an_anchor(later, start=at(INTERVIEW_DAY, 13), minutes=60, title="Later")
    return [TypedAnchor(keeps, earlier), TypedAnchor(loses, later)], None


def occupancy_of(
    loaded: Sequence[TypedAnchor],
    *,
    span: Interval,
    off_plan: OffPlanSuppression,
) -> tuple[tuple[EmptySlot, ...], tuple]:
    """The calendar half of one assembly, reduced to the two members this file asserts on."""
    occupancy = calendar_occupancy(tuple(loaded), span=span, off_plan=off_plan)
    return occupancy.dropped_legs, occupancy.shadow_blocks


def test_a_dropped_leg_is_an_explained_gap_charged_to_its_own_area() -> None:
    loaded, _ = colliding_pair()

    dropped, _ = occupancy_of(
        loaded, span=Interval(at(MONDAY, 0), at(NEXT_MONDAY, 0)), off_plan=OffPlanSuppression(())
    )

    assert [(slot.reason, slot.area_id) for slot in dropped] == [
        (EmptySlotReason.DROPPED_LEG, TRANSIT)
    ]
    # The whole of what the collision rule dropped, whole: 09:30-11:30 is exactly the later
    # commitment's declared outbound leg.
    assert [(str(slot.interval.start), str(slot.interval.end)) for slot in dropped] == [
        ("2026-02-10 09:30:00+00:00", "2026-02-10 11:30:00+00:00")
    ]


def test_an_off_plan_span_takes_the_explanation_with_everything_else() -> None:
    loaded, _ = colliding_pair()
    suppression = OffPlanSuppression(
        (OffPlanPeriod(interval=Interval(at(INTERVIEW_DAY, 9), at(INTERVIEW_DAY, 17))),)
    )

    dropped, blocks = occupancy_of(
        loaded, span=Interval(at(MONDAY, 0), at(NEXT_MONDAY, 0)), off_plan=suppression
    )

    assert dropped == ()
    assert blocks == ()


def test_the_weeks_edge_clips_the_explanation_like_every_other_product() -> None:
    loaded, _ = colliding_pair()

    dropped, _ = occupancy_of(
        loaded,
        span=Interval(at(INTERVIEW_DAY, 10, 30), at(NEXT_MONDAY, 0)),
        off_plan=OffPlanSuppression(()),
    )

    assert [(str(slot.interval.start), str(slot.interval.end)) for slot in dropped] == [
        ("2026-02-10 10:30:00+00:00", "2026-02-10 11:30:00+00:00")
    ]


def test_no_leg_dropped_means_no_gap_reported() -> None:
    """A day whose anchor types declare legs that all survive owes no cause for any absence."""
    declared: AnchorTypeRecord = a_journey_only_type(lead=60, duration=30)
    anchor = an_anchor(declared, start=at(INTERVIEW_DAY, 12), minutes=60)

    dropped, _ = occupancy_of(
        [TypedAnchor(anchor, declared)],
        span=Interval(at(MONDAY, 0), at(NEXT_MONDAY, 0)),
        off_plan=OffPlanSuppression(()),
    )

    assert dropped == ()
