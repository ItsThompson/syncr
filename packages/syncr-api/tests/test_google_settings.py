"""The Google credentials a deployment supplies, and the two ways it can get them wrong quietly.

The client id, the client secret, and the redirect URI are a deployment's to provide, and an empty
set is a VALID state: a machine with no Google credentials boots, every ICS feed syncs, and the
connect flow reports that Google is not configured. That is asserted here because the alternative
reading, refusing to start, would make Google a hard dependency of a product whose strategic ingest
path needs no OAuth at all.

The token encryption key is different. It has a development default so a fresh clone can connect,
and a deployment that keeps that default stores every Google refresh token under a key any reader
of this repository holds, which is the same as storing it in the clear. So construction fails
outside development, and only when a Google client exists at all: with no client there is nothing to
encrypt, and refusing the boot there would break a deployment that does not use Google.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from syncr_api.core.settings import (
    API_SERVICE,
    DEV_GOOGLE_TOKEN_ENCRYPTION_KEY,
    EnvSettings,
    build_service_settings,
)
from syncr_api.google_account.crypto import TokenCipher
from syncr_api.google_account.injection import build_cipher, may_store_tokens

CLIENT_ID = "581707053568-example.apps.googleusercontent.com"
CALLBACK = "http://localhost:8000/api/v1/calendar-sources/google/callback"
# A real Fernet key, generated for this test alone.
DEPLOYMENT_KEY = "dGVzdC1vbmx5LWdvb2dsZS10b2tlbi1lbmNyeXB0ISE="  # pragma: allowlist secret
DEPLOYMENT_SECRET = "a-signing-secret-a-deployment-generated"  # pragma: allowlist secret


def env(**overrides: object) -> EnvSettings:
    """Settings from explicit values only, so a developer's .env cannot change a test."""
    return EnvSettings(_env_file=None, **overrides)  # type: ignore[arg-type]


def deployed(**overrides: object) -> EnvSettings:
    """Settings for a non-development environment, which needs its own session secret."""
    return env(environment="production", session_signing_secret=DEPLOYMENT_SECRET, **overrides)


def test_a_machine_with_no_google_credentials_still_builds_settings() -> None:
    settings = env()

    assert settings.google_oauth_client_id == ""
    assert settings.google_oauth_client_secret.get_secret_value() == ""
    assert settings.google_oauth_redirect_uri == ""


def test_development_gets_a_token_key_that_works_so_a_fresh_clone_can_connect() -> None:
    assert env().google_token_encryption_key.get_secret_value() == DEV_GOOGLE_TOKEN_ENCRYPTION_KEY


def test_a_deployment_under_the_published_key_may_not_store_an_authorization() -> None:
    # The rule is at the composition, not at settings: this class is built by every process, every
    # test and `alembic`, against whatever the root env file holds, so a refusal there failed boots
    # that store no token at all. Measured, and it is what broke a production-shaped boot for a
    # whole wave.
    settings = build_service_settings(
        service=API_SERVICE, env=deployed(google_oauth_client_id=CLIENT_ID)
    )

    assert may_store_tokens(settings) is False
    # And the cipher still EXISTS, because reading an authorization stored under a real key must not
    # be taken down with the ability to write a new one.
    assert build_cipher(settings).encrypt("1//x")


def test_a_deployment_in_development_may_store_under_the_published_key() -> None:
    # A fresh clone connects Google without generating a key first, which is why a default exists.
    settings = build_service_settings(
        service=API_SERVICE, env=env(google_oauth_client_id=CLIENT_ID)
    )

    assert may_store_tokens(settings) is True
    assert build_cipher(settings).decrypt(build_cipher(settings).encrypt("1//x")) == "1//x"


def test_a_deployment_that_supplied_a_key_may_store_anywhere() -> None:
    settings = build_service_settings(
        service=API_SERVICE,
        env=deployed(google_oauth_client_id=CLIENT_ID, google_token_encryption_key=DEPLOYMENT_KEY),
    )

    assert may_store_tokens(settings) is True
    assert build_cipher(settings).encrypt("1//x")


def test_settings_construct_in_every_environment_from_a_stock_checkout() -> None:
    # The regression this pair of rules caused for seven concurrent agents: `EnvSettings()` has to
    # be constructable whatever the environment says and whatever the root env file holds, because
    # nothing it does stores a token.
    for environment in ("development", "test", "staging", "production"):
        settings = env(
            environment=environment,
            session_signing_secret=DEPLOYMENT_SECRET,
            google_oauth_client_id=CLIENT_ID,
        )
        assert settings.environment == environment


