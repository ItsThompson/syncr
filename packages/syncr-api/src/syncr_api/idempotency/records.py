"""The frozen view the idempotency repository returns."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.idempotency.config import COMPLETED

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_api.core.columns import JsonObject
    from syncr_api.idempotency.config import KeyState
    from syncr_domain.identifiers import TenantId


@dataclass(frozen=True, slots=True)
class IdempotencyKeyRecord:
    """One stored key: what was asked, and what it answered."""

    tenant_id: TenantId
    route: str
    key: str
    request_hash: str
    state: KeyState
    response_body: JsonObject | None
    created_at: datetime
    expires_at: datetime

    def is_completed(self) -> bool:
        """Whether the request this key belongs to produced its response."""
        return self.state == COMPLETED

    def answers(self, request_hash: str) -> bool:
        """Whether this row belongs to the same request as ``request_hash``."""
        return self.request_hash == request_hash
