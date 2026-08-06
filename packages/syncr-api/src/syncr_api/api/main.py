"""The HTTP application entrypoint.

Composes the api process: settings from the environment, the database, the OAuth signing keys, the
two readiness checks that gate a deploy, the event listener, and the pool-disposing lifespan.

The signing keys are loaded HERE rather than lazily on the first request, so a key file that
cannot be decrypted, or a deployment with no key file at all, fails the boot. A process that
started and then answered 500 on the token endpoint would pass its healthcheck and fail the
CLI.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import uvicorn

from syncr_api.core.app_factory import create_app
from syncr_api.core.db import create_database, db_readiness_check
from syncr_api.core.migrations import migration_readiness_check
from syncr_api.core.settings import (
    API_APP_TARGET,
    API_PORT,
    API_SERVICE,
    API_WORKERS,
    EnvSettings,
    build_service_settings,
)
from syncr_api.events.channel import listening
from syncr_api.oauth.config import build_oauth_config
from syncr_api.oauth.injection import build_oauth_state
from syncr_api.oauth.keys import load_signing_key_set
from syncr_common.logging import configure_logging

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import FastAPI
    from starlette.types import Lifespan

    from syncr_api.core.db import Database


def build_app() -> FastAPI:
    """Build the api app against the ambient environment."""
    env = EnvSettings()
    settings = build_service_settings(service=API_SERVICE, port=API_PORT, env=env)
    # The entrypoint owns the process-global logging setup, so it happens once and
    # before anything else emits a line.
    configure_logging(environment=settings.environment, log_level=settings.log_level)
    database = create_database(settings.database_url)
    oauth_config = build_oauth_config(settings, is_dev=env.is_dev)
    app = create_app(
        settings,
        readiness_checks=(
            db_readiness_check(database.engine),
            migration_readiness_check(database.engine),
        ),
        lifespan=_create_lifespan(database),
    )
    app.state.db = database
    app.state.oauth = build_oauth_state(oauth_config, load_signing_key_set(oauth_config))
    return app


def _create_lifespan(database: Database) -> Lifespan[FastAPI]:
    """The two things this process starts and stops: the event listener and the pool.

    The listener is here rather than in the factory because it holds a connection for the life of
    the process, which a test app must not: the hub the factory attaches works without it, and what
    the listener adds is events produced by the OTHER two processes.

    Composed at the entrypoint because this is the composition root. The pool is disposed last, so
    the listener's own connection is closed before the engine it came from goes away.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with listening(database.engine, app.state.events):
            yield
        await database.engine.dispose()

    return lifespan


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
