"""The drill seeder against a real Postgres: what it refuses, what it writes, and who judges it.

Three groups, and the middle one is the point of the whole module.

**The refusal.** The seeder writes invented rows, and on a deployed host the database it would reach
is the live one. Nothing about the connection distinguishes the two, so the rule is read from what
the database holds: every tenant is the drill's own, or nothing is written. Both directions are
driven, and so is the bound the rule cannot see.

**The evidence, judged by the fingerprint rather than by the seeder's own report.** The seeder says
what it did; ``ops.fingerprint`` and ``ops.verdict`` say whether that is a drill. The reading is
taken before and after, so what is asserted is that the five evidence tables GREW and that the
drill's own rotation cursor came into existence off its first variant: a count that was already
non-zero because another suite left rows behind cannot satisfy either claim.

``compare`` is called with one reading on both sides deliberately. Two of its eight claims are
functions of the BEFORE reading alone -- the evidence tables held rows, and a cursor had advanced --
and those two are what this module is about. The other six compare two readings of two databases and
a self-comparison satisfies them trivially, so nothing here should be read as a restore having been
proven.

**The console script's own composition**, which is the refusal, the bootstrap command and the write,
in that order. Its order is the assertion: a seeder that provisioned a tenant into a deployed
database and refused afterwards would already have written to it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

import pytest
from ops.config import EVIDENCE_TABLES
from ops.fingerprint import Fingerprint as DocumentReading
from ops.fingerprint import read as read_document
from ops.verdict import compare
from sqlalchemy import text

from syncr_api.accounts.passwords import hash_password
from syncr_api.accounts.repository import TenantRepository, UserRepository
from syncr_api.core.clock import utc_now
from syncr_api.core.db import create_database, create_db_engine, create_sessionmaker
from syncr_api.core.migrations import applied_revision, expected_head
from syncr_api.core.principal import Principal
from syncr_api.core.scopes import ALL_SCOPES
from syncr_api.core.settings import (
    DEFAULT_SOLVE_DEBOUNCE_MS,
    WORKER_SERVICE,
    build_service_settings,
)
from syncr_api.horizon.maintainer import PlanHorizonMaintainer
from syncr_api.learned.repository import WeightSetRepository
from syncr_api.offplan.declarations import OffPlanDeclaration
from syncr_api.offplan.injection import build_off_plan_service
from syncr_api.recovery.drill_declarations import VARIANTS, declare
from syncr_api.recovery.drill_evidence import write_the_evidence
from syncr_api.recovery.drill_history import NothingWasPlaced, record_what_happened
from syncr_api.recovery.drill_seed import (
    DRILL_EMAIL,
    EXIT_OK,
    EXIT_REFUSED,
    EXIT_UNREACHABLE,
)
from syncr_api.recovery.drill_seed import run as run_the_console_script
from syncr_api.recovery.drill_target import NotTheDrillsDatabase, require_the_drills_own_database
from syncr_api.recovery.drill_week import the_week_behind
from syncr_api.recovery.fingerprint import Fingerprint, read_fingerprint
from syncr_api.recovery.main import write_document
from syncr_api.solving.injection import debounce_window
from syncr_api.worker.main import WorkerContext
from syncr_domain.weeks import IsoWeek
from tests.conftest import UNREACHABLE_DATABASE_URL
from tests.live_tenants import delete_tenant

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.recovery.drill_week import DrillWeek

pytestmark = pytest.mark.integration

STRANGER_EMAIL: Final = "somebody-elses-deployment@syncr.test"
PASSWORD: Final = "not-a-password-anything-verifies"  # pragma: allowlist secret

# Late enough in the week that the whole of the drill's week is behind it, whatever the real date
# is, so the confirmations this module drives are confirmations of days that have been lived.
NOW: Final = datetime(2026, 8, 11, 9, 0, tzinfo=UTC)


@pytest.fixture
async def engine(live_database_url: str) -> AsyncIterator[AsyncEngine]:
    live = create_db_engine(live_database_url)
    yield live
    await live.dispose()


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_sessionmaker(engine)


@pytest.fixture
async def no_tenants(sessions: async_sessionmaker[AsyncSession]) -> None:
    """A database this module can state a rule over: every tenant in it is one of its own.

    The rule the seeder enforces is about the whole database, so a tenant another module left behind
    is indistinguishable from a deployment's. Skipped rather than deleted: emptying a database this
    suite shares is the one thing a test about a destructive seeder must not do.
    """
    async with sessions() as session:
        held = await TenantRepository(session).list_ids()
    if held:
        pytest.skip(
            f"this database already holds {len(held)} tenants, and the rule is about all of them"
        )


@pytest.fixture
async def drill_tenant(sessions: async_sessionmaker[AsyncSession]) -> AsyncIterator[UserRecord]:
    """The drill's own tenant, provisioned as the bootstrap command provisions it."""
    user = await _provision(sessions, DRILL_EMAIL)
    yield user
    await delete_tenant(sessions, user.tenant_id)