def test_the_development_token_key_is_a_key_that_can_actually_encrypt() -> None:
    # The two rules interact: the usability check is NOT gated on the environment, so a development
    # default that is not a real Fernet key would refuse to boot every development machine that
    # configures a Google client. It has to be 32 bytes as URL-safe base64, not merely base64.
    settings = env(google_oauth_client_id=CLIENT_ID)

    assert (
        settings.google_token_encryption_key.get_secret_value() == DEV_GOOGLE_TOKEN_ENCRYPTION_KEY
    )
    assert (
        TokenCipher(DEV_GOOGLE_TOKEN_ENCRYPTION_KEY).decrypt(
            TokenCipher(DEV_GOOGLE_TOKEN_ENCRYPTION_KEY).encrypt("1//refresh")
        )
        == "1//refresh"
    )


def test_the_development_token_key_is_ignored_where_nothing_is_encrypted_with_it() -> None:
    # No client id means no connect flow, so nothing is stored under this key and a deployment that
    # does not use Google is not asked for one.
    assert deployed().google_token_encryption_key.get_secret_value() == (
        DEV_GOOGLE_TOKEN_ENCRYPTION_KEY
    )


def test_a_deployment_supplied_token_key_is_accepted() -> None:
    settings = deployed(
        google_oauth_client_id=CLIENT_ID, google_token_encryption_key=DEPLOYMENT_KEY
    )

    assert settings.google_token_encryption_key.get_secret_value() == DEPLOYMENT_KEY


@pytest.mark.parametrize(
    "unusable",
    ["typo-key", DEPLOYMENT_KEY[:-4], "", f"{DEPLOYMENT_KEY[:-1]}\u00e9"],
    ids=["not base64", "truncated", "empty", "not ascii"],
)
def test_a_token_key_that_cannot_encrypt_is_refused_by_name(unusable: str) -> None:
    # Without this the value is carried as far as the first token write, which is AFTER the user has
    # consented in a browser: the flow would fail at the one point where retrying means consenting
    # again.
    with pytest.raises(ValidationError, match="GOOGLE_TOKEN_ENCRYPTION_KEY is not a Fernet key"):
        env(google_token_encryption_key=unusable)


def test_the_token_key_failure_names_how_to_generate_one() -> None:
    with pytest.raises(ValidationError) as refused:
        env(google_token_encryption_key="typo")

    assert "Fernet.generate_key" in str(refused.value)


def test_a_key_that_cannot_encrypt_is_refused_whether_or_not_a_client_exists() -> None:
    # Not gated on a second variable, unlike the published-key rule that moved out of settings: a
    # value that is not a key is wrong on its own terms, and the alternative is failing at the first
    # token write, which is after the user has consented in a browser.
    with pytest.raises(ValidationError, match="not a Fernet key"):
        env(google_token_encryption_key="typo")


def test_neither_google_secret_is_in_a_repr_or_a_dump() -> None:
    settings = env(
        google_oauth_client_id=CLIENT_ID,
        google_oauth_client_secret="GOCSPX-not-a-real-secret",  # pragma: allowlist secret
        google_token_encryption_key=DEPLOYMENT_KEY,
    )

    rendered = f"{settings!r} {settings.model_dump()}"

    assert "GOCSPX-not-a-real-secret" not in rendered
    assert DEPLOYMENT_KEY not in rendered
    # The client id is not a secret and is readable, which is what lets a surface state that this
    # deployment has a client at all.
    assert CLIENT_ID in rendered


def test_a_process_carries_the_google_credentials_through_to_its_own_view() -> None:
    settings = build_service_settings(
        service=API_SERVICE,
        env=env(
            google_oauth_client_id=CLIENT_ID,
            google_oauth_client_secret=SecretStr("GOCSPX-not-a-real-secret").get_secret_value(),
            google_oauth_redirect_uri=CALLBACK,
            google_token_encryption_key=DEPLOYMENT_KEY,
        ),
    )

    assert settings.google_oauth_client_id == CLIENT_ID
    assert settings.google_oauth_redirect_uri == CALLBACK
    assert settings.google_token_encryption_key.get_secret_value() == DEPLOYMENT_KEY
