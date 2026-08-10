"""Who may record a verdict transition, who does, and the one surface that still cannot.

``VerdictSurface`` has six members and the corpus they write into is never pruned, so a member with
no producer is a hole in a product metric that nothing detects, and a producer with no member is a
transition nobody can attribute. Four guards, each derived from the thing it is stated over rather
than from a list this file keeps.

**Every surface has a producer, or a stated reason and a guard that expires with it.** The producers
are read out of the source as the set of places a recorder is COMPOSED, because that is where the
surface is bound. One member has no producer today: ``mutation``, because no other mutation computes
a verdict yet. ``cli`` gained one the day a product route began accepting a bearer token: the pin
path binds it, because a pin made by ``syncr block move`` and a pin made by dragging a block are the
same write computed on two different surfaces.

**The guard that said no product route accepts a CLI credential is re-keyed rather than deleted.**
Ticket 43 keyed it on ``require_bearer_principal`` being declared on a route, which was the shape a
CLI route was expected to have. Ticket 1500 settled that question the other way: one dependency
accepts either credential and chooses by what the request presents, so a route serving both declares
``require_client_principal`` and the bearer resolution is reached inside it rather than beside it. A
guard on the old key would have sat green while twelve routes admitted a CLI token, which is the
failure mode this file exists to prevent. So the key is now the function that actually admits one,
and what is asserted is the rule the old guard was standing in for: a package the CLI can reach that
computes a verdict binds the CLI surface. Which routes the CLI reaches is
``tests/test_authorization_boundary.py``'s inventory, read here rather than restated.

**Every production caller of the probe records what it found.** Stated over the packages that call
the probe rather than over a list of services, so a mutation added later that computes a verdict and
records nothing fails here.

**``VE6``: no read path appends one.** The routes are bounded by the response shapes that carry a
verdict rather than by three paths named here, so the weekly-session payload comes under the rule
the moment it exists. Each is driven TWICE against a real week and the transitions are counted
before and after. **The guard bites rather than being armed**: the week read computes a real verdict
and the assertion that it did is beside the count, because zero rows written by a path that computed
nothing is not evidence of anything.

The census's own claim is stated over the PARAMETER each such read takes rather than over the prefix
it sits under, because the weekly-session payload is a review rather than a week route: the earlier
form refused a path the guard could drive perfectly well, which is a bound naming more than the set
it can see.

**The limit of the first three guards, stated because ticket 41 shipped one like it.** They read
NAMES: the surface a call site binds, the method a package calls, the field a response declares. A
recorder composed through a second indirection, a probe reached through an alias, or a read that
computes a verdict and returns it under another name would escape them. What they catch is the
ordinary way this goes wrong, which is a new caller written in the shape of the existing ones.
"""

from __future__ import annotations

import ast
import re
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, NamedTuple, get_type_hints
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
from syncr_api.plans.assembler import AssemblyCaller
from syncr_api.plans.facts import VerdictEvent
from syncr_api.plans.injection import build_week_assembler
from syncr_api.plans.surfaces import VerdictSurface
from syncr_api.plans.verdicts import ProbeCaller, WeekProbe
from syncr_api.reviews.config import REVIEWS_PREFIX, SESSION_PATH
from syncr_api.worker.main import WorkerContext
from tests.boundaries import METHODS_WITHOUT_A_BODY, RouteView, api_routes, read_paths
from tests.live_horizons import LATE_IN_THE_WEEK, THIS_WEEK, Ticking, declare_the_minimum
from tests.live_tenants import PASSWORD, delete_tenant, seed_owner
from tests.test_authorization_boundary import accepts_a_cli_credential

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings

BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]

# The function every caller composes a recorder through, and the two keywords that bind what the row
# it writes will carry. All three are read from the source rather than imported, because what is
# under test is the call sites.
BUILDER = "build_verdict_recorder"
SURFACE_KEYWORD = "surface"
SESSION_STATE_KEYWORD = "session_mode_active"

