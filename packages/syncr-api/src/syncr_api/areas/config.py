"""The bounds, the table names, and the route paths the Area and Project routes read.

Two bounds are worth a word. A weekly floor is bounded at 168 hours to reject a value that
could never be met, not because a week is 168 hours: a transition week is 167 or 169, and
`syncr_domain.weeks` is where a real week's length comes from. A single Area's share is
bounded at 100 because a share is a share OF the remainder, so one Area cannot be given more
than the whole of it. Several Areas summing past 100 is a different thing and is accepted:
that is oversubscription, and it is reported rather than prevented.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from syncr_api.core.settings import API_PREFIX

# `/api/v1/areas` and `/api/v1/projects`, built from the versioned prefix rather than
# written out, so a change to the prefix reaches this module.
AREAS_PREFIX: Final = f"{API_PREFIX}/areas"
PROJECTS_PREFIX: Final = f"{API_PREFIX}/projects"
# Relative to the router's prefix. One member of each collection.
AREA_PATH: Final = "/{area_id}"
PROJECT_PATH: Final = "/{project_id}"

AREAS_TABLE: Final = "areas"
PROJECTS_TABLE: Final = "projects"

AREA_RESOURCE: Final = "Area"
PROJECT_RESOURCE: Final = "project"

# A name is read in a block label, a ledger row, and a pie legend, all of which are tight.
AREA_NAME_MAX_LENGTH: Final = 60
PROJECT_NAME_MAX_LENGTH: Final = 120

# `NUMERIC(5, 2)`: three digits before the point and two after, which holds every legal
# percentage and every legal floor to the hundredth of an hour.
BUDGET_DECIMAL_PRECISION: Final = 5
BUDGET_DECIMAL_SCALE: Final = 2

BUDGET_PERCENT_MIN: Final = Decimal(0)
BUDGET_PERCENT_MAX: Final = Decimal(100)

FLOOR_HOURS_MIN: Final = Decimal(0)
FLOOR_HOURS_MAX: Final = Decimal(168)
