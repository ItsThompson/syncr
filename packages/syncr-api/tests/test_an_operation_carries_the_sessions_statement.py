"""A revocation's solve records what the request stated about the weekly session.

The statement a caller makes travels from the act to the row in two hops, and this suite drives
both against a real Postgres and a real request: the ``DELETE`` route resolves the header through
``SessionModeDep`` and hands it to the service, the service asks the coordinator to carry it on
the operation it schedules, and the worker's recorder reads the operation when the flip is written.

What only a real request and a real solve can prove:

*With the header, the episode the withdrawal opens is flagged; without it, it is not.* Both are
read through :mod:`syncr_api.plans.episodes`' own grouping rather than by inspecting a verdict
row, because the metric's unit is the episode and its first row decides: reading rows directly
would pass while the grouping read a confirmation instead of the discovery.

The solver is substituted so the solved verdict is stated rather than computed, exactly as
``test_first_solve_of_a_half_lived_week.py`` substitutes it. Everything around it -- the route,
the wiring, the coordinator, the operation row, the guard, the adoption, the recorder -- is the
production path over a live database.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.concessions.config import WEEKS_PREFIX
from syncr_api.core.app_factory import create_app
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.session_mode import SESSION_MODE_HEADER
from syncr_api.core.settings import DEFAULT_SOLVE_DEBOUNCE_MS, DEV_ALLOWED_ORIGINS
from syncr_api.learned.repository import WeightSetRepository
from syncr_api.plans.adjustments import WeekAdjustmentRepository
from syncr_api.plans.episodes import episodes
from syncr_api.plans.verdict_events import VerdictEventRepository
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.config import SUCCEEDED
from syncr_api.solving.dispatch import SolveDispatch
from syncr_api.solving.injection import build_solve_coordinator, debounce_window
from syncr_domain.feasibility import Provenance, Shortfall, ShortfallKind, Verdict
from syncr_domain.plan import AdjustmentKind
from syncr_domain.weeks import IsoWeek
from syncr_solver.objective import ObjectiveBreakdown
from syncr_solver.solve import SolveResult
from tests.live_tenants import PASSWORD, provision_owner, remove_tenant, run
from tests.plan_documents import a_document

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings
    from syncr_api.plans.episodes import Episode
    from syncr_api.plans.records import WeekAdjustmentRecord
    from syncr_api.solving.records import OperationRecord
    from syncr_domain.identifiers import TenantId

pytestmark = pytest.mark.integration

BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]

# Far enough ahead that the whole week is future capacity whenever this suite runs.
WEEK = IsoWeek.containing(datetime.now(UTC).date() + timedelta(days=60))
MONDAY = WEEK.monday()

# Where the worker's clock stands while it solves: inside the week, before anything has started,
# so the past guard has nothing to refuse in the substituted candidate.
NOW = datetime(MONDAY.year, MONDAY.month, MONDAY.day, 9, 0, tzinfo=UTC)

ADJUSTMENTS = f"{WEEKS_PREFIX}/{WEEK}/adjustments"


class Ticking:
    """A clock a test moves by hand."""

    def __call__(self) -> datetime:
        return NOW


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


def sign_in(http: TestClient, email: str) -> dict[str, str]:
    answered = http.post(
        f"{AUTH_PREFIX}/login",
        json={"email": email, "password": PASSWORD},
        headers={"Origin": BROWSER_ORIGIN},
    )
    assert answered.status_code == HTTPStatus.OK, answered.text
    cookie = answered.headers["set-cookie"]
    token = cookie.split(f"{SESSION_COOKIE_NAME}=", 1)[1].split(";", 1)[0]
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}", "Origin": BROWSER_ORIGIN}


def seeded_concession(database_url: str, tenant_id: TenantId) -> WeekAdjustmentRecord:
    """One approved concession, a version row, and the weights a solve prices under.

    Written through the repositories an approval writes through, because no route approves
    without a proposal, and the withdrawal under test needs only the row the act removes.
    """

    async def write() -> WeekAdjustmentRecord:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                at = datetime.now(UTC)
                await WeekInputVersionRepository(session, tenant_id).bump(WEEK, at=at)
                await WeightSetRepository(session, tenant_id).seed_hand_tuned(at=at)
                return await WeekAdjustmentRepository(session, tenant_id).upsert(
                    iso_week=WEEK,
                    kind=AdjustmentKind.REDUCE_ROUTINE.value,
                    target_id=uuid4(),
                    reductions={WEEK.dates()[2].isoformat(): 20},
                    created_at=at,
                    created_by_operation_id=uuid4(),
                )
        finally:
            await database.engine.dispose()

    return run(write())


def an_infeasible_result(document: Any, at: datetime) -> SolveResult:
    """The substituted solver's answer: the week cannot hold its commitments."""
    return SolveResult(
        document=document,
        objective_breakdown=ObjectiveBreakdown(
            deadline_risk=0.0,
            budget_deviation=0.0,
            time_of_day_misfit=0.0,
            fragmentation=0.0,
            churn=0.0,
            context_switch=0.0,
            staleness=0.0,
        ),
        verdict=Verdict(
            feasible=False,
            provenance=Provenance.SOLVER,
            computed_at=at,
            input_version=1,
            discretionary_minutes=6000,
            shortfalls=(
                Shortfall(
                    kind=ShortfallKind.FLOORS_EXCEED_CAPACITY,
                    minutes=60,
                    against=("Fitness",),
                    honoring=("the week's floors",),
                ),
            ),
        ),
        blocked_log=(),
        iterations=0,
    )


