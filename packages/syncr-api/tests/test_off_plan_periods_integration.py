"""Off-plan periods against a real Postgres: the overlap predicate, the CHECK, and the bump.

Four things cannot be shown without a real server, and each is a place a defect would hide.

**The half-open overlap predicate is stated twice, in two languages.** ``for_span`` asks Postgres
``row.start < span.end AND span.start < row.end``, and ``Interval.overlaps`` asks the same
question in Python. The corpus below crosses them: every boundary pair is answered by both, and
the two answers have to agree. A drift between them would show up as a period silently missing
from one week's assembly.

**A reversed row cannot be stored.** The CHECK is what a write bypassing the service hits, and
the reason it exists is that every reader builds an ``Interval`` from the pair.

**A period spanning two ISO weeks is one row.** Both weeks read it whole, and nothing anywhere
writes a clipped copy.

**The version bump reaches real rows.** ``TrackedWeekInputVersions`` enumerates the weeks that
have a row and increments each, so a Friday-to-Monday declaration has to move two counters and
leave a third alone.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from syncr_api.calendars.repository import CalendarSourceRepository
from syncr_api.core.db import create_db_engine, create_sessionmaker
from syncr_api.core.principal import Principal
from syncr_api.core.scopes import ALL_SCOPES
from syncr_api.horizon.projection import CurrentProjectionHorizon
from syncr_api.offplan.declarations import OffPlanChange, OffPlanDeclaration
from syncr_api.offplan.models import OffPlanPeriodRow
from syncr_api.offplan.repository import OffPlanPeriodRepository
from syncr_api.offplan.service import OffPlanService
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.injection import build_solve_requests, debounce_window
from syncr_api.user_settings.repository import SettingsRepository, TravelOverrideRepository
from syncr_api.user_settings.solve_inputs import TrackedWeekInputVersions
from syncr_domain.fixtures.off_plan_week import OFF_PLAN_WEEK
from syncr_domain.intervals import Interval
from syncr_domain.snap import SNAP
from syncr_domain.weeks import IsoWeek, week_span
from tests.live_tenants import delete_tenant, seed_owner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_domain.identifiers import TenantId

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)

WEEK = OFF_PLAN_WEEK.iso_week
FOLLOWING = OFF_PLAN_WEEK.following_week
# A week the Friday-to-Monday span does not reach, so a bump that touched it would be visible.
UNTOUCHED = IsoWeek.parse("2026-W41")

# The reference span every probe below is compared against, and the probes: one for each way two
# half-open spans can meet. Each is stated relative to the reference rather than as a literal, so
# a reader can see which boundary it is about.
REFERENCE = Interval(
    datetime(2026, 10, 23, 13, 0, tzinfo=UTC), datetime(2026, 10, 26, 9, 0, tzinfo=UTC)
)

_ONE_DAY = timedelta(days=1)

BOUNDARY_PROBES: dict[str, Interval] = {
    "ending_where_it_starts": Interval(REFERENCE.start - _ONE_DAY, REFERENCE.start),
    "ending_one_snap_after_it_starts": Interval(REFERENCE.start - _ONE_DAY, REFERENCE.start + SNAP),
    "starting_where_it_ends": Interval(REFERENCE.end, REFERENCE.end + _ONE_DAY),
    "starting_one_snap_before_it_ends": Interval(REFERENCE.end - SNAP, REFERENCE.end + _ONE_DAY),
    "identical": REFERENCE,
    "nested": Interval(REFERENCE.start + SNAP, REFERENCE.end - SNAP),
    "containing": Interval(REFERENCE.start - _ONE_DAY, REFERENCE.end + _ONE_DAY),
    "sharing_a_start": Interval(REFERENCE.start, REFERENCE.start + SNAP),
    "sharing_an_end": Interval(REFERENCE.end - SNAP, REFERENCE.end),
    "well_before": Interval(REFERENCE.start - 3 * _ONE_DAY, REFERENCE.start - 2 * _ONE_DAY),
    "well_after": Interval(REFERENCE.end + 2 * _ONE_DAY, REFERENCE.end + 3 * _ONE_DAY),
}


@pytest.fixture
async def engine(live_database_url: str) -> AsyncIterator[AsyncEngine]:
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
async def other_owner(sessions: async_sessionmaker[AsyncSession]) -> AsyncIterator[UserRecord]:
    account = await seed_owner(sessions)
    yield account
    await delete_tenant(sessions, account.tenant_id)


def principal_for(owner: UserRecord) -> Principal:
    return Principal(tenant_id=owner.tenant_id, user_id=owner.id, scopes=ALL_SCOPES)


async def store(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, *intervals: Interval
) -> None:
    async with sessions() as session, session.begin():
        periods = OffPlanPeriodRepository(session, tenant_id)
        for interval in intervals:
            await periods.create(interval=interval, keep_frame=False, label=None, created_at=NOW)


async def read_for_span(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, span: Interval
) -> tuple[Interval, ...]:
    async with sessions() as session:
        found = await OffPlanPeriodRepository(session, tenant_id).for_span(span)
        return tuple(record.interval for record in found)


def build_service(session: AsyncSession, tenant_id: TenantId) -> OffPlanService:
    """The service wired as the request path wires it, against a real session."""
    settings = SettingsRepository(session, tenant_id)
    return OffPlanService(
        periods=OffPlanPeriodRepository(session, tenant_id),
        settings=settings,
        overrides=TravelOverrideRepository(session, tenant_id),
        versions=TrackedWeekInputVersions(
            WeekInputVersionRepository(session, tenant_id), clock=lambda: NOW
        ),
        solve_requests=build_solve_requests(
            session,
            tenant_id,
            clock=lambda: NOW,
            debounce=debounce_window(1),
        ),
        horizon=CurrentProjectionHorizon(CalendarSourceRepository(session, tenant_id), settings),
        clock=lambda: NOW,
    )


# --------------------------------------------------------------------------------
# The overlap predicate, in SQL and in Python
# --------------------------------------------------------------------------------


@pytest.mark.parametrize("probe", BOUNDARY_PROBES.values(), ids=list(BOUNDARY_PROBES))
async def test_postgres_and_the_domain_agree_on_whether_two_spans_overlap(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, probe: Interval
) -> None:
    await store(sessions, owner.tenant_id, REFERENCE)

    found = await read_for_span(sessions, owner.tenant_id, probe)

    assert bool(found) == REFERENCE.overlaps(probe)
    assert found == ((REFERENCE,) if REFERENCE.overlaps(probe) else ())


async def test_the_corpus_covers_both_answers() -> None:
    # The control. Every case above compares two readings, so a corpus that was entirely
    # overlapping, or entirely not, would pass while proving one direction.
    answers = {REFERENCE.overlaps(probe) for probe in BOUNDARY_PROBES.values()}

    assert answers == {True, False}


async def test_a_period_reaching_past_a_week_is_returned_whole_to_both_weeks(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    await store(sessions, owner.tenant_id, OFF_PLAN_WEEK.off_plan)

    in_the_week = await read_for_span(
        sessions, owner.tenant_id, week_span(WEEK, OFF_PLAN_WEEK.profile)
    )
    in_the_following = await read_for_span(
        sessions, owner.tenant_id, week_span(FOLLOWING, OFF_PLAN_WEEK.profile)
    )

    assert in_the_week == (OFF_PLAN_WEEK.off_plan,)
    assert in_the_following == (OFF_PLAN_WEEK.off_plan,)
    # One row, whatever the number of weeks that read it.
    async with sessions() as session:
        stored = await OffPlanPeriodRepository(session, owner.tenant_id).list_all()
    assert len(stored) == 1
    assert stored[0].interval.total_minutes() == OFF_PLAN_WEEK.off_plan_minutes


async def test_the_periods_are_listed_earliest_first(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    later = Interval(REFERENCE.end + _ONE_DAY, REFERENCE.end + 2 * _ONE_DAY)
    await store(sessions, owner.tenant_id, later, REFERENCE)

    async with sessions() as session:
        found = await OffPlanPeriodRepository(session, owner.tenant_id).list_all()

    assert [record.interval for record in found] == [REFERENCE, later]


async def test_another_tenants_periods_are_invisible(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, other_owner: UserRecord
) -> None:
    await store(sessions, other_owner.tenant_id, REFERENCE)

    assert await read_for_span(sessions, owner.tenant_id, REFERENCE) == ()
    assert await read_for_span(sessions, other_owner.tenant_id, REFERENCE) == (REFERENCE,)


# --------------------------------------------------------------------------------
# What the database refuses
# --------------------------------------------------------------------------------


async def test_a_reversed_row_is_refused_by_the_database(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # Written past the service, which is the only way to attempt it: an interval refuses the pair
    # before a repository sees it, so this is the backstop rather than the rule.
    with pytest.raises(IntegrityError, match="ck_off_plan_periods_start_before_end"):
        async with sessions() as session, session.begin():
            session.add(
                OffPlanPeriodRow(
                    tenant_id=owner.tenant_id,
                    start=REFERENCE.end,
                    end=REFERENCE.start,
                    keep_frame=False,
                    label=None,
                    created_at=NOW,
                )
            )


async def test_a_zero_length_row_is_refused_by_the_database(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    with pytest.raises(IntegrityError, match="ck_off_plan_periods_start_before_end"):
        async with sessions() as session, session.begin():
            session.add(
                OffPlanPeriodRow(
                    tenant_id=owner.tenant_id,
                    start=REFERENCE.start,
                    end=REFERENCE.start,
                    keep_frame=False,
                    label=None,
                    created_at=NOW,
                )
            )


async def test_a_row_inserted_without_keep_frame_keeps_no_frame(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # The column default, which the application also sets. A row written by hand carries the
    # reading the product documents rather than a NULL or a surprise.
    async with sessions() as session, session.begin():
        await session.execute(
            text(
                'INSERT INTO off_plan_periods (id, tenant_id, start, "end", created_at) '
                "VALUES (gen_random_uuid(), :tenant_id, :start, :end, :created_at)"
            ),
            {
                "tenant_id": owner.tenant_id,
                "start": REFERENCE.start,
                "end": REFERENCE.end,
                "created_at": NOW,
            },
        )

    async with sessions() as session:
        found = await OffPlanPeriodRepository(session, owner.tenant_id).list_all()

    assert [record.keep_frame for record in found] == [False]
    assert [record.label for record in found] == [None]


# --------------------------------------------------------------------------------
# The version bump, over real version rows
# --------------------------------------------------------------------------------


async def version_of(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, week: IsoWeek
) -> int | None:
    async with sessions() as session:
        return await WeekInputVersionRepository(session, tenant_id).current(week)


async def track(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, *weeks: IsoWeek
) -> None:
    """Give each week a version row, as a first solve or a plan reference would."""
    async with sessions() as session, session.begin():
        versions = WeekInputVersionRepository(session, tenant_id)
        for week in weeks:
            await versions.bump(week, at=NOW)


async def test_declaring_a_span_bumps_every_tracked_week_it_touches(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    await track(sessions, owner.tenant_id, WEEK, FOLLOWING, UNTOUCHED)
    async with sessions() as session, session.begin():
        await build_service(session, owner.tenant_id).declare(
            principal_for(owner),
            OffPlanDeclaration(
                start=OFF_PLAN_WEEK.off_plan.start,
                end=OFF_PLAN_WEEK.off_plan.end,
                keep_frame=True,
                label="Italy",
            ),
        )

    assert await version_of(sessions, owner.tenant_id, WEEK) == 2
    assert await version_of(sessions, owner.tenant_id, FOLLOWING) == 2
    # A week the span does not reach keeps the version it had.
    assert await version_of(sessions, owner.tenant_id, UNTOUCHED) == 1


async def test_a_span_ending_at_a_weeks_first_instant_leaves_that_weeks_version_alone(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # The half-open boundary, over real version rows. This span's last instant is 23:59 on the
    # Sunday, so the week beginning at that midnight read no different a denominator and its
    # running solve is still valid. Reading the end's own week instead would bump it.
    await track(sessions, owner.tenant_id, WEEK, FOLLOWING)
    week_end = week_span(WEEK, OFF_PLAN_WEEK.profile).end
    async with sessions() as session, session.begin():
        await build_service(session, owner.tenant_id).declare(
            principal_for(owner),
            OffPlanDeclaration(
                start=OFF_PLAN_WEEK.off_plan.start, end=week_end, keep_frame=False, label=None
            ),
        )

    assert await version_of(sessions, owner.tenant_id, WEEK) == 2
    assert await version_of(sessions, owner.tenant_id, FOLLOWING) == 1


async def test_a_week_with_no_plan_is_not_given_a_version_row(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # Nothing is planned for either week, so there is no running solve to invalidate and no row
    # to create: creating one would claim the week had been referenced.
    async with sessions() as session, session.begin():
        await build_service(session, owner.tenant_id).declare(
            principal_for(owner),
            OffPlanDeclaration(
                start=OFF_PLAN_WEEK.off_plan.start,
                end=OFF_PLAN_WEEK.off_plan.end,
                keep_frame=False,
                label=None,
            ),
        )

    assert await version_of(sessions, owner.tenant_id, WEEK) is None
    assert await version_of(sessions, owner.tenant_id, FOLLOWING) is None


async def test_moving_a_span_bumps_the_weeks_it_left_and_the_weeks_it_reaches(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    await track(sessions, owner.tenant_id, WEEK, FOLLOWING, UNTOUCHED)
    await store(sessions, owner.tenant_id, OFF_PLAN_WEEK.off_plan)
    async with sessions() as session:
        stored = await OffPlanPeriodRepository(session, owner.tenant_id).list_all()
    moved_into = week_span(UNTOUCHED, OFF_PLAN_WEEK.profile)

    async with sessions() as session, session.begin():
        await build_service(session, owner.tenant_id).update(
            principal_for(owner),
            stored[0].id,
            OffPlanChange(
                start=moved_into.start,
                end=moved_into.start + timedelta(hours=8),
                keep_frame=False,
                label=None,
            ),
        )

    assert await version_of(sessions, owner.tenant_id, WEEK) == 2
    assert await version_of(sessions, owner.tenant_id, FOLLOWING) == 2
    assert await version_of(sessions, owner.tenant_id, UNTOUCHED) == 2


async def test_a_span_moved_onto_a_week_it_already_covered_leaves_that_week_two_ahead(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    # The observable effect of bumping per range rather than per week: the shared week is
    # incremented by both ranges. Harmless, because the guard compares a version for equality
    # rather than counting increments, and asserted here so the arithmetic is a measurement rather
    # than a claim in a docstring.
    following = week_span(FOLLOWING, OFF_PLAN_WEEK.profile)
    third = week_span(IsoWeek.parse("2026-W45"), OFF_PLAN_WEEK.profile)
    await track(sessions, owner.tenant_id, WEEK, FOLLOWING, IsoWeek.parse("2026-W45"))
    await store(sessions, owner.tenant_id, OFF_PLAN_WEEK.off_plan)
    async with sessions() as session:
        stored = await OffPlanPeriodRepository(session, owner.tenant_id).list_all()

    async with sessions() as session, session.begin():
        # From [W43, W44] to [W44, W45]: the two ranges share W44.
        await build_service(session, owner.tenant_id).update(
            principal_for(owner),
            stored[0].id,
            OffPlanChange(
                start=following.end - timedelta(hours=8),
                end=third.start + timedelta(hours=8),
                keep_frame=False,
                label=None,
            ),
        )

    assert await version_of(sessions, owner.tenant_id, WEEK) == 2
    assert await version_of(sessions, owner.tenant_id, FOLLOWING) == 3
    assert await version_of(sessions, owner.tenant_id, IsoWeek.parse("2026-W45")) == 2


async def test_removing_a_span_bumps_the_weeks_it_covered(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> None:
    await track(sessions, owner.tenant_id, WEEK, FOLLOWING)
    await store(sessions, owner.tenant_id, OFF_PLAN_WEEK.off_plan)
    async with sessions() as session:
        stored = await OffPlanPeriodRepository(session, owner.tenant_id).list_all()

    async with sessions() as session, session.begin():
        await build_service(session, owner.tenant_id).remove(principal_for(owner), stored[0].id)

    assert await version_of(sessions, owner.tenant_id, WEEK) == 2
    assert await version_of(sessions, owner.tenant_id, FOLLOWING) == 2
    async with sessions() as session:
        assert await OffPlanPeriodRepository(session, owner.tenant_id).list_all() == ()
