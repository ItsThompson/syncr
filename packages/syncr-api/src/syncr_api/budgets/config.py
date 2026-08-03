"""The route path and the period parameter the budget report is asked for."""

from __future__ import annotations

from typing import Final

from syncr_api.core.settings import API_PREFIX

# `/api/v1/budget`, built from the versioned prefix rather than written out, so a change to
# the prefix reaches this module.
BUDGET_PREFIX: Final = f"{API_PREFIX}/budget"

# The period is an ISO week identifier, `2026-W07`. Every figure the report carries is
# week-scoped: discretionary time derives from one week's span, and a target divides it.
PERIOD_PARAMETER: Final = "period"
PERIOD_EXAMPLE: Final = "2026-W07"
