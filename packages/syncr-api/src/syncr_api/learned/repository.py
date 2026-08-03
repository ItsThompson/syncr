"""Persistence for weight sets: seed version 1, read the active one, list the versions.

``seed_hand_tuned`` is what gives a NEW tenant its version 1. The migration seeds every
tenant that existed when it ran, which on a fresh database is none, so a tenant created
afterwards needs the same row from somewhere: account provisioning calls this in the
transaction that creates the tenant. Without it the first user would have no active weight
set, and ``PlanRevision.weight_set_version`` is non-optional from the first revision
onwards.

Activation and reverting are not here. Flipping ``active`` is a user-facing act with a
re-solve behind it, and it belongs with the screen that offers it.
"""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, cast

from syncr_api.core.repository import TenantScopedRepository
from syncr_api.learned.config import (
    FIRST_WEIGHT_SET_VERSION,
    HAND_TUNED,
    P0_WEIGHTS,
    WeightSetOrigin,
)
from syncr_api.learned.models import WeightSet
from syncr_api.learned.records import WeightSetRecord

if TYPE_CHECKING:
    from datetime import datetime


class WeightSetRepository(TenantScopedRepository):
    """One tenant's versioned weight sets."""

    async def seed_hand_tuned(self, *, at: datetime) -> WeightSetRecord:
        """Create this tenant's version 1: the P0 weights, hand-tuned and active."""
        seeded = WeightSet(
            tenant_id=self.tenant_id,
            version=FIRST_WEIGHT_SET_VERSION,
            active=True,
            origin=HAND_TUNED,
            duration_multiplier={},
            time_of_day_fitness={},
            skip_probability={},
            fitted_at=None,
            maturity=[],
            created_at=at,
            **P0_WEIGHTS,
        )
        self._session.add(seeded)
        # Flushed here so a second seed for one tenant fails at this call, where the caller
        # can say what it was doing, rather than at the transaction's commit.
        await self._session.flush()
        return _as_record(seeded)

    async def active(self) -> WeightSetRecord | None:
        """The weights in use, or ``None`` when this tenant has none."""
        found = await self._session.scalar(
            self.scoped_select(WeightSet).where(WeightSet.active.is_(True))
        )
        return _as_record(found) if found is not None else None

    async def versions(self) -> list[WeightSetRecord]:
        """Every version this tenant has, newest first."""
        rows = await self._session.scalars(
            self.scoped_select(WeightSet).order_by(WeightSet.version.desc())
        )
        return [_as_record(row) for row in rows]


def _as_record(weights: WeightSet) -> WeightSetRecord:
    return WeightSetRecord(
        tenant_id=weights.tenant_id,
        version=weights.version,
        active=weights.active,
        origin=cast("WeightSetOrigin", weights.origin),
        deadline_risk=weights.deadline_risk,
        budget_deviation=weights.budget_deviation,
        time_of_day_misfit=weights.time_of_day_misfit,
        fragmentation=weights.fragmentation,
        churn=weights.churn,
        context_switch=weights.context_switch,
        staleness=weights.staleness,
        duration_multiplier=deepcopy(weights.duration_multiplier),
        time_of_day_fitness=deepcopy(weights.time_of_day_fitness),
        skip_probability=deepcopy(weights.skip_probability),
        context_switch_cost=weights.context_switch_cost,
        churn_tolerance=weights.churn_tolerance,
        fitted_at=weights.fitted_at,
        maturity=deepcopy(weights.maturity),
        created_at=weights.created_at,
    )
