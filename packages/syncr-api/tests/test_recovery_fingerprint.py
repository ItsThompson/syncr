"""The reading a restore is checked against: its contract, its discovery, and the cursor it derives.

Three crossings, each closing a way the drill could agree with itself while the deployment did not:

- **The document's keys are one contract in two interpreters.** The api image writes it and the ops
  image reads it, with no import between them, so the two sets of key constants are crossed as an
  equality here and a document the writer produces is fed to the real reader.
- **The tables it counts are discovered, not listed.** `alembic/env.py` imports seventeen model
  modules by hand for their registration side effect. A second hand-written copy of that list would
  drift, and the fingerprint would silently stop counting the table a new feature added, so the walk
  is crossed against `env.py`'s own imports in BOTH directions. That also makes the drift visible on
  the autogenerate side: a model module missing from `env.py` is a migration nothing generates.
- **The five tables the drill's verdict is stated over are the application's own.** `ops.config`
  spells them as strings, because it runs in an image with no application package in it; they are
  crossed against the table-name constants the api declares.

The integration tier reads a real database, and it is where the cursor is exercised: a count is SQL
and the rotation cursor is a domain projection, which is the whole reason this reading lives in the
api image rather than beside `pg_dump`.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from ops.config import EVIDENCE_TABLES
from ops.fingerprint import CURSOR_KEYS, DOCUMENT_KEYS
from ops.fingerprint import read as read_document
from sqlalchemy import text

from syncr_api.core.db import create_database
from syncr_api.core.migrations import applied_revision, expected_head
from syncr_api.plans.config import (
    BLOCK_OUTCOMES_TABLE,
    EDIT_EVENTS_TABLE,
    PINS_TABLE,
    PLAN_REVISIONS_TABLE,
    WEEK_ADJUSTMENTS_TABLE,
)
from syncr_api.recovery import fingerprint as writer
from syncr_api.recovery.main import PATH_ENV_VAR, write_document
from syncr_api.recovery.tables import model_modules, registered_tables
from tests.test_alert_rules import repo_root

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession

NOW = datetime(2026, 8, 7, 3, tzinfo=UTC)
HEAD = "0042_pending_weights"


@pytest.fixture
async def session(live_database_url: str) -> AsyncIterator[AsyncSession]:
    """A session of this module's own, so the reading it takes disturbs no other suite."""
    database = create_database(live_database_url)
    try:
        async with database.sessionmaker() as opened:
            yield opened
    finally:
        await database.engine.dispose()


class TestTheDocumentContract:
    """One shape, two interpreters, and no import between them."""

    def test_the_writer_and_the_reader_name_the_same_keys(self) -> None:
        written = {
            writer.KEY_VERSION,
            writer.KEY_TAKEN_AT,
            writer.KEY_EXPECTED_HEAD,
            writer.KEY_APPLIED_REVISION,
            writer.KEY_ROW_COUNTS,
            writer.KEY_CURSORS,
        }

        assert written == set(DOCUMENT_KEYS)

    def test_the_writer_and_the_reader_name_the_same_cursor_keys(self) -> None:
        written = {
            writer.KEY_CURSOR_KEY,
            writer.KEY_CURSOR_INDEX,
            writer.KEY_CURSOR_VARIANT,
            writer.KEY_CURSOR_COMPLETIONS,
        }

        assert written == set(CURSOR_KEYS)

    def test_a_document_the_writer_produces_is_one_the_reader_accepts(self, tmp_path: Path) -> None:
        """The crossing a renamed key on one side only would fail.

        The value fed in is the writer's own dataclass, and the reader is the one the ops image
        runs, so this is the production pair rather than two hand-written documents.
        """
        produced = writer.Fingerprint(
            taken_at=NOW,
            expected_head=HEAD,
            applied_revision=HEAD,
            row_counts={"public.pins": 15},
            cursors=(
                writer.CursorFact(
                    key="tenant/habit", index=1, variant="Back", confirmed_completions=1
                ),
            ),
        )

        found = read_document(write_document(tmp_path / "one.json", produced.as_document()))

        assert found.row_counts == {"public.pins": 15}
        assert found.cursor_by_key()["tenant/habit"].variant == "Back"
        assert found.expected_head == HEAD
        assert found.taken_at == NOW

    def test_the_write_is_atomic_and_leaves_nothing_behind(self, tmp_path: Path) -> None:
        """The reader is another process on a schedule, and half a document is worse than none."""
        write_document(tmp_path / "fingerprint.json", {"version": 1})

        assert [path.name for path in tmp_path.iterdir()] == ["fingerprint.json"]

    def test_the_output_path_is_the_one_compose_states(self) -> None:
        """No default: a refusal writes nothing, so a stale document cannot pass for this run's."""
        assert PATH_ENV_VAR == "SYNCR_FINGERPRINT_PATH"
        assert PATH_ENV_VAR in (repo_root() / "docker-compose.yml").read_text(encoding="utf-8")


