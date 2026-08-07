"""The authorization boundary: three rules that rot silently, asserted mechanically.

Authorization is enforced in the service layer, on an explicit principal, and this file
is what keeps that true as routes accumulate. It is not a test of the three routes that
exist today: it examines whatever routes exist whenever it runs, which is the only form
of this test that still works in a year.

Each rule is checked twice: once against the real application, and once against a
synthetic input that breaks it. The second half is the important one. A rule whose test
cannot fail is indistinguishable from a rule nobody is enforcing, and the failure mode is
silent.

The four rules:

1. Every route resolves a principal, except the ones named below.
2. Every service method takes that principal FIRST, so authorizing is not optional.
3. No route module can reach persistence, so it has no way to skip the service layer.
4. No route module checks a scope, so authorization is decided in one place per request.

A fifth census sits beside them, because two credential kinds now reach this api. Which routes
serve the CLI's bearer token as well as the browser's cookie is an inventory here, asserted
exactly and in both directions, so widening the CLI's reach is a diff a reviewer reads.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, Annotated, TypeGuard

import pytest
from fastapi import Depends, FastAPI

from syncr_api.accounts.config import AUTH_PREFIX
from syncr_api.accounts.injection import (
    ClientPrincipalDep,
    PrincipalDep,
    require_client_principal,
    require_principal,
    require_trusted_origin,
)
from syncr_api.accounts.service import SessionDescription, SessionService
from syncr_api.approvals.config import APPROVE_PATH
from syncr_api.areas.config import AREAS_PREFIX
from syncr_api.concessions.config import WEEKS_PREFIX
from syncr_api.core.observability import METRICS_ENDPOINT
from syncr_api.core.principal import require_scope
from syncr_api.oauth.config import (
    JWKS_PATH,
    OAUTH_PREFIX,
    REVOKE_PATH,
    TOKEN_PATH,
    WELL_KNOWN_PREFIX,
)
from syncr_api.oauth.metadata import DISCOVERY_PATH
from syncr_api.outcomes.config import (
    BLOCKS_PREFIX,
    CONFIRM_PATH,
    DAY_PATH,
    DAYS_PREFIX,
    OUTCOME_PATH,
)
from syncr_api.pins.config import PINS_PATH
from syncr_api.plans.week_config import SOLVE_PATH, WEEK_PATH
from syncr_api.solving.config import OPERATION_PATH, OPERATIONS_PREFIX
from syncr_api.tasks.config import TASK_COMPLETE_PATH, TASKS_PREFIX
from syncr_common.health import HEALTHZ_ENDPOINT, READYZ_ENDPOINT
from tests.boundaries import (
    METHODS_WITHOUT_A_BODY,
    RouteView,
    api_routes,
    imported_modules,
    principal_position,
    public_methods,
    resolved_dependencies,
    route_identity,
    service_calls,
    service_classes,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


# The routes that deliberately resolve no principal, each for a stated reason:
#
#   POST /auth/login   is what PRODUCES a principal. Requiring one would make signing
#                      in possible only while already signed in.
#   POST /oauth/token  is the same thing for the CLI's credential: it exchanges an
#                      authorization code or a refresh token FOR a principal. The
#                      credential is in the body and is verified there, and the code is
#                      single-use, so what protects it is not an ambient session.
#   POST /oauth/revoke takes the refresh token being revoked as its subject. A client whose
#                      token is the only thing it still holds must be able to end it, and
#                      RFC 7009 answers identically whatever is presented, so there is
#                      nothing a principal would gate.
#   /.well-known/*     are read by a client BEFORE it has a credential: the discovery
#                      document is how it finds the token endpoint, and the JWKS is public
#                      key material published for verifiers. Neither discloses anything
#                      about a plan or an account.
#   /healthz /readyz   are read by Docker's healthcheck, by the deploy gate, and by an
#                      external probe, none of which holds a credential. Neither
#                      discloses anything about the plan.
#   /metrics           is read by Prometheus over the internal network and is not
#                      published through the tunnel.
#
# Adding an entry here is adding a hole in the perimeter. That is the point of keeping
# the list in the file named for the boundary: it cannot be done without editing this
# test, which is a diff a reviewer reads as what it is.
UNAUTHENTICATED_ROUTES = frozenset(
    {
        ("POST", f"{AUTH_PREFIX}/login"),
        ("POST", f"{OAUTH_PREFIX}{TOKEN_PATH}"),
        ("POST", f"{OAUTH_PREFIX}{REVOKE_PATH}"),
        ("GET", DISCOVERY_PATH),
        ("GET", f"{WELL_KNOWN_PREFIX}{JWKS_PATH}"),
        ("GET", HEALTHZ_ENDPOINT),
        ("GET", READYZ_ENDPOINT),
        ("GET", METRICS_ENDPOINT),
    }
)

# The unsafe routes that deliberately carry no origin check, and why the check does not apply.
#
# The origin check is the half of CSRF protection that `SameSite=Lax` does not cover, and CSRF
# exists because a cookie is AMBIENT: a browser attaches it to a forged cross-origin request as
# readily as to a real one. These two routes read no cookie. Their credential is a code or a
# refresh token carried in the request body, which a hostile page cannot obtain, so a forged
# request from one carries nothing and achieves nothing.
#
# Requiring the check here would instead break every legitimate caller: the CLI is not a browser
# and sends no `Origin` header at all, so the token endpoint would answer 403 to the only client
# that exists.
ROUTES_WITHOUT_AN_ORIGIN_CHECK = frozenset(
    {
        ("POST", f"{OAUTH_PREFIX}{TOKEN_PATH}"),
        ("POST", f"{OAUTH_PREFIX}{REVOKE_PATH}"),
    }
)

# The routes that serve the CLI's bearer token as well as the browser's cookie, which is section
# 17's command catalog and nothing else. Each one is here because a shipped command needs it:
#
#   GET  /areas                    `week show` names the Area on every row
#   GET  /tasks                    `task list` and `backlog list`
#   POST /tasks                    `task add`
#   POST /tasks/{id}/complete      `task done`
#   GET  /operations/{id}          `plan solve --wait` polls this to a terminal status
#   GET  /weeks/{isoWeek}          `week show`, `plan show`, and the summary a wait prints
#   POST /weeks/{isoWeek}/solve    `plan solve`
#   PUT  /blocks/{id}/outcome      `block done`, `block skip`, `block partial`
#   GET  /days/{date}              `plan show --date`
#   POST /days/{date}/confirm      `day confirm`
#   POST /weeks/{isoWeek}/pins     `block move`
#   POST /weeks/{isoWeek}/approve  `plan approve`
#
# Enumerated rather than granted by prefix or by scope. `admin` already guards calendar setup,
# template editing and the pie review in the service layer, and the CLI never requests it, but a
# route added to one of those modules that needed only `plan:read` would then be reachable by a
# stolen CLI token without anyone deciding that. So the default is closed and this list is the
# whole of the exception, in a file whose diff a reviewer reads as what it is.
CLI_ROUTES = frozenset(
    {
        ("GET", AREAS_PREFIX),
        ("GET", TASKS_PREFIX),
        ("POST", TASKS_PREFIX),
        ("POST", f"{TASKS_PREFIX}{TASK_COMPLETE_PATH}"),
        ("GET", f"{OPERATIONS_PREFIX}{OPERATION_PATH}"),
        ("GET", f"{WEEKS_PREFIX}{WEEK_PATH}"),
        ("POST", f"{WEEKS_PREFIX}{SOLVE_PATH}"),
        ("PUT", f"{BLOCKS_PREFIX}{OUTCOME_PATH}"),
        ("GET", f"{DAYS_PREFIX}{DAY_PATH}"),
        ("POST", f"{DAYS_PREFIX}{CONFIRM_PATH}"),
        ("POST", f"{WEEKS_PREFIX}{PINS_PATH}"),
        ("POST", f"{WEEKS_PREFIX}{APPROVE_PATH}"),
    }
)

# What a route module must not be able to reach. Anything here would let a handler read
# or write rows without passing through a service method, which is where authorization
# lives.
FORBIDDEN_IN_A_ROUTE_MODULE = frozenset(
    {
        "sqlalchemy",
        "sqlalchemy.orm",
        "sqlalchemy.ext.asyncio",
        "syncr_api.core.db",
        "syncr_api.core.orm",
        "syncr_api.core.repository",
    }
)

# The sibling modules of a feature package that a route module must not import. The
# per-module file set is fixed by convention, so this is enumerable: a route may reach
# its schemas, its dependencies, its config, and its service, and nothing lower.
FORBIDDEN_SIBLINGS = frozenset({"models", "repository", "provisioning"})

ROUTE_MODULE_NAME = "api.py"

# The scope check's own name, read off the function so a rename keeps the rule working. A route
# module must not reference it at all: a scope checked in a route is a second place a request's
# authority is decided, and the check inside the service method then becomes something a reader
# has to go and confirm rather than the whole answer.
SCOPE_CHECK = require_scope.__name__


def authenticated_routes(app: FastAPI) -> list[tuple[str, str, Callable[..., object]]]:
    """Every ``(method, path, endpoint)`` that is required to resolve a principal."""
    found: list[tuple[str, str, Callable[..., object]]] = []
    for route in api_routes(app):
        for method, path in sorted(route_identity(route)):
            if (method, path) not in UNAUTHENTICATED_ROUTES:
                found.append((method, path, route.endpoint))
    return found


def resolves_a_principal(route: RouteView) -> bool:
    """Whether this route resolves a principal at all, by either perimeter.

    Two perimeters, one answer: ``require_principal`` is the browser-only one and
    ``require_client_principal`` accepts either credential. A route declaring the first resolves the
    second as its sub-dependency, so a route with neither declared is a route with no credential.
    """
    resolved = resolved_dependencies(route)
    return require_principal in resolved or require_client_principal in resolved


def accepts_a_cli_credential(route: RouteView) -> bool:
    """Whether a bearer token reaches this route.

    Read off the dependency tree rather than from a list, and it takes both halves to answer.
    ``require_client_principal`` is resolved by every route that reaches a shared service or the
    idempotency guard, because those are wired for either caller; what distinguishes a route the CLI
    can use is that it does NOT also declare ``require_principal``, which is the same resolution
    with a bearer credential refused.
    """
    resolved = resolved_dependencies(route)
    return require_client_principal in resolved and require_principal not in resolved


def test_the_application_has_routes_that_this_file_examines(app: FastAPI) -> None:
    # Every assertion below iterates over routes, so all of them pass vacuously on an
    # app with none. This is the control for the other route tests' subject matter.
    assert authenticated_routes(app), "no authenticated route was found to examine"


def test_every_route_resolves_a_principal_or_is_named_as_not_needing_one(
    app: FastAPI,
) -> None:
    unguarded = [
        f"{method} {path}"
        for route in api_routes(app)
        for method, path in sorted(route_identity(route))
        if (method, path) not in UNAUTHENTICATED_ROUTES and not resolves_a_principal(route)
    ]

    assert unguarded == [], (
        f"{unguarded} resolve no principal. Declare `PrincipalDep` on the handler, "
        "`ClientPrincipalDep` and an entry in CLI_ROUTES if the CLI needs it, or "
        "add the route to UNAUTHENTICATED_ROUTES with a reason if it genuinely needs "
        "no credential."
    )


def test_the_routes_serving_the_cli_are_exactly_the_ones_named_here(app: FastAPI) -> None:
    # Both directions in one assertion. A route that starts accepting a bearer token without being
    # named here fails, and a name here whose route stopped accepting one fails too, so a stale
    # entry cannot outlive the route it was written for.
    reached = {
        (method, path)
        for route in api_routes(app)
        for method, path in sorted(route_identity(route))
        if accepts_a_cli_credential(route)
    }

    assert reached == CLI_ROUTES


def test_every_route_maps_to_a_service_method_taking_a_principal(app: FastAPI) -> None:
    failures = []
    for method, path, endpoint in authenticated_routes(app):
        calls = service_calls(endpoint)
        if not calls:
            failures.append(f"{method} {path} calls no service method")
            continue
        failures.extend(
            f"{method} {path}: {reason}"
            for service_class, method_name in sorted(calls, key=lambda call: call[1])
            if (reason := principal_position(service_class, method_name)) is not None
        )

    assert failures == [], (
        f"{failures}. A route delegates to exactly one service method, and every "
        "service method takes the principal it must authorize as its first argument."
    )


def test_every_public_service_method_takes_a_principal_first(source_root: Path) -> None:
    # Stated over every service class the package defines, discovered by walking
    # `*/service.py`, so a method added ahead of its route is covered and a service class
    # a later feature module adds needs no edit here.
    discovered = service_classes(source_root)
    assert discovered, f"no service class was found under {source_root}"

    failures = [
        reason
        for service_class in discovered
        for name in public_methods(service_class)
        if (reason := principal_position(service_class, name)) is not None
    ]

    assert failures == [], f"{failures}"


def test_the_service_class_walk_finds_the_service_this_module_ships(source_root: Path) -> None:
    # The control for the discovery above: a walk that found nothing would leave the rule
    # passing vacuously, and it would keep passing as later modules arrive.
    discovered = service_classes(source_root)

    assert SessionService in discovered
    assert public_methods(SessionService) == ["describe", "log_out"]
    # The value type in the same module is a return shape, not a service.
    assert SessionDescription not in discovered


def test_every_unsafe_route_carries_the_origin_check(app: FastAPI) -> None:
    unguarded = [
        f"{method} {path}"
        for route in api_routes(app)
        for method, path in sorted(route_identity(route))
        if method not in METHODS_WITHOUT_A_BODY
        and (method, path) not in ROUTES_WITHOUT_AN_ORIGIN_CHECK
        and require_trusted_origin not in resolved_dependencies(route)
    ]

    assert unguarded == [], (
        f"{unguarded} can change state without an origin check, which is the half of "
        "CSRF protection that SameSite=Lax does not cover."
    )


def test_the_routes_exempt_from_the_origin_check_read_no_cookie(app: FastAPI) -> None:
    # The exemption is safe only because these routes have no ambient credential to forge. If
    # one of them ever resolves a session, the exemption becomes a CSRF hole rather than a
    # statement about how OAuth clients authenticate, and this is what says so.
    exempt = [
        f"{method} {path}"
        for route in api_routes(app)
        for method, path in sorted(route_identity(route))
        if (method, path) in ROUTES_WITHOUT_AN_ORIGIN_CHECK and resolves_a_principal(route)
    ]

    assert exempt == [], (
        f"{exempt} are exempt from the origin check AND read the session cookie, which is "
        "exactly the combination CSRF protection exists for."
    )


def test_every_exempt_route_actually_exists(app: FastAPI) -> None:
    # A stale exemption is a hole that outlives the route it was written for: it would silently
    # cover whatever later takes that path.
    declared = {
        (method, path)
        for route in api_routes(app)
        for method, path in sorted(route_identity(route))
    }

    assert declared >= ROUTES_WITHOUT_AN_ORIGIN_CHECK
    assert declared >= UNAUTHENTICATED_ROUTES
    assert declared >= CLI_ROUTES


def route_modules(source_root: Path) -> list[Path]:
    """Every feature module's route file."""
    return sorted(source_root.glob(f"*/{ROUTE_MODULE_NAME}"))


