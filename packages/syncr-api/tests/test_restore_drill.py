"""The restore drill's own guards, and the verdict it prints.

**A DRILL THAT CANNOT FAIL PROVES NOTHING**, so every case here is one of the ways a drill passes
while the backup path is broken:

- restored into the database it was dumped from
- restored into a database that already held tables, so the result is neither copy
- reported a pass over tables that were empty when the dump was taken
- reported a pass over a cursor that had never advanced
- reported a pass while rows were lost
- reported a pass on a copy at a migration head `/readyz` would refuse
- reported a pass on a recovery that took longer than the objective it promises

The fingerprints below are the shape the api image's `syncr-plan-fingerprint` writes, and
``test_recovery_fingerprint.py`` crosses that writer's own key constants against the reader's, so
these documents cannot be a shape production never produces.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

import pytest
from ops import fingerprint
from ops.config import EVIDENCE_TABLES, RECOVERY_TIME_OBJECTIVE_SECONDS
from ops.environment import ConfigurationMissing, Target, live_target
from ops.fingerprint import FingerprintUnreadable
from ops.process import Result
from ops.restore import RestoreRefused, refuse_the_live_database, require_empty
from ops.verdict import compare

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

HEAD = "0042_pending_weights"


@dataclass
class FakeRun:
    """A recording :class:`ops.process.Run` for the two psql readings the restore takes."""

    answers: Mapping[str, str] = field(default_factory=dict)
    calls: list[tuple[str, ...]] = field(default_factory=list)

    def __call__(
        self,
        argv: Sequence[str],
        *,
        stdout_path: Path | None = None,
        stdin_path: Path | None = None,
        environ: Mapping[str, str] | None = None,
        check: bool = True,
    ) -> Result:
        self.calls.append(tuple(argv))
        return Result(
            argv=tuple(argv), returncode=0, stdout=self.answers.get(argv[0], ""), stderr=""
        )


def document(
    *,
    counts: dict[str, int] | None = None,
    digests: dict[str, str] | None = None,
    cursors: list[dict[str, Any]] | None = None,
    applied: str | None = HEAD,
    expected: str = HEAD,
) -> dict[str, Any]:
    """A fingerprint document, in the shape `syncr-plan-fingerprint` writes.

    The default counts give every evidence table a row, because that is the state a real deployment
    is in and the state the verdict's own evidence check requires. The default digests give each of
    them the same hash on both sides, so a case that is not about content does not fail on it.
    """
    tables = counts if counts is not None else dict.fromkeys(EVIDENCE_TABLES, 1)
    return {
        fingerprint.KEY_VERSION: 1,
        fingerprint.KEY_TAKEN_AT: "2026-08-07T03:00:00+00:00",
        fingerprint.KEY_EXPECTED_HEAD: expected,
        fingerprint.KEY_APPLIED_REVISION: applied,
        fingerprint.KEY_ROW_COUNTS: tables,
        fingerprint.KEY_DIGESTS: (
            digests if digests is not None else {table: f"digest-of-{table}" for table in tables}
        ),
        fingerprint.KEY_CURSORS: cursors
        if cursors is not None
        else [
            {
                fingerprint.KEY_CURSOR_KEY: "tenant/habit",
                fingerprint.KEY_CURSOR_INDEX: 1,
                fingerprint.KEY_CURSOR_VARIANT: "Back",
                fingerprint.KEY_CURSOR_COMPLETIONS: 1,
            }
        ],
    }


def cursor(
    *, index: int = 1, variant: str = "Back", completions: int = 1, key: str = "tenant/habit"
) -> dict[str, Any]:
    """One cursor entry, so a case can change exactly one field of it."""
    return {
        fingerprint.KEY_CURSOR_KEY: key,
        fingerprint.KEY_CURSOR_INDEX: index,
        fingerprint.KEY_CURSOR_VARIANT: variant,
        fingerprint.KEY_CURSOR_COMPLETIONS: completions,
    }


def read(
    document_: dict[str, Any], tmp_path: Path, name: str = "one.json"
) -> fingerprint.Fingerprint:
    path = tmp_path / name
    path.write_text(json.dumps(document_), encoding="utf-8")
    return fingerprint.read(path)


class TestRefusingTheLiveDatabase:
    """A drill that restores into the database it was dumped from proves nothing and destroys it."""

    def test_the_scratch_instance_is_accepted(self) -> None:
        refuse_the_live_database(
            Target(host="postgres-restore", port="5432", database="syncr_restore"),
            Target(host="postgres", port="5432", database="syncr"),
        )

    def test_the_live_database_is_refused(self) -> None:
        with pytest.raises(RestoreRefused, match="IS the live database"):
            refuse_the_live_database(
                Target(host="postgres", port="5432", database="syncr"),
                Target(host="postgres", port="5432", database="syncr"),
            )

    def test_the_same_host_with_another_database_is_accepted(self) -> None:
        """The scratch instance could legitimately be another database on one server."""
        refuse_the_live_database(
            Target(host="postgres", port="5432", database="syncr_restore"),
            Target(host="postgres", port="5432", database="syncr"),
        )

    def test_a_drill_that_does_not_know_what_production_is_refuses(self) -> None:
        """Fail closed. A drill with no live target cannot decline to overwrite it."""
        with pytest.raises(ConfigurationMissing, match="SYNCR_LIVE_PGHOST"):
            live_target({})

    def test_the_live_target_is_read_from_the_variables_compose_sets(self) -> None:
        """Named in `docker-compose.restore.yml`, where the drill's topology is declared."""
        found = live_target(
            {
                "SYNCR_LIVE_PGHOST": "postgres",
                "SYNCR_LIVE_PGPORT": "5432",
                "SYNCR_LIVE_PGDATABASE": "syncr",
            }
        )

        assert str(found) == "postgres:5432/syncr"


