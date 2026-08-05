"""The ``partial_progress`` fixture: a task half done, half placed, and one day unconfirmed.

One task, one deadline, and every shape of progress that has to be netted out of the work still
outstanding. It exists for the probe's net arithmetic, which is the one place in this product
where getting a subtraction wrong punishes the user for making progress: a shortfall that appears
*because* four hours of work became two is the failure the netting rules exist to prevent.

``Europe/London`` 2026-W07, and ``now`` is Wednesday 11 February at 09:00. The task is
``F&F Past Papers``: a 240-minute estimate in Career, due Friday 13 February at 09:00.

| Placement | When | Minutes | How it is attributed |
|---|---|---|---|
| pinned, future | Thu 09:00-11:00 | 120 | added: scheduled work no outcome can have recorded |
| unconfirmed, past | Tue 14:00-15:00 | 60 | `max(recorded, past-placed)`, and nothing is recorded |
| after the deadline | Sat 10:00-11:00 | 60 | none: Saturday does not meet a Friday deadline |

So the demand the probe reads is ``240 - (max(0, 60) + 120) = 60`` minutes, and the capacity it
compares that against has all three placements out of it, because free capacity subtracts every
placement whether or not the solver may move it.

**The unconfirmed past hour is the case worth stating.** No outcome has been recorded, because the
day has not been confirmed, so a rule that read recorded minutes alone would count nothing for it
while free capacity still subtracted the hour: the minutes would vanish from both sides and the
week would report a gap for work the user has almost certainly done.

**And it is the hour the attribution table is stated over.** Pressing skip on it says the work was
not done, so its minutes stop counting toward the task and the demand RISES to
``240 - (max(0, 0) + 120) = 120``. ``AFTER_A_SKIP`` is that same week with the row recorded, and it
is a second ``ProbeInputs`` rather than a mutation because the pair is what a property is stated
over: recording an outcome may raise a shortfall and may never lower one, and the capacity figure is
identical in both because a past span was never in capacity to be returned to it.

**There is no frame here, and no anchor.** Both would be real, and both would make every figure
above a sum of two rules rather than one, which is how a fixture stops being able to fail. The
occupancy arithmetic has its own fixtures; this one is the netting.

Every instant is a **literal**, as in the other fixtures here, and
``tests/test_partial_progress_fixture.py`` re-derives each from the stated wall time and re-derives
the netted figure from the table above. Deriving them here would make a test that asserts an
arithmetic figure against this fixture a restatement of the code under test.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final
from uuid import UUID

from syncr_domain.feasibility.inputs import DeadlineDemand, FloorReservation, ProbeInputs
from syncr_domain.identity import BindingRef
from syncr_domain.intervals import Interval, IntervalSet
from syncr_domain.outcomes import MISS_STATE, RecordedOutcome
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from syncr_domain.identifiers import AreaId, TaskId

WEEK: Final = IsoWeek(2026, 7)

# Stand-ins for the Areas a tenant would have declared. Fixed rather than generated, so a failure
# message names the same identifier on every run.
CAREER: Final[AreaId] = UUID("bbbbbbbb-0000-4000-8000-000000000001")
FITNESS: Final[AreaId] = UUID("bbbbbbbb-0000-4000-8000-000000000002")

# The task every placement below is for. Fixed for the same reason the Areas are, and needed as its
# own value because an outcome names the content it happened to rather than the Area it charged.
TASK: Final[TaskId] = UUID("cccccccc-0000-4000-8000-000000000001")

TITLE: Final = "F&F Past Papers"
ESTIMATE_MINUTES: Final = 240

# Monday 09 February 2026 at 00:00 local, which is 00:00Z: the week is in GMT throughout.
SPAN: Final = Interval(datetime(2026, 2, 9, tzinfo=UTC), datetime(2026, 2, 16, tzinfo=UTC))
NOW: Final = datetime(2026, 2, 11, 9, 0, tzinfo=UTC)
DEADLINE: Final = datetime(2026, 2, 13, 9, 0, tzinfo=UTC)

PINNED_AHEAD: Final = Interval(
    datetime(2026, 2, 12, 9, 0, tzinfo=UTC), datetime(2026, 2, 12, 11, 0, tzinfo=UTC)
)
UNCONFIRMED_PAST: Final = Interval(
    datetime(2026, 2, 10, 14, 0, tzinfo=UTC), datetime(2026, 2, 10, 15, 0, tzinfo=UTC)
)
AFTER_THE_DEADLINE: Final = Interval(
    datetime(2026, 2, 14, 10, 0, tzinfo=UTC), datetime(2026, 2, 14, 11, 0, tzinfo=UTC)
)

PLACED: Final = IntervalSet([PINNED_AHEAD, UNCONFIRMED_PAST, AFTER_THE_DEADLINE])

# 240 less the 60 attributed to the past hour less the 120 pinned before the deadline. The hour on
# Saturday satisfies nothing, because it falls after Friday 09:00.
REMAINING_MINUTES: Final = 60

# The same figure once the past hour is recorded as a confirmed skip: the user said the work was not
# done, so its 60 minutes stop counting toward the task and the whole of them is outstanding again.
REMAINING_MINUTES_AFTER_A_SKIP: Final = 120

# What the user said happened to the Tuesday hour. Keyed by binding, which is what a stored outcome
# denormalizes and what the re-derivation reads.
SKIPPED_PAST: Final = RecordedOutcome(binding=BindingRef.for_task(TASK), state=MISS_STATE)

# Career declares a 5h weekly floor and has 180 minutes of it placed, so 120 are still to find.
# Fitness declares 5h and has none placed.
CAREER_FLOOR_MINUTES: Final = 300
CAREER_RESERVED_MINUTES: Final = 120
FITNESS_FLOOR_MINUTES: Final = 300

DEMAND: Final = DeadlineDemand(
    deadline=DEADLINE,
    remaining_minutes=REMAINING_MINUTES,
    area_id=CAREER,
    labels=(TITLE,),
)

RESERVATIONS: Final = (
    FloorReservation(area_id=CAREER, reserved_minutes=CAREER_RESERVED_MINUTES, label="Career"),
    FloorReservation(area_id=FITNESS, reserved_minutes=FITNESS_FLOOR_MINUTES, label="Fitness"),
)

PARTIAL_PROGRESS: Final = ProbeInputs(
    span=SPAN,
    now=NOW,
    computed_at=NOW,
    input_version=47,
    placed=PLACED,
    area_floor_reservations=RESERVATIONS,
    area_targets={CAREER: 900, FITNESS: 420},
    deadline_demands=(DEMAND,),
)

# The same week with the Tuesday hour recorded as a skip. The demand is the only figure that moves:
# `placed` is identical, because a past span sits before `now` and was never in capacity, which is
# what stops skipping work making the week read as more feasible.
AFTER_A_SKIP: Final = ProbeInputs(
    span=SPAN,
    now=NOW,
    computed_at=NOW,
    input_version=48,
    placed=PLACED,
    area_floor_reservations=RESERVATIONS,
    area_targets={CAREER: 900, FITNESS: 420},
    deadline_demands=(
        DeadlineDemand(
            deadline=DEADLINE,
            remaining_minutes=REMAINING_MINUTES_AFTER_A_SKIP,
            area_id=CAREER,
            labels=(TITLE,),
        ),
    ),
)