def revoke_then_run_the_scheduled_solve(
    live_database_url: str,
    owner: UserRecord,
    http: TestClient,
    headers: dict[str, str],
    stored_id: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> OperationRecord:
    """The withdrawal through the route, then its solve driven to the write that records."""

    async def drive() -> OperationRecord:
        database = create_database(live_database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                claim = await build_solve_coordinator(
                    session,
                    owner.tenant_id,
                    clock=Ticking(),
                    debounce=debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS),
                ).claim_next()
            assert claim is not None, "the withdrawal scheduled no solve"
            dispatch = SolveDispatch(
                database,
                owner.tenant_id,
                clock=Ticking(),
                debounce=debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS),
            )
            return await dispatch.run(claim, WEEK)
        finally:
            await database.engine.dispose()

    monkeypatch.setattr(
        "syncr_api.solving.dispatch.solve",
        lambda *_args, **_asked: an_infeasible_result(a_document(week=WEEK), NOW),
    )

    answered = http.delete(f"{ADJUSTMENTS}/{stored_id}", headers=headers)
    assert answered.status_code == HTTPStatus.NO_CONTENT, answered.text

    return run(drive())


def the_weeks_episodes(database_url: str, tenant_id: TenantId) -> tuple[Episode, ...]:
    """The week's episodes, grouped the way every consumer of the metric groups them."""

    async def read() -> tuple[Episode, ...]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                recorded = await VerdictEventRepository(session, tenant_id).for_week(WEEK)
                return episodes(recorded)
        finally:
            await database.engine.dispose()

    return run(read())


class TestARevocationOpensTheEpisodeItsRequestStated:
    def test_with_the_header_the_episode_is_flagged(
        self,
        live_database_url: str,
        owner: UserRecord,
        http: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        stored = seeded_concession(live_database_url, owner.tenant_id)
        headers = sign_in(http, owner.email) | {SESSION_MODE_HEADER: "true"}

        finished = revoke_then_run_the_scheduled_solve(
            live_database_url, owner, http, headers, stored.id, monkeypatch
        )

        assert finished.status == SUCCEEDED, finished.error_message
        found = the_weeks_episodes(live_database_url, owner.tenant_id)
        assert len(found) == 1, f"expected one episode, found {len(found)}"
        # The FIRST row of the episode is the solve's, and it carries what the DELETE request
        # stated, so the discovery reads as one caught during a weekly session.
        assert found[0].caught_early is True

    def test_without_the_header_the_episode_is_not_flagged(
        self,
        live_database_url: str,
        owner: UserRecord,
        http: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        stored = seeded_concession(live_database_url, owner.tenant_id)
        headers = sign_in(http, owner.email)

        finished = revoke_then_run_the_scheduled_solve(
            live_database_url, owner, http, headers, stored.id, monkeypatch
        )

        assert finished.status == SUCCEEDED, finished.error_message
        found = the_weeks_episodes(live_database_url, owner.tenant_id)
        assert len(found) == 1, f"expected one episode, found {len(found)}"
        assert found[0].caught_early is False
