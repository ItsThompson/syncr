"""The one table: the spans a tenant declared off, stored as instants.

Two columns are named ``start`` and ``end`` because that is what the domain calls them, and
``end`` is a reserved word in SQL. SQLAlchemy quotes an identifier it knows the dialect
reserves, so the mapper reads and writes ``"end"``; anything hand-written against this table,
in a later revision or in ``psql``, has to quote it too.

**The interval is half-open, ``[start, end)``, and the database holds only the two instants.**
There is no stored duration and no stored week: a period's length is its two ends and a
period's weeks are whichever weeks its ends fall in, both resolved by the reader. A period
running from Friday to Monday is therefore ONE row that two weeks each hold part of, and no
write ever splits it.

Two rules are enforced here and two deliberately are not.

``start < end`` is a CHECK as well as an ``Interval`` invariant. A reversed row is
**unreadable** rather than merely odd: every reader builds an ``Interval`` from the pair and
``Interval`` refuses it, so such a row would fault the week view rather than render badly.

The quarter-hour grid is NOT a CHECK. It is one rule with one implementation, in
``syncr_domain.off_plan``, and every writer reaches this table through it. A row off the grid
would render a few minutes off the grid lines, which is a degradation rather than a fault, so
a second statement of the rule in SQL would buy a milder failure at the cost of a copy that
has to be edited when the grid is.

Non-overlap is NOT an exclusion constraint, for the reason ``travel_overrides`` states for the
same invariant: enforcing it in SQL would need a second implementation of a rule
``syncr_domain.off_plan.require_disjoint`` already owns, and the two could then disagree. The
service serializes every declaration on the tenant's own settings row instead, so the domain
check is the only implementation and it cannot be raced.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from syncr_api.core.orm import Base
from syncr_api.core.tenancy import TENANT_ID_COLUMN, TenantScoped
from syncr_api.offplan.config import LABEL_MAX_LENGTH, OFF_PLAN_TABLE


class OffPlanPeriodRow(Base, TenantScoped):
    """One declared span of time off.

    Named for the row rather than for the concept, because ``syncr_domain.off_plan.
    OffPlanPeriod`` is the concept the invariants are stated over: the row is what
    persistence knows, and the period is what the rules are written against.
    """

    __tablename__ = OFF_PLAN_TABLE
    __table_args__ = (
        CheckConstraint('start < "end"', name="start_before_end"),
        # Every read is either this tenant's periods in time order or the ones overlapping one
        # week's span, and both lead with the tenant and then with the start.
        Index(f"ix_{OFF_PLAN_TABLE}_{TENANT_ID_COLUMN}_start", TENANT_ID_COLUMN, "start"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    # The half-open bounds, as instants. Wall time is not stored: a span crossing a
    # daylight-saving transition is 68 elapsed hours where its two wall times differ by 67,
    # and the elapsed figure is the one every downstream reading needs.
    start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # False means no routine materializes inside the span, so the frame disappears with
    # everything else. True means routines materialize and nothing else does.
    keep_frame: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)
    # The user's own words, rendered in the gutter. Null when the span carries no name.
    label: Mapped[str | None] = mapped_column(String(LABEL_MAX_LENGTH), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