@pytest.fixture
async def a_stranger(sessions: async_sessionmaker[AsyncSession]) -> AsyncIterator[UserRecord]:
    """A tenant the drill did not create, which is what a deployment's database holds."""
    user = await _provision(sessions, STRANGER_EMAIL)
    yield user
    await delete_tenant(sessions, user.tenant_id)


@pytest.fixture
def context(live_database_url: str) -> WorkerContext:
    """A worker context of its own, because the console script disposes the engine it is given."""
    return WorkerContext(
        settings=build_service_settings(service=WORKER_SERVICE),
        database=create_database(live_database_url),
    )


async def _provision(sessions: async_sessionmaker[AsyncSession], email: str) -> UserRecord:
    """A tenant, its one user, and the weight set provisioning seeds beside them."""
    async with sessions() as session, session.begin():
        user = await UserRepository(session).create_tenant_with_user(
            email=email, password_hash=hash_password(PASSWORD), created_at=utc_now()
        )
        await WeightSetRepository(session, user.tenant_id).seed_hand_tuned(at=utc_now())
    return user


def _found_it(email: str, password: str) -> int:
    """The bootstrap command's answer for an account that already exists."""
    return 0


async def _declare_the_week_off_plan(
    sessions: async_sessionmaker[AsyncSession], principal: Principal, week: DrillWeek
) -> None:
    """Declare the drill's whole week off, so the solve has nowhere to place an occurrence.

    The product's own way of saying nothing may be placed in a span: every candidate is refused and
    an empty slot states `off_plan` as its reason. Declared through the service its route resolves,
    which accepts a past span because a period is a fact about time rather than a plan.
    """
    async with sessions() as session, session.begin():
        await build_off_plan_service(
            session,
            principal.tenant_id,
            debounce=debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS),
        ).declare(
            principal,
            OffPlanDeclaration(
                start=week.planned_at,
                end=week.planned_at + timedelta(days=7),
                keep_frame=False,
                label=None,
            ),
        )


async def _a_fingerprint(
    sessions: async_sessionmaker[AsyncSession], engine: AsyncEngine
) -> Fingerprint:
    """One reading of the whole database, taken the way the backup path takes it."""
    async with sessions() as session:
        return await read_fingerprint(
            session,
            now=utc_now(),
            expected_head=expected_head(),
            applied_revision=await applied_revision(engine),
        )


def _as_the_ops_package_reads_it(reading: Fingerprint, path: Path) -> DocumentReading:
    """The document the api image writes, parsed by the package on the other side of the bucket."""
    return read_document(write_document(path, reading.as_document()))


