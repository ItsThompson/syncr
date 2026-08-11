"""How an archived WAL segment reaches the Postgres container, and every refusal on the way.

The seam is a recovery that has to read the bucket and a database container that deliberately holds
no bucket credential. ``archive_command`` never makes a network call on the way out; this is the
same rule on the way back, so the segment travels through a volume:

    bucket ──ops.fetch_segment──▶ the scratch volume ──restore_command──▶ the recovery's pg_wal

Every case below is one of the ways that path reports success and delivers nothing a recovery can
replay:

- a partial download under the name Postgres asks for
- a segment staged where the shipper will upload it again and then delete it
- a segment the database's own user cannot read
- an object name one direction spells differently from the other
- a `restore_command` that reaches for a tool the deployment's Postgres image does not carry

The two external tools are behind :class:`ops.process.Run`. The fake here LEAVES THE FILES the real
ones would leave, because what this path is about is which file exists under which name: a fake that
only recorded argv would pass over a chain that wrote nothing. The whole path with real gpg, real
rclone, a real bucket and a real recovery is driven by hand; ``changesets/`` carries that run.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import pytest
from ops import fetch_segment as staging
from ops import naming, ship
from ops.config import SCRATCH_DIR, WAL_RESTORE_DIR
from ops.prepare import FILE_MODE
from ops.process import CommandFailed, Result

from tests.test_deploy_topology import resolved, services

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

# A segment name Postgres wrote, and the object the shipper uploads it as. THE OBJECT NAME IS A
# LITERAL HERE, on purpose: it is the one fact the shipping direction and the recovery direction
# have to agree on, and a test that derived it from the same helper both of them call could not see
# them disagree.
SEGMENT: Final = "000000010000000000000003"
SHIPPED_OBJECT: Final = "000000010000000000000003.gz.gpg"

# What one segment's bytes are, standing in for 16 MB of transaction records.
SEGMENT_BYTES: Final = b"the records between one checkpoint and the next"

DRILL_FILES: Final = (
    "docker-compose.yml",
    "docker-compose.restore.yml",
    "docker-compose.deploy.yml",
)

# The service the recovery runs in, and the one image in this repository that carries rclone.
RECOVERY_SERVICE: Final = "postgres-restore"
OPS_SERVICE: Final = "ops"
LIVE_SERVICE: Final = "postgres"

# The settings Postgres compares between the server that WROTE the WAL and the instance replaying
# it. An instance configured below any of them aborts at startup rather than replaying, naming the
# setting: measured, with the drill's own `max_connections` at 20 against the live database's 50.
COMPARED_SETTINGS: Final = (
    "max_connections",
    "max_worker_processes",
    "max_wal_senders",
    "max_prepared_transactions",
    "max_locks_per_transaction",
)


@dataclass
class FakeTools:
    """A recording :class:`ops.process.Run` that leaves the files rclone, gpg and gzip would leave.

    ``rclone lsjson`` answers the bucket's listing, ``rclone copyto`` writes the object, ``gpg
    --decrypt`` copies it to its output, and ``gzip --decompress`` writes the decompressed name and
    removes its input.

    ``fails_at`` NAMES A STEP RATHER THAN A TOOL, and that is not a nicety: gpg is called twice,
    once to import the private key and once to decrypt, so a fake failing on `gpg` fails the import
    and the run never reaches a download at all. Measured -- it made a case about what a failed
    decryption leaves behind pass over a run that had fetched nothing.
    """

    held: tuple[str, ...] = (SHIPPED_OBJECT,)
    payload: bytes = SEGMENT_BYTES
    fails_at: str | None = None
    half_written: bool = False
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
        step = _step(argv)
        if step is not None and step == self.fails_at and not self.half_written:
            raise CommandFailed(f"{argv[0]} exited 1: driven to fail at {step}")
        if step == "listing":
            return self._answer(argv, stdout=_listing(self.held))
        if step == "download":
            Path(argv[3]).write_bytes(b"encrypted " + self.payload)
            return self._answer(argv)
        if step == "decrypt":
            output = Path(argv[argv.index("--output") + 1])
            output.write_bytes(Path(argv[-1]).read_bytes())
            return self._answer(argv)
        if step == "decompress":
            source = Path(argv[-1])
            decompressed = source.with_suffix("")
            if self.half_written:
                # What a killed or out-of-space `gzip` leaves: some of the segment, under the name
                # the complete one would have had.
                decompressed.write_bytes(self.payload[:8])
                raise CommandFailed("gzip exited 1: driven to fail after writing")
            decompressed.write_bytes(self.payload)
            source.unlink()
        return self._answer(argv)

    def argv_for(self, tool: str) -> tuple[tuple[str, ...], ...]:
        return tuple(call for call in self.calls if call[0] == tool)

    def _answer(self, argv: Sequence[str], *, stdout: str = "") -> Result:
        return Result(argv=tuple(argv), returncode=0, stdout=stdout, stderr="")


def _step(argv: Sequence[str]) -> str | None:
    """Which step of the path one command is, read from the argv the modules build."""
    if argv[0] == "gpg":
        return "import" if "--import" in argv else "decrypt" if "--decrypt" in argv else None
    if argv[0] == "gzip":
        return "decompress" if "--decompress" in argv else "compress"
    if argv[0] == "rclone":
        if argv[1] == "lsjson":
            return "listing"
        # A download's destination is a path and an upload's IS the remote, which is how the two
        # directions of `copyto` are told apart.
        return "upload" if _names_a_remote(argv[3]) else "download"
    return None


def _names_a_remote(argument: str) -> bool:
    """Whether one `rclone copyto` argument is a remote rather than a path, as rclone reads it."""
    return ":" in argument.partition("/")[0]


def _listing(names: tuple[str, ...]) -> str:
    """A listing in the shape `rclone lsjson` prints."""
    return json.dumps(
        [
            {"Name": name, "Size": 1, "ModTime": "2026-08-07T03:00:00.000000000Z", "IsDir": False}
            for name in names
        ]
    )


def _drill_environment(root: Path) -> dict[str, str]:
    """The environment a drill's ops container runs the staging step with, in a temporary tree."""
    root.mkdir(parents=True, exist_ok=True)
    key = root / "private.asc"
    # A path rather than a key: gpg is behind the `Run` seam here, so nothing reads the contents.
    key.write_text("the private half a person brings to a drill")
    return {
        "SYNCR_BACKUP_REMOTE": "localbucket:/var/backups/bucket",
        "SYNCR_BACKUP_ALLOW_LOCAL_REMOTE": "1",
        "SYNCR_BACKUP_PRIVATE_KEY": str(key),
        "SYNCR_STAGING_DIR": str(root / "staging"),
        "SYNCR_SCRATCH_DIR": str(root / "scratch"),
        "SYNCR_TEXTFILE_DIR": str(root / "textfile"),
        "SYNCR_WAL_RESTORE_DIR": str(root / "scratch" / "wal"),
        "SYNCR_WAL_STAGING_DIR": str(root / "wal-archive"),
    }


