"""The ``reference_week`` fixture: one real week, and the eight shapes a golden file has to hold.

The same week the design probes used, so a rendering question and a solver question can be asked
about the same data. It is built through the domain constructors and the solver's own input types,
with every instant a literal derived from the week's Monday, so nothing here restates the arithmetic
a test asserts against it.

| Shape the fixture holds | Where |
|---|---|
| a frame span, inherited from the preceding week | ``OVERHANG``, Monday 00:00 to 07:00 |
| a fifteen-minute compact block | ``Wake Up``, a concrete entry on all seven dates |
| an interview anchor with prep, transit, and recovery | ``Kontron Interview``, Wednesday |
| an anchor conflict | a lecture landing on Thursday's ``Shower`` entry |
| a depth-3 overlap | two overlapping Friday lectures inside the Friday night frame |
| a pinned habit | ``Gym`` occurrence 00, pinned to Tuesday 06:30 |
| a queue binding | ``Leetcode`` draws its content from the Career backlog |
| 64 timed blocks | the composition table below |

## The 64, and how it is composed

```
   7  Sleep, one per night                                     routine
   6  Wake Up, fifteen minutes, every date but Thursday's      template entry
   6  Shower, every date but Thursday's                        template entry
   7  Stretch, fifteen minutes, one per date                   template entry
  11  lectures, two of them overlapping each other            anchor
   1  the Kontron interview                                    anchor
   1  the interview's prep                                     anchor type
   2  the interview's two transit legs                         anchor type
   5  Gym, one of them pinned, content from a rotation         habit
   4  Leetcode, content drawn from the Career backlog          habit, queue
   2  Reading, elastic between 30 and 90 minutes               habit
   4  Walk, one of them a make-up for an earlier miss          habit
   8  three tasks and the pieces they divide into              task
  ---
  64
```

Thursday's ``Wake Up`` and ``Shower`` are the anchor conflict: that morning's lecture opens at 06:30
and takes both, so the entries are refused and the refusals name the commitment. The task pieces are
what the packing decides, so the count is what the week HOLDS rather than a prediction:
``tests/test_reference_week.py`` asserts the composition against the solved document and the golden
file records every block, so a change to either is a diff rather than a number somebody remembered.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final
from uuid import UUID

from syncr_domain.gaps import ForbiddenKind, ForbiddenScope, ForbiddenWindow
from syncr_domain.habits import BindingSource, Duration
from syncr_domain.identity import BindingRef, TransitLeg, date_occurrence_key
from syncr_domain.intervals import Interval
from syncr_domain.preferences import PreferenceOwner, PreferenceOwnerKind, PreferenceStrength
from syncr_domain.tasks import Priority
from syncr_domain.templates import BindingTarget, TemplateEntryKind
from syncr_domain.weeks import IsoWeek
from syncr_solver.inputs import (
    Anchor,
    AreaBudget,
    EligibleTask,
    EntryBinding,
    FrameEntry,
    FrameOverhang,
    HabitOccurrence,
    MaterializedEntry,
    Pin,
    ResolvedPreference,
    ShadowBlock,
    SolveInputs,
)

if TYPE_CHECKING:
    from syncr_domain.identifiers import AreaId
    from syncr_domain.zones import Date, ZoneId

WEEK: Final = IsoWeek(2026, 7)
LONDON: Final[ZoneId] = "Europe/London"

# Monday 09 February 2026 at local midnight, which is 00:00Z: the week is in GMT throughout, so a
# wall time and its UTC spelling coincide and an assertion about 06:45 is not also one about an
# offset.
MONDAY: Final = datetime(2026, 2, 9, tzinfo=UTC)
SPAN: Final = Interval(MONDAY, MONDAY + timedelta(days=7))

# The week's whole span is ahead of this, so nothing is clipped and the golden file describes a
# fully planned week rather than a partly elapsed one.
NOW: Final = MONDAY

# The Areas a tenant would have declared, fixed so a failure message names the same identifier on
# every run.
FITNESS: Final[AreaId] = UUID("cccccccc-0000-4000-8000-000000000001")
CAREER: Final[AreaId] = UUID("cccccccc-0000-4000-8000-000000000002")
STUDY: Final[AreaId] = UUID("cccccccc-0000-4000-8000-000000000003")

SLEEP: Final = UUID("cccccccc-0000-4000-8000-0000000000a1")
WAKE_UP: Final = UUID("cccccccc-0000-4000-8000-0000000000a2")
SHOWER: Final = UUID("cccccccc-0000-4000-8000-0000000000a3")
STRETCH: Final = UUID("cccccccc-0000-4000-8000-0000000000a5")
LEARNING_SLOT: Final = UUID("cccccccc-0000-4000-8000-0000000000a4")

GYM: Final = UUID("cccccccc-0000-4000-8000-0000000000b1")
LEETCODE: Final = UUID("cccccccc-0000-4000-8000-0000000000b2")
READING: Final = UUID("cccccccc-0000-4000-8000-0000000000b3")
WALK: Final = UUID("cccccccc-0000-4000-8000-0000000000b4")

PAST_PAPERS: Final = UUID("cccccccc-0000-4000-8000-0000000000c1")
LAB_REPORT: Final = UUID("cccccccc-0000-4000-8000-0000000000c2")
ADMIN: Final = UUID("cccccccc-0000-4000-8000-0000000000c3")

INTERVIEW: Final = UUID("cccccccc-0000-4000-8000-0000000000d1")

# How many timed blocks this week holds, which the suite asserts against the solved document.
TIMED_BLOCKS: Final = 64


def at(hour: float, *, day: int) -> datetime:
    """An instant this many hours into one of the week's dates."""
    return MONDAY + timedelta(days=day, hours=hour)


