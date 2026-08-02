"""Readiness against a real Postgres.

The unit suite proves the readiness contract with injected checks. This proves the
two real checks against a live database, which is the claim a deploy depends on:
``/readyz`` answers 200 only when Postgres is reachable AND the shipped migration
head is applied.

Skipped when no Postgres is reachable, so the pure suites stay runnable anywhere.
CI supplies one as a service container and runs the migration one-shot first,
exactly as a deploy does.

Two shapes of test appear here for one reason: an asyncpg connection belongs to the
event loop that opened it, and ``TestClient`` runs the app in its own loop. So a test
that goes through HTTP builds its engine inside the client's lifespan, exactly as the
process does, while a test that calls a check directly uses the suite's own loop.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from syncr_api.core.app_factory import create_app
from syncr_api.core.db import create_db_engine, create_db_lifespan, db_readiness_check
from syncr_api.core.migrations import expected_head, migration_readiness_check
from syncr_common.health import READYZ_ENDPOINT, RETRY_AFTER_SECONDS
from tests.conftest import UNREACHABLE_DATABASE_URL, database_url

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine

    from syncr_api.core.settings import ServiceSettings

pytestmark = pytest.mark.integration

MIGRATE_HINT = "run `just migrate` first"


@pytest.fixture(scope="session")
def live_database_url() -> str:
    """The database URL, once it is confirmed reachable. Skips the module otherwise.

    The probe engine is fully disposed before the URL is handed out, so no connection
    outlives the probe's loop.
    """
    url = database_url()

    async def probe() -> None:
        engine = create_db_engine(url)
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        finally:
            await engine.dispose()

    try:
        asyncio.run(probe())
    except Exception as exc:
        pytest.skip(f"Postgres is not reachable at {url}: {exc}")
    return url


@pytest.fixture
async def engine(live_database_url: str) -> AsyncIterator[AsyncEngine]:
    """An engine owned by the suite's own event loop, for the direct check calls."""
    live = create_db_engine(live_database_url)
    yield live
    await live.dispose()


async def test_the_database_check_passes_against_a_live_postgres(engine: AsyncEngine) -> None:
    result = await db_readiness_check(engine)()

    assert result.ok is True, result.detail


async def test_the_migration_check_reports_the_applied_head(engine: AsyncEngine) -> None:
    result = await migration_readiness_check(engine)()

    assert result.ok is True, f"{result.detail}; {MIGRATE_HINT}"
    assert result.detail == expected_head()


def test_readyz_answers_200_with_both_real_checks_wired(
    live_database_url: str, settings: ServiceSettings
) -> None:
    live = create_db_engine(live_database_url)
    app = create_app(
        settings,
        readiness_checks=(db_readiness_check(live), migration_readiness_check(live)),
        lifespan=create_db_lifespan(live),
    )

    with TestClient(app) as http:
        response = http.get(READYZ_ENDPOINT)

    assert response.status_code == 200, f"{response.text}; {MIGRATE_HINT}"
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["postgres"]["ok"] is True
    assert body["checks"]["migrations"]["detail"] == expected_head()
    assert "Retry-After" not in response.headers


def test_readyz_answers_503_when_the_database_is_gone(
    live_database_url: str, settings: ServiceSettings
) -> None:
    # Requiring a live Postgres first means this asserts connectivity failure rather
    # than passing trivially on a host with no database at all.
    assert live_database_url
    unreachable = create_db_engine(UNREACHABLE_DATABASE_URL)
    app = create_app(
        settings,
        readiness_checks=(db_readiness_check(unreachable),),
        lifespan=create_db_lifespan(unreachable),
    )

    with TestClient(app) as http:
        response = http.get(READYZ_ENDPOINT)

    assert response.status_code == 503
    assert response.headers["Retry-After"] == str(RETRY_AFTER_SECONDS)
    assert response.json()["checks"]["postgres"]["ok"] is False