class TestRefusingATargetThatHoldsTables:
    """`pg_restore` into a populated database applies what it can, so the result is neither copy."""

    def test_an_empty_target_is_accepted(self) -> None:
        require_empty(run=FakeRun(answers={"psql": "0"}))

    def test_a_target_that_already_holds_tables_is_refused(self) -> None:
        with pytest.raises(RestoreRefused, match="already holds 36 tables"):
            require_empty(run=FakeRun(answers={"psql": "36"}))

    def test_the_reading_is_over_the_schema_a_dump_restores_into(self) -> None:
        run = FakeRun(answers={"psql": "0"})

        require_empty(run=run)

        (call,) = run.calls
        assert "pg_tables" in call[-1]
        assert "schemaname = 'public'" in call[-1]


class TestTheFingerprintReader:
    """Reading is strict, because a document that cannot be read is not an empty database."""

    def test_it_reads_the_shape_the_api_image_writes(self, tmp_path: Path) -> None:
        found = read(document(), tmp_path)

        assert found.expected_head == HEAD
        assert found.applied_revision == HEAD
        assert found.rows == len(EVIDENCE_TABLES)
        assert found.tables == frozenset(EVIDENCE_TABLES)
        assert found.cursor_by_key()["tenant/habit"].variant == "Back"

    def test_a_missing_key_is_a_refusal(self, tmp_path: Path) -> None:
        incomplete = document()
        del incomplete[fingerprint.KEY_ROW_COUNTS]

        with pytest.raises(FingerprintUnreadable, match="row_counts"):
            read(incomplete, tmp_path)

    def test_a_document_with_no_counts_is_a_refusal(self, tmp_path: Path) -> None:
        """An empty count map would compare equal to another empty one, and pass."""
        with pytest.raises(FingerprintUnreadable, match="no row counts"):
            read(document(counts={}), tmp_path)

    def test_a_document_with_no_digests_is_a_refusal(self, tmp_path: Path) -> None:
        """THE MIRROR OF THE COUNTS REFUSAL, and it had no test until a reviewer deleted it.

        With the raise replaced by `return {}`, 212 tests passed either way, and the only content
        claim then read "every one of the 0 tables hashes identically, so the rows came back byte
        for byte" as a PASS. That is a drill reporting success over nothing, which is the class the
        digest was added to close.
        """
        with pytest.raises(FingerprintUnreadable, match="no content digests"):
            read(document(digests={}), tmp_path)

    def test_a_digest_that_is_not_a_string_is_a_refusal(self, tmp_path: Path) -> None:
        with pytest.raises(FingerprintUnreadable, match="as the digest"):
            read(document(digests={"public.pins": 12}), tmp_path)  # type: ignore[dict-item]

    def test_an_empty_digest_is_a_refusal(self, tmp_path: Path) -> None:
        """An empty string is not a hash, and it would compare equal to another empty string."""
        with pytest.raises(FingerprintUnreadable, match="as the digest"):
            read(document(digests={"public.pins": ""}), tmp_path)

    def test_a_document_missing_the_digest_key_is_a_refusal(self, tmp_path: Path) -> None:
        """The key is in `DOCUMENT_KEYS`, so an older document is refused rather than half-read."""
        incomplete = document()
        del incomplete[fingerprint.KEY_DIGESTS]

        with pytest.raises(FingerprintUnreadable, match=fingerprint.KEY_DIGESTS):
            read(incomplete, tmp_path)

    def test_a_count_that_is_not_a_number_is_a_refusal(self, tmp_path: Path) -> None:
        with pytest.raises(FingerprintUnreadable, match="as the count"):
            read(document(counts={"public.pins": "many"}), tmp_path)  # type: ignore[dict-item]

    def test_an_incomplete_cursor_is_a_refusal(self, tmp_path: Path) -> None:
        with pytest.raises(FingerprintUnreadable, match="incomplete cursor"):
            read(document(cursors=[{fingerprint.KEY_CURSOR_KEY: "tenant/habit"}]), tmp_path)

    def test_a_file_that_is_not_json_is_a_refusal(self, tmp_path: Path) -> None:
        path = tmp_path / "broken.json"
        path.write_text("half a document", encoding="utf-8")

        with pytest.raises(FingerprintUnreadable):
            fingerprint.read(path)


