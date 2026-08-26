"""The Postgres adapter against a real database, seeded through the API's own writers.

What cannot be tested with literals is whether the restated spelling matches the schema. The pure
tier's agreement test crosses the names the api states as constants; this crosses the rest, in the
only way that means anything: **the api writes the rows and the learning adapter reads them back**.
A stored document assembled by hand in a test would be a third spelling, and it would agree with
this package by construction while disagreeing with production.

Importing ``syncr_api`` here is a DEV dependency, declared in this member's manifest, and
``test_package_boundary.py`` asserts the image installs neither it nor the solver.

The never-writes guard is here rather than in the pure tier because it is stated over the storage
subpackage's own source AND over the database: the source half says no statement names those tables
as a write, and the runtime half counts their rows across a whole run.
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
from syncr_api.plans.declarations import EditToRecord, PinToHold
from syncr_api.plans.edit_context import EditContext
from syncr_api.plans.edits import EditEventRepository
from syncr_api.plans.pins import PinRepository
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_documents import stored_document
from syncr_api.user_settings.repository import SettingsRepository
from syncr_domain.habits import BindingSource
from syncr_domain.identity import (
    TASK_OCCURRENCE_KEY,
    BindingKind,
    BindingRef,
    block_id,
    habit_occurrence_keys,
)
from syncr_domain.intervals import Interval
from syncr_domain.plan import Block, PlanDocument
from syncr_domain.promotion import detect_repeated_pins
from syncr_domain.reasons import Bound, ReasonRecord
from syncr_domain.weeks import IsoWeek
from syncr_learning.artifact import FittedWeightSet
from syncr_learning.config import OBJECTIVE_TERMS
from syncr_learning.gates import ParameterMaturity
from syncr_learning.job import run
from syncr_learning.preferences import unmeasured
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

# The content every seeded pin names, so three pins across three weeks are three pins of ONE habit,
# which is what makes the dropped occurrence key the thing under test.
GYM = UUID("55555555-5555-4555-8555-555555555555")

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


async def seed_pin(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    *,
    iso_week: IsoWeek,
    occurrence: int = 0,
    hour: int = 13,
) -> None:
    """One pin through the api's own repository, so the stored binding is production's shape."""
    binding = BindingRef(
        kind=BindingKind.HABIT,
        entity_id=GYM,
        occurrence_key=habit_occurrence_keys(occurrence + 1)[occurrence],
        split_index=None,
    )
    monday = datetime(
        iso_week.monday().year, iso_week.monday().month, iso_week.monday().day, tzinfo=UTC
    )
    start = monday + timedelta(days=1, hours=hour)
    async with sessions() as session, session.begin():
        await PinRepository(session, tenant_id).hold(
            PinToHold(
                iso_week=iso_week,
                block_id=block_id(iso_week, binding),
                binding=binding,
                interval=Interval(start, start + timedelta(minutes=60)),
                superseded_placement=Interval(
                    start - timedelta(hours=6), start - timedelta(hours=5)
                ),
                objective_delta=0.1,
                weight_set_version=1,
                created_at=AT,
            )
        )


async def seed_edit(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    *,
    iso_week: IsoWeek,
    measured: bool = True,
) -> None:
    """One edit event, written through the api's own repository and its own context serializer.

    ``measured=False`` writes the shape a row from before the measurement carries, which is what
    stays in the corpus permanently, because nothing prunes an edit event.
    """
    binding = BindingRef(
        kind=BindingKind.TASK,
        entity_id=uuid4(),
        occurrence_key=TASK_OCCURRENCE_KEY,
        split_index=None,
    )
    monday = datetime(
        iso_week.monday().year, iso_week.monday().month, iso_week.monday().day, tzinfo=UTC
    )
    async with sessions() as session, session.begin():
        await EditEventRepository(session, tenant_id).append(
            EditToRecord(
                iso_week=iso_week,
                binding=binding,
                proposed=Interval(monday + timedelta(hours=6), monday + timedelta(hours=7)),
                accepted=Interval(monday + timedelta(hours=13), monday + timedelta(hours=14)),
                objective_delta=1.25,
                weight_set_version=1,
                context=EditContext(
                    weekday=1,
                    accepted_start_minute_of_day=780,
                    proposed_start_minute_of_day=360,
                    duration_minutes=60,
                    zone=ZONE,
                    objective_breakdown=dict.fromkeys(OBJECTIVE_TERMS, 1.0),
                    measurement_delta=(dict.fromkeys(OBJECTIVE_TERMS, -0.5) if measured else None),
                    discretionary_minutes=5880,
                    unallocated_minutes=1000,
                    blocks_in_day=4,
                    pinned_blocks_in_week=0,
                    area_id=None,
                    area_floor_minutes=None,
                    area_placed_minutes=0,
                    area_target_minutes=0,
                    gap_before_minutes=30,
                    gap_after_minutes=30,
                    adjacent_area_before=None,
                    adjacent_area_after=None,
                ),
                created_at=AT,
            )
        )


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

    async def test_all_five_reads_carry_the_bound_the_module_claims(
        self, sessions: async_sessionmaker[AsyncSession], tenant: TenantId
    ) -> None:
        """The claim held for three of the five, and the bound IS the budget's justification.

        `edit_events` is the one table nothing prunes, so it is the one that grows without
        limit: an unbounded read of it is the one that would eventually cost the nightly budget.
        """
        area_id = await the_area(sessions, tenant)
        document = a_document(area_id, count=2)
        await seed_revision(sessions, tenant, document)
        await seed_outcomes(sessions, tenant, document)
        await seed_edit(sessions, tenant, iso_week=WEEK)
        await seed_pin(sessions, tenant, iso_week=WEEK)
        async with sessions() as session, session.begin():
            await OffPlanPeriodRepository(session, tenant).create(
                interval=Interval(MONDAY, MONDAY + timedelta(days=2)),
                keep_frame=False,
                label="inside the lookback",
                created_at=AT,
            )

        inside = await PostgresCorpusReader(sessions, now=AT).corpus(tenant)
        # A run five years later: every row above is now older than the lookback, so every one of
        # the five reads has to drop it.
        much_later = await PostgresCorpusReader(sessions, now=AT + timedelta(days=5 * 365)).corpus(
            tenant
        )

        assert (
            len(inside.revisions),
            len(inside.outcomes),
            len(inside.edits),
            len(inside.pins),
            len(inside.off_plan),
        ) == (1, 2, 1, 1, 1)
        assert much_later.revisions == ()
        assert much_later.outcomes == ()
        assert much_later.edits == ()
        assert much_later.pins == ()
        assert much_later.off_plan == ()

    async def test_a_span_still_running_is_kept_however_long_ago_it_was_declared(
        self, sessions: async_sessionmaker[AsyncSession], tenant: TenantId
    ) -> None:
        # The off-plan bound is on the span's END, not its start: a long absence declared two years
        # ago and still running governs the week this run reads.
        async with sessions() as session, session.begin():
            await OffPlanPeriodRepository(session, tenant).create(
                interval=Interval(AT - timedelta(days=800), AT + timedelta(days=30)),
                keep_frame=False,
                label="a long absence",
                created_at=AT - timedelta(days=800),
            )

        corpus = await PostgresCorpusReader(sessions, now=AT).corpus(tenant)

        assert len(corpus.off_plan) == 1

    async def test_a_pin_the_api_wrote_projects_into_a_promotion_candidate(
        self, sessions: async_sessionmaker[AsyncSession], tenant: TenantId
    ) -> None:
        """The one JSONB shape no other fixture covered: a stored `pins.binding` read back.

        Three pins of one content at one local time across three consecutive weeks, written through
        the api's own model, so the binding spelling is production's rather than this test's.
        """
        weeks = (WEEK, WEEK.following(), WEEK.following().following())
        for index, week in enumerate(weeks):
            await seed_pin(sessions, tenant, iso_week=week, occurrence=index)

        corpus = await PostgresCorpusReader(sessions, now=AT).corpus(tenant)
        candidates = detect_repeated_pins(corpus.pins)

        assert len(corpus.pins) == 3
        # Three DIFFERENT occurrence keys, which is what makes the dropped key the thing under test.
        assert len({one.binding.occurrence_key for one in corpus.pins}) == 3
        assert len(candidates) == 1
        assert candidates[0].ref.local_time == "13:00"
        assert candidates[0].consecutive_weeks == 3

    async def test_an_edit_event_the_api_wrote_projects_its_measurement_difference(
        self, sessions: async_sessionmaker[AsyncSession], tenant: TenantId
    ) -> None:
        """The other JSONB shape: `edit_events.context`, read back through the adapter.

        Written through `EditEventRepository.append` and `stored_context`, so the key the fitter
        reads is the key the api writes rather than one this test chose.
        """
        await seed_edit(sessions, tenant, iso_week=WEEK)

        corpus = await PostgresCorpusReader(sessions, now=AT).corpus(tenant)

        assert len(corpus.edits) == 1
        edit = corpus.edits[0]
        assert edit.measurement_delta is not None
        assert set(edit.measurement_delta) == set(OBJECTIVE_TERMS)
        assert edit.measurement_delta["churn"] == -0.5
        assert edit.inside_off_plan is False

    async def test_an_edit_written_before_the_measurement_reads_back_as_unmeasured(
        self, sessions: async_sessionmaker[AsyncSession], tenant: TenantId
    ) -> None:
        # The corpus nothing prunes. The absence has to read as a value the fit can exclude, not
        # as a corrupt row, and this drives it through the real column.
        await seed_edit(sessions, tenant, iso_week=WEEK, measured=False)

        corpus = await PostgresCorpusReader(sessions, now=AT).corpus(tenant)

        assert corpus.edits[0].measurement_delta is None
        assert unmeasured(corpus.edits, corpus.off_plan) == 1


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
        # `uq_weight_sets_tenant_id_active` enforces it, and appending never touches the flag, so a
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
        # Both ends of the loop: a run writes the two fitted maps and the api reads them back
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
