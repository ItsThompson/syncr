"""The table name, the route paths, and the one bound that is this module's own.

Every bound on a cadence, a duration, a variant list, and the debt cap lives in
``syncr_domain.habits`` rather than here, because they are the entity's invariants: the schema
reads them for its field bounds, the table reads them for its check constraints, and the domain
enforces them on construction, so one definition cannot drift from the other two.

The title bound is here, because it is not an entity invariant. A habit's title is read in a
block label on the Week grid, which is as tight as an Area's name in a pie legend.
"""

from __future__ import annotations

from typing import Final

from syncr_api.core.settings import API_PREFIX

# `/api/v1/habits`, built from the versioned prefix rather than written out, so a change to the
# prefix reaches this module.
HABITS_PREFIX: Final = f"{API_PREFIX}/habits"
# Relative to the router's prefix. One member of the collection.
HABIT_PATH: Final = "/{habit_id}"

HABITS_TABLE: Final = "habits"

HABIT_RESOURCE: Final = "habit"

# A title is read in a block label, and a habit fills about 30% of a week's blocks.
HABIT_TITLE_MAX_LENGTH: Final = 60