class TestTheTargetRefusal:
    """Which database the evidence may be written to, decided from what the database holds."""

    async def test_it_admits_a_database_whose_only_tenant_is_the_drills(
        self, sessions: async_sessionmaker[AsyncSession], no_tenants: None, drill_tenant: UserRecord
    ) -> None:
        async with sessions() as session:
            await require_the_drills_own_database(session, drill_email=DRILL_EMAIL)

    async def test_it_admits_a_database_holding_no_tenant_at_all(
        self, sessions: async_sessionmaker[AsyncSession], no_tenants: None
    ) -> None:
        """The bound the rule cannot see, asserted so it is a decision rather than an accident.

        A deployment between its migration one-shot and its bootstrap command is inside it. There is
        nothing there to overwrite, and the cost of the miss is a drill tenant beside the operator's
        own rather than invented rows inside real plan history.
        """
        async with sessions() as session:
            await require_the_drills_own_database(session, drill_email=DRILL_EMAIL)

    async def test_it_refuses_a_database_holding_a_tenant_the_drill_did_not_create(
        self, sessions: async_sessionmaker[AsyncSession], no_tenants: None, a_stranger: UserRecord
    ) -> None:
        with pytest.raises(NotTheDrillsDatabase) as refused:
            async with sessions() as session:
                await require_the_drills_own_database(session, drill_email=DRILL_EMAIL)
        assert str(a_stranger.tenant_id) in str(refused.value)
        assert "Nothing was written" in str(refused.value)

    async def test_it_refuses_a_tenant_that_carries_no_user(
        self, sessions: async_sessionmaker[AsyncSession], no_tenants: None, drill_tenant: UserRecord
    ) -> None:
        """A tenant with no user is foreign, because provisioning creates the pair in one write."""
        async with sessions() as session, session.begin():
            stray = (
                await session.execute(
                    text(
                        "INSERT INTO tenants (id, created_at) "
                        "VALUES (gen_random_uuid(), now()) RETURNING id"
                    )
                )
            ).scalar_one()
        try:
            with pytest.raises(NotTheDrillsDatabase) as refused:
                async with sessions() as session:
                    await require_the_drills_own_database(session, drill_email=DRILL_EMAIL)
            assert str(stray) in str(refused.value)
        finally:
            # By the id this test inserted, never "everything but the fixture's": the module's own
            # rule is that emptying a shared database is the one thing it must not do.
            await delete_tenant(sessions, stray)


