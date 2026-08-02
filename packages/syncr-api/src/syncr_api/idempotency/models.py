"""The ``idempotency_keys`` table: one row per tenant, route, and client-chosen key.

The primary key is what makes a retry find the original: the key alone would collide between
routes, and without the tenant it would collide between clients.

``expires_at`` is the row's whole retention rule. A request carrying a key whose row has
passed that instant is treated as unseen, so behavior does not depend on the sweep having
run recently. The sweep only reclaims the space.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID  # noqa: F401 - the tenancy mixin's annotation resolves in this namespace

from sqlalchemy import CheckConstraint, DateTime, Index, PrimaryKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from syncr_api.core.columns import NULLABLE_JSONB, JsonObject, values_in
from syncr_api.core.orm import Base
from syncr_api.core.tenancy import TENANT_ID_COLUMN, TenantScoped
from syncr_api.idempotency.config import (
    COMPLETED,
    IDEMPOTENCY_KEYS_TABLE,
    KEY_MAX_LENGTH,
    KEY_STATES,
    REQUEST_HASH_LENGTH,
    ROUTE_MAX_LENGTH,
    STATE_MAX_LENGTH,
)


class IdempotencyKey(Base, TenantScoped):
    """One unsafe request's key, its request hash, and the response it produced."""

    __tablename__ = IDEMPOTENCY_KEYS_TABLE

    route: Mapped[str] = mapped_column(String(ROUTE_MAX_LENGTH), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(KEY_MAX_LENGTH), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(REQUEST_HASH_LENGTH), nullable=False)
    state: Mapped[str] = mapped_column(String(STATE_MAX_LENGTH), nullable=False)
    response_body: Mapped[JsonObject | None] = mapped_column(NULLABLE_JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint(TENANT_ID_COLUMN, "route", "idempotency_key"),
        CheckConstraint(values_in("state", KEY_STATES), name="state_is_known"),
        # A completed key without its response could not be replayed, and an in-flight one
        # holding a response would replay a request that had not finished.
        CheckConstraint(
            f"(state = '{COMPLETED}') = (response_body IS NOT NULL)",
            name="completed_stores_its_response",
        ),
        # What the retention sweep reads. Not tenant-led, because the sweep serves every
        # tenant at once, so it is a single-column index rather than a composite one.
        Index("ix_idempotency_keys_expires_at", "expires_at"),
    )