class TestOneSegmentPerInvocation:
    """The arity and the shape of the one name an invocation carries.

    A recovery asks for one segment at a time and reads the exit status as the answer about THAT
    name, so an invocation naming several could not say which one was missing.
    """

    @pytest.mark.parametrize("arguments", [(), (SEGMENT, "000000010000000000000004")])
    def test_it_refuses_anything_but_one_name(self, arguments: tuple[str, ...]) -> None:
        with pytest.raises(staging.SegmentRefused, match="ONE segment per invocation"):
            staging.requested_segment(arguments)

    @pytest.mark.parametrize(
        "name",
        [
            SEGMENT,
            "000000010000000000000003.00000028.backup",
            "00000002.history",
        ],
    )
    def test_it_admits_every_name_postgres_asks_for(self, name: str) -> None:
        """THE ADMITTING DIRECTION, and it is not decoration.

        `archive_command` copies whatever `%f` it is given, so the bucket holds a backup label and a
        timeline history file beside the segments, and a recovery asks for all three. A validator
        that admitted only the 24-digit shape would refuse two names the archive contains.
        """
        assert staging.requested_segment((name,)) == name

    @pytest.mark.parametrize(
        "name",
        [
            "../../etc/passwd",
            "wal/000000010000000000000003",
            "000000010000000000000003.gz.gpg",
            "000000010000000000000003 ",
            "00000001000000000000000g",
            "000000010000000000000003.backup",
            "",
        ],
    )
    def test_it_refuses_a_name_it_would_have_to_join_to_a_path(self, name: str) -> None:
        """Including the OBJECT name, which is the plausible mistake: this step adds the suffix."""
        with pytest.raises(staging.SegmentRefused, match="not a name Postgres asks"):
            staging.requested_segment((name,))


