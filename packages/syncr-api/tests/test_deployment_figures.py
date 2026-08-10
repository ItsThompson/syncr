"""Every figure the deployment's runbooks and its timers quote, crossed against what produces it.

A runbook is read once, under pressure, by someone deciding whether to intervene. One whose numbers
have drifted from the deployment is worse than none: it will be trusted, and it will be wrong. So no
figure below is written twice. Each is asserted against the constant, the alert expression or the
systemd unit that decides it.

THE SCHEDULE IS PART OF THE CONTRACT. `ops.config` states 03:00, a 60-second ship interval and a
120-second archive timeout, and three separate places have to agree with it: the timers that run,
the Postgres command line that produces the WAL, and the runbooks that quote the arithmetic. A drift
in any one of them silently moves the recovery point.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

import pytest
from ops.config import (
    ARCHIVE_TIMEOUT_SECONDS,
    BACKUP_METRIC,
    BACKUP_STALE_AFTER_SECONDS,
    DAILY_COPIES,
    EVIDENCE_TABLES,
    MONTHLY_COPIES,
    NIGHTLY_HOUR,
    RECOVERY_POINT_OBJECTIVE_SECONDS,
    RECOVERY_TIME_OBJECTIVE_SECONDS,
    SHIP_INTERVAL_SECONDS,
    WAL_METRIC,
    WAL_STALE_AFTER_SECONDS,
    WEEKLY_COPIES,
)
from ops.fingerprint import Fingerprint
from ops.process import Result
from ops.restore import RestoreRefused, require_empty
from ops.verdict import compare

from syncr_api.core.settings import EnvSettings
from tests.test_alert_rules import named as alert_named
from tests.test_alert_rules import repo_root
from tests.test_deploy_topology import DEPLOYED_FILES

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from ops.process import Run

RUNBOOKS: Final = Path("docs/runbooks")

BACKUP_STALE = RUNBOOKS / "backup-stale.md"
RESTORE_FROM_BACKUP = RUNBOOKS / "restore-from-backup.md"
DEPLOY_AND_ROLLBACK = RUNBOOKS / "deploy-and-rollback.md"
ROTATE_SECRETS = RUNBOOKS / "rotate-secrets.md"
DISK_PRESSURE = RUNBOOKS / "disk-pressure.md"
CLOCK_DRIFT = RUNBOOKS / "clock-drift.md"
ICS_FEED_BROKEN = RUNBOOKS / "ics-feed-broken.md"

# Section 21 names eleven runbooks by file name. This is that list, and the assertion below is an
# existence check rather than a claim about content: a pointer that does not resolve is worse than
# no pointer, and eight of twelve alert annotations pointed at nothing before ticket 54.
SECTION_21_RUNBOOKS: Final = (
    "bootstrap-first-user.md",
    "restore-from-backup.md",
    "google-token-expired.md",
    "google-oauth-verification.md",
    "ics-feed-broken.md",
    "solve-failing.md",
    "stuck-operation.md",
    "rotate-secrets.md",
    "disk-pressure.md",
    "debounce-tuning.md",
    "deploy-and-rollback.md",
)

SYSTEMD: Final = Path("deployments/systemd")

# The refusal `just drill-local` and `just drill-seed` both carry, spelled once because the rule in
# `TestEveryRecipeThatSeedsRefusesADeployedHost` is stated over a derived set of recipes.
DEPLOYED_HOST_REFUSAL: Final = "_refuse-a-local-drill-on-a-deployed-host"

# The refusal every recipe that drops a project's volumes carries, spelled once because the rule in
# `TestEveryTeardownRefusesAnInheritedProject` is stated over a derived set of recipes.
RETARGETED_TEARDOWN_REFUSAL: Final = "_refuse-a-retargeted-teardown"

# Where the stub `docker` below records having been reached, relative to the tree a case builds.
DOCKER_LOG: Final = "docker-was-reached"

# One byte that is a valid CP1252 character and not valid UTF-8 on its own, spelled as a byte so the
# case that needs it does not carry a literal a secret scanner reads as high entropy.
CP1252_O_UMLAUT: Final = bytes([0xF6])

# The space compose trims and a byte-oriented pattern cannot see. Named for the same reason.
NO_BREAK_SPACE: Final = "\u00a0"

# A `docker` that records being called and can reach nothing, so "started nothing" is an OBSERVATION
# rather than an inference from an exit status: a guard that starts something and refuses afterwards
# exits non-zero too, so a returncode cannot tell an early refusal from a late one.
RECORDING_DOCKER: Final = '#!/bin/sh\nprintf "%s\\n" "$*" >> "$SYNCR_DOCKER_LOG"\n'


def _claims() -> int:
    """How many claims the verdict prints, read from the verdict rather than from a runbook."""
    reading = Fingerprint(
        taken_at=datetime(2026, 8, 7, 3, tzinfo=UTC),
        expected_head="head",
        applied_revision="head",
        row_counts=dict.fromkeys(EVIDENCE_TABLES, 1),
        content_digests=dict.fromkeys(EVIDENCE_TABLES, "digest"),
        cursors=(),
    )
    return len(compare(reading, reading, elapsed_seconds=1).findings)


def _number(count: int) -> str:
    """The English word a runbook writes a small count as."""
    words = {7: "seven", 8: "eight", 9: "nine"}
    assert count in words, f"the verdict prints {count} claims and nothing here spells that"
    return words[count]


def _every_runbook() -> tuple[str, ...]:
    """Every runbook in the directory, which is the set a rule about runbooks has to be stated over.

    Section 21 names eleven and this deployment has sixteen: the alert-named ones ticket 54 wrote
    are runbooks too, and one of them is the file this ticket rewrote.
    """
    return tuple(sorted(path.name for path in (repo_root() / RUNBOOKS).glob("*.md")))


# systemd's own default PATH for a service, which is where `/usr/bin/env just` looks. Not
# configurable in these units and not the shell's: a unit inherits this and nothing else.
#
# A STATED CONSTANT THAT NOTHING IN THE TREE CROSSES, which is what makes it the weakest reading in
# this module. It is correct for Debian bookworm and it cannot be read from the repository, so what
# makes it safe is not the constant: step 10 of `docs/runbooks/deploy-and-rollback.md` STARTS
# `syncr-walship.service` and reads its journal, which is a real execution of the claim on the only
# machine that can make it. If this tuple is ever wrong, that step is what says so.
SYSTEMD_DEFAULT_PATH: Final = (
    Path("/usr/local/sbin"),
    Path("/usr/local/bin"),
    Path("/usr/sbin"),
    Path("/usr/bin"),
    Path("/sbin"),
    Path("/bin"),
)

_ENV: Final = "/usr/bin/env"


def _exec_start(content: str) -> str:
    """One unit's `ExecStart` value, or the empty string when it has none."""
    for line in content.splitlines():
        if line.startswith("ExecStart="):
            return line.partition("=")[2].strip()
    return ""


def _where_the_runbook_installs_just() -> Path:
    """Where the deploy runbook puts the `just` binary, read from the command it tells you to run.

    `tar -xz -C <directory> just` is that command. Read rather than restated: the whole point of
    this crossing is that a second copy of the path is what went wrong.
    """
    import re

    found = re.search(r"tar -xz -C (\S+) just", read(DEPLOY_AND_ROLLBACK))
    assert found is not None, (
        "the deploy runbook no longer states where it installs `just`, so nothing crosses the "
        "units against it"
    )
    return Path(found.group(1)) / "just"


def read(relative: Path) -> str:
    path = repo_root() / relative
    assert path.is_file(), f"{relative} does not exist"
    return path.read_text(encoding="utf-8")


def directives(relative: Path) -> str:
    """One systemd unit with its comments removed, which is what systemd acts on.

    Read this way because the comments EXPLAIN the directives, so a unit's own reasoning names the
    setting it decided against: the WAL timer says why it carries no `Persistent=true`, and a
    reading over the whole file would find the phrase and conclude the opposite.
    """
    return "\n".join(
        line for line in read(relative).splitlines() if not line.strip().startswith("#")
    )


def hours(seconds: int) -> int:
    return seconds // 3600


def minutes(seconds: int) -> int:
    return seconds // 60


class TestEveryRunbookSectionTwentyOneNamesExists:
    """Eleven procedures, one file each, and each reachable by the name the spec gives it."""

    @pytest.mark.parametrize("name", SECTION_21_RUNBOOKS)
    def test_it_exists(self, name: str) -> None:
        assert (repo_root() / RUNBOOKS / name).is_file()

    @pytest.mark.parametrize("name", SECTION_21_RUNBOOKS)
    def test_it_states_a_trigger(self, name: str) -> None:
        """Section 21: each states its trigger, its steps, and how to verify it worked."""
        assert "## Trigger" in read(RUNBOOKS / name)

    def test_there_is_no_second_file_for_a_procedure_that_moved(self) -> None:
        """Two files for one procedure is two procedures, and one of them goes stale unread.

        `disk-filling-up.md` and `source-stale.md` were the alert-named spellings of two of the
        above, and they were RENAMED rather than copied, so the alert's pointer moved with them.
        """
        present = {path.name for path in (repo_root() / RUNBOOKS).glob("*.md")}

        assert "disk-filling-up.md" not in present
        assert "source-stale.md" not in present


class TestTheBackupStaleFigures:
    """The alert reads two producers, and the runbook quotes both thresholds."""

    def test_the_expression_carries_both_thresholds(self) -> None:
        expression = alert_named("BackupStale").expr

        assert str(BACKUP_STALE_AFTER_SECONDS) in expression
        assert str(WAL_STALE_AFTER_SECONDS) in expression

    def test_the_expression_reads_both_families(self) -> None:
        expression = alert_named("BackupStale").expr

        assert BACKUP_METRIC in expression
        assert WAL_METRIC in expression

    def test_both_families_carry_an_absent_disjunct(self) -> None:
        """A missing series means no backup has ever run, which is the more serious reading."""
        expression = alert_named("BackupStale").expr

        assert f"absent({BACKUP_METRIC})" in expression
        assert f"absent({WAL_METRIC})" in expression

    def test_the_runbook_quotes_the_figures_the_alert_is_written_from(self) -> None:
        runbook = read(BACKUP_STALE)

        assert str(BACKUP_STALE_AFTER_SECONDS) in runbook
        assert f"**{hours(BACKUP_STALE_AFTER_SECONDS)} hours**" in runbook
        assert str(WAL_STALE_AFTER_SECONDS) in runbook
        assert f"**{minutes(WAL_STALE_AFTER_SECONDS)} minutes**" in runbook

    def test_the_runbook_states_the_recovery_point_arithmetic(self) -> None:
        """`archive_timeout` plus the ship interval is the figure, and it has to be visible."""
        runbook = read(BACKUP_STALE)

        assert f"{ARCHIVE_TIMEOUT_SECONDS} seconds" in runbook
        assert f"{SHIP_INTERVAL_SECONDS}-second" in runbook

    def test_the_runbook_names_both_files_the_alert_reads(self) -> None:
        runbook = read(BACKUP_STALE)

        assert f"{BACKUP_METRIC}.prom" in runbook
        assert f"{WAL_METRIC}.prom" in runbook

    def test_it_names_the_series_that_says_the_exposition_failed(self) -> None:
        """The one case where nothing is wrong with the data, and it must be ruled out first."""
        assert "node_textfile_scrape_error" in read(BACKUP_STALE)


class TestTheRestoreRunbookFigures:
    """The two objectives, the retention counts, and the schedule."""

    def test_it_quotes_both_objectives(self) -> None:
        runbook = read(RESTORE_FROM_BACKUP)

        assert f"under {minutes(RECOVERY_POINT_OBJECTIVE_SECONDS)} minutes" in runbook
        assert f"under {hours(RECOVERY_TIME_OBJECTIVE_SECONDS)} hour" in runbook

    def test_it_quotes_the_three_retention_counts(self) -> None:
        runbook = read(RESTORE_FROM_BACKUP)

        assert f"{DAILY_COPIES} daily, {WEEKLY_COPIES} weekly, {MONTHLY_COPIES} monthly" in runbook

    def test_it_quotes_the_hour_the_dump_is_taken(self) -> None:
        assert f"{NIGHTLY_HOUR:02d}:00" in read(RESTORE_FROM_BACKUP)

    def test_it_states_that_the_pass_condition_is_data_read_back(self) -> None:
        """`pg_restore` exits 0 having restored an empty archive, and that is the whole point."""
        runbook = read(RESTORE_FROM_BACKUP).lower()

        assert "data read back" in runbook
        assert "empty archive" in runbook

    def test_it_quotes_the_number_of_claims_the_verdict_actually_prints(self) -> None:
        """CROSSED AGAINST THE VERDICT, because the sample block quoted two different figures.

        One sentence said seven claims after the eighth landed, and the sample's digest line quoted
        5, which is `len(EVIDENCE_TABLES)` from a test fixture, beside a table-presence line quoting
        the real 36 in the same code block. An operator comparing the printed verdict against the
        runbook had no way to tell which was right.
        """
        runbook = read(RESTORE_FROM_BACKUP)

        assert f"the {_number(_claims())} claims it prints" in runbook
        assert "seven claims" not in runbook
        assert "the 5 tables hashes identically" not in runbook, (
            "that figure is a test fixture's, not a run's"
        )

    def test_the_sample_verdict_is_a_real_run_rather_than_a_fixture(self) -> None:
        """Both figures in the sample block are the ones two real drills printed."""
        runbook = read(RESTORE_FROM_BACKUP)

        assert "every one of the 36 tables the dump was taken over is present" in runbook
        assert "every one of the 36 tables hashes identically" in runbook

    def test_step_six_does_not_write_to_the_bucket(self) -> None:
        """Step 6 is where the operator DECIDES whether the restore is correct.

        `just backup-now` uploads a dump, runs retention over the listing, and publishes the nightly
        success gauge. Doing that at step 6 puts possibly-wrong data in the bucket as the newest
        copy, prunes against it, and moves the one series `BackupStale` reads about the NIGHTLY
        path.
        """
        runbook = read(RESTORE_FROM_BACKUP)
        step_six = runbook.partition("### 6. Verify with data")[2].partition("### 7.")[0]

        assert "run --rm fingerprint" in step_six
        assert "just backup-now" not in step_six.partition("**Do not run")[0]
        assert "Do not run `just backup-now` here" in step_six
        assert "once you have accepted the restore" in runbook.lower()

    def test_it_states_that_the_drill_is_re_executed_after_a_change_to_the_backup_path(
        self,
    ) -> None:
        assert "re-executed after any change to the backup path" in read(RESTORE_FROM_BACKUP)

    def test_it_says_what_it_has_not_verified(self) -> None:
        """A runbook that reads as tested when it is not is worse than one that says so."""
        assert "## Not verified" in read(RESTORE_FROM_BACKUP)


