"""The liveness and readiness contract.

``GET /healthz`` is liveness and checks nothing: a liveness probe that fails when
the database is briefly unreachable restarts a healthy process and turns a short
outage into a longer one.

``GET /readyz`` is readiness. Every injected check must pass; any failure answers
503 with ``Retry-After``, so a deploy that has not migrated cannot serve traffic
and a load balancer knows when to come back.

Checks are injected as a sequence, so this module stays free of any dependency:
the caller supplies Postgres connectivity and the migration-head check.

Both endpoints appear in the OpenAPI document. The browser reads readiness through the
client generated from that document, so a hidden route would force the frontend to
hand-write the one thing the codegen contract exists to generate. ``/metrics`` stays
hidden, because it serves Prometheus text rather than the JSON a schema would claim.

No failure path puts a raised exception's text on the wire. A check that reports
``CheckResult(ok=False)`` chooses its own detail; a check that raises gets a fixed
reason and its text goes to the log.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from syncr_common.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

HEALTHZ_ENDPOINT = "/healthz"
READYZ_ENDPOINT = "/readyz"

# Seconds a not-ready answer asks the caller to wait. Sized to a migration
# one-shot plus a Postgres restart, not to a request retry.
RETRY_AFTER_SECONDS = 5

# What a misbehaving check reports on the wire. A raised exception's text can carry a
# host, a port, executed SQL, or a credential's user, and a deploy gate is often the
# most widely reachable endpoint a stack has. The text goes to the log instead, which is
# where it is useful. A well-behaved check never reaches this path.
RAISED_REASON = "check raised"

_log = get_logger("syncr.health")


@dataclass(frozen=True)
class CheckResult:
    """Outcome of one readiness check."""

    name: str
    ok: bool
    detail: str | None = None


# A readiness check resolves to a CheckResult. A well-behaved check reports
# failure as `CheckResult(ok=False)` rather than raising, but the aggregator below
# is defensive: a check that raises still degrades to 503 rather than 500, so one
# misbehaving dependency probe cannot mask readiness.
type ReadinessCheck = Callable[[], Awaitable[CheckResult]]


def create_health_router(
    readiness_checks: Sequence[ReadinessCheck] = (),
    *,
    retry_after_seconds: int = RETRY_AFTER_SECONDS,
) -> APIRouter:
    """Build the health router. Checks run concurrently; any failure answers 503."""
    router = APIRouter(tags=["health"])

    @router.get(HEALTHZ_ENDPOINT)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @router.get(READYZ_ENDPOINT)
    async def readyz() -> JSONResponse:
        results = await asyncio.gather(
            *(check() for check in readiness_checks),
            return_exceptions=True,
        )
        checks: dict[str, dict[str, object]] = {}
        ready = True
        for index, result in enumerate(results):
            name = f"check_{index}"
            if isinstance(result, BaseException):
                ready = False
                _log.warning("health.readiness.check_raised", check=name, error=str(result))
                checks[name] = {"ok": False, "detail": RAISED_REASON}
                continue
            ready = ready and result.ok
            checks[result.name] = {"ok": result.ok, "detail": result.detail}
        payload = {"status": "ready" if ready else "not_ready", "checks": checks}
        headers = {} if ready else {"Retry-After": str(retry_after_seconds)}
        return JSONResponse(payload, status_code=200 if ready else 503, headers=headers)

    return router