def between(start: float, end: float, *, day: int) -> Interval:
    return Interval(at(start, day=day), at(end, day=day))


def on(day: int) -> Date:
    return WEEK.dates()[day]


# --------------------------------------------------------------------------------------
# The space: the frame, the commitments, the buffers they cast, and the windows
# --------------------------------------------------------------------------------------

# Monday's own night runs into Tuesday, and so on. The Sunday of the PRECEDING week runs into this
# one, which is the frame span the fixture holds: this week has the hours and not the occurrence.
FRAME: Final = tuple(
    FrameEntry(
        routine_id=SLEEP,
        occurrence_key=date_occurrence_key(on(day)),
        interval=between(23, 30.5, day=day),
        min_duration_minutes=6 * 60,
        flex_band_minutes=30,
        title="Sleep",
    )
    for day in range(7)
)

OVERHANG: Final = (FrameOverhang(interval=between(0, 6.5, day=0)),)

# Two lectures a day from Monday to Friday, and the Friday pair OVERLAP each other: inside the
# Friday night frame that is three things covering one instant, which is the depth-3 overlap.
_LECTURES: Final = (
    ("Systems Programming", 1, 10.0, 12.0),
    ("Formal Methods", 1, 14.0, 16.0),
    ("Databases", 2, 14.0, 16.0),
    ("Networks", 2, 16.5, 18.0),
    ("Formal Methods", 3, 6.5, 8.0),
    ("Databases", 3, 14.0, 16.0),
    ("Networks", 4, 22.5, 23.5),
    ("Compilers", 4, 23.0, 23.75),
    ("Networks", 5, 11.0, 12.5),
    ("Compilers", 6, 11.0, 12.5),
    ("Systems Programming", 5, 15.0, 16.5),
)

ANCHORS: Final = (
    *(
        Anchor(
            anchor_id=UUID(f"cccccccc-1111-4000-8000-{index:012d}"),
            interval=between(start, end, day=day),
            title=title,
        )
        for index, (title, day, start, end) in enumerate(_LECTURES)
    ),
    Anchor(anchor_id=INTERVIEW, interval=between(9.25, 10.5, day=2), title="Kontron Interview"),
)

