"""The table name, the three route paths, and the resource names a refusal spells.

Every bound on a window list, an ideal duration, and a daily cap lives in
``syncr_domain.preferences`` rather than here, because they are the entity's invariants: the
schema reads them for its field bounds, the table reads them for its check constraints, and the
domain enforces them on construction, so one definition cannot drift from the other two.

The three paths are derived from the collections they hang under rather than spelled again, so a
change to ``/api/v1/areas`` reaches the Area's preference with it. That is a read of a sibling
module's constant and no more: nothing here imports a sibling's service, and no sibling imports
this package.
"""

from __future__ import annotations

from typing import Final

from syncr_api.areas.config import AREAS_PREFIX
from syncr_api.habits.config import HABITS_PREFIX
from syncr_api.tasks.config import TASKS_PREFIX

# A preference is a singleton sub-resource of its owner rather than a member of a collection:
# an owner has one or none, so the path names no preference identifier.
AREA_PREFERENCE_PATH: Final = f"{AREAS_PREFIX}/{{area_id}}/preference"
HABIT_PREFERENCE_PATH: Final = f"{HABITS_PREFIX}/{{habit_id}}/preference"
TASK_PREFERENCE_PATH: Final = f"{TASKS_PREFIX}/{{task_id}}/preference"

PREFERENCES_TABLE: Final = "preferences"

PREFERENCE_RESOURCE: Final = "preference"
