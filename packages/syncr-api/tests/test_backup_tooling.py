"""The backup path's pure logic, and every refusal it is built out of.

**AN INSTRUMENT IS WORTHLESS UNTIL IT HAS BEEN SHOWN TO FAIL**, and for a backup that is the whole
ticket: a path that reports success and produces nothing usable is the failure this deployment
cannot detect any other way. So every case below is a refusal, and each names the production shape
it is stated over.

The three external tools are behind :class:`ops.process.Run`, and the fake here records what was
asked of them. WHERE A FAKE RETURNS A VALUE, THE PRODUCTION CALL SITE THAT EMITS IT IS NAMED: the
rclone listing shape comes from `rclone lsjson`, the `pg_restore --list` text is copied from a real
16.10 archive's own output, and the archive header bytes are the first eleven bytes of a real dump.
Those three are the only places this suite invents an external shape.

The end-to-end path, with real `pg_dump`, real gpg and a real restore, is `just drill-local`. This
is the half of the coverage a machine can run in a second.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest
from ops import naming, retention, verify
from ops.config import (
    ARCHIVE_TIMEOUT_SECONDS,
    BACKUP_METRIC,
    DAILY_COPIES,
    MONTHLY_COPIES,
    RECOVERY_POINT_OBJECTIVE_SECONDS,
    SHIP_INTERVAL_SECONDS,
    WEEKLY_COPIES,
)
from ops.exposition import write_gauge
from ops.process import Result
from ops.remote import ALLOW_LOCAL, NotOffHost, Remote, off_host_or_refused
from ops.retention import RetentionRefused
from ops.verify import DumpUnusable

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

# The first eleven bytes of a dump written by `pg_dump --format=custom` in postgres:16.10-bookworm,
# read from a real archive: PGDMP, then archive version 1.15-0, 4-byte integers, 8-byte offsets, and
# format 1 for custom.
REAL_HEADER: Final = b"PGDMP\x01\x0f\x00\x04\x08\x01"

# `pg_restore --list` over that archive, abbreviated. The shape is its own: a serial, an OID pair,
# the entry type, the schema, the object and the owner.
REAL_LISTING: Final = """;
; Archive created at 2026-08-07 15:01:28 UTC
;     dbname: syncr
;     TOC Entries: 222
;     Format: CUSTOM
;
; Selected TOC Entries:
;
215; 1259 16389 TABLE public alembic_version syncr
3775; 0 16389 TABLE DATA public alembic_version syncr
3802; 0 16818 TABLE DATA public anchor_types syncr
3810; 0 16534 TABLE DATA public block_outcomes syncr
"""


@dataclass
class FakeRun:
    """A recording :class:`ops.process.Run`, answering with whatever the case needs.

    Keyed on the tool, because every module here builds its own argv and what a test asserts is the
    argv rather than the answer.
    """

    answers: Mapping[str, str] = field(default_factory=dict)
    statuses: Mapping[str, int] = field(default_factory=dict)
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
        tool = argv[0]
        return Result(
            argv=tuple(argv),
            returncode=self.statuses.get(tool, 0),
            stdout=self.answers.get(tool, ""),
            stderr="",
        )

    def argv_for(self, tool: str) -> tuple[tuple[str, ...], ...]:
        return tuple(call for call in self.calls if call[0] == tool)


def utc(year: int, month: int, day: int, hour: int = 3) -> datetime:
    return datetime(year, month, day, hour, tzinfo=UTC)


def listing_json(entries: Sequence[tuple[str, int, str]]) -> str:
    """A listing in the shape `rclone lsjson` prints: Name, Size, ModTime, IsDir."""
    return json.dumps(
        [
            {"Name": name, "Size": size, "ModTime": modified, "IsDir": False}
            for name, size, modified in entries
        ]
    )


class TestNaming:
    """The instant a retention decision is made from, in the object's own name."""

    def test_a_name_carries_the_instant_it_was_taken(self) -> None:
        assert naming.stamp(utc(2026, 8, 7)) == "syncr-20260807T030000Z"

    def test_the_instant_reads_back_out_of_every_object_of_that_backup(self) -> None:
        name = naming.stamp(utc(2026, 8, 7))

        for object_name in naming.objects_for(name):
            assert naming.taken_at(object_name) == utc(2026, 8, 7)

    def test_a_local_instant_is_stated_in_utc(self) -> None:
        """The schedule is host-local and the name is not: retention sorts on this string."""
        berlin = timezone(timedelta(hours=2))

        assert naming.stamp(datetime(2026, 8, 7, 3, tzinfo=berlin)) == "syncr-20260807T010000Z"

    def test_a_name_this_path_did_not_write_says_so(self) -> None:
        assert naming.taken_at("someone-elses-copy.tar.gz") is None
        assert naming.taken_at("syncr-notatimestamp.dump.gpg") is None

    def test_a_listing_collapses_onto_one_backup_per_pair_newest_first(self) -> None:
        found = naming.backups_in(
            [
                *naming.objects_for(naming.stamp(utc(2026, 8, 6))),
                *naming.objects_for(naming.stamp(utc(2026, 8, 7))),
                "unrelated.txt",
            ]
        )

        assert found == ("syncr-20260807T030000Z", "syncr-20260806T030000Z")


