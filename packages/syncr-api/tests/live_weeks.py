"""The rows a week's composed read is driven against, and the declarations that produce them.

Four suites now need one week in the same state: a plan of record, a pending proposal carrying a
solver verdict, approved concessions, a pin and a conflict. None of it is reachable through a route,
because no route produces a plan and no route fills the slot: that is what the horizon maintainer
and the solve worker are for. So the writes go through the same repositories production writes them
through, and they live here rather than in one suite for the reason ``plan_documents.py`` and
``assembly_fakes.py`` do -- a builder imported from a test module couples the two suites.

**Every write is through a real repository**, never raw SQL, so a row this module produces satisfies
the invariants the repository enforces: a proposal lands in the slot the document names, a
concession refuses a reduction outside its own week, and a conflict is raised once per commitment
and block.

**One solve operation per week, created once and shared.** At most one non-terminal solve for a week
can exist, so two helpers each enqueuing their own breach the partial unique index that makes that
an invariant. :func:`enqueue_a_solve` is the one that creates it and its id is what a proposal and a
concession are both pointed at.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.areas.config import AREAS_PREFIX
from syncr_api.concessions.config import WEEKS_PREFIX
from syncr_api.core.db import create_database
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS
from syncr_api.learned.repository import WeightSetRepository
from syncr_api.plans.adjustments import WeekAdjustmentRepository
from syncr_api.plans.assembler import AssemblyCaller
from syncr_api.plans.conflicts import PlanConflictRepository
from syncr_api.plans.declarations import PinToHold
from syncr_api.plans.injection import build_week_assembler
from syncr_api.plans.overlaps import DetectedConflict
from syncr_api.plans.pins import PinRepository
from syncr_api.plans.production import WeekProducer
from syncr_api.plans.proposals import PendingProposalRepository
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_documents import plan_document, stored_document
from syncr_api.plans.stored_proposals import stored_proposal_diff
from syncr_api.plans.stored_verdicts import stored_verdict
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.routines.config import ROUTINES_PREFIX
from syncr_api.solving.config import SOLVE
from syncr_api.solving.lifecycle import OperationLifecycle
from syncr_api.solving.repository import OperationRepository
from syncr_api.tasks.config import TASKS_PREFIX
from syncr_api.templates.config import DAY_TYPES_PREFIX, WEEK_PATTERN_PREFIX
from syncr_domain.feasibility import (
    Provenance,
    Shortfall,
    ShortfallKind,
    Verdict,
    minimum_chunk_shortfall,
)
from syncr_domain.intervals import Interval
from syncr_domain.plan import AdjustmentKind
from syncr_domain.proposals import BlockChange, ProposalDiff
from syncr_domain.weeks import IsoWeek, Weekday
from tests.live_tenants import PASSWORD, run
from tests.plan_documents import a_block, a_document, a_zone_map, between

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

    from syncr_domain.identifiers import TenantId
    from syncr_domain.plan import Block, PlanDocument

BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]
LONDON = "Europe/London"
# Thirteen hours east, so this tenant's local date and the UTC date disagree for part of every day.
AUCKLAND = "Pacific/Auckland"

# The task a stored solver verdict names as unplaceable. A packing failure is the one finding
# capacity arithmetic structurally cannot reach, so its presence in a served verdict is what proves
# the pending slot was read rather than a fresh probe.
UNPLACEABLE = "F&F Past Papers"

# Roughly the block count section 19's latency budget is stated over.
BLOCKS_IN_A_FULL_WEEK = 210

AN_HOUR = 60


def this_week() -> IsoWeek:
    """The week a request reads as current, which is the one inside every horizon."""
    return IsoWeek.containing(datetime.now(UTC).date())


def week_path(iso_week: object, suffix: str = "") -> str:
    return f"{WEEKS_PREFIX}/{iso_week}{suffix}"


# --------------------------------------------------------------------------------
# What a tenant declares, over HTTP, because a route owns each of these
# --------------------------------------------------------------------------------


def sign_in(http: TestClient, email: str) -> dict[str, str]:
    """The headers a signed-in browser sends. The cookie is replayed rather than jarred.

    The cookie is ``Secure`` and a client honoring that attribute will not send it back over
    ``http://testserver``.
    """
    answered = http.post(
        f"{AUTH_PREFIX}/login",
        json={"email": email, "password": PASSWORD},
        headers={"Origin": BROWSER_ORIGIN},
    )
    assert answered.status_code == HTTPStatus.OK, answered.text
    cookie = answered.headers["set-cookie"]
    token = cookie.split(f"{SESSION_COOKIE_NAME}=", 1)[1].split(";", 1)[0]
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}", "Origin": BROWSER_ORIGIN}


def set_home_zone(http: TestClient, headers: dict[str, str], zone: str) -> None:
    """The span and the current week are both resolved in this zone, so every suite states it."""
    answered = http.patch(f"{WEEKS_PREFIX[:-6]}/settings", json={"homeZone": zone}, headers=headers)
    assert answered.status_code == HTTPStatus.OK, answered.text


def declare_an_area(http: TestClient, headers: dict[str, str], **body: object) -> str:
    answered = http.post(AREAS_PREFIX, json={"name": "Career", **body}, headers=headers)
    assert answered.status_code == HTTPStatus.CREATED, answered.text
    return str(answered.json()["area"]["id"])


def declare_a_day_shape(http: TestClient, headers: dict[str, str]) -> None:
    """A day type on all seven weekdays, which is what makes a week pattern a pattern."""
    day_type = http.post(DAY_TYPES_PREFIX, json={"name": "Weekday"}, headers=headers)
    assert day_type.status_code == HTTPStatus.CREATED, day_type.text
    identifier = day_type.json()["id"]
    pattern = http.put(
        WEEK_PATTERN_PREFIX,
        json={weekday.value: identifier for weekday in Weekday},
        headers=headers,
    )
    assert pattern.status_code == HTTPStatus.OK, pattern.text


def declare_a_sleep_routine(http: TestClient, headers: dict[str, str]) -> None:
    """The circadian frame, which is what gives a materialized week any block at all."""
    declared = http.post(
        ROUTINES_PREFIX,
        json={"title": "Sleep", "targetTime": "23:00", "durationMinutes": 480},
        headers=headers,
    )
    assert declared.status_code == HTTPStatus.CREATED, declared.text


def capture_a_task(
    http: TestClient, headers: dict[str, str], area_id: str, *, title: str, **body: object
) -> dict[str, Any]:
    answered = http.post(
        TASKS_PREFIX, json={"areaId": area_id, "title": title, **body}, headers=headers
    )
    assert answered.status_code == HTTPStatus.CREATED, answered.text
    captured: dict[str, Any] = answered.json()
    return captured


def declare_the_minimum(
    http: TestClient, headers: dict[str, str], database_url: str, tenant_id: TenantId
) -> str:
    """An Area, a day shape, a circadian frame, and the weight set a produced revision records.

    The Area's identifier is returned because every task a suite captures needs one, and the weight
    set is seeded past the routes because no route creates one.
    """
    area_id = declare_an_area(http, headers)
    declare_a_day_shape(http, headers)
    declare_a_sleep_routine(http, headers)
    seed_a_weight_set(database_url, tenant_id)
    return area_id


# --------------------------------------------------------------------------------
# Rows no route writes: the plan, the slot, the concessions, the pin, the conflict
# --------------------------------------------------------------------------------


def seed_a_weight_set(database_url: str, tenant_id: TenantId) -> None:
    """The active weight set a produced revision records. No route creates one."""

    async def seed() -> None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                await WeightSetRepository(session, tenant_id).seed_hand_tuned(at=datetime.now(UTC))
        finally:
            await database.engine.dispose()

    run(seed())


def produce_a_plan(database_url: str, tenant_id: TenantId, iso_week: IsoWeek) -> None:
    """A real plan for the week, through the producer the horizon maintainer uses.

    Not through a route, because no route produces a plan: that is the whole point of the horizon
    maintainer, and a read that produced one would be the mutation these suites assert it is not.
    """

    async def produce() -> None:
        now = datetime.now(UTC)
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                await WeekProducer(
                    assembler=build_week_assembler(
                        session, tenant_id, caller=AssemblyCaller.MAINTAINER
                    ),
                    revisions=PlanRepository(session, tenant_id),
                    versions=WeekInputVersionRepository(session, tenant_id),
                    weights=WeightSetRepository(session, tenant_id),
                    operations=OperationLifecycle(
                        OperationRepository(session, tenant_id), lambda: now
                    ),
                ).advance_into(iso_week, now=now)
        finally:
            await database.engine.dispose()

    run(produce())


def the_live_plan(database_url: str, tenant_id: TenantId, iso_week: IsoWeek) -> PlanDocument:
    """The week's plan of record, rebuilt, so a caller can name one of its blocks."""

    async def read() -> PlanDocument:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                latest = await PlanRepository(session, tenant_id).latest(iso_week)
                assert latest is not None, f"{iso_week} holds no plan"
                return plan_document(latest.document)
        finally:
            await database.engine.dispose()

    return run(read())


