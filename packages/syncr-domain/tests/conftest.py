"""Fixtures for the domain suites."""

from __future__ import annotations

import pytest

from syncr_domain.fixtures.dst_weeks import DST_WEEKS, DstWeek


@pytest.fixture
def dst_weeks() -> tuple[DstWeek, ...]:
    """The spring-forward week and the fall-back week, in ``Europe/London``."""
    return DST_WEEKS