class TestRetention:
    """7 daily, 4 weekly, 6 monthly, and three refusals that delete nothing."""

    def test_a_month_of_nightly_copies_keeps_the_three_classes(self) -> None:
        """August 2026: the 3rd, 10th, 17th, 24th and 31st are Mondays, and the 1st is a Saturday.

        So the three classes are visible separately: seven dailies, the four NEWEST Mondays, and the
        first of the month, which is not a Monday and is kept for being the monthly copy.
        """
        names = [naming.stamp(utc(2026, 8, day)) for day in range(1, 32)]

        plan = retention.plan(names, just_uploaded=names[-1])

        kept = sorted(taken.day for name in plan.keep if (taken := naming.taken_at(name)))
        assert kept == [1, 10, 17, 24, 25, 26, 27, 28, 29, 30, 31]
        assert plan.keep[:DAILY_COPIES] == tuple(
            naming.stamp(utc(2026, 8, day)) for day in range(31, 24, -1)
        ), "the seven dailies are the seven newest"
        assert naming.stamp(utc(2026, 8, 1)) in plan.keep, "the monthly copy, on a Saturday"
        assert naming.stamp(utc(2026, 8, 3)) in plan.delete, (
            "the FIFTH newest Monday, which four weeklies do not reach"
        )

    def test_the_three_classes_overlap_rather_than_partition(self) -> None:
        """A copy is kept when ANY class still wants it, so which claimed it first cannot matter."""
        # 2026-06-01 is a Monday and the first of the month: daily, weekly and monthly at once.
        names = [
            naming.stamp(utc(2026, 6, 1)),
            *[naming.stamp(utc(2026, 6, day)) for day in range(2, 30)],
        ]

        plan = retention.plan(names, just_uploaded=names[-1])

        assert naming.stamp(utc(2026, 6, 1)) in plan.keep

    def test_it_keeps_no_more_than_the_three_counts_allow(self) -> None:
        """A year of nightly copies is bounded, which is what makes the bucket's size a figure."""
        names = [
            naming.stamp(utc(2026, month, day)) for month in range(1, 13) for day in (1, 5, 12)
        ]

        plan = retention.plan(names, just_uploaded=names[-1])

        assert len(plan.keep) <= DAILY_COPIES + WEEKLY_COPIES + MONTHLY_COPIES

    def test_it_refuses_a_listing_that_does_not_hold_what_this_run_uploaded(self) -> None:
        """The wrong bucket, a mistyped prefix and another deployment's copies all look prunable."""
        others = [naming.stamp(utc(2025, 1, day)) for day in range(1, 20)]

        with pytest.raises(RetentionRefused, match="not of the location this run uploaded to"):
            retention.plan(others, just_uploaded=naming.stamp(utc(2026, 8, 7)))

    def test_it_refuses_an_empty_listing(self) -> None:
        """The upload did not land, and deleting on the strength of that is the worst case."""
        with pytest.raises(RetentionRefused):
            retention.plan([], just_uploaded=naming.stamp(utc(2026, 8, 7)))

    def test_one_backup_alone_is_kept(self) -> None:
        """The first night. A plan that deleted here would leave no copy at all."""
        only = naming.stamp(utc(2026, 8, 7))

        plan = retention.plan(naming.objects_for(only), just_uploaded=only)

        assert plan.keep == (only,)
        assert plan.delete == ()

    def test_an_object_it_does_not_recognise_is_kept_and_reported(self) -> None:
        just_uploaded = naming.stamp(utc(2026, 8, 7))
        present = [*naming.objects_for(just_uploaded), "someone-elses.tar.gz", "notes.txt"]

        plan = retention.plan(present, just_uploaded=just_uploaded)

        assert plan.unclassified == ("notes.txt", "someone-elses.tar.gz")
        assert retention.objects_to_delete(present, plan.delete) == ()

    def test_both_objects_of_a_deleted_backup_go_together(self) -> None:
        """A dump whose fingerprint was deleted cannot be checked after a restore."""
        names = [naming.stamp(utc(2026, 8, day)) for day in range(1, 32)]
        present = [name for one in names for name in naming.objects_for(one)]

        plan = retention.plan(present, just_uploaded=names[-1])
        removing = retention.objects_to_delete(present, plan.delete)

        for name in plan.delete:
            assert naming.dump_object(name) in removing
            assert naming.manifest_object(name) in removing

    def test_it_never_deletes_an_object_a_listing_did_not_hold(self) -> None:
        """A backup whose fingerprint upload failed must not produce a delete for a missing one."""
        names = [naming.stamp(utc(2026, 8, day)) for day in range(1, 32)]
        present = [naming.dump_object(one) for one in names]

        plan = retention.plan(present, just_uploaded=names[-1])

        assert all(
            name.endswith(".dump.gpg") for name in retention.objects_to_delete(present, plan.delete)
        )


