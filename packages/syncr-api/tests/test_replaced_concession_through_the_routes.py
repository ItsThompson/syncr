"""The interleaving that leaves a revision naming a concession the week holds under another name.

A replacement keeps the replaced row's identifier and the document appended beside it names the
candidate identifier the row did not take, so that revision reports a REPLACED concession. Every
other suite reaches that state by writing the week's pending slot directly. This one asks the
question the count's whole value rests on: **can the shipped routes produce it at all?**

The answer is yes, and the sequence is the one ``plans/folding.py`` predicts in its own words: the
enumerator suppresses an offer for a kind and target the assembly already carries, so a second
concession for one target can only be minted while the first is unapproved, and it becomes real when
an approval lands between the second request and the solve that answers it.

```
request a tradeoff          202, a candidate on the operation, nothing stored
drain the worker            the solve proposes, so the week's slot holds it
request the SAME tradeoff   202. The concession table is still empty, so nothing suppresses it
approve the first           the row is INSERTED under the first candidate's identifier
the plan of record moves    what the maintainer or an adoption does, and what no route can do
drain the worker            the second solve reads the stored row, folds its own candidate on top,
                            and proposes against the plan the week now holds
approve the second          the upsert finds the unique index: the row keeps the FIRST identifier
GET .../revisions           the second revision reports one REPLACED concession, and no revoked one
```

**Why the plan of record is moved by an append rather than by a request.** No route produces a plan:
the horizon maintainer and the solve worker are the two writers, which is why
``test_concession_routes_integration.py`` appends the block its own week is solved around. Without
that step the second solve produces the same document the first approval already made the plan of
record, so its classification is empty, it writes nothing, and there is no second proposal to
approve. That is measured below as well, because it is the reason a shorter sequence does not reach
this state.

The worker is driven one tick at a time through ``SolveDispatch``, which is what
``test_unsolved_week_tradeoff.py`` does and what the worker's own duty does. No e2e harness is
involved.
"""

from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest

from syncr_api.areas.config import AREAS_PREFIX
from syncr_api.concessions.config import WEEKS_PREFIX
from syncr_api.core.app_factory import create_app
from syncr_api.core.clock import utc_now
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.settings import DEFAULT_SOLVE_DEBOUNCE_MS
from syncr_api.offplan.config import OFF_PLAN_PREFIX
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_documents import stored_document
from syncr_api.solving.dispatch import SolveDispatch
from syncr_api.solving.injection import build_solve_coordinator, debounce_window
from syncr_domain.identity import Origin, is_placed_by_the_solver
from syncr_domain.intervals import Interval
from syncr_domain.plan import AdjustmentKind
from tests.live_tenants import provision_owner, remove_tenant, run
from tests.live_weeks import seed_a_weight_set
from tests.plan_documents import a_block, a_document