class TestTheDeployRunbook:
    """The rules a release depends on, each stated where the operator reads them."""

    def test_it_states_the_deploy_order(self) -> None:
        runbook = read(DEPLOY_AND_ROLLBACK)

        assert "one-shot before" in runbook
        assert "/readyz" in runbook

    def test_it_states_that_rollback_is_re_deploying_the_previous_digests(self) -> None:
        runbook = read(DEPLOY_AND_ROLLBACK)

        assert "digests.previous.env" in runbook
        assert "A schema rollback is a **restore**" in runbook

    def test_it_states_that_no_feature_flag_exists(self) -> None:
        assert "**No feature flags**" in read(DEPLOY_AND_ROLLBACK)

    def test_it_carries_the_external_port_scan_the_tunnel_claim_needs(self) -> None:
        """A machine can read the resolved configuration; only a person elsewhere can scan."""
        runbook = read(DEPLOY_AND_ROLLBACK)

        assert "just ports-check" in runbook
        assert "nmap" in runbook

    def test_it_names_the_restore_drill_as_a_step_of_the_first_deployment(self) -> None:
        """The one criterion this epic cannot waive."""
        runbook = read(DEPLOY_AND_ROLLBACK)

        assert "restore drill" in runbook.lower()
        assert "before the deployment is considered live" in runbook.lower()

    def test_it_names_every_operational_cost_the_deployment_accepted(self) -> None:
        runbook = read(DEPLOY_AND_ROLLBACK)

        assert "A Cloudflare outage is a syncr outage" in runbook
        assert "cannot alert on itself" in runbook

    def test_it_lists_every_workstation_valued_key_only_the_host_file_can_decide(self) -> None:
        """A key that addresses a workstation, and that the deployed stack does not name, is
        decided by a copy.

        `google-oauth-verification.md` documents copying `.env.example` to seed a fresh machine, so
        whatever that file ships reaches a deployed host. Where a compose `environment:` entry in
        the stack a host runs names a key, the topology decides it and the copy cannot; where none
        does, the host file is the only layer, and this table is the one place an operator is told
        to change it.

        Both readings are controlled first, because an empty set satisfies a subtraction and would
        pass this while checking nothing.
        """
        listed = _keys_the_deploy_table_lists()
        assert "CLOUDFLARE_TUNNEL_TOKEN" in listed, "the table reading found no table"
        decided_by_compose = _keys_the_deployed_stack_names()
        assert "DATABASE_URL" in decided_by_compose, "the compose reading found no variables"

        unlisted = sorted(
            _keys_the_example_file_points_at_a_workstation() - decided_by_compose - listed
        )

        assert unlisted == [], (
            f"{unlisted} address a developer's own machine in .env.example, the deployed stack "
            "does not name them, and the host secret file's table does not list them, so a host "
            "seeded by copying that file holds a workstation address nobody is told to change"
        )


class TestTheSecretsRunbook:
    """Eight values, and two of them cost the user something."""

    def test_it_states_the_cost_of_the_two_that_have_one(self) -> None:
        runbook = read(ROTATE_SECRETS)

        assert "Every browser session is invalidated" in runbook
        assert "Every stored refresh token becomes unreadable" in runbook

    def test_it_names_every_secret_the_deployment_holds(self) -> None:
        runbook = read(ROTATE_SECRETS)

        for key in (
            "POSTGRES_PASSWORD",
            "SESSION_SIGNING_SECRET",
            "OAUTH_KEY_ENCRYPTION_KEY",
            "GOOGLE_OAUTH_CLIENT_SECRET",
            "GOOGLE_TOKEN_ENCRYPTION_KEY",
            "CLOUDFLARE_TUNNEL_TOKEN",
            "RCLONE_CONFIG_OFFHOST_",
        ):
            assert key in runbook

    def test_it_states_that_rotating_the_backup_key_needs_a_new_drill(self) -> None:
        assert "Re-execute the drill after any change to the backup path" in read(ROTATE_SECRETS)

    def test_it_states_the_retention_window_the_old_private_key_must_outlive(self) -> None:
        assert f"{MONTHLY_COPIES} monthly copies means six months" in read(ROTATE_SECRETS)


class TestTheClockRunbook:
    """The thirteenth rule's own file, and why a scheduler alerts on its own clock."""

    def test_the_alert_points_at_it(self) -> None:
        assert alert_named("ClockDrifting").annotations["runbook"] == "docs/runbooks/clock-drift.md"

    def test_it_names_the_series_the_alert_reads(self) -> None:
        runbook = read(CLOCK_DRIFT)

        for series in ("node_timex_sync_status", "node_timex_offset_seconds"):
            assert series in runbook
            assert series in alert_named("ClockDrifting").expr

    def test_it_states_what_reads_the_clock(self) -> None:
        """The reason it is alerted at all: nothing fails, and everything is wrong."""
        runbook = read(CLOCK_DRIFT)

        assert "The frame and the now rule" in runbook
        assert "Nothing fails, and everything is wrong" in runbook

    def test_it_carries_the_repair_for_both_time_daemons(self) -> None:
        runbook = read(CLOCK_DRIFT)

        assert "timedatectl set-ntp true" in runbook
        assert "chronyc tracking" in runbook


class TestTheDiskRunbook:
    """What is safe to prune, and that plan data is not."""

    def test_it_states_that_plan_data_is_never_pruned(self) -> None:
        runbook = read(DISK_PRESSURE)

        assert "no pruning policy for plan data" in runbook
        assert "pgdata`, ever" in runbook

    def test_it_names_the_two_volumes_this_ticket_added(self) -> None:
        runbook = read(DISK_PRESSURE)

        assert "syncr_wal_archive" in runbook
        assert "syncr_backup_staging" in runbook

    def test_it_states_that_unshipped_wal_is_the_recovery_point(self) -> None:
        assert "They are the recovery point" in read(DISK_PRESSURE)


class TestTheTimersAgreeWithTheConfiguration:
    """Three units, and the figures they run on are the ones every other reader uses."""

    def test_the_backup_timer_runs_at_the_nightly_hour(self) -> None:
        assert f"OnCalendar=*-*-* {NIGHTLY_HOUR:02d}:00:00" in read(SYSTEMD / "syncr-backup.timer")

    def test_the_learning_timer_runs_at_the_same_hour(self) -> None:
        """Which is why the learning engine turns on `pool_pre_ping`."""
        assert f"OnCalendar=*-*-* {NIGHTLY_HOUR:02d}:00:00" in read(
            SYSTEMD / "syncr-learning.timer"
        )

    def test_the_wal_timer_runs_at_the_ship_interval(self) -> None:
        assert f"OnUnitActiveSec={SHIP_INTERVAL_SECONDS}s" in read(SYSTEMD / "syncr-walship.timer")

    def test_a_missed_nightly_run_is_caught_up_and_a_missed_minute_is_not(self) -> None:
        """A missed DAY of dumps is a night with no copy; a missed minute the next run drains."""
        assert "Persistent=true" in directives(SYSTEMD / "syncr-backup.timer")
        assert "Persistent=true" in directives(SYSTEMD / "syncr-learning.timer")
        assert "Persistent=true" not in directives(SYSTEMD / "syncr-walship.timer")

    @pytest.mark.parametrize(
        "unit", ["syncr-backup.service", "syncr-walship.service", "syncr-learning.service"]
    )
    def test_each_unit_runs_a_recipe_rather_than_a_command(self, unit: str) -> None:
        """The schedule and a manual run cannot drift into two procedures if there is one.

        CROSSED AGAINST THE JUSTFILE, not against a padded substring. The first version asserted
        `" just " in _exec_start(content)`, which REJECTED `/usr/local/bin/just backup-now`: the
        absolute-path shape its sibling crossing declares valid, and arguably the more correct
        thing for a unit. A false failure rather than a false pass, so nothing was at risk, but one
        guard would have blocked the remedy the other permits, and the "two shapes" docstring next
        door was not true of the suite.

        This asserts what the test's own name claims: the thing invoked is a recipe that exists.

        THE SET IS DELIBERATELY WIDE. `_recipe_names()` includes `[private]` recipes, because `just`
        runs one when a unit names it, so this crossing accepts a unit that calls one.
        """
        content = directives(SYSTEMD / unit)
        started = _exec_start(content).split()
        assert started, f"{unit} has no ExecStart"

        binary, arguments = started[0], started[1:]
        if binary == _ENV:
            assert arguments and arguments[0] == "just", started
            arguments = arguments[1:]
        else:
            assert Path(binary).name == "just", f"{unit} runs {binary}, which is not `just`"

        assert arguments, f"{unit} runs `just` with no recipe"
        assert arguments[0] in _recipe_names(), (
            f"{unit} runs `just {arguments[0]}`, which the justfile does not declare"
        )
        assert "Type=oneshot" in content

    @pytest.mark.parametrize(
        "unit", ["syncr-backup.service", "syncr-walship.service", "syncr-learning.service"]
    )
    def test_each_unit_can_execute_the_binary_the_runbook_installs(self, unit: str) -> None:
        """DERIVED FROM THE RUNBOOK, because a pinned literal certified the wrong path.

        The units read `/usr/bin/just` and the runbook installs to `/usr/local/bin/just`. That is
        where a hand-installed binary belongs, and where the release tarball goes, since `just` is
        not in Debian's repositories. So all three units would have failed at 203/EXEC on their
        first firing: the WAL shipper within a minute, the backup and the fitter at 03:00.

        And the deployment would have read HEALTHY. `systemctl list-timers` lists a timer whether or
        not its service can execute, step 10 starts no service, and the two commands after it run in
        a shell that finds the binary on PATH, so both gauges go fresh and `BackupStale` goes quiet
        for a reason.

        The old assertion was `"ExecStart=/usr/bin/just " in content`: a value nothing else in the
        tree agreed with, pinned in the guard written to hold these files honest.

        Two shapes satisfy this, and both are checked against the runbook rather than against a
        constant: an ABSOLUTE path equal to the runbook's install directory, or `/usr/bin/env just`,
        which resolves through systemd's own PATH provided that directory is on it.
        """
        started = _exec_start(directives(SYSTEMD / unit))
        binary = started.split()[0]
        installed = _where_the_runbook_installs_just()

        if binary == _ENV:
            assert started.split()[1] == "just", started
            assert installed.parent in SYSTEMD_DEFAULT_PATH, (
                f"the runbook installs just to {installed}, which is not on systemd's own PATH "
                f"({SYSTEMD_DEFAULT_PATH}), so `{_ENV} just` cannot find it"
            )
        else:
            assert Path(binary) == installed, (
                f"{unit} runs {binary} and the runbook installs just to {installed}"
            )

    def test_the_reading_finds_both_ends_it_crosses(self) -> None:
        """The positive control: an empty read on either side would make the crossing vacuous."""
        assert _where_the_runbook_installs_just().name == "just"
        for unit in ("syncr-backup.service", "syncr-walship.service", "syncr-learning.service"):
            assert _exec_start(directives(SYSTEMD / unit))

    def test_the_runbook_starts_a_service_rather_than_only_enabling_a_timer(self) -> None:
        """The step that catches the path disagreement at deploy time rather than at 03:00."""
        runbook = read(DEPLOY_AND_ROLLBACK)

        assert "systemctl start syncr-walship.service" in runbook
        assert "systemctl status syncr-walship.service" in runbook
        assert "command -v just" in runbook, "and the operator records where the binary landed"

    @pytest.mark.parametrize(
        "unit", ["syncr-backup.service", "syncr-walship.service", "syncr-learning.service"]
    )
    def test_no_unit_needs_a_compose_seam(self, unit: str) -> None:
        """The DEFAULT carries the digest pins, so the timer and a human run the same images.

        The first version set `SYNCR_OPS_COMPOSE` in each unit and left the default base-file-only,
        so the three timers were correct and every documented human path resolved `syncr-api:latest`
        which a digest pull never creates. Putting the pins in the default made the units' seam
        redundant; asserting its absence is what stops it coming back and taking the human paths
        with it.
        """
        assert "SYNCR_OPS_COMPOSE" not in directives(SYSTEMD / unit)

    def test_the_recipes_the_units_call_compose_the_digest_pins_by_default(self) -> None:
        """Read from the justfile's own defaults, which is what every caller resolves."""
        justfile = read(Path("justfile"))

        for variable in ("ops_compose", "restore_compose"):
            declared = justfile.partition(f"{variable} := env_var_or_default(")[2].partition(")")[0]
            assert "docker-compose.deploy.yml" in declared, variable

    @pytest.mark.parametrize(
        "unit", ["syncr-backup.service", "syncr-walship.service", "syncr-learning.service"]
    )
    def test_each_unit_points_at_a_runbook(self, unit: str) -> None:
        content = read(SYSTEMD / unit)
        stated = next(line for line in content.splitlines() if line.startswith("Documentation="))
        named = stated.partition("file:/opt/syncr/")[2]

        assert (repo_root() / named).is_file(), stated

    def test_the_wal_unit_cannot_overlap_itself(self) -> None:
        """Two shippers draining one directory is a race over files that must arrive in order."""
        assert f"TimeoutStartSec={SHIP_INTERVAL_SECONDS - 15}s" in read(
            SYSTEMD / "syncr-walship.service"
        )


class TestTheRecipesTheRunbooksName:
    """Every `just` recipe a runbook tells an operator to run has to exist."""

    def test_every_named_recipe_is_in_the_justfile(self) -> None:
        justfile = read(Path("justfile"))
        named = _recipes_named_in(
            read(one)
            for one in (
                BACKUP_STALE,
                RESTORE_FROM_BACKUP,
                DEPLOY_AND_ROLLBACK,
                ROTATE_SECRETS,
                DISK_PRESSURE,
                CLOCK_DRIFT,
                ICS_FEED_BROKEN,
            )
        )

        assert named, "the reading found no recipes at all, so it asserts nothing"
        for recipe in sorted(named):
            assert f"\n{recipe}:" in justfile or f"\n{recipe} " in justfile, recipe