class TestWalRetention:
    """WAL is kept as far back as the oldest dump it could be replayed onto."""

    def test_it_deletes_only_segments_older_than_the_oldest_kept_dump(self) -> None:
        oldest_kept = utc(2026, 8, 1)
        segments = [
            ("000000010000000000000001.gz.gpg", utc(2026, 7, 20)),
            ("000000010000000000000002.gz.gpg", utc(2026, 7, 31)),
            ("000000010000000000000003.gz.gpg", utc(2026, 8, 2)),
        ]

        stale = retention.wal_to_delete(segments, oldest_kept_backup=oldest_kept)

        assert stale == ("000000010000000000000001.gz.gpg",), "the margin keeps the day before"

    def test_it_never_deletes_the_newest_segment(self) -> None:
        """That one is the deployment's current recovery point and the shipper's own evidence."""
        segments = [("000000010000000000000009.gz.gpg", utc(2020, 1, 1))]

        assert retention.wal_to_delete(segments, oldest_kept_backup=utc(2026, 8, 1)) == ()

    def test_an_empty_prefix_deletes_nothing(self) -> None:
        assert retention.wal_to_delete([], oldest_kept_backup=utc(2026, 8, 1)) == ()


class TestVerify:
    """Three readings, because a dump that reports success and restores nothing is the failure."""

    def test_a_real_header_reads_as_a_custom_format_archive(self) -> None:
        dump = _written(REAL_HEADER + b"\x00" * 4096)

        header = verify.read_header(dump)

        assert header.version == "1.15-0"
        assert header.integer_bytes == 4
        assert header.offset_bytes == 8

    def test_it_refuses_a_dump_that_succeeded_and_wrote_nothing(self) -> None:
        with pytest.raises(DumpUnusable, match="A dump that succeeded and wrote nothing"):
            verify.read_header(_written(b""))

    def test_it_refuses_a_file_that_is_not_an_archive(self) -> None:
        with pytest.raises(DumpUnusable, match="not a Postgres archive"):
            verify.read_header(_written(b"-- PostgreSQL database dump\n" + b"x" * 4096))

    def test_it_refuses_an_archive_that_is_not_custom_format(self) -> None:
        """The restore procedure and every figure in it assume --format=custom."""
        tar_format = b"PGDMP\x01\x0f\x00\x04\x08\x03"

        with pytest.raises(DumpUnusable, match="not custom"):
            verify.read_header(_written(tar_format + b"\x00" * 4096))

    def test_it_refuses_a_path_that_does_not_exist(self) -> None:
        with pytest.raises(DumpUnusable, match="0 bytes"):
            verify.read_header(Path("/nonexistent/syncr.dump"))

    def test_it_reads_the_tables_a_real_listing_names(self) -> None:
        assert verify.data_tables(REAL_LISTING) == {
            "public.alembic_version",
            "public.anchor_types",
            "public.block_outcomes",
        }

    def test_a_definition_without_data_is_not_a_data_entry(self) -> None:
        """`TABLE` and `TABLE DATA` are different entries; a schema-only dump has only the first."""
        assert "public.alembic_version" in verify.data_tables(REAL_LISTING)
        assert (
            verify.data_tables("215; 1259 16389 TABLE public alembic_version syncr\n")
            == frozenset()
        )

    def test_it_refuses_a_dump_of_another_database(self) -> None:
        expected = frozenset({"public.alembic_version", "public.plan_revisions"})

        with pytest.raises(DumpUnusable, match="plan_revisions"):
            verify.require_tables(REAL_LISTING, expected=expected)

    def test_it_accepts_a_dump_carrying_every_table_the_fingerprint_counted(self) -> None:
        verify.require_tables(REAL_LISTING, expected=frozenset({"public.block_outcomes"}))


