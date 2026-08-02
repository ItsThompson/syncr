"""The three identity tables: ``tenants``, ``users``, ``sessions``.

These are the tables the tenancy rule is defined against rather than tables it applies
to, so none of them uses the :class:`~syncr_api.core.tenancy.TenantScoped` mixin.
``syncr_api.core.tenancy`` states which exemption each one has and why.

``users.tenant_id`` is UNIQUE. That single constraint is what makes "a tenant holds
exactly one user, permanently" a property of the schema rather than a rule someone has
to keep honoring: a second user in a tenant is rejected by the database, so nothing
downstream needs a user dimension to disambiguate.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from syncr_api.accounts.config import EMAIL_MAX_LENGTH, PASSWORD_HASH_MAX_LENGTH
from syncr_api.accounts.session_tokens import DIGEST_LENGTH
from syncr_api.core.orm import Base
from syncr_api.core.tenancy import SESSIONS_TABLE, TENANTS_TABLE, USERS_TABLE


class Tenant(Base):
    """One isolated dataset. Holds exactly one user, permanently."""

    __tablename__ = TENANTS_TABLE

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class User(Base):
    """The one person a tenant belongs to."""

    __tablename__ = USERS_TABLE

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    # UNIQUE, so the one-user-per-tenant rule is enforced by the database.
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{TENANTS_TABLE}.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    # Globally unique, because sign-in resolves an email before any tenant is known.
    email: Mapped[str] = mapped_column(String(EMAIL_MAX_LENGTH), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(PASSWORD_HASH_MAX_LENGTH), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BrowserSession(Base):
    """One browser's session. Named for the credential type it belongs to.

    Not ``Session``: this package's every other module already means SQLAlchemy's
    ``AsyncSession`` by that word, and two meanings for one word in one package is a
    reading cost paid on every file.

    ``id`` is the keyed digest of the token the cookie carries, never the token, so
    this row cannot be replayed by whoever reads it. ``expires_at`` is the absolute
    cap; the sliding window is derived from ``last_seen_at`` and is not stored, so
    there is one expiry rule with one statement of it.
    """

    __tablename__ = SESSIONS_TABLE

    id: Mapped[str] = mapped_column(String(DIGEST_LENGTH), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{TENANTS_TABLE}.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{USERS_TABLE}.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
