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
# week before it, which is what makes planning and retrospective one sitting.
#
# The parameter is spelled `iso_week` so the guard that drives every parameterized read can
# substitute a week into any of them: one spelling across the week routes.
SESSION_PATH: Final = "/week/{iso_week}"
ISO_WEEK_FIELD: Final = "isoWeek"

# The weekly session payload read's p95 latency budget, in seconds.
#
# Derived from the figure the week view it composes already answers to: GET /weeks is budgeted at
# p95 under 300 ms on a full week (`tests/test_week_view_integration.py` states and measures it),
# and this read IS that view plus a bounded tail. The tail is two span reads over the reviewed
# quarter, at most thirteen stored documents parsed beside them, the seven single-statement fact
# reads `reviews/session_sources.py` composes, and three repository reads. Every one of those is a
# single statement inside a bucket of `core/db_metrics.READ_BUCKETS`, so the whole tail is held to
# one read bucket: 300 + 100 = 400 ms.
#
# One constant rather than figures spelled into prose, because three artifacts quote it: this file
# derives it, `deployments/prometheus/alerts.yml`'s `WeeklySessionSlow` threshold states it, and
# `docs/runbooks/weekly-session-slow.md` explains it. A retune moves the constant first.
SESSION_P95_BUDGET_SECONDS: Final = 0.4

# How many weeks the session's history window covers. A quarter, the same span the pie review reads,
# so "the period a review rests on" has one length in this module. It bounds the two runs the
# session computes: a chronic skip longer than the window is reported as the window, which is the
# honest answer for a read that cannot see past its own bound.
SESSION_LOOKBACK_WEEKS: Final = QUARTER_WEEKS

# An item proposed and skipped for six consecutive weeks is raised.
CHRONIC_SKIP_WEEKS: Final = 6

# One commitment meeting one block in three or more weeks is raised. Weeks, not rows,
# and not necessarily consecutive.
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
