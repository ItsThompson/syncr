"""The figures the two operation runbooks quote, crossed against the code that decides them.

A runbook is read once, under pressure, by someone deciding whether to intervene. One whose numbers
have drifted from the deployment is worse than none: it will be trusted, and it will be wrong. So
every figure these two quote is asserted against the constant that produces it, rather than against
a second copy of the number here.

The prose claims are asserted too, and each is one the ticket requires the runbook to make. They are
matched as substrings rather than by structure, because what has to survive is the STATEMENT: an
operator searching the file for "lease" has to find what the lease is.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest

from syncr_api.solving.config import (
    FAILED_RETENTION,
    LEASE,
    LEASE_EXPIRED,
    MAX_ATTEMPTS,
    RETRY_BACKOFF,
    SUCCEEDED_RETENTION,
)
from syncr_api.solving.maintenance import MAINTENANCE_INTERVAL

if TYPE_CHECKING:
    from datetime import timedelta

RUNBOOKS: Final = Path(__file__).resolve().parents[3] / "docs" / "runbooks"

STUCK_OPERATION = RUNBOOKS / "stuck-operation.md"
SOLVE_FAILING = RUNBOOKS / "solve-failing.md"


def read(runbook: Path) -> str:
    assert runbook.is_file(), f"{runbook} does not exist"
    return runbook.read_text(encoding="utf-8")


def minutes(value: timedelta) -> int:
    return int(value.total_seconds() // 60)


def days(value: timedelta) -> int:
    return value.days


@pytest.mark.parametrize("runbook", [STUCK_OPERATION, SOLVE_FAILING], ids=lambda one: one.name)
def test_the_runbook_exists_and_states_a_trigger(runbook: Path) -> None:
    """Every runbook opens with what made the reader come here, per the deployment section."""
    assert "## Trigger" in read(runbook)


@pytest.mark.parametrize("runbook", [STUCK_OPERATION, SOLVE_FAILING], ids=lambda one: one.name)
def test_the_runbook_names_the_capability_that_survives(runbook: Path) -> None:
    """The same rule the in-product degradation notices follow: say what still works."""
    assert "still projected" in read(runbook)


class TestTheStuckOperationRunbook:
    def test_it_states_what_the_reaper_does(self) -> None:
        text = read(STUCK_OPERATION)

        assert "## What the reaper does" in text
        assert LEASE_EXPIRED in text

    def test_it_states_how_to_force_it(self) -> None:
        text = read(STUCK_OPERATION)

        assert "## How to force it" in text
        assert "OperationMaintenance" in text, "the sweep an operator runs has to be named"

    def test_it_quotes_the_lease_the_code_uses(self) -> None:
        assert f"**{minutes(LEASE)} minutes**" in read(STUCK_OPERATION)

    def test_it_quotes_the_sweep_interval_the_loop_uses(self) -> None:
        assert f"**every {minutes(MAINTENANCE_INTERVAL)} minutes**" in read(STUCK_OPERATION)

    def test_it_quotes_the_attempt_bound(self) -> None:
        assert f"**{MAX_ATTEMPTS} attempts**" in read(STUCK_OPERATION)

    def test_it_quotes_both_retention_windows(self) -> None:
        text = read(STUCK_OPERATION)

        assert f"**{days(FAILED_RETENTION)} days**" in text
        assert f"**{days(SUCCEEDED_RETENTION)} days**" in text

    def test_it_states_that_nothing_else_is_pruned(self) -> None:
        assert "prunes nothing else" in read(STUCK_OPERATION)


class TestTheSolveFailingRunbook:
    def test_it_names_the_snapshot_as_the_reproduction_mechanism(self) -> None:
        text = read(SOLVE_FAILING)

        assert "failed_input_snapshot" in text
        assert "load the snapshot and call the solver" in text

    def test_it_states_why_the_input_version_cannot_do_that_job(self) -> None:
        """A counter, not a snapshot: re-assembling yields current state rather than what failed."""
        text = read(SOLVE_FAILING)

        assert "`input_version` is a **counter**" in text
        assert "not the state that failed" in text

    def test_it_states_that_supersession_is_not_this_alert(self) -> None:
        """Presenting a displaced solve as a failure sends an operator diagnosing normal use."""
        assert "**Not an error.**" in read(SOLVE_FAILING)

    def test_it_quotes_the_retry_rules_the_code_uses(self) -> None:
        text = read(SOLVE_FAILING)

        assert f"| Attempts before a failure is terminal | {MAX_ATTEMPTS} |" in text
        assert f"| Backoff between attempts | {int(RETRY_BACKOFF.total_seconds())} seconds" in text

    def test_it_quotes_both_retention_windows(self) -> None:
        text = read(SOLVE_FAILING)

        assert f"{days(FAILED_RETENTION)} days" in text
        assert f"{days(SUCCEEDED_RETENTION)} days" in text

    def test_it_states_the_fallback_for_a_week_with_no_plan(self) -> None:
        """The horizon is never left with a hole: materialization's second permanent job."""
        assert "the horizon is never left with a hole" in read(SOLVE_FAILING)

    def test_it_does_not_claim_the_reproduction_runs_today(self) -> None:
        """The callout is the sentence a reader under pressure trusts, so it must not overclaim.

        It claimed the procedure was "complete" while its own "Still to be written" listed the first
        step. An operator following it reached a script that prints ``null`` with no explanation.
        """
        text = read(SOLVE_FAILING)

        assert "reproduction's FIRST step is unwritten" in text
        assert "nothing writes a snapshot yet" in text.lower()
        assert "reproduction procedure is complete" not in text

    def test_it_warns_where_the_null_snapshot_will_be_met(self) -> None:
        """Beside the script that prints it, not only in the callout at the top."""
        _before, _, after = read(SOLVE_FAILING).partition("### Read the snapshot")

        assert "expected rather than a lost snapshot" in after.split("###")[0]
