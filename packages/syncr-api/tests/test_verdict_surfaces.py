"""Who may record a verdict transition, who does, and the one surface that still cannot.

``VerdictSurface`` has six members and the corpus they write into is never pruned, so a member with
no producer is a hole in a product metric that nothing detects, and a producer with no member is a
transition nobody can attribute. Four guards, each derived from the thing it is stated over rather
than from a list this file keeps.

**Every surface has a producer, or a stated reason and a guard that expires with it.** The producers
are read out of the source as the set of places a recorder is COMPOSED, because that is where the
surface is bound. Two members have no producer today: ``mutation``, because no other mutation
computes a verdict yet, and ``cli``, because no product route accepts a CLI credential at all. The
second exemption is asserted rather than asserted-to-be-fine: the day a route accepts a bearer
principal, this file reddens.

**Every production caller of the probe records what it found.** Stated over the packages that call
the probe rather than over a list of services, so a mutation added later that computes a verdict and
records nothing fails here.

**``VE6``: no read path appends one.** The routes are bounded by the response shapes that carry a
verdict rather than by three paths named here, so the weekly-session payload comes under the rule
the moment it exists. Each is driven TWICE against a real week and the transitions are counted
before and after.

**The limit of the first three guards, stated because ticket 41 shipped one like it.** They read
NAMES: the surface a call site binds, the method a package calls, the field a response declares. A
recorder composed through a second indirection, a probe reached through an alias, or a read that
computes a verdict and returns it under another name would escape them. What they catch is the
ordinary way this goes wrong, which is a new caller written in the shape of the existing ones.
"""

from __future__ import annotations

import ast
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, get_type_hints
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import select
from starlette.requests import Request

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.concessions.config import WEEKS_PREFIX
from syncr_api.core.app_factory import create_app
from syncr_api.core.db import (
    create_database,
    create_db_engine,
    create_db_lifespan,
    create_sessionmaker,
)
from syncr_api.core.errors import ValidationFailed
from syncr_api.core.session_mode import SESSION_MODE_HEADER, read_session_mode
from syncr_api.core.settings import (
    DEV_ALLOWED_ORIGINS,
    WORKER_SERVICE,
    EnvSettings,
    build_service_settings,
)
from syncr_api.horizon.runner import PlanHorizonRunner
from syncr_api.oauth.injection import require_bearer_principal
from syncr_api.plans.assembler import AssemblyCaller
from syncr_api.plans.facts import VerdictEvent
from syncr_api.plans.injection import build_week_assembler
from syncr_api.plans.surfaces import VerdictSurface
from syncr_api.plans.verdicts import ProbeCaller, WeekProbe
from syncr_api.worker.main import WorkerContext
from tests.boundaries import api_routes, read_paths, resolved_dependencies
from tests.live_horizons import LATE_IN_THE_WEEK, THIS_WEEK, Ticking, declare_the_minimum
from tests.live_tenants import PASSWORD, delete_tenant, seed_owner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings

BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]

# The function every caller composes a recorder through, and the keyword that binds the surface.
# Both are read from the source rather than imported, because what is under test is the call sites.
BUILDER = "build_verdict_recorder"
SURFACE_KEYWORD = "surface"

# Where each surface with a producer is composed, as module paths under the package root. An exact
# mapping rather than a membership check: a producer that moves or disappears has to be a diff a
# reviewer reads, because the corpus these write into is never pruned.
PRODUCERS = {
    VerdictSurface.PIN: {"pins/injection.py"},
    VerdictSurface.TRADEOFF: {"concessions/injection.py"},
    VerdictSurface.SOLVE: {"solving/dispatch.py"},
    VerdictSurface.MAINTAINER: {"horizon/verdicts.py"},
}

# The two members no production path can reach yet, and why. `mutation` is the surface for any other
# mutation's probe, and no other mutation computes a verdict: the fifteen rows of ticket 40's
# trigger table that bump a version and ask for no solve are ticket 1403's. `cli` cannot be reached
# because no product route accepts a CLI credential; ticket 1500 owns that, and the guard below
# expires with it.
WITHOUT_A_PRODUCER = {VerdictSurface.MUTATION, VerdictSurface.CLI}

