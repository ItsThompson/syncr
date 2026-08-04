"""The one table: the spans that bound a day.

**There is no ``area_id`` column, and the absence is the design.** A routine defines how much
time exists, so it is not competing for it: it carries no Area, it therefore carries no
pigment, and it never appears in Area budget arithmetic. A column here would make the frame
assignable to a wedge of the pie, and the denominator would then include time it had already
subtracted.

``target_time`` is wall time: no date and no zone. It becomes an instant per day, resolved
against the zone active on that day, which is what makes ``Wake 05:00`` mean 05:00 wherever
the user is. Storing an instant would freeze the frame to the zone it was authored in.

``min_duration_minutes`` is the elastic floor, and the sleep floor is this column on the sleep
routine. There is nowhere else it lives: settings has no field for it. The check constraint
allows a value below the target and the boundary defaults it to equality, so a routine is
inelastic unless the caller asks for give.

``flex_band_minutes`` is how far a placement may MOVE the routine. Nothing resizes one, so
there is deliberately no column recording a resized duration: the effective duration of one
occurrence is derived per week by the assembler and is not stored here.

No unique constraint on the title. Two routines may share one legitimately, ``Shower`` in the
morning and ``Shower`` in the evening being the obvious pair, and nothing about a routine's
identity rests on its title the way an Area's does once the pigment ramp repeats.
"""

from __future__ import annotations

from datetime import datetime, time
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Index, SmallInteger, String, Time
from sqlalchemy.orm import Mapped, mapped_column

from syncr_api.core.orm import Base
from syncr_api.core.tenancy import TENANT_ID_COLUMN, TenantScoped
from syncr_api.routines.config import ROUTINE_TITLE_MAX_LENGTH, ROUTINES_TABLE
from syncr_domain.routines import (
    MAX_DURATION_MINUTES,
    MAX_FLEX_BAND_MINUTES,
    MIN_DURATION_MINUTES,
)


class RoutineRow(Base, TenantScoped):
    """One routine: a target wall time, a span, a floor, and a band that shifts it.

    Named for the row rather than for the concept, because ``syncr_domain.routines.RoutineSpan``
    is the concept the frame's arithmetic is stated over: the row is what persistence knows,
    and the span is what resolves to an interval on a date.
    """

    __tablename__ = ROUTINES_TABLE
    __table_args__ = (
        # A routine is a span, not a marker: without a duration there is nothing to subtract
        # from the day. The upper bound is the day the routine names, and it is a cap rather
        # than a guarantee: it does not keep an occurrence clear of its own next one, and no
        # cap can, because a 23-hour spring-forward day makes a 1440-minute span overlap the
        # next date's and a date a zone skips gives two dates one instant. The week assembler
        # owns frame overlap.
        CheckConstraint(
            f"duration_minutes BETWEEN {MIN_DURATION_MINUTES} AND {MAX_DURATION_MINUTES}",
            name="duration_is_a_span",
        ),
        # The floor may sit below the target, which is what makes a routine elastic, and it may
        # not sit above it or at zero: a routine that could be compressed to nothing would let
        # the solver delete the frame instead of negotiating with it.
        CheckConstraint(
            "min_duration_minutes > 0 AND min_duration_minutes <= duration_minutes",
            name="minimum_is_within_the_target",
        ),
        CheckConstraint(
            f"flex_band_minutes BETWEEN 0 AND {MAX_FLEX_BAND_MINUTES}",
            name="flex_band_shifts_within_half_a_day",
        ),
        # Every read is this tenant's whole frame, in the order the day runs.
        Index(
            f"ix_{ROUTINES_TABLE}_{TENANT_ID_COLUMN}_target_time",
            TENANT_ID_COLUMN,
            "target_time",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(ROUTINE_TITLE_MAX_LENGTH), nullable=False)
    # Wall time: no date and no zone. It resolves against whichever zone is active on the day
    # it materializes, which is why it is not stored as an instant.
    target_time: Mapped[time] = mapped_column(Time(), nullable=False)
    # The TARGET span. A routine is a span, not a marker.
    duration_minutes: Mapped[int] = mapped_column(SmallInteger(), nullable=False)
    # The floor. Equal to the target unless the caller asked for give, which is what makes a
    # routine inelastic by default. The sleep floor is this column on the sleep routine.
    min_duration_minutes: Mapped[int] = mapped_column(SmallInteger(), nullable=False)
    # How far a placement may SHIFT the routine, never how far it may shrink it.
    flex_band_minutes: Mapped[int] = mapped_column(SmallInteger(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
