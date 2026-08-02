"""Settings that a deployment must not be allowed to get wrong quietly.

Two of them. The session signing secret has a development default, because sessions have
to work on a fresh clone with no secret file, and a default that reached production would
mean every deployment shared one session key: anyone who could read this repository could
forge a session. So construction fails outside development rather than booting.

The allowed-origin list is parsed from a comma-separated environment value, because that
is what an operator writes and what a compose file passes.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from syncr_api.core.settings import (
    API_SERVICE,
    DEV_ALLOWED_ORIGINS,
    DEV_SESSION_SIGNING_SECRET,
    EnvSettings,
    build_service_settings,
)

DEPLOYMENT_SECRET = "a-signing-secret-a-deployment-generated"  # pragma: allowlist secret


def env(**overrides: object) -> EnvSettings:
    """Settings from explicit values only, so a developer's .env cannot change a test."""
    return EnvSettings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_development_gets_a_working_default_so_a_fresh_clone_can_sign_in() -> None:
    assert env().session_signing_secret.get_secret_value() == DEV_SESSION_SIGNING_SECRET


@pytest.mark.parametrize("environment", ["production", "staging", "test"])
def test_the_development_secret_is_refused_anywhere_else(environment: str) -> None:
    with pytest.raises(ValidationError, match="SESSION_SIGNING_SECRET"):
        env(environment=environment)


@pytest.mark.parametrize("environment", ["production", "staging", "test"])
def test_a_supplied_secret_is_accepted_everywhere(environment: str) -> None:
    settings = env(environment=environment, session_signing_secret=DEPLOYMENT_SECRET)

    assert settings.session_signing_secret.get_secret_value() == DEPLOYMENT_SECRET


def test_the_secret_is_not_in_the_repr_or_a_dump() -> None:
    # Two layers, because a settings object ends up in a log line or an error message
    # eventually: the field name contains "secret" so the logger's redactor eats it, and
    # the type hides it from anything that renders the model.
    settings = env(session_signing_secret=DEPLOYMENT_SECRET)

    assert DEPLOYMENT_SECRET not in repr(settings)
    assert DEPLOYMENT_SECRET not in str(settings.model_dump())


def test_the_error_names_the_variable_and_how_to_generate_a_value() -> None:
    # This message is the whole user interface of a failed deploy, so it says which
    # variable is missing and what to put in it.
    with pytest.raises(ValidationError) as refused:
        env(environment="production")

    message = str(refused.value)
    assert "SESSION_SIGNING_SECRET" in message
    assert "secrets.token_urlsafe" in message


@pytest.mark.parametrize("secret", ["", "short", "x" * 15])
@pytest.mark.parametrize("environment", ["development", "production"])
def test_a_secret_too_short_to_be_one_is_refused_everywhere(secret: str, environment: str) -> None:
    # An empty value is what an unset variable interpolates to, which would otherwise be
    # a session key of nothing and would pass the default check in development.
    with pytest.raises(ValidationError, match="SESSION_SIGNING_SECRET"):
        env(environment=environment, session_signing_secret=secret)


def test_the_allowed_origins_default_covers_the_local_loop() -> None:
    assert env().allowed_origins == DEV_ALLOWED_ORIGINS


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://syncr.example", ("https://syncr.example",)),
        ("https://a.example,https://b.example", ("https://a.example", "https://b.example")),
        (" https://a.example , https://b.example ", ("https://a.example", "https://b.example")),
        ("", ()),
    ],
)
def test_a_comma_separated_origin_list_is_parsed(value: str, expected: tuple[str, ...]) -> None:
    assert env(allowed_origins=value).allowed_origins == expected


def test_a_process_carries_both_settings_through_to_its_own_view() -> None:
    # `ServiceSettings` is what a request reads from `app.state`, so a field that stopped
    # at `EnvSettings` would be a field no dependency could see.
    settings = build_service_settings(
        service=API_SERVICE, env=env(session_signing_secret=DEPLOYMENT_SECRET)
    )

    assert settings.session_signing_secret.get_secret_value() == DEPLOYMENT_SECRET
    assert settings.allowed_origins == DEV_ALLOWED_ORIGINS