# The methods a caller computes a verdict through. Read as names because they are the probe's whole
# public surface.
PROBE_METHODS = {"verdict_for", "offered_verdict_for"}

# The field a response shape declares when it carries a verdict to a client. The census below is
# stated over it, so a read added later comes under VE6 without this file naming its path.
VERDICT_FIELD = "verdict"


# --------------------------------------------------------------------------------
# Every surface has a producer, or a reason that expires
# --------------------------------------------------------------------------------


def composed_surfaces(source_root: Path) -> dict[str, set[str]]:
    """Which surface each module composes a recorder with, read out of the source.

    The mapping is derived from the call sites rather than from a registry, because a registry is a
    thing a new caller can forget to join while still writing rows.
    """
    found: dict[str, set[str]] = {}
    for module in sorted(source_root.rglob("*.py")):
        for call in ast.walk(ast.parse(module.read_text())):
            surface = _surface_of(call)
            if surface is not None:
                found.setdefault(surface, set()).add(str(module.relative_to(source_root)))
    return found


def _surface_of(node: ast.AST) -> str | None:
    """The surface member this node binds, if it is a recorder composition."""
    if not isinstance(node, ast.Call) or getattr(node.func, "id", None) != BUILDER:
        return None
    for keyword in node.keywords:
        if keyword.arg == SURFACE_KEYWORD and isinstance(keyword.value, ast.Attribute):
            return keyword.value.attr
    return None


def test_every_surface_with_a_producer_is_composed_where_this_file_says(source_root: Path) -> None:
    """An exact mapping, so a producer that moves is a diff rather than a silent change."""
    composed = composed_surfaces(source_root)

    assert {surface.name: modules for surface, modules in PRODUCERS.items()} == composed


def test_the_six_members_are_the_producers_plus_the_two_that_have_none() -> None:
    """So a seventh member cannot be added without deciding which of the two lists it joins."""
    assert set(VerdictSurface) == set(PRODUCERS) | WITHOUT_A_PRODUCER


def test_no_product_route_accepts_a_cli_credential(settings: ServiceSettings) -> None:
    """The ``cli`` exemption, asserted rather than assumed, over the app's own dependency trees.

    ``VerdictSurface.CLI`` has no producer because a CLI cannot reach a mutation that computes a
    verdict: every product route resolves a browser session. Ticket 1500 is what changes that, and
    this reddens on the commit that does, which is the point: whoever lets a bearer credential
    through has to wire the surface with it.
    """
    routes = [route for route in api_routes(create_app(settings)) if route.path.startswith("/api")]
    assert routes, "no product route was found, so this asserted nothing"

    reached = {
        route.path for route in routes if require_bearer_principal in resolved_dependencies(route)
    }

    assert reached == set(), (
        "a product route now accepts a CLI credential, so VerdictSurface.CLI has a reachable "
        "caller and needs a recorder bound to it"
    )


# --------------------------------------------------------------------------------
# Every caller that computes a verdict records what it found
# --------------------------------------------------------------------------------


def probing_packages(source_root: Path) -> set[str]:
    """Every package with a production call to the probe, read out of the source.

    A module that DEFINES one of the methods is not a caller of it: ``plans/verdicts.py`` is the
    probe's own home and calls ``verdict_for`` from inside ``offered_verdict_for``. The exclusion is
    derived from the definition rather than from that module's name, so moving the probe does not
    quietly widen or narrow this.
    """
    found = set()
    for module in sorted(source_root.rglob("*.py")):
        tree = ast.parse(module.read_text())
        if _defined_methods(tree) & PROBE_METHODS:
            continue
        if _called_methods(tree) & PROBE_METHODS:
            found.add(module.relative_to(source_root).parts[0])
    return found


