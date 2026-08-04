"""The immutable view of the one Google credential a tenant holds.

The stored ciphertext is deliberately on this record. A repository hands back what the row
says, and decryption is the token layer's job, so nothing in the read path holds a plaintext
token it did not ask for.

``refresh_failing_since`` and ``last_refresh_error`` move together, in both directions, and the
table's check constraint says so. That pair is what the loudest notice in the product is built
from: the notice has to state how long writes have been failing, so the instant the failure
STARTED is stored rather than the instant of the last attempt. A field that moved on every
retry would report "failing for 15 minutes" after a week of failing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_domain.identifiers import TenantId

type GoogleCredentialId = UUID


@dataclass(frozen=True, slots=True)
class GoogleCredentialRecord:
    """One tenant's Google grant, as persistence knows it."""

    id: GoogleCredentialId
    tenant_id: TenantId
    encrypted_refresh_token: str
    granted_scopes: tuple[str, ...]
    connected_at: datetime
    last_refresh_at: datetime | None = None
    refresh_failing_since: datetime | None = None
    last_refresh_error: str | None = None

    @property
    def is_refresh_failing(self) -> bool:
        """Whether the last refresh attempt failed and none has succeeded since."""
        return self.refresh_failing_since is not None
