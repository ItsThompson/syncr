"""A scope-guarded route, mounted only by the tests that drive it.

``BearerPrincipalDep`` has no product caller: a route the CLI reaches declares the dependency
that resolves either credential, in ``accounts/injection.py``. A dependency
with no caller is a dependency nothing proves: the chain from an ``Authorization`` header to
a 403 has four links, and asserting the scope arithmetic on a hand-built principal exercises
one of them. So this is the shape a bearer-only route would declare, mounted on the
application under test: the route resolves the credential and delegates, and the method it
delegates to checks the scope as its first act.

It lives here rather than in a test module so that the application the rest of the suite
builds carries no route that is not the product's, and so the route census in
``test_authorization_boundary.py`` reads the product's routes and only those.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter

from syncr_api.core.principal import require_scope
from syncr_api.core.scopes import Scope
from syncr_api.core.settings import API_PREFIX
from syncr_api.oauth.injection import BearerPrincipalDep

if TYPE_CHECKING:
    from syncr_api.core.principal import Principal

PROBE_PREFIX = f"{API_PREFIX}/probe"
PROBE_ADMIN_PATH = f"{PROBE_PREFIX}/admin-only"
PROBE_PLAN_WRITE_PATH = f"{PROBE_PREFIX}/plan-write"

REACHED_FIELD = "reached"

probe_router = APIRouter(prefix=PROBE_PREFIX)


class ScopedProbeService:
    """Stands in for a domain service. Two methods, differing only in what they require."""

    @staticmethod
    def read_as_admin(principal: Principal) -> dict[str, str]:
        require_scope(principal, Scope.ADMIN)
        return {REACHED_FIELD: Scope.ADMIN.value}

    @staticmethod
    def write_a_plan(principal: Principal) -> dict[str, str]:
        require_scope(principal, Scope.PLAN_WRITE)
        return {REACHED_FIELD: Scope.PLAN_WRITE.value}


@probe_router.get("/admin-only")
async def admin_only(principal: BearerPrincipalDep) -> dict[str, str]:
    return ScopedProbeService.read_as_admin(principal)


@probe_router.get("/plan-write")
async def plan_write(principal: BearerPrincipalDep) -> dict[str, str]:
    return ScopedProbeService.write_a_plan(principal)