def forbidden_reach(source: str) -> list[str]:
    """The persistence-layer imports in a route module's source, if any."""
    imported = imported_modules(source)
    siblings = {name.rsplit(".", 1)[-1] for name in imported}
    return sorted((imported & FORBIDDEN_IN_A_ROUTE_MODULE) | (siblings & FORBIDDEN_SIBLINGS))


def test_no_route_module_can_reach_persistence(source_root: Path) -> None:
    modules = route_modules(source_root)
    assert modules, f"no {ROUTE_MODULE_NAME} was found under {source_root}"

    violations = {
        str(module.relative_to(source_root)): reach
        for module in modules
        if (reach := forbidden_reach(module.read_text(encoding="utf-8")))
    }

    assert violations == {}, (
        f"{violations}. A route validates a body, resolves a principal, and calls one "
        "service method. Reaching a repository from a handler skips the layer that "
        "authorizes."
    )


def scope_check_lines(source: str) -> list[int]:
    """The lines where a route module's source reaches the scope check, if any.

    Imported, called, or reached through the module it lives in: all three are the same
    mistake, so all three are reported.
    """
    return sorted(node.lineno for node in ast.walk(ast.parse(source)) if _reaches_scope_check(node))


def _reaches_scope_check(node: ast.AST) -> TypeGuard[ast.Name | ast.Attribute | ast.alias]:
    if isinstance(node, ast.Name):
        return node.id == SCOPE_CHECK
    if isinstance(node, ast.Attribute):
        return node.attr == SCOPE_CHECK
    if isinstance(node, ast.alias):
        return node.name == SCOPE_CHECK
    return False


