"""The ``weight_sets`` table: 30 to 50 floats in a row, versioned per tenant.

There is no model registry, no artifact store, and no serialized binary, because the artifact is a
row. Each fitting run writes a NEW version rather than mutating the current one, so comparison and
rollback are free, and reverting is a flag rather than reprocessing history.

The PARTIAL UNIQUE index is what enforces "exactly one active version per tenant". Without it,
activating a version while another is active would be two rows both claiming to be the weights in
use, and the solve path would pick whichever the scan returned first.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID  # noqa: F401 - the tenancy mixin's annotation resolves here

from sqlalchemy import CheckConstraint, DateTime, Index, PrimaryKeyConstraint, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from syncr_api.core.columns import JsonObject, values_in
from syncr_api.core.orm import Base
from syncr_api.core.tenancy import TENANT_ID_COLUMN, TenantScoped
from syncr_api.learned.config import (
    FIRST_WEIGHT_SET_VERSION,
    FITTED,
    ORIGIN_MAX_LENGTH,
    WEIGHT_SET_ORIGINS,
    WEIGHT_SETS_TABLE,
)

_EMPTY_OBJECT = text("'{}'::jsonb")
_EMPTY_ARRAY = text("'[]'::jsonb")


class WeightSet(Base, TenantScoped):
    """One version of the numbers a solve was produced under."""

    __tablename__ = WEIGHT_SETS_TABLE

    version: Mapped[int] = mapped_column(nullable=False)
    active: Mapped[bool] = mapped_column(nullable=False)
    origin: Mapped[str] = mapped_column(String(ORIGIN_MAX_LENGTH), nullable=False)

    deadline_risk: Mapped[float] = mapped_column(nullable=False)
    budget_deviation: Mapped[float] = mapped_column(nullable=False)
    time_of_day_misfit: Mapped[float] = mapped_column(nullable=False)
    fragmentation: Mapped[float] = mapped_column(nullable=False)
    churn: Mapped[float] = mapped_column(nullable=False)
    context_switch: Mapped[float] = mapped_column(nullable=False)
    staleness: Mapped[float] = mapped_column(nullable=False)

    # Empty until a fitter has cleared that parameter's maturity gate. A parameter below its gate is
    # not applied at all, so absence is the correct representation of "unlearned" and a neutral
    # default would be a fitted-looking number nobody fitted.
    duration_multiplier: Mapped[JsonObject] = mapped_column(
        JSONB, nullable=False, server_default=_EMPTY_OBJECT
    )
    time_of_day_fitness: Mapped[JsonObject] = mapped_column(
        JSONB, nullable=False, server_default=_EMPTY_OBJECT
    )
    skip_probability: Mapped[JsonObject] = mapped_column(
        JSONB, nullable=False, server_default=_EMPTY_OBJECT
    )
    context_switch_cost: Mapped[float] = mapped_column(nullable=False)
    churn_tolerance: Mapped[float] = mapped_column(nullable=False)

    fitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    maturity: Mapped[list[JsonObject]] = mapped_column(
        JSONB, nullable=False, server_default=_EMPTY_ARRAY
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint(TENANT_ID_COLUMN, "version"),
        CheckConstraint(values_in("origin", WEIGHT_SET_ORIGINS), name="origin_is_known"),
        CheckConstraint(f"version >= {FIRST_WEIGHT_SET_VERSION}", name="version_starts_at_one"),
        # A fitted set states when it was fitted, and a hand-tuned set was never fitted at all, so
        # one column cannot claim what the other denies.
        CheckConstraint(
            f"(origin = '{FITTED}') = (fitted_at IS NOT NULL)", name="fitted_states_when"
        ),
        Index(
            "uq_weight_sets_tenant_id_active",
            TENANT_ID_COLUMN,
            unique=True,
            postgresql_where=text("active"),
        ),
    )
