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

from tests.test_alert_rules import named as alert_named
from tests.test_alert_rules import repo_root

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

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
        """The schedule and a manual run cannot drift into two procedures if there is one."""
        content = directives(SYSTEMD / unit)

        assert " just " in _exec_start(content), "the unit runs a recipe, not a command"
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

        THE ORDER IS THE POINT. The refusal was the first statement of `drill-local`'s body, and
        `drill-keys` is a dependency, so `just` ran it first: a run on a host wrote a throwaway
        keypair into `deployments/secrets` and only then refused. Measured, on this checkout.
        """
        guard = _recipe_body("_refuse-a-local-drill-on-a-deployed-host")

        assert "deployments/digests.env" in guard
        assert "exit 1" in guard
        assert "just restore-drill" in guard, "and it names the recipe to run instead"

        dependencies = _dependencies_of("drill-local")
        assert "_refuse-a-local-drill-on-a-deployed-host" in dependencies
        assert dependencies.index("_refuse-a-local-drill-on-a-deployed-host") < dependencies.index(
            "drill-keys"
        ), "just runs dependencies left to right, so the refusal has to come before the keygen"

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


def _recipe_body(name: str) -> str:
    """One `just` recipe's body, from its opening line to the next unindented one."""
    lines = read(Path("justfile")).splitlines()
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


def _dependencies_of(name: str) -> list[str]:
    """The recipes `just` runs before ``name``, in the order it runs them."""
    for line in read(Path("justfile")).splitlines():
        if line.startswith(f"{name}:"):
            return line.partition(":")[2].split()
    raise AssertionError(f"the justfile declares no recipe named {name}")