class TestTheEvidenceTheFingerprintReads:
    """What the seeder produced, judged by the reading a restore is compared against."""

    async def test_every_evidence_table_grew_and_a_cursor_came_off_its_first_variant(
        self,
        sessions: async_sessionmaker[AsyncSession],
        engine: AsyncEngine,
        context: WorkerContext,
        drill_tenant: UserRecord,
        tmp_path: Path,
    ) -> None:
        before = await _a_fingerprint(sessions, engine)
        principal = Principal(
            tenant_id=drill_tenant.tenant_id, user_id=drill_tenant.id, scopes=ALL_SCOPES
        )

        written = await write_the_evidence(context, principal, now=NOW)

        after = await _a_fingerprint(sessions, engine)
        grew = {
            table: (before.row_counts.get(table, 0), after.row_counts.get(table, 0))
            for table in EVIDENCE_TABLES
        }
        assert all(pair[1] > pair[0] for pair in grew.values()), grew

        key = f"{drill_tenant.tenant_id}/"
        assert not [one for one in before.cursors if one.key.startswith(key)]
        cursors = [one for one in after.cursors if one.key.startswith(key)]
        assert len(cursors) == 1, cursors
        # Exactly one, and the exact figures rather than "not zero": the seeder records an outcome
        # for every occurrence the week holds, so a presumption it did not state cannot move this.
        assert cursors[0].confirmed_completions == 1, cursors[0]
        assert cursors[0].index == 1, cursors[0]
        assert cursors[0].variant == VARIANTS[1], cursors[0]
        assert written.placed > 0 and written.recorded > 0 and written.confirmed > 0

        reading = _as_the_ops_package_reads_it(after, tmp_path / "fingerprint.json")
        # The two claims this reads are `_there_was_data_to_lose` and `_a_cursor_had_advanced`, both
        # functions of ONE reading, which is why one reading is passed on both sides. The other six
        # compare two databases and a self-comparison satisfies them for nothing: this asserts the
        # conjunction because it is stricter than naming two, and it says nothing about a restore.
        verdict = compare(reading, reading, elapsed_seconds=0.0)
        assert verdict.held, [str(finding) for finding in verdict.failures]

    async def test_it_refuses_to_record_an_outcome_against_nothing(
        self, sessions: async_sessionmaker[AsyncSession], drill_tenant: UserRecord
    ) -> None:
        """The recording answers for its own argument, whoever calls it.

        The composed run refuses earlier, which is what
        `test_the_whole_sequence_refuses_a_week_the_solve_left_empty` drives: this one keeps the
        function answerable for a caller that reaches it with nothing.
        """
        principal = Principal(
            tenant_id=drill_tenant.tenant_id, user_id=drill_tenant.id, scopes=ALL_SCOPES
        )
        with pytest.raises(NothingWasPlaced):
            async with sessions() as session:
                await record_what_happened(session, principal, the_week_behind(NOW), ())

    async def test_the_whole_sequence_refuses_a_week_the_solve_left_empty(
        self,
        sessions: async_sessionmaker[AsyncSession],
        engine: AsyncEngine,
        context: WorkerContext,
        drill_tenant: UserRecord,
    ) -> None:
        """The refusal through the composition, which is the only path a drill takes.

        The week is emptied the way a real one would be: the whole of it is declared off, so the
        solve places none of the habit's occurrences. Nothing about the seeder is substituted, and
        the declarations are its own, reached through its own convergence read.
        """
        principal = Principal(
            tenant_id=drill_tenant.tenant_id, user_id=drill_tenant.id, scopes=ALL_SCOPES
        )
        async with sessions() as session, session.begin():
            await declare(session, principal)
        await _declare_the_week_off_plan(sessions, principal, the_week_behind(NOW))
        before = await _a_fingerprint(sessions, engine)

        with pytest.raises(NothingWasPlaced):
            await write_the_evidence(context, principal, now=NOW)

        after = await _a_fingerprint(sessions, engine)
        # No outcome, no pin and no concession: the refusal is before every step that writes one.
        for table in ("public.block_outcomes", "public.pins", "public.week_adjustments"):
            assert after.row_counts[table] == before.row_counts[table] == 0, table

    async def test_the_console_script_reports_the_refusal_rather_than_a_traceback(
        self, sessions: async_sessionmaker[AsyncSession], no_tenants: None, context: WorkerContext
    ) -> None:
        """The exit code the module documents for a week the solve left empty.

        Through `run`, because what an operator gets is its answer: a status and a stated reason,
        rather than whatever an unhandled exception exits with.
        """
        user = await _provision(sessions, DRILL_EMAIL)
        principal = Principal(tenant_id=user.tenant_id, user_id=user.id, scopes=ALL_SCOPES)
        try:
            async with sessions() as session, session.begin():
                await declare(session, principal)
            await _declare_the_week_off_plan(sessions, principal, the_week_behind(utc_now()))
            assert await run_the_console_script(context, bootstrap=_found_it) == EXIT_REFUSED
        finally:
            await delete_tenant(sessions, user.tenant_id)

    async def test_a_second_run_writes_nothing_more(
        self,
        sessions: async_sessionmaker[AsyncSession],
        engine: AsyncEngine,
        context: WorkerContext,
        drill_tenant: UserRecord,
    ) -> None:
        """A drill is repeated, so a second seed leaves the same database rather than a bigger."""
        principal = Principal(
            tenant_id=drill_tenant.tenant_id, user_id=drill_tenant.id, scopes=ALL_SCOPES
        )
        first = await write_the_evidence(context, principal, now=NOW)
        after_one = await _a_fingerprint(sessions, engine)

        second = await write_the_evidence(context, principal, now=NOW)
        after_two = await _a_fingerprint(sessions, engine)

        # The database first and the report afterwards, so a member that moves both names the
        # database: a claim about what the run said is worth less than a claim about what it wrote.
        #
        # Every table rather than the five, and derived from the reading rather than listed: a
        # convergence read that went missing would grow whatever table it guards, and a claim over
        # the five could not see a second Area slot or a second habit.
        assert after_two.row_counts == after_one.row_counts
        # And the digests beside the counts, from the same reading. A row an upsert rewrote in place
        # moves no count, and the drill's own verdict compares a table's bytes rather than its size:
        # The seeder's convergence property is "running it twice is running it once".
        assert after_two.content_digests == after_one.content_digests
        assert first.materialized and first.solved and first.pinned and first.conceded
        assert not second.materialized and not second.solved
        assert not second.pinned and not second.conceded

    async def test_a_second_run_writes_nothing_with_the_current_week_tracked_too(
        self,
        sessions: async_sessionmaker[AsyncSession],
        engine: AsyncEngine,
        context: WorkerContext,
        drill_tenant: UserRecord,
    ) -> None:
        """The state a claim over every table is still only as wide as the database it is read on.

        Recording an outcome and confirming a day both end by bumping every TRACKED week from the
        one holding the clock onwards, and the drill's week is behind the clock, so those bumps move
        nothing while nothing at or after the clock is tracked. A database that tracks the current
        week is where they would, and it is reachable the moment a stack with a worker in it runs
        this seeder. So the week holding the real clock is materialized between the two runs, which
        is what tracks it, and the claim is made after that rather than before.
        """
        principal = Principal(
            tenant_id=drill_tenant.tenant_id, user_id=drill_tenant.id, scopes=ALL_SCOPES
        )
        await write_the_evidence(context, principal, now=NOW)

        async with sessions() as session, session.begin():
            planned = await PlanHorizonMaintainer(
                session,
                principal.tenant_id,
                clock=utc_now,
                debounce=debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS),
            ).plan(IsoWeek.containing(utc_now().date()), now=utc_now())
        assert planned.planned == 1
        before = await _a_fingerprint(sessions, engine)

        second = await write_the_evidence(context, principal, now=NOW)

        after = await _a_fingerprint(sessions, engine)
        assert after.row_counts == before.row_counts
        assert after.content_digests == before.content_digests
        assert second.recorded == 0 and second.confirmed == 0