def _defined_methods(tree: ast.AST) -> set[str]:
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _called_methods(tree: ast.AST) -> set[str]:
    return {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


def test_every_package_that_computes_a_verdict_records_the_transition(source_root: Path) -> None:
    """``09``'s rule: every mutation or job that computes a verdict writes one on a transition.

    Stated over packages rather than modules because a package computes its verdict in a service and
    composes its recorder in its wiring. A mutation added later that probes and records nothing
    fails here without this file naming it.
    """
    probing = probing_packages(source_root)
    recording = {
        module.split("/")[0]
        for modules in composed_surfaces(source_root).values()
        for module in modules
    }
    assert probing, "no caller of the probe was found, so this asserted nothing"

    assert probing <= recording, (
        f"these compute a verdict and record no transition: {probing - recording}"
    )


def test_the_probe_is_not_counted_as_a_caller_of_itself(source_root: Path) -> None:
    """The control on the guard above, and on the one exclusion it makes.

    ``plans/verdicts.py`` calls ``verdict_for`` from inside ``offered_verdict_for``, so a scan that
    read calls alone would report the plan package as a mutation that records nothing, and the guard
    would fail for a reason that is not a defect. What it must still see is the real callers.
    """
    probe = source_root / "plans" / "verdicts.py"
    tree = ast.parse(probe.read_text())
    assert _called_methods(tree) & PROBE_METHODS, "the exclusion below now guards nothing"
    assert _defined_methods(tree) & PROBE_METHODS

    packages = probing_packages(source_root)

    assert "plans" not in packages
    assert {"pins", "concessions", "horizon"} <= packages, "a real caller was not seen at all"


# --------------------------------------------------------------------------------
# VE6: no read path appends one
# --------------------------------------------------------------------------------


def verdict_bearing_reads(settings: ServiceSettings) -> list[str]:
    """Every GET path whose response shape carries a verdict to a client.

    Derived from the response models rather than from the three paths ``VE6`` names, so the
    weekly-session payload comes under the rule when it ships rather than when someone remembers.
    """
    paths = []
    for route in api_routes(create_app(settings)):
        if "GET" not in route.methods:
            continue
        answered = get_type_hints(route.endpoint).get("return")
        if (
            isinstance(answered, type)
            and issubclass(answered, BaseModel)
            and VERDICT_FIELD in answered.model_fields
        ):
            paths.append(route.path)
    return sorted(paths)


def test_the_reads_that_carry_a_verdict_are_the_two_that_exist(settings: ServiceSettings) -> None:
    """Named here so the arrival of a third is a diff, and so the census below is not empty.

    ``VE6`` names three: the week view, the verdict refresh, and the weekly-session payload. The
    third is ticket 51's and does not exist yet, which is why this asserts two rather than three.
    """
    assert verdict_bearing_reads(settings) == [
        f"{WEEKS_PREFIX}/{{iso_week}}",
        f"{WEEKS_PREFIX}/{{iso_week}}/verdict",
    ]


def test_every_verdict_bearing_read_is_covered_by_the_week_prefix_guard(
    settings: ServiceSettings,
) -> None:
    """The census: each such read is a parameterized week read, which is the set the guard drives.

    A verdict-bearing read outside the week prefix would need a value invented for its own parameter
    and would not be driven by anything, so it fails here rather than being inherited unguarded.
    """
    driven = set(read_paths(create_app(settings), parameterized=True))

    for path in verdict_bearing_reads(settings):
        assert path in driven, path
        assert path.startswith(WEEKS_PREFIX), path


# --------------------------------------------------------------------------------
# VE6 and VE3 against a real week: the reads, and the header a mutation states
# --------------------------------------------------------------------------------


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
async def context(live_database_url: str) -> AsyncIterator[WorkerContext]:
    worker = build_service_settings(service=WORKER_SERVICE, env=EnvSettings(_env_file=None))
    database = create_database(live_database_url)
    yield WorkerContext(settings=worker, database=database)
    await database.engine.dispose()


@pytest.fixture
def http(live_database_url: str, settings: ServiceSettings) -> Iterator[TestClient]:
    database = create_database(live_database_url)
    app = create_app(settings, lifespan=create_db_lifespan(database.engine))
    app.state.db = database
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


async def a_planned_week(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, context: WorkerContext
) -> None:
    """A week with a live plan and NO verdict transitions, which is duty 1 without duty 2.

    Duty 1 alone, deliberately: a tick that ran duty 2 would record the week's first transition and
    every assertion below about a first row would then be about the second.
    """
    await declare_the_minimum(sessions, owner.tenant_id)
    clock = Ticking(LATE_IN_THE_WEEK)
    await PlanHorizonRunner(clock=clock).plan(context, now=LATE_IN_THE_WEEK)


async def transitions(sessions: async_sessionmaker[AsyncSession], owner: UserRecord) -> list[Any]:
    async with sessions() as session:
        found = await session.scalars(
            select(VerdictEvent).where(VerdictEvent.tenant_id == owner.tenant_id)
        )
        return list(found)


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


@pytest.mark.integration
async def test_no_verdict_bearing_read_appends_a_row_however_often_it_is_driven(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    http: TestClient,
    settings: ServiceSettings,
) -> None:
    """``VE6``, driven twice, and **armed rather than proven** in this deployment.

    Neither read computes a verdict yet: both response shapes declare ``verdict: None`` and say so,
    and the service parses the week and answers ``None``. So this cannot fail today, and what it is
    for is the commit that makes it able to: the driven set is bounded by the response shapes that
    carry a verdict, so the read that starts computing one and the weekly-session payload arrive
    already covered.

    The week is impossible at this instant, so once a verdict IS computed here each read finds one a
    transition recorder would write a row for. Twice, because a read that wrote on the first call
    and not the second would pass a one-call guard.
    """
    await a_planned_week(sessions, owner, context)
    headers = sign_in(http, owner.email)
    paths = verdict_bearing_reads(settings)

    for _ in range(2):
        for path in paths:
            answered = http.get(path.replace("{iso_week}", str(THIS_WEEK)), headers=headers)
            assert answered.status_code == HTTPStatus.OK, (path, answered.text)

    assert await transitions(sessions, owner) == []


@pytest.mark.integration
async def test_the_same_week_records_a_row_when_a_mutation_asks_the_same_question(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    http: TestClient,
) -> None:
    """The control on ``VE6``, and the ``tradeoff`` surface and ``VE3`` end to end in one request.

    What separates this from the reads above is that it is a mutation: the reads compute no verdict
    in this deployment, and this path does. It states that the weekly session is open, and the row
    carries that answer from the header rather than from anything this application knows.
    """
    await a_planned_week(sessions, owner, context)
    headers = sign_in(http, owner.email)
    breach = await _a_breach_the_week_offers(sessions, owner)

    answered = http.post(
        f"{WEEKS_PREFIX}/{THIS_WEEK}/tradeoffs",
        json=breach,
        headers={**headers, SESSION_MODE_HEADER: "true"},
    )

    assert answered.status_code == HTTPStatus.ACCEPTED, answered.text
    (one,) = await transitions(sessions, owner)
    assert one.surface == VerdictSurface.TRADEOFF.value
    assert one.feasible is False
    assert one.session_mode_active is True, "the header the client stated did not reach the row"


@pytest.mark.integration
async def test_a_mutation_that_states_no_session_records_that_it_was_not_open(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    http: TestClient,
) -> None:
    """An absent header is false, which is what every caller with no session concept is.

    The pair with the test above is the whole of ``VE3`` on this surface: the row carries what the
    caller stated, and neither answer is the one this application chose.
    """
    await a_planned_week(sessions, owner, context)
    headers = sign_in(http, owner.email)
    breach = await _a_breach_the_week_offers(sessions, owner)

    answered = http.post(f"{WEEKS_PREFIX}/{THIS_WEEK}/tradeoffs", json=breach, headers=headers)

    assert answered.status_code == HTTPStatus.ACCEPTED, answered.text
    (one,) = await transitions(sessions, owner)
    assert one.session_mode_active is False


@pytest.mark.integration
async def test_a_session_mode_header_this_deployment_cannot_read_is_refused(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    http: TestClient,
) -> None:
    """Refused rather than read as false, and nothing is changed.

    A client with a typo would otherwise have every transition it caused recorded as a miss, and the
    early-catch metric would report a number worse than the truth with nothing anywhere saying why.
    """
    await a_planned_week(sessions, owner, context)
    headers = sign_in(http, owner.email)
    breach = await _a_breach_the_week_offers(sessions, owner)

    answered = http.post(
        f"{WEEKS_PREFIX}/{THIS_WEEK}/tradeoffs",
        json=breach,
        headers={**headers, SESSION_MODE_HEADER: "yes please"},
    )

    assert answered.status_code == ValidationFailed.status, answered.text
    assert SESSION_MODE_HEADER in answered.text
    assert await transitions(sessions, owner) == []


@pytest.mark.integration
async def test_a_read_is_not_refused_for_a_header_it_has_no_use_for(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    http: TestClient,
) -> None:
    """The refusal above belongs to the path that computes a verdict, and to no other.

    Its message says nothing was changed, which is true of a mutation and meaningless on a ``GET``.
    The concession routes share a service, so a header read in one composition would refuse the read
    that lists a week's concessions for a value that read cannot use.
    """
    await a_planned_week(sessions, owner, context)
    headers = sign_in(http, owner.email)
    listing = f"{WEEKS_PREFIX}/{THIS_WEEK}/adjustments"

    clean = http.get(listing, headers=headers)
    with_a_bad_header = http.get(listing, headers={**headers, SESSION_MODE_HEADER: "yes please"})

    assert clean.status_code == HTTPStatus.OK, clean.text
    assert with_a_bad_header.status_code == HTTPStatus.OK, with_a_bad_header.text
    assert with_a_bad_header.json() == clean.json()


@pytest.mark.integration
async def test_a_tradeoff_refused_after_the_record_leaves_no_row(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    http: TestClient,
) -> None:
    """``VE5`` on the one path that records before it refuses.

    The request records the verdict beside the probe that found it and then refuses a concession the
    week does not offer, so the 422 has to take the row with it. The control is the same week
    answering 202 for the concession it does offer and keeping exactly one row: without it, a guard
    counting zero rows could be measuring a path that never records at all.
    """
    await a_planned_week(sessions, owner, context)
    headers = sign_in(http, owner.email)
    offered = await _a_breach_the_week_offers(sessions, owner)
    not_offered = {**offered, "targetId": str(uuid4())}

    refused = http.post(f"{WEEKS_PREFIX}/{THIS_WEEK}/tradeoffs", json=not_offered, headers=headers)

    assert refused.status_code == ValidationFailed.status, refused.text
    assert await transitions(sessions, owner) == []

    accepted = http.post(f"{WEEKS_PREFIX}/{THIS_WEEK}/tradeoffs", json=offered, headers=headers)

    assert accepted.status_code == HTTPStatus.ACCEPTED, accepted.text
    assert len(await transitions(sessions, owner)) == 1


@pytest.mark.parametrize(
    ("stated", "reading"),
    [(None, False), ("true", True), ("TRUE", True), ("1", True), ("false", False), ("0", False)],
)
def test_the_header_reads_what_a_client_can_state(stated: str | None, reading: bool) -> None:
    """The four accepted spellings and the absent case, without a request behind them."""
    headers = {} if stated is None else {SESSION_MODE_HEADER: stated}

    assert read_session_mode(_a_request(headers)) is reading


def test_the_header_refuses_a_value_it_cannot_read() -> None:
    with pytest.raises(ValidationFailed, match=SESSION_MODE_HEADER):
        read_session_mode(_a_request({SESSION_MODE_HEADER: "maybe"}))


def _a_request(headers: dict[str, str]) -> Request:
    """A real request object over a minimal ASGI scope, so no header reading is faked."""
    raw = [(key.lower().encode(), value.encode()) for key, value in headers.items()]
    return Request({"type": "http", "method": "POST", "path": "/", "headers": raw})


async def _a_breach_the_week_offers(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> dict[str, str]:
    """The concession this week actually offers, read from the enumerator that offers it.

    Taken from production code rather than constructed, because a request naming a concession syncr
    did not offer is refused: the offer is where the figures come from.
    """
    async with sessions() as session:
        inputs = await build_week_assembler(
            session, owner.tenant_id, caller=AssemblyCaller.REQUEST
        ).assemble(THIS_WEEK, LATE_IN_THE_WEEK)
    offered = WeekProbe(caller=ProbeCaller.REQUEST).offered_verdict_for(inputs)
    assert offered.offers, "the week offers no concession, so no tradeoff request could be made"
    first = offered.offers[0]
    return {"kind": first.tradeoff.kind.value, "targetId": str(first.tradeoff.target_id)}
