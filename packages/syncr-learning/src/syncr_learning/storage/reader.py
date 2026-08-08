"""The Postgres corpus reader: four reads, none of them a write.

Statements are built with SQLAlchemy Core over table names rather than over mapped classes, because
the mapped classes belong to the api and this package cannot import it. What that buys is that every
column this job reads is named at the call site, so the restated spelling is one module and the
agreement test can cross all of it.

**Every read is scoped to one tenant.** The tenant list is the one exception and it is the scope
itself. There is no row-level security in this deployment, so the predicate is the guarantee, and it
is applied where the statement is built rather than filtered afterwards.

The reads are BOUNDED by a lookback, because a corpus grows forever and the nightly budget is five
minutes. The bound is a year of weeks, which is roughly 3,250 timed blocks for one user: past that
the duration multiplier has long since matured and older rows would move it by less than the outlier
bound.

**All five reads carry the bound**, each through the column it has. The revisions, the pins and the
edits filter on ``iso_week``; the outcomes filter on ``occurred_at`` and the off-plan spans on their
end, because neither table names a week. An earlier version bounded three of the five and said it
bounded all of them, which matters because the bound IS the justification for the budget, and
``edit_events`` is the one table ``E5`` forbids pruning: it is the one that grows without limit.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from typing import TYPE_CHECKING, Final

from sqlalchemy import column, select, table

from syncr_domain.intervals import Interval
from syncr_domain.outcomes import OutcomeState
from syncr_domain.promotion import PinPlacement
from syncr_domain.weeks import IsoWeek
from syncr_learning.facts import (
    LoggedOutcome,
    OffPlanSpan,
    RecordedEdit,
    StoredRevision,
    TenantCorpus,
)
from syncr_learning.storage import documents, spelling

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from syncr_domain.identifiers import TenantId

LOOKBACK_WEEKS: Final = 52
"""How far back a run reads. A year, and the reason the read is bounded is the 5-minute budget.

