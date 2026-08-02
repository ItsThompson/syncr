"""The migration-head readiness check.

Migrations run as a one-shot before the api and the worker start, never at
application startup, so two replicas cannot race. That leaves one question a
deploy has to answer before it takes traffic: did the one-shot actually run?
``GET /readyz`` answers it by comparing the revision Postgres has recorded against
the head the checkout ships, so a deploy that did not migrate cannot serve.

The chain is forward-only with exactly one head, which is why "the head" is a
single value here rather than a set to reconcile.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from alembic.script import ScriptDirectory
from sqlalchemy import text

import syncr_api
from syncr_common.health import CheckResult

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from syncr_common.health import ReadinessCheck

# packages/syncr-api/src/syncr_api/ -> packages/syncr-api/alembic. Every member is
# editable-installed in dev, in CI, and in the image, so the directory sits beside
# the installed package in all three.
ALEMBIC_DIR = Path(syncr_api.__file__).resolve().parents[2] / "alembic"

MIGRATION_CHECK_NAME = "migrations"

_APPLIED_REVISION_SQL = text("SELECT version_num FROM alembic_version")


def script_heads(alembic_dir: Path = ALEMBIC_DIR) -> tuple[str, ...]:
    """Every head revision in the migration chain. Exactly one, by design."""
    return tuple(ScriptDirectory(str(alembic_dir)).get_heads())


def expected_head(alembic_dir: Path = ALEMBIC_DIR) -> str:
    """The single head revision the checkout ships."""
    heads = script_heads(alembic_dir)
    if len(heads) != 1:
        raise RuntimeError(f"the migration chain must have exactly one head, found {list(heads)}")
    return heads[0]


async def applied_revision(engine: AsyncEngine) -> str | None:
    """The revision Postgres has recorded, or ``None`` if nothing has been applied."""
    async with engine.connect() as connection:
        result = await connection.execute(_APPLIED_REVISION_SQL)
        return result.scalar_one_or_none()


def migration_readiness_check(
    engine: AsyncEngine, *, alembic_dir: Path = ALEMBIC_DIR
) -> ReadinessCheck:
    """Readiness check that confirms the shipped migration head is applied.

    Never raises: a missing ``alembic_version`` table, an unreachable database, or a
    stale revision all resolve to a failed
    :class:`~syncr_common.health.CheckResult`, so ``/readyz`` answers 503.
    """

    async def check() -> CheckResult:
        try:
            head = expected_head(alembic_dir)
            applied = await applied_revision(engine)
        except Exception as exc:  # noqa: BLE001 - any failure here is "not ready"
            return CheckResult(name=MIGRATION_CHECK_NAME, ok=False, detail=str(exc))
        if applied != head:
            return CheckResult(
                name=MIGRATION_CHECK_NAME,
                ok=False,
                detail=f"head {head} is not applied (database is at {applied or 'nothing'})",
            )
        return CheckResult(name=MIGRATION_CHECK_NAME, ok=True, detail=head)

    return check