class TestWhatReachesTheVolume:
    def test_the_segment_arrives_decompressed_under_the_name_postgres_asks_for(
        self, tmp_path: Path
    ) -> None:
        run = FakeTools()

        staged = staging.fetch_segment(SEGMENT, environ=_drill_environment(tmp_path), run=run)

        assert staged == tmp_path / "scratch" / "wal" / SEGMENT
        assert staged.read_bytes() == SEGMENT_BYTES
        assert sorted(path.name for path in staged.parent.iterdir()) == [SEGMENT]

    def test_the_staged_file_is_owned_by_the_user_that_copies_it_out(self, tmp_path: Path) -> None:
        """gpg and gzip write 0600 as the user running them, which in the ops image is root.

        The chown needs root and is skipped in a test; the mode is the half a test can read, and the
        drill in `changesets/` is where a real recovery's own user reads the file.
        """
        staged = staging.fetch_segment(
            SEGMENT, environ=_drill_environment(tmp_path), run=FakeTools()
        )

        assert staged.stat().st_mode & 0o777 == FILE_MODE

    def test_a_decompression_that_stops_halfway_leaves_no_segment_behind(
        self, tmp_path: Path
    ) -> None:
        """THE FAILURE THIS PATH CANNOT REPORT ANY OTHER WAY.

        A partial file under the segment's own name is one `restore_command` copies and Postgres
        tries to replay: it fails a checksum mid-recovery rather than ending the recovery, so the
        copy stops at a point nobody chose. The download and the decompression therefore happen
        under a working name, and only a complete file is moved to the name Postgres asks for.
        """
        environ = _drill_environment(tmp_path)

        with pytest.raises(CommandFailed):
            staging.fetch_segment(SEGMENT, environ=environ, run=FakeTools(half_written=True))

        assert not (tmp_path / "scratch" / "wal" / SEGMENT).exists()
        assert list((tmp_path / "scratch" / "wal").iterdir()) == []

    def test_a_failed_decryption_leaves_no_encrypted_copy_behind_either(
        self, tmp_path: Path
    ) -> None:
        """The property this step shares with the dump's fetch, which is why it is one function.

        An encrypted file left beside the plaintext one cannot be told from an object the step
        fetched itself, and a directory listing is what the next reader trusts.
        """
        environ = _drill_environment(tmp_path)

        with pytest.raises(CommandFailed):
            staging.fetch_segment(SEGMENT, environ=environ, run=FakeTools(fails_at="decrypt"))

        assert list((tmp_path / "scratch" / "wal").iterdir()) == []

    def test_the_download_happens_before_anything_is_decrypted(self, tmp_path: Path) -> None:
        """The order the two cases above depend on: a fake that failed the key import instead would
        make both of them pass over a run that had fetched nothing."""
        run = FakeTools()

        staging.fetch_segment(SEGMENT, environ=_drill_environment(tmp_path), run=run)

        steps = [found for found in (_step(call) for call in run.calls) if found is not None]
        assert steps == ["listing", "import", "download", "decrypt", "decompress"]

    def test_a_second_invocation_replaces_the_segment_rather_than_refusing(
        self, tmp_path: Path
    ) -> None:
        """One segment per invocation means a recovery's list is staged by several, and a retry of
        one of them must not need the directory emptied first."""
        environ = _drill_environment(tmp_path)
        staging.fetch_segment(SEGMENT, environ=environ, run=FakeTools())

        staged = staging.fetch_segment(
            SEGMENT, environ=environ, run=FakeTools(payload=b"fetched again")
        )

        assert staged.read_bytes() == b"fetched again"


