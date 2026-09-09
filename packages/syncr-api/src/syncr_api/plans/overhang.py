"""The preceding week's frame occurrences, as the time they occupy in the week that follows.

A ``Sleep 23:00 + 8h`` on a Sunday runs into Monday, which is the next ISO week. The occurrence
belongs to the week its START falls in and is stored whole there, because clipping it would
truncate one night into two fragments: the block's duration would stop matching the routine, both
weeks' denominators would change, and confirmation would ask the user about two halves of one
night. So the week it runs into carries the SPANS instead. The time is genuinely occupied, and
nothing may be placed in it.

## The overhang is resolved exactly as its own week resolves it

This module re-resolves the preceding week's frame through the same function, the same zone
profile, the same clamp, that week's own off-plan periods, and that week's own approved
concessions, and then keeps the part that falls inside the week being assembled. That is what
makes the two answers one answer: a routine reduction approved for the preceding week shortens
the occurrence there, so an overhang computed from the unreduced declaration would occupy time
the concession freed, and the two weeks would disagree about how long one night was.

A candidate concession being evaluated is not folded here. A candidate is a decision about the
week being assembled, and the occurrence belongs to the week before it.

## One preceding week is enough, and a column bound is why

A routine runs for at most a day, so an occurrence starting on the preceding week's last date
ends at most a day into this one, and no occurrence from any earlier week can reach this week at
all. Reading one week back is therefore complete rather than a heuristic, and the bound that makes
it complete is a domain invariant on the routine's span.

## What crosses a week boundary, and where each one is answered

| Shape | Answered by |
|---|---|
| A frame occurrence | here |
| An off-plan period | one row, clipped per week, so each week reads its own part |
| An anchor and its shadows | the calendar resolution, which loads by overlap |
| A block the solver placed in the preceding week | its own week: solver placements cannot cross
  the week's span |
| A concrete template entry | here, labelled with the entry's resolved title |
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.plans.folding import Concessions, fold
from syncr_api.plans.materialization import OffPlanSuppression, frame_entries, periods_of
from syncr_domain.templates import TemplateEntryKind
from syncr_domain.weeks import active_zone_by_date, week_span
from syncr_solver.inputs import FrameOverhang

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_api.offplan.records import OffPlanPeriodRecord
    from syncr_api.routines.records import RoutineRecord
    from syncr_domain.intervals import Interval
    from syncr_domain.weeks import IsoWeek
    from syncr_domain.zones import ZoneProfile
    from syncr_solver.inputs import MaterializedEntry, WeekAdjustment


def frame_overhang(
    routines: Sequence[RoutineRecord],
    *,
    into: Interval,
    preceding: IsoWeek,
    profile: ZoneProfile,
    periods: Sequence[OffPlanPeriodRecord],
    adjustments: Sequence[WeekAdjustment],
) -> tuple[FrameOverhang, ...]:
    """The spans ``preceding``'s frame occupies inside ``into``, clipped to it.

    Empty for a week whose predecessor's occurrences all end inside it, which is every week of a
    tenant whose routines finish before local midnight.
    """
    span = week_span(preceding, profile)
    resolved = frame_entries(
        routines,
        dates=preceding.dates(),
        zone_by_date=active_zone_by_date(preceding, profile),
        off_plan=OffPlanSuppression(periods_of(periods, span)),
    )
    folded = fold(
        adjustments,
        Concessions(frame=resolved, eligible_tasks=(), demands=(), areas=()),
    )
    return tuple(
        FrameOverhang(interval=inside)
        for entry in folded.frame
        if (inside := entry.interval.clipped_to(into)) is not None
    )


def concrete_entry_overhang(
    entries: Sequence[MaterializedEntry], *, into: Interval
) -> tuple[FrameOverhang, ...]:
    """Concrete entries' preceding-week minutes inside ``into``, with their resolved title."""
    return tuple(
        FrameOverhang(interval=inside, label=entry.title, area_id=entry.area_id)
        for entry in entries
        if entry.kind is TemplateEntryKind.CONCRETE
        and entry.title is not None
        and (inside := entry.interval.clipped_to(into)) is not None
    )