class TestTheShellVariablesTheRunbooksUse:
    """A `$NAME` an operator pastes has to be defined in the file they pasted it from.

    `$DEPLOY` and `$OPS` were used in thirteen commands across four runbooks and defined nowhere in
    the tree, so the first check in the file for the case where nothing is wrong with the data ran
    against the base compose file alone. Same root cause as the recipes resolving `:latest`, and the
    same fix: say it where it is read.
    """

    # Variables a runbook may use without defining, because the shell or the reader supplies them.
    # Named rather than pattern-matched, so a fourteenth undefined variable fails.
    SUPPLIED_BY_THE_READER = frozenset({"?", "PWD", "HOME", "VERSION_CODENAME"})

    @pytest.mark.parametrize("name", _every_runbook())
    def test_every_variable_it_uses_is_defined_in_it(self, name: str) -> None:
        content = read(RUNBOOKS / name)

        undefined = sorted(
            _variables_used_in(content)
            - _variables_defined_in(content)
            - self.SUPPLIED_BY_THE_READER
        )

        assert undefined == [], (
            f"{name} uses {undefined} and defines none of them, so an operator pasting a command "
            "from it runs it with an empty value"
        )

    @pytest.mark.parametrize("name", _every_runbook())
    def test_every_variable_is_defined_before_it_is_used(self, name: str) -> None:
        """An operator pastes from the top down, so a definition below the first use is no help.

        The set comparison above is order-insensitive. It would pass a runbook whose conventions
        block sat at the bottom. Every one is at the top today, which is what this keeps true.
        """
        content = read(RUNBOOKS / name)

        late = sorted(
            variable
            for variable in _variables_used_in(content) - self.SUPPLIED_BY_THE_READER
            if _first_definition(content, variable) > _first_use(content, variable)
        )

        assert late == [], (
            f"{name} uses {late} above where it defines them, and an operator reads it downwards"
        )

    def test_it_reads_every_runbook_rather_than_the_eleven_section_21_names(self) -> None:
        """THE SET THIS BOUNDS IS EVERY FILE IN THE DIRECTORY, and the first version was not.

        Parametrized over section 21's eleven, it never read `backup-stale.md`: the file whose FIRST
        CHECK uses `$OPS`, and the one this ticket rewrote. Measured by removing that file's own
        definition and watching nothing redden.
        """
        reading = set(_every_runbook())

        assert "backup-stale.md" in reading
        assert set(SECTION_21_RUNBOOKS) < reading

    def test_the_reading_sees_a_variable_that_is_used(self) -> None:
        """The positive control: the two that shipped undefined."""
        used = _variables_used_in(
            "docker compose $OPS run --rm ops ls\ndocker compose $DEPLOY ps\n"
        )

        assert used == {"OPS", "DEPLOY"}

    def test_the_reading_sees_a_definition(self) -> None:
        assert _variables_defined_in('OPS="-f docker-compose.yml"\n') == {"OPS"}
        assert _variables_defined_in("export SYNCR_BACKUP_PRIVATE_KEY=/run/secrets/key\n") == {
            "SYNCR_BACKUP_PRIVATE_KEY"
        }

    def test_sourcing_the_host_secret_file_defines_what_it_documents(self) -> None:
        """`set -a; . ./.env` is how a runbook gets `DATABASE_URL`, and it is a definition."""
        found = _variables_defined_in("cd /opt/syncr && set -a && . ./.env && set +a\n")

        assert "DATABASE_URL" in found
        assert "POSTGRES_PASSWORD" in found, "read from .env.example rather than listed here"

    def test_the_compose_set_a_runbook_defines_is_the_one_the_recipes_carry(self) -> None:
        """A runbook defining its own different set would be a second topology."""
        justfile = read(Path("justfile"))

        for name in _every_runbook():
            content = read(RUNBOOKS / name)
            if 'OPS="' not in content:
                continue
            stated = content.partition('OPS="')[2].partition('"')[0]
            assert stated in justfile, f"{name} defines an OPS set the justfile does not carry"

    def test_the_local_drill_refuses_on_a_host_that_has_a_recorded_release(self) -> None:
        """An instrument refuses rather than relying on its name.

        `just drill-local` composes the one file that sets the off-host escape hatch. On a deployed
        host it would generate a throwaway keypair, dump the LIVE database to that host's own disk
        under it, restore into a locally-built image, and print "the data came back": every guard
        satisfied and nothing proven about the real bucket or the real key.

        `deployments/digests.env` is the fact that distinguishes a host from a workstation, and
        `just deploy` is the only thing that writes it.

        TWO FACTS, not one. The first version keyed on the digest file alone, which was untracked
        and NOT gitignored, so any `git clean -fd` removed it: after that `just restore-drill`
        aborted for want of digests AND this stopped refusing, leaving the throwaway-key path as
        the only drill that still ran. The digest file is gitignored now and the production public
        key is the second fact, and the two do not go missing together.
        THE ORDER IS THE POINT. The refusal was the first statement of `drill-local`'s body, and
        `drill-keys` is a dependency, so `just` ran it first: a run on a host wrote a throwaway
        keypair into `deployments/secrets` and only then refused. Measured, on this checkout.
        """
        guard = _recipe_body("_refuse-a-local-drill-on-a-deployed-host")

        assert "deployments/digests.env" in guard
        assert "deployments/secrets/backup-recipient.asc" in guard, (
            "the second fact, so one file going missing does not re-enable the path"
        )
        assert "exit 1" in guard
        assert "just restore-drill" in guard, "and it names the recipe to run instead"

        dependencies = _dependencies_of("drill-local")
        assert "_refuse-a-local-drill-on-a-deployed-host" in dependencies
        assert dependencies.index("_refuse-a-local-drill-on-a-deployed-host") < dependencies.index(
            "drill-keys"
        ), "just runs dependencies left to right, so the refusal has to come before the keygen"

    def test_the_digest_file_the_refusal_reads_is_gitignored(self) -> None:
        """The fact a guard keys on must survive the troubleshooting a runbook might invite.

        `git clean -fd` removes untracked files that nothing ignores, and the digest file was one.
        It also names the production public key now, but a guard whose evidence a routine command
        deletes is a guard with a schedule.
        """
        for name in ("deployments/digests.env", "deployments/digests.previous.env"):
            ignored = subprocess.run(  # noqa: S603 - a literal argv, no shell
                # `git` from the PATH the developer and CI both have, like every other call here.
                ["git", "check-ignore", "-q", name],  # noqa: S607
                cwd=repo_root(),
                check=False,
            )
            assert ignored.returncode == 0, (
                f"{name} is not gitignored, so `git clean -fd` removes it and the local drill "
                "stops refusing on a deployed host"
            )

    def test_the_recipes_read_the_digest_file_in_one_place(self) -> None:
        """One definition, four callers, and the callers keep their own argument quoting.

        The first version wrapped `docker compose` in a `_compose +ARGS` recipe, and `{{ARGS}}`
        interpolates a space-joined string into a shell, which re-splits it: a caller writing
        `run --rm ops sh -c 'psql -c "..."'` lost the quoting one layer down. A sourced snippet
        keeps `"$@"` intact.
        """
        justfile = read(Path("justfile"))

        assert 'read_digests := "set -a; [ -f deployments/digests.env ]' in justfile
        for recipe in ("backup-now", "wal-ship", "learn-once", "restore-drill"):
            assert "{{read_digests}}" in _recipe_body(recipe), recipe
        # No RECIPE by that name, read at the start of a line: the comment explaining the correction
        # names it, and a substring test over the whole file would find that instead.
        assert not any(line.startswith("_compose") for line in justfile.splitlines()), (
            "the wrapper recipe that re-split its arguments is gone"
        )


def _files_git_has() -> tuple[str, ...]:
    """Every path in the index, which is the repository as it is about to be committed."""
    listed = subprocess.run(
        # `git` from the PATH the developer and CI both have, like every other call here.
        ["git", "ls-files", "--cached", "-z"],  # noqa: S607
        cwd=repo_root(),
        capture_output=True,
        text=True,
        check=True,
    )
    return tuple(name for name in listed.stdout.split("\0") if name)


def _justfile_text(text: str | None) -> str:
    """The justfile a reading is about: the repository's, or one a control wrote."""
    return read(Path("justfile")) if text is None else text


def _recipe_body(name: str, *, text: str | None = None) -> str:
    """One `just` recipe's body, from its opening line to the next unindented one.

    ``text`` is for the synthetic controls, which drive the derivation below over a justfile they
    wrote rather than over this one.
    """
    lines = _justfile_text(text).splitlines()
    opener = next(
        index
        for index, line in enumerate(lines)
        if line.startswith(f"{name}:") or line.startswith(f"{name} ")
    )
    body: list[str] = []
    for line in lines[opener + 1 :]:
        if line and not line.startswith((" ", "\t")):
            break
        body.append(line)
    return "\n".join(body)


def _dependencies_of(name: str, *, text: str | None = None) -> list[str]:
    """The recipes `just` runs before ``name``, in the order it runs them.

    THE OPENER MAY CARRY PARAMETERS BEFORE THE COLON. The first version matched `f"{name}:"` and
    so RAISED for `e2e-only pattern:` rather than answering `[]`, which is fine while every caller
    names a recipe by hand and wrong the moment a caller asks this of every recipe declared.

    AND AN OPENER'S COLON IS NOT A `:=`. Widening for the parameter admitted `members := "..."`, so
    this answered a variable declaration with the pieces of its value instead of saying no such
    recipe exists. Its sibling below learned the same thing separately, which is how two readers
    came to disagree about what an opener is.
    """
    import re

    opener = re.compile(rf"^{re.escape(name)}(?:\s+[^:]*)?:(?!=)(.*)$")
    for line in _justfile_text(text).splitlines():
        found = opener.match(line)
        if found is not None:
            return found.group(1).split()
    raise AssertionError(f"the justfile declares no recipe named {name}")


def _recipe_names(*, text: str | None = None) -> frozenset[str]:
    """Every recipe the justfile declares, read from its own declarations.

    A recipe opens at column zero, may carry parameters, and ends its opener with `:`. Read rather
    than listed, because the point of crossing a unit's `ExecStart` against this is that a second
    copy of the recipe name is what would rot.

    TWO CORRECTIONS, both of which a caller asking this for EVERY recipe needs and a caller
    checking one name did not. A `[private]` recipe is still a recipe and `just` still runs it: the
    leading underscore was excluded, so the deployed-host refusal was not in this set. And
    `members := "..."` was IN it, because the name is followed by a space, so a variable
    declaration was answered as a recipe by every reader that took its word for it.
    """
    import re

    found = {
        match.group(1)
        for line in _justfile_text(text).splitlines()
        if (match := re.match(r"^(_?[a-z][a-z0-9-]*)(?:\s+[^:]*)?:(?!=)", line))
    }
    assert found, "no recipe was read out of the justfile, so this crossing is vacuous"
    return frozenset(found)


def _commands_of(body: str) -> str:
    """A recipe body with its comment lines and its shebang removed.

    A comment inside a body NAMES the recipes and the files it is explaining rather than reaching
    them, and the readings below are about what a recipe reaches.
    """
    return "\n".join(line for line in body.splitlines() if not line.strip().startswith("#"))


def _seed_artifacts() -> frozenset[str]:
    """Every file in the repository that IS seed data, which is every tracked SQL file.

    The schema is Alembic's, so SQL in this tree means hand-written rows rather than a migration.
    Read from the index rather than listed, because the defect a list cannot catch is a SECOND seed
    file arriving with a recipe of its own and no refusal.
    """
    return frozenset(name for name in _files_git_has() if name.endswith(".sql"))


def _recipes_invoked_in(body: str) -> frozenset[str]:
    """Every recipe a body runs as a nested `just` invocation.

    A QUOTED SPAN IS DATA RATHER THAN A COMMAND, and here that distinction decides the answer: the
    deployed-host refusal NAMES three recipes in the message it prints, so a reading over the whole
    line made the refusal a caller of the recipe that carries it.
    """
    import re

    commands = "\n".join(
        re.sub(r"\"[^\"]*\"|'[^']*'", "", line) for line in _commands_of(body).splitlines()
    )
    return frozenset(re.findall(r"(?<![\w-])just\s+([a-z][a-z0-9-]*)", commands))


def _recipes_reaching_seed_data(*, text: str | None = None) -> frozenset[str]:
    """Every recipe that can put seed data in a database, DERIVED rather than listed.

    Two ways to reach it, and both are members: a body that names seed data, and a recipe that runs
    one that does, whether as a nested `just` invocation or as a dependency.

    The second is not a courtesy. `just` runs a recipe's dependencies and then its body, so a
    refusal carried only by the inner recipe fires AFTER the outer one has started Postgres and run
    migrations. That is the ordering that once wrote a throwaway keypair onto a host and refused
    afterwards.
    """
    justfile = _justfile_text(text)
    artifacts = _seed_artifacts()
    names = _recipe_names(text=justfile)
    statements = {name: _commands_of(_recipe_body(name, text=justfile)) for name in names}
    reaching = {
        name for name, body in statements.items() if any(artifact in body for artifact in artifacts)
    }
    while True:
        grown = reaching | {
            name
            for name in names
            if reaching
            & (
                frozenset(_dependencies_of(name, text=justfile))
                | _recipes_invoked_in(statements[name])
            )
        }
        if grown == reaching:
            return frozenset(reaching)
        reaching = grown


def _facts_the_refusal_reads() -> tuple[str, ...]:
    """The evidence paths the refusal iterates, read from the recipe rather than restated.

    Derived so there is one runtime case per fact. A derived parametrization SHRINKS silently when a
    member is deleted, which is why the set is also asserted whole.
    """
    import re

    stated = re.search(r"for evidence in (.+?); do", _recipe_body(DEPLOYED_HOST_REFUSAL))
    assert stated is not None, "the refusal no longer iterates a list of facts"
    return tuple(stated.group(1).split())


def _drill_seed_in_a_tree_of_its_own(
    root: Path, *, evidence: Sequence[str]
) -> subprocess.CompletedProcess[str]:
    """Run `just drill-seed` against a copy of the justfile, in a tree that holds nothing.

    NOT IN THE CHECKOUT, and not as caution for its own sake: `docker-compose.yml` declares the
    project `syncr`, so a run here reaches whichever `syncr` Postgres is up on the machine and
    writes the seed into it. That is the defect, executed.

    The tree gets the justfile, the seed file the recipe redirects, the evidence files the case is
    about, and a `docker` that records being reached.
    """
    assert shutil.which("just") is not None, (
        "`just` is not on PATH, and it is what CI and the hooks run every gate through"
    )
    (root / "justfile").write_bytes((repo_root() / "justfile").read_bytes())
    seed = root / "deployments" / "drill" / "seed-local.sql"
    seed.parent.mkdir(parents=True)
    seed.write_bytes((repo_root() / "deployments" / "drill" / "seed-local.sql").read_bytes())
    for fact in evidence:
        (root / fact).parent.mkdir(parents=True, exist_ok=True)
        (root / fact).write_text("", encoding="utf-8")

    stub = root / "bin" / "docker"
    stub.parent.mkdir()
    stub.write_text(RECORDING_DOCKER, encoding="utf-8")
    stub.chmod(0o755)

    return subprocess.run(
        # `just` from the PATH the developer and CI both have, like every other call here.
        ["just", "drill-seed"],  # noqa: S607
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "PATH": f"{stub.parent}:{os.environ['PATH']}",
            "SYNCR_DOCKER_LOG": str(root / DOCKER_LOG),
        },
    )


