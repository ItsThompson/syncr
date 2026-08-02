"""The HTTP application entrypoint.

Composes the api process: settings from the environment, the database, the two
readiness checks that gate a deploy, and the pool-disposing lifespan.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import uvicorn

from syncr_api.core.app_factory import create_app
from syncr_api.core.db import create_database, create_db_lifespan, db_readiness_check
from syncr_api.core.migrations import migration_readiness_check
from syncr_api.core.settings import (
    API_APP_TARGET,
    API_PORT,
    API_SERVICE,
    API_WORKERS,
    build_service_settings,
)
from syncr_common.logging import configure_logging

if TYPE_CHECKING:
    from fastapi import FastAPI


def build_app() -> FastAPI:
    """Build the api app against the ambient environment."""
    settings = build_service_settings(service=API_SERVICE, port=API_PORT)
    # The entrypoint owns the process-global logging setup, so it happens once and
    # before anything else emits a line.
    configure_logging(environment=settings.environment, log_level=settings.log_level)
    database = create_database(settings.database_url)
    app = create_app(
        settings,
        readiness_checks=(
            db_readiness_check(database.engine),
            migration_readiness_check(database.engine),
        ),
        lifespan=create_db_lifespan(database.engine),
    )
    app.state.db = database
    return app


app = build_app()


def main() -> None:
    """Serve the api. The container entrypoint; `just dev-api` adds autoreload.

    The app is named by import string rather than passed as the object above, because
    uvicorn silently ignores ``workers=`` when it receives an app object and serves a
    single process. Both the resource budget and the deployment topology call for two.

    ``log_config=None`` leaves uvicorn's stdlib logging unconfigured, so the process
    emits syncr's JSON lines and nothing else on the happy path. Uvicorn's own
    warnings and errors, a failed port bind among them, still surface through the
    standard-library fallback handler as plain text.
    """
    settings = build_service_settings(service=API_SERVICE, port=API_PORT)
    uvicorn.run(
        API_APP_TARGET,
        host=settings.host,
        port=settings.port,
        workers=API_WORKERS,
        log_config=None,
    )
