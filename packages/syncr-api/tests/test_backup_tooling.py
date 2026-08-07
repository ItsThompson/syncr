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
from ops import crypto, naming, retention, verify
from ops.config import (
    ARCHIVE_TIMEOUT_SECONDS,
    BACKUP_METRIC,
    DAILY_COPIES,
    MANIFEST_MAX_AGE_SECONDS,
    MONTHLY_COPIES,
    RECOVERY_POINT_OBJECTIVE_SECONDS,
    SHIP_INTERVAL_SECONDS,
    WEEKLY_COPIES,
)
from ops.crypto import EncryptionRefused
from ops.dump import BackupRefused, recent_fingerprint
from ops.exposition import write_gauge
from ops.fetch import NothingToRestore, newest_backup
from ops.prepare import DIRECTORY_MODE, prepare, writable_by_app
from ops.process import Result
from ops.remote import ALLOW_LOCAL, NotOffHost, Remote, off_host_or_refused
from ops.retention import RetentionRefused
from ops.ship import ARCHIVER_STATE, ArchivingFailing, require_archiving_works, staged_segments
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

    def test_a_foreign_object_with_an_embedded_stamp_is_not_a_backup(self) -> None:
        """The pattern is ANCHORED, so `backups_in` and `unclassified` partition a listing.

        With a search rather than a match, `copy-of-syncr-...-elsewhere.tar` was classified as a
        backup: nothing foreign would be deleted, because the delete set is intersected with the
        listing's own names, but a phantom could occupy a daily slot and age a real copy out a night
        early.
        """
        foreign = "copy-of-syncr-20260807T030000Z-elsewhere.tar"

        assert naming.taken_at(foreign) is None
        assert naming.backups_in([foreign]) == ()

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


class TestTheArchiverGuard:
    """The reading that makes the WAL freshness gauge mean anything.

    Both holes it closes are the same shape: an EMPTY staging volume, which a healthy deployment and
    a broken one leave identically. One is reached by a failing `archive_command`, the other by
    archiving switched off, and the second was found by a reviewer driving the shipper against a
    real service in this tree that has no archive settings.

    The rows below are the shape `psql -At` returns for `ARCHIVER_STATE`: seven fields, pipe
    separated, with the pending-failure comparison already made by SQL.
    """

    def test_a_healthy_archiver_is_accepted(self) -> None:
        require_archiving_works(run=_archiver(mode="on", level="replica", pending="f"))

    def test_a_standby_archiving_always_is_accepted(self) -> None:
        require_archiving_works(run=_archiver(mode="always", level="logical", pending="f"))

    def test_archiving_switched_off_is_refused(self) -> None:
        """Zero archived, zero failed, no timestamps: the guard that read failures alone passed."""
        with pytest.raises(ArchivingFailing, match="NOTHING is being archived"):
            require_archiving_works(
                run=_archiver(mode="off", level="replica", pending="f", archived="0", failed="0")
            )

    def test_a_wal_level_that_cannot_be_replayed_is_refused(self) -> None:
        with pytest.raises(ArchivingFailing, match="does not produce WAL a recovery can replay"):
            require_archiving_works(run=_archiver(mode="on", level="minimal", pending="f"))

    def test_a_pending_failure_is_refused(self) -> None:
        with pytest.raises(ArchivingFailing, match="last FAILED to archive"):
            require_archiving_works(
                run=_archiver(
                    mode="on",
                    level="replica",
                    pending="t",
                    archived="3",
                    failed="7",
                    last_archived="2026-08-07 15:59:42+00",
                    last_failed="2026-08-07 16:28:18+00",
                )
            )

    def test_a_failure_it_has_since_recovered_from_is_accepted(self) -> None:
        """The state `ops.prepare` leaves a new deployment in, once the first archive lands."""
        require_archiving_works(
            run=_archiver(
                mode="on",
                level="replica",
                pending="f",
                archived="4",
                failed="7",
                last_archived="2026-08-07 16:30:00+00",
                last_failed="2026-08-07 16:28:18+00",
            )
        )

    def test_the_comparison_is_made_by_sql_rather_than_by_this_module(self) -> None:
        """Two `timestamptz::text` values compare lexically only while the offset is constant."""
        assert "last_failed_time > last_archived_time" in ARCHIVER_STATE
        assert "current_setting('archive_mode')" in ARCHIVER_STATE
        assert "current_setting('wal_level')" in ARCHIVER_STATE

    def test_a_row_that_is_not_the_expected_shape_is_refused(self) -> None:
        """A short row would be read off by one, and every field after it would be another's."""
        with pytest.raises(ArchivingFailing, match="not one row"):
            require_archiving_works(run=FakeRun(answers={"psql": "on|replica"}))