def _the_scratch_teardown_in_a_tree_of_its_own(
    root: Path,
    *,
    inherited: str | None = None,
    dotenv: str | None = None,
    dotenv_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run `just e2e-down` against a copy of the justfile, in a tree that holds nothing.

    NOT IN THE CHECKOUT, and against a `docker` that can reach nothing, because the command under
    test is the one that destroys a project: the admitting direction needs the recipe to run to
    completion, and the only safe way to watch that is a stub. THE SCRATCH TEARDOWN RATHER THAN
    EITHER, for the same reason: no caller can point this at the recipe whose own scope is a
    developer's database.

    ``inherited`` is the environment a developer's shell would hand the recipe, and ``dotenv`` is
    the gitignored file compose reads from the project directory. A case passes one, the other, or
    both, which is how the precedence between them is driven. ``dotenv_bytes`` writes that file
    without an encoding, which is the only way to express a file compose reads and a text tool
    cannot.
    """
    assert shutil.which("just") is not None, (
        "`just` is not on PATH, and it is what CI and the hooks run every gate through"
    )
    (root / "justfile").write_bytes((repo_root() / "justfile").read_bytes())
    if dotenv is not None:
        (root / ".env").write_text(dotenv, encoding="utf-8")
    if dotenv_bytes is not None:
        (root / ".env").write_bytes(dotenv_bytes)

    stub = root / "bin" / "docker"
    stub.parent.mkdir()
    stub.write_text(RECORDING_DOCKER, encoding="utf-8")
    stub.chmod(0o755)

    environment = {
        **os.environ,
        "PATH": f"{stub.parent}:{os.environ['PATH']}",
        "SYNCR_DOCKER_LOG": str(root / DOCKER_LOG),
    }
    environment.pop("COMPOSE_PROJECT_NAME", None)
    if inherited is not None:
        environment["COMPOSE_PROJECT_NAME"] = inherited

    return subprocess.run(
        # `just` from the PATH the developer and CI both have, like every other call here.
        ["just", "e2e-down"],  # noqa: S607
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )


class TheDestructiveTeardown:
    """Nothing in this tree may TELL anyone to run ``docker compose down -v`` against a project
    holding anything a developer or a deployment keeps.

    ``down -v`` is scoped to the PROJECT, and that is the whole hazard: a local run of ticket 58's
    own drill proved what it means, because the drill and the deployed stack share a project name
    and its teardown deleted ``pgdata``, the WAL volume, the staging volume and the bucket. The code
    path was fixed to remove containers BY SERVICE NAME, and the instruction survived in a refusal
    message the operator reads while trying to recover years of data, falsely attributed to the
    recipe that avoids it.

    So the rule is stated over the whole tree rather than over one recipe: every occurrence must be
    a DECLARED line, or must be inside a recipe whose compose scope is a project that holds nothing
    anyone keeps.

    **THE SCOPE IS RESOLVED RATHER THAN NAMED.** The first version allowed exactly one recipe by
    name, which is what the rule needed while one stack existed. A second scratch stack arrived, its
    overlay declares ``name: syncr-e2e``, and its teardown destroys nothing anyone holds -- and the
    guard refused it, because a recipe list cannot tell a scratch project from the deployed one.
    What can is the project the line acts on, and TWO INPUTS DECIDE IT: the ``-f`` list, whose last
    declared ``name:`` wins as compose merges them, and an explicit override by ``-p``,
    ``--project-name`` or ``COMPOSE_PROJECT_NAME``, which beats the files entirely. Reading only the
    first admitted ``-p syncr`` carrying the e2e stack's files, which resolves to ``syncr-e2e`` by
    its files and destroys the DEPLOYED project when it runs; it also refused ``-p syncr-scratch3``
    over the base file, which destroys nothing. Too narrow and too wide on one axis at once, which
    is what a derivation that reads one of two deciding inputs looks like. The override is now read
    first, WITH COMPOSE'S OWN PRECEDENCE AMONG THE OVERRIDES: a flag beats the environment variable
    and the last flag beats an earlier one, because enumerating the four spellings without the
    precedence between them admitted two lines carrying contradictory overrides. A project name this
    reading cannot resolve is REFUSED rather than admitted.

    The two projects that hold something are the ones the justfile's own ``dev_compose`` and
    ``deploy_compose`` resolve to. A third scratch stack is allowed the day it declares a project
    name of its own, and a recipe pointed at the deployed project is refused whatever it is called,
    which is now true of a line carrying several overrides as well as of one carrying none.
    ``restore_compose`` resolves to the DEPLOYED project, which is exactly the reading that cost a
    ``pgdata``, and a test below states that figure so it cannot drift quietly.

    ``dev-reset`` is the one recipe allowed to destroy a project someone holds, because its name
    says what it does and the thing it destroys is the developer's own stack.

    BOTH EXEMPTION ARMS HAVE THEIR OWN CONTROLS, at the predicate rather than two layers under it.
    Opening either one fully -- `_scoped_to_a_scratch_project` or `_inside_dev_reset` returning True
    for everything -- left all 153 tests green when this class was first widened, because the scope
    cases called `_project_named_by` directly and could not see either arm. A guard widened with six
    controls that do not cover the widening is the shape this class exists to refuse.

    THREE TIMES THE READING WAS NARROWER THAN THE RULE, and someone else caught each one. Five
    suffixes and one filename, so a `.service` running the command was invisible. Then every text
    file under `rglob`, which read this module's own negative controls out of `.pytest_cache`. Then
    a hand-written skip list with two crossings to keep it honest, where the crossing that checked
    "nothing skipped is tracked" was itself root-anchored while the skip rule matched any path
    component. `_lines_mentioning` now asks git what the files are and keeps no list.

    AND TWICE THE EXEMPTION WAS A HEURISTIC OVER PROSE. First the substring `not`, so `Nothing`,
    `Note`, `cannot`, `Another` and `Notice` each exempted a line that instructed the command. Then
    whole phrases, which a line carrying a negation about something ELSE still satisfied: "Do not
    stop the api first; run `docker compose down -v` to reset the stack" was exempt. No phrase list
    can answer whether a negation applies to the command, so the exemption is now ENUMERATED, in
    the shape this class already used for `DECLARING_FILE`.
    """

    # The one recipe allowed to destroy a project someone holds. Its name says what it does, and
    # what it destroys is the developer's own stack rather than a deployment's.
    ALLOWED_RECIPE = "dev-reset"

    # The justfile variables whose resolved project a `down -v` may NOT be scoped to, because each
    # names a stack holding something someone keeps: the developer's database, and the deployment's.
    PROTECTED_SCOPES = ("dev_compose", "deploy_compose")

    # EVERY LINE ALLOWED TO NAME THE COMMAND WITHOUT INSTRUCTING IT, as (path, substring) pairs.
    #
    # Declared, not recognised. A phrase list asks whether a negation appears ANYWHERE on the line,
    # which is not the question: five contrived lines carrying an unrelated negation each instructed
    # the command and each was exempt. An enumerated set cannot be fooled by prose, and it inverts
    # the cost: a NEW forbidding line is a deliberate addition here, and a new instructing line
    # fails.
    #
    # `test_every_declared_exemption_matches_exactly_one_line` keeps this from going stale in either
    # direction: a pair that matches nothing is dead, and a pair that matches two is too loose.
    EXEMPTED = (
        ("deployments/ops/restore.py", "Never `docker compose down -v`"),
        ("docker-compose.restore.yml", "dropping one needs a `down -v`, never"),
        ("justfile", "Never `down -v`"),
    )

    # The one file allowed to quote the forbidden instruction without forbidding it: this one, which
    # cannot state the rule without naming the string. Declared rather than pattern-matched, so a
    # second file claiming the same exemption fails.
    DECLARING_FILE = "packages/syncr-api/tests/test_deployment_figures.py"

    # The nine file types a reviewer planted the instruction in, four of which the first reading
    # saw. The walk's positive control rather than its input: the walk reads every text file.
    PLANTED = (
        "invented.py",
        "invented.md",
        "invented.yml",
        "invented.service",
        "invented.timer",
        "Dockerfile",
        "invented.toml",
        "invented.sh",
        "extensionless-script",
    )


class TestTheDestructiveTeardown:
    def test_nothing_instructs_it_outside_a_project_that_holds_nothing(self) -> None:
        offenders = [
            f"{path}:{number}: {line.strip()}"
            for path, number, line in _lines_mentioning("down -v")
            if path != TheDestructiveTeardown.DECLARING_FILE
            and not _inside_dev_reset(path, number)
            and not _scoped_to_a_scratch_project(path, number, line)
            and not _declared_exempt(path, line)
        ]

        assert offenders == [], (
            "these lines mention `docker compose down -v` without being declared on "
            "`TheDestructiveTeardown.EXEMPTED`, and the command is scoped to the PROJECT rather "
            f"than to a service: {offenders}"
        )

    def test_the_projects_each_compose_scope_resolves_to(self) -> None:
        """THE FIGURE THE WHOLE RULE TURNS ON, stated so it cannot drift quietly.

        The restore drill resolves to the DEPLOYED project, which is the reading that deleted a
        `pgdata`: its own overlay declares no name and the deploy overlay it composes with declares
        `syncr`. The e2e stack resolves to a project of its own, which is why its teardown is
        allowed. A change to any of these four is a change to what `down -v` would destroy.
        """
        variables = _justfile_variables()
        resolved = {
            scope: _project_named_by(
                _compose_files_in(f"docker compose {{{{{scope}}}}} up", variables)
            )
            for scope in ("dev_compose", "e2e_compose", "deploy_compose", "restore_compose")
        }

        assert resolved == {
            "dev_compose": "syncr-dev",
            "e2e_compose": "syncr-e2e",
            "deploy_compose": "syncr",
            "restore_compose": "syncr",
        }

    def test_the_scopes_that_hold_something_are_the_two_the_guard_protects(self) -> None:
        """The protected set is derived, so it cannot be a list that stops describing the stacks."""
        assert _protected_projects() == {"syncr-dev", "syncr"}

    @pytest.mark.parametrize(
        ("scope", "is_scratch"),
        [
            ("e2e_compose", True),
            ("dev_compose", False),
            ("deploy_compose", False),
            ("restore_compose", False),
            ("ops_compose", False),
            ("monitoring_compose", False),
        ],
    )
    def test_which_scopes_the_allowance_admits(self, scope: str, is_scratch: bool) -> None:
        """THE NEGATIVE CONTROLS THE OLD RULE DID NOT NEED AND THIS ONE DOES.

        Allowing a recipe by its resolved project rather than by its name is a WIDENING, so the
        shapes it must still refuse are driven: a `down -v` scoped to the deployed stack, to the
        restore drill (which is the deployed stack), to the monitoring composition or to the ops
        one-shots is an offender whatever recipe it sits in. Only a scope declaring a project of its
        own is admitted.
        """
        variables = _justfile_variables()
        project = _project_named_by(
            _compose_files_in(f"docker compose {{{{{scope}}}}} down -v", variables)
        )

        assert (project is not None and project not in _protected_projects()) is is_scratch

    def test_a_line_naming_no_compose_file_is_not_admitted(self) -> None:
        """A bare instruction resolves to no project, so it cannot be a scratch one."""
        assert _project_named_by(_compose_files_in("docker compose down -v", {})) is None

    # --- The controls over the two exemption arms themselves --------------------------------------
    #
    # THE SIX SCOPE CASES ABOVE CALL `_project_named_by` TWO LAYERS BELOW THE PREDICATE, so neither
    # exemption arm is covered by them: opening `_scoped_to_a_scratch_project` or
    # `_inside_dev_reset` fully left every test green. These are the arms' own controls.

    @pytest.mark.parametrize(
        ("scope", "admitted"),
        [
            ("e2e_compose", True),
            ("dev_compose", False),
            ("deploy_compose", False),
            ("restore_compose", False),
            ("ops_compose", False),
            ("monitoring_compose", False),
        ],
    )
    def test_the_scratch_exemption_judges_the_scope_at_the_predicate(
        self, scope: str, admitted: bool
    ) -> None:
        """Asked of the predicate the sweep calls, in a recipe that really carries the command."""
        line = f"    docker compose {{{{{scope}}}}} down -v"

        assert _scoped_to_a_scratch_project("justfile", _e2e_down_line(), line) is admitted, scope

    @pytest.mark.parametrize(
        "override",
        [
            "docker compose -p syncr {{e2e_compose}} down -v",
            "docker compose --project-name syncr {{e2e_compose}} down -v",
            "docker compose --project-name=syncr {{e2e_compose}} down -v",
            "COMPOSE_PROJECT_NAME=syncr docker compose {{e2e_compose}} down -v",
            "docker compose -p syncr-dev {{e2e_compose}} down -v",
        ],
    )
    def test_a_project_override_pointing_at_a_protected_stack_is_refused(
        self, override: str
    ) -> None:
        """THE HOLE THE FILE-ONLY READING LEFT, in the four spellings compose accepts.

        Each of these carries the e2e stack's own files, so the ``-f`` reading resolves
        ``syncr-e2e`` and calls it scratch; each actually tears down a project someone holds.
        `down -v` there is the reading that once deleted a `pgdata`.
        """
        assert not _scoped_to_a_scratch_project("justfile", _e2e_down_line(), f"    {override}")

    def test_a_project_override_naming_a_scratch_stack_is_admitted(self) -> None:
        """The other direction, which the file-only reading got wrong too.

        `-p syncr-scratch3` over the base file destroys nothing anyone holds, and refusing it was a
        false failure: the override decides the project, so it is what has to be judged.
        """
        line = "    docker compose -p syncr-scratch3 -f docker-compose.yml down -v"

        assert _scoped_to_a_scratch_project("justfile", _e2e_down_line(), line)

    @pytest.mark.parametrize(
        "unreadable",
        [
            "docker compose -p $PROJECT {{e2e_compose}} down -v",
            "docker compose -p {{some_project}} {{e2e_compose}} down -v",
            'docker compose -p "$(cat name)" {{e2e_compose}} down -v',
        ],
    )
    def test_an_override_this_reading_cannot_resolve_is_refused(self, unreadable: str) -> None:
        """A guard refuses what it cannot judge, because the alternative is admitting it.

        The project is decided somewhere this reading cannot see, so the answer is no rather than a
        guess about what the variable holds.
        """
        assert not _scoped_to_a_scratch_project("justfile", _e2e_down_line(), f"    {unreadable}")

    # --- The precedence AMONG the overrides -----------------------------------------------------
    #
    # ENUMERATING THE FOUR SPELLINGS WAS NOT ENOUGH. A first-match reading admitted two lines that
    # compose acts on as `syncr`, because it never asked which override wins. Compose's rules are
    # that a FLAG beats `COMPOSE_PROJECT_NAME` and the LAST flag beats an earlier one, so the pairs
    # below carry the same two names in both orders and must come out opposite: a case that only
    # refused "a line with two overrides" would pass without implementing either rule.
    # two overrides" would pass without implementing either rule.

    @pytest.mark.parametrize(
        ("line", "admitted", "why"),
        [
            (
                "COMPOSE_PROJECT_NAME=syncr-scratch docker compose -p syncr"
                " {{e2e_compose}} down -v",
                False,
                "the flag beats the environment variable, so this acts on syncr",
            ),
            (
                "COMPOSE_PROJECT_NAME=syncr docker compose -p syncr-scratch"
                " {{e2e_compose}} down -v",
                True,
                "the flag beats the environment variable, so this acts on syncr-scratch",
            ),
            (
                "docker compose -p syncr-scratch -p syncr {{e2e_compose}} down -v",
                False,
                "the last flag wins, so this acts on syncr",
            ),
            (
                "docker compose -p syncr -p syncr-scratch {{e2e_compose}} down -v",
                True,
                "the last flag wins, so this acts on syncr-scratch",
            ),
        ],
    )
    def test_the_override_precedence_is_composes_own(
        self, line: str, admitted: bool, why: str
    ) -> None:
        assert (
            _scoped_to_a_scratch_project("justfile", _e2e_down_line(), f"    {line}") is admitted
        ), why

    def test_the_environment_variable_is_read_only_when_no_flag_names_a_project(self) -> None:
        """Stated at the reader rather than through the predicate, so the rule is visible alone."""
        assert (
            _project_override_in("COMPOSE_PROJECT_NAME=one docker compose -p two down -v") == "two"
        )
        assert _project_override_in("COMPOSE_PROJECT_NAME=one docker compose down -v") == "one"
        assert _project_override_in("docker compose -p one -p two down -v") == "two"
        assert _project_override_in("docker compose --project-name one -p two down -v") == "two"
        assert _project_override_in("docker compose down -v") is None

    def test_the_scratch_exemption_refuses_a_line_outside_any_recipe(self) -> None:
        """A runbook sentence is not a recipe, whatever compose files it happens to name."""
        line = "Run `docker compose {{e2e_compose}} down -v` to reset the stack."

        assert not _scoped_to_a_scratch_project("docs/runbooks/invented.md", 1, line)

    def test_the_dev_reset_exemption_stops_at_the_end_of_the_recipe(self) -> None:
        """`dev-reset`'s exemption is UNCONDITIONAL over its lines, so its extent is the whole rule.

        The recipe's own body is exempt and the lines after it are not. This was red: the reader
        skipped `#` lines when resetting, so the comment two lines below the body inherited
        `dev-reset` and its blanket exemption, and a `down -v` written into a comment there would
        have been exempt.
        """
        body = _dev_reset_line()
        lines = read(Path("justfile")).splitlines()

        assert _inside_dev_reset("justfile", body)
        after = next(
            index
            for index in range(body + 1, len(lines) + 1)
            if lines[index - 1] and not lines[index - 1].startswith((" ", "\t"))
        )
        assert not _inside_dev_reset("justfile", after), (
            f"justfile:{after} is outside the recipe and inherits its blanket exemption: "
            f"{lines[after - 1]!r}"
        )

    def test_both_exemption_arms_are_reached_by_the_sweep_they_guard(self) -> None:
        """The arms above are the ones the offender sweep calls, asserted rather than assumed.

        A control at a predicate is only a control if the sweep goes through it. Both lines the tree
        ships are exempt for one reason each, and this states which.
        """
        e2e = _e2e_down_line()
        dev = _dev_reset_line()

        assert _recipe_holding("justfile", e2e) == "e2e-down"
        assert not _inside_dev_reset("justfile", e2e)
        assert _scoped_to_a_scratch_project(
            "justfile", e2e, read(Path("justfile")).splitlines()[e2e - 1]
        )
        assert _inside_dev_reset("justfile", dev)
        assert not _scoped_to_a_scratch_project(
            "justfile", dev, read(Path("justfile")).splitlines()[dev - 1]
        )

    def test_the_reading_sees_the_line_that_shipped(self, tmp_path: Path) -> None:
        """The positive control, over the WALK, in every file type a reviewer planted it in.

        Driven against a tree of its own rather than against the repository, because the rule's
        whole point is that a NEW file cannot reintroduce the instruction, and a control that could
        not see one in a file this suite does not already know about would prove nothing.

        NINE TYPES, because the first version of the walk read five suffixes and one filename and
        therefore saw four of these.
        """
        shipped = (
            "`just restore-drill` does that with `docker compose down -v` on the scratch instance."
        )
        for name in TheDestructiveTeardown.PLANTED:
            (tmp_path / name).write_text(f"{shipped}\n", encoding="utf-8")
        (tmp_path / "an-image.png").write_bytes(b"\x89PNG\r\n\x1a\n\xff down -v")

        found = _lines_mentioning("down -v", root=tmp_path)
        offenders = {path for path, line_number, line in found if not _declared_exempt(path, line)}

        assert offenders == set(TheDestructiveTeardown.PLANTED), (
            "the reading covers every text file type, and none of these is a declared exemption"
        )
        assert "an-image.png" not in {path for path, _, _ in found}, "a binary file is not read"

    @pytest.mark.parametrize(
        "line",
        [
            # The five the substring test on `not` exempted.
            "Nothing else clears it: run `docker compose down -v` on the host.",
            "Note: run `docker compose down -v` to reset the stack.",
            "You cannot skip this. Run `docker compose down -v`.",
            "Another option is `docker compose down -v`.",
            "Notice the volume: `docker compose down -v`.",
            # The five the WHOLE-PHRASE list exempted, each carrying a negation about something
            # else.
            "Do not stop the api first; run `docker compose down -v` to reset the stack.",
            "You must not skip this: run `docker compose down -v` on the host.",
            "Don't wait for the timer. Run `docker compose down -v`.",
            "This is not safe to interrupt, so run `docker compose down -v` and wait.",
            "Never mind the warning: run `docker compose down -v`.",
            # And the shapes the phrase list got right, still not exemptions unless declared.
            "Never `docker compose down -v`: it is scoped to the project.",
            "Do not run `docker compose down -v` here.",
        ],
    )
    def test_no_prose_exempts_a_line_that_is_not_declared(self, line: str) -> None:
        """TEN OF THESE ESCAPED A HEURISTIC, five per version, and the last two show the cost.

        The final two are genuine refusals and they are STILL offenders here, because the exemption
        is a declared set rather than a reading of the sentence. That is the trade: a real new
        refusal has to be added to `EXEMPTED` by hand, and in exchange no line talks its way past
        the guard.
        """
        assert not _declared_exempt("docs/runbooks/invented.md", line), line

    def test_every_declared_exemption_matches_exactly_one_line(self) -> None:
        """The declared set cannot go stale in either direction.

        A pair matching nothing is a dead entry that would silently stop exempting anything, and a
        pair matching two lines is a substring loose enough to exempt a line nobody read.
        """
        occurrences = _lines_mentioning("down -v")

        for path, fragment in TheDestructiveTeardown.EXEMPTED:
            matched = [
                f"{found}:{number}"
                for found, number, line in occurrences
                if found == path and fragment in line
            ]
            assert len(matched) == 1, f"({path}, {fragment!r}) matches {matched}, not one line"

    def test_the_reading_covers_every_file_type_that_carries_the_string(self) -> None:
        """An EXACT set rather than a count, which is what round 1 asked for on another reading.

        `>= 2` passed with three suffixes. It would keep passing if the walk narrowed to two, which
        is exactly how the systemd units came to be invisible.
        """
        suffixes = {
            Path(path).suffix or Path(path).name for path, _, _ in _lines_mentioning("down -v")
        }

        assert suffixes == {".py", ".yml", "justfile"}, (
            "these are the file types that carry the string TODAY: the refusal message, the "
            "restore overlay's comment, this module, and the two recipes. A new one is a "
            "deliberate change."
        )

    def test_the_walk_reads_nothing_git_ignores(self) -> None:
        """THE ONE CROSSING LEFT, and it replaced two that a hand-written list needed.

        The reading is `git ls-files --cached`, so this is a property of git's answer rather than of
        a list: nothing generated, nothing ignored, and no entry that could quietly exclude a
        tracked file. The previous version kept a list and crossed it twice, and the crossing that
        checked "nothing skipped is tracked" passed `dist` as a ROOT-ANCHORED pathspec while the
        skip rule matched any path component, so a tracked `frontend/dist/x.md` was invisible to
        both.
        """
        read_paths = sorted({path for path, _, _ in _lines_mentioning("docker")})
        assert read_paths, "the reading found nothing, so this asserts nothing"

        ignored = subprocess.run(
            # `git` from the PATH the developer and CI both have, like every other call here.
            ["git", "check-ignore", "--stdin"],  # noqa: S607
            cwd=repo_root(),
            input="\n".join(read_paths),
            capture_output=True,
            text=True,
            check=False,
        )

        assert ignored.stdout.strip() == "", (
            f"the reading covered paths git ignores, which are generated rather than the "
            f"repository: {ignored.stdout.strip().splitlines()}"
        )

    def test_the_reading_sees_a_file_in_a_directory_a_skip_list_would_have_excluded(self) -> None:
        """THE CONTROL FOR THE CLASS THAT KEPT RECURRING, stated over a real tracked path.

        `frontend/dist/x.md` is the shape a reviewer planted to defeat the hand-written list:
        tracked, inside a directory the list named, and therefore invisible to the walk AND to the
        crossing that was supposed to catch exactly that. There is no list now, so the property to
        hold is that the reading covers a tracked file wherever it sits, including under a name a
        list would have skipped.
        """
        under_a_skipped_name = [
            name
            for name in _files_git_has()
            if any(
                part in {"dist", "coverage", "htmlcov", "__pycache__", "node_modules"}
                for part in Path(name).parts
            )
        ]

        assert _files_git_has(), "git listed nothing, so the reading reads nothing"
        assert under_a_skipped_name == [], (
            "a tracked file now sits under one of the names the old skip list held, so the reading "
            f"has to cover it and this control has to be driven rather than vacuous: "
            f"{under_a_skipped_name}"
        )

    def test_the_refusal_names_the_command_the_recipe_actually_runs(self) -> None:
        """The remedy an operator is given has to be the one the drill uses."""
        with pytest.raises(RestoreRefused) as refused:
            require_empty(run=_answering("37"))

        stated = str(refused.value)
        assert "rm -fsv postgres-restore" in stated
        assert "Never `docker compose down -v`" in stated
        assert "rm -fsv postgres-restore" in read(Path("justfile")), (
            "the message names a command `just restore-drill` does not run"
        )


def _answering(stdout: str) -> Run:
    """A :class:`ops.process.Run` answering one value, for the one psql reading a refusal takes."""

    def run(argv: Sequence[str], **_: object) -> Result:
        return Result(argv=tuple(argv), returncode=0, stdout=stdout, stderr="")

    return cast("Run", run)


def _declared_exempt(path: str, line: str) -> bool:
    """Whether this exact line is one of the declared exemptions.

    Both halves have to match: a pair exempts a substring IN A NAMED FILE, so the same sentence in a
    runbook is still an offender. Two heuristics preceded this, and each was defeated by ordinary
    prose carrying a negation that was not about the command.
    """
    return any(
        path == declared and fragment in line
        for declared, fragment in TheDestructiveTeardown.EXEMPTED
    )


def _lines_mentioning(fragment: str, *, root: Path | None = None) -> list[tuple[str, int, str]]:
    """Every line of every TEXT file THE REPOSITORY CONTAINS that names ``fragment``.

    GIT ANSWERS WHAT THE FILES ARE. There is no exclusion list, because three successive widenings
    of this reading were each caught by someone else rather than by me:

    1. Five suffixes and one filename, so a `.service` running the command was invisible.
    2. Every text file under `rglob`, which read `.pytest_cache/v/cache/nodeids` and therefore this
       module's own negative controls.
    3. A hand-written skip list with two crossings against git to keep it honest, and the crossing
       that checked "nothing skipped is tracked" used ROOT-ANCHORED pathspecs while the skip rule
       matched any path component, so a tracked `frontend/dist/x.md` instructing the command was
       invisible and the whole class still passed. The fix for the narrowing was narrower than the
       narrowing.

    `git ls-files --cached` is the index, which is what is about to become the repository: it covers
    a staged new file, which is the moment the pre-commit hook and CI care about, and it cannot see
    a developer's scratch notes or any generated tree, so the set the reading covers is by
    construction the set the rule is about. A file is text if it decodes as UTF-8, which is the
    question the reading has to ask anyway, so a PNG is skipped by the read rather than by a list.

    ``root`` is for the positive control alone: a scratch tree the test built, which is not a git
    repository and holds nothing but what the test planted.
    """
    if root is not None:
        paths = [path for path in sorted(root.rglob("*")) if path.is_file()]
        walking = root
    else:
        walking = repo_root()
        paths = [walking / name for name in _files_git_has()]

    found: list[tuple[str, int, str]] = []
    for path in paths:
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(content.splitlines(), start=1):
            if fragment in line:
                found.append((str(path.relative_to(walking)), number, line))
    return found


def _inside_dev_reset(path: str, number: int) -> bool:
    """Whether this line is inside the one recipe allowed to destroy a project someone holds."""
    return _recipe_holding(path, number) == TheDestructiveTeardown.ALLOWED_RECIPE


def _recipe_holding(path: str, number: int) -> str | None:
    """The justfile recipe this line is the body of, or None when it is not in one.

    A recipe opens at column zero and ends at the NEXT LINE AT COLUMN ZERO, comments included. An
    earlier version of this reader skipped `#` lines when resetting, which gave the recipe two extra
    lines of reach: justfile line 131 is a comment between `dev-reset`'s body and the next
    declaration, it resolved to `dev-reset`, and `_inside_dev_reset` exempts that recipe's lines
    UNCONDITIONALLY. A
    `down -v` written into a comment there would have been blanket-exempt, and the window grew with
    every comment added. A recipe's body is indented, so nothing legitimate is lost by ending at the
    first unindented line whatever it says.
    """
    import re

    if path != "justfile":
        return None
    lines = read(Path("justfile")).splitlines()
    opener: str | None = None
    for index, line in enumerate(lines, start=1):
        if line and not line.startswith((" ", "\t")):
            named = re.match(r"^([a-z][\w-]*)(?:\s+[^:]*)?:", line)
            opener = None if named is None else named.group(1)
        if index == number:
            return opener
    return None


def _justfile_variables() -> dict[str, str]:
    """Every ``name := "value"`` the justfile declares, which is how a recipe names a compose scope.

    A multi-line ``env_var_or_default(...)`` is read too: the default is the composition an operator
    gets without overriding it, and that is the scope the guard has to judge.
    """
    import re

    text = read(Path("justfile"))
    declared: dict[str, str] = {}
    for found in re.finditer(
        r"^([a-z][\w_]*)\s*:=\s*(.+?)(?=^\S|\Z)", text, re.MULTILINE | re.DOTALL
    ):
        declared[found.group(1)] = " ".join(found.group(2).split())
    return declared


def _expanded(command: str, variables: Mapping[str, str]) -> str:
    """The line with every justfile variable in it replaced by its declared value."""
    import re

    expanded = command
    for _ in range(4):
        found = re.search(r"\{\{\s*([a-z][\w_]*)\s*\}\}", expanded)
        if found is None:
            break
        expanded = expanded.replace(found.group(0), variables.get(found.group(1), ""))
    return expanded


def _compose_files_in(command: str, variables: Mapping[str, str]) -> tuple[str, ...]:
    """The ``-f`` list a command line names, with any justfile variable in it expanded."""
    import re

    return tuple(re.findall(r"-f\s+(\S+\.ya?ml)", _expanded(command, variables)))


def _project_named_by(files: Iterable[str]) -> str | None:
    """The compose project a ``-f`` list resolves to, which is the LAST file that declares a name.

    Compose merges the files in order and a later ``name:`` wins, so the project a command acts on
    is decided by the end of the list rather than by the base file.
    """
    project: str | None = None
    for name in files:
        path = repo_root() / name
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("name:"):
                project = line.removeprefix("name:").strip()
    return project


def _protected_projects() -> set[str]:
    """The projects holding something someone keeps: the developer's stack, and the deployment's."""
    variables = _justfile_variables()
    protected = set()
    for scope in TheDestructiveTeardown.PROTECTED_SCOPES:
        project = _project_named_by(
            _compose_files_in(f"docker compose {{{{{scope}}}}} up", variables)
        )
        if project is not None:
            protected.add(project)
    return protected


def _project_override_in(command: str) -> str | None:
    """The project a line names EXPLICITLY, which overrides what its ``-f`` list would resolve to.

    ``-p``, ``--project-name`` and ``COMPOSE_PROJECT_NAME`` all decide the project compose acts on,
    and the ``-f`` list decides it only when none of them is present. A reading that saw the files
    and not the override admitted ``-p syncr -f docker-compose.yml -f e2e/docker-compose.e2e.yml
    down -v``, which resolves to ``syncr-e2e`` by its files and destroys the DEPLOYED project.

    **AND THE PRECEDENCE AMONG THE OVERRIDES IS PART OF THE READING.** Enumerating the four
    spellings was not enough: a first-match search admitted ``COMPOSE_PROJECT_NAME=syncr-scratch
    docker compose -p syncr ... down -v`` and ``-p syncr-scratch -p syncr ... down -v``, both of
    which compose acts on as ``syncr``. Two rules decide it, and they are compose's rather than this
    reading's: a FLAG beats the environment variable, and the LAST flag beats an earlier one. So the
    flags are collected and the last is taken, and the variable is consulted only when there is no
    flag at all.
    """
    import re

    flags: list[str] = re.findall(r"(?:^|\s)(?:-p|--project-name)[= ]\s*(\S+)", command)
    if flags:
        return flags[-1]
    environment: list[str] = re.findall(r"(?:^|\s)COMPOSE_PROJECT_NAME=(\S+)", command)
    return environment[-1] if environment else None


def _is_a_scratch_project(project: str | None) -> bool:
    """Whether this project holds nothing anyone keeps.

    A name the reading cannot resolve to a plain project -- a shell variable, an unexpanded just
    interpolation -- is NOT a scratch project: the guard has to refuse what it cannot judge, because
    the alternative is admitting a line whose project is decided somewhere this reading cannot see.

    WHAT IS STILL NOT BOUNDED. The reading judges one line, with the justfile's own variables
    expanded, so a project name decided anywhere else never reaches it: `COMPOSE_PROJECT_NAME` in a
    gitignored `.env`, or exported by an earlier line of a shebang recipe, whose body runs in one
    shell rather than one shell per line. Compose honours that variable over the last `name:` in the
    `-f` list, so such a line is ADMITTED here while compose acts on the project the variable names.
    A name this reading can see and cannot resolve is refused; a name it cannot see is not.
    """
    import re

    if project is None or not re.match(r"^[a-z0-9][a-z0-9_.-]*$", project):
        return False
    return project not in _protected_projects()


def _scoped_to_a_scratch_project(path: str, number: int, line: str) -> bool:
    """Whether this line runs the command against a project that holds nothing anyone keeps.

    THE OVERRIDE IS READ BEFORE THE FILES, because that is the order compose applies them: a line
    carrying ``-p``, ``--project-name`` or ``COMPOSE_PROJECT_NAME`` acts on THAT project whatever
    its ``-f`` list declares. Reading only the files was too narrow in one direction and too wide in
    the other at once: it admitted a deployed-project teardown wearing the e2e stack's files, and
    refused a
    scratch-project teardown of the base file alone.

    Otherwise the compose files the line names are resolved and their project read, so a recipe is
    judged by what it acts on rather than by what it is called. A line naming no compose file and no
    override resolves to no project, and is not a scratch one.
    """
    if path != "justfile" or _recipe_holding(path, number) is None:
        return False
    variables = _justfile_variables()
    expanded = _expanded(line, variables)
    override = _project_override_in(expanded)
    if override is not None:
        return _is_a_scratch_project(override)
    return _is_a_scratch_project(_project_named_by(_compose_files_in(line, variables)))


def _lines_of_the_recipe(recipe: str) -> list[int]:
    """Every justfile line carrying `down -v` inside one recipe, so a case names no line number.

    A literal line number in a test is a second copy of a fact about a file that moves: the two
    lines
    this guard is about are found by asking the reader itself which recipe holds them.
    """
    return [
        number
        for path, number, _ in _lines_mentioning("down -v")
        if path == "justfile" and _recipe_holding(path, number) == recipe
    ]


def _e2e_down_line() -> int:
    """The line `e2e-down` runs the command on, which is the scratch-scope arm's own subject."""
    found = _lines_of_the_recipe("e2e-down")
    assert len(found) == 1, f"e2e-down carries {found} `down -v` line(s), not one"
    return found[0]


def _dev_reset_line() -> int:
    """The line `dev-reset` runs the command on, which is the declared exception's own subject."""
    found = _lines_of_the_recipe(TheDestructiveTeardown.ALLOWED_RECIPE)
    assert len(found) == 1, f"dev-reset carries {found} `down -v` line(s), not one"
    return found[0]


def _recipes_carrying_the_command() -> frozenset[str]:
    """Every justfile recipe that RUNS the destructive teardown, derived rather than listed.

    The declared exemptions are not members: a line that forbids the command names it without
    running it, and one of them sits in a recipe body.
    """
    return frozenset(
        recipe
        for path, number, line in _lines_mentioning("down -v")
        if path == "justfile"
        and not _declared_exempt(path, line)
        and (recipe := _recipe_holding(path, number)) is not None
    )


def _projects_the_refusal_reads() -> frozenset[str]:
    """The projects the runtime refusal names, read from the justfile variable it expands."""
    variables = _justfile_variables()

    assert "protected_projects" in variables, (
        "the justfile no longer declares the projects the runtime refusal iterates, so nothing "
        "crosses that list against the stacks it is meant to describe"
    )
    return frozenset(variables["protected_projects"].strip('"').split())


def _recipes_named_in(documents: Iterable[str]) -> set[str]:
    """Every `just <recipe>` a runbook tells the operator to RUN.

    Only inside backticks or at the start of a line in a code block, which is how a command is
    written in these files. A reading over the prose matched "just been" and asserted a recipe by
    that name, which is the same defect as a guard reading a set it does not mean.
    """
    import re

    inline = re.compile(r"`just ([a-z][a-z0-9-]+)")
    fenced = re.compile(r"^just ([a-z][a-z0-9-]+)", re.MULTILINE)
    found: set[str] = set()
    for document in documents:
        found |= set(inline.findall(document)) | set(fenced.findall(document))
    return found


def _variables_used_in(document: str) -> set[str]:
    """Every `$NAME` or `${NAME}` a document's commands expand."""
    import re

    return set(re.findall(r"\$\{?([A-Za-z_?][A-Za-z0-9_]*)\}?", document))


def _variables_defined_in(document: str) -> set[str]:
    """Every variable a document sets before it uses one.

    Two mechanisms, because the tree uses both. A literal `NAME=` or `export NAME=` at the start of
    a line, and SOURCING THE HOST SECRET FILE, which is how a runbook gets `DATABASE_URL` and every
    other key `.env.example` documents: `set -a; . ./.env` defines them as surely as an assignment
    does, and a reading that only saw assignments would have made that runbook impossible to satisfy
    honestly.
    """
    import re

    found = set(re.findall(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=", document, re.MULTILINE))
    if re.search(r"\.\s+\.?/?\.env\b", document):
        found |= _keys_the_environment_file_documents()
    return found


def _keys_the_environment_file_documents() -> set[str]:
    """Every key `.env.example` declares, which is what sourcing the host secret file provides.

    THE SPELLINGS A DOTENV READER ACCEPTS, not the one this file happens to use. An `export ` prefix
    and leading whitespace both declare a key to compose and to `set -a; . ./.env`, so a reading
    anchored on an upper-case letter at column zero answers a narrower question than either consumer
    asks. `_first_definition` below already accepts the prefix, and the runtime refusal in the
    justfile accepts both.
    """
    import re

    text = read(Path(".env.example"))
    return set(re.findall(r"^[ \t]*(?:export[ \t]+)?([A-Z][A-Z0-9_]*)=", text, re.MULTILINE))


def _keys_the_example_file_points_at_a_workstation() -> frozenset[str]:
    """Every key `.env.example` ships holding an address of the machine it is read on.

    A value naming the developer's own host is right for a developer and wrong for every deployment,
    so these are the keys where what the file ships decides whether a copy of it is safe.

    THE PRIVATE RANGES ARE MATCHED AS DOTTED QUADS, not as prefixes. `10.` as a substring matches a
    pinned image tag, so a reading that cheap would refuse a value for its version number.
    """
    import re

    text = read(Path(".env.example"))
    declared = re.findall(r"^[ \t]*(?:export[ \t]+)?([A-Z][A-Z0-9_]*)=(.*)$", text, re.MULTILINE)
    return frozenset(key for key, value in declared if _names_a_workstation(value))


def _names_a_workstation(value: str) -> bool:
    """Whether a value addresses the machine it is read on rather than a deployment.

    The loopback names, the container-to-host name Docker Desktop publishes, and the three private
    ranges an operator's own network uses.
    """
    import re

    literals = ("localhost", "127.0.0.1", "[::1]", "host.docker.internal")
    private = (
        r"\b10(?:\.\d{1,3}){3}\b",
        r"\b172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}\b",
        r"\b192\.168(?:\.\d{1,3}){2}\b",
    )
    return any(one in value for one in literals) or any(
        re.search(one, value) is not None for one in private
    )


def _keys_the_deployed_stack_names() -> frozenset[str]:
    """Every variable the compose files a DEPLOYED HOST runs name, in either accepted spelling.

    A key named there is decided by the topology, whatever a host's own file holds, so it is a key
    an operator cannot get wrong by copying the example.

    THE FILE SET IS THE DEPLOYED ONE, taken from `tests.test_deploy_topology`, and that is the whole
    point of this reading rather than an optimisation. A reading over every `docker-compose*.yml` in
    the tree exempts a key that only the e2e overlay names, and no deployed host composes that file:
    the same key would then be free to carry a development address into `/opt/syncr/.env` with this
    guard green.
    """
    import re

    named: set[str] = set()
    for name in DEPLOYED_FILES:
        content = read(Path(name))
        named |= set(re.findall(r"^\s+([A-Z][A-Z0-9_]*):", content, re.MULTILINE))
        named |= set(re.findall(r"^\s+-\s+([A-Z][A-Z0-9_]*)=", content, re.MULTILINE))
    return frozenset(named)


def _keys_the_deploy_table_lists() -> frozenset[str]:
    """Every key named in the deploy runbook's host-secret-file table.

    Bounded by the heading that table sits under, so another table in the same runbook is not read
    as this one.
    """
    import re

    section = (
        read(DEPLOY_AND_ROLLBACK).partition("### 4. The host secret file")[2].partition("\n### ")[0]
    )
    return frozenset(re.findall(r"^\|\s*`([A-Z][A-Z0-9_*]*)`", section, re.MULTILINE))


def _first_use(document: str, variable: str) -> int:
    """Where a document first expands ``variable``, as a line number."""
    import re

    pattern = re.compile(rf"\$\{{?{re.escape(variable)}\}}?\b")
    for number, line in enumerate(document.splitlines(), start=1):
        if pattern.search(line):
            return number
    return len(document.splitlines()) + 1


def _first_definition(document: str, variable: str) -> int:
    """Where a document first defines ``variable``, as a line number.

    Sourcing the host secret file counts, and it defines every key `.env.example` documents, so the
    line that sources it is the definition line for those.
    """
    import re

    assignment = re.compile(rf"^(?:export\s+)?{re.escape(variable)}=")
    sourcing = re.compile(r"\.\s+\.?/?\.env\b")
    documented = _keys_the_environment_file_documents()
    for number, line in enumerate(document.splitlines(), start=1):
        if assignment.match(line):
            return number
        if variable in documented and sourcing.search(line):
            return number
    return len(document.splitlines()) + 1


class TestEveryRecipeThatSeedsRefusesADeployedHost:
    """A recipe that writes seed data refuses a deployed host, and the SET of them is derived.

    `drill-seed` composes `docker-compose.yml` alone, that file declares the project `syncr`, and on
    a deployed host `syncr` is the live stack. So the recipe whose own comment calls a compose route
    reaching the wrong database "the most expensive hazard in this repository" WAS that route, and
    nothing refused: `just drill-seed` on a host writes invented tenants, weeks and outcomes into
    real plan history, and `just drill-local` step 3 calls it.

    THE RULE IS STATED OVER A DERIVED SET RATHER THAN OVER A LIST, because the defect a list cannot
    catch is a forgotten member: a second seeding recipe added beside the two that exist.

    The nine `seed-*` fixtures are not in the set and must not be. They declare fixtures over the
    HTTP API of a stack that `e2e/docker-compose.e2e.yml` gives a project and a published port of
    its own, and the deployed stack publishes no host port at all, which `just ports-check` asserts.

    THIS CLASS SITS BELOW THE READERS IT USES rather than beside its siblings, because two of its
    parametrizations are derived and a decorator is evaluated when the class is created.
    """

    def test_the_seed_data_the_repository_holds(self) -> None:
        """The positive control: an empty artifact set makes every reading below vacuous."""
        assert _seed_artifacts() == {"deployments/drill/seed-local.sql"}, (
            "a second hand-written seed arrived, so whichever recipe loads it is a member of the "
            "rule below and this figure is where that is acknowledged"
        )

    def test_the_recipes_that_reach_it(self) -> None:
        """The derived set, stated whole so a member that stops being derived is visible.

        A parametrization derived from this set SHRINKS silently: removing `just drill-seed` from
        `drill-local`'s body would drop that recipe's case rather than redden it.
        """
        assert _recipes_reaching_seed_data() == {"drill-seed", "drill-local"}

    @pytest.mark.parametrize("recipe", sorted(_recipes_reaching_seed_data()))
    def test_it_refuses_before_any_other_dependency(self, recipe: str) -> None:
        """A DEPENDENCY, AND THE FIRST ONE. Two claims, and the second is the one that was learned.

        `just` runs dependencies left to right, and the refusal was once the first STATEMENT of
        `drill-local`'s body: a run on a host wrote a throwaway keypair into `deployments/secrets`
        and only then refused.
        """
        dependencies = _dependencies_of(recipe)

        assert DEPLOYED_HOST_REFUSAL in dependencies, (
            f"`just {recipe}` reaches seed data and nothing stops it writing that seed into a "
            "deployment's own database"
        )
        assert dependencies.index(DEPLOYED_HOST_REFUSAL) == 0, (
            f"`just` runs dependencies left to right, so {dependencies} lets {dependencies[0]} run "
            "on the host this recipe is about to refuse"
        )

    def test_the_project_the_seeder_writes_into_is_one_that_holds_something(self) -> None:
        """THE PREMISE THE WHOLE RULE RESTS ON, resolved from the recipe rather than argued.

        If this ever resolves to a project holding nothing anyone keeps, the refusal is unnecessary
        and the rule above wants re-deriving rather than keeping.
        """
        project = _project_named_by(
            _compose_files_in(_commands_of(_recipe_body("drill-seed")), _justfile_variables())
        )

        assert project in _protected_projects(), (
            f"`just drill-seed` writes into the project {project}, and the refusal it carries is "
            "justified by that project being a deployment's own"
        )

    def test_the_refusal_reads_both_facts_a_workstation_does_not_have(self) -> None:
        """The list the runtime cases are derived from, asserted whole for the same reason."""
        assert _facts_the_refusal_reads() == (
            "deployments/digests.env",
            "deployments/secrets/backup-recipient.asc",
        )

    def test_the_shared_refusal_states_the_hazard_of_each_caller(self) -> None:
        """One message, two callers, two different things that would happen on the host.

        A reason stated for the drill alone would leave an operator reading about a dump they never
        asked for while the thing they ran writes rows.
        """
        refusal = _recipe_body(DEPLOYED_HOST_REFUSAL)

        assert "dump the live database under a throwaway" in refusal
        assert "invented rows into that same live database" in refusal

    @pytest.mark.parametrize("fact", _facts_the_refusal_reads())
    def test_it_refuses_at_runtime_and_reaches_no_container(
        self, fact: str, tmp_path: Path
    ) -> None:
        """THE DELETION PROOF, run rather than read: `just drill-seed` on a simulated host.

        The recording stub answers whether the recipe REACHED a container, which an exit status
        cannot: a guard that starts something and refuses afterwards exits non-zero too, and firing
        late is the regression this recipe pair has already suffered once.
        """
        done = _drill_seed_in_a_tree_of_its_own(tmp_path, evidence=(fact,))
        reached = tmp_path / DOCKER_LOG

        assert done.returncode != 0, done.stdout
        assert f"this host is a deployment ({fact} exists)" in done.stderr
        assert not reached.exists(), (
            f"the recipe reached docker before refusing: {reached.read_text(encoding='utf-8')}"
        )

    def test_it_does_not_refuse_a_workstation(self, tmp_path: Path) -> None:
        """THE OTHER DIRECTION, and the case that sees an always-firing guard for its own reason.

        The two directions redden overlapping sets rather than disjoint ones: forcing the condition
        true also reddens a refusal case, because the loop then refuses on the first fact in the
        list and the message names the wrong one. This is the only case that fails because the guard
        refused a tree holding neither fact, which is what a workstation is.
        """
        done = _drill_seed_in_a_tree_of_its_own(tmp_path, evidence=())

        assert done.returncode == 0, done.stderr
        assert "this host is a deployment" not in done.stderr
        assert "compose -f docker-compose.yml exec" in (tmp_path / DOCKER_LOG).read_text(
            encoding="utf-8"
        ), "the recipe refused a tree holding neither fact, so it refuses a workstation too"

    def test_the_reading_follows_a_recipe_that_only_calls_the_seeder(self) -> None:
        """The derivation's own controls, over a justfile the case wrote.

        Four recipes and three arms: naming the seed, invoking a recipe that does, depending on one,
        and MENTIONING one in a comment, which reaches nothing and must not be a member.

        The fifth prints a recipe name in a message, which is what the deployed-host refusal itself
        does three times over: a reading that took the whole line made the refusal a caller of the
        recipe that carries it, so the derived set held it and its own case then failed.
        """
        justfile = (
            "loads:\n"
            "    psql -f deployments/drill/seed-local.sql\n"
            "calls-it:\n"
            "    just loads\n"
            "depends-on-it: loads\n"
            "    echo hello\n"
            "mentions-it:\n"
            "    # just loads, one day\n"
            "    echo hello\n"
            "prints-it:\n"
            '    echo "run `just loads` instead" >&2\n'
        )

        assert _recipes_reaching_seed_data(text=justfile) == {
            "loads",
            "calls-it",
            "depends-on-it",
        }

    def test_the_recipe_reading_sees_a_private_recipe_and_not_a_variable(self) -> None:
        """Both corrections a rule over EVERY recipe needed, and neither was visible before."""
        names = _recipe_names()

        assert DEPLOYED_HOST_REFUSAL in names, "a `[private]` recipe is one `just` still runs"
        assert "members" not in names, "a `name := value` declaration is not a recipe"

    def test_the_dependency_reading_answers_for_a_recipe_with_a_parameter(self) -> None:
        """`e2e-only pattern:` raised rather than answering, and the set covers every recipe.

        And a `name := value` line is not an opener. Widening for the parameter admitted one, so the
        reading answered `members` with the pieces of a variable's value.
        """
        assert _dependencies_of("e2e-only") == []

        with pytest.raises(AssertionError, match="no recipe named members"):
            _dependencies_of("members")


def _assert_it_refused(done: subprocess.CompletedProcess[str], root: Path, *, saying: str) -> None:
    """The refusing direction: a non-zero exit, the reason, and NO container reached.

    The third claim is the one an exit status cannot make. A guard that starts something and refuses
    afterwards exits non-zero too, and the whole point of a teardown refusal is that it fires before
    compose acts.
    """
    assert done.returncode != 0, done.stdout
    assert saying in done.stderr, done.stderr

    reached = root / DOCKER_LOG
    assert not reached.exists(), (
        f"the recipe reached docker before refusing: {reached.read_text(encoding='utf-8')}"
    )


def _assert_it_ran(done: subprocess.CompletedProcess[str], root: Path) -> None:
    """The admitting direction, which a refusal that fires on any name at all cannot satisfy."""
    assert done.returncode == 0, done.stderr

    reached = root / DOCKER_LOG
    assert reached.is_file() and "down -v" in reached.read_text(encoding="utf-8"), (
        "the teardown never reached docker, so the refusal refused a project holding nothing"
    )


class TestEveryTeardownRefusesAnInheritedProject:
    """A recipe that drops a project's volumes refuses an inherited project name, and the SET of
    those recipes is derived.

    `_scoped_to_a_scratch_project` judges ONE LINE, so it reads a project override written on that
    line and nothing else. Compose takes `COMPOSE_PROJECT_NAME` from the shell environment first and
    from the project directory's `.env` second, and honours it ABOVE the last `name:` in the `-f`
    list. So a name that appears neither on the line nor in any tracked file decides which project a
    teardown destroys, and `pgdata`, the WAL volume, the staging volume and the bucket go together.

    NEITHER CARRIER CAN BE CLOSED BY A READING OF THE INDEX. `.env` is gitignored, so
    `git ls-files --cached` cannot see the one file that reprojects every teardown here, and an
    exported variable sits in no file at all. What can refuse them is the recipe itself, at the
    moment it would run, which is what the cases below drive.

    THE RUNTIME CASES RUN `e2e-down` AGAINST A STUB `docker`, IN A TREE OF ITS OWN. The admitting
    direction has to let the recipe finish, and what it finishes with is the command that destroys
    a project: the tree holds no compose file, so a `docker` escaping the stub would resolve
    nothing, and that recipe's own scope is the scratch stack rather than one anyone keeps. Which
    recipes carry the refusal is a separate claim, and it is the derived one below.

    THIS CLASS SITS BELOW THE READERS IT USES rather than beside its siblings, because two of its
    parametrizations are derived and a decorator is evaluated when the class is created.
    """

    def test_the_recipes_that_carry_the_command(self) -> None:
        """The derived set, stated whole so a member that stops being derived is visible.

        A parametrization derived from this set SHRINKS silently: a recipe that stopped carrying the
        command would drop its own case rather than redden it.
        """
        assert _recipes_carrying_the_command() == {"dev-reset", "e2e-down"}

    @pytest.mark.parametrize("recipe", sorted(_recipes_carrying_the_command()))
    def test_it_refuses_before_any_other_dependency(self, recipe: str) -> None:
        """A DEPENDENCY, AND THE FIRST ONE, which is the order `just` runs them in."""
        dependencies = _dependencies_of(recipe)

        assert RETARGETED_TEARDOWN_REFUSAL in dependencies, (
            f"`just {recipe}` drops the volumes of whatever project COMPOSE_PROJECT_NAME names, "
            "and nothing here stops that name being a deployment's"
        )
        assert dependencies.index(RETARGETED_TEARDOWN_REFUSAL) == 0, (
            f"`just` runs dependencies left to right, so {dependencies} lets {dependencies[0]} run "
            "before the teardown it precedes is refused"
        )

    def test_the_projects_the_refusal_iterates_are_the_ones_that_hold_something(self) -> None:
        """The justfile's own list crossed against what its compose scopes resolve to.

        The refusal cannot read a compose file's `name:` in four lines of shell, so it names the two
        projects. This crossing is what keeps that list from becoming a second definition of which
        projects hold something, drifting from the one the scopes decide.
        """
        assert _projects_the_refusal_reads() == _protected_projects()

    def test_the_example_environment_file_does_not_teach_the_pattern(self) -> None:
        """A key here is copied into `.env` by everyone who follows that file's first line."""
        keys = _keys_the_environment_file_documents()

        assert "POSTGRES_DB" in keys, "no key was read at all, so the claim below is vacuous"
        assert "COMPOSE_PROJECT_NAME" not in keys, (
            "`.env.example` is copied to `.env`, and compose reads that file's project name above "
            "every `-f` list in this repository"
        )

    @pytest.mark.parametrize("held", sorted(_protected_projects()))
    def test_it_refuses_a_project_the_environment_names(self, held: str, tmp_path: Path) -> None:
        """One case per project that holds something, so neither passes on the other's arm."""
        done = _the_scratch_teardown_in_a_tree_of_its_own(tmp_path, inherited=held)

        _assert_it_refused(done, tmp_path, saying=f"COMPOSE_PROJECT_NAME names `{held}`")

    def test_it_admits_a_project_the_environment_names_that_holds_nothing(
        self, tmp_path: Path
    ) -> None:
        """THE OTHER DIRECTION. A refusal reading no name at all passes every case above."""
        done = _the_scratch_teardown_in_a_tree_of_its_own(tmp_path, inherited="syncr-e2e")

        _assert_it_ran(done, tmp_path)

    def test_it_admits_a_tree_that_inherits_nothing(self, tmp_path: Path) -> None:
        """What a developer with no `.env` and nothing exported has, which is the ordinary run."""
        done = _the_scratch_teardown_in_a_tree_of_its_own(tmp_path)

        _assert_it_ran(done, tmp_path)

    def test_it_refuses_a_project_only_a_gitignored_file_names(self, tmp_path: Path) -> None:
        """THE CARRIER NO READING OF THE INDEX REACHES, which is why the refusal reads the file."""
        done = _the_scratch_teardown_in_a_tree_of_its_own(
            tmp_path, dotenv="COMPOSE_PROJECT_NAME=syncr\n"
        )

        _assert_it_refused(done, tmp_path, saying="COMPOSE_PROJECT_NAME names `syncr`")

    def test_it_admits_a_gitignored_file_naming_a_project_that_holds_nothing(
        self, tmp_path: Path
    ) -> None:
        """The file arm's own other direction: reading the file is not refusing every file."""
        done = _the_scratch_teardown_in_a_tree_of_its_own(
            tmp_path, dotenv="COMPOSE_PROJECT_NAME=syncr-e2e\n"
        )

        _assert_it_ran(done, tmp_path)

    def test_it_reads_the_quotes_compose_strips(self, tmp_path: Path) -> None:
        """Compose acts on `syncr` for a quoted value, so a reading that kept the quotes would
        compare a name no project has and admit the teardown."""
        done = _the_scratch_teardown_in_a_tree_of_its_own(
            tmp_path, dotenv='COMPOSE_PROJECT_NAME="syncr"\n'
        )

        _assert_it_refused(done, tmp_path, saying="COMPOSE_PROJECT_NAME names `syncr`")

    @pytest.mark.parametrize(
        ("dotenv", "refused"),
        [
            ("export COMPOSE_PROJECT_NAME=syncr\n", True),
            ("export COMPOSE_PROJECT_NAME=syncr-e2e\n", False),
        ],
    )
    def test_it_reads_the_export_prefix_compose_accepts(
        self, dotenv: str, refused: bool, tmp_path: Path
    ) -> None:
        """THE SPELLING A READING ANCHORED ON THE KEY ALONE ADMITS.

        Compose's dotenv reader accepts `export ` on a line, measured against `docker compose`
        `config` on a scratch project: `export COMPOSE_PROJECT_NAME=x` decides the project. So a
        refusal that matched only an assignment at the start of the line read nothing here and let
        the teardown run against `syncr`, which is the carrier this refusal exists for, in the
        spelling a developer who writes shell files reaches for first.

        Both directions, because a reading that refused any line carrying `export` would pass the
        first row while judging no name at all.
        """
        done = _the_scratch_teardown_in_a_tree_of_its_own(tmp_path, dotenv=dotenv)

        if refused:
            _assert_it_refused(done, tmp_path, saying="COMPOSE_PROJECT_NAME names `syncr`")
        else:
            _assert_it_ran(done, tmp_path)

    @pytest.mark.parametrize(
        ("dotenv", "refused"),
        [
            ("COMPOSE_PROJECT_NAME=syncr-e2e\nCOMPOSE_PROJECT_NAME=syncr\n", True),
            ("COMPOSE_PROJECT_NAME=syncr\nCOMPOSE_PROJECT_NAME=syncr-e2e\n", False),
        ],
    )
    def test_the_last_assignment_in_the_file_is_the_one_it_judges(
        self, dotenv: str, refused: bool, tmp_path: Path
    ) -> None:
        """THE SAME TWO NAMES IN BOTH ORDERS, which must come out opposite.

        One order alone passes on a reading that takes the first assignment, and compose takes the
        last.
        """
        done = _the_scratch_teardown_in_a_tree_of_its_own(tmp_path, dotenv=dotenv)

        if refused:
            _assert_it_refused(done, tmp_path, saying="COMPOSE_PROJECT_NAME names `syncr`")
        else:
            _assert_it_ran(done, tmp_path)

    @pytest.mark.parametrize(
        ("inherited", "dotenv", "refused"),
        [
            ("syncr-e2e", "COMPOSE_PROJECT_NAME=syncr\n", False),
            ("syncr", "COMPOSE_PROJECT_NAME=syncr-e2e\n", True),
        ],
    )
    def test_the_environment_beats_the_file(
        self, inherited: str, dotenv: str, refused: bool, tmp_path: Path
    ) -> None:
        """COMPOSE'S OWN PRECEDENCE, driven with the same two names in both positions.

        A reading that consulted the file first would refuse the row compose runs as `syncr-e2e` and
        admit the row it runs as `syncr`, which is wrong in both directions at once.
        """
        done = _the_scratch_teardown_in_a_tree_of_its_own(
            tmp_path, inherited=inherited, dotenv=dotenv
        )

        if refused:
            _assert_it_refused(done, tmp_path, saying="COMPOSE_PROJECT_NAME names `syncr`")
        else:
            _assert_it_ran(done, tmp_path)

    @pytest.mark.parametrize(
        ("dotenv", "refused"),
        [
            ("\ufeffCOMPOSE_PROJECT_NAME=syncr\n", True),
            ("\ufeffCOMPOSE_PROJECT_NAME=syncr-e2e\n", False),
        ],
    )
    def test_it_reads_past_a_byte_order_mark(
        self, dotenv: str, refused: bool, tmp_path: Path
    ) -> None:
        """THE OTHER SPELLING A LINE-ANCHORED PATTERN MISSES, and the worse one.

        Compose's dotenv reader skips a leading byte order mark, so the first key still declares the
        project. A pattern anchored at the start of the line does not: the mark sits before the key,
        nothing matches, and an empty reading admits. An editor writing UTF-8 with a mark, or a
        PowerShell copy of the example file, produces exactly this file.

        Both directions, because dropping the mark must not become refusing every file that carries
        one.
        """
        done = _the_scratch_teardown_in_a_tree_of_its_own(tmp_path, dotenv=dotenv)

        if refused:
            _assert_it_refused(done, tmp_path, saying="COMPOSE_PROJECT_NAME names `syncr`")
        else:
            _assert_it_ran(done, tmp_path)

    @pytest.mark.parametrize(
        ("dotenv", "refused"),
        [
            ("COMPOSE_PROJECT_NAME=syncr\r\n", True),
            ("COMPOSE_PROJECT_NAME=syncr-e2e\r\n", False),
        ],
    )
    def test_it_reads_a_file_written_with_crlf_endings(
        self, dotenv: str, refused: bool, tmp_path: Path
    ) -> None:
        """A `\\r` belongs to the line ending rather than to the value.

        Compose acts on the name without the carriage return. Keeping it made the value
        unresolvable, which refused for the wrong reason: safe, but it named a project nobody wrote.

        Both directions, because dropping the carriage return must not become refusing every file
        that carries one: a reading that mapped any such file to a held project would pass a single
        row.
        """
        done = _the_scratch_teardown_in_a_tree_of_its_own(tmp_path, dotenv=dotenv)

        if refused:
            _assert_it_refused(done, tmp_path, saying="COMPOSE_PROJECT_NAME names `syncr`")
        else:
            _assert_it_ran(done, tmp_path)

    @pytest.mark.parametrize(
        ("dotenv", "saying"),
        [
            ("COMPOSE_PROJECT_NAME=syncr\nCOMPOSE_PROJECT_\rNAME=syncr-e2e\n", "names `syncr`"),
            ("COMPOSE_PROJECT_NAME=syncr-e2e\nCOMPOSE_PROJECT_\rNAME=syncr\n", None),
            ("COMPOSE_PROJECT_NAME=syncr\n\ufeffCOMPOSE_PROJECT_NAME=syncr-e2e\n", "on line 2"),
        ],
    )
    def test_the_two_tolerances_are_scoped_the_way_compose_scopes_them(
        self, dotenv: str, saying: str | None, tmp_path: Path
    ) -> None:
        """A mark is forgiven at the start of the FILE and a carriage return at the end of a LINE.

        Compose reads the FIRST line of the first two files, because the second line's key carries a
        byte that makes it a different key. A reading that deleted either byte from anywhere would
        see a second assignment compose does not honour, and the last matching line would win.

        The carriage-return rows carry the same two names in both orders and must come out opposite,
        so a reading that refused every file containing an out-of-scope byte fails the second. The
        mark row refuses through the position arm rather than by name, because a mark before a later
        key is a line this reading cannot read and compose cannot read the file either.
        """
        done = _the_scratch_teardown_in_a_tree_of_its_own(tmp_path, dotenv=dotenv)

        if saying is None:
            _assert_it_ran(done, tmp_path)
        else:
            _assert_it_refused(done, tmp_path, saying=saying)

    @pytest.mark.parametrize(
        ("project", "refused"),
        [(b"syncr", True), (b"syncr-e2e", False)],
    )
    def test_it_reads_a_file_that_is_not_valid_utf_8(
        self, project: bytes, refused: bool, tmp_path: Path
    ) -> None:
        """COMPOSE'S READER IS BYTE-ORIENTED AND A TEXT TOOL IS NOT.

        One CP1252 byte in `POSTGRES_PASSWORD` is the whole trigger: that key ships in
        `.env.example` under a first line telling the reader to copy the file, so a Latin-1 editor
        and a non-ASCII password produce this file. Compose resolves it without complaint. In a
        UTF-8 locale BSD `sed` aborts at that line with `illegal byte sequence` and reads nothing
        after it, so the project name below was never seen and the teardown ran.

        Both directions, because reading bytes must not become refusing every file that holds one.
        """
        dotenv_bytes = (
            b"POSTGRES_PASSWORD=pw" + CP1252_O_UMLAUT + b"\nCOMPOSE_PROJECT_NAME=" + project + b"\n"
        )

        done = _the_scratch_teardown_in_a_tree_of_its_own(tmp_path, dotenv_bytes=dotenv_bytes)

        if refused:
            _assert_it_refused(done, tmp_path, saying="COMPOSE_PROJECT_NAME names `syncr`")
        else:
            _assert_it_ran(done, tmp_path)

    @pytest.mark.parametrize(
        "before_the_key",
        [
            "\u00a0",
            "\u3000",
            "\u202f",
            "\u2028",
            "\u1680",
            "\u0085",
        ],
    )
    def test_a_space_this_reading_cannot_see_is_refused_rather_than_admitted(
        self, before_the_key: str, tmp_path: Path
    ) -> None:
        """THE PART THAT MAKES A READING NARROWER THAN COMPOSE SAFE RATHER THAN FATAL.

        Compose trims Unicode whitespace before a key, and a byte-oriented pattern cannot see it: no
        locale gives a text tool both byte semantics and Unicode classes, so this pattern cannot in
        principle match its subject. Each space below makes compose resolve the name on that line
        while the pattern reads nothing.

        The reading therefore refuses when the file sets this key on a line it could not read.
        Each of these was an admitted teardown of the deployed project before that rule existed.
        """
        done = _the_scratch_teardown_in_a_tree_of_its_own(
            tmp_path, dotenv=f"{before_the_key}COMPOSE_PROJECT_NAME=syncr\n"
        )

        _assert_it_refused(done, tmp_path, saying="sets COMPOSE_PROJECT_NAME on line 1")

    def test_the_refusal_names_a_way_out_and_every_way_out_is_safe(self, tmp_path: Path) -> None:
        """A refusal a developer cannot act on is a refusal someone disables.

        And every action it advises has to be safe under this gate, which is not automatic: the
        earlier message said "rewrite it as plain ASCII", and adding an ASCII line ABOVE the
        unreadable one satisfied that wording while leaving compose acting on the line below. The
        advice now says REPLACE, and the position case below is why the half-followed version is
        refused rather than admitted.
        """
        done = _the_scratch_teardown_in_a_tree_of_its_own(
            tmp_path, dotenv=f"{NO_BREAK_SPACE}COMPOSE_PROJECT_NAME=syncr\n"
        )

        assert "delete line 1" in done.stderr, done.stderr
        assert "REPLACE line 1" in done.stderr, done.stderr
        assert "export COMPOSE_PROJECT_NAME=<project>" in done.stderr, done.stderr

    def test_the_cost_of_that_rule_is_one_false_refusal(self, tmp_path: Path) -> None:
        """THE PRICE, ASSERTED RATHER THAN LEFT FOR SOMEONE TO DISCOVER.

        Compose resolves `syncr-e2e` here, which holds nothing, so the teardown would have been
        safe. The reading cannot see the name at all, and it refuses on the same rule that catches
        the deployed project. That is the trade: a spurious refusal a developer clears in one
        command, in exchange for a miss that cannot destroy volumes.
        """
        done = _the_scratch_teardown_in_a_tree_of_its_own(
            tmp_path, dotenv=f"{NO_BREAK_SPACE}COMPOSE_PROJECT_NAME=syncr-e2e\n"
        )

        _assert_it_refused(done, tmp_path, saying="sets COMPOSE_PROJECT_NAME on line 1")

    def test_a_file_that_only_mentions_the_key_in_a_comment_is_admitted(
        self, tmp_path: Path
    ) -> None:
        """A line that only names the key after a `#` sets nothing, and this turns on that."""
        done = _the_scratch_teardown_in_a_tree_of_its_own(
            tmp_path,
            dotenv="# COMPOSE_PROJECT_NAME is forbidden\n  # nor indented\nLOG_LEVEL=info\n",
        )

        _assert_it_ran(done, tmp_path)

    def test_a_byte_copy_of_the_example_file_is_admitted(self, tmp_path: Path) -> None:
        """THE FILE THE PROHIBITION TELLS EVERYONE TO COPY, read from the repository rather than
        reconstructed.

        `.env.example` names this key in its own prohibition, in comments. A developer who follows
        its first line gets those comments in `.env`, and that must not refuse every teardown.
        """
        done = _the_scratch_teardown_in_a_tree_of_its_own(
            tmp_path, dotenv_bytes=(repo_root() / ".env.example").read_bytes()
        )

        _assert_it_ran(done, tmp_path)

    @pytest.mark.parametrize(
        ("dotenv", "saying"),
        [
            (
                f"COMPOSE_PROJECT_NAME=syncr-e2e\n{NO_BREAK_SPACE}COMPOSE_PROJECT_NAME=syncr\n",
                "line 2",
            ),
            (f"{NO_BREAK_SPACE}COMPOSE_PROJECT_NAME=syncr\nCOMPOSE_PROJECT_NAME=syncr-e2e\n", None),
        ],
    )
    def test_a_readable_line_above_an_unreadable_one_is_refused(
        self, dotenv: str, saying: str | None, tmp_path: Path
    ) -> None:
        """THE GATE IS A POSITION, BECAUSE COMPOSE TAKES THE LAST ASSIGNMENT IT SEES.

        `tail -n 1` takes the last assignment THIS pattern sees, so asking only "did I read nothing"
        caught the case where both sets were empty and missed this one: compose acts on line 2 while
        the pattern reads line 1 and finds a name that holds nothing.

        Both orders, and they must come out opposite. In the second file compose acts on the
        readable line, which is the last one, so admitting is correct and a gate that refused any
        file with an unreadable mention anywhere would fail it.
        """
        done = _the_scratch_teardown_in_a_tree_of_its_own(tmp_path, dotenv=dotenv)

        if saying is None:
            _assert_it_ran(done, tmp_path)
        else:
            _assert_it_refused(done, tmp_path, saying=saying)

    def test_a_hash_earlier_in_the_line_does_not_make_it_a_comment(self, tmp_path: Path) -> None:
        """A dotenv comment is a line whose FIRST non-blank character is `#`.

        Compose resolves `syncr` here. A condition that asked whether any `#` preceded the key read
        this assignment as a comment and admitted the teardown.
        """
        done = _the_scratch_teardown_in_a_tree_of_its_own(
            tmp_path, dotenv='FOO="a#b" COMPOSE_PROJECT_NAME=syncr\n'
        )

        _assert_it_refused(done, tmp_path, saying="sets COMPOSE_PROJECT_NAME on line 1")

    @pytest.mark.parametrize(
        "dotenv",
        [
            pytest.param(
                'MY_COMPOSE_PROJECT_NAME="x" COMPOSE_PROJECT_NAME=syncr\n', id="prefixed-then-syncr"
            ),
            pytest.param(
                'MY_COMPOSE_PROJECT_NAME="x" COMPOSE_PROJECT_NAME=syncr-dev\n',
                id="prefixed-then-syncr-dev",
            ),
            pytest.param(
                'X_COMPOSE_PROJECT_NAME="x" COMPOSE_PROJECT_NAME=syncr\n', id="one-char-prefix"
            ),
            pytest.param(
                '1COMPOSE_PROJECT_NAME="x" COMPOSE_PROJECT_NAME=syncr\n', id="digit-prefix"
            ),
        ],
    )
    def test_a_longer_key_beside_a_real_assignment_does_not_hide_it(
        self, dotenv: str, tmp_path: Path
    ) -> None:
        """WHY THIS READS THE LINE RATHER THAN THE IDENTIFIER.

        Compose resolves the protected project on every file here, because the second assignment on
        the line is a real one. An exclusion for a longer key was tried and reverted: it dropped the
        whole LINE rather than the occurrence, so the mention disappeared, the value pattern had
        never matched it either, and the teardown ran silently.

        The cost of reading the line is that a longer key on its own is refused. That case is one
        `unset` away and it is asserted below; this one was volumes.
        """
        done = _the_scratch_teardown_in_a_tree_of_its_own(tmp_path, dotenv=dotenv)

        _assert_it_refused(done, tmp_path, saying="sets COMPOSE_PROJECT_NAME on line 1")

    @pytest.mark.parametrize(
        "dotenv",
        [
            pytest.param("MY_COMPOSE_PROJECT_NAME=x\n", id="a-longer-key-alone"),
            pytest.param("COMPOSE_PROJECT_NAME_OVERRIDE=x\n", id="a-suffixed-key-alone"),
        ],
    )
    def test_a_longer_key_alone_is_refused_and_that_is_the_accepted_cost(
        self, dotenv: str, tmp_path: Path
    ) -> None:
        """THE FALSE REFUSALS THIS READING KEEPS, asserted so they are known rather than surprising.

        Compose takes no project from either file: it resolves the compose file's own `name:`. This
        refuses both, because it reads whole lines, and the case above is why. The message names the
        way out for exactly this shape.
        """
        done = _the_scratch_teardown_in_a_tree_of_its_own(tmp_path, dotenv=dotenv)

        _assert_it_refused(done, tmp_path, saying="only carries a LONGER key")

    def test_an_empty_value_is_admitted(self, tmp_path: Path) -> None:
        """THE FALSE REFUSAL THE POSITION GATE RETIRED, measured against compose.

        Compose ignores an empty `COMPOSE_PROJECT_NAME` and falls back to the compose file's own
        `name:`, so refusing it was a cost with no safety behind it. The assignment IS the last line
        the pattern matched, so nothing sits below it and the gate stays quiet.
        """
        done = _the_scratch_teardown_in_a_tree_of_its_own(
            tmp_path, dotenv="COMPOSE_PROJECT_NAME=\n"
        )

        _assert_it_ran(done, tmp_path)

    def test_a_name_it_cannot_resolve_is_refused(self, tmp_path: Path) -> None:
        """Compose interpolates the file's values, and this refusal does not.

        The value below is `syncr` by the time compose reads it, so admitting what cannot be
        resolved would admit the deployed project by way of a second variable.
        """
        done = _the_scratch_teardown_in_a_tree_of_its_own(
            tmp_path,
            dotenv="INNER=syncr\nCOMPOSE_PROJECT_NAME=${INNER}\n",
        )

        _assert_it_refused(done, tmp_path, saying="cannot resolve to a project")


# --- Why writing to a real calendar is off, stated in ten places ---------------------------------

# Every file that states WHY `GOOGLE_PROJECTION_WRITES` ships false. The reason is one fact and the
# tree spells it ten times, in five comment languages, so flipping the default falsifies all ten at
# once and each has to be corrected in the same change.
#
# Enumerated rather than discovered, because discovery has now failed four times on this exact set.
# A review found 4, a sweep of two directories found 6, and both greps that surfaced the rest miss
# `.env.example`: its sentence wraps between "the real" and "Google API", and it says "has ever been
# run" rather than "never". A declared tuple cannot wrap and cannot rephrase.
WHY_WRITING_IS_OFF: Final = (
    Path("packages/syncr-api/src/syncr_api/core/settings.py"),
    Path("packages/syncr-api/src/syncr_api/calendars/injection.py"),
    Path("packages/syncr-api/tests/test_google_reconcile.py"),
    Path("packages/syncr-api/tests/test_projection_runner.py"),
    Path("docs/runbooks/google-token-expired.md"),
    Path("docs/smoke-scenarios.md"),
    Path("docker-compose.yml"),
    Path(".env.example"),
    Path("e2e/tests/paths.spec.ts"),
    Path("e2e/docker-compose.e2e.yml"),
)

# The clause every one of them carries, naming the condition that is still open. Short deliberately:
# a longer phrase is likelier to wrap, and wrapping is what hid one site from two greps.
THE_OPEN_CONDITION: Final = "armed deployment"


def _prose_of(relative: Path) -> str:
    """One file's text with comment markers stripped and every run of whitespace flattened.

    The reason is prose in Python, YAML, shell, TypeScript and Markdown comments, and it wraps
    across lines in most of them. Matching raw text would miss a site whose phrase broke over a
    newline, which is exactly how the widest-readership site of the ten survived every earlier
    reading.
    """
    import re

    unmarked = re.sub(r"(?m)^\s*(?:#|//|\*|--)+[ \t]?", " ", read(relative))
    return re.sub(r"\s+", " ", unmarked)


class TestWhyWritingToARealCalendarIsOff:
    """The default, and the ten statements of why, crossed against each other.

    This exists because the reason drifted twice inside one ticket. The live Google suite met the
    provider, which falsified the sentence "it has never met the real API" wherever it was written,
    and it was written in ten files. Two rounds of human sweeping found 4 and then 6 of them.

    The guard is positive and bounded on purpose. A check that no sentence in the tree CLAIMS the
    write path is unproven would be a check over unbounded wordings that goes green the moment a
    writer picks a phrasing it does not know. This asserts instead that a declared set of files each
    still names the condition that is genuinely open, and that the default those statements justify
    is still what they say it is.
    """

    def test_the_shipped_default_is_still_off(self) -> None:
        """The field default, not a resolved setting: a stray environment variable is not the ship.

        When this reddens, every file in `WHY_WRITING_IS_OFF` is stating a reason that has lapsed
        and has to be corrected in the same change. That is the whole purpose of this check.
        """
        declared = EnvSettings.model_fields["google_projection_writes"].default

        assert declared is False, (
            "GOOGLE_PROJECTION_WRITES now ships armed, so the stated reason has lapsed at every "
            "one of these and each needs correcting in this change: "
            f"{[str(one) for one in WHY_WRITING_IS_OFF]}"
        )

    @pytest.mark.parametrize("relative", WHY_WRITING_IS_OFF, ids=lambda one: one.name)
    def test_the_site_names_the_condition_that_is_still_open(self, relative: Path) -> None:
        """Each one says what has NOT happened yet, rather than what has.

        The distinction is the whole defect: "has never met the real API" became false when the live
        suite ran, while "has never run from an armed deployment" is still true and is what the
        default is for.
        """
        assert THE_OPEN_CONDITION in _prose_of(relative), (
            f"{relative} states why writing is off without naming the condition that is still open "
            f"({THE_OPEN_CONDITION!r}), so its reason cannot be told from one that has lapsed"
        )

    @pytest.mark.parametrize("relative", WHY_WRITING_IS_OFF, ids=lambda one: one.name)
    def test_the_site_does_not_claim_the_provider_was_never_met(self, relative: Path) -> None:
        """The one negative worth keeping, because these three spellings are what actually drifted.

        Bounded to the phrasings the tree really used rather than to every way the claim could be
        written: as a general check it would be decoration, and it is recorded here as covering
        three known drifts and nothing more.
        """
        prose = _prose_of(relative)

        for lapsed in (
            "never met the real",
            "never been run against the real",
            "never run against",
        ):
            assert lapsed not in prose, (
                f"{relative} still says {lapsed!r}, which the live suite made false"
            )
