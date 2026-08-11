"""Persistence for the identity tables.

Neither repository here extends
:class:`~syncr_api.core.repository.TenantScopedRepository`, and that is the point of
the split: both are read by something other than a tenant, because both run BEFORE a
tenant is known. A user is found by the email in the sign-in body; a session is found
by the digest of the presented cookie. A tenant-scoped repository could not answer
either question, because the answer is what supplies the scope.

What protects a foreign row here is the service layer, which authorizes an explicit
principal against the row's own ``tenant_id`` and raises 404 on a mismatch. Every
repository over a table that holds a plan is scoped instead, and cannot be constructed
without a tenant.

No method commits. One request is one transaction, opened and committed by
:func:`syncr_api.core.db.get_transaction`, so a service that writes two rows cannot
leave one behind.

Each class carries :func:`~syncr_api.core.db_metrics.measure_reads` explicitly, because the hook
that applies it to every scoped repository is on the base these three do not extend. Without it the
session lookup on the hot path of every request a cookie authenticates would be the one read
``syncr_db_query_duration_seconds`` could not see.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import select, update

from syncr_api.accounts.models import BrowserSession, Tenant, User
from syncr_api.accounts.records import SessionRecord, UserRecord
from syncr_api.core.db_metrics import measure_reads

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_api.accounts.session_tokens import SessionId
    from syncr_domain.identifiers import TenantId, UserId


@measure_reads
class TenantRepository:
    """Reads the tenants a deployment holds.

    Exists for the maintenance sweeps. Every statement over a table that holds a plan carries
    its tenant, so a sweep that spans the deployment enumerates the scopes first and then
    works inside each one; this is what enumerates them. ``tenants`` is the scope itself, so
    this repository is not and cannot be scoped.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_ids(self) -> list[TenantId]:
        """Every tenant id, oldest first, so a sweep visits them in a stable order."""
        found = await self._session.scalars(select(Tenant.id).order_by(Tenant.created_at))
        return list(found)


@measure_reads
class UserRepository:
    """Reads and creates the one user a tenant holds."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_email(self, email: str) -> UserRecord | None:
        """The user with this email, or ``None``. The sign-in lookup."""
        found = await self._session.scalar(select(User).where(User.email == email))
        return _as_user_record(found) if found is not None else None

    async def find(self, user_id: UserId) -> UserRecord | None:
        """The user with this id, or ``None``."""
        found = await self._session.get(User, user_id)
        return _as_user_record(found) if found is not None else None

    async def find_by_tenant(self, tenant_id: TenantId) -> UserRecord | None:
        """The one user this tenant holds, or ``None``.

        Answerable because ``users.tenant_id`` is UNIQUE, which is what makes the relation
        1:1 rather than conventional. It exists because no table that holds a plan may carry
        a ``user_id``, so a caller that has a tenant and needs the subject behind it (an
        access token's ``sub``, for one) resolves it here rather than storing a second copy
        of it on a scoped row.
        """
        found = await self._session.scalar(select(User).where(User.tenant_id == tenant_id))
        return _as_user_record(found) if found is not None else None

    async def create_tenant_with_user(
        self, *, email: str, password_hash: str, created_at: datetime
    ) -> UserRecord:
        """Create a tenant and its one user together.

        There is no method that creates a tenant on its own, because there is no legal
        state in which one exists without its user. The unique index on
        ``users.tenant_id`` is what rejects a second user; this signature is what makes
        the first one unskippable.
        """
        tenant = Tenant(id=uuid4(), created_at=created_at)
        user = User(
            id=uuid4(),
            tenant_id=tenant.id,
            email=email,
            password_hash=password_hash,
            created_at=created_at,
        )
        self._session.add(tenant)
        self._session.add(user)
        # Flushed here so a duplicate email or tenant surfaces as this call's failure
        # rather than as an error at commit, after the caller has reported success.
        await self._session.flush()
        return _as_user_record(user)


@measure_reads
class SessionRepository:
    """Reads, creates, slides, and revokes browser sessions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find(self, session_id: SessionId) -> SessionRecord | None:
        """The session with this id, or ``None``. Takes the digest, not the token."""
        found = await self._session.get(BrowserSession, session_id)
        return _as_session_record(found) if found is not None else None

    async def create(self, record: SessionRecord) -> None:
        """Persist a new session exactly as the caller composed it."""
        self._session.add(
            BrowserSession(
                id=record.id,
                tenant_id=record.tenant_id,
                user_id=record.user_id,
                created_at=record.created_at,
                last_seen_at=record.last_seen_at,
                expires_at=record.expires_at,
                revoked_at=record.revoked_at,
            )
        )
        await self._session.flush()

    async def touch(self, session_id: SessionId, at: datetime) -> None:
        """Slide the idle window by recording this use."""
        await self._session.execute(
            update(BrowserSession).where(BrowserSession.id == session_id).values(last_seen_at=at)
        )

    async def revoke(self, session_id: SessionId, at: datetime) -> None:
        """Revoke server-side, so the cookie alone cannot be replayed.

        Guarded on ``revoked_at IS NULL`` so a repeated sign-out keeps the instant the
        session actually stopped being usable rather than the instant of the last
        attempt.
        """
        await self._session.execute(
            update(BrowserSession)
            .where(BrowserSession.id == session_id, BrowserSession.revoked_at.is_(None))
            .values(revoked_at=at)
        )


def _as_user_record(user: User) -> UserRecord:
    return UserRecord(
        id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        password_hash=user.password_hash,
    )


def _as_session_record(session: BrowserSession) -> SessionRecord:
    return SessionRecord(
        id=session.id,
        tenant_id=session.tenant_id,
        user_id=session.user_id,
        created_at=session.created_at,
        last_seen_at=session.last_seen_at,
        expires_at=session.expires_at,
        revoked_at=session.revoked_at,
    )