class TestWhatIsShipped:
    """Which files in the staging volume are objects a recovery can read."""

    def test_a_completed_segment_is_shipped_oldest_first(self, tmp_path: Path) -> None:
        """Name order is LSN order is replay order, and a gap is worse than a delay."""
        for name in ("000000010000000000000003", "000000010000000000000001"):
            (tmp_path / name).write_bytes(b"\x00")

        assert [path.name for path in staged_segments(tmp_path)] == [
            "000000010000000000000001",
            "000000010000000000000003",
        ]

    def test_this_modules_own_intermediates_are_not_shipped(self, tmp_path: Path) -> None:
        """Shipping a half-compressed file would put an object in the bucket recovery cannot read"""
        for name in (
            "000000010000000000000001.gz",
            "000000010000000000000001.gz.gpg",
            "000000010000000000000002.tmp",
            "000000010000000000000002.partial",
        ):
            (tmp_path / name).write_bytes(b"\x00")

        assert staged_segments(tmp_path) == ()

    def test_a_timeline_history_file_is_shipped(self, tmp_path: Path) -> None:
        """It is what a point-in-time recovery reads to follow a timeline switch.

        Excluded in the first version, which both left it out of the bucket and left it on the
        volume forever. It is a few hundred bytes and it ships like a segment.
        """
        (tmp_path / "00000002.history").write_bytes(b"1\t0/3000000\tno recovery target\n")

        assert [path.name for path in staged_segments(tmp_path)] == ["00000002.history"]

    def test_a_staging_directory_that_does_not_exist_yet_ships_nothing(
        self, tmp_path: Path
    ) -> None:
        assert staged_segments(tmp_path / "absent") == ()


class TestTheFingerprintTheDumpRequires:
    """The ordering between the two containers `just backup-now` runs, enforced not assumed."""

    def test_a_recent_reading_is_accepted(self, tmp_path: Path) -> None:
        reading = _written_fingerprint(tmp_path)

        found = recent_fingerprint(reading, now=datetime.now(tz=UTC))

        assert found.rows == 1

    def test_a_missing_reading_is_refused(self, tmp_path: Path) -> None:
        """The fingerprint step failed, and a dump nothing describes is not a dump."""
        with pytest.raises(BackupRefused, match="no reading of the live database was taken"):
            recent_fingerprint(tmp_path / "absent.json", now=datetime.now(tz=UTC))

    def test_a_reading_from_an_earlier_run_is_refused(self, tmp_path: Path) -> None:
        """An old manifest uploaded beside a new dump makes a drill compare two different days."""
        reading = _written_fingerprint(tmp_path)
        stale = datetime.now(tz=UTC) + timedelta(seconds=MANIFEST_MAX_AGE_SECONDS + 60)

        with pytest.raises(BackupRefused, match="past the"):
            recent_fingerprint(reading, now=stale)


