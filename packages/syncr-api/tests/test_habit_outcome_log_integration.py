"""Both habit figures against a log a real request wrote, read through the wiring production uses.

The service suite asserts the two derivations against a log handed in through the reader seam, so
it holds whatever the fake was given. This asserts the half a fake cannot: that the rows a habit
response answers from are rows in ``block_outcomes``, found by the projection the habit module is
wired to. Wire the seam back to an empty log and both figures collapse, which is the whole claim.

**And that the week the assembler produces answers from the same rows.** Two components derive the
rotation cursor and the outstanding debt, the habit routes and the week assembler, and each acquires
the log through its own composition. So the two crossings here read one figure from the habit
resource and the same figure out of the assembled week, in one test: the resource alone proves the
projection, the week alone proves an expansion, and only the pair proves the plan places the variant
the habit's own screen names.

**The rows are written by the outcome routes rather than by this suite.** A binding reaches the
table in the spelling ``stored_binding`` writes, and the projection extracts two of its keys, so a
seeded row spelled by hand would prove the reader matches the seeder rather than the writer. That
is the failure mode worth defending against here: a key nobody writes matches no row, and the
symptom is every rotation habit reading as sitting on its first variant with nothing reporting it.

**The index is asserted against the live schema.** The model-level assertion in
``test_plan_storage_boundary.py`` says the projection states both keys the index leads with, and it
passes against a database that never created the index: the two facts are declared in different
files and only one of them is what makes the read cheap.

The cookie is replayed by setting the header rather than through a cookie jar: the cookie is
``Secure``, and an HTTP client that honors that attribute will not send it back over
``http://testserver``.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.areas.config import AREAS_PREFIX
from syncr_api.core.app_factory import create_app
from syncr_api.core.clock import utc_now
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS
from syncr_api.core.tenancy import TENANT_ID_COLUMN
from syncr_api.habits.config import HABITS_PREFIX
from syncr_api.outcomes.config import BLOCKS_PREFIX, DAYS_PREFIX
from syncr_api.plans.assembler import AssemblyCaller
from syncr_api.plans.config import APPLIED, BLOCK_OUTCOMES_TABLE
from syncr_api.plans.facts import BlockOutcome
from syncr_api.plans.habit_log import HabitOutcomeLog
from syncr_api.plans.injection import build_week_assembler
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_documents import (
    BINDING,
    ENTITY_ID,
    KIND,
    OCCURRENCE_KEY,
    SPLIT_INDEX,
    stored_document,
)
from syncr_domain.habits import (
    DEFAULT_DEBT_CAP_PERIODS,
    BindingSource,
    TimesPerWeek,
    occurrences_per_period,
)
from syncr_domain.identity import BindingKind, BindingRef, index_occurrence_key
from syncr_domain.intervals import Interval
from syncr_domain.plan import Block, PlanDocument
from syncr_domain.reasons import Bound, ReasonRecord
from syncr_domain.weeks import IsoWeek, active_zone_by_date
from syncr_domain.zones import ZoneProfile
from tests.live_tenants import PASSWORD, provision_owner, remove_tenant, run

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings
    from syncr_domain.identifiers import AreaId, TenantId
    from syncr_domain.outcomes import HabitOutcome
    from syncr_domain.zones import Date
    from syncr_solver.inputs import SolveInputs

pytestmark = pytest.mark.integration

BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]
UTC_ZONE = "UTC"

# The index the projection's two predicates exist to reach, and the clause its key list follows.
BINDING_INDEX = "ix_block_outcomes_tenant_id_binding_entity"
KEY_LIST = "USING btree ("
INDEX_DEFINITION = text(
    "SELECT indexdef FROM pg_indexes WHERE tablename = :table AND indexname = :index"
)

A_REASON = ReasonRecord((Bound(BindingSource.ROTATION, "Gym · rotation"),))
GYM_SPLIT = ["Push", "Pull", "Legs"]
THREE_A_WEEK: dict[str, Any] = {"kind": "times_per_week", "timesPerWeek": 3}

# One skip more than the declared cap can hold, so the clamp is observable rather than assumed. The
# cap is a product of the habit's own two figures, so it is derived here from the cadence every
# habit below is declared with and the periods a habit that states none is created with.
CADENCE = TimesPerWeek(THREE_A_WEEK["timesPerWeek"])
OVER_THE_CAP = DEFAULT_DEBT_CAP_PERIODS * occurrences_per_period(CADENCE) + 1

# Yesterday, so every block is behind `now`: a day that has not begun is not confirmable, and an
# occurrence that has not come due is not missed.
YESTERDAY = (utc_now() - timedelta(days=1)).date()
WEEK = IsoWeek.containing(YESTERDAY)


@pytest.fixture
def owner(live_database_url: str) -> Iterator[UserRecord]:
    account = provision_owner(live_database_url)
    yield account
    remove_tenant(live_database_url, account.tenant_id)


@pytest.fixture
def http(live_database_url: str, settings: ServiceSettings) -> Iterator[TestClient]:
    """A client against an app wired to the live database, as the process wires it."""
    database = create_database(live_database_url)
    app = create_app(settings, lifespan=create_db_lifespan(database.engine))
    app.state.db = database
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def signed_in(http: TestClient, owner: UserRecord) -> dict[str, str]:
    """The headers a signed-in browser sends: the session cookie and its origin."""
    answered = http.post(
        f"{AUTH_PREFIX}/login",
        json={"email": owner.email, "password": PASSWORD},
        headers={"Origin": BROWSER_ORIGIN},
    )
    assert answered.status_code == HTTPStatus.OK, answered.text
    cookie = answered.headers["set-cookie"]
    token = cookie.split(f"{SESSION_COOKIE_NAME}=", 1)[1].split(";", 1)[0]
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}", "Origin": BROWSER_ORIGIN}


def declare_area(http: TestClient, headers: dict[str, str]) -> AreaId:
    answered = http.post(AREAS_PREFIX, json={"name": f"Fitness {uuid4().hex[:8]}"}, headers=headers)
    assert answered.status_code == HTTPStatus.CREATED, answered.text
    return UUID(answered.json()["area"]["id"])


def declare_habit(
    http: TestClient, headers: dict[str, str], area_id: AreaId, **overrides: object
) -> UUID:
    body: dict[str, Any] = {
        "areaId": str(area_id),
        "title": "Gym",
        "cadence": dict(THREE_A_WEEK),
        "minDurationMinutes": 60,
        "missPolicy": "forgive",
    }
    body.update(overrides)
    answered = http.post(HABITS_PREFIX, json=body, headers=headers)
    assert answered.status_code == HTTPStatus.CREATED, answered.text
    return UUID(answered.json()["id"])


def read_habit(http: TestClient, headers: dict[str, str], habit_id: UUID) -> dict[str, Any]:
    answered = http.get(f"{HABITS_PREFIX}/{habit_id}", headers=headers)
    assert answered.status_code == HTTPStatus.OK, answered.text
    read: dict[str, Any] = answered.json()
    return read


def an_occurrence(
    *, habit_id: UUID, index: int, hour: int, area_id: AreaId, make_up: bool = False
) -> Block:
    """One habit occurrence as the assembler places it: a block bound to the habit and its index."""
    starts = datetime.combine(YESTERDAY, time(hour), tzinfo=UTC)
    return Block(
        iso_week=WEEK,
        interval=Interval(starts, starts + timedelta(hours=1)),
        binding=BindingRef.for_habit(habit_id, index=index),
        title="Gym",
        reason=A_REASON,
        area_id=area_id,
        make_up=make_up,
    )


def seed_plan(database_url: str, tenant_id: TenantId, blocks: Sequence[Block]) -> None:
    """One applied revision holding ``blocks``, appended through the repository that owns it.

    Not through ``live_weeks.produce_a_plan``, which is the sibling a reader reaches for first: that
    solves the assembled week, so the solver chooses which occurrence index each block binds and
    what hour it sits at. Both are what these cases name: the outcome route is addressed by block,
    and the debt derivation clips on the instant an occurrence came due. There is no route to reach
    for either, because no route produces a plan.
    """
    document = PlanDocument(
        iso_week=WEEK,
        zone_by_date=active_zone_by_date(WEEK, ZoneProfile(UTC_ZONE)),
        discretionary_minutes=0,
        unallocated_minutes=0,
        oversubscription_minutes=0,
        blocks=tuple(blocks),
    )

    async def append() -> None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                await PlanRepository(session, tenant_id).append(
                    document=stored_document(document),
                    objective_breakdown={},
                    status=APPLIED,
                    reason="materialized",
                    weight_set_version=1,
                    input_version=1,
                    created_at=utc_now(),
                )
        finally:
            await database.engine.dispose()

    run(append())


def record_skip(http: TestClient, headers: dict[str, str], block: Block) -> None:
    answered = http.put(
        f"{BLOCKS_PREFIX}/{block.id}/outcome",
        json={"isoWeek": str(WEEK), "state": "skipped"},
        headers=headers,
    )
    assert answered.status_code == HTTPStatus.OK, answered.text


def record_completion(http: TestClient, headers: dict[str, str], block: Block) -> None:
    answered = http.put(
        f"{BLOCKS_PREFIX}/{block.id}/outcome",
        json={"isoWeek": str(WEEK), "state": "completed"},
        headers=headers,
    )
    assert answered.status_code == HTTPStatus.OK, answered.text


def confirm_day(http: TestClient, headers: dict[str, str], on: Date) -> None:
    answered = http.post(f"{DAYS_PREFIX}/{on.isoformat()}/confirm", headers=headers)
    assert answered.status_code == HTTPStatus.OK, answered.text


def assemble(database_url: str, tenant_id: TenantId, week: IsoWeek = WEEK) -> SolveInputs:
    """One week's solve inputs, composed exactly as every week route composes them.

    Through the wiring rather than through a hand-built assembler, because the composition is what
    decides which log the expansion derives from and that is the claim under test.
    """

    async def read() -> SolveInputs:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                assembler = build_week_assembler(session, tenant_id, caller=AssemblyCaller.REQUEST)
                return await assembler.assemble(week, utc_now())
        finally:
            await database.engine.dispose()

    return run(read())


def variants_of(inputs: SolveInputs) -> list[str | None]:
    return [occurrence.variant for occurrence in inputs.habit_occurrences]


def test_the_cursor_the_habit_resource_reports_is_the_one_the_assembled_week_places(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # The seam this crosses is the log the habit endpoint reads against the log the assembly reads.
    # Either surface alone proves nothing: the resource could report a cursor no plan honors, and
    # the week could place a rotation nothing else agrees with. Read at rest and again after one
    # confirmation, because two surfaces that are both stuck agree at rest.
    area_id = declare_area(http, signed_in)
    habit_id = declare_habit(http, signed_in, area_id, bindingSource="rotation", variants=GYM_SPLIT)
    seed_plan(
        live_database_url,
        owner.tenant_id,
        [an_occurrence(habit_id=habit_id, index=0, hour=9, area_id=area_id)],
    )

    at_rest = read_habit(http, signed_in, habit_id)["cursor"]["variant"]
    week_at_rest = variants_of(assemble(live_database_url, owner.tenant_id))
    confirm_day(http, signed_in, YESTERDAY)
    advanced = read_habit(http, signed_in, habit_id)["cursor"]["variant"]
    week_advanced = variants_of(assemble(live_database_url, owner.tenant_id))

    assert (at_rest, week_at_rest[0]) == (GYM_SPLIT[0], GYM_SPLIT[0])
    assert (advanced, week_advanced[0]) == (GYM_SPLIT[1], GYM_SPLIT[1])
    # The whole week, so a rotation that advanced its first occurrence and nothing after it fails.
    assert week_advanced == [GYM_SPLIT[1], GYM_SPLIT[2], GYM_SPLIT[0]]


def test_the_debt_the_habit_resource_reports_arrives_in_the_week_capped_as_declared(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # The other derivation over the same read, crossed the same way, with one skip more than the cap
    # so the clamp is observable: the cap is read from the resource rather than typed here, and the
    # week is asserted to hold exactly that many made-up occurrences and no more.
    area_id = declare_area(http, signed_in)
    habit_id = declare_habit(http, signed_in, area_id, title="Anki", missPolicy="debt")
    occurrences = [
        an_occurrence(habit_id=habit_id, index=index, hour=9 + index, area_id=area_id)
        for index in range(OVER_THE_CAP)
    ]
    seed_plan(live_database_url, owner.tenant_id, occurrences)

    fresh = len(assemble(live_database_url, owner.tenant_id).habit_occurrences)
    for occurrence in occurrences:
        record_skip(http, signed_in, occurrence)
    confirm_day(http, signed_in, YESTERDAY)
    debt = read_habit(http, signed_in, habit_id)["debt"]
    week = assemble(live_database_url, owner.tenant_id).habit_occurrences

    # The cap is pinned before it is used as an expectation. Read from the response and compared
    # against nothing, a cap that had collapsed to zero would satisfy every assertion below while no
    # made-up occurrence reached the week at all.
    assert debt["cap"] == OVER_THE_CAP - 1
    assert (fresh, debt["misses"]) == (THREE_A_WEEK["timesPerWeek"], OVER_THE_CAP)
    assert (debt["outstanding"], debt["raisedInWeeklySession"]) == (debt["cap"], True)
    assert [occurrence.is_debt for occurrence in week] == [False] * fresh + [True] * debt["cap"]
    assert [occurrence.binding.occurrence_key for occurrence in week] == [
        index_occurrence_key(index) for index in range(fresh + debt["cap"])
    ]


def test_a_confirmed_completion_moves_the_cursor_the_habit_resource_reports(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # The cursor is a count of confirmed completions in the log, so a habit whose occurrence was
    # confirmed reads one variant on from a habit whose log holds nothing.
    area_id = declare_area(http, signed_in)
    habit_id = declare_habit(http, signed_in, area_id, bindingSource="rotation", variants=GYM_SPLIT)
    seed_plan(
        live_database_url,
        owner.tenant_id,
        [an_occurrence(habit_id=habit_id, index=0, hour=9, area_id=area_id)],
    )

    before = read_habit(http, signed_in, habit_id)["cursor"]
    confirm_day(http, signed_in, YESTERDAY)
    after = read_habit(http, signed_in, habit_id)["cursor"]

    assert (before["variant"], before["confirmedCompletions"]) == ("Push", 0)
    assert (after["variant"], after["confirmedCompletions"]) == ("Pull", 1)
    assert after["previousVariant"] == "Push"


def test_confirmed_skips_reach_the_debt_figure_the_habit_resource_reports(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # The other derivation over the same read, and the one no test has ever taken through the
    # database: two skips of a `debt` habit's occurrences are two outstanding sessions, under a cap
    # of two periods times three a week.
    area_id = declare_area(http, signed_in)
    habit_id = declare_habit(http, signed_in, area_id, title="Anki", missPolicy="debt")
    occurrences = [
        an_occurrence(habit_id=habit_id, index=index, hour=hour, area_id=area_id)
        for index, hour in enumerate((9, 11))
    ]
    seed_plan(live_database_url, owner.tenant_id, occurrences)

    before = read_habit(http, signed_in, habit_id)["debt"]
    for occurrence in occurrences:
        record_skip(http, signed_in, occurrence)
    confirm_day(http, signed_in, YESTERDAY)
    after = read_habit(http, signed_in, habit_id)["debt"]

    assert (before["misses"], before["outstanding"]) == (0, 0)
    assert (after["misses"], after["outstanding"], after["cap"]) == (2, 2, 6)
    assert not after["raisedInWeeklySession"]


def test_the_projection_reads_the_mark_the_write_path_stored_and_defaults_the_rows_without_one(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    """``habit_log.py`` projects the binding's own key into ``HabitOutcome``.

    One row here was written by the route, so its mark is the write path's own spelling; the other
    is seeded with a binding that names no mark at all, which is every row written before the mark
    existed. Those read as fresh occurrences, which is the honest default rather than a claimed
    discharge.
    """

    area_id = declare_area(http, signed_in)
    habit_id = declare_habit(http, signed_in, area_id)
    made_up = an_occurrence(habit_id=habit_id, index=1, hour=11, area_id=area_id, make_up=True)
    seed_plan(live_database_url, owner.tenant_id, [made_up])
    record_completion(http, signed_in, made_up)

    # A row from before the mark existed, spelled exactly as ``stored_binding`` spelled it then,
    # against the plan of record the route's own row names.
    async def seed_unmarked() -> None:
        database = create_database(live_database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                revision = await PlanRepository(session, owner.tenant_id).latest(WEEK)
                assert revision is not None
                session.add(
                    BlockOutcome(
                        id=uuid4(),
                        tenant_id=owner.tenant_id,
                        block_id="e" * 64,
                        binding={
                            KIND: BindingKind.HABIT.value,
                            ENTITY_ID: str(habit_id),
                            OCCURRENCE_KEY: "00",
                            SPLIT_INDEX: None,
                        },
                        revision_id=revision.id,
                        state="completed",
                        occurred_at=datetime.combine(YESTERDAY, time(9), tzinfo=UTC),
                    )
                )
        finally:
            await database.engine.dispose()

    run(seed_unmarked())

    async def project() -> tuple[HabitOutcome, ...]:
        database = create_database(live_database_url)
        try:
            async with database.sessionmaker() as session:
                return await HabitOutcomeLog(session, owner.tenant_id).read([habit_id])
        finally:
            await database.engine.dispose()

    rows = {row.occurrence_key: row for row in run(project())}

    assert (rows["00"].is_make_up, rows["01"].is_make_up) == (False, True)


def test_two_made_up_completions_settle_the_debt_by_the_next_weeks_assembly(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    """The whole loop, over HTTP and through the wiring both assemblies compose.

    Two confirmed skips charge two. This week's expansion carries them as made-up occurrences;
    placed, completed, and confirmed, their rows carry the mark, and NEXT week's assembly expands
    the cadence alone: nothing is owed, because the log holds a discharge for each charge. Driven
    through the assembler rather than through ``outstanding_debt``, so the claim is what a week
    route would expand and not only what a function would answer.
    """
    area_id = declare_area(http, signed_in)
    habit_id = declare_habit(http, signed_in, area_id, title="Anki", missPolicy="debt")

    # Two misses, yesterday, confirmed: debt stands at two.
    missed = [
        an_occurrence(habit_id=habit_id, index=index, hour=9 + index, area_id=area_id)
        for index in range(2)
    ]
    seed_plan(live_database_url, owner.tenant_id, missed)
    for occurrence in missed:
        record_skip(http, signed_in, occurrence)
    confirm_day(http, signed_in, YESTERDAY)

    owing = assemble(live_database_url, owner.tenant_id).habit_occurrences
    assert [occurrence.is_debt for occurrence in owing] == [False] * THREE_A_WEEK[
        "timesPerWeek"
    ] + [True, True]

    # The made-up occurrences are placed, marked the way the solver marks them, done, and settled.
    made_up = [
        an_occurrence(
            habit_id=habit_id,
            index=int(occurrence.binding.occurrence_key),
            hour=13 + position,
            area_id=area_id,
            make_up=True,
        )
        for position, occurrence in enumerate(o for o in owing if o.is_debt)
    ]
    seed_plan(live_database_url, owner.tenant_id, made_up)
    for block in made_up:
        record_completion(http, signed_in, block)
    confirm_day(http, signed_in, YESTERDAY)

    # Before the mark existed this read back as two forever; now the next week owes nothing.
    settled = read_habit(http, signed_in, habit_id)["debt"]
    following = assemble(live_database_url, owner.tenant_id, week=WEEK.following())

    assert (settled["misses"], settled["outstanding"]) == (0, 0)
    assert [occurrence.is_debt for occurrence in following.habit_occurrences] == [False] * (
        THREE_A_WEEK["timesPerWeek"]
    )
    assert [occurrence.binding.occurrence_key for occurrence in following.habit_occurrences] == [
        index_occurrence_key(index) for index in range(THREE_A_WEEK["timesPerWeek"])
    ]


def test_the_live_schema_carries_the_index_the_projection_reads_through(
    live_database_url: str,
) -> None:
    # The read runs once per habit collection and its two predicates buy nothing but this index, so
    # an index the migration failed to create has no symptom other than a sequential scan.
    #
    # Read out of the KEY LIST rather than out of the whole definition, which names the index: the
    # name carries the word `tenant_id`, so a definition-wide search finds the tenant leading
    # whatever the index actually leads with. A B-tree is asserted because the ordered condition is
    # the point: a GIN index over the same two keys cannot carry the tenant, which turns the scope
    # into a filter applied after another tenant's rows have been read.
    async def definition() -> str | None:
        database = create_database(live_database_url)
        try:
            async with database.sessionmaker() as session:
                found = await session.scalar(
                    INDEX_DEFINITION,
                    {"table": BLOCK_OUTCOMES_TABLE, "index": BINDING_INDEX},
                )
                return None if found is None else str(found)
        finally:
            await database.engine.dispose()

    indexdef = run(definition())

    assert indexdef is not None, f"{BLOCK_OUTCOMES_TABLE} has no index named {BINDING_INDEX}"
    assert KEY_LIST in indexdef, f"{BINDING_INDEX} is not a B-tree: {indexdef}"
    keys = indexdef.split(KEY_LIST, 1)[1]
    read_in_order = [TENANT_ID_COLUMN, f"({BINDING} ->> '{KIND}'", f"({BINDING} ->> '{ENTITY_ID}'"]
    for key in read_in_order:
        assert key in keys, f"{BINDING_INDEX} does not read {key}: {indexdef}"
    positions = [keys.index(key) for key in read_in_order]
    assert positions == sorted(positions), f"{BINDING_INDEX} reads them out of order: {indexdef}"
