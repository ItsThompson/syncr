"""Application settings.

Deployment-wide configuration is sourced from the environment once
(:class:`EnvSettings`) and is identical for the api and the worker. Per-process
identity (the ``service`` name bound onto every log line, and the port the api
binds) is injected at construction time, so the two entrypoints differ only by
their injected settings.
"""

from __future__ import annotations

from pydantic import BaseModel

from syncr_common.config import SyncrSettings

API_SERVICE = "syncr-api"
WORKER_SERVICE = "syncr-worker"
API_PORT = 8000

# The import string uvicorn needs to fork workers. Passing an app OBJECT makes
# uvicorn ignore `workers=` silently and serve one process, so the target is named
# here and `main()` passes this rather than the module-level `app`.
API_APP_TARGET = "syncr_api.api.main:app"
# Two workers, per the resource budget and the deployment topology.
API_WORKERS = 2

# Domain routes live under one versioned prefix. `/oauth`, `/.well-known`,
# `/healthz`, `/readyz`, and `/metrics` sit outside it, so a feature module builds
# its own full prefix from this constant rather than the app factory imposing one.
API_PREFIX = "/api/v1"


class EnvSettings(SyncrSettings):
    """Deployment-wide config, sourced from the environment.

    Field names mirror the root ``.env`` keys: ``ENVIRONMENT``, ``LOG_LEVEL``,
    ``HOST``, ``DATABASE_URL``. Unknown keys are ignored (see
    :class:`syncr_common.config.SyncrSettings`).
    """

    # The container binds all interfaces; the Cloudflare tunnel is the only
    # ingress and no host port is published.
    host: str = "0.0.0.0"  # noqa: S104
    # Async SQLAlchemy URL (asyncpg driver). The dev default targets the Postgres
    # that docker-compose.dev.yml publishes to localhost; in the stack, Compose
    # injects the in-network `@postgres:5432` form.
    database_url: str = "postgresql+asyncpg://syncr:syncr@localhost:5432/syncr"


class ServiceSettings(BaseModel):
    """Full settings for one process: shared env config plus its own identity.

    ``is_dev`` is deliberately not repeated here: read it from the
    :class:`~syncr_common.config.SyncrSettings` instance that produced these values, or
    compare ``environment`` directly. One predicate, one definition.
    """

    service: str
    port: int
    environment: str
    log_level: str
    host: str
    database_url: str


def build_service_settings(
    *, service: str, port: int = API_PORT, env: EnvSettings | None = None
) -> ServiceSettings:
    """Compose one process's settings from injected identity and shared env config."""
    env = env or EnvSettings()
    return ServiceSettings(
        service=service,
        port=port,
        environment=env.environment,
        log_level=env.log_level,
        host=env.host,
        database_url=env.database_url,
    )