class TestEncryptionIsNotOptional:
    """Every block title and every anchor location is in that dump."""

    def test_a_missing_recipient_key_refuses_rather_than_uploading_plaintext(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(EncryptionRefused, match="not uploaded in the clear"):
            crypto.encrypt(
                tmp_path / "syncr.dump",
                into=tmp_path / "syncr.dump.gpg",
                public_key=tmp_path / "absent.asc",
                run=FakeRun(),
            )

    def test_it_encrypts_to_the_recipient_file_rather_than_to_a_keyring(
        self, tmp_path: Path
    ) -> None:
        """Nothing imports into a keyring inside an image the next deploy discards."""
        key = tmp_path / "recipient.asc"
        key.write_text("-----BEGIN PGP PUBLIC KEY BLOCK-----\n", encoding="utf-8")
        run = FakeRun()

        crypto.encrypt(tmp_path / "syncr.dump", into=tmp_path / "out.gpg", public_key=key, run=run)

        (call,) = run.argv_for("gpg")
        assert "--recipient-file" in call
        assert str(key) in call
        assert "--encrypt" in call


class TestAnEmptyBucket:
    """The most important thing a drill can discover."""

    def test_a_bucket_with_no_backup_refuses(self) -> None:
        run = FakeRun(answers={"rclone": listing_json([])})

        with pytest.raises(NothingToRestore, match="BackupStale is telling the truth"):
            newest_backup(Remote("offhost:bucket", prefix="dumps", run=run))

    def test_a_bucket_holding_only_foreign_objects_refuses(self) -> None:
        """Nothing this deployment recognises is the same answer as nothing at all."""
        run = FakeRun(
            answers={"rclone": listing_json([("someone-elses.tar.gz", 10, "2026-08-07T03:00:00Z")])}
        )

        with pytest.raises(NothingToRestore):
            newest_backup(Remote("offhost:bucket", prefix="dumps", run=run))

    def test_the_newest_of_several_is_chosen(self) -> None:
        run = FakeRun(
            answers={
                "rclone": listing_json(
                    [
                        ("syncr-20260806T030000Z.dump.gpg", 1, "2026-08-06T03:00:00Z"),
                        ("syncr-20260807T030000Z.dump.gpg", 1, "2026-08-07T03:00:00Z"),
                    ]
                )
            }
        )

        assert (
            newest_backup(Remote("offhost:bucket", prefix="dumps", run=run))
            == "syncr-20260807T030000Z"
        )


class TestPreparingTheVolumes:
    """A fresh named volume belongs to root and neither writer is root."""

    def test_it_creates_each_directory_it_is_asked_for(self, tmp_path: Path) -> None:
        environ = {
            "SYNCR_STAGING_DIR": str(tmp_path / "staging"),
            "SYNCR_SCRATCH_DIR": str(tmp_path / "scratch"),
            "SYNCR_TEXTFILE_DIR": str(tmp_path / "textfile"),
            "SYNCR_WAL_STAGING_DIR": str(tmp_path / "wal"),
        }

        prepared = prepare(environ=environ)

        assert [path.name for path in prepared] == ["staging", "scratch", "wal"]
        for path in prepared:
            assert path.is_dir()

    def test_it_is_idempotent(self, tmp_path: Path) -> None:
        """It runs first in every backup rather than once at provisioning time."""
        environ = {
            "SYNCR_STAGING_DIR": str(tmp_path / "staging"),
            "SYNCR_SCRATCH_DIR": str(tmp_path / "scratch"),
            "SYNCR_TEXTFILE_DIR": str(tmp_path / "textfile"),
            "SYNCR_WAL_STAGING_DIR": str(tmp_path / "wal"),
        }

        prepare(environ=environ)
        prepare(environ=environ)

        assert (tmp_path / "staging").is_dir()

    def test_the_directories_are_not_world_readable(self, tmp_path: Path) -> None:
        """The staging one holds a plaintext dump for as long as it takes to encrypt it."""
        writable_by_app(tmp_path / "staging", environ={})

        assert oct((tmp_path / "staging").stat().st_mode)[-3:] == oct(DIRECTORY_MODE)[-3:]


def _archiver(
    *,
    mode: str,
    level: str,
    pending: str,
    archived: str = "1",
    failed: str = "0",
    last_archived: str = "",
    last_failed: str = "",
) -> FakeRun:
    """A `psql` answering `ARCHIVER_STATE`'s seven fields, in the order the query selects them."""
    row = "|".join((mode, level, archived, failed, pending, last_archived, last_failed))
    return FakeRun(answers={"psql": row})


def _written_fingerprint(directory: Path) -> Path:
    """A fingerprint document on disk, in the shape the api image writes."""
    path = directory / "fingerprint.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "taken_at": "2026-08-07T03:00:00+00:00",
                "expected_head": "0042_pending_weights",
                "applied_revision": "0042_pending_weights",
                "row_counts": {"public.pins": 1},
                "content_digests": {
                    # md5 of the empty string: what an empty table hashes to, so the fixture is a
                    # value production produces rather than an invented one.
                    "public.pins": "d41d8cd98f00b204e9800998ecf8427e"  # pragma: allowlist secret
                },
                "cursors": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def _written(payload: bytes) -> Path:
    """A real file, because :func:`ops.verify.read_header` reads a real one."""
    import tempfile

    path = Path(tempfile.mkdtemp()) / "syncr.dump"
    path.write_bytes(payload)
    return path