class TestTheConsoleScriptsComposition:
    """The refusal, the bootstrap command, and the write, in that order."""

    async def test_it_refuses_before_it_provisions_anything(
        self,
        sessions: async_sessionmaker[AsyncSession],
        no_tenants: None,
        a_stranger: UserRecord,
        context: WorkerContext,
    ) -> None:
        """The order is the assertion: a tenant provisioned first is a write to a live database."""
        asked: list[str] = []

        def never(email: str, password: str) -> int:
            asked.append(email)
            return 0

        assert await run_the_console_script(context, bootstrap=never) == EXIT_REFUSED
        assert asked == []

    async def test_it_stops_when_the_bootstrap_command_fails(
        self, no_tenants: None, drill_tenant: UserRecord, context: WorkerContext
    ) -> None:
        def refuses(email: str, password: str) -> int:
            return 1

        assert await run_the_console_script(context, bootstrap=refuses) == EXIT_REFUSED

    async def test_it_seeds_through_the_bootstrap_command_it_is_given(
        self,
        sessions: async_sessionmaker[AsyncSession],
        engine: AsyncEngine,
        no_tenants: None,
        drill_tenant: UserRecord,
        context: WorkerContext,
    ) -> None:
        """The whole composition, with the one step that needs a second process substituted."""
        credentials: list[tuple[str, str]] = []

        def found_it(email: str, password: str) -> int:
            credentials.append((email, password))
            return 0

        assert await run_the_console_script(context, bootstrap=found_it) == EXIT_OK
        assert [email for email, _ in credentials] == [DRILL_EMAIL]
        after = await _a_fingerprint(sessions, engine)
        assert all(after.row_counts[table] > 0 for table in EVIDENCE_TABLES)

    async def test_an_unreachable_database_is_not_a_refused_one(self) -> None:
        """Two non-zero codes, because the two states are opposite instructions to a caller.

        A refused target must never be retried and an absent one is worth waiting for, so a recipe
        that reads the status can tell them apart. The URL names a closed port, so the failure is
        the driver's own and no database is addressed.
        """
        unreachable = WorkerContext(
            settings=build_service_settings(service=WORKER_SERVICE),
            database=create_database(UNREACHABLE_DATABASE_URL),
        )
        assert await run_the_console_script(unreachable, bootstrap=_found_it) == EXIT_UNREACHABLE
