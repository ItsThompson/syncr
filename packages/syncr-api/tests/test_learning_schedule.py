"""The nightly learning run's schedule, read as one chain rather than as four declarations.

A timer that exists in a unit file is not a run. Six links have to agree for 03:00 to produce
something an operator could be alerted about, and each of them lives in a different file:

    the timer's calendar
      -> the service that timer starts
      -> the `just` recipe that service runs
      -> the container that recipe starts, under the profile that keeps it off `docker compose up`
      -> the directory that container writes its exposition into
      -> the window the alert reads that exposition over

Every link below is crossed against the next one, so no link can move alone. The declarations
themselves are asserted next door: `test_deployment_figures.py` crosses the hour against
`ops.config.NIGHTLY_HOUR` and holds `Persistent=true`, and `test_deploy_topology.py` bounds the
resolved stack. What is here is the joins between them.

`TEXTFILE_COLLECTOR_DIR` is load-bearing rather than incidental: a container that has exited cannot
be scraped, and the job writes no exposition at all when that setting is empty, which is its
default. So the directory in the container's environment is the whole surface the run is visible on.

WHETHER THE TIMER FIRES IS A PROPERTY OF A HOST and nothing in this module claims it. The schedule
is readable here; the run is not. `systemctl list-timers syncr-learning` on the deployed host is
what settles that, and its `LAST` column is the reading.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import pytest
from ops.config import TEXTFILE_DIR

from tests.test_alert_rules import comparison_on, named
from tests.test_deploy_topology import DEPLOYED_FILES, resolved, services
from tests.test_deployment_figures import SYSTEMD, directives, read

if TYPE_CHECKING:
    from collections.abc import Mapping

TIMER: Final = SYSTEMD / "syncr-learning.timer"
UNIT: Final = SYSTEMD / "syncr-learning.service"

# The one name in this chain that is a literal rather than a reading, and it is crossed in three
# directions: the unit's `ExecStart` invokes it, the justfile declares it, and its body starts the
# container below. A rename that misses any of the three fails here.
NIGHTLY_RECIPE: Final = "learn-once"
CONTAINER: Final = "learning"

ALERT: Final = "LearningJobFailed"
RUN_FAMILY: Final = "syncr_learning_run_duration_seconds"

# Every directive systemd will start a unit on. All of them, because a second one beside
# `OnCalendar=` is a schedule with two periods, and reading the first and ignoring the rest is how a
# reading answers a question the file does not.
_TIMING: Final = (
    "OnActiveSec",
    "OnBootSec",
    "OnCalendar",
    "OnClockChange",
    "OnStartupSec",
    "OnTimezoneChange",
    "OnUnitActiveSec",
    "OnUnitInactiveSec",
)

# `*-*-* HH:MM:SS` and nothing else. A weekday prefix, a repetition suffix or a named shorthand all
# denote schedules this reading cannot reduce to a period, and each has to fail rather than be
# rounded to a day.
_DAILY: Final = re.compile(r"^OnCalendar=\*-\*-\* \d{2}:\d{2}:\d{2}$")

_PROMQL_DURATION: Final = re.compile(r"^(?P<count>\d+)(?P<unit>[smhdw])$")
_SECONDS_PER: Final[Mapping[str, int]] = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}

_DAY_SECONDS: Final = 24 * 3600


def timer_period_seconds(stated: str) -> int:
    """How often a timer starts its service, read from the timer's own directives.

    Only the every-day-at-a-time calendar is reduced to a period. Everything else fails, including
    the shapes a substring reading admits: `OnCalendar=*-*-* 03:00:00/6h` contains the daily
    spelling and fires four times a night, and a monotonic `OnUnitActiveSec=` carries no calendar at
    all. A reading that answered one day whatever the file said would be a guard that cannot fail.
    """
    timings = [line for line in stated.splitlines() if line.partition("=")[0] in _TIMING]

    assert len(timings) == 1, f"{timings} is not one schedule, so no single period follows from it"
    assert _DAILY.match(timings[0]), (
        f"{timings[0]!r} is not the every-day-at-a-time shape this reading can turn into a period"
    )
    return _DAY_SECONDS


def promql_seconds(duration: str) -> int:
    """A Prometheus duration in seconds, or a failure naming the spelling it could not read."""
    found = _PROMQL_DURATION.match(duration)

    assert found is not None, f"{duration!r} is not a duration this reading covers"
    return int(found.group("count")) * _SECONDS_PER[found.group("unit")]


def recipe_body(name: str) -> str:
    """The commands one justfile recipe runs: its indented block, with its comments removed.

    Comments go for the reason `directives` removes them from a unit: this recipe's own comment
    names the container and the alert, so a reading over the whole block would find every string
    below in prose and cross nothing. The shebang goes with them, and nothing here reads it.
    """
    lines = read(Path("justfile")).splitlines()
    opened = next(
        (
            position
            for position, line in enumerate(lines)
            if re.match(rf"^{re.escape(name)}(?:\s|:)", line)
        ),
        None,
    )
    assert opened is not None, f"the justfile declares no `{name}` recipe"

    body: list[str] = []
    for line in lines[opened + 1 :]:
        if line.strip() and not line.startswith((" ", "\t")):
            break
        if not line.strip().startswith("#"):
            body.append(line)

    assert any(line.strip() for line in body), f"`{name}` runs nothing"
    return "\n".join(body)


def nightly_invocation() -> tuple[str, ...]:
    """The one `docker compose` command the nightly recipe issues, as its own words."""
    issued = [line for line in recipe_body(NIGHTLY_RECIPE).splitlines() if "docker compose" in line]

    assert len(issued) == 1, f"`{NIGHTLY_RECIPE}` issues {len(issued)} compose commands, not one"
    return tuple(issued[0].split())


def recipe_the_unit_runs(unit: Path) -> str:
    """The `just` recipe a unit's `ExecStart` invokes, in either shape it may name `just` in.

    An absolute path and `/usr/bin/env just` are both valid, and which one is correct is settled
    against the deploy runbook next door. This reads the recipe out of either.
    """
    (started,) = [line for line in directives(unit).splitlines() if line.startswith("ExecStart=")]
    words = started.partition("=")[2].split()

    if Path(words[0]).name == "just":
        arguments = words[1:]
    else:
        assert Path(words[1]).name == "just", started
        arguments = words[2:]

    assert arguments, f"{unit.name} runs `just` with no recipe"
    return arguments[0]


def profile_the_recipe_enables() -> str:
    """The one compose profile the nightly recipe turns on."""
    words = nightly_invocation()
    enabled = [words[position + 1] for position, word in enumerate(words) if word == "--profile"]

    assert len(enabled) == 1, f"`{NIGHTLY_RECIPE}` enables {enabled}, and the gate is one profile"
    return enabled[0]


@pytest.fixture(scope="module")
def deployed() -> dict[str, Any]:
    return resolved(*DEPLOYED_FILES)


class TestTheTimerDeclaresOneDailySchedule:
    """A period, computed from the calendar rather than recognised as a string."""

    def test_the_timer_fires_once_a_day(self) -> None:
        assert timer_period_seconds(directives(TIMER)) == _DAY_SECONDS

    @pytest.mark.parametrize(
        "stated",
        [
            "OnCalendar=Mon *-*-* 03:00:00",
            "OnCalendar=*-*-* 03:00:00/6h",
            "OnCalendar=daily",
            "OnUnitActiveSec=60s",
            "OnCalendar=*-*-* 03:00:00\nOnBootSec=15min",
            "",
        ],
    )
    def test_the_reading_refuses_a_schedule_it_cannot_reduce_to_a_period(self, stated: str) -> None:
        """The control that matters, because two of these pass a substring reading.

        `03:00:00/6h` and a second timing directive beside the calendar both contain the daily
        spelling, and both are different schedules. A reader that saw the substring and returned a
        day would certify a timer firing four times a night.
        """
        with pytest.raises(AssertionError):
            timer_period_seconds(stated)


class TestTheAlertReadsTheWindowTheTimerFiresOn:
    """The schedule and the window it is watched over, so neither can move without the other."""

    def test_the_lookback_is_exactly_one_firing_period(self) -> None:
        """Shorter and a healthy deployment reads as a job that never ran; longer and a failed
        night stays visible past the run that replaced it."""
        window = comparison_on(named(ALERT), RUN_FAMILY).window

        assert promql_seconds(window) == timer_period_seconds(directives(TIMER))

    def test_the_pending_window_is_shorter_than_the_window_the_evidence_lives_in(self) -> None:
        """A rule pending as long as its own lookback cannot fire: the condition ages out of the
        window exactly as the pending period elapses, and the rule is decoration.

        Bounded against the timer as well as the lookback, so one test names both ends the schedule
        and the pending window can drift apart at. The two bounds are the same number today, because
        the test above pins the lookback to the period, and they are asserted separately because a
        `for` equal to the period is the defect rather than the intent.
        """
        rule = named(ALERT)
        lookback = promql_seconds(comparison_on(rule, RUN_FAMILY).window)
        pending = promql_seconds(rule.holds_for)

        assert 0 < pending < lookback
        assert pending < timer_period_seconds(directives(TIMER))

    def test_the_reading_finds_both_ends_it_crosses(self) -> None:
        """The positive control: an empty window on either side would make the crossing vacuous."""
        assert comparison_on(named(ALERT), RUN_FAMILY).window
        assert named(ALERT).holds_for


class TestTheUnitRunsTheRecipeThatStartsTheContainer:
    """Three files naming one run, crossed rather than each read on its own."""

    def test_the_unit_runs_the_nightly_recipe(self) -> None:
        assert recipe_the_unit_runs(UNIT) == NIGHTLY_RECIPE

    def test_the_recipe_starts_the_container_and_does_not_leave_it_behind(self) -> None:
        """`run --rm`: a one-shot accumulating a stopped container a night would fill the host."""
        words = nightly_invocation()

        assert "run" in words, words
        assert "--rm" in words, words
        assert words.index("run") < words.index(CONTAINER), words

    def test_the_recipe_runs_the_container_rather_than_starting_the_stack(self) -> None:
        """`up` would start every service the profile does not gate, at 03:00, unattended."""
        assert "up" not in nightly_invocation()


class TestTheContainerTheRecipeStarts:
    """What the compose configuration says the recipe gets, resolved rather than read off a file."""

    pytestmark = pytest.mark.skipif(
        shutil.which("docker") is None,
        reason="the resolved Compose configuration needs the docker CLI",
    )

    def test_it_is_gated_behind_exactly_the_profile_the_recipe_enables(
        self, deployed: dict[str, Any]
    ) -> None:
        """An exact equality in both directions. A profile renamed on one side leaves the timer
        running a container nothing gates, and a second profile added silently widens the gate."""
        gated = set(services(deployed)[CONTAINER]["profiles"])

        assert gated == {profile_the_recipe_enables()}

    def test_it_is_told_the_directory_the_collector_reads(self, deployed: dict[str, Any]) -> None:
        """One directory named in three files: the job's environment, the exporter's flag, and the
        constant the backup one-shot writes its own two families with."""
        told = services(deployed)[CONTAINER]["environment"]["TEXTFILE_COLLECTOR_DIR"]

        assert told == TEXTFILE_DIR
        assert (
            f"--collector.textfile.directory={told}"
            in services(deployed)["node_exporter"]["command"]
        )

    def test_the_job_and_the_exporter_mount_one_volume_at_that_directory(
        self, deployed: dict[str, Any]
    ) -> None:
        """Two containers agreeing on a path inside two different volumes would write and read
        different files, and the alert would never see a run."""
        mounted = {
            name: {
                mount["source"]
                for mount in services(deployed)[name]["volumes"]
                if mount["target"] == TEXTFILE_DIR
            }
            for name in (CONTAINER, "node_exporter")
        }

        assert mounted[CONTAINER], f"{CONTAINER} mounts nothing at {TEXTFILE_DIR}"
        assert mounted[CONTAINER] == mounted["node_exporter"]
