"""The migration chain and the head-applied readiness check."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syncr_api.core.db import create_db_engine
from syncr_api.core.migrations import (
    ALEMBIC_DIR,
    MIGRATION_CHECK_NAME,
    PROBE_FAILED_REASON,
    expected_head,
    migration_readiness_check,
    script_heads,
)
from tests.conftest import UNREACHABLE_DATABASE_URL

if TYPE_CHECKING:
    from pathlib import Path

BASELINE_REVISION = "0001_baseline"


def test_the_chain_has_exactly_one_head() -> None:
    # Forward-only with one head. A second head means a branch, which a single
    # deployable has no way to reconcile.
    assert len(script_heads()) == 1


def test_the_baseline_is_the_root_of_the_chain() -> None:
    revisions = sorted(path.name for path in (ALEMBIC_DIR / "versions").glob("*.py"))

    assert f"{BASELINE_REVISION}.py" in revisions


def test_expected_head_resolves_the_single_head() -> None:
    assert expected_head() == script_heads()[0]


def test_expected_head_rejects_a_branched_chain(tmp_path: Path) -> None:
    # Guard the guard: a chain with two heads must raise rather than silently pick
    # one, because picking one would make /readyz pass on a branched deploy.
    alembic_dir = tmp_path / "alembic"
    versions = alembic_dir / "versions"
    versions.mkdir(parents=True)
    (alembic_dir / "script.py.mako").write_text("", encoding="utf-8")
    for revision in ("a", "b"):
        (versions / f"{revision}.py").write_text(
            f'revision = "{revision}"\ndown_revision = None\n'
            "def upgrade():\n    pass\ndef downgrade():\n    pass\n",
            encoding="utf-8",
        )

    with pytest.raises(RuntimeError, match="exactly one head"):
        expected_head(alembic_dir)


async def test_readiness_reports_not_ready_when_the_database_is_unreachable() -> None:
    engine = create_db_engine(UNREACHABLE_DATABASE_URL)
    try:
        result = await migration_readiness_check(engine)()
    finally:
        await engine.dispose()

    assert result.name == MIGRATION_CHECK_NAME
    assert result.ok is False
    # A stable reason, not the driver's message: it names the host, the port, the
    # executed SQL, and the connecting user, and /readyz is widely reachable.
    assert result.detail == PROBE_FAILED_REASON