def the_weeks_version(database_url: str, tenant_id: TenantId, iso_week: IsoWeek) -> int:
    """The week's input version, which is what the currency test compares a slot against."""

    async def read() -> int:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                return await WeekInputVersionRepository(session, tenant_id).tracked_version(
                    iso_week
                )
        finally:
            await database.engine.dispose()

    return run(read())


def a_packing_failure(*, input_version: int, deadline: datetime) -> Verdict:
    """What a completed attempt found and no total over intervals can: capacity in the wrong shape.

    Three hours of free time in six half-hour gaps is three hours by every total the probe takes and
    no minutes at all to a task that cannot be split below fifty.
    """
    return Verdict(
        feasible=False,
        provenance=Provenance.SOLVER,
        computed_at=datetime.now(UTC) - timedelta(minutes=5),
        input_version=input_version,
        discretionary_minutes=6720,
        shortfalls=(
            minimum_chunk_shortfall(
                minutes=50,
                chunk_minutes=50,
                against=(UNPLACEABLE,),
                blocked_by=("the lectures between 09:00 and 17:00",),
                deadline=deadline,
            ),
        ),
    )


def a_solved_deadline_gap(
    *, input_version: int, deadline: datetime, area_id: str, against: str, minutes: int = 360
) -> Verdict:
    """A SOLVER verdict carrying a ``deadline_capacity`` gap that names one task.

    The pair to :func:`a_packing_failure`, and the two exist for opposite reasons. A packing failure
    proves the slot was read, because arithmetic cannot produce one; this one is the kind the
    backlog's at-risk column reads, so it is what drives the pair-of-screens equality on the branch
    the serve rule exists for. A verdict carrying only a packing failure marks no task, by design.

    ``provenance`` is solver and ``feasible`` is false, which is a pair only an attempted placement
    may report: it found a gap and it knows.
    """
    return Verdict(
        feasible=False,
        provenance=Provenance.SOLVER,
        computed_at=datetime.now(UTC) - timedelta(minutes=5),
        input_version=input_version,
        discretionary_minutes=6720,
        shortfalls=(
            Shortfall(
                kind=ShortfallKind.DEADLINE_CAPACITY,
                minutes=minutes,
                against=(against,),
                honoring=("the circadian frame", "the 0m still uncommitted before it"),
                deadline=deadline,
                area_id=UUID(area_id),
            ),
        ),
    )


