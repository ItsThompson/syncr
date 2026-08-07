"""Shared fixtures for the learning suite.

Most of it is pure and needs none. The storage tier needs a real Postgres, for the reason the api
suite's own conftest states: an in-memory substitute for a JSONB read would be a second
implementation of the spelling this package exists to keep honest.

The tier is skipped only when ``SYNCR_SKIP_DB_TESTS`` is set, never merely because no database
answered. Reachability is the wrong condition: an unreachable Postgres in an environment that is
supposed to have one is exactly the failure the tier exists to catch, and skipping on it turns a
broken loop into a green run.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy import text

from syncr_learning.storage.engine import LearningSettings, create_database

SKIP_ENV_VAR = "SYNCR_SKIP_DB_TESTS"
_TRUTHY = frozenset({"1", "true", "yes"})

SETUP_HINT = (
    "start it with `just dev-infra`, apply migrations with `just migrate`, "
    f"or set {SKIP_ENV_VAR}=1 to skip this tier deliberately"
)


@pytest.fixture(scope="session")
def live_database_url() -> str:
    """The database URL, once it is confirmed reachable. Fails the tier otherwise.

    Read through the job's own settings rather than from the environment directly, so the default
    has one definition and ``DATABASE_URL`` overrides it the way it does for the running container.
    """
    if os.environ.get(SKIP_ENV_VAR, "").strip().lower() in _TRUTHY:
        pytest.skip(f"{SKIP_ENV_VAR} is set")

    url = LearningSettings().database_url

    async def probe() -> None:
        database = create_database(url)
        try:
            async with database.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        finally:
            await database.engine.dispose()

    reason: str | None = None
    try:
        asyncio.run(probe())
    except Exception as exc:  # noqa: BLE001 - reported as a setup line, not re-raised
        reason = f"{type(exc).__name__}: {exc}"
    if reason is not None:
        pytest.fail(f"Postgres is not reachable at {url} ({reason}). {SETUP_HINT}", pytrace=False)
    return url