# The week, its figures, and the helpers that read it are the concession route suite's. Imported
# rather than restated, so a six-hour week short of a seven-hour floor has one definition: a second
# copy of those numbers would be a second week to keep in step. The two route calls that build it
# are made here, because each integration module in this suite builds its own tenant and client.
from tests.test_concession_routes_integration import (
    FLOOR_HOURS,
    ON_PLAN_HOURS,
    PLACED_FROM_HOUR,
    WEEK,
    append_a_solved_revision,
    instant,
    pending_proposal,
    request_tradeoff,
    sign_in,
    stored_concessions,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi.testclient import TestClient

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings
    from syncr_api.solving.records import OperationRecord
    from syncr_domain.identifiers import TenantId

pytestmark = pytest.mark.integration

APPROVE = f"{WEEKS_PREFIX}/{WEEK}/approve"
REVISIONS = f"{WEEKS_PREFIX}/{WEEK}/revisions"

# Where the block that stands for the plan of record moving sits: a second solver-placed block, on a
# different day from the fixture's own so the two cannot be confused in a diff.
MOVED_ON_DAY = 4


@pytest.fixture
def owner(live_database_url: str) -> Iterator[UserRecord]:
    account = provision_owner(live_database_url)
    yield account
    remove_tenant(live_database_url, account.tenant_id)


@pytest.fixture
def http(live_database_url: str, settings: ServiceSettings) -> Iterator[TestClient]:
    from fastapi.testclient import TestClient as Client

    database = create_database(live_database_url)
    app = create_app(settings, lifespan=create_db_lifespan(database.engine))
    app.state.db = database
    with Client(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def a_short_solved_week(
    http: TestClient, owner: UserRecord, live_database_url: str
) -> tuple[dict[str, str], str]:
    """A signed-in tenant whose week is an hour short of its own Fitness floor, with a plan.

    The same week the concession route suite drives, from the same two figures: everything after the
    sixth hour declared off plan, and a seven-hour floor against what is left. The plan of record
    holds one block a solve placed, because a week holding nothing a solve placed is refused before
    the offer is read.
    """
    headers = sign_in(http, owner.email)
    declared = http.post(
        OFF_PLAN_PREFIX,
        json={"start": instant(hours=ON_PLAN_HOURS), "end": instant(days=7), "keepFrame": False},
        headers=headers,
    )
    assert declared.status_code == HTTPStatus.CREATED, declared.text
    area = http.post(
        AREAS_PREFIX, json={"name": "Fitness", "floorHours": FLOOR_HOURS}, headers=headers
    )
    assert area.status_code == HTTPStatus.CREATED, area.text
    append_a_solved_revision(http, headers, live_database_url, owner.tenant_id)
    return headers, area.json()["area"]["id"]


def drain_one_solve(database_url: str, tenant_id: TenantId) -> OperationRecord | None:
    """Claim the due solve and dispatch it, which is what one tick of the worker's duty does.

    ``None`` when nothing is due, so a caller can tick until the queue is empty rather than assume
    how many ticks a request produced.
    """

    async def drive() -> OperationRecord | None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                claim = await build_solve_coordinator(
                    session,
                    tenant_id,
                    clock=utc_now,
                    debounce=debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS),
                ).claim_next()
            if claim is None:
                return None
            return await SolveDispatch(
                database,
                tenant_id,
                clock=utc_now,
                debounce=debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS),
            ).run(claim, WEEK)
        finally:
            await database.engine.dispose()

    return run(drive())


def drain_until_the_slot_fills(database_url: str, tenant_id: TenantId, *, ticks: int = 4) -> bool:
    """Tick the worker until the week's slot holds a proposal, or the queue empties."""
    for _ in range(ticks):
        if drain_one_solve(database_url, tenant_id) is None:
            break
        if pending_proposal(database_url, tenant_id) is not None:
            return True
    return pending_proposal(database_url, tenant_id) is not None


def append_a_second_solved_block(database_url: str, tenant_id: TenantId) -> None:
    """Move the plan of record on, the way the maintainer or a concurrent adoption moves it.

    No route writes a plan, so this is the same device the concession route suite uses to give its
    week a block a solve placed. What it stands for here is any writer at all: the next solve then
    has something to propose removing, which is what puts its answer in the slot rather than
    nowhere.
    """
    placed = a_block(
        Origin.HABIT,
        week=WEEK,
        interval=Interval(
            datetime.fromisoformat(instant(days=MOVED_ON_DAY, hours=PLACED_FROM_HOUR)),
            datetime.fromisoformat(instant(days=MOVED_ON_DAY, hours=PLACED_FROM_HOUR + 1)),
        ),
    )
    assert is_placed_by_the_solver(placed.origin), "the block has to be one a solve placed"

    async def append() -> None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                await PlanRepository(session, tenant_id).append(
                    document=stored_document(a_document(week=WEEK, blocks=(placed,))),
                    objective_breakdown={},
                    status="applied",
                    reason="auto_applied_fill",
                    weight_set_version=1,
                    input_version=1,
                    created_at=datetime.now(UTC),
                )
        finally:
            await database.engine.dispose()

    run(append())


def a_breach_of_the_floor(
    http: TestClient, headers: dict[str, str], area_id: str
) -> tuple[int, dict[str, Any]]:
    return request_tradeoff(
        http, headers, kind=AdjustmentKind.BREACH_FLOOR.value, target_id=area_id
    )