class TestTheTablesAreDiscovered:
    """A list nobody maintains, derived from the package and crossed against alembic's own."""

    def test_the_walk_finds_every_model_module(self) -> None:
        found = model_modules()

        assert len(found) >= 17
        assert "syncr_api.plans.models" in found
        assert all(one.endswith(".models") for one in found)

    def test_the_walk_and_alembic_import_the_same_modules(self) -> None:
        """BOTH DIRECTIONS, and each catches a different failure.

        A model module missing from `env.py` is a migration nothing generates. One missing from the
        walk is a table the fingerprint never counts, the dump is never verified against, and the
        drill never checks.
        """
        source = (repo_root() / "packages/syncr-api/alembic/env.py").read_text(encoding="utf-8")
        imported = {
            alias.name
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Import)
            for alias in node.names
            if alias.name.endswith(".models")
        }

        assert imported == set(model_modules())

    def test_the_registered_tables_include_the_ones_the_drill_is_stated_over(self) -> None:
        names = {f"{table.schema or 'public'}.{table.name}" for table in registered_tables()}

        assert set(EVIDENCE_TABLES) <= names

    def test_there_are_far_more_tables_than_the_five(self) -> None:
        """The positive control: a walk finding only the evidence tables would satisfy the above."""
        assert len(registered_tables()) > 30


class TestTheEvidenceTablesAreTheApplicationsOwn:
    """`ops.config` spells them as strings, because it runs where no application package exists."""

    def test_each_one_is_the_constant_the_application_declares(self) -> None:
        assert set(EVIDENCE_TABLES) == {
            f"public.{PLAN_REVISIONS_TABLE}",
            f"public.{BLOCK_OUTCOMES_TABLE}",
            f"public.{PINS_TABLE}",
            f"public.{WEEK_ADJUSTMENTS_TABLE}",
            f"public.{EDIT_EVENTS_TABLE}",
        }


@pytest.mark.integration
class TestTheReadingItself:
    """Against a real database, because a count is SQL and a cursor is a domain projection."""

    async def test_it_counts_every_registered_table(self, session: AsyncSession) -> None:
        found = await writer.read_fingerprint(
            session, now=NOW, expected_head=expected_head(), applied_revision=None
        )

        assert set(found.row_counts) == {
            f"{table.schema or 'public'}.{table.name}" for table in registered_tables()
        }

    async def test_every_evidence_table_is_counted(self, session: AsyncSession) -> None:
        found = await writer.read_fingerprint(
            session, now=NOW, expected_head=expected_head(), applied_revision=None
        )

        for table in EVIDENCE_TABLES:
            assert table in found.row_counts

    async def test_a_count_moves_with_the_rows(self, session: AsyncSession) -> None:
        """Unscoped by design: the question the drill asks is how many rows there are, in total."""
        before = await writer.read_fingerprint(
            session, now=NOW, expected_head=expected_head(), applied_revision=None
        )
        await session.execute(
            text("INSERT INTO tenants (id, created_at) VALUES (gen_random_uuid(), now())")
        )
        after = await writer.read_fingerprint(
            session, now=NOW, expected_head=expected_head(), applied_revision=None
        )
        await session.rollback()

        assert after.row_counts["public.tenants"] == before.row_counts["public.tenants"] + 1

    async def test_the_head_it_reads_is_the_one_the_checkout_ships(
        self, live_database_url: str, session: AsyncSession
    ) -> None:
        """`/readyz` compares the same two values, so a drill's copy satisfies the same check."""
        database = create_database(live_database_url)
        try:
            applied = await applied_revision(database.engine)
        finally:
            await database.engine.dispose()

        found = await writer.read_fingerprint(
            session, now=NOW, expected_head=expected_head(), applied_revision=applied
        )

        assert found.applied_revision == found.expected_head, (
            "the integration database is expected to be at head; `just migrate` puts it there"
        )
