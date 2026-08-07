"""The Postgres adapter against a real database, seeded through the API's own writers.

What cannot be tested with literals is whether the restated spelling matches the schema. The pure
tier's agreement test crosses the names the api states as constants; this crosses the rest, and it
does it
it the only way that means anything: **the api writes the rows and the learning adapter reads them
back**. A stored document assembled by hand in a test would be a third spelling, and it would agree
with this package by construction while disagreeing with production.

Importing ``syncr_api`` here is a DEV dependency, declared in this member's manifest, and
``test_package_boundary.py`` asserts the image installs neither it nor the solver.

The never-writes guard is here rather than in the pure tier because it is stated over the storage
subpackage's own source AND over the database: the source half says no statement names those tables
as
a write, and the runtime half counts their rows across a whole run.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from syncr_api.accounts.passwords import hash_password
from syncr_api.accounts.repository import UserRepository
from syncr_api.areas.repository import AreaRepository
from syncr_api.learned.repository import WeightSetRepository
from syncr_api.offplan.repository import OffPlanPeriodRepository
from syncr_api.plans.config import APPLIED
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_documents import stored_document
from syncr_api.user_settings.repository import SettingsRepository
from syncr_domain.habits import BindingSource
from syncr_domain.identity import BindingKind, BindingRef, habit_occurrence_keys
from syncr_domain.intervals import Interval
from syncr_domain.plan import Block, PlanDocument
from syncr_domain.reasons import Bound, ReasonRecord
from syncr_domain.weeks import IsoWeek
from syncr_learning.artifact import FittedWeightSet
from syncr_learning.config import OBJECTIVE_TERMS
from syncr_learning.gates import ParameterMaturity
from syncr_learning.job import run
from syncr_learning.storage import spelling
from syncr_learning.storage.engine import create_database
from syncr_learning.storage.reader import PostgresCorpusReader
from syncr_learning.storage.writer import PostgresParameterWriter
from syncr_solver.weights import TimeBucket

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from syncr_api.learned.records import WeightSetRecord
    from syncr_domain.identifiers import AreaId, PlanRevisionId, TenantId

AT = datetime(2026, 2, 16, 3, 0, tzinfo=UTC)
WEEK = IsoWeek(year=2026, week=7)
MONDAY = datetime(2026, 2, 9, tzinfo=UTC)
ZONE = "Europe/London"

# The Area a stored map is keyed on in the artefact below. A real identifier, because the reader
# that projects a stored map into the solver's value refuses a key that is not one, which is what
# the round trip in this file exists to drive.
ARTIFACT_AREA = UUID("44444444-4444-4444-8444-444444444444")

HAND_TUNED_IN_FORCE = {
    "deadline_risk": 10.0,
    "budget_deviation": 3.0,
    "time_of_day_misfit": 2.0,
    "fragmentation": 1.5,
    "churn": 4.0,
    "context_switch": 1.0,
    "staleness": 1.5,
    "context_switch_cost": 1.0,
    "churn_tolerance": 3.0,
}


@pytest.fixture
async def sessions(live_database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    database = create_database(live_database_url)
    try:
        yield database.sessions
    finally:
        await database.engine.dispose()


@pytest.fixture
async def tenant(sessions: async_sessionmaker[AsyncSession]) -> AsyncIterator[TenantId]:
    """A real tenant with a settings row, one Area, and version 1 of its weights.

    Seeded through the api's own repositories, so every column and default is the production one.
    Removed afterwards, which cascades to every scoped row a test added.
    """
    async with sessions() as session, session.begin():
        owner = await UserRepository(session).create_tenant_with_user(
            email=f"learning-{uuid4().hex}@syncr.test",
            password_hash=hash_password("correct-horse-battery-staple"),  # pragma: allowlist secret
            created_at=AT,
        )
        await SettingsRepository(session, owner.tenant_id).lock(created_at=AT)
        await AreaRepository(session, owner.tenant_id).create(
            parent_id=None,
            name="Fitness",
            pigment_index=0,
            budget_percent=Decimal("10.00"),
            floor_hours=None,
            created_at=AT,
        )
        await WeightSetRepository(session, owner.tenant_id).seed_hand_tuned(at=AT)
    try:
        yield owner.tenant_id
    finally:
        async with sessions() as session, session.begin():
            await session.execute(
                text("DELETE FROM tenants WHERE id = :id"), {"id": owner.tenant_id}
            )


async def the_area(sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId) -> AreaId:
    async with sessions() as session:
        areas = await AreaRepository(session, tenant_id).list_all()
    return areas[0].id


def a_document(area_id: AreaId, *, count: int = 3, hour: int = 9) -> PlanDocument:
    """One week's plan, built through the DOMAIN constructors the api writes through.

    Not assembled as a dictionary: a hand-written document would be a third spelling of the stored
    shape and would agree with the reader by construction.
    """
    keys = habit_occurrence_keys(count)
    return PlanDocument(
        iso_week=WEEK,
        zone_by_date=dict.fromkeys(WEEK.dates(), ZONE),
        discretionary_minutes=5880,
        unallocated_minutes=1000,
        oversubscription_minutes=0,
        blocks=tuple(
            Block(
                iso_week=WEEK,
                interval=Interval(
                    MONDAY + timedelta(hours=hour, minutes=index * 90),
                    MONDAY + timedelta(hours=hour + 1, minutes=index * 90),
                ),
                binding=BindingRef(
                    kind=BindingKind.HABIT,
                    entity_id=uuid4(),
                    occurrence_key=keys[index],
                    split_index=None,
                ),
                title=f"Session {index}",
                reason=ReasonRecord(
                    clauses=(Bound(source=BindingSource.FIXED, selected=f"Session {index}"),)
                ),
                area_id=area_id,
            )
            for index in range(count)
        ),
    )


async def seed_revision(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, document: PlanDocument
) -> None:
    async with sessions() as session, session.begin():
        await PlanRepository(session, tenant_id).append(
            document=stored_document(document),
            objective_breakdown=dict.fromkeys(OBJECTIVE_TERMS, 0.0),
            status=APPLIED,
            reason="materialized",
            weight_set_version=1,
            input_version=1,
            created_at=AT,
        )


async def seed_outcomes(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    document: PlanDocument,
    *,
    state: str = "partial",
    actual_minutes: int | None = 82,
    confirmed: bool = True,
) -> None:
    """One outcome row per block, written as the api's own migration shapes the table."""
    revision_id = await _latest_revision(sessions, tenant_id)
    async with sessions() as session, session.begin():
        for block in document.blocks:
            await session.execute(
                text(
                    "INSERT INTO block_outcomes (id, tenant_id, block_id, binding, revision_id, "
                    "state, actual_minutes, occurred_at, confirmed_at) VALUES (:id, :tenant, "
                    ":block, CAST(:binding AS jsonb), :revision, :state, :minutes, :occurred, "
                    ":confirmed)"
                ),
                {
                    "id": uuid4(),
                    "tenant": tenant_id,
                    "block": block.id,
                    "binding": _json(_stored_binding(block.binding)),
                    "revision": revision_id,
                    "state": state,
                    "minutes": actual_minutes,
                    "occurred": block.interval.start,
                    "confirmed": AT if confirmed else None,
                },
            )