def test_no_route_module_checks_a_scope(source_root: Path) -> None:
    modules = route_modules(source_root)
    assert modules, f"no {ROUTE_MODULE_NAME} was found under {source_root}"

    violations = {
        str(module.relative_to(source_root)): lines
        for module in modules
        if (lines := scope_check_lines(module.read_text(encoding="utf-8")))
    }

    assert violations == {}, (
        f"{violations} reach {SCOPE_CHECK} from a route. It is called once, as the first act "
        "of the service method the route delegates to, so the whole authorization decision is "
        "visible in that method."
    )


# --------------------------------------------------------------------------------
# The controls. Each one is a rule broken on purpose, asserting that the check above
# reports it rather than passing.
# --------------------------------------------------------------------------------


class _ServiceWithoutAPrincipal:
    """Stands in for a service method that forgot to take one."""

    async def do_something(self, thing_id: str) -> str:
        return thing_id


# Placed in a module whose name ends in `.service` the same way a real one is, so the
# control exercises the same detection path rather than a special case.
_ServiceWithoutAPrincipal.__module__ = "syncr_api.control.service"

_ControlServiceDep = Annotated[_ServiceWithoutAPrincipal, Depends(_ServiceWithoutAPrincipal)]


async def _handler_calling_an_unauthorized_service(service: _ControlServiceDep) -> str:
    return await service.do_something("42")


