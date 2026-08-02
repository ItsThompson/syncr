"""The two tables: one settings row per tenant, and the travel overrides that displace it.

``settings`` takes ``tenant_id`` as its PRIMARY KEY, which is what makes "one row per
tenant" a property of the database rather than a rule a repository has to keep. The
column itself comes from the scoped mixin, so its type and its cascading foreign key are
stated in one place for every table in the product.

``TravelOverrideRow`` is named for the row rather than for the concept because
``syncr_domain.zones.TravelOverride`` is the concept, and the service holds both at once:
the row is what persistence knows, the domain value is what resolves a zone. Two names
for two things beats one name meaning whichever is in scope.

The non-overlap invariant is NOT a database constraint. Enforcing it in SQL would need an
exclusion constraint over a date range, which is a second implementation of a rule
``ZoneProfile`` already owns, and the two could then disagree. The service serializes
every declaration on the tenant's own settings row instead, so the domain check is the
only implementation and it cannot be raced.
"""

from __future__ import annotations

from datetime import date, datetime, time
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Index,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Time,
)
from sqlalchemy.orm import Mapped, mapped_column

from syncr_api.core.orm import Base
from syncr_api.core.tenancy import TENANT_ID_COLUMN, TenantScoped
from syncr_api.user_settings.config import (
    DAY_END_DEFAULT,
    DAY_START_DEFAULT,
    HOME_ZONE_DEFAULT,
    REVIEW_CADENCE_DEFAULT,
    SETTINGS_TABLE,
    TRAVEL_OVERRIDES_TABLE,
    VISIBLE_HOURS_DEFAULT,
    VISIBLE_HOURS_MAX,
    VISIBLE_HOURS_MIN,
    ReviewCadence,
)
from syncr_domain.zones import MAX_ZONE_KEY_LENGTH

# A varchar plus a CHECK rather than a Postgres enum type: adding a cadence later is then
# a check-constraint edit rather than an ALTER TYPE, and the constraint is generated from
# the enum so the two cannot drift. `create_constraint` is stated because SQLAlchemy
# defaults it to False, which would leave the column accepting any string of the right
# length. `values_callable` stores the member VALUES, which are what the wire and the
# generated TypeScript carry.
_REVIEW_CADENCE_COLUMN = Enum(
    ReviewCadence,
    native_enum=False,
    create_constraint=True,
    length=max(len(cadence.value) for cadence in ReviewCadence),
    values_callable=lambda enum: [member.value for member in enum],
    name="review_cadence",
)


class Settings(Base, TenantScoped):
    """One tenant's configuration.

    ``day_start < day_end`` is checked here as well as at the boundary. The Week grid
    derives its default extent as the interval between them, and an interval needs a
    positive length, so a row that inverted them would be a rendering fault rather than
    a bad request.
    """

    __tablename__ = SETTINGS_TABLE
    __table_args__ = (
        PrimaryKeyConstraint(TENANT_ID_COLUMN),
        CheckConstraint(
            f"visible_hours BETWEEN {VISIBLE_HOURS_MIN} AND {VISIBLE_HOURS_MAX}",
            name="visible_hours_within_the_zoom_range",
        ),
        CheckConstraint("day_start < day_end", name="day_start_before_day_end"),
    )

    visible_hours: Mapped[int] = mapped_column(
        SmallInteger(), nullable=False, default=VISIBLE_HOURS_DEFAULT
    )
    # Wall time: no date and no zone. It resolves against whichever zone is active on the
    # day being rendered, which is why it is not stored as an instant.
    day_start: Mapped[time] = mapped_column(Time(), nullable=False, default=DAY_START_DEFAULT)
    day_end: Mapped[time] = mapped_column(Time(), nullable=False, default=DAY_END_DEFAULT)
    review_cadence: Mapped[ReviewCadence] = mapped_column(
        _REVIEW_CADENCE_COLUMN, nullable=False, default=REVIEW_CADENCE_DEFAULT
    )
    # Bounded by the domain's own limit on a zone identifier, so the column and the
    # lookup that reads it reject the same keys.
    home_zone: Mapped[str] = mapped_column(
        String(MAX_ZONE_KEY_LENGTH), nullable=False, default=HOME_ZONE_DEFAULT
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TravelOverrideRow(Base, TenantScoped):
    """A date range, inclusive at both ends, in which another zone is active."""

    __tablename__ = TRAVEL_OVERRIDES_TABLE
    __table_args__ = (
        CheckConstraint("start_date <= end_date", name="start_date_not_after_end_date"),
        # Every read is "this tenant's overrides, in date order", which is also the order
        # `ZoneProfile` wants them in.
        Index(
            f"ix_{TRAVEL_OVERRIDES_TABLE}_{TENANT_ID_COLUMN}_start_date",
            TENANT_ID_COLUMN,
            "start_date",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    start_date: Mapped[date] = mapped_column(Date(), nullable=False)
    end_date: Mapped[date] = mapped_column(Date(), nullable=False)
    zone: Mapped[str] = mapped_column(String(MAX_ZONE_KEY_LENGTH), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
