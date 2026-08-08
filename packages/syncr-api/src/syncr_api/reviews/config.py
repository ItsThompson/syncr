"""The review routes' paths, the windows they read, and the parameters they take."""

from __future__ import annotations

from typing import Final

from syncr_api.core.settings import API_PREFIX
from syncr_domain.budget_review import QUARTER_WEEKS

# `/api/v1/reviews`, built from the versioned prefix rather than written out, so a change to the
# prefix reaches this module. Both reviews live under it: the pie review, which is a mode of the
# Areas screen, and the weekly session, which is a mode of the Week screen.
REVIEWS_PREFIX: Final = f"{API_PREFIX}/reviews"

# Relative to the prefix above.
BUDGET_PATH: Final = "/budget"
APPLY_PATH: Final = "/budget/apply"

# The weekly session's payload, addressed by the week it PLANS. The retrospective half covers the
# week before it, which is what makes planning and retrospective one sitting: `US-REV-01`.
#
# The parameter is spelled `iso_week` for the reason ticket 1363 settled across the week routes: one
# spelling, so the guard that drives every parameterized read can substitute a week into any of
# them.
SESSION_PATH: Final = "/week/{iso_week}"
ISO_WEEK_FIELD: Final = "isoWeek"

# How many weeks the session's history window covers. A quarter, the same span the pie review reads,
# so "the period a review rests on" has one length in this module. It bounds the two runs the
# session computes: a chronic skip longer than the window is reported as the window, which is the
# honest answer for a read that cannot see past its own bound.
SESSION_LOOKBACK_WEEKS: Final = QUARTER_WEEKS

# `US-REV-02`: an item proposed and skipped for six consecutive weeks is raised.
CHRONIC_SKIP_WEEKS: Final = 6

# `US-REV-05`: one commitment meeting one block in three or more weeks is raised. Weeks, not rows,
# and not necessarily consecutive: the story's own words.
REPEATED_COLLISION_WEEKS: Final = 3

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
