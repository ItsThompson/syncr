"""The migration chain, the head-applied readiness check, and what a revision may read.

A revision is a historical artifact: it describes the schema at its own point in the chain,
and it is replayed forever against databases at that point. So it may not import the
workspace's own code, whose definitions describe the schema as it is now. The seeded weight
set is where that bites hardest, and the drift test below keeps the two statements of those
numbers in step without coupling one to the other.
"""

from __future__ import annotations

import tomllib
from types import ModuleType
from typing import TYPE_CHECKING

import pytest
from alembic.script import ScriptDirectory

from syncr_api.core.db import create_db_engine
from syncr_api.core.migrations import (
    ALEMBIC_DIR,
    MIGRATION_CHECK_NAME,
    PROBE_FAILED_REASON,
    expected_head,
    migration_readiness_check,
    script_heads,
)
from syncr_api.learned.config import FIRST_WEIGHT_SET_VERSION, HAND_TUNED, P0_WEIGHTS
from tests.boundaries import PACKAGE_NAME, imported_modules
from tests.conftest import UNREACHABLE_DATABASE_URL

if TYPE_CHECKING:
    from pathlib import Path

BASELINE_REVISION = "0001_baseline"
PLAN_STORAGE_REVISION = "0004_plan_storage"

# packages/syncr-api/alembic -> packages/syncr-api -> packages -> the workspace root.
WORKSPACE_ROOT = ALEMBIC_DIR.parents[2]


def revision_files() -> list[Path]:
    return sorted((ALEMBIC_DIR / "versions").glob("*.py"))


def revision_module(revision: str) -> ModuleType:
    """One revision's loaded module, through Alembic's own loader."""
    module = ScriptDirectory(str(ALEMBIC_DIR)).get_revision(revision).module
    assert isinstance(module, ModuleType)
    return module


def workspace_packages() -> frozenset[str]:
    """Every importable package the workspace's own members ship.

    Derived from the member list and the members' own source trees rather than named, because
    the rule below is about a revision reading code that moves, and every member's code moves.
    A member added later comes under the rule without this test being edited. ``syncr_domain``
    is the near miss the derivation exists for: it holds the closed vocabularies and the
    identifier types, so it is the most inviting thing for a revision author to reach for.
    """
    manifest = tomllib.loads((WORKSPACE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    members: list[str] = manifest["tool"]["uv"]["workspace"]["members"]
    return frozenset(
        package.name
        for member in members
        for package in (WORKSPACE_ROOT / member / "src").iterdir()
        if (package / "__init__.py").exists()
    )


def workspace_imports(source: str) -> list[str]:
    """The workspace's own modules a revision's source imports."""
    shipped = workspace_packages()
    return sorted(module for module in imported_modules(source) if module.split(".")[0] in shipped)


def test_the_chain_has_exactly_one_head() -> None:
    # Forward-only with one head. A second head means a branch, which a single
    # deployable has no way to reconcile.
    assert len(script_heads()) == 1


def test_the_baseline_is_the_root_of_the_chain() -> None:
    revisions = sorted(path.name for path in (ALEMBIC_DIR / "versions").glob("*.py"))

    assert f"{BASELINE_REVISION}.py" in revisions


def test_expected_head_resolves_the_single_head() -> None:
    assert expected_head() == script_heads()[0]


def test_no_revision_imports_the_workspace() -> None:
    # A revision runs against a database at ITS point in the chain, and the workspace's code
    # describes the schema at the head. An INSERT built from a live constant names whatever
    # columns that constant holds today, and Postgres resolves an INSERT's column list when it
    # parses the statement, so a column a later revision adds fails the upgrade on every fresh
    # database before a single row is read.
    reaching = {
        path.name: found
        for path in revision_files()
        if (found := workspace_imports(path.read_text(encoding="utf-8")))
    }

    assert reaching == {}, (
        f"{reaching}. Spell the values the revision needs in the revision, and keep them in "
        "step with the workspace's definition through a test rather than through an import."
    )


def test_the_rule_covers_every_package_the_workspace_ships() -> None:
    # The derivation's control. Stated over one package, the rule would pass on a revision
    # importing any of the other five, which carry the same hazard for the same reason.
    shipped = workspace_packages()

    assert PACKAGE_NAME in shipped
    assert {"syncr_domain", "syncr_common", "syncr_solver", "syncr_learning", "syncr_cli"} <= (
        shipped
    )


@pytest.mark.parametrize(
    "source",
    [
        "import sqlalchemy as sa\nfrom syncr_api.learned.config import P0_WEIGHTS\n",
        "from syncr_domain.identifiers import TenantId\n",
        "import syncr_common.logging\n",
    ],
    ids=["api", "domain", "common"],
)
def test_the_import_check_reports_a_revision_that_reaches_into_the_workspace(source: str) -> None:
    # The control. Without it, "no revision imports the workspace" passes on a reading that
    # finds nothing, and goes on passing after someone adds the import it forbids.
    assert workspace_imports(source) != []


def test_the_import_check_leaves_a_third_party_import_alone() -> None:
    # The other half of the control: the rule must distinguish, not flag every import a
    # revision needs. Alembic and SQLAlchemy are exactly what a revision is written with.
    source = (
        "import sqlalchemy as sa\nfrom alembic import op\nfrom collections.abc import Sequence\n"
    )

    assert workspace_imports(source) == []


def test_the_seeded_weight_set_matches_the_definition_provisioning_reads() -> None:
    # Two writers seed a tenant's version 1: this revision, for the tenants that already
    # existed when it ran, and account provisioning, for every tenant after. They state the
    # numbers separately, so this is what makes a retune a deliberate edit in both places
    # rather than a silent divergence in one.
    seeding = revision_module(PLAN_STORAGE_REVISION)
    definition = dict(P0_WEIGHTS)

    assert definition == seeding.SEEDED_WEIGHTS, (
        "the seeded weights and the definition account provisioning reads have diverged. If a "
        "weight was RETUNED, change both. If an objective TERM was added after this revision, "
        "do not add a column to a revision that cannot have one: narrow this comparison to the "
        "keys the revision names, and decide what a tenant seeded before the term holds."
    )
    assert seeding.SEEDED_VERSION == FIRST_WEIGHT_SET_VERSION
    assert seeding.SEEDED_ORIGIN == HAND_TUNED


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
