"""The authorization boundary: three rules that rot silently, asserted mechanically.

Authorization is enforced in the service layer, on an explicit principal, and this file
is what keeps that true as routes accumulate. It is not a test of the three routes that
exist today: it examines whatever routes exist whenever it runs, which is the only form
of this test that still works in a year.

Each rule is checked twice: once against the real application, and once against a
synthetic input that breaks it. The second half is the important one. A rule whose test
cannot fail is indistinguishable from a rule nobody is enforcing, and the failure mode is
silent.

The three rules:

1. Every route resolves a principal, except the ones named below.
2. Every service method takes that principal FIRST, so authorizing is not optional.
3. No route module can reach persistence, so it has no way to skip the service layer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

import pytest
from fastapi import Depends, FastAPI

from syncr_api.accounts.config import AUTH_PREFIX
from syncr_api.accounts.injection import require_principal, require_trusted_origin
from syncr_api.accounts.service import SessionService
from syncr_api.core.observability import METRICS_ENDPOINT
from syncr_common.health import HEALTHZ_ENDPOINT, READYZ_ENDPOINT
from tests.boundaries import (
    METHODS_WITHOUT_A_BODY,
    api_routes,
    imported_modules,
    principal_position,
    public_methods,
    resolved_dependencies,
    route_identity,
    service_calls,
)

if TYPE_CHECKING:
    from pathlib import Path


# The routes that deliberately resolve no principal, each for a stated reason:
#
#   POST /auth/login   is what PRODUCES a principal. Requiring one would make signing
#                      in possible only while already signed in.
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
        ("GET", HEALTHZ_ENDPOINT),
        ("GET", READYZ_ENDPOINT),
        ("GET", METRICS_ENDPOINT),
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


def authenticated_routes(app: FastAPI) -> list[tuple[str, str, object]]:
    """Every ``(method, path, endpoint)`` that is required to resolve a principal."""
    found = []
    for route in api_routes(app):
        for method, path in sorted(route_identity(route)):
            if (method, path) not in UNAUTHENTICATED_ROUTES:
                found.append((method, path, route.endpoint))
    return found


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
        if (method, path) not in UNAUTHENTICATED_ROUTES
        and require_principal not in resolved_dependencies(route)
    ]

    assert unguarded == [], (
        f"{unguarded} resolve no principal. Declare `PrincipalDep` on the handler, or "
        "add the route to UNAUTHENTICATED_ROUTES with a reason if it genuinely needs "
        "no credential."
    )


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


def test_every_public_service_method_takes_a_principal_first() -> None:
    # The rule stated over the class rather than over the routes that happen to reach
    # it, so a method added ahead of its route is covered too.
    failures = [
        reason
        for name in public_methods(SessionService)
        if (reason := principal_position(SessionService, name)) is not None
    ]

    assert failures == [], f"{failures}"


def test_every_unsafe_route_carries_the_origin_check(app: FastAPI) -> None:
    unguarded = [
        f"{method} {path}"
        for route in api_routes(app)
        for method, path in sorted(route_identity(route))
        if method not in METHODS_WITHOUT_A_BODY
        and require_trusted_origin not in resolved_dependencies(route)
    ]

    assert unguarded == [], (
        f"{unguarded} can change state without an origin check, which is the half of "
        "CSRF protection that SameSite=Lax does not cover."
    )


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


def test_the_service_method_check_reports_a_method_without_a_principal() -> None:
    calls = service_calls(_handler_calling_an_unauthorized_service)

    assert calls == {(_ServiceWithoutAPrincipal, "do_something")}
    assert principal_position(_ServiceWithoutAPrincipal, "do_something") is not None


def test_the_service_method_check_reports_a_handler_that_calls_none() -> None:
    assert service_calls(_handler_touching_no_service) == set()


def test_the_principal_check_reports_a_route_that_resolves_none() -> None:
    control = FastAPI()
    control.get("/unguarded")(_handler_touching_no_service)

    unguarded = [
        route
        for route in api_routes(control)
        if require_principal not in resolved_dependencies(route)
    ]

    assert len(unguarded) == 1


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
