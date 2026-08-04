"""The bounds, the table name, and the route paths the backlog reads.

Three bounds are worth a word.

**A title is bounded at the length a Project's name is**, because both are read in the same
places: a block label on the week grid, a ledger row, and a backlog table cell. An Area's name
is shorter because it is also a legend entry beside a pie wedge.

**An estimate is bounded at one week's minutes.** That rejects a value no week could ever hold,
which is what a non-splittable task needs: an atomic task larger than a week can never be
placed at all, so accepting one would store a task that is silently unschedulable forever. A
splittable task genuinely larger than a week is a Project's worth of work and is expressed as
several tasks inside one, which is what a Project is for. The figure is 168 hours for the same
reason ``FLOOR_HOURS_MAX`` is: it rejects nonsense rather than describing a real week, and a
real week is 167 or 169 hours whenever a zone transitions.

**Neither minute bound is a multiple of the grid step**, and that is deliberate. The snap grid
governs the instants a placement starts and ends on, not the physics a task declares:
`04-domain-model.md`'s own elasticity example puts one task at 25, 45, and 90 minutes, so
requiring a multiple of fifteen here would refuse a value the domain model uses.
"""

from __future__ import annotations

from typing import Final

from syncr_api.core.settings import API_PREFIX

# `/api/v1/tasks`, built from the versioned prefix rather than written out.
TASKS_PREFIX: Final = f"{API_PREFIX}/tasks"
# Relative to the router's prefix.
TASK_PATH: Final = "/{task_id}"
TASK_COMPLETE_PATH: Final = "/{task_id}/complete"

TASKS_TABLE: Final = "tasks"

TASK_RESOURCE: Final = "task"

# Read in a block label, a ledger row, and a backlog cell, the same three places a Project's
# name is read, so it carries the same bound.
TITLE_MAX_LENGTH: Final = 120

MINUTES_IN_AN_HOUR: Final = 60
HOURS_IN_A_NOMINAL_WEEK: Final = 168

ESTIMATE_MINUTES_MIN: Final = 1
ESTIMATE_MINUTES_MAX: Final = MINUTES_IN_AN_HOUR * HOURS_IN_A_NOMINAL_WEEK

# A minimum chunk is a chunk OF the estimate, so it can never usefully exceed the estimate's
# own ceiling. T1 is what compares the two, in the domain; this only keeps a stored value
# inside the column's range.
MIN_CHUNK_MINUTES_MIN: Final = 1
MIN_CHUNK_MINUTES_MAX: Final = ESTIMATE_MINUTES_MAX

RECORDED_MINUTES_MIN: Final = 0