SHADOWS: Final = (
    ShadowBlock(
        binding=BindingRef.for_anchor_prep(INTERVIEW),
        interval=between(8.25, 9.0, day=2),
        area_id=CAREER,
        title="Interview prep",
        anchor_type_name="Interview",
        anchor_title="Kontron Interview",
    ),
    ShadowBlock(
        binding=BindingRef.for_anchor_transit(INTERVIEW, leg=TransitLeg.OUT),
        interval=between(9.0, 9.25, day=2),
        area_id=CAREER,
        title="Leave for Kontron",
        anchor_type_name="Interview",
        anchor_title="Kontron Interview",
    ),
    ShadowBlock(
        binding=BindingRef.for_anchor_transit(INTERVIEW, leg=TransitLeg.BACK),
        interval=between(10.5, 10.75, day=2),
        area_id=CAREER,
        title="Go Home",
        anchor_type_name="Interview",
        anchor_title="Kontron Interview",
    ),
)

FORBIDDEN: Final = (
    ForbiddenWindow(
        between(10.5, 11.5, day=2),
        ForbiddenKind.RECOVERY,
        ForbiddenScope.AREAS,
        (CAREER, STUDY),
        "recovery · Kontron Interview",
        INTERVIEW,
    ),
)

# --------------------------------------------------------------------------------------
# The day's shape: a fifteen-minute compact block, a Shower an anchor collides with, and slots
# --------------------------------------------------------------------------------------


def _entry(
    entry_id: UUID,
    day: int,
    interval: Interval,
    *,
    area_id: AreaId,
    title: str,
) -> MaterializedEntry:
    return MaterializedEntry(
        entry_id=entry_id,
        occurrence_key=date_occurrence_key(on(day)),
        kind=TemplateEntryKind.CONCRETE,
        interval=interval,
        flex_band_minutes=0,
        area_id=area_id,
        day_type_name="Uni day",
        title=title,
        binding=EntryBinding(target=BindingTarget.HABIT, entity_id=entry_id),
    )


TEMPLATE_ENTRIES: Final = (
    *(
        _entry(WAKE_UP, day, between(6.5, 6.75, day=day), area_id=FITNESS, title="Wake Up")
        for day in range(7)
    ),
    # Thursday's Shower falls inside that morning's Formal Methods lecture, so the entry is refused
    # and the refusal names the commitment: the anchor conflict this fixture holds.
    *(
        _entry(SHOWER, day, between(6.75, 7.0, day=day), area_id=FITNESS, title="Shower")
        for day in range(7)
    ),
    *(
        _entry(STRETCH, day, between(20.75, 21.0, day=day), area_id=FITNESS, title="Stretch")
        for day in range(7)
    ),
    MaterializedEntry(
        entry_id=LEARNING_SLOT,
        occurrence_key=date_occurrence_key(on(0)),
        kind=TemplateEntryKind.SLOT,
        interval=between(19, 20, day=0),
        flex_band_minutes=15,
        area_id=STUDY,
        day_type_name="Uni day",
    ),
    MaterializedEntry(
        entry_id=LEARNING_SLOT,
        occurrence_key=date_occurrence_key(on(4)),
        kind=TemplateEntryKind.SLOT,
        interval=between(19, 20, day=4),
        flex_band_minutes=15,
        area_id=STUDY,
        day_type_name="Rest day",
    ),
)

# --------------------------------------------------------------------------------------
# The content: four Gym occurrences with one pinned, three queue-bound, two elastic, three tasks
# --------------------------------------------------------------------------------------

HABIT_OCCURRENCES: Final = (
    *(
        HabitOccurrence(
            binding=BindingRef.for_habit(GYM, index=index),
            duration=Duration.fixed(75),
            area_id=FITNESS,
            title="Gym",
            binding_source=BindingSource.ROTATION,
            variant=("Push", "Pull", "Legs", "Push", "Pull")[index],
        )
        for index in range(5)
    ),
    *(
        HabitOccurrence(
            binding=BindingRef.for_habit(LEETCODE, index=index),
            duration=Duration.fixed(45),
            area_id=CAREER,
            title="Leetcode",
            binding_source=BindingSource.QUEUE,
        )
        for index in range(4)
    ),
    *(
        HabitOccurrence(
            binding=BindingRef.for_habit(READING, index=index),
            duration=Duration.elastic(min_minutes=30, max_minutes=90),
            area_id=STUDY,
            title="Reading",
            binding_source=BindingSource.FIXED,
        )
        for index in range(2)
    ),
    *(
        HabitOccurrence(
            binding=BindingRef.for_habit(WALK, index=index),
            duration=Duration.fixed(30),
            area_id=FITNESS,
            title="Walk",
            binding_source=BindingSource.FIXED,
            is_debt=index == 3,
        )
        for index in range(4)
    ),
)