async def _handler_touching_no_service() -> str:
    return "nothing was authorized"


async def _handler_taking_either_credential(principal: ClientPrincipalDep) -> str:
    return str(principal.tenant_id)


async def _handler_taking_a_session(principal: PrincipalDep) -> str:
    return str(principal.tenant_id)


def test_the_service_method_check_reports_a_method_without_a_principal() -> None:
    calls = service_calls(_handler_calling_an_unauthorized_service)

    assert calls == {(_ServiceWithoutAPrincipal, "do_something")}
    assert principal_position(_ServiceWithoutAPrincipal, "do_something") is not None


def test_the_service_method_check_reports_a_handler_that_calls_none() -> None:
    assert service_calls(_handler_touching_no_service) == set()


def test_the_principal_check_reports_a_route_that_resolves_none() -> None:
    control = FastAPI()
    control.get("/unguarded")(_handler_touching_no_service)

    unguarded = [route for route in api_routes(control) if not resolves_a_principal(route)]

    assert len(unguarded) == 1


def test_the_cli_census_discriminates_between_the_two_perimeters() -> None:
    # The census reads an exact set off the real app, so its own discrimination needs a control:
    # a route declaring the either-credential perimeter has to be reported and a route declaring
    # the browser-only one has to not be, or the set could be right for the wrong reason.
    control = FastAPI()
    control.get("/for-the-cli")(_handler_taking_either_credential)
    control.get("/for-the-browser")(_handler_taking_a_session)

    reached = {route.path for route in api_routes(control) if accepts_a_cli_credential(route)}

    assert reached == {"/for-the-cli"}


