"""``OperationService``: the two reads a route answers with, on an explicit principal.

Thin on purpose, and read-only on purpose. An operation is created by the mutation whose work it
tracks, so there is no request that creates one and no request that steps one: what a client needs
is to follow one to a terminal state, and the CLI does that by polling the first of these while the
browser is pushed the same resource over SSE.

The writes are :mod:`syncr_api.solving.lifecycle`, which takes no principal because every caller of
it is either the worker or a service that has already authorized the request it is serving. Keeping
them apart is what lets authorization sit in one place per request while the worker still steps an
operation through the one state machine.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.core.errors import NotFound
from syncr_api.core.principal import authorize_tenant, require_scope
from syncr_api.core.scopes import Scope
from syncr_api.solving.config import OPERATION_RESOURCE, OperationKind
from syncr_common.metrics import measured

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_api.core.principal import Principal
    from syncr_api.solving.config import OperationStatus
    from syncr_api.solving.records import OperationRecord
    from syncr_api.solving.repository import OperationRepository
    from syncr_domain.identifiers import OperationId


class OperationService:
    """Reports one tenant's operations to whoever asked, once their scope allows it."""

    def __init__(self, operations: OperationRepository) -> None:
        self._operations = operations

    @measured("operations")
    async def report(self, principal: Principal, operation_id: OperationId) -> OperationRecord:
        """One operation of this tenant's, or a 404 that discloses nothing about another's."""
        require_scope(principal, Scope.PLAN_READ)
        found = await self._operations.find(operation_id)
        if found is None:
            raise NotFound(f"No {OPERATION_RESOURCE} matches that identifier.")
        authorize_tenant(principal, found.tenant_id, resource=OPERATION_RESOURCE)
        return found

    @measured("operations")
    async def page(
        self,
        principal: Principal,
        *,
        limit: int,
        status: OperationStatus | None = None,
        kind: OperationKind | None = None,
        after: tuple[datetime, OperationId] | None = None,
    ) -> list[OperationRecord]:
        """One page of this tenant's operations, most recently scheduled first."""
        require_scope(principal, Scope.PLAN_READ)
        return await self._operations.page(limit=limit, status=status, kind=kind, after=after)
