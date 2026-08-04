"""Application settings.

Deployment-wide configuration is sourced from the environment once
(:class:`EnvSettings`) and is identical for the api and the worker. Per-process
identity (the ``service`` name bound onto every log line, and the port the api
binds) is injected at construction time, so the two entrypoints differ only by
their injected settings.
"""

from __future__ import annotations

from typing import Annotated

from cryptography.fernet import Fernet
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

# The origin every OAuth URL is built from: the issuer in the discovery document, the
# audience an access token is bound to, and the endpoint URLs the document advertises.
#
# PINNED, never derived from the request host. Cloudflare Tunnel reaches this process as
# `http://api:8000` from inside `app-net`, so a request-derived issuer would advertise an
# unreachable URL and would sign tokens whose `iss` no client can match against the one it
# opened the flow at. That failure appears only through the tunnel, which is to say only in
# the deployed stack.
DEV_PUBLIC_BASE_URL = "http://localhost:8000"

# The key the OAuth signing keys are encrypted with at rest. Same shape of rule as the
# session secret: a development default exists so a fresh clone boots with no secret
# file, and it is refused outside development. A Fernet key is 32 bytes as URL-safe
# base64; this one is the ASCII of its own purpose, so it is recognizable in a diff.
DEV_OAUTH_KEY_ENCRYPTION_KEY = (
    "ZGV2LW9ubHktb2F1dGgta2V5LWVuY3J5cHRpb24ta2U="  # pragma: allowlist secret
)

# The key a stored Google refresh token is encrypted with at rest. Its own value rather than
# the OAuth signing key's, because the two rotate on different schedules and for different
# reasons: rotating the signing key retires a JWKS entry, and rotating this one costs the user
# a reconnect.
#
# A Fernet key is 32 bytes as URL-safe base64, so this one is the ASCII of its own purpose at
# exactly that length: a development default that is not a usable key would fail at the first
# token write rather than at load, which is after the user has consented in a browser.
#
# **Whether this published value may be USED is decided where a token is encrypted, not here.**
# `syncr_api.google_account.crypto.is_published_key` is that check, and the composition that
# builds a cipher refuses outside development. It is not a settings rule because the condition
# that makes the key dangerous is another variable's value, and this class is constructed by
# every process, every test, and `alembic`, against whatever the root env file happens to hold:
# a cross-variable refusal here fails a boot that stores nothing.
DEV_GOOGLE_TOKEN_ENCRYPTION_KEY = "ZGV2LW9ubHktZ29vZ2xlLXRva2VuLWVuY3J5cHQta2U="  # noqa: S105 # pragma: allowlist secret

# How to produce a real key-encryption key, named in the failure message for the same
# reason the session hint is: that message is the whole user interface of a deployment
# that got this wrong.
_GENERATE_ENCRYPTION_KEY_HINT = (
    "Generate one with "
    '`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.'
)

# How to produce a real signing secret, named in both failure messages because that
# message is the entire user interface of a deployment that got this wrong.
_GENERATE_HINT = (
    "Generate one with "
    "`python -c \"import secrets; print('syncrp_' + secrets.token_urlsafe(48))\"`."
)