# Where each surface with a producer is composed, as module paths under the package root. An exact
# mapping rather than a membership check: a producer that moves or disappears has to be a diff a
# reviewer reads, because the corpus these write into is never pruned.
PRODUCERS = {
    VerdictSurface.PIN: {"pins/injection.py"},
    VerdictSurface.CLI: {"pins/injection.py"},
    VerdictSurface.TRADEOFF: {"concessions/injection.py"},
    VerdictSurface.SOLVE: {"solving/dispatch.py"},
    VerdictSurface.MAINTAINER: {"horizon/verdicts.py"},
}

# The one member no production path can reach yet, and why. `mutation` is the surface for any other
# mutation's probe, and no other mutation computes a verdict: the fifteen rows of ticket 40's
# trigger table that bump a version and ask for no solve are ticket 1403's.
WITHOUT_A_PRODUCER = {VerdictSurface.MUTATION}

# The methods a caller computes a verdict through. Read as names because they are the probe's whole
# public surface.
PROBE_METHODS = {"verdict_for", "offered_verdict_for"}

# The field a response shape declares when it carries a verdict to a client. The census below is
# stated over it, so a read added later comes under VE6 without this file naming its path.
VERDICT_FIELD = "verdict"

# The one path parameter a verdict-bearing read may take, which is the value the guard substitutes.
# Ticket 1363 settled the spelling across the week routes and the weekly session takes the same one.
ISO_WEEK_PARAMETER = "iso_week"


# --------------------------------------------------------------------------------
# Every surface has a producer, or a reason that expires
# --------------------------------------------------------------------------------


class Composition(NamedTuple):
    """One recorder composition: the surface it binds, and the session state bound beside it."""

    surface: str
    session_state: str


type Compositions = list[tuple[str, Composition]]


def compositions(source_root: Path) -> Compositions:
    """Every recorder composition in the package, with the module each sits in.

    Derived from the call sites rather than from a registry, because a registry is a thing a new
    caller can forget to join while still writing rows.
    """
    return [
        (str(module.relative_to(source_root)), composed)
        for module in sorted(source_root.rglob("*.py"))
        for node in ast.walk(ast.parse(module.read_text()))
        if (composed := _composition_of(node)) is not None
    ]


def composed_surfaces(source_root: Path) -> dict[str, set[str]]:
    """Which surface each module composes a recorder with."""
    found: dict[str, set[str]] = {}
    for module, composed in compositions(source_root):
        found.setdefault(composed.surface, set()).add(module)
    return found


def _composition_of(node: ast.AST) -> Composition | None:
    """The surface and session state this node binds, if it is a recorder composition."""
    if not isinstance(node, ast.Call) or getattr(node.func, "id", None) != BUILDER:
        return None
    bound = {keyword.arg: keyword.value for keyword in node.keywords}
    surface = bound.get(SURFACE_KEYWORD)
    state = bound.get(SESSION_STATE_KEYWORD)
    if not isinstance(surface, ast.Attribute) or state is None:
        return None
    return Composition(surface.attr, ast.unparse(state))


def test_every_surface_with_a_producer_is_composed_where_this_file_says(source_root: Path) -> None:
    """An exact mapping, so a producer that moves is a diff rather than a silent change."""
    composed = composed_surfaces(source_root)

    assert {surface.name: modules for surface, modules in PRODUCERS.items()} == composed


def test_the_six_members_are_the_producers_plus_the_one_that_has_none() -> None:
    """So a seventh member cannot be added without deciding which of the two lists it joins."""
    assert set(VerdictSurface) == set(PRODUCERS) | WITHOUT_A_PRODUCER