class TestTheBucketsAnswerAboutOneName:
    def test_an_object_the_bucket_does_not_hold_is_not_a_failure(self, tmp_path: Path) -> None:
        """It is how a recovery finds the end of the archive, so its exit status is its own."""
        with pytest.raises(staging.SegmentAbsent, match=re.escape(f"holds no {SHIPPED_OBJECT}")):
            staging.fetch_segment(
                SEGMENT, environ=_drill_environment(tmp_path), run=FakeTools(held=())
            )

    def test_the_three_exit_statuses_are_distinct(self) -> None:
        """A caller loops until the archive ends and stops when the bucket breaks, so it needs to
        tell those apart from each other and from success."""
        assert len({staging.EXIT_OK, staging.EXIT_REFUSED, staging.EXIT_ABSENT}) == 3

    def test_nothing_is_downloaded_for_a_name_the_bucket_lacks(self, tmp_path: Path) -> None:
        run = FakeTools(held=("000000010000000000000009.gz.gpg",))

        with pytest.raises(staging.SegmentAbsent):
            staging.fetch_segment(SEGMENT, environ=_drill_environment(tmp_path), run=run)

        assert [call for call in run.argv_for("rclone") if "copyto" in call] == []


class TestTheDirectoryASegmentIsStagedIn:
    """Every other directory this path writes has an owner, and this step re-owns what it stages in.

    The WAL staging volume is the one that loses data rather than confusing a reader: the shipper
    uploads every file it finds there and then removes it, so a segment staged in it would be
    shipped back to the bucket and gone before a recovery could copy it.
    """

    @pytest.mark.parametrize(
        ("variable", "reason"),
        [
            ("SYNCR_WAL_STAGING_DIR", "the volume `archive_command` writes into"),
            ("SYNCR_STAGING_DIR", "the dump's staging volume"),
            ("SYNCR_SCRATCH_DIR", "the scratch volume's own root"),
            ("SYNCR_TEXTFILE_DIR", "the metrics textfile collector"),
        ],
    )
    def test_it_refuses_a_directory_another_step_owns(
        self, tmp_path: Path, variable: str, reason: str
    ) -> None:
        environ = _drill_environment(tmp_path)
        environ["SYNCR_WAL_RESTORE_DIR"] = environ[variable]

        with pytest.raises(staging.SegmentRefused, match=reason):
            staging.fetch_segment(SEGMENT, environ=environ, run=FakeTools())

    def test_it_admits_a_directory_of_its_own(self, tmp_path: Path) -> None:
        """THE OTHER DIRECTION. A refusal over four paths passes with the reading inverted, and this
        is what says the four are a set rather than everything."""
        environ = _drill_environment(tmp_path)
        environ["SYNCR_WAL_RESTORE_DIR"] = str(tmp_path / "somewhere-else")

        staged = staging.fetch_segment(SEGMENT, environ=environ, run=FakeTools())

        assert staged.parent == tmp_path / "somewhere-else"

    def test_it_is_inside_the_volume_the_drill_empties(self) -> None:
        """WHERE THE `just` RECIPE'S OWN CLEANLINESS COMES FROM, and it is inherited rather than
        built: `ops.fetch` empties the scratch directory at the start of a drill, so a segment an
        earlier run staged cannot satisfy a later one. A staging directory moved out of that tree
        would keep its segments across drills with nothing to say so."""
        assert WAL_RESTORE_DIR.startswith(f"{SCRATCH_DIR}/")


