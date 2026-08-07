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
from typing import TYPE_CHECKING, Final, cast

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
from ops.process import Result
from ops.restore import RestoreRefused, require_empty

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


def _every_runbook() -> tuple[str, ...]:
    """Every runbook in the directory, which is the set a rule about runbooks has to be stated over.

    Section 21 names eleven and this deployment has sixteen: the alert-named ones ticket 54 wrote
    are runbooks too, and one of them is the file this ticket rewrote.
    """
    return tuple(sorted(path.name for path in (repo_root() / RUNBOOKS).glob("*.md")))


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
    """

    # The one recipe allowed to run it. Its name says what it does, and it names the dev stack's own
    # compose files, which is a different project from the deployed one.
    ALLOWED_RECIPE = "dev-reset"

    # A line that mentions it while forbidding it. Both words are ordinary English and neither can
    # be written by accident on a line that instructs the command.
    FORBIDDING = ("never", "not")

    # The one file allowed to quote the forbidden instruction without forbidding it: this one, which
    # cannot state the rule without naming the string. Declared rather than pattern-matched, so a
    # second file claiming the same exemption fails.
    DECLARING_FILE = "packages/syncr-api/tests/test_deployment_figures.py"


class TestTheDestructiveTeardown:
    def test_nothing_instructs_it_outside_the_recipe_that_owns_it(self) -> None:
        offenders = [
            f"{path}:{number}: {line.strip()}"
            for path, number, line in _lines_mentioning("down -v")
            if path != TheDestructiveTeardown.DECLARING_FILE
            and not _inside_dev_reset(path, number)
            and not any(word in line.lower() for word in TheDestructiveTeardown.FORBIDDING)
        ]

        assert offenders == [], (
            "these lines mention `docker compose down -v` without forbidding it, and it is scoped "
            f"to the PROJECT rather than to a service: {offenders}"
        )

    def test_the_reading_sees_the_line_that_shipped(self, tmp_path: Path) -> None:
        """The positive control, over the WALK, with the exact line a reviewer found on a terminal.

        Driven against a tree of its own rather than against the repository, because the rule's
        whole point is that a NEW file cannot reintroduce the instruction, and a control that could
        not see one in a file this suite does not already know about would prove nothing.
        """
        shipped = (
            "`just restore-drill` does that with `docker compose down -v` on the scratch instance."
        )
        (tmp_path / "invented.py").write_text(f'raise Refused("{shipped}")\n', encoding="utf-8")
        (tmp_path / "innocent.md").write_text(
            "Never run `docker compose down -v` here.\n", encoding="utf-8"
        )

        found = _lines_mentioning("down -v", root=tmp_path)
        offenders = [
            path
            for path, _, line in found
            if not any(word in line.lower() for word in TheDestructiveTeardown.FORBIDDING)
        ]

        assert len(found) == 2, "the walk reads both file types"
        assert offenders == ["invented.py"], "and only the one that instructs it is an offender"

    def test_the_reading_covers_more_than_one_file_type(self) -> None:
        """A guard over one extension would have missed this one, which lived in a `.py`."""
        suffixes = {
            Path(path).suffix or Path(path).name for path, _, _ in _lines_mentioning("down -v")
        }

        assert len(suffixes) >= 2, suffixes

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


def _lines_mentioning(fragment: str, *, root: Path | None = None) -> list[tuple[str, int, str]]:
    """Every line of every source, document, recipe and Compose file that names ``fragment``.

    The tree is walked rather than a list of files read, because the point of the rule is that a NEW
    file cannot reintroduce the instruction.
    """
    walking = root if root is not None else repo_root()
    found: list[tuple[str, int, str]] = []
    for path in sorted(walking.rglob("*")):
        if not path.is_file() or _ignored(path.relative_to(walking)):
            continue
        if path.suffix not in {".py", ".md", ".yml", ".yaml", ".sh"} and path.name != "justfile":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if fragment in line:
                found.append((str(path.relative_to(walking)), number, line))
    return found


# Directories a walk of a working tree must not enter: two are build output, one is another
# project's dependency tree, and one is this repository's own history.
_NOT_SOURCE = (".git", ".venv", "node_modules", ".mypy_cache", ".ruff_cache", "__pycache__", "dist")


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