def test_every_cli_reachable_mutation_that_records_a_verdict_binds_the_cli_surface(
    settings: ServiceSettings, source_root: Path
) -> None:
    """The rule ticket 43's expiring guard was standing in for, keyed on what admits a CLI token.

    Derived from two inventories rather than from a name here: the packages owning a route that
    accepts a bearer credential and can change state, and the modules that compose a recorder. Their
    intersection is the set of modules that record a transition for a CLI caller, and each one has
    to bind ``VerdictSurface.CLI``, or a CLI mutation's row lands in the corpus attributed to the
    browser.

    Mutations only, because ``VE6`` says a read appends nothing: a read that computes a verdict to
    render it has no surface to record under, which is why no member names one.

    A CLI mutation added later in a module that records fails here without this file naming it.
    """
    routes = [route for route in api_routes(create_app(settings)) if route.path.startswith("/api")]
    assert routes, "no product route was found, so this asserted nothing"

    changing_state_for_the_cli = {
        _package_of(route)
        for route in routes
        if accepts_a_cli_credential(route) and route.methods - METHODS_WITHOUT_A_BODY
    }
    recorded = {
        module: surfaces
        for module, surfaces in _surfaces_by_module(source_root).items()
        if module.split("/")[0] in changing_state_for_the_cli
    }
    assert recorded, (
        "no module both records a verdict and serves a CLI mutation, so this asserted nothing. "
        "If that is now true, the CLI surface has no producer and belongs in WITHOUT_A_PRODUCER."
    )

    missing = sorted(module for module, surfaces in recorded.items() if "CLI" not in surfaces)

    assert missing == [], (
        f"{missing} record a verdict for a caller that may be the CLI and never bind "
        f"{VerdictSurface.CLI.value}, so a CLI mutation's transition is attributed to a browser."
    )


def _surfaces_by_module(source_root: Path) -> dict[str, set[str]]:
    """The inverse of :data:`PRODUCERS`, read out of the source the same way it is."""
    inverted: dict[str, set[str]] = {}
    for surface, modules in composed_surfaces(source_root).items():
        for module in modules:
            inverted.setdefault(module, set()).add(surface)
    return inverted


def _package_of(route: RouteView) -> str:
    """Which feature package owns a route, read off the module its handler is defined in."""
    return str(route.endpoint.__module__).removeprefix("syncr_api.").split(".")[0]


# --------------------------------------------------------------------------------
# Every caller that computes a verdict records what it found
# --------------------------------------------------------------------------------


def probing_modules(source_root: Path) -> set[str]:
    """Every module with a production call to the probe, read out of the source.

    A module that DEFINES one of the methods is not a caller of it: ``plans/verdicts.py`` is the
    probe's own home and calls ``verdict_for`` from inside ``offered_verdict_for``. The exclusion is
    derived from the definition rather than from that module's name, so moving the probe does not
    quietly widen or narrow this.

    Modules rather than packages, because the plan package now holds both a mutation-free read that
    computes a verdict and the probe that defines the call: a package-level answer could not tell
    the self-call exclusion working from the exclusion having quietly swallowed a real caller.
    """
    found = set()
    for module in sorted(source_root.rglob("*.py")):
        tree = ast.parse(module.read_text())
        if _defined_methods(tree) & PROBE_METHODS:
            continue
        if _called_methods(tree) & PROBE_METHODS:
            found.add(str(module.relative_to(source_root)))
    return found


def probing_packages(source_root: Path) -> set[str]:
    """Every package with a production call to the probe."""
    return {module.split("/")[0] for module in probing_modules(source_root)}


def verdict_reading_packages(settings: ServiceSettings) -> set[str]:
    """The packages that ANSWER a verdict-bearing read, read off the app's own routes.

    ``VE6`` forbids a read from recording a transition, so a package whose only verdict computation
    is on a read cannot appear in the recording set and would otherwise fail the guard below. Which
    packages those are is derived from the routes whose response shape carries a verdict rather than
    named here, so this exemption widens only when a package starts answering such a read.
    """
    bearing = set(verdict_bearing_reads(settings))
    return {
        _package_of(route)
        for route in api_routes(create_app(settings))
        if route.path in bearing and "GET" in route.methods
    }


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


