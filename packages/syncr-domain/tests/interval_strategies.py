"""Interval and interval-set strategies, shared by the suites that generate occupancy.

Generated instants are whole minutes inside one ordinary week, so ``total_minutes`` is exact
and an arithmetic identity can be asserted as equality rather than as a tolerance. Sub-minute
bounds are deliberately not generated: per-set truncation would turn every such identity into
an inequality, and the truncation rule itself is pinned by example in ``test_intervals.py``.

These live beside ``instants.py`` rather than inside one suite, because the budget denominator
generates the same shapes the interval algebra does and a strategy imported from a test module
couples two suites through one of them.
"""

from __future__ import annotations

from datetime import timedelta

from hypothesis import strategies as st

from syncr_domain.intervals import Interval, IntervalSet
from tests.instants import MONDAY

WEEK_MINUTES = 7 * 24 * 60

MAX_SET_SIZE = 8


@st.composite
def intervals(draw: st.DrawFn) -> Interval:
    start = draw(st.integers(min_value=0, max_value=WEEK_MINUTES))
    length = draw(st.integers(min_value=1, max_value=1440))
    return Interval(
        MONDAY + timedelta(minutes=start),
        MONDAY + timedelta(minutes=start + length),
    )


def interval_sets(max_size: int = MAX_SET_SIZE) -> st.SearchStrategy[IntervalSet]:
    return st.builds(IntervalSet, st.lists(intervals(), max_size=max_size))
