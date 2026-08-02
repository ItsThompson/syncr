"""The settings tables as Postgres sees them, and the race the row lock closes.

Four things here cannot be proven anywhere else.

**The constraints are real.** A visible-hours value outside the zoom range, a day that ends
before it starts, and a review cadence the enum does not name are all rejected by the
database, so a row that would render a broken axis cannot exist even if a caller reached
the table another way.

**One row per tenant is the primary key.** A second insert is rejected by Postgres rather
than by a repository remembering to update instead.

**Every statement carries the scope.** Compiling a statement proves what a repository
built; the recorder proves what reached Postgres. These are the first production tables
the rule applies to.

**Two concurrent declarations cannot both land.** That is the interesting one. The overlap
rule lives in the domain and runs against the rows already stored, so without
serialization two requests would both read the same rows, both pass the check, and both
insert, leaving a tenant with no single active zone on a date. The control below runs the
same race with the lock bypassed and asserts both rows land, so the lock is shown to be
what closes it rather than assumed to be.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from syncr_api.core.clock import utc_now
from syncr_api.core.db import create_db_engine, create_sessionmaker
from syncr_api.core.errors import Conflict
from syncr_api.core.principal import Principal
from syncr_api.core.scopes import ALL_SCOPES
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.user_settings.config import (
    DAY_END_DEFAULT,
    DAY_START_DEFAULT,
    HOME_ZONE_DEFAULT,
    REVIEW_CADENCE_DEFAULT,
    VISIBLE_HOURS_DEFAULT,
)
from syncr_api.user_settings.models import Settings, TravelOverrideRow
from syncr_api.user_settings.repository import SettingsRepository, TravelOverrideRepository
from syncr_api.user_settings.service import SettingsChange, SettingsService
from syncr_api.user_settings.solve_inputs import TrackedWeekInputVersions
from syncr_domain.weeks import IsoWeek
from tests.control_models import recording
from tests.live_tenants import delete_tenant, seed_owner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
    from sqlalchemy.orm import DeclarativeBase
    from sqlalchemy.sql.elements import TextClause

    from syncr_api.accounts.records import UserRecord
    from syncr_api.user_settings.records import SettingsRecord
    from tests.control_models import StatementRecorder

pytestmark = pytest.mark.integration

TOKYO = "Asia/Tokyo"
SEOUL = "Asia/Seoul"

# Far enough ahead that these dates are never in the past when the suite runs, so the
# bump range is stable and the rows under test are always future-dated. 2099-03-02 is a
# Monday, so the range also reaches the week before it.
TRIP_START = date(2099, 3, 2)
TRIP_END = date(2099, 3, 6)


class UnlockedSettingsRepository(SettingsRepository):
    """The repository with its serialization point removed, for the control below.

    Reads the row without ``FOR UPDATE`` and creates it if absent, so two callers can be
    inside the overlap check at once. This is the defect the real ``lock`` prevents.
    """

    async def lock(self, *, created_at: datetime) -> SettingsRecord:
        found = await self._session.scalar(self.scoped_select(Settings))
        if found is None:
            await super().lock(created_at=created_at)
        return await self.read()


@pytest.fixture
async def engine(live_database_url: str) -> AsyncIterator[AsyncEngine]:
    """An engine owned by this test's own event loop."""
    live = create_db_engine(live_database_url)
    yield live
    await live.dispose()


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_sessionmaker(engine)


@pytest.fixture
async def owner(sessions: async_sessionmaker[AsyncSession]) -> AsyncIterator[UserRecord]:
    account = await seed_owner(sessions)
    yield account
    await delete_tenant(sessions, account.tenant_id)


@pytest.fixture
def principal(owner: UserRecord) -> Principal:
    return Principal(tenant_id=owner.tenant_id, user_id=owner.id, scopes=ALL_SCOPES)


@pytest.fixture
def recorder(engine: AsyncEngine) -> Iterator[StatementRecorder]:
    """Records the SQL Postgres actually executed for the duration of one test."""
    yield from recording(engine)