def test_every_package_that_computes_a_verdict_records_the_transition(
    source_root: Path, settings: ServiceSettings
) -> None:
    """``09``'s rule: every mutation or job that computes a verdict writes one on a transition.

    Stated over packages rather than modules because a package computes its verdict in a service and
    composes its recorder in its wiring. A mutation added later that probes and records nothing
    fails here without this file naming it.

    **The exemption is ``VE6`` rather than a list**, and it is the other half of the same rule: a
    read computes a verdict for display and may not record one. Which packages that covers is read
    off the routes, so a package that begins probing on a MUTATION is not exempted by having a read.
    That residual is the price of a package-level unit and it is the one this file's own "limit of
    the first three guards" paragraph names.
    """
    probing = probing_packages(source_root)
    recording = {
        module.split("/")[0]
        for modules in composed_surfaces(source_root).values()
        for module in modules
    }
    assert probing, "no caller of the probe was found, so this asserted nothing"

    assert probing - recording - verdict_reading_packages(settings) == set(), (
        "these compute a verdict, record no transition, and answer no verdict-bearing read: "
        f"{sorted(probing - recording - verdict_reading_packages(settings))}"
    )


def test_the_only_package_exempt_from_recording_is_the_one_that_answers_a_verdict_read(
    settings: ServiceSettings, source_root: Path
) -> None:
    """Named so widening the exemption above is a diff a reviewer reads.

    Both halves are asserted, because an exemption that covered nothing and an exemption that
    covered everything would both leave the guard above green: the set that does any work is exactly
    the plan package, and the plan package really is a probe caller that records nothing.

    **Two packages answer a verdict-bearing read and only one of them is exempted**, which is not an
    inconsistency: ``reviews`` answers the weekly session's payload and calls the probe NOWHERE. It
    reaches the plan package's own composed read, which is what makes the verdict on the session and
    the verdict on the Week screen one computation rather than two that agree today. A package that
    computes nothing needs no exemption from recording what it computed.
    """
    answering = verdict_reading_packages(settings)
    exempt = answering & probing_packages(source_root)

    assert answering == {"plans", "reviews"}
    assert exempt == {"plans"}, "another probe caller now answers a read and was exempted silently"


def test_the_probe_is_not_counted_as_a_caller_of_itself(source_root: Path) -> None:
    """The control on the guard above, and on the one exclusion it makes.

    ``plans/verdicts.py`` calls ``verdict_for`` from inside ``offered_verdict_for``, so a scan that
    read calls alone would report the probe's own home as a caller and the exclusion exists to stop
    it. What it must still see is the real callers, INCLUDING the read in the same package: an
    exclusion keyed on the package rather than on the definition would hide that one.
    """
    probe = source_root / "plans" / "verdicts.py"
    tree = ast.parse(probe.read_text())
    assert _called_methods(tree) & PROBE_METHODS, "the exclusion below now guards nothing"
    assert _defined_methods(tree) & PROBE_METHODS

    modules = probing_modules(source_root)

    assert "plans/verdicts.py" not in modules
    assert "plans/served_verdicts.py" in modules, "the read in the probe's own package was hidden"
    assert {"pins", "concessions", "horizon"} <= probing_packages(source_root), (
        "a real caller was not seen at all"
    )


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


def test_the_reads_that_carry_a_verdict_are_the_four_that_exist(
    settings: ServiceSettings,
) -> None:
    """Named here so the arrival of a fifth is a diff, and so the census below is not empty.

    ``VE6`` names three surfaces: the week view, the verdict refresh, and the weekly-session
    payload. The proposal read is a fourth ROUTE under the same rule and not a fourth surface: it
    answers the verdict the solve that filled the slot produced, which is a stored value rather than
    a computation, and it must still write nothing.
    """
    assert verdict_bearing_reads(settings) == [
        f"{REVIEWS_PREFIX}{SESSION_PATH}",
        f"{WEEKS_PREFIX}/{{iso_week}}",
        f"{WEEKS_PREFIX}/{{iso_week}}/proposal",
        f"{WEEKS_PREFIX}/{{iso_week}}/verdict",
    ]


