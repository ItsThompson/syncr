"""The ``calendar_sources`` table: many sources read as anchors, exactly one written to.

Two indexes and three check constraints carry invariants that would otherwise be rules a
repository has to remember.

**The partial unique index is the one-write-target invariant.** At most one source per tenant
may hold ``role = 'write-target'``, and it is the database that says so. A bug that tried to
designate a second would be rejected here rather than producing two calendars each believing
it is the projection, which is the state that would make the plan appear twice on the phone
and be reconciled destructively in two places.

**A horizon belongs to the write target and only to it.** The biconditional check is what
makes that structural: a write target always has a projection bound, and an anchor source
never has one, so no reader has to decide what a horizon on a read-only feed would mean.

**One source per feed per tenant.** Adding the same URL twice would double every anchor it
contributes and make the solver treat one lecture as two overlapping commitments.

The sync state is embedded rather than kept in a table of its own. There is exactly one per
source, every read of a source wants it, and a join to fetch a last-sync time would be a join
on every panel render. ``rejections`` is part of it for the same reason: the panel that states
how many events were rejected is rendered from a read, so a rejection has to survive the
attempt that produced it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    SmallInteger,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from syncr_api.calendars.config import (
    CALENDAR_PROVIDERS,
    CALENDAR_ROLES,
    CALENDAR_SOURCES_TABLE,
    CURSOR_MAX_LENGTH,
    DISPLAY_NAME_MAX_LENGTH,
    EXTERNAL_ID_MAX_LENGTH,
    HORIZON_DAYS_MAX,
    HORIZON_DAYS_MIN,
    LAST_ERROR_MAX_LENGTH,
    WRITE_TARGET,
)
from syncr_api.core.columns import NULLABLE_JSONB, values_in
from syncr_api.core.orm import Base
from syncr_api.core.tenancy import TENANT_ID_COLUMN, TenantScoped

PROVIDER_LENGTH = max(len(provider) for provider in CALENDAR_PROVIDERS)
ROLE_LENGTH = max(len(role) for role in CALENDAR_ROLES)

# One rejected component, as the panel reads it back. A JSONB array rather than a table:
# rejections are read only with their source, are replaced wholesale on every attempt, and
# nothing queries across them.
type RejectionRow = dict[str, Any]


class CalendarSource(Base, TenantScoped):
    """One calendar this tenant reads anchors from, or the one it projects the plan onto."""

    __tablename__ = CALENDAR_SOURCES_TABLE

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(PROVIDER_LENGTH), nullable=False)
    role: Mapped[str] = mapped_column(String(ROLE_LENGTH), nullable=False)
    display_name: Mapped[str] = mapped_column(String(DISPLAY_NAME_MAX_LENGTH), nullable=False)
    # A normalized feed URL for an ICS source, a calendarId for a Google one. The
    # reconciliation key for the source itself, which is why it is unique per tenant.
    external_id: Mapped[str] = mapped_column(String(EXTERNAL_ID_MAX_LENGTH), nullable=False)
    included: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=True)
    horizon_days: Mapped[int | None] = mapped_column(SmallInteger(), nullable=True)

    # The embedded sync state. Written on every attempt, successful or not, so staleness is
    # always computable from the two instants.
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(LAST_ERROR_MAX_LENGTH), nullable=True)
    # An ICS ETag or Last-Modified date, or a Google syncToken. Which one it holds is written
    # into the value by the adapter that stores it.
    cursor: Mapped[str | None] = mapped_column(String(CURSOR_MAX_LENGTH), nullable=True)
    events_read: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    anchors_current: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    rejections: Mapped[list[RejectionRow] | None] = mapped_column(NULLABLE_JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(values_in("provider", CALENDAR_PROVIDERS), name="provider_is_known"),
        CheckConstraint(values_in("role", CALENDAR_ROLES), name="role_is_known"),
        CheckConstraint(
            f"(role = '{WRITE_TARGET}') = (horizon_days IS NOT NULL)",
            name="only_the_write_target_carries_a_horizon",
        ),
        CheckConstraint(
            f"horizon_days IS NULL OR horizon_days BETWEEN {HORIZON_DAYS_MIN} "
            f"AND {HORIZON_DAYS_MAX}",
            name="horizon_days_within_the_projection_range",
        ),
        CheckConstraint(
            "events_read >= 0 AND anchors_current >= 0", name="counts_are_not_negative"
        ),
        # One source per feed per tenant. Adding the same URL twice would double every anchor
        # it contributes. A unique INDEX rather than a unique CONSTRAINT, matching the
        # convention plan storage set: the metadata's `uq` naming rule derives a name from the
        # first column alone, so a constraint spanning three would be named after one of them.
        Index(
            f"uq_{CALENDAR_SOURCES_TABLE}_{TENANT_ID_COLUMN}_provider_external_id",
            TENANT_ID_COLUMN,
            "provider",
            "external_id",
            unique=True,
        ),
        # The one-write-target invariant, enforced by the schema rather than by convention.
        Index(
            "uq_calendar_sources_tenant_id_write_target",
            TENANT_ID_COLUMN,
            unique=True,
            postgresql_where=text(f"role = '{WRITE_TARGET}'"),
        ),
        # Every listing read is this tenant's sources in the order they were added, which is
        # the order the Settings panel shows them in.
        Index(
            f"ix_{CALENDAR_SOURCES_TABLE}_{TENANT_ID_COLUMN}_created_at",
            TENANT_ID_COLUMN,
            "created_at",
        ),
    )
