"""Fixtures for the domain suites."""

from __future__ import annotations

import pytest

from syncr_domain.fixtures.dst_weeks import DST_WEEKS, DstWeek
from syncr_domain.fixtures.off_plan_week import OFF_PLAN_WEEK, OffPlanWeek


@pytest.fixture
def dst_weeks() -> tuple[DstWeek, ...]:
    """The spring-forward week and the fall-back week, in ``Europe/London``."""
    return DST_WEEKS


@pytest.fixture
def off_plan_week() -> OffPlanWeek:
    """The Friday-to-Monday off-plan span, over the week the clocks go back."""
    return OFF_PLAN_WEEK