class TestTheVerdict:
    """Seven claims, and each one is a way a drill passes while the path is broken."""

    def test_a_restore_that_came_back_whole_holds_every_claim(self, tmp_path: Path) -> None:
        before = read(document(), tmp_path, "before.json")
        after = read(document(), tmp_path, "after.json")

        verdict = compare(before, after, elapsed_seconds=17)

        assert verdict.held, [str(one) for one in verdict.failures]
        assert len(verdict.findings) == 8

    def test_content_that_changed_with_the_counts_intact_fails(self, tmp_path: Path) -> None:
        """THE HOLE THIS CLAIM CLOSES, and it was demonstrated on a running deployment.

        A reviewer replaced every `plan_revisions` document, set `iso_week` to 1999-W01 and moved
        every pin four hundred days. Every count was identical, the cursor was unchanged, and the
        verdict printed seven PASS and "the data came back".
        """
        before = read(document(), tmp_path, "b.json")
        after = read(
            document(
                digests={
                    **{table: f"digest-of-{table}" for table in EVIDENCE_TABLES},
                    "public.plan_revisions": "the-plan-the-restore-lost",
                }
            ),
            tmp_path,
            "a.json",
        )

        verdict = compare(before, after, elapsed_seconds=17)

        assert not verdict.held
        assert "content differs" in str(verdict.failures[0])
        assert "plan_revisions" in str(verdict.failures[0])

    def test_a_table_that_was_not_hashed_after_the_restore_fails(self, tmp_path: Path) -> None:
        """A missing digest is not a matching one."""
        before = read(document(), tmp_path, "b.json")
        after = read(document(digests={"public.pins": "digest-of-public.pins"}), tmp_path, "a.json")

        verdict = compare(before, after, elapsed_seconds=17)

        assert not verdict.held
        assert "were not hashed after the restore" in str(verdict.failures[0])

    def test_the_content_claim_names_how_many_tables_it_read(self, tmp_path: Path) -> None:
        """A claim that read nothing would otherwise be indistinguishable from one that held."""
        before = read(document(), tmp_path, "b.json")

        (finding,) = [
            one
            for one in compare(before, before, elapsed_seconds=17).findings
            if "hashes" in one.claim
        ]

        assert f"{len(EVIDENCE_TABLES)} tables hashes identically" in finding.claim

    def test_a_comparison_over_zero_hashed_tables_fails(self, tmp_path: Path) -> None:
        """THE TWO GUARDS ARE INDEPENDENT NOW, not sequential.

        `ops.fingerprint` refuses a document with no digests, so the verdict could only be reached
        this way by a caller building one directly. With the parser's refusal deleted, this claim
        held over zero tables and printed "byte for byte": a claim that cannot fail.
        """
        before = read(document(), tmp_path, "b.json")
        hollow = replace(before, content_digests={})

        verdict = compare(hollow, hollow, elapsed_seconds=17)

        assert not verdict.held
        assert "no table was hashed before the dump" in str(verdict.failures[0])

    def test_a_lost_row_fails(self, tmp_path: Path) -> None:
        """The whole reconciliation: count in, count out."""
        before = read(
            document(counts={**dict.fromkeys(EVIDENCE_TABLES, 1), "public.pins": 15}),
            tmp_path,
            "b.json",
        )
        after = read(
            document(counts={**dict.fromkeys(EVIDENCE_TABLES, 1), "public.pins": 14}),
            tmp_path,
            "a.json",
        )

        verdict = compare(before, after, elapsed_seconds=17)

        assert not verdict.held
        assert "rows were lost" in str(verdict.failures[0])

    def test_a_row_written_between_the_reading_and_the_dump_fails_on_content_not_on_the_count(
        self, tmp_path: Path
    ) -> None:
        """The two claims are deliberately asymmetric, and this is the case that shows why.

        The manifest is read BEFORE the dump's snapshot, so the copy is a SUPERSET and the count
        claim is a floor: a row appended in that window does not fail it. The digest is over the set
        of rows, so the same row DOES change it, and that is reported as a failure rather than
        tolerated, because a comparison that cannot distinguish a write from a loss is not a
        comparison. The message says which of the two it is and what to do about it.
        """
        before = read(
            document(counts={**dict.fromkeys(EVIDENCE_TABLES, 1), "public.pins": 14}),
            tmp_path,
            "b.json",
        )
        after = read(
            document(
                counts={**dict.fromkeys(EVIDENCE_TABLES, 1), "public.pins": 15},
                digests={
                    **{table: f"digest-of-{table}" for table in EVIDENCE_TABLES},
                    "public.pins": "one-more-pin-than-the-reading-saw",
                },
            ),
            tmp_path,
            "a.json",
        )

        verdict = compare(before, after, elapsed_seconds=17)

        counts, contents = verdict.findings[1], verdict.findings[2]
        assert counts.held, "the count claim is a floor, and a superset satisfies it"
        assert not contents.held
        assert "re-run the drill" in contents.claim

    def test_a_table_that_vanished_fails(self, tmp_path: Path) -> None:
        """A count cannot report a table whose count went missing with it."""
        before = read(document(), tmp_path, "b.json")
        after = read(document(counts={"public.pins": 1}), tmp_path, "a.json")

        verdict = compare(before, after, elapsed_seconds=17)

        assert not verdict.held
        assert "tables are absent" in str(verdict.failures[0])

    def test_a_drill_over_empty_evidence_tables_fails(self, tmp_path: Path) -> None:
        """AN EMPTY TABLE RESTORES PERFECTLY. This is the most convincing false pass there is."""
        empty = read(document(counts=dict.fromkeys(EVIDENCE_TABLES, 0)), tmp_path, "b.json")

        verdict = compare(empty, empty, elapsed_seconds=17)

        assert not verdict.held
        assert "proves nothing about them" in str(verdict.failures[0])

    def test_a_drill_over_a_cursor_that_never_advanced_fails(self, tmp_path: Path) -> None:
        """A cursor at index 0 with no confirmations re-derives correctly from no data at all."""
        before = read(document(cursors=[cursor(index=0, variant="Chest", completions=0)]), tmp_path)

        verdict = compare(before, before, elapsed_seconds=17)

        assert not verdict.held
        assert "no rotation cursor had advanced" in str(verdict.failures[0])

    def test_a_cursor_that_re_derives_to_another_index_fails(self, tmp_path: Path) -> None:
        before = read(document(), tmp_path, "b.json")
        after = read(document(cursors=[cursor(index=0)]), tmp_path, "a.json")

        verdict = compare(before, after, elapsed_seconds=17)

        assert not verdict.held
        assert "re-derive differently" in str(verdict.failures[0])

    def test_a_cursor_that_re_derives_to_another_variant_fails(self, tmp_path: Path) -> None:
        """A restore that lost one confirmation trains the wrong muscle group, unnoticed.

        ONE FIELD, and that is the point: the first version of this changed the index, the variant
        and the completion count together, so it passed through the index while `_cursors_rederive`
        never compared the variant its own claim is stated in terms of.
        """
        before = read(document(), tmp_path, "b.json")
        after = read(document(cursors=[cursor(variant="Chest")]), tmp_path, "a.json")

        verdict = compare(before, after, elapsed_seconds=17)

        assert not verdict.held
        assert "re-derive differently" in str(verdict.failures[0])
        assert "'Back', 'Chest'" in str(verdict.failures[0])

    def test_a_cursor_whose_completion_count_changed_fails(self, tmp_path: Path) -> None:
        """The count is what the index is derived FROM, so a matching index over another count is a
        database that will diverge on its next confirmation."""
        before = read(document(), tmp_path, "b.json")
        after = read(document(cursors=[cursor(completions=5)]), tmp_path, "a.json")

        verdict = compare(before, after, elapsed_seconds=17)

        assert not verdict.held
        assert "re-derive differently" in str(verdict.failures[0])

    def test_a_cursor_that_vanished_fails(self, tmp_path: Path) -> None:
        before = read(document(), tmp_path, "b.json")
        after = read(document(cursors=[]), tmp_path, "a.json")

        verdict = compare(before, after, elapsed_seconds=17)

        assert not verdict.held
        assert "absent" in str(verdict.failures[0])

    def test_a_copy_at_another_migration_head_fails(self, tmp_path: Path) -> None:
        """`/readyz` would refuse it, and a drill without this check would not mention it."""
        before = read(document(), tmp_path, "b.json")
        after = read(document(applied="0039_conflicts"), tmp_path, "a.json")

        verdict = compare(before, after, elapsed_seconds=17)

        assert not verdict.held
        assert "would refuse traffic" in str(verdict.failures[0])

    def test_a_recovery_past_the_objective_fails(self, tmp_path: Path) -> None:
        """An hour is the promise. A drill that took three is a drill that disproved it."""
        before = read(document(), tmp_path, "b.json")

        verdict = compare(before, before, elapsed_seconds=RECOVERY_TIME_OBJECTIVE_SECONDS + 1)

        assert not verdict.held
        assert "recovery time objective" in str(verdict.failures[0])

    def test_the_objective_boundary_itself_holds(self, tmp_path: Path) -> None:
        before = read(document(), tmp_path, "b.json")

        assert compare(before, before, elapsed_seconds=RECOVERY_TIME_OBJECTIVE_SECONDS).held

    def test_every_finding_states_its_claim_whether_it_held_or_not(self, tmp_path: Path) -> None:
        """A drill printing only failures leaves a pass indistinguishable from no checks."""
        before = read(document(), tmp_path, "b.json")

        verdict = compare(before, before, elapsed_seconds=17)

        for finding in verdict.findings:
            assert str(finding).startswith("PASS  ")
            assert len(finding.claim) > 40


class TestTheEvidenceTables:
    """The five the ticket names, and the fact that a drill is stated over them at all."""

    def test_there_are_five_and_each_is_schema_qualified(self) -> None:
        assert len(EVIDENCE_TABLES) == 5
        for table in EVIDENCE_TABLES:
            assert table.startswith("public.")

    def test_they_name_the_plan_history_outcomes_pins_adjustments_and_edit_events(self) -> None:
        assert set(EVIDENCE_TABLES) == {
            "public.plan_revisions",
            "public.block_outcomes",
            "public.pins",
            "public.week_adjustments",
            "public.edit_events",
        }