class TestOffHost:
    """A backup on the same disk as the database is not a backup."""

    def test_a_configured_bucket_is_off_host(self) -> None:
        off_host_or_refused("offhost:syncr-backups", {"RCLONE_CONFIG_OFFHOST_TYPE": "s3"})

    def test_a_bare_path_is_refused(self) -> None:
        with pytest.raises(NotOffHost, match="same disk"):
            off_host_or_refused("/var/backups/syncr", {})

    def test_a_remote_configured_as_local_is_refused(self) -> None:
        """The guard reads the SAME variable rclone resolves the remote from."""
        with pytest.raises(NotOffHost, match="type 'local'"):
            off_host_or_refused(
                "localbucket:/var/backups", {"RCLONE_CONFIG_LOCALBUCKET_TYPE": "local"}
            )

    def test_the_escape_hatch_is_named_and_explicit(self) -> None:
        """`just drill-local` sets it, and it is the only thing in the tree that does."""
        off_host_or_refused("localbucket:/tmp/bucket", {ALLOW_LOCAL: "1"})


class TestTheRemote:
    """rclone, as the four operations a caller means."""

    def test_an_upload_names_the_object_rather_than_a_directory(self) -> None:
        """`copyto`, not `copy`: `copy` takes a directory and would nest the file under the name."""
        run = FakeRun()
        remote = Remote("offhost:bucket", prefix="dumps", run=run)

        remote.upload(Path("/var/backups/syncr/one.dump.gpg"), "syncr-20260807T030000Z.dump.gpg")

        assert run.argv_for("rclone") == (
            (
                "rclone",
                "copyto",
                "/var/backups/syncr/one.dump.gpg",
                "offhost:bucket/dumps/syncr-20260807T030000Z.dump.gpg",
            ),
        )

    def test_a_listing_reads_the_shape_lsjson_prints(self) -> None:
        run = FakeRun(
            answers={
                "rclone": listing_json(
                    [("syncr-20260807T030000Z.dump.gpg", 16987, "2026-08-07T03:00:04.123456789Z")]
                )
            }
        )
        remote = Remote("offhost:bucket", prefix="dumps", run=run)

        (entry,) = remote.listing()

        assert entry.name == "syncr-20260807T030000Z.dump.gpg"
        assert entry.size == 16987
        assert entry.modified_at == datetime(2026, 8, 7, 3, 0, 4, 123456, tzinfo=UTC)

    def test_a_prefix_that_does_not_exist_reads_as_empty(self) -> None:
        """rclone exits 3 for it, and on the first night the WAL prefix holds nothing."""
        run = FakeRun(statuses={"rclone": 3})
        remote = Remote("offhost:bucket", prefix="wal", run=run)

        assert remote.listing() == ()

    def test_any_other_failure_is_raised(self) -> None:
        """A credential that cannot list is not an empty bucket."""
        run = FakeRun(statuses={"rclone": 1})
        remote = Remote("offhost:bucket", prefix="dumps", run=run)

        with pytest.raises(Exception, match="could not list"):
            remote.listing()


class TestExposition:
    """Publishing from a process that has exited, atomically."""

    def test_it_writes_a_gauge_the_textfile_collector_can_parse(self, tmp_path: Path) -> None:
        written = write_gauge(
            tmp_path / "textfile", family=BACKUP_METRIC, help_text="Unix time.", value=1786000000.0
        )

        assert written.name == f"{BACKUP_METRIC}.prom"
        assert written.read_text() == (
            f"# HELP {BACKUP_METRIC} Unix time.\n"
            f"# TYPE {BACKUP_METRIC} gauge\n"
            f"{BACKUP_METRIC} 1786000000\n"
        )

    def test_it_leaves_no_temporary_file_behind(self, tmp_path: Path) -> None:
        """A half-written file in that directory sets `node_textfile_scrape_error` and discards the
        whole directory, which would take the learning job's exposition down with the backup's."""
        write_gauge(tmp_path, family=BACKUP_METRIC, help_text="Unix time.", value=1.0)

        assert [path.name for path in tmp_path.iterdir()] == [f"{BACKUP_METRIC}.prom"]

    def test_a_second_write_replaces_the_first(self, tmp_path: Path) -> None:
        write_gauge(tmp_path, family=BACKUP_METRIC, help_text="Unix time.", value=1.0)
        write_gauge(tmp_path, family=BACKUP_METRIC, help_text="Unix time.", value=2.0)

        assert (tmp_path / f"{BACKUP_METRIC}.prom").read_text().endswith(f"{BACKUP_METRIC} 2\n")


class TestTheRecoveryPointArithmetic:
    """The objective is a promise, and two configuration figures are what keep it."""

    def test_the_archive_timeout_and_the_ship_interval_fit_inside_the_objective(self) -> None:
        """A commit sits unshipped for one archive timeout plus one ship interval, no more."""
        worst_case = ARCHIVE_TIMEOUT_SECONDS + SHIP_INTERVAL_SECONDS

        assert worst_case < RECOVERY_POINT_OBJECTIVE_SECONDS


def _written(payload: bytes) -> Path:
    """A real file, because :func:`ops.verify.read_header` reads a real one."""
    import tempfile

    path = Path(tempfile.mkdtemp()) / "syncr.dump"
    path.write_bytes(payload)
    return path
