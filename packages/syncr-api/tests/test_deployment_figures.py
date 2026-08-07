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

from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest
from ops.config import (
    ARCHIVE_TIMEOUT_SECONDS,
    BACKUP_METRIC,
    BACKUP_STALE_AFTER_SECONDS,
    DAILY_COPIES,
    MONTHLY_COPIES,
    NIGHTLY_HOUR,
    RECOVERY_POINT_OBJECTIVE_SECONDS,
    RECOVERY_TIME_OBJECTIVE_SECONDS,
    SHIP_INTERVAL_SECONDS,
    WAL_METRIC,
    WAL_STALE_AFTER_SECONDS,
    WEEKLY_COPIES,
)

from tests.test_alert_rules import named as alert_named
from tests.test_alert_rules import repo_root

if TYPE_CHECKING:
    from collections.abc import Iterable

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
        content = read(SYSTEMD / unit)

        assert "ExecStart=/usr/bin/just " in content
        assert "Type=oneshot" in content

    @pytest.mark.parametrize(
        "unit", ["syncr-backup.service", "syncr-walship.service", "syncr-learning.service"]
    )
    def test_each_unit_composes_the_digest_pins(self, unit: str) -> None:
        """Or the nightly job runs whatever is tagged on the host rather than the reviewed image."""
        assert "docker-compose.deploy.yml" in read(SYSTEMD / unit)

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
