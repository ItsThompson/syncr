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
from syncr_api.core.settings import API_PORT, API_SERVICE, build_service_settings

if TYPE_CHECKING:
    from fastapi import FastAPI


def build_app() -> FastAPI:
    """Build the api app against the ambient environment."""
    settings = build_service_settings(service=API_SERVICE, port=API_PORT)
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
    """Serve the api. The container entrypoint; `just dev-api` adds autoreload."""
    settings = build_service_settings(service=API_SERVICE, port=API_PORT)
    uvicorn.run(app, host=settings.host, port=settings.port, log_config=None)
