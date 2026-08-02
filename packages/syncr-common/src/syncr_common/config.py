"""The settings base every deployable extends.

One base class fixes three things so no member re-decides them: where the
environment file lives, that unknown keys are ignored, and the two fields every
process needs (``ENVIRONMENT`` and ``LOG_LEVEL``) to configure logging.

Ignoring unknown keys is what lets one sectioned repository-root ``.env`` carry
variables for the api, the worker, the learning job, and Compose itself.
Real environment variables always win over the file, so Compose and CD inject
values without the file existing at all.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# `just dev-api` and `just dev-worker` run from a member directory, so a
# package-relative ".env" would silently miss the repository-root file. Anchor it
# from this module's own location instead:
#   packages/syncr-common/src/syncr_common/config.py -> <repo root>/.env
# In an image the path resolves inside /app and simply does not exist, which
# pydantic-settings treats as "no env file" while real environment variables
# continue to apply.
ROOT_ENV_FILE = Path(__file__).resolve().parents[4] / ".env"


class SyncrSettings(BaseSettings):
    """Base for every member's settings: the root env file plus the two shared fields."""

    model_config = SettingsConfigDict(env_file=ROOT_ENV_FILE, extra="ignore")

    environment: str = "development"
    log_level: str = "info"

    @property
    def is_dev(self) -> bool:
        return self.environment.lower() == "development"