class EnvSettings(SyncrSettings):
    """Deployment-wide config, sourced from the environment.

    Field names mirror the root ``.env`` keys: ``ENVIRONMENT``, ``LOG_LEVEL``,
    ``HOST``, ``DATABASE_URL``, ``SESSION_SIGNING_SECRET``, ``ALLOWED_ORIGINS``,
    ``PUBLIC_BASE_URL``, ``OAUTH_KEYS_PATH``, ``OAUTH_KEY_ENCRYPTION_KEY``,
    ``GOOGLE_OAUTH_CLIENT_ID``, ``GOOGLE_OAUTH_CLIENT_SECRET``,
    ``GOOGLE_OAUTH_REDIRECT_URI``, ``GOOGLE_TOKEN_ENCRYPTION_KEY``.
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
    # The pinned origin every OAuth URL and token claim is built from.
    public_base_url: str = DEV_PUBLIC_BASE_URL
    # Where the encrypted OAuth signing keys are read from. Empty means "no key file",
    # which development answers with an ephemeral in-memory keypair and every other
    # environment refuses, so a deployment cannot serve a JWKS whose keys vanish on
    # restart and take every live token with them.
    oauth_keys_path: str = ""
    # The Fernet key the signing-key file is encrypted with. `SecretStr` so a settings
    # dump, a repr, or a validation error cannot carry it.
    oauth_key_encryption_key: SecretStr = SecretStr(DEV_OAUTH_KEY_ENCRYPTION_KEY)
    # The web-application OAuth client for the one Google integration. Empty is a valid
    # state: the stack boots and the connect flow reports that Google is not configured,
    # so a machine with no Google credentials still runs every other surface.
    google_oauth_client_id: str = ""
    google_oauth_client_secret: SecretStr = SecretStr("")
    # Which registered redirect URI this process uses. Google matches redirect URIs as exact
    # strings, so this selects one of the URIs registered on the client rather than deriving
    # one from a base URL.
    google_oauth_redirect_uri: str = ""
    # The Fernet key a stored Google refresh token is encrypted with.
    google_token_encryption_key: SecretStr = SecretStr(DEV_GOOGLE_TOKEN_ENCRYPTION_KEY)

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

    @model_validator(mode="after")
    def _refuse_an_empty_origin_list(self) -> EnvSettings:
        """Fail construction rather than serve a stack that rejects every mutation.

        An unset variable interpolates to an empty value, and an empty allowlist trusts
        no origin, so every unsafe request answers 403. That reads as an application bug
        rather than as a missing variable, which is the failure this refuses to ship.
        """
        if not self.allowed_origins:
            message = (
                "ALLOWED_ORIGINS is empty, so every unsafe request would be rejected with "
                "403. Name the origins the browser sends from, comma separated, for "
                "example ALLOWED_ORIGINS=https://syncr.example"
            )
            raise ValueError(message)
        return self

    @model_validator(mode="after")
    def _refuse_the_development_key_encryption_key_elsewhere(self) -> EnvSettings:
        """Fail construction rather than encrypt a signing key with a published key.

        The default is in this file, so a deployment that kept it stores its OAuth signing
        key under a key any reader of the repository holds, which is the same as storing it
        in the clear.

        Gated on there being a key file at all. With no ``OAUTH_KEYS_PATH`` nothing is
        encrypted with this value: development generates an ephemeral key set in memory and
        every other environment refuses to start at all, in
        :func:`syncr_api.oauth.keys.load_signing_key_set`, which is the guard that catches
        that case and states what to do about it.
        """
        if self.is_dev or not self.oauth_keys_path:
            return self
        if self.oauth_key_encryption_key.get_secret_value() == DEV_OAUTH_KEY_ENCRYPTION_KEY:
            message = (
                "OAUTH_KEY_ENCRYPTION_KEY is still the development default in "
                f"environment={self.environment!r}, so the OAuth signing key at "
                f"{self.oauth_keys_path} is effectively unencrypted. "
                f"{_GENERATE_ENCRYPTION_KEY_HINT}"
            )
            raise ValueError(message)
        return self

    @model_validator(mode="after")
    def _refuse_a_google_token_key_that_cannot_encrypt(self) -> EnvSettings:
        """Fail construction rather than discover a truncated paste at the first connect.

        Checked whenever a value is set at all, and NOT gated on any other variable: this class is
        constructed by every process, every test, and ``alembic``, so a rule that read a second
        variable would fail a boot for a value that boot never uses. A key that cannot encrypt is
        different: it is wrong on its own terms, and the alternative is failing at the first token
        write, which is after the user has consented in a browser.
        """
        try:
            Fernet(self.google_token_encryption_key.get_secret_value().encode("ascii"))
        except (ValueError, UnicodeEncodeError) as unusable:
            message = (
                "GOOGLE_TOKEN_ENCRYPTION_KEY is not a Fernet key, so a Google refresh token can "
                f"be neither stored nor read. {_GENERATE_ENCRYPTION_KEY_HINT}"
            )
            raise ValueError(message) from unusable
        return self

    @model_validator(mode="after")
    def _refuse_a_key_that_cannot_encrypt(self) -> EnvSettings:
        """Fail construction rather than let a library report a truncated paste.

        Without this the value is carried as far as the first read of the key file, where
        ``Fernet`` raises "Fernet key must be 32 url-safe base64-encoded bytes": a message that
        names neither the variable, nor the file, nor how to generate one. Every other way of
        misconfiguring this pair says all three, and a truncated paste is the likeliest of them.
        """
        if not self.oauth_keys_path:
            return self
        try:
            Fernet(self.oauth_key_encryption_key.get_secret_value().encode("ascii"))
        except (ValueError, UnicodeEncodeError) as unusable:
            message = (
                "OAUTH_KEY_ENCRYPTION_KEY is not a Fernet key, so the OAuth signing keys at "
                f"{self.oauth_keys_path} can be neither written nor read. "
                f"{_GENERATE_ENCRYPTION_KEY_HINT}"
            )
            raise ValueError(message) from unusable
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
    public_base_url: str
    oauth_keys_path: str
    oauth_key_encryption_key: SecretStr
    google_oauth_client_id: str
    google_oauth_client_secret: SecretStr
    google_oauth_redirect_uri: str
    google_token_encryption_key: SecretStr


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
        public_base_url=env.public_base_url,
        oauth_keys_path=env.oauth_keys_path,
        oauth_key_encryption_key=env.oauth_key_encryption_key,
        google_oauth_client_id=env.google_oauth_client_id,
        google_oauth_client_secret=env.google_oauth_client_secret,
        google_oauth_redirect_uri=env.google_oauth_redirect_uri,
        google_token_encryption_key=env.google_token_encryption_key,
    )
