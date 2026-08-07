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
from uuid import UUID

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
            writer.KEY_DIGESTS,
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
            # md5 of the empty string, which is what an empty table hashes to, so the fixture is a
            # value production produces. The scanner reads it as a high-entropy hex string, which is
            # the scan working: it is a digest and not a credential.
            content_digests={
                "public.pins": "d41d8cd98f00b204e9800998ecf8427e"  # pragma: allowlist secret
            },
            cursors=(
                writer.CursorFact(
                    key="tenant/habit", index=1, variant="Back", confirmed_completions=1
                ),
            ),
        )

        found = read_document(write_document(tmp_path / "one.json", produced.as_document()))

        assert found.row_counts == {"public.pins": 15}
        assert found.content_digests == {
            "public.pins": "d41d8cd98f00b204e9800998ecf8427e"  # pragma: allowlist secret
        }
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

    async def test_it_hashes_every_registered_table(self, session: AsyncSession) -> None:
        """The only claim in the verdict that can see a row's bytes, so it covers every table."""
        found = await writer.read_fingerprint(
            session, now=NOW, expected_head=expected_head(), applied_revision=None
        )

        assert set(found.content_digests) == set(found.row_counts)
        for table, digest in found.content_digests.items():
            assert len(digest) == 32, table

    async def test_a_digest_moves_when_a_row_changes_and_the_count_does_not(
        self, session: AsyncSession
    ) -> None:
        """The reading that would have caught a restore whose every plan document was replaced."""
        await session.execute(
            text("INSERT INTO tenants (id, created_at) VALUES (gen_random_uuid(), now())")
        )
        before = await writer.read_fingerprint(
            session, now=NOW, expected_head=expected_head(), applied_revision=None
        )
        await session.execute(text("UPDATE tenants SET created_at = now() - interval '400 days'"))
        after = await writer.read_fingerprint(
            session, now=NOW, expected_head=expected_head(), applied_revision=None
        )
        await session.rollback()

        assert after.row_counts["public.tenants"] == before.row_counts["public.tenants"]
        assert after.content_digests["public.tenants"] != before.content_digests["public.tenants"]

    async def test_two_readings_of_one_database_agree(self, session: AsyncSession) -> None:
        """It is compared across two databases, so it must not depend on the physical row order."""
        first = await writer.read_fingerprint(
            session, now=NOW, expected_head=expected_head(), applied_revision=None
        )
        second = await writer.read_fingerprint(
            session, now=NOW, expected_head=expected_head(), applied_revision=None
        )

        assert first.content_digests == second.content_digests

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

    async def test_a_rotation_habit_with_a_confirmed_completion_derives_its_cursor(
        self, session: AsyncSession
    ) -> None:
        """The cursor is a DOMAIN PROJECTION, and this is the reading that exercises it.

        It is why this whole document is taken by the api image rather than beside `pg_dump`, and
        until the content digests landed it was the only content reading. The derivation is
        `syncr_domain.cursor.cursor_reading` over `HabitOutcomeLog`, which is production's.
        """
        await _seed_a_confirmed_rotation(session)

        found = await writer.read_fingerprint(
            session, now=NOW, expected_head=expected_head(), applied_revision=None
        )
        await session.rollback()

        (fact,) = [one for one in found.cursors if one.key.endswith(str(_HABIT))]
        assert fact.confirmed_completions == 1
        assert fact.index == 1, "one confirmed completion advances the cursor one variant"
        assert fact.variant == "Back"

    async def test_a_habit_that_does_not_rotate_holds_no_cursor(
        self, session: AsyncSession
    ) -> None:
        """A fixed habit repeats one content, so a cursor for it would read as meaningful."""
        await _seed_a_confirmed_rotation(session, binding_source="fixed")

        found = await writer.read_fingerprint(
            session, now=NOW, expected_head=expected_head(), applied_revision=None
        )
        await session.rollback()

        assert [one for one in found.cursors if one.key.endswith(str(_HABIT))] == []


# Identifiers this module's own rows use, so a rolled-back transaction cannot collide with the
# drill's seed or with another module's.
_TENANT = UUID("beef0000-0000-4000-8000-00000000d0d0")
_AREA = UUID("beef0000-0000-4000-8000-00000000a4ea")
_HABIT = UUID("beef0000-0000-4000-8000-00000000bab1")
_REVISION = UUID("beef0000-0000-4000-8000-00000000fee1")


async def _seed_a_confirmed_rotation(
    session: AsyncSession, *, binding_source: str = "rotation"
) -> None:
    """One rotation habit and one confirmed completion of its first occurrence.

    The binding object carries the four keys `stored_binding` writes and the occurrence key the one
    derivation of it produces, so the cursor derives through the reader production uses. If any of
    that were wrong, the assertions above would report zero cursors rather than a wrong one.

    A habit that does not rotate carries NO variants, which the schema enforces: the check
    constraint is what says the two belong together, and honouring it keeps this seed a shape the
    write path could also produce.
    """
    variants = '["Chest", "Back", "Legs", "Shoulders"]' if binding_source == "rotation" else "[]"
    await session.execute(
        text("INSERT INTO tenants (id, created_at) VALUES (:id, now())"), {"id": _TENANT}
    )
    await session.execute(
        text(
            "INSERT INTO areas (id, parent_id, name, pigment_index, created_at, tenant_id) "
            "VALUES (:id, NULL, 'Training', 3, now(), :tenant)"
        ),
        {"id": _AREA, "tenant": _TENANT},
    )
    await session.execute(
        text(
            "INSERT INTO habits (id, area_id, title, cadence_kind, cadence_times_per_week, "
            "duration_min_minutes, duration_max_minutes, miss_policy, binding_source, variants, "
            "debt_cap_periods, created_at, tenant_id) "
            "VALUES (:id, :area, 'Gym', 'times_per_week', 4, 60, 90, 'debt', "
            "cast(:source as varchar), cast(:variants as jsonb), 2, now(), :tenant)"
        ),
        {
            "id": _HABIT,
            "area": _AREA,
            "tenant": _TENANT,
            "source": binding_source,
            "variants": variants,
        },
    )
    await session.execute(
        text(
            "INSERT INTO plan_revisions (id, tenant_id, iso_week, status, reason, document, "
            "objective_breakdown, weight_set_version, input_version, created_at) "
            "VALUES (:id, :tenant, '2026-W32', 'applied', 'materialized', '{}'::jsonb, "
            "'{}'::jsonb, 1, 1, now())"
        ),
        {"id": _REVISION, "tenant": _TENANT},
    )
    await session.execute(
        text(
            "INSERT INTO block_outcomes (id, tenant_id, block_id, binding, revision_id, state, "
            "occurred_at, confirmed_at) VALUES (gen_random_uuid(), :tenant, 'cursor-probe-00', "
            "jsonb_build_object('kind', 'habit', 'entity_id', cast(:habit as text), "
            "'occurrence_key', '00', 'split_index', NULL), :revision, 'completed', now(), now())"
        ),
        {"tenant": _TENANT, "habit": str(_HABIT), "revision": _REVISION},
    )