def a_candidate_moving_one_block(live: PlanDocument) -> tuple[PlanDocument, ProposalDiff]:
    """The proposal a solve lands: the live week with one block two hours later, and its own diff.

    Both halves from one construction, because approval compares the candidate document against the
    live plan and refuses a change the diff never named. A document and a diff built separately are
    exactly the pair that disagrees.
    """
    held = live.blocks[0]
    moved = replace(held, interval=Interval(*_two_hours_later(held)))
    candidate = replace(live, blocks=(moved, *live.blocks[1:]))
    return candidate, ProposalDiff(moved=(BlockChange.moved(live=held, candidate=moved),))


def _two_hours_later(block: Block) -> tuple[datetime, datetime]:
    shift = timedelta(hours=2)
    return (block.interval.start + shift, block.interval.end + shift)


def enqueue_a_solve(database_url: str, tenant_id: TenantId, iso_week: IsoWeek) -> str:
    """One pending solve for the week, which is what a proposal and a concession both point at.

    Enqueued once and shared, because at most one non-terminal solve per week can exist: two helpers
    each creating their own would breach the partial unique index that makes that an invariant.
    """

    async def enqueue() -> str:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                created = await OperationLifecycle(
                    OperationRepository(session, tenant_id), lambda: datetime.now(UTC)
                ).enqueue(kind=SOLVE, iso_week=iso_week)
                return str(created.id)
        finally:
            await database.engine.dispose()

    return run(enqueue())


def fill_the_slot(
    database_url: str,
    tenant_id: TenantId,
    iso_week: IsoWeek,
    *,
    verdict: Verdict,
    document: PlanDocument,
    diff: ProposalDiff,
    input_version: int,
    operation_id: str,
    candidate: dict[str, Any] | None = None,
) -> None:
    """One pending proposal, written through the repository a solve writes it through."""

    async def fill() -> None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                await PendingProposalRepository(session, tenant_id).replace(
                    document=stored_document(document),
                    proposal_diff=stored_proposal_diff(diff),
                    objective_breakdown={},
                    verdict=stored_verdict(verdict),
                    weight_set_version=1,
                    input_version=input_version,
                    operation_id=UUID(operation_id),
                    created_at=datetime.now(UTC),
                    candidate_adjustment=candidate,
                )
        finally:
            await database.engine.dispose()

    run(fill())


