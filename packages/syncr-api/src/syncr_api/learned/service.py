"""``LearnedService``: the read the Learned screen makes, the version list, and the activation.

Three methods, and only one of them writes. Reading what has been learned is a read: no row, no
input version bump, and no solve.

## What the activation is, in order

Flip the flag, then invalidate and re-solve every FUTURE week the tenant has planned. Past weeks are
never touched, because a past week's approved revision is immutable and keeps the inputs it was
computed with: re-deriving one would change history rather than the plan.

**Activating the version already in force is not a conflict, and it still re-solves.** The flip is a
no-op and the re-solve is the point: a user who has just been told a fit was rejected may want the
current weights applied to a week whose inputs have moved, and refusing the request would make them
reach for the re-solve control instead to do the same thing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.core.errors import NotFound
from syncr_api.core.principal import require_scope
from syncr_api.core.scopes import Scope
from syncr_api.learned.config import WEIGHT_SET_RESOURCE
from syncr_api.learned.gate_statements import (
    COLLECTING_IS_NORMAL,
    THRESHOLDS_ARE_ESTIMATES,
    UNLOCKS_COUNT_CONFIRMED_VOLUME,
)
from syncr_api.learned.maturity import collecting_count, maturity_rows, ready_count
from syncr_api.learned.views import ActivatedWeightSet, LearnedReading, WeightSetSummary

# One condition, one class. Plan storage raised it first, on the solve path, and a second class of
# the same name here would let one caller catch the other's and conclude the tenant was fine.
from syncr_api.plans.production import NoWeightSetInForce
from syncr_common.logging import get_logger
from syncr_common.metrics import measured

if TYPE_CHECKING:
    from syncr_api.core.clock import Clock
    from syncr_api.core.principal import Principal
    from syncr_api.learned.activation import FutureWeeksResolved, WeightSetActivation
    from syncr_api.learned.records import WeightSetRecord
    from syncr_api.learned.repository import WeightSetRepository

_log = get_logger("syncr.learned")


class LearnedService:
    """One tenant's learned parameters: what they are, which versions exist, which is in force."""

    def __init__(
        self,
        *,
        weights: WeightSetRepository,
        activation: WeightSetActivation,
        resolver: FutureWeeksResolved,
        clock: Clock,
    ) -> None:
        self._weights = weights
        self._activation = activation
        self._resolver = resolver
        self._clock = clock

    @measured("learned")
    async def read(self, principal: Principal) -> LearnedReading:
        """The active version's parameters, their maturity, and the statements the screen makes."""
        require_scope(principal, Scope.PLAN_READ)
        active = await self._weights.active()
        if active is None:
            raise NoWeightSetInForce(
                f"this account has no active {WEIGHT_SET_RESOURCE}, so there is nothing learned to "
                "report. Provisioning seeds version 1 in the transaction that creates a tenant"
            )
        rows = maturity_rows(active.maturity)
        return LearnedReading(
            version=active.version,
            origin=active.origin,
            fitted_at=active.fitted_at,
            rows=rows,
            ready=ready_count(rows),
            collecting=collecting_count(rows),
            thresholds_are_estimates=THRESHOLDS_ARE_ESTIMATES,
            unlocks_count_confirmed_volume=UNLOCKS_COUNT_CONFIRMED_VOLUME,
            collecting_is_normal=COLLECTING_IS_NORMAL,
        )

    @measured("learned")
    async def versions(self, principal: Principal) -> tuple[WeightSetSummary, ...]:
        """Every version this account holds, newest first. Writes nothing."""
        require_scope(principal, Scope.PLAN_READ)
        return tuple(_summary(one) for one in await self._weights.versions())

    @measured("learned")
    async def activate(self, principal: Principal, version: int) -> ActivatedWeightSet:
        """Make ``version`` the weights in force, and re-solve every future week."""
        require_scope(principal, Scope.PLAN_WRITE)
        held = [one for one in await self._weights.versions() if one.version == version]
        if not held:
            raise NotFound(f"No {WEIGHT_SET_RESOURCE} of this account has that version.")
        await self._activation.activate(version)
        operations = await self._resolver.from_the_week_holding(self._clock())
        _log.info(
            "learned.weight_set.activated",
            weight_set_version=version,
            origin=held[0].origin,
            weeks_resolved=len(operations),
        )
        return ActivatedWeightSet(
            version=version,
            resolved_weeks=tuple(str(one.iso_week) for one in operations),
        )


def _summary(stored: WeightSetRecord) -> WeightSetSummary:
    rows = maturity_rows(stored.maturity)
    return WeightSetSummary(
        version=stored.version,
        origin=stored.origin,
        active=stored.active,
        fitted_at=stored.fitted_at,
        created_at=stored.created_at,
        ready=ready_count(rows),
        collecting=collecting_count(rows),
    )