class TheDestructiveTeardown:
    """Nothing in this tree may TELL anyone to run `docker compose down -v`.

    `down -v` is scoped to the PROJECT, and the dev stack, the deployed stack and the drill share
    one project name. A local run of this ticket's own drill proved what that means: its teardown
    deleted `pgdata`, the WAL volume, the staging volume and the bucket. The code path was fixed to
    remove containers BY SERVICE NAME, and the instruction survived in a refusal message the
    operator reads while trying to recover years of data, falsely attributed to the recipe that
    avoids it.

    So the rule is stated over the whole tree rather than over the recipe: every occurrence must be
    either inside the one recipe whose name says what it destroys, or on a line that forbids it.

    TWICE NOW THE READING WAS NARROWER THAN THE RULE. The first version read five suffixes and one
    filename, so nine planted lines produced four catches: a systemd unit running
    `ExecStart=/usr/bin/docker compose down -v` was invisible, which is the one file type where a
    SCHEDULED teardown would live and no human reads it first. And the exemption was a substring
    test on `"not"`, so `Nothing`, `Note`, `cannot`, `Another` and `Notice` each exempted a line
    that instructed the command. Both are closed below and both have negative controls.
    """

    # The one recipe allowed to run it. Its name says what it does, and it names the dev stack's own
    # compose files, which is a different project from the deployed one.
    ALLOWED_RECIPE = "dev-reset"

    # A line that mentions it while FORBIDDING it. Whole phrases rather than a word that hides
    # inside five ordinary ones: a line reading "Note: run `docker compose down -v`" contains `not`
    # and instructs the command.
    FORBIDDING = ("never", "do not", "don't", "not safe", "must not")

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
    def test_nothing_instructs_it_outside_the_recipe_that_owns_it(self) -> None:
        offenders = [
            f"{path}:{number}: {line.strip()}"
            for path, number, line in _lines_mentioning("down -v")
            if path != TheDestructiveTeardown.DECLARING_FILE
            and not _inside_dev_reset(path, number)
            and not _forbids(line)
        ]

        assert offenders == [], (
            "these lines mention `docker compose down -v` without forbidding it, and it is scoped "
            f"to the PROJECT rather than to a service: {offenders}"
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
        (tmp_path / "innocent.md").write_text(
            "Never run `docker compose down -v` here.\n", encoding="utf-8"
        )
        (tmp_path / "an-image.png").write_bytes(b"\x89PNG\r\n\x1a\n\xff down -v")

        found = _lines_mentioning("down -v", root=tmp_path)
        offenders = {path for path, _, line in found if not _forbids(line)}

        assert offenders == set(TheDestructiveTeardown.PLANTED), (
            "the walk reads every text file type, and only the ones that instruct it are offenders"
        )
        assert "an-image.png" not in {path for path, _, _ in found}, "a binary file is not read"

    @pytest.mark.parametrize(
        "line",
        [
            "Nothing else clears it: run `docker compose down -v` on the host.",
            "Note: run `docker compose down -v` to reset the stack.",
            "You cannot skip this. Run `docker compose down -v`.",
            "Another option is `docker compose down -v`.",
            "Notice the volume: `docker compose down -v`.",
        ],
    )
    def test_a_word_that_merely_contains_not_does_not_exempt_a_line(self, line: str) -> None:
        """All five were exempted by the substring test, and `Note:` begins a runbook line."""
        assert not _forbids(line), line

    @pytest.mark.parametrize(
        "line",
        [
            "Never `docker compose down -v`: it is scoped to the project.",
            "Do not run `docker compose down -v` here.",
            "`down -v` is not safe against this project.",
            "You must not use `docker compose down -v` on the host.",
        ],
    )
    def test_an_explicit_negation_exempts_a_line(self, line: str) -> None:
        """The other direction: every occurrence in the tree today is one of these shapes."""
        assert _forbids(line), line

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
        """The ignore list is a hand-written set, so it is crossed against git's own answer.

        Reading every text file pulled in `.pytest_cache/v/cache/nodeids`, which holds this module's
        parametrized test ids and so the five lines that instruct the command: a guard failing on
        its own negative controls. Rather than patch the list and hope, this asks git which paths
        are ignored and requires the walk to have read none of them.
        """
        read_paths = sorted({path for path, _, _ in _lines_mentioning("docker")})
        assert read_paths, "the walk read nothing, so this asserts nothing"

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
            f"the walk read paths git ignores, which are generated rather than the tree: "
            f"{ignored.stdout.strip().splitlines()}"
        )

    def test_nothing_the_walk_skips_is_a_tracked_file(self) -> None:
        """THE OTHER DIRECTION, and it caught two entries.

        The test above only checks that what the walk READ is not ignored. That leaves the list free
        to grow an entry naming a TRACKED file, which narrows the reading below the rule and is the
        exact defect this class exists to prevent: the first version of `_NOT_SOURCE` grew `uv.lock`
        and `package-lock.json`, both tracked, on the way to fixing something else.
        """
        tracked = subprocess.run(  # noqa: S603 - a literal argv over a module constant, no shell
            # `git` from the PATH the developer and CI both have, like every other call here.
            ["git", "ls-files", "--", *_NOT_SOURCE],  # noqa: S607
            cwd=repo_root(),
            capture_output=True,
            text=True,
            check=False,
        )

        assert tracked.stdout.strip() == "", (
            f"the walk skips tracked files, so the rule is stated over less than the tree: "
            f"{tracked.stdout.strip().splitlines()}"
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


def _forbids(line: str) -> bool:
    """Whether this line mentions the command while forbidding it.

    Whole phrases, because the first version tested for the substring `not`, and five ordinary
    English words contain it.
    """
    lowered = line.lower()
    return any(phrase in lowered for phrase in TheDestructiveTeardown.FORBIDDING)


def _lines_mentioning(fragment: str, *, root: Path | None = None) -> list[tuple[str, int, str]]:
    """Every line of every TEXT file in the tree that names ``fragment``.

    Every text file, not a list of suffixes. The first version read five suffixes and one filename,
    which made systemd units invisible: the one operational file type where a scheduled teardown
    would live. A file is text if it decodes as UTF-8, which is the question this reading has to ask
    anyway, so a PNG or a compiled artefact is skipped by the read rather than by a list.
    """
    walking = root if root is not None else repo_root()
    found: list[tuple[str, int, str]] = []
    for path in sorted(walking.rglob("*")):
        if not path.is_file() or _ignored(path.relative_to(walking)):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(content.splitlines(), start=1):
            if fragment in line:
                found.append((str(path.relative_to(walking)), number, line))
    return found


# What a walk of a working tree must not enter or read: build output, another project's dependency
# tree, this repository's own history, and the test caches. EVERY ENTRY IS SOMETHING GIT IGNORES,
# which `test_the_walk_reads_nothing_git_ignores` asserts rather than trusts, so this list cannot
# quietly grow to exclude a tracked file the rule covers.
#
# Broadening the reading to every text file made it read `.pytest_cache/v/cache/nodeids`, which
# holds this module's own parametrized test ids, and so the five lines that instruct the command.
_NOT_SOURCE = (
    ".git",
    ".venv",
    "node_modules",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".hypothesis",
    "__pycache__",
    "htmlcov",
    "dist",
    "coverage",
)


def _ignored(relative: Path) -> bool:
    return any(part in _NOT_SOURCE for part in relative.parts)


def _inside_dev_reset(path: str, number: int) -> bool:
    """Whether this line is inside the one recipe allowed to destroy volumes."""
    if path != "justfile":
        return False
    lines = read(Path("justfile")).splitlines()
    opener = next(
        (
            index
            for index, line in enumerate(lines, start=1)
            if line.startswith(f"{TheDestructiveTeardown.ALLOWED_RECIPE}:")
        ),
        None,
    )
    if opener is None:  # pragma: no cover - the recipe exists, and its absence fails elsewhere
        return False
    for index in range(opener + 1, len(lines) + 1):
        if index == number:
            return True
        if lines[index - 1] and not lines[index - 1].startswith((" ", "\t")):
            return False
    return False


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
    """Every key `.env.example` declares, which is what sourcing the host secret file provides."""
    import re

    text = read(Path(".env.example"))
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=", text, re.MULTILINE))


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
