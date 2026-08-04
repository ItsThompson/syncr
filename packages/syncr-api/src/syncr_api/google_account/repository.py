"""Persistence for ``google_credentials``. Tenant-scoped, and the only writer of the grant.

Four writes, and each is one statement, because each answers one event: the user connected, a
refresh succeeded, a refresh failed, the user disconnected.

``connect`` replaces the whole row rather than patching it. A reconnect is a new grant: a new
refresh token, whatever scopes were granted this time, and no history of the failure it repaired.
Patching would leave a stale ``last_refresh_error`` beside a working credential, which is the
notice this package exists to raise still rendering after the repair.

``record_refresh_failure`` sets ``refresh_failing_since`` only when it is not already set, so the
instant it holds is when failing STARTED. Every later failure moves the message and not the
instant, which is what lets the notice state how long the plan has not been reaching the phone.

No method commits. One request is one transaction; the worker opens its own around a tick.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import func

from syncr_api.core.repository import TenantScopedRepository
from syncr_api.google_account.models import GoogleCredential
from syncr_api.google_account.records import GoogleCredentialRecord

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

SCOPE_SEPARATOR = " "


class GoogleCredentialRepository(TenantScopedRepository):
    """The one Google grant this tenant holds, and the state of its last refresh."""

    async def read(self) -> GoogleCredentialRecord | None:
        """This tenant's credential, or ``None`` when no account is connected."""
        found = await self._session.scalar(self.scoped_select(GoogleCredential))
        return _as_record(found) if found is not None else None

    async def connect(
        self,
        *,
        encrypted_refresh_token: str,
        granted_scopes: Sequence[str],
        at: datetime,
    ) -> GoogleCredentialRecord:
        """Store a new grant, replacing any the tenant already held.

        Deleting and inserting rather than updating: the row's whole meaning is "the grant in
        force", and the unique index makes a replace the only shape a second connect can take.
        """
        await self._session.execute(self.scoped_delete(GoogleCredential))
        row = GoogleCredential(
            id=uuid4(),
            tenant_id=self.tenant_id,
            encrypted_refresh_token=encrypted_refresh_token,
            granted_scopes=SCOPE_SEPARATOR.join(granted_scopes),
            connected_at=at,
        )
        self._session.add(row)
        # Flushed here so an oversize ciphertext or a second row surfaces as this call's failure
        # rather than at commit, after the user has been told the account is connected.
        await self._session.flush()
        return _as_record(row)

    async def record_refresh(self, *, at: datetime) -> None:
        """Record a refresh that worked, clearing any failure it repaired."""
        await self._session.execute(
            self.scoped_update(GoogleCredential).values(
                last_refresh_at=at, refresh_failing_since=None, last_refresh_error=None
            )
        )

    async def record_refresh_failure(self, *, at: datetime, reason: str) -> None:
        """Record a refresh that failed, keeping the instant the failing started.

        ``COALESCE`` is what makes the instant sticky: the first failure writes ``at``, and every
        later one writes the value already there. Reading the row first and branching in Python
        would let two concurrent failures both read null and both write their own instant, which
        would shorten the duration the notice reports every time the worker retried.
        """
        await self._session.execute(
            self.scoped_update(GoogleCredential).values(
                refresh_failing_since=func.coalesce(GoogleCredential.refresh_failing_since, at),
                last_refresh_error=reason,
            )
        )

    async def disconnect(self) -> None:
        """Remove this tenant's grant. Every Google source stops being readable."""
        await self._session.execute(self.scoped_delete(GoogleCredential))


def _as_record(row: GoogleCredential) -> GoogleCredentialRecord:
    granted = row.granted_scopes
    return GoogleCredentialRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        encrypted_refresh_token=row.encrypted_refresh_token,
        granted_scopes=tuple(granted.split(SCOPE_SEPARATOR)) if granted else (),
        connected_at=row.connected_at,
        last_refresh_at=row.last_refresh_at,
        refresh_failing_since=row.refresh_failing_since,
        last_refresh_error=row.last_refresh_error,
    )
