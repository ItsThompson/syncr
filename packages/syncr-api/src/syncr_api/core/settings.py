"""Application settings.

Deployment-wide configuration is sourced from the environment once
(:class:`EnvSettings`) and is identical for the api and the worker. Per-process
identity (the ``service`` name bound onto every log line, and the port the api
binds) is injected at construction time, so the two entrypoints differ only by
their injected settings.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, SecretStr, field_validator, model_validator
from pydantic_settings import NoDecode

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

# The value SESSION_SIGNING_SECRET holds when nobody has set it. Every browser
# session's stored identifier is keyed by this secret, so replacing it signs every
# live session out: that is the documented cost of rotating it, not a bug.
#
# Sessions must work on a fresh clone with no secret file, so there is a default; a
# default that reached production would mean every deployment shared one session key,
# so `EnvSettings` refuses to be built with this value outside development.
DEV_SESSION_SIGNING_SECRET = "dev-only-session-signing-key-not-for-deployment"  # noqa: S105 # pragma: allowlist secret

# A secret shorter than this is a typo or an empty interpolation, not a key. Checked in
# every environment, because the guard against the development default cannot catch a
# value that is merely too short.
MINIMUM_SESSION_SIGNING_SECRET_LENGTH = 16

# Where the browser may send an unsafe request from. In the deployed stack this is
# the tunnel hostname; locally it is the Vite dev server and the api's own origin,
# because a same-origin POST carries an Origin header too.
DEV_ALLOWED_ORIGINS = ("http://localhost:5173", "http://localhost:8000")

# How to produce a real signing secret, named in both failure messages because that
# message is the entire user interface of a deployment that got this wrong.
_GENERATE_HINT = (
    "Generate one with "
    "`python -c \"import secrets; print('syncrp_' + secrets.token_urlsafe(48))\"`."
)


class EnvSettings(SyncrSettings):
    """Deployment-wide config, sourced from the environment.

    Field names mirror the root ``.env`` keys: ``ENVIRONMENT``, ``LOG_LEVEL``,
    ``HOST``, ``DATABASE_URL``, ``SESSION_SIGNING_SECRET``, ``ALLOWED_ORIGINS``.
    Unknown keys are ignored (see
    :class:`syncr_common.config.SyncrSettings`).
    """

    # The container binds all interfaces; the Cloudflare tunnel is the only
    # ingress and no host port is published.
    host: str = "0.0.0.0"  # noqa: S104
    # Async SQLAlchemy URL (asyncpg driver). The dev default targets the Postgres
    # that docker-compose.dev.yml publishes to localhost; in the stack, Compose
    # injects the in-network `@postgres:5432` form.
    database_url: str = "postgresql+asyncpg://syncr:syncr@localhost:5432/syncr"
    # Keyed digest secret for browser sessions. `SecretStr` so a settings dump, a
    # repr, or a validation error cannot carry it, on top of the logger's own
    # redaction of any key containing "secret".
    session_signing_secret: SecretStr = SecretStr(DEV_SESSION_SIGNING_SECRET)
    # `NoDecode` because pydantic-settings would otherwise JSON-decode a complex
    # field, and `ALLOWED_ORIGINS=https://a,https://b` is not JSON.
    allowed_origins: Annotated[tuple[str, ...], NoDecode] = DEV_ALLOWED_ORIGINS

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_comma_separated(cls, value: object) -> object:
        """Accept a comma-separated environment value as the list it reads as."""
        if isinstance(value, str):
            return tuple(origin.strip() for origin in value.split(",") if origin.strip())
        return value

    @model_validator(mode="after")
    def _refuse_the_development_session_secret_elsewhere(self) -> EnvSettings:
        """Fail construction rather than boot with a session key anyone can read.

        Raised at settings construction, which is the first thing an entrypoint does,
        so a deployment missing the secret fails immediately and visibly instead of
        issuing sessions that any reader of this file could forge.
        """
        secret = self.session_signing_secret.get_secret_value()
        if len(secret) < MINIMUM_SESSION_SIGNING_SECRET_LENGTH:
            too_short = (
                "SESSION_SIGNING_SECRET is shorter than "
                f"{MINIMUM_SESSION_SIGNING_SECRET_LENGTH} characters. "
                f"{_GENERATE_HINT}"
            )
            raise ValueError(too_short)
        if not self.is_dev and secret == DEV_SESSION_SIGNING_SECRET:
            still_the_default = (
                "SESSION_SIGNING_SECRET is still the development default in "
                f"environment={self.environment!r}. {_GENERATE_HINT}"
            )
            raise ValueError(still_the_default)
        return self


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
    session_signing_secret: SecretStr
    allowed_origins: tuple[str, ...]


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
        session_signing_secret=env.session_signing_secret,
        allowed_origins=env.allowed_origins,
    )
