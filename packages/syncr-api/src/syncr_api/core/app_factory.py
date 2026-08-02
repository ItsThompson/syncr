"""The application factory and the feature-router registry.

:func:`create_app` assembles a configured app: structured logging, the health and
metrics routers, the error contract, correlation, and every router the registry
below declares.

Wiring only. This module imports feature modules; a feature module must never
import this one, or the composition root becomes a cycle. A feature module builds
its own path from ``syncr_api.core.settings.API_PREFIX``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, FastAPI

from syncr_api.core.correlation import CorrelationMiddleware
from syncr_api.core.errors import build_exception_handlers
from syncr_common.health import create_health_router
from syncr_common.logging import configure_logging, get_logger
from syncr_common.metrics import create_metrics_router

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
# changes this list and nothing else in this file.
# ---------------------------------------------------------------------------
FEATURE_ROUTERS: tuple[RouterFactory, ...] = ()

API_VERSION = "0.1.0"


def create_app(
    settings: ServiceSettings,
    *,
    feature_routers: Sequence[RouterFactory] = FEATURE_ROUTERS,
    readiness_checks: Sequence[ReadinessCheck] = (),
    lifespan: Lifespan[FastAPI] | None = None,
) -> FastAPI:
    """Assemble the configured app from injected settings and mount points."""
    configure_logging(environment=settings.environment, log_level=settings.log_level)
    log = get_logger(settings.service)

    app = FastAPI(title=settings.service, version=API_VERSION, lifespan=lifespan)
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