def build_service(session: AsyncSession, principal: Principal) -> SettingsService:
    """The service as the request path wires it, counter included."""
    return SettingsService(
        settings=SettingsRepository(session, principal.tenant_id),
        overrides=TravelOverrideRepository(session, principal.tenant_id),
        versions=TrackedWeekInputVersions(
            WeekInputVersionRepository(session, principal.tenant_id), clock=utc_now
        ),
        clock=utc_now,
    )


# --------------------------------------------------------------------------------
# The row, its defaults, and the constraints on it
# --------------------------------------------------------------------------------


async def test_locking_creates_the_row_with_the_declared_defaults(
    sessions: async_sessionmaker[AsyncSession], principal: Principal
) -> None:
    async with sessions() as session, session.begin():
        repository = SettingsRepository(session, principal.tenant_id)
        created = await repository.lock(created_at=utc_now())

    assert created.visible_hours == VISIBLE_HOURS_DEFAULT
    assert (created.day_start, created.day_end) == (DAY_START_DEFAULT, DAY_END_DEFAULT)
    assert created.review_cadence == REVIEW_CADENCE_DEFAULT
    assert created.home_zone == HOME_ZONE_DEFAULT

    async with sessions() as session:
        rows = list(
            await session.scalars(select(Settings).where(Settings.tenant_id == principal.tenant_id))
        )
    assert len(rows) == 1


async def test_locking_twice_leaves_one_row(
    sessions: async_sessionmaker[AsyncSession], principal: Principal
) -> None:
    for _ in range(2):
        async with sessions() as session, session.begin():
            await SettingsRepository(session, principal.tenant_id).lock(created_at=utc_now())

    async with sessions() as session:
        rows = list(
            await session.scalars(select(Settings).where(Settings.tenant_id == principal.tenant_id))
        )
    assert len(rows) == 1


async def test_a_second_settings_row_for_one_tenant_is_rejected_by_the_database(
    sessions: async_sessionmaker[AsyncSession], principal: Principal
) -> None:
    async with sessions() as session, session.begin():
        await SettingsRepository(session, principal.tenant_id).lock(created_at=utc_now())

    with pytest.raises(IntegrityError):
        await _insert(sessions, _a_settings_row(principal))


@pytest.mark.parametrize("visible_hours", [5, 25, 0, -1])
async def test_a_visible_hours_value_outside_the_zoom_range_is_rejected(
    sessions: async_sessionmaker[AsyncSession], principal: Principal, visible_hours: int
) -> None:
    with pytest.raises(IntegrityError, match="visible_hours_within_the_zoom_range"):
        await _insert(sessions, _a_settings_row(principal, visible_hours=visible_hours))


@pytest.mark.parametrize(
    ("day_start", "day_end"),
    [
        # Inverted: an axis that runs backwards.
        (time(23, 0), time(6, 0)),
        # Equal: an axis of no length.
        (time(9, 0), time(9, 0)),
    ],
)
async def test_a_day_that_ends_before_it_starts_is_rejected(
    sessions: async_sessionmaker[AsyncSession],
    principal: Principal,
    day_start: time,
    day_end: time,
) -> None:
    with pytest.raises(IntegrityError, match="day_start_before_day_end"):
        await _insert(sessions, _a_settings_row(principal, day_start=day_start, day_end=day_end))


async def test_a_review_cadence_the_vocabulary_does_not_name_is_rejected(
    sessions: async_sessionmaker[AsyncSession], principal: Principal
) -> None:
    # Written as SQL on purpose: the mapper would refuse the value before Postgres saw it,
    # and what is under test is that the COLUMN refuses it. `weekly` fits the column's
    # width, so it is the check constraint that rejects it rather than the length.
    unknown_cadence = text(
        "INSERT INTO settings (tenant_id, visible_hours, day_start, day_end, "
        "review_cadence, home_zone, created_at) VALUES (:tenant, 12, '07:00', "
        "'23:00', 'weekly', 'UTC', now())"
    )

    with pytest.raises(IntegrityError, match="review_cadence"):
        await _execute(sessions, unknown_cadence, {"tenant": principal.tenant_id})


async def test_a_range_that_ends_before_it_starts_is_rejected_by_the_database(
    sessions: async_sessionmaker[AsyncSession], principal: Principal
) -> None:
    inverted = TravelOverrideRow(
        id=uuid4(),
        tenant_id=principal.tenant_id,
        start_date=TRIP_END,
        end_date=TRIP_START,
        zone=TOKYO,
        created_at=utc_now(),
    )

    with pytest.raises(IntegrityError, match="start_date_not_after_end_date"):
        await _insert(sessions, inverted)


