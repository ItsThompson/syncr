"""SR-DEPLOY-18: the point-in-time rehearsal's structure, and its ninth claim.

The seam the ticket names is the instant a dump was taken and the instant a recovery was asked for;
a replay that lands on the first is a dump restore wearing the second's clothes. What bites here,
layer by layer:

- the ninth claim (:mod:`ops.pitr`) is judged as a pure function, including BOTH directions a fake
  recovery fails in;
- the recovery instance is read from ``docker compose config`` rather than from the file, so the
  crossings are about the stack that actually runs (`test_wal_recovery.py` established the pattern);
- the recipe's guards are read out of the justfile, whose bodies are the statements of record.

The rehearsal ITSELF runs against Docker and a wall-clock WAL timeline, which no suite here fakes:
``just drill-pitr-local`` is its own runtime proof, and the justfile states why nothing of it is on
CI.
"""

from __future__ import annotations

import re
import shutil
import sys
from typing import TYPE_CHECKING, Any, Final

import pytest
from ops.config import WAL_RESTORE_DIR
from ops.pitr import claim

from tests.test_alert_rules import repo_root
from tests.test_deploy_topology import resolved, services
from tests.test_deployment_figures import _commands_of, _dependencies_of, _recipe_body

if TYPE_CHECKING:
    from collections.abc import Mapping

RECIPE: Final = "drill-pitr-local"
DEPLOYED_HOST_REFUSAL: Final = "_refuse-a-local-drill-on-a-deployed-host"
RECOVERY_SERVICE: Final = "postgres-recovery"
PREPARE_SERVICE: Final = "pitr-prepare"
DRILL_INSTANCE: Final = "postgres-restore"
LIVE_SERVICE: Final = "postgres"

# The overlays the rehearsal composes, in order. The pitr overlay last, so what it declares wins.
PITR_FILES: Final = (
    "docker-compose.yml",
    "docker-compose.restore.yml",
    "docker-compose.drill-local.yml",
    "docker-compose.drill-pitr.yml",
)


# --- The ninth claim ---------------------------------------------------------