class TestBothDirectionsNameTheSameObject:
    """The shipper writes the object and a recovery reads it, and nothing else crosses the two.

    A segment is compressed and then encrypted, so its object name carries both suffixes. If the
    two directions spelled it differently, the bucket would fill with objects no recovery could
    find, and every guard on both sides would stay green: the shipper's upload succeeds and the
    recovery reads "the archive ends here".
    """

    def test_the_shipper_uploads_the_name_the_recovery_asks_for(self, tmp_path: Path) -> None:
        uploaded = _shipped_object_name(tmp_path)
        run = FakeTools()
        staging.fetch_segment(SEGMENT, environ=_drill_environment(tmp_path), run=run)

        requested = next(call[2] for call in run.argv_for("rclone") if call[1] == "copyto")

        assert uploaded.endswith(f"/{SHIPPED_OBJECT}")
        assert requested.endswith(f"/{SHIPPED_OBJECT}")

    def test_the_object_name_is_read_out_of_one_place(self) -> None:
        assert naming.segment_object(SEGMENT) == SHIPPED_OBJECT

    def test_both_directions_reach_the_same_prefix_of_the_bucket(self, tmp_path: Path) -> None:
        """The dumps' prefix and the WAL prefix are different, and a recovery reading the wrong one
        finds nothing while reporting the archive ended."""
        uploaded = _shipped_object_name(tmp_path)
        run = FakeTools()
        staging.fetch_segment(SEGMENT, environ=_drill_environment(tmp_path), run=run)

        requested = next(call[2] for call in run.argv_for("rclone") if call[1] == "copyto")

        assert uploaded.rpartition("/")[0] == requested.rpartition("/")[0]


def _shipped_object_name(root: Path) -> str:
    """Run the real shipper over one staged segment and return the object name it uploaded to."""
    environ = _drill_environment(root)
    environ["SYNCR_BACKUP_PUBLIC_KEY"] = environ["SYNCR_BACKUP_PRIVATE_KEY"]
    environ |= {"PGHOST": "postgres", "PGUSER": "syncr", "PGDATABASE": "syncr"}
    archive = root / "wal-archive"
    archive.mkdir(parents=True, exist_ok=True)
    (archive / SEGMENT).write_bytes(SEGMENT_BYTES)
    run = _ShippingTools()

    assert ship.ship(environ=environ, run=run) == 1

    return next(call[3] for call in run.argv_for("rclone") if call[1] == "copyto")


@dataclass
class _ShippingTools(FakeTools):
    """The same fake, answering the one reading the shipper takes before it ships anything."""

    def __call__(
        self,
        argv: Sequence[str],
        *,
        stdout_path: Path | None = None,
        stdin_path: Path | None = None,
        environ: Mapping[str, str] | None = None,
        check: bool = True,
    ) -> Result:
        if argv[0] == "psql":
            self.calls.append(tuple(argv))
            return Result(argv=tuple(argv), returncode=0, stdout="on|replica|1|0|f||", stderr="")
        return super().__call__(
            argv, stdout_path=stdout_path, stdin_path=stdin_path, environ=environ, check=check
        )


@pytest.fixture(scope="module")
def drill() -> dict[str, Any]:
    """The drill's own configuration, as Compose resolves it on a host with a release recorded."""
    return resolved(*DRILL_FILES)