async def test_both_tables_cascade_with_the_tenant(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Removed here rather than through the `owner` fixture, because the deletion IS the
    # subject: a settings row surviving its tenant would reference a scope that is gone.
    doomed = await seed_owner(sessions)
    principal = Principal(tenant_id=doomed.tenant_id, user_id=doomed.id, scopes=ALL_SCOPES)
    async with sessions() as session, session.begin():
        service = build_service(session, principal)
        await service.update(principal, SettingsChange(visible_hours=18))
        await service.declare_travel_override(
            principal, start_date=TRIP_START, end_date=TRIP_END, zone=TOKYO
        )

    await delete_tenant(sessions, doomed.tenant_id)

    async with sessions() as session:
        settings_rows = list(
            await session.scalars(select(Settings).where(Settings.tenant_id == doomed.tenant_id))
        )
        override_rows = list(
            await session.scalars(
                select(TravelOverrideRow).where(TravelOverrideRow.tenant_id == doomed.tenant_id)
            )
        )
    assert (settings_rows, override_rows) == ([], [])


# --------------------------------------------------------------------------------
# The version bump, against real version rows
# --------------------------------------------------------------------------------

# Far from today in both directions, so "which week is current" cannot decide the outcome:
# every home-zone change invalidates the future week and none invalidates the past one.
_TODAY = utc_now().date()
_FUTURE_WEEK = IsoWeek.containing(_TODAY + timedelta(days=60))
_PAST_WEEK = IsoWeek.containing(_TODAY - timedelta(days=60))
_UNTRACKED_WEEK = IsoWeek.containing(_TODAY + timedelta(days=120))


async def test_a_home_zone_change_bumps_a_tracked_future_week_and_not_a_past_one(
    sessions: async_sessionmaker[AsyncSession], principal: Principal
) -> None:
    async with sessions() as session, session.begin():
        versions = WeekInputVersionRepository(session, principal.tenant_id)
        for week in (_PAST_WEEK, _FUTURE_WEEK):
            await versions.bump(week, at=utc_now())

    async with sessions() as session, session.begin():
        service = build_service(session, principal)
        await service.update(principal, SettingsChange(home_zone=TOKYO))

    async with sessions() as session:
        versions = WeekInputVersionRepository(session, principal.tenant_id)
        assert await versions.current(_FUTURE_WEEK) == 2
        # An approved revision is immutable and keeps the span it was computed with, so a
        # past week must not be re-derived.
        assert await versions.current(_PAST_WEEK) == 1
        # A week nothing has planned gets no row: it has no solve to invalidate.
        assert await versions.current(_UNTRACKED_WEEK) is None


async def test_a_visible_hours_change_bumps_nothing_in_the_database(
    sessions: async_sessionmaker[AsyncSession], principal: Principal
) -> None:
    # The control for the bump above. The grid's zoom is not a solve input, so a save from
    # the Settings screen must not enqueue a solve for every week that has a plan.
    async with sessions() as session, session.begin():
        await WeekInputVersionRepository(session, principal.tenant_id).bump(
            _FUTURE_WEEK, at=utc_now()
        )

    async with sessions() as session, session.begin():
        await build_service(session, principal).update(principal, SettingsChange(visible_hours=20))

    async with sessions() as session:
        current = await WeekInputVersionRepository(session, principal.tenant_id).current(
            _FUTURE_WEEK
        )
    assert current == 1


async def test_declaring_a_travel_override_bumps_only_the_weeks_its_range_reaches(
    sessions: async_sessionmaker[AsyncSession], principal: Principal
) -> None:
    trip_week = IsoWeek.containing(TRIP_START)
    async with sessions() as session, session.begin():
        versions = WeekInputVersionRepository(session, principal.tenant_id)
        for week in (trip_week, _FUTURE_WEEK):
            await versions.bump(week, at=utc_now())

    async with sessions() as session, session.begin():
        await build_service(session, principal).declare_travel_override(
            principal, start_date=TRIP_START, end_date=TRIP_END, zone=TOKYO
        )

    async with sessions() as session:
        versions = WeekInputVersionRepository(session, principal.tenant_id)
        assert await versions.current(trip_week) == 2
        # A tracked week outside the range keeps its version: the override changes no zone
        # on any of its days.
        assert await versions.current(_FUTURE_WEEK) == 1


# --------------------------------------------------------------------------------
# The scope, as Postgres received it
# --------------------------------------------------------------------------------


async def test_every_statement_these_repositories_execute_carries_the_tenant_predicate(
    recorder: StatementRecorder,
    sessions: async_sessionmaker[AsyncSession],
    principal: Principal,
) -> None:
    async with sessions() as session, session.begin():
        service = build_service(session, principal)
        await service.read(principal)
        created = await service.declare_travel_override(
            principal, start_date=TRIP_START, end_date=TRIP_END, zone=TOKYO
        )
        await service.list_travel_overrides(principal)
        await service.remove_travel_override(principal, created.id)

    for table in ("settings", "travel_overrides"):
        # The rule is stated over statements that FILTER rows. On an insert the scope is a
        # column value rather than a predicate, which is why the scoped base offers no
        # insert helper, so those are read separately below.
        filtered = [
            statement
            for statement in recorder.without_a_tenant_predicate(table)
            if not statement.startswith("INSERT")
        ]
        assert filtered == [], f"{table}: {filtered}"
        # The control for the reading above: it saw statements at all.
        assert recorder.against(table)

    inserts = [
        statement
        for table in ("settings", "travel_overrides")
        for statement in recorder.against(table)
        if statement.startswith(f"INSERT INTO {table} ")
    ]
    assert len(inserts) == 2, f"expected one insert per table, got {inserts}"
    assert all("tenant_id" in statement for statement in inserts), inserts


async def test_one_tenants_overrides_are_invisible_to_another(
    sessions: async_sessionmaker[AsyncSession], principal: Principal
) -> None:
    stranger = await seed_owner(sessions)
    try:
        async with sessions() as session, session.begin():
            await build_service(session, principal).declare_travel_override(
                principal, start_date=TRIP_START, end_date=TRIP_END, zone=TOKYO
            )

        stranger_principal = Principal(
            tenant_id=stranger.tenant_id, user_id=stranger.id, scopes=ALL_SCOPES
        )
        async with sessions() as session:
            listed = await build_service(session, stranger_principal).list_travel_overrides(
                stranger_principal
            )
        assert listed == ()
    finally:
        await delete_tenant(sessions, stranger.tenant_id)


# --------------------------------------------------------------------------------
# The race, and its control
# --------------------------------------------------------------------------------


async def test_two_concurrent_overlapping_declarations_leave_one_row(
    sessions: async_sessionmaker[AsyncSession], principal: Principal
) -> None:
    outcomes = await _declare_concurrently(
        sessions,
        principal,
        first=(TRIP_START, TRIP_END, TOKYO),
        second=(TRIP_START, TRIP_END, SEOUL),
    )

    refused = [outcome for outcome in outcomes if isinstance(outcome, Exception)]
    assert len(refused) == 1, outcomes
    assert isinstance(refused[0], Conflict)

    async with sessions() as session:
        rows = list(
            await session.scalars(
                select(TravelOverrideRow).where(TravelOverrideRow.tenant_id == principal.tenant_id)
            )
        )
    assert len(rows) == 1


async def test_two_concurrent_declarations_that_do_not_overlap_both_land(
    sessions: async_sessionmaker[AsyncSession], principal: Principal
) -> None:
    # The other half of the claim: the lock serializes the check, it does not turn every
    # concurrent declaration into a conflict.
    outcomes = await _declare_concurrently(
        sessions,
        principal,
        first=(TRIP_START, TRIP_END, TOKYO),
        second=(date(2099, 3, 7), date(2099, 3, 9), SEOUL),
    )

    assert [type(outcome).__name__ for outcome in outcomes if isinstance(outcome, Exception)] == []

    async with sessions() as session:
        rows = list(
            await session.scalars(
                select(TravelOverrideRow).where(TravelOverrideRow.tenant_id == principal.tenant_id)
            )
        )
    assert len(rows) == 2


async def test_without_the_lock_both_overlapping_declarations_land(
    sessions: async_sessionmaker[AsyncSession], principal: Principal
) -> None:
    # The control. It fails the product's invariant on purpose, against a repository whose
    # serialization point has been removed, so the test above is shown to be about the
    # lock rather than about the two coroutines happening not to interleave.
    outcomes = await _declare_concurrently(
        sessions,
        principal,
        first=(TRIP_START, TRIP_END, TOKYO),
        second=(TRIP_START, TRIP_END, SEOUL),
        settings_repository=UnlockedSettingsRepository,
    )

    assert [outcome for outcome in outcomes if isinstance(outcome, Exception)] == []

    async with sessions() as session:
        rows = list(
            await session.scalars(
                select(TravelOverrideRow).where(TravelOverrideRow.tenant_id == principal.tenant_id)
            )
        )
    assert len(rows) == 2, (
        "the unlocked repository was expected to admit both declarations, which is the "
        "race the real one closes"
    )
    # And the state it left is the one the product cannot read: two zones on one date.
    assert rows[0].start_date == rows[1].start_date


# How long the first declaration holds its transaction open, and how long the second waits
# before starting. The margin is generous because what is under test is an ordering, not a
# latency: the second must be inside the overlap check while the first is uncommitted.
_HOLD_SECONDS = 0.5
_STAGGER_SECONDS = 0.1


async def _declare_concurrently(
    sessions: async_sessionmaker[AsyncSession],
    principal: Principal,
    *,
    first: tuple[date, date, str],
    second: tuple[date, date, str],
    settings_repository: type[SettingsRepository] = SettingsRepository,
) -> list[object]:
    """Run two declarations in overlapping transactions, and report what each returned.

    The settings row is created and committed FIRST, deliberately. Creating it is an
    ``INSERT ... ON CONFLICT DO NOTHING``, and a second transaction inserting the same
    primary key waits for the first to finish, so with no row to begin with the two
    declarations would serialize on the insert and the lock would prove nothing. Once the
    row exists, ``FOR UPDATE`` is the only thing that serializes them.
    """
    async with sessions() as session, session.begin():
        await SettingsRepository(session, principal.tenant_id).lock(created_at=utc_now())

    async def declare(declaration: tuple[date, date, str], *, wait: float, hold: float) -> object:
        await asyncio.sleep(wait)
        start_date, end_date, zone = declaration
        async with sessions() as session, session.begin():
            service = SettingsService(
                settings=settings_repository(session, principal.tenant_id),
                overrides=TravelOverrideRepository(session, principal.tenant_id),
                versions=TrackedWeekInputVersions(
                    WeekInputVersionRepository(session, principal.tenant_id), clock=utc_now
                ),
                clock=utc_now,
            )
            declared = await service.declare_travel_override(
                principal, start_date=start_date, end_date=end_date, zone=zone
            )
            await asyncio.sleep(hold)
            return declared

    return list(
        await asyncio.gather(
            declare(first, wait=0, hold=_HOLD_SECONDS),
            declare(second, wait=_STAGGER_SECONDS, hold=0),
            return_exceptions=True,
        )
    )


def _a_settings_row(principal: Principal, **changes: object) -> Settings:
    fields: dict[str, object] = {
        "tenant_id": principal.tenant_id,
        "visible_hours": VISIBLE_HOURS_DEFAULT,
        "day_start": DAY_START_DEFAULT,
        "day_end": DAY_END_DEFAULT,
        "review_cadence": REVIEW_CADENCE_DEFAULT,
        "home_zone": HOME_ZONE_DEFAULT,
        "created_at": datetime.now(UTC),
    }
    return Settings(**{**fields, **changes})


async def _insert(sessions: async_sessionmaker[AsyncSession], row: DeclarativeBase) -> None:
    """Write one row in a transaction of its own, so a rejection is this call's failure."""
    async with sessions() as session, session.begin():
        session.add(row)
        await session.flush()


async def _execute(
    sessions: async_sessionmaker[AsyncSession],
    statement: TextClause,
    parameters: dict[str, object],
) -> None:
    async with sessions() as session, session.begin():
        await session.execute(statement, parameters)
