"""Readiness against a real Postgres.

The unit suite proves the readiness contract with injected checks. This proves the
two real checks against a live database, which is the claim a deploy depends on:
``/readyz`` answers 200 only when Postgres is reachable AND the shipped migration
head is applied.

The reachability gate lives in ``conftest.py`` as ``live_database_url``, shared with
every other integration module: skipped only when ``SYNCR_SKIP_DB_TESTS`` is set, never
merely because no database answered.

Two shapes of test appear here for one reason: an asyncpg connection belongs to the
event loop that opened it, and ``TestClient`` runs the app in its own loop. So a test
that goes through HTTP builds its engine inside the client's lifespan, exactly as the
process does, while a test that calls a check directly uses the suite's own loop.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from syncr_api.core.app_factory import create_app
from syncr_api.core.db import (
    DB_UNREACHABLE_REASON,
    create_db_engine,
    create_db_lifespan,
    db_readiness_check,
)
from syncr_api.core.migrations import expected_head, migration_readiness_check
from syncr_common.health import READYZ_ENDPOINT, RETRY_AFTER_SECONDS
from tests.conftest import UNREACHABLE_DATABASE_URL

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncEngine

    from syncr_api.core.settings import ServiceSettings

pytestmark = pytest.mark.integration

MIGRATE_HINT = "run `just migrate` first"


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
    # The wire carries a stable reason, not the driver's host, port, and SQL.
    assert response.json()["checks"]["postgres"]["detail"] == DB_UNREACHABLE_REASON


def _chain_with_an_extra_revision(root: Path) -> Path:
    """An Alembic directory whose head is one revision beyond the applied baseline.

    Pointing the check at this instead of mutating ``alembic_version`` reproduces the
    deploy-gate state without touching the database: the checkout ships a migration
    the database has not run.
    """
    alembic_dir = root / "alembic"
    versions = alembic_dir / "versions"
    versions.mkdir(parents=True)
    (alembic_dir / "script.py.mako").write_text("", encoding="utf-8")
    body = "def upgrade():\n    pass\n\n\ndef downgrade():\n    pass\n"
    (versions / "0001_baseline.py").write_text(
        f'revision = "0001_baseline"\ndown_revision = None\n{body}', encoding="utf-8"
    )
    (versions / "0002_unapplied.py").write_text(
        f'revision = "0002_unapplied"\ndown_revision = "0001_baseline"\n{body}',
        encoding="utf-8",
    )
    return alembic_dir


async def test_the_migration_check_reports_a_reachable_database_at_a_stale_revision(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    # The state a deploy gate exists to catch, and the one the unit tier can only
    # reach with an injected failing check: the database answers, but the head this
    # checkout ships has not been applied.
    result = await migration_readiness_check(
        engine, alembic_dir=_chain_with_an_extra_revision(tmp_path)
    )()

    assert result.ok is False
    # The applied revision is read rather than written out, so this assertion states the
    # rule ("the shipped head is not the applied one") rather than today's chain, which
    # every later migration would otherwise break.
    assert result.detail == (
        f"head 0002_unapplied is not applied (database is at {expected_head()})"
    )


def test_readyz_answers_503_when_the_database_is_reachable_but_the_head_is_stale(
    live_database_url: str, settings: ServiceSettings, tmp_path: Path
) -> None:
    live = create_db_engine(live_database_url)
    app = create_app(
        settings,
        readiness_checks=(
            db_readiness_check(live),
            migration_readiness_check(live, alembic_dir=_chain_with_an_extra_revision(tmp_path)),
        ),
        lifespan=create_db_lifespan(live),
    )

    with TestClient(app) as http:
        response = http.get(READYZ_ENDPOINT)

    assert response.status_code == 503
    assert response.headers["Retry-After"] == str(RETRY_AFTER_SECONDS)
    body = response.json()
    assert body["checks"]["postgres"]["ok"] is True
    assert body["checks"]["migrations"]["ok"] is False