PINS: Final = (
    Pin(
        binding=BindingRef.for_habit(GYM, index=0),
        interval=between(6.5, 7.75, day=1),
        pinned_on=on(0),
        superseded_placement=between(18, 19.25, day=1),
        objective_delta=0.42,
    ),
)

ELIGIBLE_TASKS: Final = (
    EligibleTask(
        binding=BindingRef.for_task(PAST_PAPERS),
        remaining_minutes=8 * 60,
        priority=Priority.HIGH,
        min_chunk_minutes=60,
        splittable=True,
        area_id=STUDY,
        title="F&F Past Papers",
        deadline=at(9, day=4),
    ),
    EligibleTask(
        binding=BindingRef.for_task(LAB_REPORT),
        remaining_minutes=5 * 60,
        priority=Priority.NORMAL,
        min_chunk_minutes=60,
        splittable=True,
        area_id=STUDY,
        title="Lab Report",
        deadline=at(9, day=6),
    ),
    EligibleTask(
        binding=BindingRef.for_task(ADMIN),
        remaining_minutes=5 * 60,
        priority=Priority.LOW,
        min_chunk_minutes=60,
        splittable=True,
        area_id=CAREER,
        title="Placement Admin",
    ),
)

AREAS: Final = (
    AreaBudget(
        area_id=FITNESS,
        name="Fitness",
        floor_minutes=180,
        floor_reservation_minutes=180,
        declared_floor_minutes=180,
        target_minutes=12 * 60,
        placed_minutes=0,
        max_per_day_minutes=180,
    ),
    AreaBudget(
        area_id=CAREER,
        name="Career",
        floor_minutes=240,
        floor_reservation_minutes=240,
        declared_floor_minutes=240,
        target_minutes=11 * 60,
        placed_minutes=0,
    ),
    AreaBudget(
        area_id=STUDY,
        name="Study",
        floor_minutes=600,
        floor_reservation_minutes=600,
        declared_floor_minutes=600,
        target_minutes=22 * 60,
        placed_minutes=0,
    ),
)

PREFERENCES: Final = (
    ResolvedPreference(
        owner=PreferenceOwner(kind=PreferenceOwnerKind.AREA, id=FITNESS),
        windows=tuple(between(6, 9, day=day) for day in range(7)),
        strength=PreferenceStrength.STRONG,
        preferred_duration_minutes=75,
    ),
    ResolvedPreference(
        owner=PreferenceOwner(kind=PreferenceOwnerKind.AREA, id=STUDY),
        windows=tuple(between(16, 22, day=day) for day in range(7)),
        strength=PreferenceStrength.SOFT,
        preferred_duration_minutes=120,
    ),
)


def reference_week() -> SolveInputs:
    """One real week, fully resolved. What the golden file is taken over."""
    return SolveInputs(
        iso_week=WEEK,
        span=SPAN,
        now=NOW,
        zone_by_date=dict.fromkeys(WEEK.dates(), LONDON),
        input_version=47,
        frame=FRAME,
        frame_overhang=OVERHANG,
        anchors=ANCHORS,
        shadow_blocks=SHADOWS,
        forbidden_windows=FORBIDDEN,
        template_entries=TEMPLATE_ENTRIES,
        habit_occurrences=HABIT_OCCURRENCES,
        eligible_tasks=ELIGIBLE_TASKS,
        areas=AREAS,
        preferences=PREFERENCES,
        pins=PINS,
    )