Older rows are not excluded because they are wrong: they are excluded because a mature parameter
moves by less than its own outlier bound from one more observation, so the cost of reading them is
real and the benefit is not.
"""

_TENANTS = table(spelling.TENANTS, column(spelling.ID))
_SETTINGS = table(spelling.SETTINGS, column(spelling.TENANT_ID), column(spelling.HOME_ZONE))
_AREAS = table(
    spelling.AREAS, column(spelling.ID), column(spelling.TENANT_ID), column(spelling.NAME)
)
_REVISIONS = table(
    spelling.PLAN_REVISIONS,
    column(spelling.TENANT_ID),
    column(spelling.ISO_WEEK),
    column(spelling.CREATED_AT),
    column(spelling.DOCUMENT),
)
_OUTCOMES = table(
    spelling.BLOCK_OUTCOMES,
    column(spelling.TENANT_ID),
    column(spelling.BLOCK_ID),
    column(spelling.STATE),
    column(spelling.ACTUAL_MINUTES),
    column(spelling.ACTUAL_STARTS_AT),
    column(spelling.ACTUAL_ENDS_AT),
    # Read for the lookback rather than for a fitter: `block_outcomes` names no week, so this is the
    # column the bound is applied through.
    column(spelling.OCCURRED_AT),
    column(spelling.CONFIRMED_AT),
)
_EDITS = table(
    spelling.EDIT_EVENTS,
    column(spelling.TENANT_ID),
    column(spelling.ISO_WEEK),
    column(spelling.CREATED_AT),
    column("proposed_starts_at"),
    column("proposed_ends_at"),
    column("accepted_starts_at"),
    column("accepted_ends_at"),
    column(spelling.OBJECTIVE_DELTA),
    column(spelling.CONTEXT),
    column(spelling.WEIGHT_SET_VERSION),
)
_PINS = table(
    spelling.PINS,
    column(spelling.TENANT_ID),
    column(spelling.ISO_WEEK),
    column(spelling.BINDING),
    column(spelling.STARTS_AT),
)
# `end` is a reserved word in SQL. `column()` quotes an identifier it knows the dialect reserves,
# the same way the mapper does, so the name is written plainly here and the quoting is the driver's.
_OFF_PLAN = table(
    spelling.OFF_PLAN_PERIODS,
    column(spelling.TENANT_ID),
    column(spelling.SPAN_START),
    column(spelling.SPAN_END),
)
_WEIGHT_SETS = table(
    spelling.WEIGHT_SETS,
    column(spelling.TENANT_ID),
    column(spelling.VERSION),
    column(spelling.ACTIVE),
    column("deadline_risk"),
    column("budget_deviation"),
    column("time_of_day_misfit"),
    column("fragmentation"),
    column("churn"),
    column("context_switch"),
    column("staleness"),
    column("context_switch_cost"),
    column("churn_tolerance"),
)

_IN_FORCE_FIGURES: Final[tuple[str, ...]] = (
    "deadline_risk",
    "budget_deviation",
    "time_of_day_misfit",
    "fragmentation",
    "churn",
    "context_switch",
    "staleness",
    "context_switch_cost",
    "churn_tolerance",
)


class PostgresCorpusReader:
    """One deployment's corpus, over a session factory. Reads only."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], *, now: datetime) -> None:
        self._sessions = sessions
        self._from = IsoWeek.containing(now.date())
        self._oldest = _weeks_back(self._from, LOOKBACK_WEEKS)
        # The same bound as an instant, for the two tables that name no week. Taken from the oldest
        # week's own Monday rather than from `now` minus a year, so one figure bounds all five
        # reads.
        self._since = datetime.combine(self._oldest.monday(), time.min, tzinfo=UTC)

    async def tenants(self) -> Sequence[TenantId]:
        """Every tenant, in identifier order, so a run's log reads the same way twice."""
        async with self._sessions() as session:
            rows = await session.execute(select(_TENANTS.c.id).order_by(_TENANTS.c.id))
            return [row.id for row in rows]

    async def corpus(self, tenant_id: TenantId) -> TenantCorpus:
        """One tenant's revisions, outcomes, edits, pins and off-plan spans, over the lookback."""
        async with self._sessions() as session:
            return TenantCorpus(
                tenant_id=tenant_id,
                revisions=await self._revisions(session, tenant_id),
                outcomes=await self._outcomes(session, tenant_id),
                edits=await self._edits(session, tenant_id),
                pins=await self._pins(session, tenant_id),
                off_plan=await self._off_plan(session, tenant_id),
            )

    async def weights_in_force(self, tenant_id: TenantId) -> Mapping[str, float] | None:
        """The seven weights and the two scalars the active version carries."""
        async with self._sessions() as session:
            found = (
                await session.execute(
                    select(_WEIGHT_SETS).where(
                        _WEIGHT_SETS.c.tenant_id == tenant_id,
                        _WEIGHT_SETS.c.active.is_(True),
                    )
                )
            ).first()
        if found is None:
            return None
        return {name: float(getattr(found, name)) for name in _IN_FORCE_FIGURES}

    async def area_names(self, tenant_id: TenantId) -> Mapping[str, str]:
        """Each Area's own name by its identifier, for the plain-language statements."""
        async with self._sessions() as session:
            rows = await session.execute(
                select(_AREAS.c.id, _AREAS.c.name).where(_AREAS.c.tenant_id == tenant_id)
            )
            return {str(row.id): row.name for row in rows}

    async def _home_zone(self, session: AsyncSession, tenant_id: TenantId) -> str | None:
        """The zone a template entry's wall time is declared in, which is what a pin groups on.

        One statement, called from the one place that needs it. It was a public method with no
        caller beside an inline copy of the same query, which is two answers to one question.
        """
        return await session.scalar(
            select(_SETTINGS.c.home_zone).where(_SETTINGS.c.tenant_id == tenant_id)
        )

    async def _revisions(
        self, session: AsyncSession, tenant_id: TenantId
    ) -> tuple[StoredRevision, ...]:
        rows = await session.execute(
            select(_REVISIONS)
            .where(
                _REVISIONS.c.tenant_id == tenant_id,
                _REVISIONS.c.iso_week >= str(self._oldest),
            )
            .order_by(_REVISIONS.c.iso_week, _REVISIONS.c.created_at)
        )
        return tuple(
            StoredRevision(
                iso_week=IsoWeek.parse(row.iso_week),
                created_at=row.created_at,
                zone_by_date=documents.zone_by_date(row.document),
                blocks=documents.planned_blocks(row.document),
            )
            for row in rows
        )

    async def _outcomes(
        self, session: AsyncSession, tenant_id: TenantId
    ) -> tuple[LoggedOutcome, ...]:
        rows = await session.execute(
            select(_OUTCOMES).where(
                _OUTCOMES.c.tenant_id == tenant_id, _OUTCOMES.c.occurred_at >= self._since
            )
        )
        return tuple(
            LoggedOutcome(
                block_id=row.block_id,
                state=OutcomeState(row.state),
                actual_minutes=row.actual_minutes,
                actual=_actual(row.actual_starts_at, row.actual_ends_at),
                is_confirmed=row.confirmed_at is not None,
            )
            for row in rows
        )

    async def _edits(self, session: AsyncSession, tenant_id: TenantId) -> tuple[RecordedEdit, ...]:
        rows = await session.execute(
            select(_EDITS)
            .where(_EDITS.c.tenant_id == tenant_id, _EDITS.c.iso_week >= str(self._oldest))
            .order_by(_EDITS.c.created_at)
        )
        return tuple(
            RecordedEdit(
                iso_week=IsoWeek.parse(row.iso_week),
                created_at=row.created_at,
                proposed=Interval(row.proposed_starts_at, row.proposed_ends_at),
                accepted=Interval(row.accepted_starts_at, row.accepted_ends_at),
                objective_delta=row.objective_delta,
                measurement_delta=documents.measurement_delta(row.context),
                weight_set_version=row.weight_set_version,
                inside_off_plan=documents.inside_off_plan(row.context),
            )
            for row in rows
        )

    async def _pins(self, session: AsyncSession, tenant_id: TenantId) -> tuple[PinPlacement, ...]:
        zone = await self._home_zone(session, tenant_id)
        if zone is None:
            # A tenant with no settings row has no home zone, so no wall time a template could hold.
            # Promotion detection is the only reader of pins and it groups on that wall time.
            return ()
        rows = await session.execute(
            select(_PINS)
            .where(_PINS.c.tenant_id == tenant_id, _PINS.c.iso_week >= str(self._oldest))
            .order_by(_PINS.c.iso_week, _PINS.c.starts_at)
        )
        found = []
        for row in rows:
            identity = documents.binding(row.binding)
            if identity is None:
                continue
            found.append(
                PinPlacement(
                    binding=identity,
                    iso_week=IsoWeek.parse(row.iso_week),
                    starts_at=row.starts_at,
                    zone=zone,
                )
            )
        return tuple(found)

    async def _off_plan(
        self, session: AsyncSession, tenant_id: TenantId
    ) -> tuple[OffPlanSpan, ...]:
        rows = await session.execute(
            select(_OFF_PLAN).where(
                _OFF_PLAN.c.tenant_id == tenant_id,
                # Bounded on the span's END rather than its start, so a long holiday declared two
                # years ago and still running is kept. A span that ENDED before the lookback opens
                # governs no week this run reads.
                getattr(_OFF_PLAN.c, spelling.SPAN_END) >= self._since,
            )
        )
        return tuple(
            OffPlanSpan(interval=Interval(row.start, getattr(row, spelling.SPAN_END)))
            for row in rows
        )


def _actual(starts_at: datetime | None, ends_at: datetime | None) -> Interval | None:
    """The interval a ``moved`` outcome happened in. Both ends or neither, which the row checks."""
    if starts_at is None or ends_at is None:
        return None
    return Interval(starts_at, ends_at)


def _weeks_back(week: IsoWeek, count: int) -> IsoWeek:
    """The week ``count`` weeks before ``week``, walked through the calendar.

    Walked rather than subtracted, because 2027-W01 precedes into 2026-W53 and 2026-W01 into
    2025-W52, so the week number alone does not decide the answer and neither does the ISO year.
    """
    found = week
    for _ in range(count):
        found = found.preceding()
    return found