def _stored_binding(binding: BindingRef) -> dict[str, object]:
    from syncr_api.plans.stored_documents import stored_binding

    return dict(stored_binding(binding))


def _json(value: object) -> str:
    import json

    return json.dumps(value)


async def _latest_revision(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> PlanRevisionId:
    async with sessions() as session:
        found = await PlanRepository(session, tenant_id).latest(WEEK)
    assert found is not None
    return found.id


class TestTheReaderResolvesWhatTheApiWrote:
    async def test_the_tenant_list_finds_a_seeded_tenant(
        self, sessions: async_sessionmaker[AsyncSession], tenant: TenantId
    ) -> None:
        assert tenant in await PostgresCorpusReader(sessions, now=AT).tenants()

    async def test_the_weights_in_force_are_the_nine_figures_a_fit_is_stated_against(
        self, sessions: async_sessionmaker[AsyncSession], tenant: TenantId
    ) -> None:
        # Seven weights and the two shaping scalars. A missing one would leave a scalar with nothing
        # to fall back to and the vector with no incumbent to beat.
        in_force = await PostgresCorpusReader(sessions, now=AT).weights_in_force(tenant)

        assert in_force is not None
        assert dict(in_force) == HAND_TUNED_IN_FORCE

    async def test_a_tenant_with_no_active_version_reads_as_none(
        self, sessions: async_sessionmaker[AsyncSession], tenant: TenantId
    ) -> None:
        async with sessions() as session, session.begin():
            await session.execute(
                text("UPDATE weight_sets SET active = false WHERE tenant_id = :tenant"),
                {"tenant": tenant},
            )

        assert await PostgresCorpusReader(sessions, now=AT).weights_in_force(tenant) is None

    async def test_the_area_names_are_what_a_statement_quotes(
        self, sessions: async_sessionmaker[AsyncSession], tenant: TenantId
    ) -> None:
        names = await PostgresCorpusReader(sessions, now=AT).area_names(tenant)

        assert set(names.values()) == {"Fitness"}

    async def test_a_document_the_api_wrote_rebuilds_into_the_blocks_it_held(
        self, sessions: async_sessionmaker[AsyncSession], tenant: TenantId
    ) -> None:
        area_id = await the_area(sessions, tenant)
        document = a_document(area_id, count=3)
        await seed_revision(sessions, tenant, document)

        corpus = await PostgresCorpusReader(sessions, now=AT).corpus(tenant)

        assert len(corpus.revisions) == 1
        rebuilt = corpus.revisions[0]
        assert [one.interval for one in rebuilt.blocks] == [one.interval for one in document.blocks]
        assert [one.binding for one in rebuilt.blocks] == [one.binding for one in document.blocks]
        assert {one.area_id for one in rebuilt.blocks} == {area_id}
        assert rebuilt.zone_by_date == dict.fromkeys(WEEK.dates(), ZONE)

    async def test_an_outcome_the_api_shaped_pairs_with_its_block_by_derived_id(
        self, sessions: async_sessionmaker[AsyncSession], tenant: TenantId
    ) -> None:
        # The pairing is a digest of the week and the binding, computed on both sides. A spelling
        # mismatch would make every outcome match nothing and every fitter read an empty corpus.
        area_id = await the_area(sessions, tenant)
        document = a_document(area_id, count=3)
        await seed_revision(sessions, tenant, document)
        await seed_outcomes(sessions, tenant, document)

        corpus = await PostgresCorpusReader(sessions, now=AT).corpus(tenant)

        assert {one.block_id for one in corpus.outcomes} == {one.id for one in document.blocks}
        assert all(one.is_confirmed for one in corpus.outcomes)

    async def test_an_off_plan_span_reads_back_through_its_reserved_column_name(
        self, sessions: async_sessionmaker[AsyncSession], tenant: TenantId
    ) -> None:
        # `end` is a reserved word. A statement that failed to quote it would raise here rather than
        # silently returning nothing, which is why this is asserted against a real row.
        async with sessions() as session, session.begin():
            await OffPlanPeriodRepository(session, tenant).create(
                interval=Interval(MONDAY, MONDAY + timedelta(days=2)),
                keep_frame=False,
                label="a holiday",
                created_at=AT,
            )

        corpus = await PostgresCorpusReader(sessions, now=AT).corpus(tenant)

        assert len(corpus.off_plan) == 1
        assert corpus.off_plan[0].interval == Interval(MONDAY, MONDAY + timedelta(days=2))

    async def test_the_read_is_bounded_by_the_lookback(
        self, sessions: async_sessionmaker[AsyncSession], tenant: TenantId
    ) -> None:
        area_id = await the_area(sessions, tenant)
        await seed_revision(sessions, tenant, a_document(area_id))
        ancient = IsoWeek(year=2019, week=1)
        async with sessions() as session, session.begin():
            await PlanRepository(session, tenant).append(
                document=stored_document(
                    PlanDocument(
                        iso_week=ancient,
                        zone_by_date=dict.fromkeys(ancient.dates(), ZONE),
                        discretionary_minutes=0,
                        unallocated_minutes=0,
                        oversubscription_minutes=0,
                        blocks=(),
                    )
                ),
                objective_breakdown=dict.fromkeys(OBJECTIVE_TERMS, 0.0),
                status=APPLIED,
                reason="materialized",
                weight_set_version=1,
                input_version=1,
                created_at=datetime(2019, 1, 7, tzinfo=UTC),
            )

        corpus = await PostgresCorpusReader(sessions, now=AT).corpus(tenant)

        assert [str(one.iso_week) for one in corpus.revisions] == [str(WEEK)]


class TestTheWriterAppends:
    async def test_the_first_append_takes_version_two_and_is_not_active(
        self, sessions: async_sessionmaker[AsyncSession], tenant: TenantId
    ) -> None:
        version = await PostgresParameterWriter(sessions).append_version(tenant, an_artifact())

        row = await _weight_set(sessions, tenant, version)

        assert version == 2
        assert row.active is False
        assert row.origin == "fitted"
        assert row.fitted_at == AT
        assert row.duration_multiplier == {str(ARTIFACT_AREA): 1.2}
        assert row.skip_probability == {str(ARTIFACT_AREA): {"morning": 0.4}}
        assert row.time_of_day_fitness == {str(ARTIFACT_AREA): [1.0] * 24}
        assert len(row.maturity) == 1
        assert row.maturity[0]["plain_language"]

    async def test_a_second_append_takes_the_next_version_and_leaves_the_first_alone(
        self, sessions: async_sessionmaker[AsyncSession], tenant: TenantId
    ) -> None:
        writer = PostgresParameterWriter(sessions)

        first = await writer.append_version(tenant, an_artifact())
        second = await writer.append_version(tenant, an_artifact(multiplier=1.9))

        assert (await _weight_set(sessions, tenant, first)).duration_multiplier == {
            str(ARTIFACT_AREA): 1.2
        }
        assert (await _weight_set(sessions, tenant, second)).duration_multiplier == {
            str(ARTIFACT_AREA): 1.9
        }
        assert second == first + 1

    async def test_exactly_one_version_stays_active_per_tenant(
        self, sessions: async_sessionmaker[AsyncSession], tenant: TenantId
    ) -> None:
        # Ticket 7's partial unique index enforces it, and appending never touches the flag, so a
        # run cannot make a second row claim to be the weights in use.
        await PostgresParameterWriter(sessions).append_version(tenant, an_artifact())
        await PostgresParameterWriter(sessions).append_version(tenant, an_artifact())

        async with sessions() as session:
            active = await session.scalar(
                text("SELECT count(*) FROM weight_sets WHERE tenant_id = :tenant AND active"),
                {"tenant": tenant},
            )

        assert active == 1

    async def test_the_stored_curve_is_readable_by_the_solver_s_own_projection(
        self, sessions: async_sessionmaker[AsyncSession], tenant: TenantId
    ) -> None:
        # The loop this ticket closes: a run writes the two fitted maps and the api reads them back
        # into the value the objective applies. Without this the stored spelling would be this
        # package's private invention.
        from syncr_api.learned.weight_reading import as_weight_set

        version = await PostgresParameterWriter(sessions).append_version(tenant, an_artifact())
        async with sessions() as session:
            stored = next(
                one
                for one in await WeightSetRepository(session, tenant).versions()
                if one.version == version
            )

        weights = as_weight_set(stored)

        assert weights.fitness_at(ARTIFACT_AREA, 7) == 1.0
        assert weights.skip_at(ARTIFACT_AREA, TimeBucket.MORNING) == 0.4
        # The other direction: an Area the map does not name has no fitted curve, and none is
        # applied.
        assert weights.fitness_at(uuid4(), 7) is None


class TestTheLayerNeverWritesTheThreeFactTables:
    def test_no_statement_in_the_storage_package_writes_a_plan_a_pin_or_an_outcome(self) -> None:
        # The source half. A write reaches a table only through an `insert`, `update` or `delete`
        # naming it, so the check is over the calls a module makes and the names they carry.
        writing = tables_written(Path(spelling.__file__).parent)

        assert writing == {spelling.WEIGHT_SETS}
        for forbidden in spelling.NEVER_WRITTEN:
            assert forbidden not in writing

    def test_the_walk_would_see_a_write_to_one_of_them(self, tmp_path: Path) -> None:
        # The positive control. Without it, a walk that found no statements at all would pass
        # forever.
        (tmp_path / "control.py").write_text(
            "from sqlalchemy import insert, table\n"
            "PINS = table('pins')\n"
            "STATEMENT = insert(PINS)\n",
            encoding="utf-8",
        )

        assert "pins" in tables_written(tmp_path)

    async def test_a_whole_run_leaves_the_three_tables_row_counts_unchanged(
        self, sessions: async_sessionmaker[AsyncSession], tenant: TenantId
    ) -> None:
        # The runtime half, over a corpus that reaches the duration, fitness, skip and switch
        # fitters.
        area_id = await the_area(sessions, tenant)
        document = a_document(area_id, count=4)
        await seed_revision(sessions, tenant, document)
        await seed_outcomes(sessions, tenant, document)
        before = await counts(sessions, tenant)

        report = await run(
            PostgresCorpusReader(sessions, now=AT), PostgresParameterWriter(sessions), at=AT
        )

        # Scoped to this tenant rather than to the whole report: a developer's database holds other
        # tenants, and a test cannot claim every one of them is healthy.
        assert not [one for one in report.failures if str(tenant) in one], report.failures
        assert await counts(sessions, tenant) == before

    async def test_a_whole_run_appends_one_version_and_records_the_observations_it_read(
        self, sessions: async_sessionmaker[AsyncSession], tenant: TenantId
    ) -> None:
        area_id = await the_area(sessions, tenant)
        document = a_document(area_id, count=4)
        await seed_revision(sessions, tenant, document)
        await seed_outcomes(sessions, tenant, document)

        report = await run(
            PostgresCorpusReader(sessions, now=AT), PostgresParameterWriter(sessions), at=AT
        )

        mine = [one for one in report.tenants if one.tenant_id == tenant]
        assert len(mine) == 1
        # Four confirmed partials in one Area: below the gate of twelve, so nothing is applied and
        # the row says so. That is the end-to-end statement of the gate over real rows.
        samples = mine[0].fitted.samples_by_parameter()
        assert samples["duration_multiplier"] == 4
        assert mine[0].fitted.artifact.duration_multiplier == {}

    async def test_an_unconfirmed_week_produces_no_observations_at_all(
        self, sessions: async_sessionmaker[AsyncSession], tenant: TenantId
    ) -> None:
        area_id = await the_area(sessions, tenant)
        document = a_document(area_id, count=4)
        await seed_revision(sessions, tenant, document)
        await seed_outcomes(sessions, tenant, document, confirmed=False)

        report = await run(
            PostgresCorpusReader(sessions, now=AT), PostgresParameterWriter(sessions), at=AT
        )

        mine = next(one for one in report.tenants if one.tenant_id == tenant)

        assert mine.fitted.samples_by_parameter().get("duration_multiplier", 0) == 0


async def counts(sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId) -> dict[str, int]:
    found: dict[str, int] = {}
    async with sessions() as session:
        for name in spelling.NEVER_WRITTEN:
            found[name] = (
                await session.scalar(
                    text(f"SELECT count(*) FROM {name} WHERE tenant_id = :tenant"),  # noqa: S608
                    {"tenant": tenant_id},
                )
                or 0
            )
    return found


def tables_written(directory: Path) -> set[str]:
    """Every table name a module in ``directory`` passes to an insert, update or delete.

    Read as syntax rather than by importing, so a table named in a comment or an annotation is not
    counted and a statement built at import time is.
    """
    writing: set[str] = set()
    for path in sorted(directory.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        tables = _tables_by_name(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id not in {"insert", "update", "delete"}:
                continue
            for argument in node.args:
                writing |= _named(argument, tables)
    return writing


def _tables_by_name(tree: ast.Module) -> dict[str, str]:
    """Each module-level ``X = table("name", ...)`` binding, so a write on ``X`` names its table."""
    bound: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        if not isinstance(node.value.func, ast.Name) or node.value.func.id != "table":
            continue
        first = node.value.args[0] if node.value.args else None
        name = _literal_or_attribute(first)
        for target in node.targets:
            if isinstance(target, ast.Name) and name is not None:
                bound[target.id] = name
    return bound


def _named(argument: ast.expr, tables: dict[str, str]) -> set[str]:
    if isinstance(argument, ast.Name) and argument.id in tables:
        return {tables[argument.id]}
    literal = _literal_or_attribute(argument)
    return {literal} if literal is not None else set()


def _literal_or_attribute(node: ast.expr | None) -> str | None:
    """A table name written as a literal, or resolved from ``spelling.X`` at module scope."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Attribute):
        resolved = getattr(spelling, node.attr, None)
        return resolved if isinstance(resolved, str) else None
    return None


async def _weight_set(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, version: int
) -> WeightSetRecord:
    async with sessions() as session:
        rows = await WeightSetRepository(session, tenant_id).versions()
    found = [one for one in rows if one.version == version]
    assert found, f"version {version} was not written"
    return found[0]


def an_artifact(*, multiplier: float = 1.2) -> FittedWeightSet:
    """One appendable artefact carrying all three maps, so every stored key is exercised."""
    return FittedWeightSet(
        term_weights=dict.fromkeys(OBJECTIVE_TERMS, 2.0),
        context_switch_cost=4.5,
        churn_tolerance=6.0,
        duration_multiplier={str(ARTIFACT_AREA): multiplier},
        time_of_day_fitness={str(ARTIFACT_AREA): (1.0,) * 24},
        skip_probability={str(ARTIFACT_AREA): {"morning": 0.4}},
        maturity=(
            ParameterMaturity(
                parameter=f"duration_multiplier[{ARTIFACT_AREA}]",
                samples=12,
                threshold=12,
                state="ready",
                value=multiplier,
                shrinkage_weight=0.45,
                plain_language="You estimate 60m; your actual median is 82m.",
            ),
        ),
        fitted_at=AT,
    )
