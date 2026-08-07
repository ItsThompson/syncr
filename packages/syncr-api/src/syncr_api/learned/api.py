"""The three learning routes.

Thin, on purpose. Each validates its shape, resolves who is asking, calls one service method, and
maps
the result through that shape's own ``of``. No authorization decision and no persistence.

**The two reads write nothing.** No row, no input version bump, and no solve: reading what has been
learned is a read, and the Learned screen is one a user opens to check syncr against their own
experience rather than to change anything.

The activation takes the idempotency guard. A retried activation is harmless in itself -- the flip
is the same two statements -- but the re-solve it triggers is not free, so the stored response is
what makes a retry after a timeout read the operations the first attempt created rather than queue a
second pass over every future week.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path

from syncr_api.accounts.injection import PrincipalDep
from syncr_api.idempotency.injection import IdempotencyGuardDep
from syncr_api.learned.config import ACTIVATE_PATH, LEARNED_PATH, WEIGHT_SETS_PATH
from syncr_api.learned.injection import LearnedServiceDep
from syncr_api.learned.schemas import ActivatedResponse, LearnedResponse, WeightSetsResponse

learned_router = APIRouter()
weight_set_router = APIRouter()

ACTIVATE_ROUTE = "learned.activate_weight_set"


@learned_router.get(LEARNED_PATH, summary="What has been learned, and what is still collecting")
async def read_learned(principal: PrincipalDep, service: LearnedServiceDep) -> LearnedResponse:
    """Per-parameter maturity, values, sample counts and plain-language statements. A read."""
    return LearnedResponse.of(await service.read(principal))


@weight_set_router.get(WEIGHT_SETS_PATH, summary="Every version, with origin and active flag")
async def list_weight_sets(
    principal: PrincipalDep, service: LearnedServiceDep
) -> WeightSetsResponse:
    """The versions this account holds, newest first. Writes nothing."""
    return WeightSetsResponse.of(await service.versions(principal))


@weight_set_router.post(ACTIVATE_PATH, summary="Activate a version, or revert to an earlier one")
async def activate_weight_set(
    version: Annotated[int, Path(description="The version to put in force.", ge=1)],
    principal: PrincipalDep,
    guard: IdempotencyGuardDep,
    service: LearnedServiceDep,
) -> ActivatedResponse:
    """Put ``version`` in force and re-solve every future week. Past weeks are immutable."""

    async def activate() -> ActivatedResponse:
        return ActivatedResponse.of(await service.activate(principal, version))

    return await guard.once(ACTIVATE_ROUTE, ActivatedResponse, activate)
