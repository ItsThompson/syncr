"""The bounds, the defaults, the table names, and the route paths.

Every default here is read twice: as the column default a newly written row takes, and
as the record served to a tenant who has never saved settings. A read never writes, so
a tenant with no row is answered from these constants rather than having a row created
for them, and the two paths cannot disagree because they name the same values.
"""

from __future__ import annotations

from datetime import time
from enum import StrEnum
from typing import Final

from syncr_api.core.settings import API_PREFIX

# `/api/v1/settings`, built from the versioned prefix rather than written out, so a
# change to the prefix reaches this module.
SETTINGS_PREFIX: Final = f"{API_PREFIX}/settings"
# Relative to the router's prefix. The collection and one member of it.
TRAVEL_OVERRIDES_PATH: Final = "/travel-overrides"
TRAVEL_OVERRIDE_PATH: Final = "/travel-overrides/{override_id}"

SETTINGS_TABLE: Final = "settings"
TRAVEL_OVERRIDES_TABLE: Final = "travel_overrides"

# The grid's zoom range. Six hours is the least a day shape reads usefully at and 24 is
# a whole day. The Week grid narrows this per display, because a zoom level at which a
# thirty-minute block loses its title is not a useful level, and it never widens it.
VISIBLE_HOURS_MIN: Final = 6
VISIBLE_HOURS_MAX: Final = 24
VISIBLE_HOURS_DEFAULT: Final = 12

# The DEFAULT axis extent, never a crop: the grid's extent is the union of these bounds
# with the bounding interval of every block in the visible week, so a block outside them
# expands the axis rather than being hidden by it.
DAY_START_DEFAULT: Final = time(7, 0)
DAY_END_DEFAULT: Final = time(23, 0)

# UTC until the user says where they are. Guessing from a request header would persist a
# guess as a declaration, and the home zone is the input every wall-time resolution in
# the product reads; `/setup` asks for it before the first solve.
HOME_ZONE_DEFAULT: Final = "UTC"


class ReviewCadence(StrEnum):
    """Whether the pie review waits to be asked, or is offered on a schedule.

    The review proposes revised Area percentages and never applies them, so the cadence
    decides when it is offered rather than when anything changes.
    """

    ON_DEMAND = "on_demand"
    QUARTERLY = "quarterly"


# On demand, because nothing in P0 runs the review on a schedule: storing `quarterly` as
# the default would advertise a cadence no job honors. The user opts into it.
REVIEW_CADENCE_DEFAULT: Final = ReviewCadence.ON_DEMAND
