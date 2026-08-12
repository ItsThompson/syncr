"""One week where a strong preferred window cannot be honored, for the yield's own rendering.

A yielded preference reports three clauses, and they are clauses the closed vocabulary already has
rather than a seventh kind:

```
Gym · Shoulder & Arms
  blocked      05:30-06:30  ·  anchor_overlap: Kontron Placement Interview
  blocked      13:15-14:15  ·  area_daily_cap: Fitness, 60m already placed
  dominant     timeOfDayMisfit  ·  62% of total cost
```

So this week is built to produce exactly those two refusals, in that order, and to leave the misfit
as the term that carries the cost.

## How each of the two windows comes to be offered at all

A gap is what construction offers a candidate, and an imported commitment is never part of one: the
anchors are subtracted from the claimable set before any gap exists. **So an offer refused by H1
cannot come from the packing phase**, and reproducing the first row means the early window has to
be offered by the phase that offers a declared span rather than a gap. That is slot binding: a
template slot is offered at the time the template fixed, whatever now holds it. The week therefore
declares a Fitness slot across the commitment, which is what a user who wants the gym at 05:30 has
in their template.

The second row is a gap, and the gap has to BEGIN at the midday window for the recorded span to be
that window: one offer is made per length at the earliest start a gap allows. A commitment ending
at 13:15 is what puts the gap's start there.

## Why the misfit is the term that dominates

Every other term is zero by construction, so the rendering is reproducible rather than incidental.
The Area's target is exactly the minutes the week places in it, so its budget deviation is zero.
There is no task, so nothing carries deadline risk or a split deficit. The occurrence is not debt
and its rotation is not behind, so staleness is zero. No revision has been approved, so churn is
zero. Both Fitness blocks sit on different days with a commitment between them, so no adjacency
crosses an Area.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final
from uuid import UUID

from syncr_domain.habits import BindingSource, Duration
from syncr_domain.identity import BindingRef
from syncr_domain.preferences import PreferenceOwner, PreferenceOwnerKind, PreferenceStrength
from syncr_solver.inputs import HabitOccurrence, ResolvedPreference
from tests.materialized_weeks import (
    FITNESS,
    a_concrete_entry,
    a_frame_entry,
    a_slot,
    an_anchor,
    an_area_budget,
    between,
    inputs,
)

if TYPE_CHECKING:
    from syncr_solver.inputs import SolveInputs

GYM: Final = UUID("00000000-0000-4000-8000-0000000000c1")
VARIANT: Final = "Shoulder & Arms"

# The two windows the Area declares. The first is spent by a commitment and the second by the
# Area's own daily cap, which is what leaves the occurrence nowhere preferred to go.
EARLY: Final = between(5.5, 6.5)
MIDDAY: Final = between(13.25, 14.25)

# What holds each of them, and the span that makes the midday gap begin at the window.
COMMITMENT: Final = "Kontron Placement Interview"
LECTURE: Final = "Systems Programming"
CAP_MINUTES: Final = 60

# Where the occurrence ends up: the first gap whose own start no rule refuses, which is the morning
# after the night the frame holds.
PLACED_AT: Final = between(7, 8, day=1)


def preference_yield_week(**overrides: object) -> SolveInputs:
    """A week whose only content is one Fitness occurrence with nowhere preferred to go."""
    stated: dict[str, object] = {
        "now": between(0, 1).start,
        "anchors": (
            an_anchor(interval=EARLY, title=COMMITMENT),
            an_anchor(interval=between(7.5, 13.25), title=LECTURE),
        ),
        "frame": (a_frame_entry(interval=between(23, 31), title="Sleep"),),
        "template_entries": (
            a_slot(interval=EARLY, area_id=FITNESS),
            a_concrete_entry(interval=between(6.5, 7.5), area_id=FITNESS, title="Stretch"),
        ),
        "habit_occurrences": (
            HabitOccurrence(
                binding=BindingRef.for_habit(GYM, index=0),
                duration=Duration.fixed(CAP_MINUTES),
                area_id=FITNESS,
                title="Gym",
                binding_source=BindingSource.ROTATION,
                variant=VARIANT,
            ),
        ),
        "areas": (
            an_area_budget(
                area_id=FITNESS,
                name="Fitness",
                target_minutes=2 * CAP_MINUTES,
                max_per_day_minutes=CAP_MINUTES,
            ),
        ),
        "preferences": (
            ResolvedPreference(
                owner=PreferenceOwner(kind=PreferenceOwnerKind.AREA, id=FITNESS),
                windows=(EARLY, MIDDAY),
                strength=PreferenceStrength.STRONG,
                preferred_duration_minutes=CAP_MINUTES,
            ),
        ),
    }
    stated.update(overrides)
    return inputs(**stated)
