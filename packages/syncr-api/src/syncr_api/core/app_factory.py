"""The application factory and the feature-router registry.

:func:`create_app` assembles a configured app: the health and metrics routers, the
error contract, correlation, and every router the registry below declares.

It deliberately does NOT configure logging. That is a process-global side effect, and
an entrypoint owns it: ``api/main.py`` and ``worker/main.py`` each call
``configure_logging`` before building anything, so a factory stays a factory and a
test is not fighting a global it did not ask for.

Wiring only. This module imports feature modules; a feature module must never
import this one, or the composition root becomes a cycle. A feature module builds
its own path from ``syncr_api.core.settings.API_PREFIX``.
"""

from __future__ import annotations

from importlib.metadata import version
from typing import TYPE_CHECKING

from fastapi import APIRouter, FastAPI

from syncr_api.accounts.wiring import build_accounts_router
from syncr_api.anchors.wiring import build_anchors_router
from syncr_api.areas.wiring import build_areas_router
from syncr_api.budgets.wiring import build_budget_router
from syncr_api.calendars.wiring import build_calendars_router
from syncr_api.core.correlation import CorrelationMiddleware
from syncr_api.core.error_handlers import PROBLEM_RESPONSES, build_exception_handlers
from syncr_api.core.observability import create_metrics_router
from syncr_api.oauth.wiring import build_oauth_router
from syncr_api.offplan.wiring import build_off_plan_router
from syncr_api.routines.wiring import build_routines_router
from syncr_api.tasks.wiring import build_tasks_router
from syncr_api.user_settings.wiring import build_settings_router
from syncr_common.health import create_health_router
from syncr_common.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from starlette.types import Lifespan

    from syncr_api.core.settings import ServiceSettings
    from syncr_common.health import ReadinessCheck

# A feature module exports a zero-argument factory returning its router. Everything
# the router needs is resolved per request through FastAPI dependencies reading
# `app.state`, so the factory takes no wiring arguments and the registry below stays
# one line per module.
type RouterFactory = Callable[[], APIRouter]

# ---------------------------------------------------------------------------
# THE FEATURE-ROUTER REGISTRY. APPEND ONLY.
#
# One line per feature module, added at the END of this tuple. Adding a feature
# changes this list and nothing else in this file. Written multi-line while empty so
# the first appending ticket adds a line rather than reformatting the one every later
# ticket then edits.
# ---------------------------------------------------------------------------
FEATURE_ROUTERS: tuple[RouterFactory, ...] = (
    build_accounts_router,
    build_settings_router,
    build_oauth_router,
    build_areas_router,
    build_budget_router,
    build_calendars_router,
    build_tasks_router,
    build_routines_router,
    build_off_plan_router,
    build_anchors_router,
)

# The one place the api's version is stated: the package metadata uv installs from
# pyproject.toml.
API_VERSION = version("syncr-api")


def create_app(
    settings: ServiceSettings,
    *,
    feature_routers: Sequence[RouterFactory] = FEATURE_ROUTERS,
    readiness_checks: Sequence[ReadinessCheck] = (),
    lifespan: Lifespan[FastAPI] | None = None,
) -> FastAPI:
    """Assemble the configured app from injected settings and mount points."""
    log = get_logger(settings.service)

    app = FastAPI(
        title=settings.service,
        version=API_VERSION,
        lifespan=lifespan,
        # So the generated document describes the error shape the api actually sends.
        responses=dict(PROBLEM_RESPONSES),
    )
    app.state.settings = settings
    app.state.log = log

    for key, handler in build_exception_handlers().items():
        app.add_exception_handler(key, handler)

    app.include_router(create_health_router(readiness_checks))
    app.include_router(create_metrics_router())
    for build_router in feature_routers:
        app.include_router(build_router())

    # Mounted last so it is the outermost middleware: the correlation id is bound
    # before any router runs and survives out to the catch-all fault handler.
    app.add_middleware(CorrelationMiddleware)

    log.info(
        "api.app.configured",
        environment=settings.environment,
        port=settings.port,
        feature_routers=len(feature_routers),
        readiness_checks=len(readiness_checks),
    )
    return app
