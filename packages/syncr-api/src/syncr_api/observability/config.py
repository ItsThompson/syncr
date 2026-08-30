"""What the observability duties are, and how often each runs.

Two cadences, and they differ by what the reading costs.

The state reading is three cheap indexed reads per tenant, and it backs a critical alert, so it runs
often: a threshold stated in hours is meaningless if the series behind it is a quarter of an hour
stale in the worst case and absent for the first quarter hour after every restart.

The product reading walks a period of weeks and rebuilds every plan document it touches, so it runs
hourly. The four figures it exports move over weeks, and Grafana trends them from the gauge's own
history rather than from how often the job ran.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

# How often the state gauges are re-read from stored rows.
STATE_INTERVAL: Final = timedelta(minutes=1)

# How often the four product metrics are recomputed.
PRODUCT_INTERVAL: Final = timedelta(hours=1)

# How many complete ISO weeks the three period-shaped product metrics are measured over.
#
# One week is too few: a week with two partial outcomes gives a median absolute percentage error
# that swings on one block, and a week with no infeasibility gives a ratio with no denominator at
# all. Four gives every figure a denominator worth reading while staying short enough that the
# gauge's own history shows a trend rather than a smear. The targets are stated by
# week number, which a trend over this window answers and a single week's noise does not.
MEASUREMENT_WEEKS: Final = 4

# How far back the engagement streak looks. A streak longer than a year is not a figure anyone acts
# on differently from a year, and the walk costs one read per week.
STREAK_LOOKBACK_WEEKS: Final = 52
