"""The pie review's route paths, the window it reads, and the parameter it takes."""

from __future__ import annotations

from typing import Final

from syncr_api.core.settings import API_PREFIX
from syncr_domain.budget_review import QUARTER_WEEKS

# `/api/v1/reviews`, built from the versioned prefix rather than written out, so a change to the
# prefix reaches this module. The weekly session's own payload joins this collection at
# `/reviews/week/{isoWeek}` and is ticket 51's.
REVIEWS_PREFIX: Final = f"{API_PREFIX}/reviews"

# Relative to the prefix above.
BUDGET_PATH: Final = "/budget"
APPLY_PATH: Final = "/budget/apply"

# The period is an ISO week identifier, `2026-W07`. It names the week the review is anchored at:
# composition and deviation are that week's, and the trend is the quarter ending with it.
PERIOD_PARAMETER: Final = "period"
PERIOD_EXAMPLE: Final = "2026-W07"

# How many weeks the trend covers. A quarter, so the window and the gate the proposal half is
# behind are the same span: a review that charted twenty weeks and proposed off thirteen would
# report two different periods as one.
TREND_WEEKS: Final = QUARTER_WEEKS

AREA_FIELD: Final = "areaId"
PERCENTAGES_FIELD: Final = "percentages"