class TestTheNinthClaim:
    """One claim, stated so it can fail in BOTH directions a fake recovery fails in."""

    ASKED_FOR: Final = "2026-08-05 12:00:00.000"
    DUMP_INSTANT: Final = "2026-08-05 11:30:00.000"

    def judge(self, found_at_target: int, found_at_dump_instant: int) -> tuple[bool, str]:
        finding = claim(
            asked_for=self.ASKED_FOR,
            dump_instant=self.DUMP_INSTANT,
            found_at_target=found_at_target,
            found_at_dump_instant=found_at_dump_instant,
        )
        return finding.held, finding.claim

    def test_a_real_replay_holds(self) -> None:
        """Present at the instant asked for, absent at the dump's own: the seam was crossed."""
        held, text = self.judge(found_at_target=1, found_at_dump_instant=0)

        assert held
        assert self.ASKED_FOR in text
        assert self.DUMP_INSTANT in text

    def test_a_replay_that_ignored_the_target_fails(self) -> None:
        """Present at BOTH instants, including the dump's own where it cannot be."""
        held, text = self.judge(found_at_target=1, found_at_dump_instant=1)

        assert not held
        assert "ignored" in text

    def test_a_dump_restore_fails(self) -> None:
        """Absent everywhere: the bytes came back and no archived WAL was read."""
        held, text = self.judge(found_at_target=0, found_at_dump_instant=0)

        assert not held
        assert "nothing replayed" in text

    def test_main_reports_the_verdict_through_its_exit_status(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The recipe gates on this process, so the status is the verdict's whole contract."""
        from ops import pitr

        arguments = ["ops.pitr", self.ASKED_FOR, self.DUMP_INSTANT, "1", "0"]
        monkeypatch.setattr(sys, "argv", arguments)
        assert pitr.main() == pitr.EXIT_OK
        assert "POINT-IN-TIME REHEARSAL" in capsys.readouterr().out

        failing = ["ops.pitr", self.ASKED_FOR, self.DUMP_INSTANT, "0", "0"]
        monkeypatch.setattr(sys, "argv", failing)
        assert pitr.main() == pitr.EXIT_FAILED

        monkeypatch.setattr(sys, "argv", ["ops.pitr"])
        assert pitr.main() == pitr.EXIT_FAILED


# --- The recovery instance, read from Compose --------------------------------


def declared_settings(drill: dict[str, Any], service: str) -> dict[str, str]:
    """Every server setting one service's command line declares, as Compose resolved it."""
    found = [
        argument.partition("=")
        for argument in services(drill)[service]["command"]
        if "=" in argument
    ]
    return {name: value for name, _, value in found}


def credentials(environment: Mapping[str, str]) -> set[str]:
    """Every variable naming the bucket or a key, with a value: what a recovery must NOT carry."""
    return {
        name
        for name, value in environment.items()
        if value and name.startswith(("RCLONE_", "SYNCR_BACKUP_"))
    }


@pytest.fixture(scope="class")
def drill() -> dict[str, Any]:
    """The rehearsal's own composition. digests=False: a machine that has never deployed."""
    return resolved(*PITR_FILES, digests=False)


@pytest.mark.skipif(
    shutil.which("docker") is None, reason="the resolved Compose configuration needs the docker CLI"
)
class TestTheRecoveryInstance:
    """Everything the replay depends on, crossed against what this repository already runs."""

    def test_it_is_the_image_the_drill_instance_runs(self, drill: dict[str, Any]) -> None:
        """One literal digest, shared with the restore drill's scratch instance.

        The other half of the crossing -- that this digest is the one the deploy overlay pins for
        the LIVE database -- is `test_deploy_topology.py`'s, and holds by transitivity from here.
        """
        found = services(drill)

        assert found[RECOVERY_SERVICE]["image"] == found[DRILL_INSTANCE]["image"]

    def test_it_is_not_configured_below_the_server_that_wrote_the_wal(
        self, drill: dict[str, Any]
    ) -> None:
        """Postgres refuses to replay on an instance configured below its writer, at startup."""
        live = declared_settings(drill, LIVE_SERVICE)
        recovery = declared_settings(drill, RECOVERY_SERVICE)

        assert int(recovery["max_connections"]) >= int(live["max_connections"])

    def test_its_restore_command_is_the_drill_instance_s(self, drill: dict[str, Any]) -> None:
        """One string, stated twice, reading where `ops.fetch_segment` stages."""
        assert (
            declared_settings(drill, RECOVERY_SERVICE)["restore_command"]
            == declared_settings(drill, DRILL_INSTANCE)["restore_command"]
            == f"cp {WAL_RESTORE_DIR}/%f %p"
        )

    def test_it_declares_no_archiving(self, drill: dict[str, Any]) -> None:
        """A recovery that archived would ship its own WAL back into the bucket."""
        assert "archive_mode" not in declared_settings(drill, RECOVERY_SERVICE)

    def test_it_carries_neither_the_bucket_nor_the_key(self, drill: dict[str, Any]) -> None:
        """With the ops container as the positive control, in the same stack."""
        environment = services(drill)[RECOVERY_SERVICE].get("environment") or {}

        assert credentials(services(drill)["ops"]["environment"]), (
            "the reading found none where both are declared"
        )
        assert credentials(environment) == set()

    def test_its_data_lives_in_the_volume_the_recipe_removes_by_name(
        self, drill: dict[str, Any]
    ) -> None:
        """Unlike the drill's scratch instance, a physical recovery holds its data BEFORE starting.

        The volume is the one `teardown` removes by name, never by a project-scoped teardown:
        this project holds the live database's volume on a host.
        """
        mounts = services(drill)[RECOVERY_SERVICE]["volumes"]
        data = [m for m in mounts if str(m["target"]).startswith("/var/lib/postgresql")]

        assert [m["source"] for m in data] == ["pitr_pgdata"]
        scratch = [
            m for m in mounts if str(m["target"]).startswith(WAL_RESTORE_DIR.rsplit("/", 1)[0])
        ]

        assert scratch[0]["read_only"] is True

    def test_the_prepare_step_writes_what_a_recovery_needs(self, drill: dict[str, Any]) -> None:
        """`recovery.signal`, and the target instant the recipe exports, refused without."""
        script = " ".join(services(drill)[PREPARE_SERVICE]["command"])

        assert "recovery.signal" in script
        assert "recovery_target_time" in script
        assert "SYNCR_PITR_TARGET_TIME is not set" in script, (
            "the rehearsal refuses to guess an instant"
        )


# --- The recipe's guards, read from the justfile -----------------------------


class TestTheRehearsalRefusesWhatItMust:
    def test_it_carries_the_deployed_host_refusal_before_the_keygen(self) -> None:
        """The same two-fact refusal `just drill-local` carries, and before keys are written."""
        dependencies = _dependencies_of(RECIPE)

        assert DEPLOYED_HOST_REFUSAL in dependencies
        assert dependencies.index(DEPLOYED_HOST_REFUSAL) < dependencies.index("drill-keys"), (
            "`just` runs dependencies left to right, and the keygen writes to deployments/secrets"
        )

    def test_it_refuses_an_empty_evidence_set(self) -> None:
        """Exactly the tables `just restore-drill` refuses over, crossed against the constants.

        A recovery of an empty table always succeeds, so the rehearsal checks every evidence table
        before taking the base backup. Read from the COMMANDS, so a mention in a comment does not
        satisfy this.
        """
        from ops.config import EVIDENCE_TABLES

        listed = set(re.findall(r"public\.[a-z_]+", _commands_of(_recipe_body(RECIPE))))

        assert listed == set(EVIDENCE_TABLES)

    def test_it_refuses_an_empty_wal_archive(self) -> None:
        """Nothing staged means nothing could replay, which is not a pass."""
        assert "holds no archived WAL segment" in _commands_of(_recipe_body(RECIPE))

    def test_nothing_is_on_ci_and_the_reason_is_stated_in_the_recipe(self) -> None:
        """An omission explained nowhere reads as an oversight; this one is a decision."""
        justfile = (repo_root() / "justfile").read_text(encoding="utf-8")

        for name in ("ci.yml", "cd.yml", "healthcheck.yml"):
            workflow = (repo_root() / ".github" / "workflows" / name).read_text(encoding="utf-8")
            assert "drill-pitr" not in workflow, f"{name} must not run the rehearsal"
        assert "WHY NOTHING HERE IS ON CI" in justfile, (
            "the recipe states why the run itself is rehearsed by hand"
        )
