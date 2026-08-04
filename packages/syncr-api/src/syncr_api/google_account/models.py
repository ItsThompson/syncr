"""The ``google_credentials`` table: one grant per tenant, and the failure it is in.

**One row per tenant, enforced by a unique index rather than by convention.** syncr connects one
Google account, because the write target is one calendar and the anchor sources are calendars in
that same account. Two rows would mean two refresh tokens, and a read would have to choose.

**The refresh token is stored encrypted and only encrypted.** The column holds ciphertext, so a
database dump, a backup, and a replica carry no usable authority. The key lives in the
environment, which is the one place a database dump does not reach.

**The failure pair moves together.** ``refresh_failing_since`` and ``last_refresh_error`` are
both set or both null, checked by the schema, because the notice built from them states how long
writes have been failing AND why: half of that pair is a notice that cannot be rendered.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from syncr_api.core.orm import Base
from syncr_api.core.tenancy import TENANT_ID_COLUMN, TenantScoped
from syncr_api.google_account.config import (
    ENCRYPTED_TOKEN_MAX_LENGTH,
    GOOGLE_CREDENTIALS_TABLE,
    GRANTED_SCOPES_MAX_LENGTH,
    REFRESH_ERROR_MAX_LENGTH,
)


class GoogleCredential(Base, TenantScoped):
    """The OAuth grant behind every Google read and the one destructive write."""

    __tablename__ = GOOGLE_CREDENTIALS_TABLE

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    # Fernet ciphertext. Never a plaintext token, in any environment.
    encrypted_refresh_token: Mapped[str] = mapped_column(
        String(ENCRYPTED_TOKEN_MAX_LENGTH), nullable=False
    )
    # The scopes Google says it granted, space separated as the token response states them. Kept
    # because a grant can be narrower than the request: the user may untick one on the consent
    # screen, and the surface that says what syncr can do has to read what was granted rather
    # than what was asked for.
    granted_scopes: Mapped[str] = mapped_column(String(GRANTED_SCOPES_MAX_LENGTH), nullable=False)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # When refreshing STARTED failing, not when it last failed. The notice states a duration.
    refresh_failing_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_refresh_error: Mapped[str | None] = mapped_column(
        String(REFRESH_ERROR_MAX_LENGTH), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "(refresh_failing_since IS NULL) = (last_refresh_error IS NULL)",
            name="a_refresh_failure_states_when_and_why",
        ),
        # One Google account per tenant. A unique INDEX rather than a constraint, matching the
        # convention the calendar tables set.
        Index(
            f"uq_{GOOGLE_CREDENTIALS_TABLE}_{TENANT_ID_COLUMN}",
            TENANT_ID_COLUMN,
            unique=True,
        ),
    )