def approve(http: TestClient, headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
    answered = http.post(APPROVE, headers={**headers, "Idempotency-Key": uuid4().hex})
    return answered.status_code, answered.json()


def history(http: TestClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    answered = http.get(REVISIONS, headers=headers)
    assert answered.status_code == HTTPStatus.OK, answered.text
    listed: list[dict[str, Any]] = answered.json()["revisions"]
    return listed


def test_the_shipped_routes_produce_a_revision_reporting_a_replaced_concession(
    http: TestClient,
    owner: UserRecord,
    live_database_url: str,
    a_short_solved_week: tuple[dict[str, str], str],
) -> None:
    """The producer of `replacedAdjustments`, driven end to end rather than argued.

    Every step is a request except the two the product does not expose: the worker's tick, and the
    plan of record moving. The assertion is over the response of `GET .../revisions`, so what is
    measured is the figure a client reads.
    """
    headers, area_id = a_short_solved_week
    seed_a_weight_set(live_database_url, owner.tenant_id)

    first, body = a_breach_of_the_floor(http, headers, area_id)
    assert first == HTTPStatus.ACCEPTED, body
    assert drain_until_the_slot_fills(live_database_url, owner.tenant_id), (
        "the first candidate-carrying solve did not propose"
    )
    # The concession table is still empty, so nothing suppresses a second offer for the same kind
    # and target. This is the sentence the concession table's own comment used to deny.
    assert stored_concessions(live_database_url, owner.tenant_id) == []
    second, again = a_breach_of_the_floor(http, headers, area_id)
    assert second == HTTPStatus.ACCEPTED, again

    approved, granted = approve(http, headers)
    assert approved == HTTPStatus.CREATED, granted
    held = stored_concessions(live_database_url, owner.tenant_id)
    assert len(held) == 1
    inserted = held[0].id
    assert str(inserted) == granted["adjustment"]["id"]

    append_a_second_solved_block(live_database_url, owner.tenant_id)
    assert drain_until_the_slot_fills(live_database_url, owner.tenant_id), (
        "the second candidate-carrying solve did not propose"
    )
    replaced, second_body = approve(http, headers)
    assert replaced == HTTPStatus.CREATED, second_body

    # The row kept the FIRST candidate's identifier and took the second's figures, which is what
    # leaves the second revision naming an identifier nothing holds.
    after = stored_concessions(live_database_url, owner.tenant_id)
    assert [one.id for one in after] == [inserted]
    assert second_body["adjustment"]["id"] == str(inserted)

    listed = history(http, headers)
    replacing = listed[0]
    assert replacing["reason"] == "tradeoff_approved"
    assert (replacing["revokedAdjustments"], replacing["replacedAdjustments"]) == (0, 1)
    assert [one["id"] for one in replacing["adjustments"]] == [str(inserted)]
    granting = next(one for one in listed if one["id"] == granted["revisionId"])
    assert (granting["revokedAdjustments"], granting["replacedAdjustments"]) == (0, 0)
    assert [one["id"] for one in granting["adjustments"]] == [str(inserted)]


def test_without_the_plan_of_record_moving_the_second_solve_proposes_nothing_to_approve(
    http: TestClient,
    owner: UserRecord,
    live_database_url: str,
    a_short_solved_week: tuple[dict[str, str], str],
) -> None:
    """Why the sequence above needs the plan of record to move, measured rather than asserted.

    The first approval makes the first solve's own document the plan of record. The second solve
    then produces that same document -- the compounded concession changes no placement on this
    week, whose gap is exactly what one breach recovers -- so its classification is empty, it writes
    nothing, the slot stays empty, and there is no second proposal to approve. No revision reports a
    replacement, and the count is right to say so: nothing was replaced.
    """
    headers, area_id = a_short_solved_week
    seed_a_weight_set(live_database_url, owner.tenant_id)

    first, body = a_breach_of_the_floor(http, headers, area_id)
    assert first == HTTPStatus.ACCEPTED, body
    assert drain_until_the_slot_fills(live_database_url, owner.tenant_id)
    second, again = a_breach_of_the_floor(http, headers, area_id)
    assert second == HTTPStatus.ACCEPTED, again
    approved, granted = approve(http, headers)
    assert approved == HTTPStatus.CREATED, granted

    # The plan of record is NOT moved here, which is the only difference from the case above.
    assert drain_until_the_slot_fills(live_database_url, owner.tenant_id) is False
    refused, detail = approve(http, headers)

    assert refused == HTTPStatus.CONFLICT, detail
    assert len(stored_concessions(live_database_url, owner.tenant_id)) == 1
    listed = history(http, headers)
    assert [(one["revokedAdjustments"], one["replacedAdjustments"]) for one in listed] == [
        (0, 0) for _ in listed
    ]
