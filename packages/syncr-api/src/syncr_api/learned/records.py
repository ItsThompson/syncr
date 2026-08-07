"""The frozen view the weight-set repository returns.

Flat rather than nested. The seven term weights and the five fitted parameters are read by different
consumers at different times, and grouping them would make every caller reach through a container to
get one float.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_api.core.columns import JsonObject
    from syncr_api.learned.config import WeightSetOrigin
    from syncr_domain.identifiers import TenantId


@dataclass(frozen=True, slots=True)
class WeightSetRecord:
    """One version of the weights, as stored."""

    tenant_id: TenantId
    version: int
    active: bool
    origin: WeightSetOrigin

    deadline_risk: float
    budget_deviation: float
    time_of_day_misfit: float
    fragmentation: float
    churn: float
    context_switch: float
    staleness: float

    duration_multiplier: JsonObject
    time_of_day_fitness: JsonObject
    skip_probability: JsonObject
    context_switch_cost: float
    churn_tolerance: float

    fitted_at: datetime | None
    maturity: list[JsonObject]
    created_at: datetime
