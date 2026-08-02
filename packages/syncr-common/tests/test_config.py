"""The settings base: env-file anchoring, unknown-key tolerance, precedence."""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_common.config import ROOT_ENV_FILE, SyncrSettings

if TYPE_CHECKING:
    import pytest


class FeatureSettings(SyncrSettings):
    """A member's settings, extending the shared base."""

    database_url: str = "postgresql+asyncpg://syncr:syncr@localhost:5432/syncr"


def test_defaults_boot_without_any_environment() -> None:
    settings = FeatureSettings(_env_file=None)

    assert settings.environment == "development"
    assert settings.log_level == "info"
    assert settings.is_dev is True


def test_environment_variables_override_the_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("LOG_LEVEL", "warning")

    settings = FeatureSettings(_env_file=None)

    assert settings.environment == "production"
    assert settings.log_level == "warning"
    assert settings.is_dev is False


def test_unknown_keys_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    # One sectioned root .env carries variables for the api, the worker, the
    # learning job, and Compose itself, so a member must tolerate the rest.
    monkeypatch.setenv("POSTGRES_PASSWORD", "not-a-member-field")

    assert FeatureSettings(_env_file=None).environment == "development"


def test_env_file_is_anchored_at_the_repository_root() -> None:
    # `just dev-api` runs from a member directory, so a package-relative ".env"
    # would silently miss the root file.
    assert ROOT_ENV_FILE.name == ".env"
    assert (ROOT_ENV_FILE.parent / "pyproject.toml").is_file()