def approve_two_concessions(
    database_url: str, tenant_id: TenantId, iso_week: IsoWeek, *, operation_id: str
) -> list[str]:
    """Two approved concessions for one week, of two kinds, as an approval persists them."""

    async def approve() -> list[str]:
        now = datetime.now(UTC)
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                adjustments = WeekAdjustmentRepository(session, tenant_id)
                first = await adjustments.upsert(
                    iso_week=iso_week,
                    kind=AdjustmentKind.BREACH_FLOOR.value,
                    target_id=uuid4(),
                    created_at=now,
                    created_by_operation_id=UUID(operation_id),
                    delta_minutes=80,
                )
                second = await adjustments.upsert(
                    iso_week=iso_week,
                    kind=AdjustmentKind.REDUCE_ROUTINE.value,
                    target_id=uuid4(),
                    created_at=now,
                    created_by_operation_id=UUID(operation_id),
                    reductions={iso_week.dates()[1].isoformat(): 20},
                )
                return [str(first.id), str(second.id)]
        finally:
            await database.engine.dispose()

    return run(approve())


def hold_a_pin(database_url: str, tenant_id: TenantId, iso_week: IsoWeek, block: Block) -> str:
    """One pin on a block of the live plan, at the placement it already holds."""

    async def hold() -> str:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                held = await PinRepository(session, tenant_id).hold(
                    PinToHold(
                        iso_week=iso_week,
                        block_id=block.id,
                        binding=block.binding,
                        interval=block.interval,
                        superseded_placement=block.interval,
                        weight_set_version=1,
                        created_at=datetime.now(UTC),
                    )
                )
                return str(held.id)
        finally:
            await database.engine.dispose()

    return run(hold())


def raise_a_conflict(
    database_url: str, tenant_id: TenantId, iso_week: IsoWeek, block: Block
) -> str:
    """One unanswered conflict on a block of the live plan."""

    async def raise_one() -> str:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                (raised,) = await PlanConflictRepository(session, tenant_id).raise_all(
                    [
                        DetectedConflict(
                            anchor_id=uuid4(),
                            iso_week=iso_week,
                            binding=block.binding,
                            overlap=block.interval,
                        )
                    ],
                    at=datetime.now(UTC),
                )
                return str(raised.id)
        finally:
            await database.engine.dispose()

    return run(raise_one())


def append_a_full_week(database_url: str, tenant_id: TenantId, iso_week: IsoWeek) -> None:
    """A revision holding roughly a full week's blocks, for the latency measurement.

    Materializing a week this full would need a week of declarations, and what the measurement is
    about is the cost of composing and serializing a week that size.
    """

    async def append() -> None:
        document = a_document(
            week=iso_week,
            zone_by_date=a_zone_map(iso_week),
            blocks=tuple(
                a_block(
                    week=iso_week,
                    interval=between(
                        (index % 40) * 0.25 + 6,
                        (index % 40) * 0.25 + 6.5,
                        day=index % 7,
                        week=iso_week,
                    ),
                    binding=a_block(week=iso_week).binding,
                    title=f"block {index}",
                )
                for index in range(BLOCKS_IN_A_FULL_WEEK)
            ),
        )
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                await PlanRepository(session, tenant_id).append(
                    document=stored_document(document),
                    objective_breakdown={},
                    status="applied",
                    reason="horizon_advanced",
                    weight_set_version=1,
                    input_version=1,
                    created_at=datetime.now(UTC),
                )
        finally:
            await database.engine.dispose()

    run(append())


# --------------------------------------------------------------------------------
# What a suite reads back
# --------------------------------------------------------------------------------


def week_view(http: TestClient, headers: dict[str, str], iso_week: object) -> dict[str, Any]:
    answered = http.get(week_path(iso_week), headers=headers)
    assert answered.status_code == HTTPStatus.OK, answered.text
    payload: dict[str, Any] = answered.json()
    return payload


def backlog(http: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    answered = http.get(TASKS_PREFIX, headers=headers)
    assert answered.status_code == HTTPStatus.OK, answered.text
    payload: dict[str, Any] = answered.json()
    return payload