def test_every_verdict_bearing_read_is_driven_by_a_week_the_guard_can_supply(
    settings: ServiceSettings,
) -> None:
    """The census: each such read is a parameterized read addressed by a week and nothing else.

    That is the set the guard below drives, because driving one substitutes a week identifier into
    its path. A verdict-bearing read taking any other parameter would need a value invented for it
    and would not be driven by anything, so it fails here rather than being inherited unguarded.

    **Stated over the parameter rather than over a prefix**, and the difference is the
    weekly-session payload: it is a review rather than a week route, so it sits under ``/reviews``
    and the earlier form of this claim would have refused it while the guard could drive it
    perfectly well. A bound that names more than the set it can see is worse than a stated gap,
    because a reader who trusts the sentence stops looking.
    """
    driven = set(read_paths(create_app(settings), parameterized=True))

    for path in verdict_bearing_reads(settings):
        assert path in driven, path
        assert _parameters_of(path) == {ISO_WEEK_PARAMETER}, path


def _parameters_of(path: str) -> set[str]:
    """Every path parameter this route declares, by the name the route template spells."""
    return set(re.findall(r"\{([^}]+)\}", path))


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
    """``VE6``, driven twice, and it now bites rather than being armed.

    Two of the three reads compute a real verdict and the week is impossible at this instant, so
    each finds a gap a transition recorder would write a row for. The proposal read answers 404
    here, because a materialized week holds no proposal, and it is driven anyway: the set is bounded
    by the response shapes that carry a verdict, so a read arrives covered rather than being
    remembered.

    Twice, because a read that wrote on the first call and not the second would pass a one-call
    guard: the recorder writes only on a TRANSITION, so a read that recorded would write one row and
    then be quiet, which counting once after one call cannot tell from writing none.
    """
    await a_planned_week(sessions, owner, context)
    headers = sign_in(http, owner.email)
    paths = verdict_bearing_reads(settings)

    for _ in range(2):
        for path in paths:
            answered = http.get(path.replace("{iso_week}", str(THIS_WEEK)), headers=headers)
            assert answered.status_code in {HTTPStatus.OK, HTTPStatus.NOT_FOUND}, (
                path,
                answered.text,
            )

    assert await transitions(sessions, owner) == []
    assert _a_verdict_was_computed(http, headers), (
        "neither read answered a verdict, so this guard is armed rather than biting"
    )


def _a_verdict_was_computed(http: TestClient, headers: dict[str, str]) -> bool:
    """Whether the week read really answered a verdict, which is what makes the count above mean.

    Without this the guard passes on a deployment where every read answers null, which is exactly
    the state it sat in before a read computed one: zero rows written by a path that computed
    nothing is not evidence of anything.
    """
    answered = http.get(f"{WEEKS_PREFIX}/{THIS_WEEK}", headers=headers)
    assert answered.status_code == HTTPStatus.OK, answered.text
    verdict = answered.json()[VERDICT_FIELD]
    return verdict is not None and bool(verdict["shortfalls"])


@pytest.mark.integration
async def test_the_same_week_records_a_row_when_a_mutation_asks_the_same_question(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    http: TestClient,
) -> None:
    """The control on ``VE6``, and the ``tradeoff`` surface and ``VE3`` end to end in one request.

    What separates this from the reads above is that it is a mutation. Both compute a verdict over
    the same week and find the same gaps; this one records the transition and the reads may not. It
    states that the weekly session is open, and the row carries that answer from the header rather
    than from anything this application knows.
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