def test_the_origin_check_reports_an_unsafe_route_without_it() -> None:
    control = FastAPI()
    control.post("/unguarded")(_handler_touching_no_service)

    exposed = [
        route
        for route in api_routes(control)
        if require_trusted_origin not in resolved_dependencies(route)
    ]

    assert len(exposed) == 1


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("from sqlalchemy import select", ["sqlalchemy"]),
        ("from syncr_api.core.db import get_transaction", ["syncr_api.core.db"]),
        ("from syncr_api.accounts.repository import UserRepository", ["repository"]),
        ("from syncr_api.accounts.models import User", ["models"]),
        ("from syncr_api.accounts.schemas import LoginRequest", []),
    ],
)
def test_the_route_module_check_reports_a_handler_reaching_persistence(
    source: str, expected: list[str]
) -> None:
    assert forbidden_reach(source) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("from syncr_api.core.principal import require_scope", [1]),
        ("require_scope(principal, Scope.ADMIN)", [1]),
        ("principal_module.require_scope(principal, Scope.ADMIN)", [1]),
        ("from syncr_api.core.principal import authorize_tenant", []),
        ("return await service.read(principal)", []),
    ],
    ids=["imported", "called", "reached through its module", "another check", "delegating"],
)
def test_the_scope_rule_reports_a_route_that_decides_authorization_itself(
    source: str, expected: list[int]
) -> None:
    assert scope_check_lines(source) == expected