@pytest.mark.skipif(
    shutil.which("docker") is None, reason="the resolved Compose configuration needs the docker CLI"
)
class TestTheRecoveryInstanceHoldsNoCredential:
    """Read from `docker compose config` rather than from the file, so this is about the stack.

    The recovery instance is the deployment's own Postgres image, and the whole reason the segment
    travels through a volume is that this container has nothing to fetch it with: no bucket
    credential, no private key, no rclone, and a network with no route off the host. A
    `restore_command` that fetched for itself would have to run in the ops image, which is the one
    carrying rclone and python3, and a recovery proven in that image is proven against something the
    deployment does not run.
    """

    def test_the_restore_command_copies_from_where_the_staging_step_writes(
        self, drill: dict[str, Any]
    ) -> None:
        """THE ONE CROSSING THAT DECIDES WHETHER A RECOVERY FINDS ANYTHING.

        Two files state this path: `ops.config` for the writer and this command for the reader.
        Postgres reports a restore command that finds nothing as the end of the archive, so the two
        drifting apart is a recovery that stops early and reports nothing wrong.
        """
        assert _restore_command(drill) == f"cp {WAL_RESTORE_DIR}/%f %p"

    def test_the_restore_command_reaches_for_no_tool_the_image_does_not_carry(
        self, drill: dict[str, Any]
    ) -> None:
        """`archive_command` makes no network call, and this is that rule in the other direction."""
        command = _restore_command(drill)

        for tool in ("rclone", "gpg", "gunzip", "curl", "wget", "ssh", "nc", "python"):
            assert tool not in command, tool

    def test_the_recovery_instance_carries_neither_the_bucket_nor_the_key(
        self, drill: dict[str, Any]
    ) -> None:
        """With the ops container as the positive control: it carries both, in the same stack, so
        this reading is one that can see a credential where there is one."""
        recovery = services(drill)[RECOVERY_SERVICE]["environment"]
        ops = services(drill)[OPS_SERVICE]["environment"]

        assert _credentials(ops), "the reading found none where both are declared"
        assert _credentials(recovery) == set()

    def test_the_recovery_instance_is_the_image_the_deployment_runs(
        self, drill: dict[str, Any]
    ) -> None:
        """Not the ops image, which is the only one here that COULD fetch and decrypt for itself.

        The live database's own pin is the other half of this and is crossed in
        `test_deploy_topology.py`, which reads the deployed composition beside this one.
        """
        found = services(drill)

        assert found[RECOVERY_SERVICE]["image"] == found["postgres"]["image"]
        assert found[RECOVERY_SERVICE]["image"] != found[OPS_SERVICE]["image"]

    def test_the_recovery_instance_is_not_configured_below_the_live_database(
        self, drill: dict[str, Any]
    ) -> None:
        """THE SETTING THAT DECIDES WHETHER A REPLAY STARTS AT ALL.

        Postgres refuses to replay WAL from a server configured higher than the instance replaying
        it, and it refuses at startup rather than part way through, so the failure is a recovery
        that never begins. Both numbers are declared, in two files, and this keeps them together.
        """
        live = _declared_settings(drill, LIVE_SERVICE)
        recovery = _declared_settings(drill, RECOVERY_SERVICE)
        compared = {name: value for name, value in live.items() if name in COMPARED_SETTINGS}

        assert compared, "the live database declares none of the settings a replay compares"
        for name, value in compared.items():
            declared = recovery.get(name)
            assert declared is not None, f"the recovery instance declares no {name}"
            assert int(declared) >= int(value), f"{name}: {declared} against the live {value}"

    def test_it_reads_the_volume_the_staging_step_writes_and_cannot_write_to_it(
        self, drill: dict[str, Any]
    ) -> None:
        """Read-only, and it holds no database state: the scratch database is still in the
        container's own writable layer, so removing the container removes the copy."""
        mounts = services(drill)[RECOVERY_SERVICE]["volumes"]
        holding = [mount for mount in mounts if WAL_RESTORE_DIR.startswith(f"{mount['target']}/")]

        assert [mount["source"] for mount in holding] == ["restore_scratch"]
        assert holding[0]["read_only"] is True
        assert [mount for mount in mounts if _holds_a_database(mount)] == []


def _restore_command(drill: dict[str, Any]) -> str:
    """The recovery instance's own `restore_command`, or a failure saying it declares none."""
    declared = _declared_settings(drill, RECOVERY_SERVICE).get("restore_command")

    assert declared is not None, f"{RECOVERY_SERVICE} declares no restore command"
    return declared


def _holds_a_database(mount: Mapping[str, Any]) -> bool:
    """Whether one mount is where Postgres keeps its data directory."""
    target = str(mount["target"])
    return target.startswith("/var/lib/postgresql")


def _declared_settings(drill: dict[str, Any], service: str) -> dict[str, str]:
    """Every server setting one service's command line declares, as Compose resolved it."""
    command = services(drill)[service]["command"]
    settings = [argument.partition("=") for argument in command if "=" in argument]

    assert settings, f"{service} declares no settings, so this reading crosses nothing"
    return {name: value for name, _, value in settings}


def _credentials(environment: Mapping[str, str]) -> set[str]:
    """Every variable in one service's environment that names the bucket or a key, with a value."""
    return {
        name
        for name, value in environment.items()
        if value and (name.startswith(("RCLONE_", "SYNCR_BACKUP_")))
    }
