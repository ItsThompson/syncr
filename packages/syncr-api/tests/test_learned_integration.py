"""The three learning routes against a real Postgres, and the activation's own two rules.

Four groups.

**The read.** What the Learned screen renders: a row per parameter with its samples, its threshold,
its state, and the sentence that explains it. Plus the two statements the screen makes in prose,
which the api serves rather than leaving to the client.

**The version list.** Every version with its origin and its active flag, newest first.

**The activation.** The flip leaves exactly one active version per tenant, enforced by the partial
index rather than by the order of two statements. Reverting is the same route with an earlier
version.

**The re-solve.** FUTURE weeks only, because a past week's approved revision is immutable. A week
with no version row is not re-solved: it has no plan and no running solve to invalidate.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select, text

from syncr_api.core.db import create_db_engine, create_sessionmaker
from syncr_api.learned.config import FITTED, HAND_TUNED
from syncr_api.learned.maturity import maturity_rows
from syncr_api.learned.models import WeightSet
from syncr_api.learned.repository import WeightSetRepository
from syncr_api.plans.injection import DEFAULT_DEBOUNCE

# One condition, one class: the learned service raises plan storage's, so the test catches the same
# class the solve path does.
from syncr_api.plans.production import NoWeightSetInForce
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.config import SOLVE
from syncr_domain.weeks import IsoWeek
from tests.live_tenants import delete_tenant, seed_owner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.principal import Principal
    from syncr_api.learned.service import LearnedService

NOW = datetime(2026, 2, 16, 9, 0, tzinfo=UTC)
THIS_WEEK = IsoWeek.containing(NOW.date())
NEXT_WEEK = THIS_WEEK.following()
LAST_WEEK = THIS_WEEK.preceding()

A_MATURITY_ROW = {
    "parameter": "duration_multiplier[11111111-1111-4111-8111-111111111111]",
    "samples": 14,
    "threshold": 12,
    "state": "ready",
    "value": 1.37,
    "shrinkage_weight": 0.42,
    "plain_language": "You estimate 60m for Fitness; your actual median is 82m.",
}
A_COLLECTING_ROW = {
    "parameter": "churn_tolerance",
    "samples": 3,
    "threshold": 20,
    "state": "collecting",
    "value": None,
    "shrinkage_weight": 1.0,
    "plain_language": "Rearrangement: 3 of 20 proposals. Still collecting, which is normal.",
}


@pytest.fixture
async def engine(live_database_url: str) -> AsyncIterator[AsyncEngine]:
    made = create_db_engine(live_database_url)
    try:
        yield made
    finally:
        await made.dispose()


@pytest.fixture
async def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_sessionmaker(engine)


@pytest.fixture
async def owner(sessions: async_sessionmaker[AsyncSession]) -> AsyncIterator[UserRecord]:
    seeded = await seed_owner(sessions)
    async with sessions() as session, session.begin():
        await WeightSetRepository(session, seeded.tenant_id).seed_hand_tuned(at=NOW)
    try:
        yield seeded
    finally:
        await delete_tenant(sessions, seeded.tenant_id)


def a_principal(owner: UserRecord) -> Principal:
    from syncr_api.core.principal import Principal
    from syncr_api.core.scopes import Scope

    return Principal(
        tenant_id=owner.tenant_id,
        user_id=owner.id,
        scopes=frozenset({Scope.PLAN_READ, Scope.PLAN_WRITE}),
    )


def build(session: AsyncSession, owner: UserRecord) -> LearnedService:
    """The service, wired the way the injection wires it, over one session."""
    from syncr_api.areas.repository import AreaRepository
    from syncr_api.learned.activation import FutureWeeksResolved, WeightSetActivation
    from syncr_api.learned.service import LearnedService
    from syncr_api.solving.injection import build_solve_coordinator
    from syncr_api.user_settings.repository import SettingsRepository

    tenant_id = owner.tenant_id
    return LearnedService(
        weights=WeightSetRepository(session, tenant_id),
        areas=AreaRepository(session, tenant_id),
        activation=WeightSetActivation(session, tenant_id),
        resolver=FutureWeeksResolved(
            versions=WeekInputVersionRepository(session, tenant_id),
            settings=SettingsRepository(session, tenant_id),
            coordinator=build_solve_coordinator(
                session, tenant_id, clock=lambda: NOW, debounce=DEFAULT_DEBOUNCE
            ),
        ),
        clock=lambda: NOW,
    )


async def append_fitted(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    *,
    version: int,
    maturity: list[dict[str, object]] | None = None,
    multiplier: float = 1.37,
) -> None:
    """A fitted version as the nightly job appends one: not active, and stating when it was fit."""
    async with sessions() as session, session.begin():
        session.add(
            WeightSet(
                tenant_id=owner.tenant_id,
                version=version,
                active=False,
                origin=FITTED,
                deadline_risk=9.0,
                budget_deviation=3.0,
                time_of_day_misfit=2.0,
                fragmentation=1.5,
                churn=4.0,
                context_switch=1.0,
                staleness=1.5,
                duration_multiplier={"11111111-1111-4111-8111-111111111111": multiplier},
                time_of_day_fitness={},
                skip_probability={},
                context_switch_cost=2.5,
                churn_tolerance=5.0,
                fitted_at=NOW,
                maturity=maturity if maturity is not None else [A_MATURITY_ROW, A_COLLECTING_ROW],
                created_at=NOW,
            )
        )


async def track(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, *weeks: IsoWeek
) -> None:
    """Give each week a version row, which is what makes it a week the tenant has planned."""
    async with sessions() as session, session.begin():
        versions = WeekInputVersionRepository(session, owner.tenant_id)
        for week in weeks:
            await versions.bump(week, at=NOW)


async def active_version(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> int | None:
    async with sessions() as session:
        found = await WeightSetRepository(session, owner.tenant_id).active()
    return None if found is None else found.version


class TestTheLearnedRead:
    async def test_a_new_tenant_reads_version_one_hand_tuned_with_no_rows(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        # The state every account starts in: the hand-tuned weights shipped through the same
        # versioned mechanism a fitted set uses, and nothing learned yet.
        async with sessions() as session:
            reading = await build(session, owner).read(a_principal(owner))

        assert reading.version == 1
        assert reading.origin == HAND_TUNED
        assert reading.fitted_at is None
        assert reading.rows == ()
        assert reading.ready == 0

    async def test_the_read_serves_the_two_statements_the_screen_makes(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        # Both are claims about how this system works. A caveat that lives only in a client's
        # template is one a client can render without.
        async with sessions() as session:
            reading = await build(session, owner).read(a_principal(owner))

        assert "estimates rather than measurements" in reading.thresholds_are_estimates
        assert "skipped everything and said so" in reading.unlocks_count_confirmed_volume

    async def test_a_fitted_version_reads_its_rows_with_the_gate_each_row_reports(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        await append_fitted(sessions, owner, version=2)
        async with sessions() as session, session.begin():
            await build(session, owner).activate(a_principal(owner), 2)

        async with sessions() as session:
            reading = await build(session, owner).read(a_principal(owner))

        assert reading.version == 2
        assert reading.origin == FITTED
        assert reading.ready == 1
        assert reading.collecting == 1
        ready = next(one for one in reading.rows if one.is_ready)
        assert ready.value == 1.37
        assert ready.samples == 14
        assert "82m" in ready.plain_language
        collecting = next(one for one in reading.rows if not one.is_ready)
        assert collecting.value is None
        assert "normal" in collecting.plain_language

    async def test_a_malformed_row_is_dropped_and_the_rest_are_served(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        # The Learned screen is a trust surface. A 500 because one of three rows is malformed tells
        # the user nothing and hides the two that are fine.
        await append_fitted(
            sessions,
            owner,
            version=2,
            maturity=[A_MATURITY_ROW, {"parameter": "broken"}, A_COLLECTING_ROW],
        )
        async with sessions() as session, session.begin():
            await build(session, owner).activate(a_principal(owner), 2)

        async with sessions() as session:
            reading = await build(session, owner).read(a_principal(owner))

        assert len(reading.rows) == 2

    async def test_a_row_claiming_ready_with_no_figure_is_refused(self) -> None:
        # The gate as the user reads it: a ready row with no value would say the solver is applying
        # something it is not. Driven at the reader, because that is where a stored row becomes a
        # row.
        lying = {**A_MATURITY_ROW, "value": None}

        assert maturity_rows([lying]) == ()

    async def test_a_tenant_with_no_active_version_is_a_stated_refusal(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        async with sessions() as session, session.begin():
            await session.execute(
                text("UPDATE weight_sets SET active = false WHERE tenant_id = :tenant"),
                {"tenant": owner.tenant_id},
            )

        async with sessions() as session:
            with pytest.raises(NoWeightSetInForce, match="nothing learned to report"):
                await build(session, owner).read(a_principal(owner))


class TestTheVersionList:
    async def test_every_version_is_listed_newest_first_with_its_origin_and_flag(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        await append_fitted(sessions, owner, version=2)
        await append_fitted(sessions, owner, version=3)

        async with sessions() as session:
            versions = await build(session, owner).versions(a_principal(owner))

        assert [one.version for one in versions] == [3, 2, 1]
        assert [one.origin for one in versions] == [FITTED, FITTED, HAND_TUNED]
        assert [one.active for one in versions] == [False, False, True]

    async def test_each_version_reports_how_much_of_it_is_ready(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        await append_fitted(sessions, owner, version=2)

        async with sessions() as session:
            versions = await build(session, owner).versions(a_principal(owner))

        fitted = next(one for one in versions if one.version == 2)
        assert fitted.ready == 1
        assert fitted.collecting == 1


class TestTheActivation:
    async def test_activating_a_version_leaves_exactly_one_active(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        await append_fitted(sessions, owner, version=2)

        async with sessions() as session, session.begin():
            await build(session, owner).activate(a_principal(owner), 2)

        async with sessions() as session:
            flags = (
                await session.scalars(
                    select(WeightSet.version).where(
                        WeightSet.tenant_id == owner.tenant_id, WeightSet.active.is_(True)
                    )
                )
            ).all()

        assert list(flags) == [2]

    async def test_reverting_is_the_same_route_with_an_earlier_version(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        # No reprocessing of history: reverting is one flip, and the row it flips back to is the row
        # it always was.
        await append_fitted(sessions, owner, version=2)
        async with sessions() as session, session.begin():
            await build(session, owner).activate(a_principal(owner), 2)
        async with sessions() as session, session.begin():
            await build(session, owner).activate(a_principal(owner), 1)

        assert await active_version(sessions, owner) == 1

    async def test_activating_a_version_this_account_does_not_hold_is_a_404(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        from syncr_api.core.errors import NotFound

        async with sessions() as session, session.begin():
            with pytest.raises(NotFound):
                await build(session, owner).activate(a_principal(owner), 99)

        # And it left the flag where it was, rather than clearing it and finding nothing to set.
        assert await active_version(sessions, owner) == 1

    async def test_activating_the_version_already_in_force_still_re_solves(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        # Not a conflict. The flip is a no-op and the re-solve is what the caller asked for:
        # refusing would send them to the re-solve control to do the same thing.
        await track(sessions, owner, THIS_WEEK)

        async with sessions() as session, session.begin():
            activated = await build(session, owner).activate(a_principal(owner), 1)

        assert activated.version == 1
        assert activated.resolved_weeks == (str(THIS_WEEK),)


class TestTheReSolveIsFutureWeeksOnly:
    async def test_a_past_week_is_not_re_solved(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        # A past week's approved revision is immutable and keeps the inputs it was computed with, so
        # re-deriving one would change history rather than the plan.
        await track(sessions, owner, LAST_WEEK, THIS_WEEK, NEXT_WEEK)
        await append_fitted(sessions, owner, version=2)

        async with sessions() as session, session.begin():
            activated = await build(session, owner).activate(a_principal(owner), 2)

        assert set(activated.resolved_weeks) == {str(THIS_WEEK), str(NEXT_WEEK)}
        assert str(LAST_WEEK) not in activated.resolved_weeks

    async def test_a_past_week_s_input_version_is_left_where_it_was(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        await track(sessions, owner, LAST_WEEK, THIS_WEEK)
        async with sessions() as session:
            before = await WeekInputVersionRepository(session, owner.tenant_id).current(LAST_WEEK)
        await append_fitted(sessions, owner, version=2)

        async with sessions() as session, session.begin():
            await build(session, owner).activate(a_principal(owner), 2)

        async with sessions() as session:
            versions = WeekInputVersionRepository(session, owner.tenant_id)
            assert await versions.current(LAST_WEEK) == before
            assert await versions.current(THIS_WEEK) != before

    async def test_a_week_with_no_version_row_is_not_re_solved(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        # Such a week has no plan and no running solve to invalidate, and the horizon maintainer is
        # what brings a week into range: creating a row here would decide which weeks a tenant
        # plans.
        await append_fitted(sessions, owner, version=2)

        async with sessions() as session, session.begin():
            activated = await build(session, owner).activate(a_principal(owner), 2)

        assert activated.resolved_weeks == ()

    async def test_each_future_week_gets_a_solve_operation(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        # The trigger table says this row bumps AND solves. This is the runtime half of it.
        await track(sessions, owner, THIS_WEEK, NEXT_WEEK)
        await append_fitted(sessions, owner, version=2)

        async with sessions() as session, session.begin():
            await build(session, owner).activate(a_principal(owner), 2)

        async with sessions() as session:
            weeks = (
                await session.execute(
                    text(
                        "SELECT DISTINCT iso_week FROM operations "
                        "WHERE tenant_id = :tenant AND kind = :kind"
                    ),
                    {"tenant": owner.tenant_id, "kind": SOLVE},
                )
            ).all()

        assert {one.iso_week for one in weeks} == {str(THIS_WEEK), str(NEXT_WEEK)}

    async def test_a_week_a_year_out_is_re_solved_because_the_range_has_no_end(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        # Activating a version governs every week the user has not yet lived, so the range is open
        # ended: a bound would leave a planned week solving under the weights it no longer uses.
        far = IsoWeek.containing(NOW.date() + timedelta(days=300))
        await track(sessions, owner, THIS_WEEK, far)
        await append_fitted(sessions, owner, version=2)

        async with sessions() as session, session.begin():
            activated = await build(session, owner).activate(a_principal(owner), 2)

        assert str(far) in activated.resolved_weeks
